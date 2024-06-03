import gc
import time
time.sleep(3)           # failsafe
from machine import Pin
import esp
import machine
import libs.png as png
import network
import socket
import libs.winbond as wb
print(gc.mem_alloc())
#gc.enable()
import libs.text as txt
import libs.epd7in3f as epd73





machine.freq(240000000) # set the CPU frequency to 240 MHz
#uart = UART(0, 115200)
time.sleep(3)           # failsafe

esp.osdebug(0)

try:
    ft = open('timings.txt', 'r')
    awake = int(ft.readline())
    sleep = int(ft.readline())
    ft.close()
except:
    ft = open('timings.txt', 'w')
    ft.writelines('110\r\n100\r\n')
    awake=100
    sleep=100
    ft.close()

print('i will listen for connections for ' + str(awake) + 's and sleep for ' + str(sleep) + 's')


spi = machine.SPI(1, baudrate=20_000_000, miso = Pin(19), mosi = Pin(23), sck = Pin(18), polarity = 0, phase=0)
flash_CS = Pin(2,Pin.OUT, value=1)
flash = wb.W25QFlash(spi=spi, cs=flash_CS, baud=20_000_000, software_reset=True)

epd = epd73.EPD(RST_PIN=Pin(12, Pin.OUT),
                DC_PIN=Pin(14, Pin.OUT),
                BUSY_PIN=Pin(13, Pin.IN),
                CS_PIN=Pin(27, Pin.OUT),
                spi=spi)

# epd.init()
# epd.Clear()
# epd.sleep()

print("manuf = " + str(flash.manufacturer))
print("capacity = " + str(flash.capacity))
# fb = wb.WinbondBuff(4 * 4096, flash, readonly=True)
# out_fb = wb.WinbondBuff(1024 * 1024 + 512*1024, flash, readonly=False)
# image_meta = png.PngMeta(fb, out_fb)
# if image_meta!=None:
#     image_meta.init_from_flash()
#     t0 = time.time()
#     png_decoder = png.PngDecoder(image_meta, 32 * 1024)
#     png_decoder.decode_png()
#     t1 = time.time()
#
# epd.init()
# epd.display(image_meta, None)
# epd.sleep()

# out = wb.WinbondBuff(offset = 1024*1024*6, flash=flash)
# out.push(mono.buff.res_buff)

# fontb = wb.WinbondBuff(1024*1024, flash, hotsize=16)
# f = open('glyphs.bin', 'rb')
# bytes = f.read(4096)
# f.close()
# fontb.push(memoryview(bytes))
# bytes=None

gc.collect()

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.config(reconnects=3)
wlan.connect('Bulk', 'beginagain')
while wlan.status()==network.STAT_CONNECTING:
    pass
if not wlan.isconnected():
    wlan.connect('Salo', 'alphabeta')
    if not wlan.isconnected():
        print('no wifi in range... guess i will die!')
        machine.disable_irq()
        machine.deepsleep(sleep)

print('connected... ')
print(wlan.ifconfig())

s : socket.Socket = socket.socket()
s.settimeout(awake)
s.bind(('', 80))
s.listen(3)

image_meta = None
text_meta = None
clear_flag = False

