import ctypes
import os
import sys

# Qt's automatic HighDPI scaling makes mapToGlobal()/widget geometry return
# logical (scaled) pixel coordinates, while mss/screen capture always works in
# raw physical pixels. Screen-region calibration depends on both agreeing on
# the same coordinate space, so disable Qt's own scaling layer process-wide.
# Must run before QApplication is constructed, hence living at package import time.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

if sys.platform == "win32":
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE: tells Windows not to virtualize/stretch
        # this process's windows, so GetWindowRect/mouse coords/mss all agree on
        # true physical pixels regardless of the display's scaling percentage.
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()
