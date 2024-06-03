#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Implementation to interact with Winbond W25Q Flash with software reset.

Credits & kudos to crizeo
Taken from https://forum.micropython.org/viewtopic.php?f=16&t=3899
"""
import micropython
from micropython import const
import time
from machine import SPI, Pin


class W25QFlash(object):
    """W25QFlash implementation"""
    SECTOR_SIZE = const(4096)
    #BLOCK_SIZE = const(512)     # шизофреник бл
    PAGE_SIZE = const(256)

    def __init__(self,
                 spi: SPI,
                 cs: Pin,
                 baud: int = 40000000,
                 software_reset: bool = True) -> None:
        self._manufacturer = 0x0
        self._mem_type = 0
        self._device_type = 0x0
        self._capacity = 0

        self.cs = cs
        self.spi = spi
        self.cs.init(self.cs.OUT, value=1)
        # highest possible baudrate is 40 MHz for ESP-12
        # why????? WHY INIT IT HERE???????
        #self.spi.init(baudrate=baud, phase=1, polarity=1)
        self._busy = False

        if software_reset:
            self.reset()

        # buffer for writing single blocks
        self._cache = bytearray(self.SECTOR_SIZE)

        # calc number of bytes (and makes sure the chip is detected and
        # supported)
        self.identify()

        # address length (default: 3 bytes, 32MB+: 4)
        self._ADR_LEN = 3 if (len(bin(self._capacity - 1)) - 2) <= 24 else 4

        # setup address mode:
        if self._ADR_LEN == 4:
            if not self._read_status_reg(nr=16):  # not in 4-byte mode
                self._await()
                self.cs(0)
                self.spi.write(b'\xB7')  # 'Enter 4-Byte Address Mode'
                self.cs(1)

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def device(self) -> int:
        return self._device_type

    @property
    def manufacturer(self) -> int:
        return self._manufacturer

    @property
    def mem_type(self) -> int:
        return self._mem_type

    def reset(self) -> None:
        if self._busy:
            self._await()
        self._busy = True
        self.cs(0)
        self.spi.write(b'\x66')  # 'Enable Reset' command
        self.cs(1)
        self.cs(0)
        self.spi.write(b'\x99')  # 'Reset' command
        self.cs(1)
        time.sleep_us(30)
        self._busy = False

    def identify(self) -> None:
        self._await()
        self.cs(0)
        self.spi.write(b'\x9F')  # 'Read JEDEC ID' command

        # manufacturer id, memory type id, capacity id
        mf, mem_type, cap = self.spi.read(3, 0x00)
        self.cs(1)

        self._capacity = int(2**cap)

        if not (mf and mem_type and cap):  # something is 0x00
            raise OSError("device not responding, check wiring. ({}, {}, {})".
                          format(hex(mf), hex(mem_type), hex(cap)))
        if mf != 0xEF or mem_type not in [0x40, 0x60, 0x70]:
            # Winbond manufacturer, Q25 series memory (tested 0x40 only)
            print("Warning manufacturer XX or memory type XX not tested.")

        self._manufacturer = mf
        self._mem_type = mem_type
        self._device_type = mem_type << 8 | cap

    def get_size(self) -> int:
        return self._capacity

    def format(self) -> None:
        self._wren()
        self._await()
        self.cs(0)
        self.spi.write(b'\xC7')  # 'Chip Erase' command
        self.cs(1)
        self._await()  # wait for the chip to finish formatting

    def _read_status_reg(self, nr) -> int:

        reg, bit = divmod(nr, 8)
        self.cs(0)
        # 'Read Status Register-...' (1, 2, 3) command
        self.spi.write((b'\x05', b'\x35', b'\x15')[reg])
        stat = 2**bit & self.spi.read(1, 0xFF)[0]
        self.cs(1)

        return stat

    def _await(self) -> None:
        """
        Wait for device not to be busy
        """
        self._busy = True
        self.cs(0)
        self.spi.write(b'\x05')  # 'Read Status Register-1' command

        # last bit (1) is BUSY bit in stat. reg. byte (0 = not busy, 1 = busy)
        trials = 0
        while 0x1 & self.spi.read(1, 0xFF)[0]:
            if trials > 20000:
                raise Exception("Device keeps busy, aborting.")
            time.sleep_ms(3)        # 3 ms is max page program time
            trials += 1
        self.cs(1)
        self._busy = False

    def sector_erase(self, addr) -> None:
        """
        Resets all memory within the specified sector (4kB) to 0xFF

        :param      addr:  The addresss
        :type       addr:  int
        """

        self._wren()
        self._await()
        self.cs(0)
        self.spi.write(b'\x20')  # 'Sector Erase' command
        self.spi.write(addr.to_bytes(self._ADR_LEN, 'big'))
        self.cs(1)
        print('erased at ' + str(addr))

    def block32k_erase(self,addr):
        self._wren()
        self._await()
        self.cs(0)
        self.spi.write(b'\x52')  # 'Sector Erase' command
        self.spi.write(addr.to_bytes(self._ADR_LEN, 'big'))
        self.cs(1)
        print('erased 32k at ' + str(addr))

    def _read(self, buf: list, addr: int) -> None:
        assert addr + len(buf) <= self._capacity, \
            "memory not addressable at %s with range %d (max.: %s)" % \
            (hex(addr), len(buf), hex(self._capacity - 1))

        self._await()
        self.cs(0)
        # 'Fast Read' (0x03 = default), 0x0C for 4-byte mode command
        self.spi.write(b'\x0C' if self._ADR_LEN == 4 else b'\x0B')
        self.spi.write(addr.to_bytes(self._ADR_LEN, 'big'))
        self.spi.write(b'\xFF')  # dummy byte
        self.spi.readinto(buf, 0xFF)
        self.cs(1)

    def _wren(self) -> None:
        self._await()
        self.cs(0)
        self.spi.write(b'\x06')  # 'Write Enable' command
        self.cs(1)

    def write_page(self, buf: memoryview, addr: int) -> None:
        # rewrote to accept addresses other than page start
        # and to program only one page
        if len(buf)+addr&0xff>256:
            raise Exception("out of page bounds")


        address = bytearray(3)
        address[0] = (addr >> 16) & 0xff
        address[1] = (addr >> 8) & 0xff
        address[2] = addr & 0xff

        #print('writing at ' + str(addr))

        self._wren()
        self._await()
        self.cs(0)
        self.spi.write(b'\x02')  # 'Page Program' command
        self.spi.write(address)
        self.spi.write(buf)
        self.cs(1)

    def _writeblock(self, blocknum: int, buf: list) -> None:
        assert len(buf) == self.BLOCK_SIZE, \
            "invalid block length: {}".format(len(buf))

        sector_nr = blocknum // 8
        sector_addr = sector_nr * self.SECTOR_SIZE
        # index of first byte of page in sector (multiple of self.PAGE_SIZE)
        index = (blocknum << 9) & 0xfff

        self._read(buf=self._cache, addr=sector_addr)
        self._cache[index:index + self.BLOCK_SIZE] = buf  # apply changes
        self.sector_erase(addr=sector_addr)
        # addr is multiple of self.SECTOR_SIZE, so last byte is zero
        self.write_page(buf=self._cache, addr=sector_addr)

    def readblocks(self, blocknum: int, buf: list) -> None:
        assert len(buf) % self.BLOCK_SIZE == 0, \
            'invalid buffer length: {}'.format(len(buf))

        buf_len = len(buf)
        if buf_len == self.BLOCK_SIZE:
            self._read(buf=buf, addr=blocknum << 9)
        else:
            offset = 0
            buf_mv = memoryview(buf)
            while offset < buf_len:
                self._read(buf=buf_mv[offset:offset + self.BLOCK_SIZE],
                           addr=blocknum << 9)
                offset += self.BLOCK_SIZE
                blocknum += 1

    def writeblocks(self, blocknum: int, buf: list) -> None:
        buf_len = len(buf)
        if buf_len % self.BLOCK_SIZE != 0:
            # appends xFF dummy bytes
            buf += bytearray((self.BLOCK_SIZE - buf_len) * [255])

        if buf_len == self.BLOCK_SIZE:
            self._writeblock(blocknum=blocknum, buf=buf)
        else:
            offset = 0
            buf_mv = memoryview(buf)
            while offset < buf_len:
                self._writeblock(blocknum=blocknum,
                                 buf=buf_mv[offset:offset + self.BLOCK_SIZE])
                offset += self.BLOCK_SIZE
                blocknum += 1
        # remove appended bytes
        buf = buf[:buf_len]

    def count(self) -> int:
        return int(self._capacity / self.BLOCK_SIZE)

    def read_bytes(self, addr, len, buff):
        self._await()
        address = bytearray(3)
        address[0] = (addr >> 16) & 0xff
        address[1] = (addr >> 8) & 0xff
        address[2] = addr & 0xff
        self.cs(0)
        self.spi.write(b'\x0B')
        self.spi.write(address)
        self.spi.write(b'\xFF')     #dummy
        b = memoryview(buff)
        self.spi.readinto(b[0:len])
        self.cs(1)



class WinbondBuff:
    def __init__(self, offset : int, flash : W25QFlash, readonly = False, hotsize=4096, no_erase=False):
        self.offset = offset
        self.flash = flash
        self.readonly = readonly
        self.writeptr = offset
        self.hotbuff = bytearray(hotsize)
        self.hotsize=hotsize
        self.no_erase = no_erase
        self.hotbuff_contains=0
        self.hotbuff_rel_ptr = 0


    def read(self, p, n, buff=None):
        if n>self.hotsize:
            raise Exception("longer than hotsize!")
        ret = 0
        if buff==None:
            ret = 1
            # buff = bytearray(n)

        if (p + n > self.hotbuff_rel_ptr + self.hotbuff_contains) or (p < self.hotbuff_rel_ptr):
            if self.readonly:
                to_read = self.hotsize
            else:
                to_read = min(self.hotsize, self.writeptr - self.offset - p)
                if to_read<n:
                    raise Exception("out of bounds")
            self.flash.read_bytes(self.offset+p,to_read , self.hotbuff)
            self.hotbuff_contains = to_read
            self.hotbuff_rel_ptr=p


        if ret!=0:
            return memoryview(self.hotbuff)[p-self.hotbuff_rel_ptr:p - self.hotbuff_rel_ptr + n]
        else:
            i = 0
            while i < n:
                buff[i] = self.hotbuff[p - self.hotbuff_rel_ptr + i]
                i += 1
            return None


    def push(self, buff : memoryview):
        if self.readonly:
            raise ("Read only!")
        n=len(buff)
        #print("pushing " + str(n) + " bytes")
        if n>4096:
            raise Exception("too long")

        if not self.no_erase:
            if self.writeptr==self.offset or self.writeptr%4096==0:
                self.flash.sector_erase(self.writeptr&0x00fff000)

            if self.writeptr//4096 < (self.writeptr + n - 1)//4096:
                self.flash.sector_erase((self.writeptr + n) & 0x00fff000)

        page_bytes_left = 256-(self.writeptr & 0xff)
        if page_bytes_left>=n:
            self.flash.write_page(buff, self.writeptr)
        else:
            self.flash.write_page(buff[0:page_bytes_left], self.writeptr)
            extra = (n-page_bytes_left)&0xff

            p = page_bytes_left
            while p < n-extra:
                self.flash.write_page(buff[p:p+256], self.writeptr + p)
                p+=256
            if extra>0:
                self.flash.write_page(buff[n-extra:n], self.writeptr + n - extra)


        self.writeptr+=n



    def write(self, p, n, buff):
        raise Exception("TODO")

        if n>4096:
            raise
        ptr = p+self.offset
        cur_sector = bytearray(4096)
        self.flash.read_bytes(ptr & 0x00fff000, 4096, cur_sector)
        if (ptr & 0x00fff000) != ((ptr+n) & 0x00fff000):
            n2 = (ptr+n) & 0xfff
            n1 = n-n2
        else:
            n1=n
            n2=0

        self.flash.sector_erase(ptr)
        self.flash._await()
        for i in range(0, n):
            pass
