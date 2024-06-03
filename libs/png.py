import array
import os

import deflate
import gc
import struct
import time

import micropython

import libs.winbond as wb

GREY_SCALE = 0
TRUE_COLOR = 2
INDEXED_COLOR = 3
GREY_SCALE_ALPHA = 4
TRUE_COLOR_ALPHA = 6

BINARY_COLOR = 0
SEVEN_COLORS = 1

@micropython.viper
def int_from_bytes(bts, l : int, as_big : bool) -> int:
    ba = ptr8(bts)
    res : int = 0
    i : int=0
    while i<l:
        if as_big:
            res<<=8
            res |= ba[i]
        else:
            res |= ba[i] << i*8

        i+=1

    return res


class PngMeta:
    def __init__(self, input_buff : wb.WinbondBuff, out_buff: wb.WinbondBuff):
        self.flash_buff = input_buff
        self.processed_image_buff = out_buff
        #image.read(16)  # skip signature + header len and name

    diff0=255
    mono0=127
    use_treshold_map = True
    display_type = SEVEN_COLORS
    invert_binary = False

    palette_7colors = [[0,0,0],
                       [255,255,255],
                       [0,255,0],
                       [0,0,255],
                       [255,0,0],
                       [255,255,0], #a bit less tolerance for yellow
                       [255,127,0]] # same for orange


    def init_from_flash(self):
        ihdr = bytearray(16)
        self.flash_buff.read(16, 13, ihdr)
        self.width = int.from_bytes(ihdr[0:4], 'big') & 0x7fffffff
        print('width = ' + str(self.width))
        self.height = int.from_bytes(ihdr[4:8], 'big') & 0x7fffffff
        print('height = ' + str(self.height))
        self.bit_depth = ihdr[8]
        self.color_type = ihdr[9]
        self.compression = ihdr[10]
        self.filter = ihdr[11]
        self.interlace = ihdr[12]
        self.bpp = self.bit_depth

        if self.color_type == GREY_SCALE:
            pass
        if self.color_type == TRUE_COLOR or self.color_type == INDEXED_COLOR:
            self.bpp *= 3
        if self.color_type == GREY_SCALE_ALPHA:
            self.bpp *= 2
        if self.color_type == TRUE_COLOR_ALPHA:
            self.bpp *= 4
        self.bpp //= 8
        if self.bpp == 0:
            self.bpp = 1

        if self.color_type==INDEXED_COLOR:
            raise("Indexed color is not supported yet")

        self.ptr = 0

    # returns 3 for indexed color
    def bytes_per_pixel(self):
        return self.bpp

    @micropython.native
    def read(self, n):
        res = self.flash_buff.read(self.ptr,n)
        self.ptr+=n
        #print('reading from pngmeta: ' + str(res))
        return res

    @micropython.native
    def skip(self, n):
        self.ptr+=n

    def get_encoding_7colors(self, pixel):
        #TODO indexed color
        if self.color_type==GREY_SCALE or self.color_type==GREY_SCALE_ALPHA:
            raise Exception("cant transform greyscale to 7 colors!")


        # TODO optimize
        mindiff=999
        mindiff_i=0
        for i in range(0,7):
            diff = abs(self.palette_7colors[i][0]-pixel[0])+\
                abs(self.palette_7colors[i][1]-pixel[1]) +\
                abs(self.palette_7colors[i][2]-pixel[2])

            if diff<mindiff:
                mindiff=diff
                mindiff_i=i

        return mindiff_i



