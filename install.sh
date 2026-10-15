#!/bin/sh
# Install ak820 for the current user (the udev rule needs sudo once).  ./install.sh --uninstall removes it.
set -e
SRC=$(cd "$(dirname "$0")" && pwd)
DEST="$HOME/.local/share/ak820"
APPS="$HOME/.local/share/applications"
RULE=/etc/udev/rules.d/70-ak820.rules

if [ "$1" = "--uninstall" ]; then
    rm -rf "$DEST" "$HOME/.local/bin/ak820" "$HOME/.local/bin/ak820-gui" "$APPS/ak820.desktop"
    if [ -e "$RULE" ]; then sudo rm "$RULE" && sudo udevadm control --reload; fi
    echo "Removed."
    exit 0
fi

python3 -c "import PIL, tkinter" 2>/dev/null || {
    echo "Missing dependencies. Fedora: sudo dnf install python3-tkinter python3-pillow"
    echo "                      Debian/Ubuntu: sudo apt install python3-tk python3-pil python3-pil.imagetk"
    exit 1
}
mkdir -p "$DEST" "$HOME/.local/bin" "$APPS"
cp "$SRC/ak820.py" "$SRC/ak820_gui.py" "$SRC/ak820.png" "$DEST/"
ln -sf "$DEST/ak820.py" "$HOME/.local/bin/ak820"
ln -sf "$DEST/ak820_gui.py" "$HOME/.local/bin/ak820-gui"
sed "s|@DEST@|$DEST|g" "$SRC/ak820.desktop" > "$APPS/ak820.desktop"

if ! cmp -s "$SRC/70-ak820.rules" "$RULE"; then
    sudo install -m 644 "$SRC/70-ak820.rules" "$RULE"
    sudo udevadm control --reload
    sudo udevadm trigger --subsystem-match=hidraw
    echo "udev rule installed. If access is still denied, unplug and replug the keyboard."
fi
echo "Done. Open 'AJAZZ AK820 Pro' from the app menu, or run: ak820-gui / ak820 --help"
