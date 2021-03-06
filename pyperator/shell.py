import asyncio
import collections.abc as _collabc
import hashlib as _hl
import os
import pathlib as _path
import shutil
import subprocess as _sub
import tempfile as _temp
import re as _re


from pyperator import IP
from pyperator.decorators import log_schedule
from pyperator.exceptions import FormatterError, FileNotExistingError, CommandFailedError
from pyperator.nodes import Component
from pyperator.utils import Wildcards, InputPort,OutputPort

import itertools as _iter

port_pattern = _re.compile(r"\{(?P<type>inputs|outputs|params)\.(?P<port_name>\w+)(\.\w+)*\}")

def parse_command(cmd):
    """
    Parses a command and returns
    a dictionary of {register_name:(port_names)}
    :param cmd: 
    :return: 
    """
    new_ports = {'inputs':set(), 'params':set(), 'outputs':set()}
    for line in cmd.splitlines():
        matches = port_pattern.finditer(line)
        for match in matches:
            if match.group('type') in new_ports:
                new_ports[match.group('type')].add(match.group('port_name'))
    return new_ports




def unique_filename(inputs, wildcards):
    """
    Generates an unique outputs filename
    by hashing inputs values.
    :param outport: 
    :param inputs: 
    :param wildcards: 
    :return: 
    """
    unique_if = ("".join([str(v) for p, v in inputs.items()])).encode('utf-8')
    return str(_hl.md5(unique_if).hexdigest())


def dynamic_filename(inputs, wildcards, pattern):
    """
    Generate a filename dynamically by 
    formatting a pattern with
    input values and wildcards
    :param inputs: 
    :param wildcards: 
    :param pattern: 
    :return: 
    """
    return pattern.format(inputs=inputs, wildcards=wildcards)


def make_call(cmd, stderr, stdout):
    proc = _sub.Popen(cmd, shell=True, stdout=stdout, stderr=stderr)
    return proc


def make_async_call(cmd, stderr, stdout):
    return asyncio.create_subprocess_shell(cmd, stdout=stdout, stderr=stderr)


def normalize_path_to_workdir(path, workdir):
    """
    Normalizes a path and returns an output path relative
    to the current workdir
    :param path: 
    :param workdir: 
    :return: 
    """
    # Find the common prefix
    return os.path.normpath(workdir + os.path.basename(path))


def check_missing(path, workdir):
    return not os.path.exists(normalize_path_to_workdir(path, workdir))

def check_older(ancestor, current):
    try:
        return os.path.getmtime(current) < os.path.getmtime(ancestor)
    #If it is not a file, we return false
    except FileNotFoundError:
        return False
    except OSError:
        return False


def list_missing(out_packets, workdir):
    return {port: packet for port, packet in out_packets.items() if
            check_missing(str(packet), workdir)}

def list_modified(out_packets, in_packets):
    new_ancestors = set()
    to_redo = {}
    for (out_port, out_packet), (in_port, in_packet) in _iter.product(out_packets.items(), in_packets.items()):
        if check_older(str(in_packet), str(out_packet)):
            new_ancestors.add(in_packet)
            to_redo[out_port] = out_packet
    return new_ancestors, to_redo



class PacketRegister(_collabc.Mapping):
    """
    This class is used to represent a collection of
    packets received from a number of ports, so that
    in a shell command, we can use {inputs.port.packet_attribute} to
    access a certain attribute belonging to a packet received from port `port`
    """

    def __init__(self, packets):
        self._packets = {k: v for k, v in packets.items()}
        self._temp_packets = {}

    def copy_temp(self):
        """
        Create a temporary copy of
        each input and output
        packet and returns a copied :class:`PacketRegister`.
        Each packet that behaves in a "path-like"
        manner will receive a new tempfile attached.
        
        :return: 
        """
        # Create temporary file
        paths = {}
        for k, v in self._packets.items():
            paths[k] = IP.InformationPacket(_path.Path(_temp.NamedTemporaryFile(delete=True).name))
        self._temp_packets = PacketRegister(paths)
        return self._temp_packets

    def finalize_temp(self):
        """
        This is used to copy the temporary files
        to the final destination
        :return: 
        """
        for (k_temp, v_temp), (k_final, v_final) in zip(self._temp_packets.items(), self.items()):
            if not os.path.exists(str(v_final)):
                shutil.copy(str(v_temp), str(v_final))

    def __getitem__(self, item):
        if item in self._packets:
            return self._packets[item].value
        else:
            pass

    def get_packet(self, item):
        return self._packets.get(item)

    def as_dict(self):
        return self._packets

    def __getattr__(self, item):
        return self.__getitem__(item)

    def __iter__(self):
        return self._packets.__iter__()

    def __len__(self):
        return len(self._packets)

    def __str__(self):
        return self._packets.__str__()

    # Context manager: creates temporary files
    def __enter__(self):
        return self.copy_temp()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val:
            print(exc_val)
            for name, packet in self._temp_packets.items():
                del packet
            raise (exc_val)
        else:
            self.finalize_temp()