class PngDecoder:
    data_bytes_left = 0
    palette_arr = None
    chunk_name = b''
    chunk_bytes_left = 0

    bitseq = int(0x0000)
    bits_left = 0
    zblock_type = 0b11
    zblock00_bytes_left = 0
    zblock_last = 0

    doubleencoding_alphabet = [16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15]

    def __init__(self, meta: PngMeta, hotbuffsize=4*1024):
        self.LUT_mirrored = bytearray(256)
        self.LUT_bitmaskLSB = [0]*33
        if meta.bit_depth < 8:
            raise #stub

        from libs.pngtoeink import PngToEink      # avoiding cyclical


        self.meta = meta
        meta.skip(8) #skip png header
        self.pngtoeink = PngToEink(hotbuffsize, meta)

        for i in range(0,256):
            t = ((i>>1) & 0x55) | ((i & 0x55) << 1)
            t = ((t>>2) & 0x33) | ((t & 0x33) << 2)
            self.LUT_mirrored[i] = ((t >> 4) | (t << 4)) & 0xff

        for i in range (0,33):
            self.LUT_bitmaskLSB[i] = (1 << i) - 1

    # potential out-of-boundaries bug
    @micropython.native
    def read_chunk_int(self, size_bytes, bo = 'little'):
        if size_bytes>self.chunk_bytes_left:
            raise Exception('Not enough bytes left')
        if self.chunk_bytes_left == 0:
            if self.chunk_name != b'':  # skip checksum
                self.meta.skip(4)

            self.chunk_bytes_left = int_from_bytes(self.meta.read(4),4, True)
            self.chunk_name = bytearray(self.meta.read(4))
            print('chunk len = ' + str(self.chunk_bytes_left))
            print('chunk name = ' + str(self.chunk_name))

        self.chunk_bytes_left = self.chunk_bytes_left - size_bytes

        return int_from_bytes(self.meta.read(size_bytes), size_bytes, bo!='little')

    @micropython.native
    def jump_to_next_chunk_data(self):
        self.meta.skip(self.chunk_bytes_left)
        if (self.chunk_name != b''):
            self.meta.skip(4)

        self.chunk_bytes_left = int_from_bytes(self.meta.read(4), 4, True)
        name= bytearray(self.meta.read(4))
        self.chunk_name = name
        print('chunk len = ' + str(self.chunk_bytes_left))
        print('chunk name = ' + str(name))

    @micropython.native
    def fill_bitseq(self, size_bytes):
        extra = size_bytes - self.chunk_bytes_left
        bits_left = self.bits_left
        if extra>0:
            if self.chunk_bytes_left>0:
                self.bitseq |= (int_from_bytes(self.meta.read(self.chunk_bytes_left), self.chunk_bytes_left, False) << bits_left)
                self.chunk_bytes_left=0
            self.jump_to_next_chunk_data()
            self.bitseq |= (int_from_bytes(self.meta.read(extra), extra, False) << (bits_left + (size_bytes-extra)*8))
            self.chunk_bytes_left = self.chunk_bytes_left - extra
        else:
            self.bitseq |= (int_from_bytes(self.meta.read(size_bytes), size_bytes, False) << bits_left)
            self.chunk_bytes_left = self.chunk_bytes_left - size_bytes

        self.bits_left += 8 * size_bytes

    @micropython.viper
    # l<32!!!
    def _reverse(self, n : uint, l: int) -> uint:
        lut = ptr8(self.LUT_mirrored)
        res : uint = uint(lut[n >> 24])
        res |= lut[(n >> 16) & 0xff] << 8
        res |= lut[(n >> 8) & 0xff] << 16
        res |= lut[n & 0xff] << 24
        res >>= 32-l
        # res &= (ptr32(self.LUT_bitmaskLSB))[l]
        return res

    @micropython.native
    def read_from_bitseq(self, size_bits, flush=False, decode_as_huffman=True):
        if size_bits>32:
            raise Exception('Too long')
        if size_bits==0:
            return 0
        if size_bits>self.bits_left:
            self.fill_bitseq(size_bits // 8 + 1)  #1 extra byte wont do any harm


        if decode_as_huffman:
            res = self._reverse((self.bitseq & 0xffffffff), size_bits)
            # print('reverse: ' + str(bin(self.bitseq & self.LUT_bitmaskLSB[size_bits])) + "  " + str(bin(res)) + " ;;;; len = " + str(size_bits))

        else:
            res = self.bitseq & self.LUT_bitmaskLSB[size_bits]

        if flush:
            self.flush_bitseq(size_bits)
        return res

    @micropython.native
    def flush_bitseq(self, len_bits : int):
        self.bitseq = self.bitseq >> len_bits
        self.bits_left = self.bits_left - len_bits
        if self.bits_left<0:
            self.bits_left=0

    @micropython.viper
    def len_from_0285(self, code0285 : int) -> int:
        l: int = 0
        if code0285 == 285:
            l = 258
        else:
            l = code0285 - 257
            ex : int = (l >> 2) - 1
            # if ex <= 0:
            #     pass
            #     # l = l & (0b11 if ex!=0 else 0b111)
            # else:
            if ex>0:
                l = 0b100 | (l & 0b11)
                l = l << ex
                l = l | int(self.read_from_bitseq(ex, flush=True, decode_as_huffman=False))
            l = l + 3

        return l

    @micropython.viper
    def dist_from_031(self, code031 : int) -> int:
        d : int = 0
        ex : int = (code031 >> 1) - 1
        if ex <= 0:
            d = code031
        else:
            d = 0b10 | (code031 & 1)
            d = d << ex
            d = d | int(self.read_from_bitseq(ex, flush=True, decode_as_huffman=False))
        d = d + 1

        return d


    def decode_fixed_huffman(self):
        # 00110000          0           01100
        # 10111111          143         11101
        # 110010000         144         10011
        # 111111111         255         11111
        # 0000000           256         00000
        # 0010111           279         10100
        # 11000000          280         00011
        # 11000111          287         00011


        code = self.read_from_bitseq(8, flush = False, decode_as_huffman=True)
        if code<0b00110000:
            self.flush_bitseq(7)
            code0285 = 256+(code>>1)
        elif code<0b11000000:
            self.flush_bitseq(8)
            code0285 = 0+code-0b00110000
        elif code<0b11001000:
            self.flush_bitseq(8)
            code0285 = 280+code-0b11000000
        else:
            code0285 = self.read_from_bitseq(9,flush=True)

        if code0285<256:
            self.pngtoeink.write_int(code0285, 1)
            return True
        elif code0285==256:
            return False
        else:
            l = self.len_from_0285(code0285)
            d = self.dist_from_031(self.read_from_bitseq(5,flush=True,decode_as_huffman=True))          # ?? still huffman, right?

            for i in range(0, l):
                if self.pngtoeink.ptr%(1024 * 32)==0:
                    print("processed " + self.pngtoeink.ptr // 1024 + "kb...")
                self.pngtoeink.write(self.pngtoeink.read(self.pngtoeink.ptr - d, 1))  # TODO optimize

            return True

    @micropython.viper
    # flushes bitseq
    # yet, still needs bitseq as arg
    # because.... reasons!!! actually, bitseq isnt guaranteed to be 32 bit int
    def read_huffcode_index_viper(self, bitseq_reversed : uint, seq_len : int, len_cnt) -> int:
        code_cnt = ptr8(len_cnt)

        curlen_mincode : uint = 0
        bitcnt : int = 1
        index : int = 0
        evaluated_seq : uint = uint(bitseq_reversed >> (seq_len-bitcnt))
        while bitcnt!=seq_len and (uint(evaluated_seq) >= uint(curlen_mincode) + code_cnt[bitcnt]):
            index+=code_cnt[bitcnt]
            curlen_mincode+=code_cnt[bitcnt]
            curlen_mincode<<=1
            bitcnt+=1
            evaluated_seq = uint(bitseq_reversed >> (seq_len-bitcnt))

        self.flush_bitseq(bitcnt)

        return index + (evaluated_seq-curlen_mincode)


    def decode_png(self):
        time_total = time.time() - time.time()
        while self.chunk_name != b'IDAT':
            self.jump_to_next_chunk_data()

            if self.chunk_name == b'IEND':
                return

        pngtoeink = self.pngtoeink

        should_read_zlib_header = True

        while not self.zblock_last:

            if should_read_zlib_header:
                header = self.read_from_bitseq(2 * 8, flush=True, decode_as_huffman=False)
                print(header)
                should_read_zlib_header = False



            self.zblock_last = self.read_from_bitseq(1, flush=True, decode_as_huffman=False)
            self.zblock_type = self.read_from_bitseq(2, flush=True, decode_as_huffman=False)

            if self.zblock_type==0b00:
                # we feed bitseq multiples of 8 bits each time,
                # which means bits_left%8 equals bits unread from current byte
                print("no compression")
                dummy_bits = self.bits_left % 8
                self.flush_bitseq(dummy_bits)
                self.zblock00_bytes_left = self.read_from_bitseq(16, flush=True, decode_as_huffman=False)
                self.read_from_bitseq(16, flush=True)   # skip one's complaint
                while self.zblock00_bytes_left>0:
                    # TODO rewrite to avoid ineffective bitseq read
                    d = self.read_from_bitseq(8, flush=True, decode_as_huffman=False)
                    pngtoeink.write_int(d, 1)

                    self.zblock00_bytes_left = self.zblock00_bytes_left-1


            # while True:     # DEBUG
            #     stub = self.read_from_bitseq(32, flush=True)
            #     pass

            if self.zblock_type==0b01:
                print("fixed compression")
                while self.decode_fixed_huffman():
                    pass



            if self.zblock_type == 0b10:
                print("dynamic compression")
                hlit = self.read_from_bitseq(5, flush=True, decode_as_huffman=False) + 257
                hdist = self.read_from_bitseq(5, flush=True, decode_as_huffman=False) + 1
                hclen = self.read_from_bitseq(4, flush=True, decode_as_huffman=False) + 4
                debug_lengths = bytearray(19)
                lengths = bytearray(19)
                for i in range(0,hclen):
                    lengths[self.doubleencoding_alphabet[i]] = self.read_from_bitseq(3, flush=True, decode_as_huffman=False)

                de_mincodes = bytearray(8)
                de_codecnt = bytearray(8)
                de_codeseq = bytearray(19)
                codeseq_ptr = 0
                for curlen in range(1, 8):
                    de_mincodes[curlen] = (de_mincodes[curlen-1] + de_codecnt[curlen-1]) << 1
                    for i in range(0, 19):
                        if lengths[i] == curlen:
                            de_codeseq[codeseq_ptr] = i
                            codeseq_ptr = codeseq_ptr + 1
                            de_codecnt[curlen] = de_codecnt[curlen] + 1

                total = hlit+hdist
                lengths = bytearray(total)
                i = 0

                while i<total:
                    code018 = 19
                    bits_cnt = 0
                    ptr = 0
                    while code018>18:
                        bits_cnt = bits_cnt + 1
                        code = self.read_from_bitseq(bits_cnt, flush=False, decode_as_huffman=True)
                        n = code - de_mincodes[bits_cnt]
                        if n < de_codecnt[bits_cnt]:

                            code018 = de_codeseq[ptr+n]

                            self.flush_bitseq(bits_cnt)
                            break
                        ptr = ptr + de_codecnt[bits_cnt]

                    if code018<16:
                        lengths[i] = code018
                        i = i+1

                    elif code018 == 16:
                        ex = self.read_from_bitseq(2, flush=True, decode_as_huffman=False) + 3
                        for j in range(0, ex):
                            lengths[i+j] = lengths[i-1]
                        i = i + ex

                    elif code018==17:
                        ex = self.read_from_bitseq(3, flush=True, decode_as_huffman=False) + 3
                        for j in range(0, ex):
                            if i+j==total:      # stub
                                break
                            lengths[i+j] = 0
                        i = i + ex

                    elif code018 == 18:
                        ex = self.read_from_bitseq(7, flush=True, decode_as_huffman=False) + 11
                        for j in range(0, ex):
                            if i+j==total:      # stub
                                break
                            lengths[i + j] = 0
                        i = i + ex

                # ll_mincodes = [0]*16
                ll_codecnt = bytearray(16)  # lets pray no encoder ever generates >255 codes with same length
                ll_codeseq = [0]*hlit
                codeseq_ptr = 0
                ll_maxcodelen=0
                for curlen in range(1, 16):
                    # ll_mincodes[curlen] = (ll_mincodes[curlen - 1] + ll_codecnt[curlen - 1]) << 1
                    for i in range(0, hlit):
                        if lengths[i] == curlen:
                            ll_maxcodelen=curlen
                            ll_codeseq[codeseq_ptr] = i
                            codeseq_ptr = codeseq_ptr + 1
                            ll_codecnt[curlen] += 1

                # ds_mincodes = [0] * 16
                ds_codecnt = bytearray(16)
                ds_codeseq = [0] * hdist
                ds_maxcodelen = 0
                codeseq_ptr = 0
                for curlen in range(1, 16):
                    # ds_mincodes[curlen] = (ds_mincodes[curlen - 1] + ds_codecnt[curlen - 1]) << 1
                    for i in range(hlit, hlit+hdist):
                        if lengths[i] == curlen:
                            ds_maxcodelen=curlen
                            ds_codeseq[codeseq_ptr] = i - hlit
                            codeseq_ptr = codeseq_ptr + 1
                            ds_codecnt[curlen] += 1

                #
                # decoding actual data
                #

                code0285 = 999
                while code0285!=256:
                    # code0285 = 999
                    # bits_cnt = 0
                    # ptr=0
                    # while code0285>285:
                        # bits_cnt = bits_cnt + 1
                        # n = self.read_from_bitseq(bits_cnt, flush=False, decode_as_huffman=True) - ll_mincodes[bits_cnt]
                        # if n < ll_codecnt[bits_cnt]:
                        #     code0285=ll_codeseq[ptr+n]
                        #     self.flush_bitseq(bits_cnt)
                        #     break
                        # ptr = ptr + ll_codecnt[bits_cnt]


                    precode = self.read_from_bitseq(ll_maxcodelen, flush=False, decode_as_huffman=True)
                    # while code0285>285:
                    #     bits_cnt = bits_cnt + 1
                    #     n = (precode >> (ll_maxcodelen - bits_cnt)) - ll_mincodes[bits_cnt]
                    #     if n < ll_codecnt[bits_cnt]:
                    #         code0285=ll_codeseq[ptr+n]
                    #         self.flush_bitseq(bits_cnt)
                    #         break
                    #     ptr = ptr + ll_codecnt[bits_cnt]
                    index = self.read_huffcode_index_viper(precode, ll_maxcodelen, ll_codecnt)
                    code0285 = ll_codeseq[index]

                    if code0285<256:
                        pngtoeink.write_int(code0285, 1)
                        if pngtoeink.ptr % (32 * 1024) == 0:
                            print('Processed ' + str(pngtoeink.ptr // 1024) + 'kB...')
                    elif code0285>256:
                        l = self.len_from_0285(code0285)

                        # code031 = 32            # i know its 29 max
                        # bits_cnt=0
                        # ptr=0
                        ds_precode = self.read_from_bitseq(ds_maxcodelen, flush=False, decode_as_huffman=True)
                        # while code031>31:
                        #     bits_cnt = bits_cnt + 1
                        #     n = (ds_precode >> (ds_maxcodelen - bits_cnt))- ds_mincodes[bits_cnt]
                        #     if n < ds_codecnt[bits_cnt]:
                        #         code031 = ds_codeseq[ptr + n]
                        #         self.flush_bitseq(bits_cnt)
                        #         break
                        #     ptr = ptr + ds_codecnt[bits_cnt]
                        index = self.read_huffcode_index_viper(ds_precode, ds_maxcodelen, ds_codecnt)
                        code031 = ds_codeseq[index]
                        d = self.dist_from_031(code031)
                        maxread = min(l, d)
                        #
                        # gc.collect()
                        for i in range(0, l, maxread):
                            # hellish fragmentation here
                            # 31/53 w/o maxread
                            # 26/43 with

                            if pngtoeink.ptr%pngtoeink.hotsize+maxread>=pngtoeink.hotsize:
                                print('Processed ' + str(pngtoeink.ptr // 1024 + 1) + 'kB...')
                            start = time.time()
                            bts = pngtoeink.read(pngtoeink.ptr - d, min(l - i, maxread))

                            pngtoeink.write(bts)       # TODO optimize

                            time_total += time.time() - start

        # temp solution
        # coldbuff needs new filter type byte to save prev line
        pngtoeink.write(b'\0')

        # TODO pos-unzip cleanup
        print('DONE!!!')
        print('Image processing itself took ' + str(time_total))
        gc.collect()