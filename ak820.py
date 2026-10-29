#!/usr/bin/env python3
"""AJAZZ AK820 Pro (USB 0c45:8009) RGB + TFT screen tool for Linux.

Protocol recovered from the vendor's DeviceDriver.exe v1.0.0.5:
  - commands: 64-byte HID feature reports on the vendor interface (usage page 0xff13)
  - screen data: 4096-byte output reports on the vendor interface (usage page 0xff68)
"""
import argparse, array, colorsys, fcntl, glob, os, select, shutil, subprocess, sys, time

__version__ = "0.3.3"

VID_PIDS = {(0x0C45, 0x8009), (0x0C45, 0x800A)}
# same text as 70-ak820.rules (selftest checks), so a packaged copy without that file can still install it
RULE_PATH = "/etc/udev/rules.d/70-ak820.rules"
UDEV_RULE = "# AJAZZ AK820 Pro: let the logged-in user open its hidraw nodes (used by ak820.py)\n" + "".join(
    f'KERNEL=="hidraw*", ATTRS{{idVendor}}=="{v:04x}", ATTRS{{idProduct}}=="{p:04x}", TAG+="uaccess"\n'
    for v, p in sorted(VID_PIDS))
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
ROW_ENDS = {"delete", "home", "pgup", "pgdn", "up", "right"}  # last key of each row, in KEYS order


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


class NoPermission(SystemExit):
    """The keyboard is there but this user may not open it; exits like sys.exit, the GUI catches it to offer setup."""


def open_hidraw(usage_page):
    path = find_hidraw(usage_page)
    try:
        return os.open(path, os.O_RDWR)
    except PermissionError:
        raise NoPermission(f"no permission to open {path}; run 'ak820 setup' once to allow your user")


def setup():
    """Install UDEV_RULE and apply it to the plugged-in keyboard. Asks for the password via pkexec (sudo without it)."""
    script = ('cat > "$1" && chmod 644 "$1" && udevadm control --reload && '
              'udevadm trigger --subsystem-match=hidraw && udevadm settle')
    cmd = ["sh", "-c", script, "sh", RULE_PATH]
    if os.geteuid():
        cmd = (["pkexec"] if shutil.which("pkexec") else ["sudo"]) + cmd
    if subprocess.run(cmd, input=UDEV_RULE.encode()).returncode:
        sys.exit("udev rule not installed (password dialog cancelled?)")


class Kbd:
    def __init__(self):
        self.fd = open_hidraw(0xFF13)
        self.lcd = None

    def feature(self, data, readback=True, delay=DELAY):
        """Mirrors the vendor's send routine: sleep, SetFeature(65 bytes), sleep, GetFeature."""
        for off in range(0, len(data), 64):
            time.sleep(delay)
            fcntl.ioctl(self.fd, ioc(0x06, 65), b"\0" + data[off:off + 64].ljust(64, b"\0"))
            if readback:
                time.sleep(delay)
                fcntl.ioctl(self.fd, ioc(0x07, 65), bytearray(65))

    def cmd(self, op, count=0, extra=b"", readback=True, delay=DELAY):
        """0x04 <op> header; byte 8 (and 9) = number of 64-byte (or 4 KiB) data packets that follow."""
        p = bytearray(64)
        p[0], p[1] = 0x04, op
        p[2:2 + len(extra)] = extra
        p[8], p[9] = count & 0xFF, count >> 8
        self.feature(bytes(p), readback, delay)

    def lcd_write(self, chunk):
        if self.lcd is None:
            self.lcd = open_hidraw(0xFF68)
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

    def live(self, colors):
        """One real-time frame, as the vendor's music page sends it: no session, not saved to flash."""
        self.cmd(0x20, 8, delay=0.005)
        self.feature(live_packet(colors), readback=False, delay=0.002)
        self.cmd(0x02, delay=0.005)

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


def live_packet(colors):
    """colors: {light_index: (r,g,b)} -> 512 bytes of consecutive (index, r, g, b) entries, at most 128."""
    return b"".join(bytes([i, *rgb]) for i, rgb in sorted(colors.items())[:128]).ljust(512, b"\0")


def key_grid():
    """light_index -> (x, y): position 0..1 in its row (left->right) and row 0..1 (top->bottom)."""
    # ponytail: rank in the row, not physical position (space counts as one key); use key widths if it looks off
    rows, row = [], []
    for name, idx in KEYS.items():
        row.append(idx)
        if name in ROW_ENDS:
            rows.append(row)
            row = []
    return {idx: (i / (len(r) - 1), j / (len(rows) - 1)) for j, r in enumerate(rows) for i, idx in enumerate(r)}