class FileOperator(Component):
    """
    This component operates on files, it supports
    wilcard expressions and output file formatters based on
    input files, i.e extracting part of the paths to generate output paths.
    To subclass it, you need to implement the function
    `produce_outputs` that generates the output packets, the component
    will automatically check wether the files that it produces exists, in order
    to avoid rerunning the command again.
    If check_older=True, the modification date of files
    are compared and things are redone whenever an input file is
    newer than any existing output.
    """

    def __init__(self, name, check_older=False):
        super(FileOperator, self).__init__(name)
        self.output_formatters = {}
        # Input ports may have wildcard expressions attached
        self.wildcard_expressions = {}
        self.check_older = check_older


    def FixedFormatter(self, port, path):
        """
        Formats the ouput port with a fixed

        """
        self.output_formatters[port] = lambda inputs, wildcards: path

    def DynamicFormatter(self, outport, pattern):
        formatter = lambda inputs, wildcards: dynamic_filename(inputs, wildcards, pattern)
        self.output_formatters[outport] = formatter
        return formatter

    def UniqueFormatter(self, outport):
        formatter = lambda inputs, wildcards: unique_filename(inputs, wildcards)
        self.output_formatters[outport] = formatter
        return formatter

    def WildcardsExpression(self, inport, pattern):
        self.wildcard_expressions[inport] = Wildcards(pattern)

    def parse_wildcards(self, received_data):
        """
        This function parses the input packets
        to extract the wildcards, if any are defined.
        Returns a dict of wildcards objects
        which can be accessed as
        {portname.wildcards.wildcard_name}
        """
        wildcards_dict = {}
        for inport, inpacket in received_data.items():
            if inport in self.wildcard_expressions:
                wildcards_dict[inport] = self.wildcard_expressions[inport].parse(inpacket)
                self.log.debug("Port {}, with wildcard pattern {}, wildcards are {}".format(inport,
                                                                                            self.wildcard_expressions[
                                                                                                inport].pattern,
                                                                                            wildcards_dict[inport]))
        wildcards = type('wildcards', (object,), wildcards_dict)
        return wildcards

    def generate_output_paths(self, received_data):
        """
        This function generates the (dynamic) output and inputs
        paths using the inputs and the formatting functions.
        The output paths are always relative to the DAGs
        current workdir
        """
        inputs = PacketRegister(received_data)
        out_paths = {}
        wildcards = self.parse_wildcards(received_data)
        for out, out_port in self.outputs.items():
            try:
                current_formatter = self.output_formatters[out]
            except KeyError:
                current_formatter = self.UniqueFormatter(out)
                self.log.warn(
                    "Output port {} has no output formatter specified, will form an unique ID based on inputs".format(
                        out_port, out_paths[out]))
            try:
                out_paths[out] = normalize_path_to_workdir(current_formatter(inputs, wildcards), self.dag.workdir)
                self.log.debug(
                    "Output port {} will send file '{}'".format(out_port, out_paths[out]))
            except NameError as e:
                ex_text = 'Port {} does not have a path formatter specified'.format(out)
                self.log.error(ex_text)
                raise FormatterError(ex_text)
            except Exception as e:
                raise e
        return out_paths, wildcards

    def generate_packets(self, out_paths):
        out_packets = {}
        for port, path in out_paths.items():
            out_packets[port] = IP.InformationPacket(_path.Path(path), owner=None)
        return PacketRegister(out_packets)

    # def enumerate_newer(self, input_packets, output_packet):
    #     newer = {}
    #     for (out_port, out_packet), (inport, inpacket) in _iter.combinations(input_packets.items(), output_packet.items()):
    #         if _os.path.getmtime(out_packet.path) < _os.path.getmtime(inpacket.path):



    def produce_outputs(self, input_packets, output_packets, wildcards):
        pass

    @log_schedule
    async def __call__(self):
        while True:
            # Wait for all upstram to be completed
            received_packets = await self.receive_packets()
            # Generate output paths
            out_paths, wildcards = self.generate_output_paths(received_packets)
            out_packets = self.generate_packets(out_paths)
            # Check for missing packet
            missing = list_missing(out_packets, self.dag.workdir)
            #Check for modified ancestors
            if self.check_older:
                modified_ancestors, to_redo = list_modified(out_packets, PacketRegister(received_packets))
            else:
                to_redo = {}
            if missing or to_redo:
                self.log.warn("Output files '{}' do not exist not exist, command will be run".format(
                    [
                        packet
                        for
                        packet
                        in
                        missing.values()]))
                self.log.warn("Input files are older than output files '{}', the command will be run".format(
                    [
                        packet
                        for
                        packet
                        in
                        to_redo.values()]))
                inputs_obj = PacketRegister(received_packets)
                # Produce the outputs using the tempfile
                # context manager
                # with out_packets as temp_out:
                new_out = await self.produce_outputs(inputs_obj, out_packets, wildcards)

                # Check if the output files exist
                missing_after = list_missing(out_packets, self.dag.workdir)
                if missing_after:
                    missing_err = "Following files are missing {}, check the command".format(
                        [packet for packet in missing_after.values()])
                    self.log.error(missing_err)
                    raise FileNotExistingError(missing_err)

            else:
                self.log.debug("All output files exist, command will not be run")
                new_out = out_packets
            await asyncio.wait(self.send_packets(out_packets.as_dict()))
            await asyncio.sleep(0)


