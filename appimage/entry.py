"""AppImage entry point: no arguments (or "gui ...") opens the GUI, anything else is the ak820 command line."""
import sys

import ak820
import ak820_gui

if len(sys.argv) == 1 or sys.argv[1] == "gui":
    del sys.argv[1:2]  # "gui selftest" -> the GUI sees ["selftest"]
    ak820_gui.main()
else:
    ak820.main()
