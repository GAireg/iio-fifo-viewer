#!/bin/env python2
""" Handling iio fifo """
from __future__ import print_function

import os
import struct
import time
import glob
import sys
from datetime import datetime

SYSFS_BASEPATH = "/sys/bus/iio/devices/"
# the timestamp is 64 bit aligned
TIMESTAMP_ALIGNMENT=64/8

def match_file_content(filename, content):
    """Checks if the file at fil has the given conten"""
    with open(filename) as fil:
        return fil.read(len(content)) == content

def find_devnum(name):
    """ returns the number of an iio device with a given name """
    return [directory[-1:] for directory in os.listdir(SYSFS_BASEPATH) if directory[0] == "i" and
            match_file_content(os.path.join(SYSFS_BASEPATH, directory, "name"), name)]

def read_one_line(filename):
    """Returns the first line of the given file"""
    with open(filename) as fil:
        return fil.readline()

def type_to_unpack(typ):
    """Parses the scan element type and produces struct.unpack format string"""
    ret = ">" if typ[:2] == "be" else "<"
    valtyp = typ[typ.find(":")+1:typ.find("/")]
    inttypes = {
        "0": ("x", 0),
        "s8": ("b", 1),
        "u8": ("B", 1),
        "s16": ("h", 2),
        "u16": ("H", 2),
        "s32": ("i", 4),
        "u32": ("I", 4),
        "s64": ("q", 8),
        "u64": ("Q", 8),
    }
    char, leng = inttypes.get(valtyp, ("x", 0))
    ret = ret + char
    return (ret, leng)

def align(value, alignment):
    """Returns an aligned value equal to or lager than value"""
    floor, remainder = divmod(value, alignment)
    return (floor + (1 if remainder > 0 else 0)) * alignment

class ChunkReader(file):
    """Reads a file in defined chunks"""
    def __init__(self, filename, chunk_size):
        file.__init__(self, filename, "r")
        self.chunk_size = chunk_size

    def next(self):
        return self.read(self.chunk_size)

class IioChannel:
    """Represents an iio channel and its configuration"""
    def __init__(self, iio, direction, name):
        self.iio = iio
        self.name = name
        self.direction = direction
        self.enabled = self.read_info(self.iio.scan_path, "en")
        self.index = self.read_info(self.iio.scan_path, "index")
        self.typ = self.read_info(self.iio.scan_path, "type")
        self.typ_str, self.typ_len = type_to_unpack(self.typ)
        self.offset = self.read_info(self.iio.sysfs_path, "offset")
        if self.offset is None:
            self.offset = 0
        self.scale = self.read_info(self.iio.sysfs_path, "scale")
        if self.scale is None:
            self.scale = 1

    def read_info(self, basepath, postfix):
        """Get the postfix info on a possible shared channel"""
        search_path = os.path.join(basepath, "{}_{}*_{}".format(self.direction,
                                                                self.name,
                                                                postfix))
        paths = glob.glob(search_path)
        if len(paths) < 1:
            search_path = os.path.join(basepath, "{}_{}*_{}".format(self.direction,
                                                                    self.name.split("_")[0],
                                                                    postfix))
            paths = glob.glob(search_path)
        if len(paths) < 1:
            return None
        return read_one_line(paths[0])

    def __lt__(self, other):
        return self.index.__lt__(other.index)

    def __eq__(self, other):
        return self.index.__eq__(other.index)

    def __str__(self):
        return "{}: {}".format(self.name, self.index)

class IioInfo:
    """Information about an iio device, gatherd from sysfs"""
    def __init__(self, iio_name):
        self.iio_name = iio_name
        self.dev_num = find_devnum(self.iio_name)[0]
        self.sysfs_path = os.path.join(SYSFS_BASEPATH, "iio:device%s" % self.dev_num)
        self.scan_path = os.path.join(self.sysfs_path, "scan_elements")
        self.channel = [IioChannel(self, fil.split("_")[0], "_".join(fil.split("_")[1:-1]))
                        for fil in os.listdir(self.scan_path) if fil[-2:] == "en"]

        self.dev_file = ChunkReader("/dev/iio:device{}".format(self.dev_num), self.get_chunk_size())

    def decorate(self, data):
        """converts a chunk of data to a list of name, value tupels"""
        ret = []
        byte_start = 0
        byte_end = 0
        for chan in sorted(self.channel):
            if chan.name == "timestamp":
                byte_start = align(byte_start, TIMESTAMP_ALIGNMENT)
            if chan.typ_len == 0:
                val = (chan.name, 0)
            else:
                byte_end = byte_start + chan.typ_len
                rawval = struct.unpack(chan.typ_str, data[byte_start:byte_end])[0]
                val = (chan.name, ((rawval + float(chan.offset)) * float(chan.scale)))
            ret.append(val)
            byte_start = byte_end
        return ret

    def get_chunk_size(self):
        """Get the total number of bytes in a chunk"""
        return align(sum([chan.typ_len for chan in self.channel]), TIMESTAMP_ALIGNMENT)


def view_fifo(iio_dev_name):
    """run this"""
    info = IioInfo(iio_dev_name)
    now = time.time()
    sys.stdout.write("sample_freq\t")
    for chan in sorted(info.channel):
        sys.stdout.write("{:10}\t".format(chan.name))
    sys.stdout.write("\n")
    sys.stdout.flush()
    for chunk in info.dev_file:
        sys.stdout.write("\r")
        nnow = time.time()
        sys.stdout.write("{:+f}\t".format(1/(nnow-now)))
        now = nnow
        for name, value in info.decorate(chunk):
            if name == "timestamp":
                tme = datetime.fromtimestamp(value * 10**-9)
                sys.stdout.write("{}\t".format(tme))
            else:
                sys.stdout.write("{:+f}\t".format(value))
        sys.stdout.flush()


if __name__ == "__main__":
    try:
        view_fifo("icm20602")
    except KeyboardInterrupt:
        print("")
        sys.exit(0)
