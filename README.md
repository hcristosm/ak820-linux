# ak820-linux

Control the RGB lighting and the 0.85" 128×128 screen of the **AJAZZ AK820 Pro** keyboard on Linux,
without the vendor's Windows-only software.

- 20 built-in lighting effects with color, rainbow, brightness, speed and direction
- per-key static colors
- upload an image or animated GIF (up to 140 frames) to the screen
- sync the screen clock to your PC
- music mode: the keys react to whatever your PC is playing (level meter, center, spectrum or beat pulse)
- command line tool and a small GUI with saved profiles

Unofficial project. Not affiliated with or endorsed by AJAZZ.

## Tested hardware

| Device | USB ID | Status |
|---|---|---|
| AJAZZ AK820 Pro, wired USB | `0c45:8009` | effects, per-key colors, screen GIF and clock verified on the keyboard |
| AK820 variant | `0c45:800a` | listed by the vendor software, untested |

The 2.4 GHz dongle (`0c45:fdfd`) and Bluetooth are not supported. Connect the keyboard with the USB cable.

## Install

Needs Python 3 with PySide6 (Qt 6) and Pillow:

```sh
sudo dnf install python3-pyside6 python3-pillow                 # Fedora
sudo apt install python3-pyside6.qtwidgets python3-pil          # Debian 13+ / Ubuntu 24.10+
pip install --user PySide6 pillow                               # anything else
```

Music mode also needs `parec` (package `pulseaudio-utils`; works with PipeWire too), and its spectrum style
needs numpy (`python3-numpy`).

Prefer a lighter GUI without Qt? The Tkinter version lives on the
[`tk-gui`](https://github.com/hcristosm/ak820-linux/tree/tk-gui) branch.

Then download the [latest release](https://github.com/hcristosm/ak820-linux/releases/latest) and run the installer:

```sh
curl -L https://github.com/hcristosm/ak820-linux/archive/refs/tags/v0.2.0.tar.gz | tar xz
cd ak820-linux-0.2.0
./install.sh
```

(or `git clone https://github.com/hcristosm/ak820-linux` for the latest code.)

`install.sh` copies the program to `~/.local/share/ak820`, adds `ak820` and `ak820-gui` to `~/.local/bin`,
creates an "AJAZZ AK820 Pro" entry in the app menu, and installs a udev rule (asks for sudo once) so your
user can open the keyboard's hidraw devices. Unplug and replug the keyboard if you still get a permission
error. `./install.sh --uninstall` removes everything.

You can also run `./ak820.py` or `./ak820_gui.py` straight from the cloned folder once the udev rule
(`70-ak820.rules`) is installed.

## Usage

GUI: open **AJAZZ AK820 Pro** from the app menu, or run `ak820-gui`.

- sidebar with Effects (pick one from the gallery), Per-key colors (click keys to paint them),
  Screen (with preview), Clock and Music (Start/Stop, style, colors, sensitivity; changes apply live)
- settings are remembered between runs, in `~/.config/ak820/config.json`
- **Profile** (bottom of the sidebar): type a name and Save; Load fills in the pages and applies the profile's lighting
  (the screen image is remembered but not re-sent, since uploads take a few seconds); Delete asks first

Command line:

```sh
ak820 mode static -c 00ff88 -b 5              # solid color, brightness 0-5
ak820 mode rolling -s 4 -d 1                  # no -c = rainbow; speed 0-5; direction 0/1
ak820 keys --all 101010 w=ff0000 a=ff0000 s=ff0000 d=ff0000
ak820 keys --list                             # key names
ak820 screen picture.gif                      # also png/jpg; --fit pad keeps the whole image
ak820 time                                    # sync the clock
ak820 music -g 1.5                            # react to the system audio until Ctrl-C; -g = sensitivity
ak820 music --style spectrum --colors rainbow # styles: meter center spectrum pulse
ak820 music --style pulse --colors ff0080-00ffff   # colors: classic, rainbow, or two colors
ak820 --version
```

Self-checks that need no keyboard: `ak820 selftest` (packet builders) and `ak820-gui selftest`
(settings and profiles survive a restart).

Effects: `off static singleon singleoff glittering falling colourful breath spectrum outward scrolling
rolling rotating explode launch ripples flowing pulsating tilt shuttle` (or their numbers 0-19).
Direction `0` = left→right / down, `1` = right→left / up. Rolling moves horizontally and scrolling vertically.

## Protocol

Recovered by reverse engineering the vendor's Windows configurator (`DeviceDriver.exe` v1.0.0.5).
The keyboard exposes four HID interfaces. Two of them are used here:

- **interface 3**, usage page `0xff13`: 64-byte feature reports (no report ID) carry commands
- **interface 2**, usage page `0xff68`: 4096-byte output reports carry screen data

Every command is a session: `04 18` (begin) … `04 02` (end), and lighting commands also send `04 F0`.
A header packet `04 <op>` holds the number of data packets that follow in byte 8 (bytes 8–9 for the screen).
Data blocks end with `AA 55`. The vendor app waits 35 ms between packets and reads a feature report back
after each header (`04 18` answers `04 18 00 01`).

| Op | Function | Data |
|---|---|---|
| `13` | lighting effect | 1 packet: `[0]` mode, `[1..3]` R G B, `[8]` rainbow, `[9]` brightness 0-5, `[10]` speed 0-5, `[11]` direction, `[14..15]` `AA 55` |
| `13` + `23` | per-key colors | mode `0x80` with `[9]` brightness, then 9 packets: 144 × (index, R, G, B), last two bytes `AA 55` |
| `72` | screen | `[2]` slot (1), `[8..9]` number of 4 KiB chunks; payload = 256-byte header (frame count, then one delay per frame in 2 ms units, padded with `FF`) + frames as 128×128 little-endian RGB565, padded with `FF` to 4 KiB |
| `20` | live per-key colors (music mode) | no `04 18`/`04 F0`, not saved: header byte 8 = 8, then 512 bytes of consecutive (index, R, G, B) entries, then `04 02`. Vendor waits 5 ms around headers and 2 ms between data packets. When frames stop, the keyboard returns to its saved effect by itself |
| `28` | clock | `[1]` 1, `[2]` `5A`, `[3..8]` year−2000, month, day, hour, minute, second, `[10]` weekday (Sunday = 0), `[62..63]` `AA 55` |

Mode numbers and per-key indices come from the vendor's default effect table and `rgb-keyboard.xml`;
both are in `ak820.py`.

## Not implemented

Key remapping, macros, and wireless (2.4 GHz) mode. Music styles are this project's own, not the vendor's.

## License

MIT
