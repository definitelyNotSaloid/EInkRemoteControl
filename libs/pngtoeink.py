import gc
import io
import libs.winbond as wb
import libs.png as png
import os
import micropython

DISPLAY_WIDTH = 800
#DISPLAY_WIDTH_BYTES = DISPLAY_WIDTH // 8
DISPLAY_HEIGHT = 480
#DISPLAY_HEIGHT_BYTES = DISPLAY_HEIGHT // 8



class PngToEink:
    def __init__(self, hotsize, meta: png.PngMeta, tmpsize=16, width=DISPLAY_WIDTH, height = DISPLAY_HEIGHT):
        self.res_flash_buff = meta.processed_image_buff
        #prepare flash
        blocksize = (1024*32)
        blockstart = self.res_flash_buff.offset & 0xff7000
        if self.res_flash_buff.offset % blocksize!=0:
            blockstart+=blocksize

        dbpp = 4 if meta.display_type == png.SEVEN_COLORS else 1
        imgsize = DISPLAY_HEIGHT*DISPLAY_WIDTH*dbpp//8
        for i in range(blockstart, self.res_flash_buff.offset+imgsize, blocksize):
            self.res_flash_buff.flash.block32k_erase(i)


        self.disp_width = width
        self.disp_height = height
        self.meta = meta
        print(" mem used up = " + str(gc.mem_alloc()))
        print("mem free = " + str(gc.mem_free()))
        self.pngbuffsize = meta.width * meta.bytes_per_pixel() + self.meta.bytes_per_pixel()
        print('pngbuffsize = ' + str(self.pngbuffsize))
        self.pnghotbuff = bytearray(self.pngbuffsize)
        self.debug_totalmono = 0.0
        self.meta = meta
        self.rows_ratio_cnt = 0.0
        self.row_ratio = self.meta.height / DISPLAY_HEIGHT
        self.col_ratio_cnt = 0.0
        self.col_ratio = self.meta.width / DISPLAY_WIDTH
        #self.prev_mono_scanline = bytearray(DISPLAY_WIDTH)
        #self.cur_mono_scanline = bytearray(DISPLAY_WIDTH)
        self.colorline_buff_displaywidth = bytearray(DISPLAY_WIDTH * self.meta.bytes_per_pixel())
        print(" mem used up = " + str(gc.mem_alloc()))
        print("mem free = " + str(gc.mem_free()))
        self.res_buff = bytearray(DISPLAY_WIDTH * (1 if self.meta.display_type==png.BINARY_COLOR else 4) // 8)



        self.rowssaved = 0
        self.colcnt_diff = 0

        self.hotsize = hotsize
        self.hotbuff_arr = bytearray(self.hotsize)
        self.hotbuff = memoryview(self.hotbuff_arr)
        self.ptr = 0

        self.halfsize = self.hotsize // 2
        self.tmpsize = tmpsize
        self.tmpbuff_arr = bytearray(tmpsize)
        self.tmpbuff = memoryview(self.tmpbuff_arr)
        self.tmpptr = 0
        self.tmpcurhold = 0
        self.curfilter = 0

        self.filter_bytes_skipped = 0
        self.max_savefiles = 0 if hotsize>=32*1024 else 32*1024 // self.halfsize - 1       # 32kb total
        if self.max_savefiles<0:
            self.max_savefiles=0

        self.treshold_map_rot0 = [0, 32, 8, 40, 2, 34, 10, 42,
                                  48, 16, 56, 24, 50, 18, 58, 26,
                                  12, 44, 4, 36, 14, 46, 6, 38,
                                  60, 28, 52, 20, 62, 30, 54, 22,
                                  3, 35, 11, 43, 1, 33, 9, 41,
                                  51, 19, 59, 27, 49, 17, 57, 25,
                                  15, 47, 7, 39, 13, 45, 5, 37,
                                  63, 31, 55, 23, 61, 29, 53, 21]

        self.treshold_map_rot1 = [42, 26, 38, 22, 41, 25, 37, 21,
                                  10, 58, 6, 54, 9, 57, 5, 53,
                                  34, 18, 46, 30, 33, 15, 45, 29,
                                  2, 50, 14, 62, 1, 49, 13, 61,
                                  40, 24, 36, 20, 43, 27, 39, 23,
                                  8, 56, 4, 52, 11, 59, 7, 55,
                                  32, 16, 44, 28, 35, 19, 47, 31,
                                  0, 48, 12, 60, 3, 61, 15, 63]

        self.treshold_map_rot2 = [21, 53, 29, 61, 23, 55, 31, 63,
                                  37, 5, 45, 13, 39, 7, 47, 15,
                                  25, 57, 17, 49, 27, 59, 19, 51,
                                  41, 9, 33, 1, 43, 11, 35, 3,
                                  22, 54, 30, 62, 20, 52, 28, 60,
                                  38, 6, 46, 14, 36, 4, 44, 12,
                                  26, 58, 18, 50, 24, 56, 16, 48,
                                  42, 10, 34, 2, 40, 8, 32, 0]

        # f = open(outpath, 'wb')
        # f.close()

    def filesize(self):
        return self.ptr // self.halfsize * self.halfsize - self.halfsize  # FIXXX

    def hotptr(self):
        return self.ptr % self.hotsize

    def can_use_tmp_buff(self, p, n):
        return p >= self.tmpptr and p + n <= self.tmpptr + self.tmpcurhold

    def fill_tmp_buff(self, p, n):
        raise Exception("no need for it")

        if n>self.tmpsize:
            raise Exception('out of bounds')
        file_n = p // self.halfsize

        in_files = min(self.filesize() - p, self.tmpsize)
        if in_files < 0:
            raise  # TODO

        #print('Had to peek into file, offset = ' + str(self.ptr - p))
        f = open(str(file_n) + self.outpath, 'rb')
        f.seek(p % self.halfsize)
        if in_files >= n:
            # all data is in files
            n1 = self.halfsize - p % self.halfsize
            if n1 > n:
                n1 = n

            n2 = n - n1
            for i in range(0,n1):
                self.tmpbuff_arr[i]=f.read(1)[0]
            # res = bytearray(f.read(n1))
            f.close()

            if n2 != 0:
                # print('Filled tmpbuff using 2 files')
                f = open(str(file_n + 1) + self.outpath, 'rb')
                for i in range(n1,n2):
                    self.tmpbuff_arr[i] = f.read(1)[0]
                f.close()
            # else:
            # print('Filled tmpbuff using only 1 file')

        else:
            # print('Filled tmpbuff using file and hotbuff')
            for i in range(0, in_files):
                self.tmpbuff_arr[i] = f.read(1)[0]
            # res = bytearray(f.read(n1))
            f.close()
            leftover = n - in_files
            for i in range(self.filesize(), self.filesize() + leftover):
                self.tmpbuff_arr[i - self.filesize()+in_files] = self.hotbuff_arr[i % self.hotsize]

    @micropython.viper
    # 32k hotsize assumed!!!
    # offset is relative to first byte ever written
    def write_viper(self, offset : int, l : int, data_arr):
        data = ptr8(data_arr)
        pbuff =ptr8(self.hotbuff_arr)
        right_relative = (offset+l)&0x7fff
        if right_relative>offset:
            for i in range(offset,right_relative):
                pbuff[i] = data[i-offset]
        else:
            for i in range(offset,0x8000):
                pbuff[i] = data[i-offset]

            wrote = 0x8000-offset
            for i in range(0, right_relative):
                pbuff[i] = data[i+wrote]

    @micropython.viper
    def write_byte_viper(self, offset: int, byte: int):
        p = ptr8(self.hotbuff_arr)
        p[offset & 0x7fff]=byte&0xff

    def write(self, data):
        l = len(data)

        if l > self.halfsize:
            raise
        ptr = self.ptr

        # in case of emergency (catatrophic lack of memory) uncomment this
        # if l + (ptr % int(self.halfsize)) >= int(self.halfsize):
        #     self._save()

        for i in range(ptr, ptr + l):
            byte = data[i - ptr]
            self.write_byte_viper(i, byte)

            j = i - self.filter_bytes_skipped
            if i % (self.pngbuffsize - self.meta.bytes_per_pixel() + 1) == 0:

                print("\r\nFILTER TYPE = " + str(byte))
                print()

                if j != 0:
                    self.rows_ratio_cnt += 1
                    tmp = self.ptr          # nyeehheheheheheheh i wont rewrite it
                    self.ptr=i
                    if self.rows_ratio_cnt >= 1:
                        self._savepng()
                        self.rows_ratio_cnt -= self.row_ratio
                    # else:
                    #     self.diffmask_buff = 0
                    self.ptr = tmp
                    ptr = tmp

                self.curfilter = byte
                self.filter_bytes_skipped += 1


            else:
                self.pnghotbuff[j % self.pngbuffsize] = self.filter(
                    byte,
                    j
                ) & 0xff

        self.ptr += l

    def write_int(self, data_int: int, l):
        ba = bytearray(l)
        for i in range(0,l):
            ba[i] = data_int & 0xff
            data_int>>=8
        self.write(ba)

    @micropython.native
    def read(self, p : int, n : int):
        # if n > 258:
        #     raise  # stub
        hs = int(self.hotsize)
        if (int(self.ptr) - p) <= hs:

            if (p%hs) + n<=hs:
                return self.hotbuff[p%hs: p%hs+n]

            res = bytearray(n)
            for i in range(p, p + n):
                res[i - p] = self.hotbuff_arr[i % self.hotsize]

            return memoryview(res)

        else:
            if not self.can_use_tmp_buff(p, n):
                # print('Had to peek into file, offset = ' + str(self.ptr-p))
                self.fill_tmp_buff(p, n)
            else:
                pass
                #print('saved some time using tmpbuff')
            return self.tmpbuff[p - self.tmpptr: p - self.tmpptr + n]

    # @micropython.viper
    # def byte_a(self, j : int) -> int:
    #
    #
    #
    # @micropython.viper
    # def byte_b(self, j : int) -> int:
    #     bpp: int = int(self.meta.bytes_per_pixel())
    #     pngbuff = ptr8(self.pnghotbuff)
    #     bs: int = int(self.pngbuffsize)
    #     if j >= bs - bpp:
    #         return int(pngbuff[(j + bpp) % bs])
    #     else:
    #         return 0
    #
    # @micropython.viper
    # def byte_c(self, j : int) -> int:
    #     bpp: int = int(self.meta.bytes_per_pixel())
    #     pngbuff = ptr8(self.pnghotbuff)
    #     bs: int = int(self.pngbuffsize)
    #     if j >= bs - bpp and j % (bs - bpp) >= bpp:
    #         return int(pngbuff[j % bs])
    #     else:
    #         return 0

    @micropython.native
    def to_mono(self, pixel):
        res = 0
        bpp = self.meta.bytes_per_pixel()

        if bpp == 1:
            res = int(pixel[0])
        if bpp == 2:
            res = pixel[0] * pixel[1] // 255
        if bpp == 3:
            res = pixel[0] // 4 + pixel[1] * 11 // 16 + pixel[2] // 16
        if bpp == 4:
            res = pixel[0] // 4 + pixel[1] * 11 // 16 + pixel[2] // 16 #* pixel[3] // 255

        return res

    @micropython.viper
    def filter(self, x : int, relptr: int) -> int:
        # moved a,b,c byte calculations under if's to avoid uncecessary computations

        t = int(self.curfilter)
        bpp : int = int(self.meta.bytes_per_pixel())
        pngbuff = ptr8(self.pnghotbuff)
        bs : int = int(self.pngbuffsize)
        if t == 0:
            return x
        if t == 1:
            a : int =0
            if relptr % (bs - bpp) >= bpp:
                a = int(pngbuff[(relptr - bpp) % bs])

            return (x + a) & 0xff
        if t == 2:
            b : int = 0
            if relptr >= bs - bpp:
                b = int(pngbuff[(relptr + bpp) % bs])

            return (x + b) & 0xff

        if t == 3:
            a: int = 0
            if relptr % (bs - bpp) >= bpp:
                a = int(pngbuff[(relptr - bpp) % bs])
            b: int = 0
            if relptr >= bs - bpp:
                b = int(pngbuff[(relptr + bpp) % bs])
            return (x + (a + b) // 2) & 0xff

        if t == 4:
            a: int = 0
            if relptr % (bs - bpp) >= bpp:
                a = int(pngbuff[(relptr - bpp) % bs])
            b: int = 0
            if relptr >= bs - bpp:
                b = int(pngbuff[(relptr + bpp) % bs])
            c: int = 0
            if relptr >= bs - bpp and relptr % (bs - bpp) >= bpp:
                c = int(pngbuff[relptr % bs])

            p : int = a + b - c
            pa : int  = abs(p - a)
            pb : int  = abs(p - b)
            pc : int  = abs(p - c)
            Pr : int = 0
            if pa <= pb and pa <= pc:
                Pr = a
            elif pb <= pc:
                Pr = b
            else:
                Pr = c
            return (x + Pr) & 0xff
        raise Exception('unknown filter type')



    # TODO save to flash, not files
    def _save(self):
        if self.ptr < self.halfsize:
            return


        if self.max_savefiles>0:
            file_n = int(self.ptr / self.halfsize) - 1
            f = open(str(file_n) + self.outpath, 'wb')

            if self.ptr % self.hotsize >= self.halfsize:
                f.write(self.hotbuff[0:self.halfsize])
            else:
                f.write(self.hotbuff[self.halfsize:])
            f.close()

            if file_n - self.max_savefiles >= 0:
                os.remove(str(file_n - self.max_savefiles) + self.outpath)

    def _savepng(self):
        pngptr = (self.ptr - self.filter_bytes_skipped) # width + filter byte

        byte = 0
        diffmask = 0
        bitscnt = 0
        ratio_cnt = 0

        bpp = self.meta.bytes_per_pixel()
        dbpp = 4 if self.meta.display_type==png.SEVEN_COLORS else 1
        res_buff = self.res_buff

        list3buff = [0,0,0]

        i = pngptr - (self.pngbuffsize - bpp)
        while i < pngptr:
            if bitscnt//dbpp >= DISPLAY_WIDTH:
                break
            if ratio_cnt <= 0:
                pixel = memoryview(self.pnghotbuff)[i % self.pngbuffsize:i % self.pngbuffsize + bpp]
                # print(str(bytearray(pixel)) + ' -- ' + str(i))


                if self.meta.display_type==png.BINARY_COLOR:
                    byte <<= 1
                    diffmask<<=1



                    mono = self.to_mono(pixel)
                    self.debug_totalmono += mono

                    if self.rowssaved==0 or bitscnt==0 or self.meta.diff0>253:
                        diff = 0
                    else:
                        diff = 0
                        bcnt = min(bpp,3)   # i wont use alpha in diff calculations
                        for j in range(0,bcnt):
                            diff+=abs(pixel[j]-self.colorline_buff_displaywidth[bitscnt*bpp+j])         #up
                            diff+=abs(pixel[j] -self.colorline_buff_displaywidth[bitscnt*bpp-bpp + j])    #left
                        diff//=2*bcnt

                    if self.meta.diff0<=253:
                        for j in range(0, bpp):
                            self.colorline_buff_displaywidth[bitscnt*bpp+j] = pixel[j]

                    if diff>self.meta.mono0:
                        diffmask|=1
                    if mono>self.meta.diff0:
                        byte|=1

                    bitscnt += 1

                    if bitscnt % 8 == 0:
                        byte ^= diffmask #& (~(byte ^ (byte >> 1)) & ~(byte ^ (byte << 1)) & ~(byte ^ self.binary_image_buff[p-DISPLAY_WIDTH_BYTES]))   # only inverse pixels that border same color pixel
                        diffmask=0                                                                                          # yup, losing 2 pixels in horizontal check

                        res_buff[bitscnt//8-1] = byte
                        byte = 0

                elif self.meta.display_type==png.SEVEN_COLORS:
                    byte <<= dbpp
                    if self.meta.use_treshold_map:
                        r=96        #varies
                        pixel2 = list3buff
                        #alpha is ignored
                        pixel2[0] = pixel[0] + (r * self.treshold_map_rot0[(self.rowssaved % 8)*8 + (bitscnt // 4) % 8] // 64 - r // 2)
                        pixel2[1] = pixel[1] + (r * self.treshold_map_rot2[(self.rowssaved % 8)*8 + (bitscnt // 4) % 8] // 64 - r // 2)
                        pixel2[2] = pixel[2] + (r * self.treshold_map_rot1[(self.rowssaved % 8)*8 + (bitscnt // 4) % 8] // 64 - r // 2)

                        byte|=self.meta.get_encoding_7colors(pixel2)

                    else:
                        byte|=self.meta.get_encoding_7colors(pixel)

                    bitscnt+=dbpp
                    if bitscnt%8==0:
                        res_buff[bitscnt//8-1]=byte
                        byte=0

                    pass

                ratio_cnt += self.col_ratio

            ratio_cnt -= 1

            i += bpp

        print()
        if bitscnt//dbpp < DISPLAY_WIDTH:
            for j in range(bitscnt, DISPLAY_WIDTH*dbpp, 8):
                res_buff[j//8] = 0x11 if dbpp==4 else 0xff
        else:
            pass

        self.res_flash_buff.push(res_buff)

        self.rowssaved += 1
        print('row saved, pushed ' + str(self.rowssaved) + ' times')

        if self.rowssaved==self.meta.height:
            for i in range(self.meta.height, DISPLAY_HEIGHT):
                for j in range(0,DISPLAY_WIDTH, 8):
                    self.res_flash_buff.push(bytearray(b'\xff' if dbpp==1 else b'\x11\x11\x11\x11'))



