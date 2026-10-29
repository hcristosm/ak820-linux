#!/bin/sh
# Build ak820-<version>-x86_64.AppImage with Python, PySide6, Pillow and numpy inside (PyInstaller + appimagetool).
# Needs python3 with pip and internet. The AppImage runs on distros whose glibc is at least the build machine's,
# so release builds run on an old Ubuntu (see .github/workflows/appimage.yml).
set -e
SRC=$(cd "$(dirname "$0")/.." && pwd)
B="$SRC/build"
VER=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/ak820.py")
OUT="$B/ak820-$VER-x86_64.AppImage"
rm -rf "$B" && mkdir -p "$B"

# a venv without pip works even where python3-venv isn't installed; the host's pip installs into it
python3 -m venv --without-pip "$B/venv"
python3 -m pip --python "$B/venv/bin/python" install -q \
    pyinstaller==6.22.3 PySide6_Essentials==6.12.0 pillow numpy
"$B/venv/bin/pyinstaller" --noconfirm --log-level WARN --name ak820 \
    --distpath "$B/dist" --workpath "$B/work" --specpath "$B" \
    --paths "$SRC" --add-data "$SRC/ak820.png:." "$SRC/appimage/entry.py"
# shortcut: libstdc++, X11 and xcb still come from the build machine; if the AppImage breaks on some distro,
# add the offending library to prune.py's HOST list
python3 "$SRC/appimage/prune.py" "$B/dist/ak820/_internal"

A="$B/AppDir"
mkdir -p "$A/usr/lib"
mv "$B/dist/ak820" "$A/usr/lib/ak820"
ln -s usr/lib/ak820/ak820 "$A/AppRun"
cp "$SRC/ak820.png" "$A/"
sed -e 's|^Exec=.*|Exec=ak820|' -e 's|^Icon=.*|Icon=ak820|' "$SRC/ak820.desktop" > "$A/ak820.desktop"

curl -sSLo "$B/appimagetool" \
    https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage
chmod +x "$B/appimagetool"
# extract-and-run: works without FUSE (containers, CI)
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$B/appimagetool" -n "$A" "$OUT"

APPIMAGE_EXTRACT_AND_RUN=1 "$OUT" selftest
APPIMAGE_EXTRACT_AND_RUN=1 "$OUT" gui selftest
echo "Built $OUT"
