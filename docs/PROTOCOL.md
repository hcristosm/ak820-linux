# AJAZZ AK820 Pro USB protocol

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
both are in [`ak820.py`](../ak820.py).
