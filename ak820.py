#!/usr/bin/env python3
"""AJAZZ AK820 Pro (USB 0c45:8009) RGB + TFT screen tool for Linux.

Protocol recovered from the vendor's DeviceDriver.exe v1.0.0.5:
  - commands: 64-byte HID feature reports on the vendor interface (usage page 0xff13)
  - screen data: 4096-byte output reports on the vendor interface (usage page 0xff68)
"""
import argparse, fcntl, glob, os, select, sys, time

__version__ = "0.1.0"

VID_PIDS = {(0x0C45, 0x8009), (0x0C45, 0x800A)}
DELAY = 0.035  # <cmd_delaytime value="35"/> from the vendor's rgb-keyboard.xml
W = H = 128    # <screen width="128" height="128" gif_headlength="256" gif_maxframes="140"/>
HEAD, MAX_FRAMES, CHUNK = 256, 140, 4096

# mode id -> (name, flags).  flags from the vendor's default table: 1=brightness 2=speed
# 4=horizontal direction 8=vertical direction 0x10=color 0x20=rainbow.
# Direction, tested on hardware: 0/3 = left->right (rolling) or down (scrolling), 1/2 = the reverse.
MODES = {
    0: ("off", 0x00), 1: ("static", 0x31), 2: ("singleon", 0x33), 3: ("singleoff", 0x33),
    4: ("glittering", 0x33), 5: ("falling", 0x33), 6: ("colourful", 0x03), 7: ("breath", 0x33),
    8: ("spectrum", 0x03), 9: ("outward", 0x33), 10: ("scrolling", 0x3B), 11: ("rolling", 0x37),
    12: ("rotating", 0x37), 13: ("explode", 0x33), 14: ("launch", 0x33), 15: ("ripples", 0x33),
    16: ("flowing", 0x37), 17: ("pulsating", 0x33), 18: ("tilt", 0x37), 19: ("shuttle", 0x33),
}
MODE_BY_NAME = {n: i for i, (n, _) in MODES.items()}

# key name -> light_index, from the vendor's layouts/rgb-keyboard.xml
KEYS = dict(
    esc=1, f1=2, f2=3, f3=4, f4=5, f5=6, f6=7, f7=8, f8=9, f9=10, f10=11, f11=12, f12=13, delete=119,
    grave=19, **{"1": 20, "2": 21, "3": 22, "4": 23, "5": 24, "6": 25, "7": 26, "8": 27, "9": 28, "0": 29},
    minus=30, equal=31, backspace=103, home=117,
    tab=37, q=38, w=39, e=40, r=41, t=42, y=43, u=44, i=45, o=46, p=47, lbracket=48, rbracket=49,
    backslash=67, pgup=118,
    capslock=55, a=56, s=57, d=58, f=59, g=60, h=61, j=62, k=63, l=64, semicolon=65, quote=66,
    enter=85, pgdn=121,
    lshift=73, z=74, x=75, c=76, v=77, b=78, n=79, m=80, comma=81, period=82, slash=83, rshift=84, up=101,
    lctrl=91, win=92, lalt=93, space=94, ralt=95, fn=96, rctrl=98, left=99, down=100, right=102,
)


def ioc(nr, size):  # _IOC(_IOC_READ|_IOC_WRITE, 'H', nr, size)
    return (3 << 30) | (size << 16) | (ord("H") << 8) | nr


def find_hidraw(usage_page):
    """hidraw node of the keyboard whose report descriptor starts with Usage Page (usage_page)."""
    tag = bytes([0x06, usage_page & 0xFF, usage_page >> 8])
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        ue = open(node + "/device/uevent").read()
        hid_id = next(l for l in ue.splitlines() if l.startswith("HID_ID=")).split("=")[1]
        _, vid, pid = (int(x, 16) for x in hid_id.split(":"))
        if (vid, pid) in VID_PIDS and open(node + "/device/report_descriptor", "rb").read().startswith(tag):
            return "/dev/" + os.path.basename(node)
    sys.exit(f"AK820 interface 0x{usage_page:04x} not found (USB cable plugged in? udev rule installed?)")