def grad(t, colors=None):
    """t 0..1 -> rgb. colors: None = green->yellow->red, "rainbow", or a (from_rgb, to_rgb) pair."""
    if colors == "rainbow":
        return tuple(int(255 * c) for c in colorsys.hsv_to_rgb(0.8 * t, 1, 1))
    if colors:
        (r1, g1, b1), (r2, g2, b2) = colors
        return int(r1 + (r2 - r1) * t), int(g1 + (g2 - g1) * t), int(b1 + (b2 - b1) * t)
    return min(255, int(510 * t)), min(255, int(510 * (1 - t))), 0


STYLES = ("meter", "center", "spectrum", "pulse")
BANDS = 16    # spectrum columns
TILT = 0.15   # spectrum: boost per band so treble isn't always lower than bass (music falls ~3 dB/octave)


def render(style, grid, colors, level=0.0, bands=(), pulse=(0.0, 0.0)):
    """One music frame {light_index: rgb}. level 0..1; bands: BANDS values 0..1; pulse: (strength 0..1, color t)."""
    if style == "pulse":
        k, t = pulse
        c = tuple(int(v * k) for v in grad(t, colors))
        return {i: c for i in grid}
    out = {}
    for i, (x, y) in grid.items():
        if style == "spectrum":  # column = band (bass left), rows fill from the bottom
            h = 1 - y
            lit = bands[round(x * (len(bands) - 1))] > h * 0.9 + 0.05
        else:  # meter fills left->right, center fills outwards
            h = abs(x - 0.5) * 2 if style == "center" else x
            lit = h < level
        out[i] = grad(h, colors) if lit else (0, 0, 0)
    return out


def rms(pcm):
    """Loudness 0..1 of signed 16-bit little-endian mono samples."""
    a = array.array("h", pcm[len(pcm) % 2:])
    return (sum(v * v for v in a) / len(a)) ** 0.5 / 32768 if a else 0.0


def spectrum(pcm, n=BANDS, rate=44100):
    """Log-spaced band levels (40 Hz..16 kHz, natural-log magnitude) of s16le mono samples."""
    try:
        import numpy as np
    except ImportError:
        sys.exit("the spectrum style needs numpy (Fedora: python3-numpy, Debian/Ubuntu: python3-numpy)")
    a = np.frombuffer(pcm[len(pcm) % 2:], "<i2").astype(float)
    mag = np.abs(np.fft.rfft(a * np.hanning(len(a))))
    freqs = np.fft.rfftfreq(len(a), 1 / rate)
    edges = np.geomspace(40, 16000, n + 1)
    return [float(np.log1p(mag[(freqs >= lo) & (freqs < hi)].mean())) if ((freqs >= lo) & (freqs < hi)).any()
            else 0.0 for lo, hi in zip(edges, edges[1:])]


def music(kb, opts=lambda: {}, stop=lambda: False):
    """Light the keys from whatever the system is playing until stop() is true.
    opts() is read every frame: dict(style=STYLES item, gain=sensitivity, colors=see grad)."""
    try:
        rec = subprocess.Popen(["parec", "--device=@DEFAULT_MONITOR@", "--format=s16le", "--rate=44100",
                                "--channels=1", "--latency-msec=20", "--raw"], stdout=subprocess.PIPE)
    except FileNotFoundError:
        sys.exit("music needs parec (Fedora: pulseaudio-utils, Debian/Ubuntu: pulseaudio-utils)")
    fd, buf, grid = rec.stdout.fileno(), b"", key_grid()
    peak, shown, bpeak, bshown = 0.05, 0.0, 1.0, [0.0] * BANDS
    avg, k, t, last_beat = 0.0, 0.0, 0.0, 0.0
    os.set_blocking(fd, False)
    try:
        while not stop():
            o = opts()
            style, gain, colors = o.get("style", "meter"), o.get("gain", 1.0), o.get("colors")
            try:
                chunk = os.read(fd, 65536)
                if not chunk:
                    sys.exit("parec stopped (no audio server?)")
                buf = (buf + chunk)[-8192:]  # newest ~93 ms; older audio is already stale
            except BlockingIOError:
                pass
            level = rms(buf[-2048:])
            peak = max(level, peak * 0.995, 0.01)  # auto gain: follows the loudest recent moment
            shown = max(min(1.0, level / peak * gain), shown * 0.8)  # fast attack, smooth fall
            if style == "spectrum" and len(buf) >= 4096:
                raw = [v + TILT * i for i, v in enumerate(spectrum(buf))]
                bpeak = max(max(raw), bpeak * 0.995, 1.0)
                # show the top 4*gain log units (~35 dB at gain 1) under the recent peak
                bshown = [max(min(1.0, max(0.0, 1 - (bpeak - v) / (4 * gain))), s * 0.8) for v, s in zip(raw, bshown)]
            now = time.monotonic()
            if level * gain > avg * 1.5 and level > 0.01 and now - last_beat > 0.15:  # beat: jump above the average
                k, t, last_beat = 1.0, (t + 0.37) % 1, now
            else:
                k *= 0.8
            avg = avg * 0.9 + level * 0.1
            kb.live(render(style, grid, colors, shown, bshown, (k, t)))  # ~60 ms per frame paces the loop
    finally:
        rec.terminate()


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


