#!/bin/sh
# Install ak820 for the current user (the udev rule asks for your password once).  ./install.sh --uninstall removes it.
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

python3 -c "import PIL, PySide6.QtWidgets" 2>/dev/null || {
    echo "Missing dependencies. Fedora: sudo dnf install python3-pyside6 python3-pillow"
    echo "                      Debian/Ubuntu: sudo apt install python3-pyside6.qtwidgets python3-pil"
    echo "                      Ubuntu 24.04 / Mint 22: sudo apt install python3-pip python3-pil libxcb-cursor0"
    echo "                                              pip install --user --break-system-packages PySide6"
    echo "                      elsewhere: pip install --user PySide6 pillow"
    exit 1
}
# pip's PySide6 (Qt >= 6.5) can't open an X11 window without libxcb-cursor; distro PySide6 packages pull it in
if command -v ldconfig >/dev/null && ! ldconfig -p | grep -q 'libxcb-cursor\.so\.0'; then
    echo "Warning: libxcb-cursor not found, the GUI may not start on X11."
    echo "         Debian/Ubuntu: sudo apt install libxcb-cursor0   Fedora/Arch: install xcb-util-cursor"
fi
mkdir -p "$DEST" "$HOME/.local/bin" "$APPS"
cp "$SRC/ak820.py" "$SRC/ak820_gui.py" "$SRC/ak820.png" "$DEST/"
ln -sf "$DEST/ak820.py" "$HOME/.local/bin/ak820"
ln -sf "$DEST/ak820_gui.py" "$HOME/.local/bin/ak820-gui"
sed "s|@DEST@|$DEST|g" "$SRC/ak820.desktop" > "$APPS/ak820.desktop"
# KDE caches menu entries and may keep launching an old Exec path until the cache is rebuilt
for c in kbuildsycoca6 kbuildsycoca5; do command -v $c >/dev/null && $c >/dev/null 2>&1 && break; done || true

cmp -s "$SRC/70-ak820.rules" "$RULE" || python3 "$SRC/ak820.py" setup
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) echo "~/.local/bin is not on your PATH yet; log out and back in to use the ak820 commands." ;;
esac
echo "Done. Open 'AJAZZ AK820 Pro' from the app menu, or run: ak820-gui / ak820 --help"