class Kbd:
    def __init__(self):
        self.fd = os.open(find_hidraw(0xFF13), os.O_RDWR)
        self.lcd = None

    def feature(self, data, readback=True):
        """Mirrors the vendor's send routine: sleep, SetFeature(65 bytes), sleep, GetFeature."""
        for off in range(0, len(data), 64):
            time.sleep(DELAY)
            fcntl.ioctl(self.fd, ioc(0x06, 65), b"\0" + data[off:off + 64].ljust(64, b"\0"))
            if readback:
                time.sleep(DELAY)
                fcntl.ioctl(self.fd, ioc(0x07, 65), bytearray(65))

    def cmd(self, op, count=0, extra=b"", readback=True):
        """0x04 <op> header; byte 8 (and 9) = number of 64-byte (or 4 KiB) data packets that follow."""
        p = bytearray(64)
        p[0], p[1] = 0x04, op
        p[2:2 + len(extra)] = extra
        p[8], p[9] = count & 0xFF, count >> 8
        self.feature(bytes(p), readback)

    def lcd_write(self, chunk):
        if self.lcd is None:
            self.lcd = os.open(find_hidraw(0xFF68), os.O_RDWR)
        os.write(self.lcd, b"\0" + chunk)
        if select.select([self.lcd], [], [], 0.3)[0]:  # vendor waits up to 300 ms for an ack
            os.read(self.lcd, 64)

    def set_mode(self, mode, rgb=None, brightness=5, speed=3, direction=0):
        """Built-in effect; rgb=None means rainbow."""
        self.cmd(0x18)
        self.cmd(0x13, 1)
        self.feature(light_packet(mode, rgb or (255, 0, 0), rgb is None, brightness, speed, direction),
                     readback=False)
        self.cmd(0x02)
        self.cmd(0xF0, readback=False)

    def set_keys(self, colors, brightness=5):
        """colors: {light_index: (r,g,b)}. Vendor sequence: custom mode 0x80 + brightness, then the colors."""
        p = bytearray(64); p[0], p[9] = 0x80, brightness; p[14:16] = b"\xaa\x55"
        for op, count, data in ((0x13, 1, bytes(p)), (0x23, 9, keys_packet(colors))):
            self.cmd(0x18)
            self.cmd(op, count)
            self.feature(data, readback=False)
            self.cmd(0x02)
            self.cmd(0xF0, readback=False)

    def upload_screen(self, blob, progress=lambda i, n: None):
        n = len(blob) // CHUNK
        self.cmd(0x18)
        self.cmd(0x72, n, extra=b"\x01")  # byte 2 = screen slot (gif_count=1)
        for i in range(n):
            self.lcd_write(blob[i * CHUNK:(i + 1) * CHUNK])
            progress(i + 1, n)
        self.cmd(0x02)

    def sync_time(self):
        self.cmd(0x18)
        self.cmd(0x28, 1)
        self.feature(time_packet(time.localtime()))
        self.cmd(0x02)


def light_packet(mode, rgb, rainbow, brightness, speed, direction):
    p = bytearray(64)
    p[0] = mode
    if mode:
        p[1:4] = bytes(rgb)
        p[8], p[9], p[10], p[11] = int(rainbow), brightness, speed, direction
    p[14:16] = b"\xaa\x55"
    return bytes(p)


def keys_packet(colors):
    """colors: {light_index: (r,g,b)} -> 576 bytes (144 slots of index,r,g,b) ending in aa 55."""
    p = bytearray(0x240)
    for idx, (r, g, b) in colors.items():
        p[idx * 4:idx * 4 + 4] = bytes([idx, r, g, b])
    p[0x23E:0x240] = b"\xaa\x55"
    return bytes(p)


def time_packet(t, slot=1):
    p = bytearray(64)
    p[1], p[2] = slot, 0x5A
    p[3:9] = bytes([t.tm_year % 2000, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec])
    p[10] = (t.tm_wday + 1) % 7  # Windows wDayOfWeek: Sunday=0
    p[62:64] = b"\xaa\x55"
    return bytes(p)


def rgb565(img):
    """Pillow RGB image (W x H) -> little-endian RGB565 bytes, like mui.dll GetImageRGB565Data."""
    out, px = bytearray(), img.tobytes()
    for i in range(0, len(px), 3):
        r, g, b = px[i:i + 3]
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out += bytes([v & 0xFF, v >> 8])
    return out


