import libs.winbond as wb


class TextMeta:
    x=0
    y=0
    double_on_display=True

    BLACK = 0
    WHITE = 1
    GREEN = 2
    BLUE = 3
    RED = 4
    YELLOW = 5
    ORANGE = 6

    textcolor = BLACK
    bgcolor = WHITE



    FONT_PTR = 1024*1024
    OUTPUT_PTR = 1024*1024 + 64*1024
    width_bits = 0
    height_bits = 16
    CHAR_BIT_WIDTH = 8
    CHAR_BIT_HEIGHT = 16
    FONT_CHAR_OFFSET=0
    FONT_CHAR_CNT = 256


    def __init__(self, flash : wb.W25QFlash):
        self.font_reader = wb.WinbondBuff(self.FONT_PTR, flash, readonly=True)
        self.bitmap_reader = wb.WinbondBuff(self.OUTPUT_PTR, flash, readonly=True)
        pass


    def fill_bitmap_rows(self, str : bytearray):
        bitmap_writer = wb.WinbondBuff(self.OUTPUT_PTR, self.bitmap_reader.flash, readonly=False)
        self.width_bits = self.CHAR_BIT_WIDTH * len(str)
        for row in range(0, self.CHAR_BIT_HEIGHT*self.CHAR_BIT_WIDTH//8, self.CHAR_BIT_WIDTH//8):
            for i in range(0, len(str)):
                c = str[i]
                if c==0:
                    break

                if c<self.FONT_CHAR_OFFSET or c>=self.FONT_CHAR_OFFSET+self.FONT_CHAR_CNT:
                    c=32   # space

                ptr = (c-self.FONT_CHAR_OFFSET)*self.CHAR_BIT_HEIGHT*self.CHAR_BIT_WIDTH//8+row*self.CHAR_BIT_WIDTH//8
                
                bitmap_writer.push(self.font_reader.read(ptr, self.CHAR_BIT_WIDTH//8))


