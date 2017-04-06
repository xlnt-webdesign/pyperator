#Based on https://github.com/LumaPictures/pflow/blob/master/pflow/packet.py

import os as _os

import os.path as _path
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
            raise ValueError('Cannot set owner, copy packet with new owner')
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

class FilePacket(InformationPacket):

    def __init__(self, path, mode='r', owner=None):
        super(FilePacket, self).__init__(None, owner=owner)
        self._path = path
        self.mode = mode
        self.tempfile = tempfile.TemporaryFile()

    def open(self, mode='r'):
        if self.exists:
            return open(self.path, mode)
        else:
            return self.open_temp()

    def open_temp(self):
        return self.tempfile

    def finalize(self):
        shutil.copy(self.tempfile, self.path)

    def __str__(self):
        return "{} owned by {}, path {}, existing {}".format(self.__repr__(), self.owner, self.path, self.exists)

    @property
    def value(self):
        with self.open('r') as infile:
            return infile.readlines()

    @property
    def path(self):
        return self._path


    @property
    def exists(self):
        return _os.path.isfile(self.path)

    @property
    def is_file(self):
        return True



class EndOfStream(InformationPacket):

    def __init__(self):
        super(EndOfStream,self).__init__(None)

    @property
    def is_eos(self):
        return True

    def __str__(self):
        return "EOS"


class FileExistingError(BaseException):
    def __init__(self, *args, **kwargs):
        BaseException.__init__(self, *args, **kwargs)


class FileNotExistingError(BaseException):
    def __init__(self, *args, **kwargs):
        BaseException.__init__(self, *args, **kwargs)