def screen_blob(frames):
    """frames: [(rgb565_bytes, delay_ms)] -> header + frames, padded with 0xff to 4 KiB chunks."""
    frames = frames[:MAX_FRAMES]
    head = bytearray(b"\xff" * HEAD)
    head[0] = len(frames)
    for i, (_, ms) in enumerate(frames):
        head[1 + i] = min(255, max(1, ms // 2))  # unit is 2 ms
    blob = head + b"".join(f for f, _ in frames)
    return bytes(blob + b"\xff" * (-len(blob) % CHUNK))


def load_frames(path, fit):
    from PIL import Image, ImageOps, ImageSequence
    im = Image.open(path)
    frames = []
    for fr in ImageSequence.Iterator(im):
        f = fr.convert("RGB")
        f = ImageOps.fit(f, (W, H)) if fit == "crop" else ImageOps.pad(f, (W, H))
        frames.append((rgb565(f), fr.info.get("duration", 100) or 100))
    return frames


def hexrgb(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mode", help="built-in lighting effect")
    m.add_argument("mode", help="name or number: " + ", ".join(f"{i}={n}" for i, (n, _) in MODES.items()))
    m.add_argument("-c", "--color", type=hexrgb, help="RRGGBB (turns rainbow off)")
    m.add_argument("-b", "--brightness", type=int, default=5, choices=range(6))
    m.add_argument("-s", "--speed", type=int, default=3, choices=range(6))
    m.add_argument("-d", "--direction", type=int, default=0, choices=(0, 1),
                   help="0 = left->right / down, 1 = right->left / up (effects that move)")
    k = sub.add_parser("keys", help="per-key static colors, e.g.: keys --all 000020 w=ff0000 a=ff0000")
    k.add_argument("assign", nargs="*", help="key=RRGGBB (names: --list)")
    k.add_argument("--all", type=hexrgb, help="base color for every key")
    k.add_argument("-b", "--brightness", type=int, default=5, choices=range(6))
    k.add_argument("--list", action="store_true", help="print key names")
    s = sub.add_parser("screen", help="upload an image or animated GIF to the 128x128 screen")
    s.add_argument("image")
    s.add_argument("--fit", choices=["crop", "pad"], default="crop")
    sub.add_parser("time", help="sync the screen clock to this PC")
    sub.add_parser("selftest", help="check packet builders (no keyboard needed)")
    a = ap.parse_args()

    if a.cmd == "selftest":
        return selftest()
    if a.cmd == "keys" and a.list:
        return print(" ".join(KEYS))

    kb = Kbd()
    if a.cmd == "mode":
        mode = MODE_BY_NAME.get(a.mode.lower()) if not a.mode.isdigit() else int(a.mode)
        if mode not in MODES:
            sys.exit(f"unknown mode {a.mode}")
        kb.set_mode(mode, a.color, a.brightness, a.speed, a.direction)
    elif a.cmd == "keys":
        colors = {i: a.all or (0, 0, 0) for i in KEYS.values()}
        for kv in a.assign:
            name, _, col = kv.partition("=")
            if name.lower() not in KEYS:
                sys.exit(f"unknown key {name} (see --list)")
            colors[KEYS[name.lower()]] = hexrgb(col)
        kb.set_keys(colors, a.brightness)
    elif a.cmd == "screen":
        kb.upload_screen(screen_blob(load_frames(a.image, a.fit)),
                         lambda i, n: print(f"\r{100 * i // n}%", end="", flush=True))
        print()
    elif a.cmd == "time":
        kb.sync_time()


def selftest():
    p = light_packet(1, (0x11, 0x22, 0x33), False, 5, 3, 2)
    assert p[:4] == b"\x01\x11\x22\x33" and p[8:12] == b"\x00\x05\x03\x02" and p[14:16] == b"\xaa\x55"
    assert light_packet(0, (1, 2, 3), True, 5, 3, 0)[:12] == bytes(12)
    k = keys_packet({1: (255, 0, 0), 121: (0, 0, 255)})
    assert len(k) == 576 and k[4:8] == b"\x01\xff\x00\x00" and k[484:488] == b"\x79\x00\x00\xff" and k[-2:] == b"\xaa\x55"
    t = time_packet(time.struct_time((2026, 10, 14, 21, 5, 9, 2, 287, 0)))
    assert t[1:9] == bytes([1, 0x5A, 26, 10, 14, 21, 5, 9]) and t[10] == 3 and t[62:] == b"\xaa\x55"
    from PIL import Image
    assert rgb565(Image.new("RGB", (1, 1), (255, 0, 0))) == b"\x00\xf8"
    assert rgb565(Image.new("RGB", (1, 1), (0, 0, 255))) == b"\x1f\x00"
    b = screen_blob([(b"\0" * W * H * 2, 100)] * 2)
    assert len(b) == 69632 and b[0] == 2 and b[1:3] == b"\x32\x32" and b[3] == 0xFF and b[-1] == 0xFF
    assert ioc(0x06, 65) == 0xC0414806
    print("selftest ok")


if __name__ == "__main__":
    main()