while (True):
    con : socket.Socket

    try:
        con, addr = s.accept()
    except:
        break
    print('caught connection')
    cmd = con.recv(4)
    print(cmd)
    cnt = con.recv(4)
    arg_cnt = int.from_bytes(cnt, 'big')
    if cmd[0:4]==b'INFO':
        print('valid')
        if arg_cnt==0:
            resp = b'OK\r\n5\r\nESP32\r\n'
            con.send(resp)
        else:
            respbody =""
            status="OK"
            for argn in range(0, arg_cnt):
                arg=bytearray(b'\0\0\0\0')
                con.readinto(arg, 4)

                if arg==b'CHRG':
                    respbody+="100"
                elif arg!='STUB':
                    status="ERR"
                    respbody="Unknown arg: " + str(arg)
                    break
            con.send(bytes(status + '\r\n' + str(len(respbody)) + '\r\n' + respbody + '\r\n','utf-8'))

    if cmd[0:4]==b'CYCL':
        print('CYCL setup')
        # cnt = con.recv(4)
        # arg_cnt = (cnt[0] << 24) | (cnt[1] << 16) | (cnt[2] << 8) | cnt[3]
        val = bytearray(b'\0\0\0\0')
        arg = bytearray(b'\0\0\0\0')
        status="OK"
        respbody=""
        for argn in range(0, arg_cnt):
            con.readinto(arg, 4)

            if arg == b'DSLP':
                con.readinto(val, 4)
                sleep = (val[0] << 24) | (val[1] << 16) | (val[2] <<8) | val[3]

            elif arg == b'AWKE':
                con.readinto(val,4)
                awake = (val[0] << 24) | (val[1] << 16) | (val[2] << 8) | val[3]


            elif arg != b'STUB':
                status = "ERR"
                respbody = "Unknown arg: " + str(arg)
                break

        ft = open('timings.txt')
        ft.writelines([str(awake),str(sleep)])
        con.send(bytearray(status + '\r\n' + str(len(respbody)) + '\r\n' + respbody + '\r\n', 'utf-8'))


    if cmd[0:4]==b'IMGE':
        fb = wb.WinbondBuff(4 * 4096, flash, readonly=False, hotsize=256)
        out_fb = wb.WinbondBuff(1024 * 1024 + 512*1024, flash, readonly=False, hotsize=256)
        image_meta = png.PngMeta(fb, out_fb)
        respbody = ""
        status = "ACK"
        for argn in range(0, arg_cnt):
            arg = bytearray(b'\0\0\0\0')
            con.readinto(arg, 4)
            print(arg)

            if (arg==b'SIZE'):
                val = bytearray(b'\0\0\0\0')
                con.readinto(val, 4)
                size = (val[0] << 24) | (val[1] << 16) | (val[2] <<8) | val[3]
                print("SIZE = " + str(size))
                if size>950*1024:
                    status="ERR"
                    respbody="image too big!"
                    try:
                        con.send(bytearray(status + '\r\n'+ str(len(respbody)) + '\r\n' + respbody+'\r\n', 'utf-8'))       #mmmm spaghetti
                    except:
                        pass
                    break
                image_meta.size_bytes=size

                # #prep for writing
                # blocksize = (1024 * 32)
                # blockstart = fb.offset & 0xff7000
                # if fb.offset % blocksize != 0:
                #     blockstart += blocksize
                # for i in range(blockstart, fb.offset + size, blocksize):
                #     fb.flash.block32k_erase(i)


            elif (arg==b'DATA'):
                buff = bytearray(4096)

                for bytesN in range(0, image_meta.size_bytes, 4096):
                    to_read = min(4096, image_meta.size_bytes - bytesN)
                    con.readinto(buff, to_read)
                    print('package of 4kb received, in total ' + str(bytesN//1024 + 4) + 'kB')
                    #print('DEBUG 32b=' + str(bytes(fb.read(0, 32))))
                    if bytesN==0 and memoryview(buff[1:4])!=b'PNG':
                        print('Unknown format received')
                        respbody = "Unknown format"
                        status="ERR"
                        break
                    image_meta.flash_buff.push(memoryview(buff)[0:to_read])

                    gc.collect()

                #con.close()
                                 # allowing gc to do its job
                buff = None
                #wlan.disconnect()
                gc.collect()
                break

            elif arg == b'SCLR':
                clear_flag=True
                pass
            elif arg== b'INVB':
                image_meta.invert_binary = True
                pass

            elif (arg!=b'STUB'):
                status = "ERR"
                respbody = "Unknown arg: " + str(arg)
                break

        try:
            con.send(bytearray('ERR\r\n8\e\r\nNo image\r\n', 'utf-8'))
        except:
            pass
        break

    if cmd[0:4]==b'TEXT':
        size = 0
        respbody = ""
        status = "ACK"
        text_meta = txt.TextMeta(flash)
        arg = bytearray(b'\0\0\0\0')
        val = bytearray(b'\0\0\0\0')

        for argn in range(0, arg_cnt):
            con.readinto(arg)
            print(arg)

            if (arg==b'SIZE'):
                con.readinto(val,4)
                size = (val[0] << 24) | (val[1] << 16) | (val[2] <<8) | val[3]
                print("SIZE = " + str(size))
            elif (arg==b'DATA'):
                text = con.recv(size)
                print("TEXT = " + str(text))
                text_meta.fill_bitmap_rows(text)
                mul = 2 if text_meta.double_on_display else 1
                if text_meta.x.to_bytes(4, 'big') == b'CENT':
                    text_meta.x = epd73.EPD_WIDTH//2 - text_meta.width_bits//2*mul
                if text_meta.y.to_bytes(4, 'big') == b'CENT':
                    text_meta.y = epd73.EPD_HEIGHT//2 - text_meta.height_bits // 2*mul

            elif(arg==b'POSX'):
                con.readinto(val, 4)
                # if val!=b'CENT':
                text_meta.x = (val[0] << 24) | (val[1] << 16) | (val[2] <<8) | val[3]
                # else:
                #     text_meta.x = epd73.EPD_WIDTH - text_meta.width_bits//2

            elif (arg == b'POSY'):
                con.readinto(val, 4)
                # if val != b'CENT':
                text_meta.y = (val[0] << 24) | (val[1] << 16) | (val[2] << 8) | val[3]
                # else:
                #     text_meta.y = epd73.EPD_HEIGHT - text_meta.height_bits//2

            elif (arg==b'TRSP'):
                text_meta.bgcolor = None

            elif (arg==b'TCLR'):
                con.readinto(val,4)
                print('color = ' + str(val))
                # one day i will rewrite it. one day.. some day...
                if val==b'BLCK':
                    text_meta.textcolor = text_meta.BLACK
                elif val==b'WHTE':
                    text_meta.textcolor = text_meta.WHITE
                    if text_meta.bgcolor!=None:
                        text_meta.bgcolor = text_meta.BLACK
                elif val==b'GREN':
                    text_meta.textcolor = text_meta.GREEN
                elif val==b'BLUE':
                    text_meta.textcolor = text_meta.BLUE
                elif val==b'XRED':
                    text_meta.textcolor = text_meta.RED
                elif val==b'YELW':
                    text_meta.textcolor = text_meta.YELLOW
                elif val==b'ORNG':
                    text_meta.textcolor = text_meta.ORANGE


            elif (arg!=b'STUB'):
                status = "ERR"
                respbody = "Unknown arg: " + str(arg)
                break

        con.send(bytearray(str(status + '\r\n' + str(len(respbody)) + '\r\n' + respbody + '\r\n'),'utf-8'))
        break

    time.sleep_ms(500)
    print('...')


wlan.disconnect()
wlan=None
buff=None
con = None
gc.collect()

epd = epd73.EPD(RST_PIN=Pin(12, Pin.OUT),
                DC_PIN=Pin(14, Pin.OUT),
                BUSY_PIN=Pin(13, Pin.IN),
                CS_PIN=Pin(27, Pin.OUT),
                spi=spi)

if clear_flag:
    epd.init()
    epd.Clear()
    epd.sleep()

if image_meta!=None:
    image_meta.init_from_flash()
    t0 = time.time()
    png_decoder = png.PngDecoder(image_meta, 32 * 1024)
    png_decoder.decode_png()
    t1 = time.time()




if (image_meta==None and text_meta==None):
    print('got nothing for awake period! (' + str(awake) + ')\r\nentering deepsleep...')
    machine.disable_irq()
    machine.deepsleep(sleep*1000)

if image_meta==None:
    image_meta = png.PngMeta(wb.WinbondBuff(4096 * 4, flash, readonly=True, hotsize=16, no_erase=True),
                             wb.WinbondBuff(1024 * 1024 + 512 * 1024, flash, readonly=True, hotsize=4096,
                                            no_erase=True))

epd.init()
epd.display(image_meta, text_meta)
epd.sleep()
print('my job here is done... entering deepsleep')
machine.disable_irq()
machine.deepsleep(sleep*1000)