# *****************************************************************************
# * | File        :	  epd7in3f.py
# * | Author      :   Waveshare team
# * | Function    :   Electronic paper driver
# * | Info        :
# *----------------
# * | This version:   V1.0
# * | Date        :   2022-10-20
# # | Info        :   python demo
# -----------------------------------------------------------------------------
# ******************************************************************************/
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documnetation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to  whom the Software is
# furished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS OR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
import time
import libs.winbond as wb
import libs.png as png
import libs.text as txt

# Display resolution
EPD_WIDTH       = 800
EPD_HEIGHT      = 480


class EPD:
    onebytebuff = bytearray(1)
    def __init__(self, RST_PIN, DC_PIN, BUSY_PIN, CS_PIN, spi):
        self.reset_pin = RST_PIN
        self.dc_pin = DC_PIN
        self.busy_pin = BUSY_PIN
        self.cs_pin = CS_PIN
        self.width = EPD_WIDTH
        self.height = EPD_HEIGHT
        self.spi=spi
        self.BLACK  = 0x000000   #   0000  BGR
        self.WHITE  = 0xffffff   #   0001
        self.GREEN  = 0x00ff00   #   0010
        self.BLUE   = 0xff0000   #   0011
        self.RED    = 0x0000ff   #   0100
        self.YELLOW = 0x00ffff   #   0101
        self.ORANGE = 0x0080ff   #   0110
        
    # Hardware reset
    def reset(self):
        self.reset_pin.value(1)
        time.sleep_ms(20)
        self.reset_pin.value(0)      # module reset
        time.sleep_ms(20)
        self.reset_pin.value(1)
        time.sleep_ms(20)


    def write_cmd(self, cmd):
        self.onebytebuff[0]=cmd
        self.cs_pin.value(0)
        self.dc_pin.value(0)
        time.sleep_ms(1)
        mask = 0x80
        self.spi.write(self.onebytebuff)
        time.sleep_ms(1)
        self.cs_pin.value(1)

    def write_data(self, data, hold_cs=False, is_arr=False):
        if not is_arr:
            # fragmentation problems here
            b = self.onebytebuff
            b[0] = data
        else:
            b = data
        self.cs_pin.value(0)
        self.dc_pin.value(1)
        self.spi.write(b)

        if not hold_cs:
            self.cs_pin.value(1)

    def ReadBusyH(self):
        while(self.busy_pin.value()==0):      # 0: busy, 1: idle
            time.sleep_ms(5)

        print('wake')


    def TurnOnDisplay(self):
        self.write_cmd(0x04) # POWER_ON
        self.ReadBusyH()

        self.write_cmd(0x12) # DISPLAY_REFRESH
        self.write_data(0X00)
        self.ReadBusyH()
        
        self.write_cmd(0x02) # POWER_OFF
        self.write_data(0X00)
        self.ReadBusyH()
        
    def init(self):
        # EPD hardware init start
        self.reset()
        self.ReadBusyH()
        time.sleep_ms(30)

        self.write_cmd(0xAA)    # CMDH
        self.write_data(0x49)
        self.write_data(0x55)
        self.write_data(0x20)
        self.write_data(0x08)
        self.write_data(0x09)
        self.write_data(0x18)

        self.write_cmd(0x01)
        self.write_data(0x3F)
        self.write_data(0x00)
        self.write_data(0x32)
        self.write_data(0x2A)
        self.write_data(0x0E)
        self.write_data(0x2A)

        self.write_cmd(0x00)
        self.write_data(0x5F)
        self.write_data(0x69)

        self.write_cmd(0x03)
        self.write_data(0x00)
        self.write_data(0x54)
        self.write_data(0x00)
        self.write_data(0x44)

        self.write_cmd(0x05)
        self.write_data(0x40)
        self.write_data(0x1F)
        self.write_data(0x1F)
        self.write_data(0x2C)

        self.write_cmd(0x06)
        self.write_data(0x6F)
        self.write_data(0x1F)
        self.write_data(0x1F)
        self.write_data(0x22)

        self.write_cmd(0x08)
        self.write_data(0x6F)
        self.write_data(0x1F)
        self.write_data(0x1F)
        self.write_data(0x22)

        self.write_cmd(0x13)    # IPC
        self.write_data(0x00)
        self.write_data(0x04)

        self.write_cmd(0x30)
        self.write_data(0x3C)

        self.write_cmd(0x41)     # TSE
        self.write_data(0x00)

        self.write_cmd(0x50)
        self.write_data(0x3F)

        self.write_cmd(0x60)
        self.write_data(0x02)
        self.write_data(0x00)

        self.write_cmd(0x61)
        self.write_data(0x03)
        self.write_data(0x20)
        self.write_data(0x01)
        self.write_data(0xE0)

        self.write_cmd(0x82)
        self.write_data(0x1E)

        self.write_cmd(0x84)
        self.write_data(0x00)

        self.write_cmd(0x86)    # AGID
        self.write_data(0x00)

        self.write_cmd(0xE3)
        self.write_data(0x2F)

        self.write_cmd(0xE0)   # CCSET
        self.write_data(0x00)

        self.write_cmd(0xE6)   # TSSET
        self.write_data(0x00)
        return 0

    def display(self, image : png.PngMeta = None, text : txt.TextMeta = None):
        if image==None and text == None:
            raise Exception("someone forgot args!")

        if text!=None:
            print("text width = " + str(text.width_bits))
            print("text height = " + str(text.height_bits))
            print("text x = " + str(text.x))
            print("text y = " + str(text.y))


        self.write_cmd(0x10)
        mask=0x80
        for i in range(0,self.width*self.height//2):
            byte=0
            if image!=None:
                if image.display_type== png.BINARY_COLOR:
                    if (image.processed_image_buff.read(i//4,1)[0] & mask) ^ image.invert_binary:
                        byte|=0b0001    #white
                    else:
                        byte|=0b0000    #black

                    byte <<=4
                    if image.processed_image_buff.read(i//4,1)[0] & (mask >> 1):
                        byte|=0b0001
                    else:
                        byte|=0b0000
                else:
                    byte = bytearray(image.processed_image_buff.read(i,1))[0]

            if text!=None:
                # can be optimized, but.. no
                x = (i%400) * 2
                y = i//400

                dx = x - text.x
                dy = y - text.y
                mul = 2 if text.double_on_display else 1

                if (dx>=0 and dx<text.width_bits*mul) and (dy>=0 and dy < text.height_bits*mul):
                    print("its texting time!!!")
                    if text.bgcolor!=None:
                        byte = (text.bgcolor << 4) | (text.bgcolor)
                    tmp = text.bitmap_reader.read(dx//mul//8+dy//mul*text.width_bits//8, 1)[0]

                    if text.double_on_display:
                        if tmp & (1 << (7 - ((dx//2)%8))):
                            byte = (text.textcolor << 4) | (text.textcolor)
                    else:

                        if tmp & mask:
                            byte&=0b00001111
                            byte+=text.textcolor << 4

                        if tmp & (mask >> 1):
                            byte &= 0b11110000
                            byte += text.textcolor


            self.write_data(byte)
            mask>>=2
            if mask==0:
                mask=0x80

            # self.write_data(image, is_arr=True)

        self.TurnOnDisplay()
        
    def Clear(self, color=0x11):
        self.write_cmd(0x10)
        for i in range(self.width * self.height//2):
            self.write_data(color)

        self.TurnOnDisplay()

    def sleep(self):
        self.write_cmd(0x07) # DEEP_SLEEP
        self.write_data(0XA5)
        
        time.sleep_ms(2000)
### END OF FILE ###

