# Based on https://github.com/LumaPictures/pflow/blob/master/pflow/packet.py

import os as _os

import shutil

import tempfile



class InformationPacket(object):
    def __init__(self, value, owner=None):
        self._value = value
        self._owner = owner

    def drop(self):
        del self

    def __str__(self):
        return "{} owned by {}, path {}, value {}".format(self.__repr__(), self.owner, self.path, self.value)

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        raise ValueError('Cannot set value, copy packet and set its value')

    @property
    def owner(self):
        return self._owner

    @owner.setter
    def owner(self, value):
        if self._owner is not None:
            raise ValueError('Packet is owned by {}, Cannot set owner, copy packet with new owner'.format(self.owner))
        else:
            self._owner = value

    @property
    def is_eos(self):
        return False

    @property
    def exists(self):
        return True

    @property
    def path(self):
        return self.value

    @property
    def basename(self):
        if self.path:
            return _os.path.basename(self.path)
        else:
            return None

    @property
    def is_file(self):
        return False

    def open(self):
        pass

    def copy(self):
        return InformationPacket(self.value, owner=None)



class EndOfStream(InformationPacket):
    """
    End of stream packet, to signal end of computation
    """
    def __init__(self):
        super(EndOfStream, self).__init__(None)

    @property
    def is_eos(self):
        return True

    def __str__(self):
        return "EOS"


class Bracket(InformationPacket):
    """
    This is a bracket IP, composed of a list of IPs
    """

    def __init__(self, owner=None):
        super(Bracket, self).__init__(value=None, owner=owner)

    # def __getitem__(self, item):
    #     return self.value.__getitem__(item)
    #
    # def __add__(self, other):
    #     self._value.__add__(other)
    #
    # def append(self, other):
    #     other_packet = InformationPacket(other, owner=self)
    #     self._value.append(other_packet)
    #
    # def append_packet(self, packet):
    #     self._value.append(packet)
    #
    # def __len__(self):
    #     return self.value.__len__()
    #
    # def __str__(self):
    #     st = "{} owned by {}, length {}, value {}".format(self.__repr__(), self.owner, self.__len__(), self._value)
    #     return st
    #
    # def __iter__(self):
    #     return self.value.__iter__()


class OpenBracket(InformationPacket):

    def __init__(self, owner=None):
        super(OpenBracket, self).__init__(value=None, owner=owner)


class CloseBracket(InformationPacket):
    def __init__(self, owner=None):
        super(CloseBracket, self).__init__(value=None, owner=owner)

