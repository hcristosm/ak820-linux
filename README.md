# ak820-linux

Control the RGB lighting and the 0.85" 128×128 screen of the **AJAZZ AK820 Pro** keyboard on Linux,
without the vendor's Windows-only software.

- 20 built-in lighting effects with color, rainbow, brightness, speed and direction
- per-key static colors
- upload an image or animated GIF (up to 140 frames) to the screen
- sync the screen clock to your PC
- command line tool and a small GUI

Unofficial project. Not affiliated with or endorsed by AJAZZ.

## Tested hardware

| Device | USB ID | Status |
|---|---|---|
| AJAZZ AK820 Pro, wired USB | `0c45:8009` | effects, per-key colors, screen GIF and clock verified on the keyboard |
| AK820 variant | `0c45:800a` | listed by the vendor software, untested |

The 2.4 GHz dongle (`0c45:fdfd`) and Bluetooth are not supported. Connect the keyboard with the USB cable.

## Install

Needs Python 3 with Tkinter and Pillow:

```sh
sudo dnf install python3-tkinter python3-pillow                 # Fedora
sudo apt install python3-tk python3-pil python3-pil.imagetk     # Debian / Ubuntu
```

Then:

```sh
git clone https://github.com/hcristosm/ak820-linux
cd ak820-linux
./install.sh
```

`install.sh` copies the program to `~/.local/share/ak820`, adds `ak820` and `ak820-gui` to `~/.local/bin`,
creates an "AJAZZ AK820 Pro" entry in the app menu, and installs a udev rule (asks for sudo once) so your
user can open the keyboard's hidraw devices. Unplug and replug the keyboard if you still get a permission
error. `./install.sh --uninstall` removes everything.

You can also run `./ak820.py` or `./ak820_gui.py` straight from the cloned folder once the udev rule
(`70-ak820.rules`) is installed.

## Usage

GUI: open **AJAZZ AK820 Pro** from the app menu, or run `ak820-gui`.

Command line:

```sh
ak820 mode static -c 00ff88 -b 5              # solid color, brightness 0-5
ak820 mode rolling -s 4 -d 1                  # no -c = rainbow; speed 0-5; direction 0/1
ak820 keys --all 101010 w=ff0000 a=ff0000 s=ff0000 d=ff0000
ak820 keys --list                             # key names
ak820 screen picture.gif                      # also png/jpg; --fit pad keeps the whole image
ak820 time                                    # sync the clock
ak820 selftest                                # checks the packet builders, no keyboard needed
```

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
| `28` | clock | `[1]` 1, `[2]` `5A`, `[3..8]` year−2000, month, day, hour, minute, second, `[10]` weekday (Sunday = 0), `[62..63]` `AA 55` |

Mode numbers and per-key indices come from the vendor's default effect table and `rgb-keyboard.xml`;
both are in `ak820.py`.

## Not implemented

Key remapping, macros, the music-reactive lighting mode, and wireless (2.4 GHz) mode.

## License

MIT