class Shell(FileOperator):
    """
    This component executes a shell script with inputs and outputs
    the command can contain normal ports and FilePorts
    for input and output
    """

    def __init__(self, name, cmd, **kwargs):
        super(Shell, self).__init__(name, **kwargs)
        self.cmd = cmd
        self.output_formatters = {}
        # Input ports may have wildcard expressions attached
        self.wildcard_expressions = {}
        #Add an additional "parameters" port register
        #Automatically add ports
        new_ports = parse_command(cmd)
        #Horribly stateful and based on side-effects, adds port
        #from the command
        [self.inputs.add(InputPort(name)) for name in new_ports['inputs']]
        [self.outputs.add(OutputPort(name)) for name in new_ports['outputs']]



    async def produce_outputs(self, input_packets, output_packets, wildcards):
        formatted_cmd = self.cmd.format(inputs=input_packets, outputs=output_packets, wildcards=wildcards)
        self.log.info("Executing command {}".format(formatted_cmd))
        # Define stdout and stderr pipes
        stdout = asyncio.subprocess.PIPE
        stderr = asyncio.subprocess.PIPE
        proc = await make_async_call(formatted_cmd, stderr, stdout)
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            fail_str = "running command '{}' failed with output: \n {}".format(formatted_cmd, stderr.strip())
            e = CommandFailedError(self, fail_str)
            self.log.error(e)
            raise e
        else:
            success_str = "Command successfully run, with output: {}".format(self.name, stdout)
            self.log.info(success_str)
            return output_packets


class ShellScript(Shell):
    """
    This component executes an external shell script, whose path
    is given in the constructor
    """

    def __init__(self, name, script, **kwargs):
        #read command
        with open(script) as input_script:
            cmd = input_script.read()
        #Produce command
        super(ShellScript, self).__init__(name, cmd, **kwargs)
        self.script = script
        self.log.info("Initialized to run script {}".format(self.name, script))
