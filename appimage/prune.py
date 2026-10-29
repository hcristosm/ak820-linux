"""Trim the PyInstaller bundle (the _internal folder given as argv[1]) after collection.

Qt's GTK theme and GLib network plugins pull in the build machine's GTK, GLib and GIO; an old bundled GIO then
loads the host's newer GIO modules (gvfs) and fails. Without those plugins Qt draws its own dialogs or uses the
desktop portal, and GLib comes from the host, which every desktop has. Libraries nothing needs any more go too.
"""
import os
import re
import subprocess
import sys

root = sys.argv[1]
for p in ("platformthemes/libqgtk3.so", "networkinformation/libqglib.so"):
    os.remove(os.path.join(root, "PySide6/Qt/plugins", p))

HOST = re.compile(r"lib(glib|gobject|gio|gmodule|gthread)-2\.0\.so")
libs = {f for f in os.listdir(root) if ".so" in f and os.path.isfile(os.path.join(root, f))}


def needed(path):
    out = subprocess.run(["readelf", "-d", path], capture_output=True, text=True).stdout
    return re.findall(r"\(NEEDED\).*\[(.+)\]", out)


def is_elf(path):
    with open(path, "rb") as f:
        return f.read(4) == b"\x7fELF"


# start from every ELF that isn't a top-level system library copy, plus the launcher next to _internal
todo = [os.path.join(root, "..", "ak820")]
for d, _, files in os.walk(root):
    todo += [os.path.join(d, f) for f in files if not (d == root and f in libs) and is_elf(os.path.join(d, f))]
keep = {f for f in libs if f.startswith("libpython")}  # the bootloader dlopens it, nothing lists it as NEEDED
while todo:
    for name in needed(todo.pop()):
        if name in libs and name not in keep and not HOST.match(name):
            keep.add(name)
            todo.append(os.path.join(root, name))
gone = sorted(libs - keep)
for f in gone:
    os.remove(os.path.join(root, f))
print(f"prune: removed {len(gone)} of {len(libs)} bundled system libraries:", " ".join(gone))