def palette(s):
    """--colors value -> grad() colors: classic -> None, rainbow, or RRGGBB-RRGGBB -> pair of rgb."""
    if s in ("classic", "rainbow"):
        return None if s == "classic" else s
    try:
        c1, c2 = s.split("-")
        return hexrgb(c1), hexrgb(c2)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{s!r}: use classic, rainbow or RRGGBB-RRGGBB")


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
    mu = sub.add_parser("music", help="level meter of the system audio on the keys, until Ctrl-C")
    mu.add_argument("-g", "--gain", type=float, default=1.0, help="sensitivity (default 1.0)")
    mu.add_argument("--style", choices=STYLES, default="meter",
                    help="meter: fills left->right, center: fills outwards, spectrum: equalizer (needs numpy), "
                         "pulse: whole keyboard flashes on beats")
    mu.add_argument("--colors", type=palette, default="classic",
                    help="classic (green->yellow->red), rainbow, or two colors RRGGBB-RRGGBB")
    sub.add_parser("setup", help="allow your user to open the keyboard (installs a udev rule, asks for your password)")
    sub.add_parser("selftest", help="check packet builders (no keyboard needed)")
    a = ap.parse_args()

    if a.cmd == "selftest":
        return selftest()
    if a.cmd == "setup":
        setup()
        return print(f"Installed {RULE_PATH}. If access is still denied, unplug and replug the keyboard.")
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
    elif a.cmd == "music":
        try:
            music(kb, lambda: dict(style=a.style, gain=a.gain, colors=a.colors))
        except KeyboardInterrupt:
            pass  # the keyboard goes back to its saved effect by itself


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
    rules = os.path.join(os.path.dirname(os.path.realpath(__file__)), "70-ak820.rules")
    assert not os.path.exists(rules) or open(rules).read() == UDEV_RULE
    lp = live_packet({2: (4, 5, 6), 1: (1, 2, 3)})
    assert len(lp) == 512 and lp[:8] == b"\x01\x01\x02\x03\x02\x04\x05\x06" and lp[8:] == bytes(504)
    grid = key_grid()
    assert len(grid) == len(KEYS) and grid[KEYS["esc"]] == (0, 0) and grid[KEYS["right"]] == (1, 1)
    assert grad(0) == (0, 255, 0) and grad(1) == (255, 0, 0) and grad(0.5, ((0, 0, 0), (200, 100, 50))) == (100, 50, 25)
    assert grad(0, "rainbow") == (255, 0, 0)
    assert palette("classic") is None and palette("rainbow") == "rainbow"
    assert palette("ff0080-00ffff") == ((255, 0, 128), (0, 255, 255))
    for bad in ("red", "ff0000", "ff0000-00ff", "zzzzzz-000000"):
        try:
            palette(bad)
            raise AssertionError(bad)
        except argparse.ArgumentTypeError:
            pass
    off = (0, 0, 0)
    assert all(c == off for st in ("meter", "center") for c in render(st, grid, None, 0).values())
    m = render("meter", grid, None, 1.01)
    assert m[KEYS["esc"]] == (0, 255, 0) and m[KEYS["delete"]] == (255, 0, 0)
    c = render("center", grid, None, 0.3)
    assert c[KEYS["esc"]] == off and c[KEYS["delete"]] == off and c[KEYS["t"]] != off
    sp = render("spectrum", grid, None, bands=[1.0] + [0.0] * (BANDS - 1))
    assert sp[KEYS["lctrl"]] != off and sp[KEYS["esc"]] != off and sp[KEYS["right"]] == off
    assert all(v == (0, 127, 0) for v in render("pulse", grid, None, pulse=(0.5, 0)).values())
    import math
    try:
        import numpy  # optional dependency, only the spectrum style uses it
    except ImportError:
        numpy = None
    if numpy:
        tone = array.array("h", (int(20000 * math.sin(2 * math.pi * 1000 * n / 44100)) for n in range(4096))).tobytes()
        b = spectrum(tone)
        assert len(b) == BANDS and b.index(max(b)) == next(i for i in range(BANDS) if 40 * 400 ** ((i + 1) / BANDS) > 1000)
    assert rms(b"") == 0 and abs(rms(array.array("h", [32767, -32767]).tobytes()) - 1) < 0.001
    print("selftest ok")


if __name__ == "__main__":
    main()
