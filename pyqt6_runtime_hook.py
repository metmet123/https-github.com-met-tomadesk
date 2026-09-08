"""Load bundled Qt runtimes before PyQt6 extension modules are imported."""

import builtins
import ctypes
import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    meipass = Path(sys._MEIPASS)
    qt_bin = meipass / "PyQt6" / "Qt6" / "bin"
    builtins._tomadesk_qt_dll_directories = [
        os.add_dll_directory(str(meipass)),
        os.add_dll_directory(str(qt_bin)),
    ]
    builtins._tomadesk_qt_dll_handles = [
        ctypes.WinDLL(str(qt_bin / dll_name))
        for dll_name in (
            "concrt140.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
            "vcruntime140.dll", "vcruntime140_1.dll", "d3dcompiler_47.dll",
            "opengl32sw.dll", "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll",
        )
    ]
