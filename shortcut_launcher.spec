# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the Windows standalone distribution.

The internal executable name deliberately stays ASCII.  The application itself
can be placed in folders with Korean names; data uses the configured writable folder.
"""

from pathlib import Path
import os
import sys

import PyQt6


PROJECT_ROOT = Path(SPECPATH).resolve()
ICON_FILE = PROJECT_ROOT / "토마2_icon.ico"
QT_BIN_DIR = Path(PyQt6.__file__).resolve().parent / "Qt6" / "bin"
# Resolve binary dependencies using this build's runtimes, never unrelated
# development tools on the inherited PATH (which may ship incompatible ICU/CRT).
os.environ["PATH"] = os.pathsep.join([
    str(QT_BIN_DIR), str(Path(sys.executable).parent), sys.base_prefix,
    str(Path(sys.base_prefix) / "DLLs"),
    str(Path(os.environ["SystemRoot"]) / "System32"), os.environ["SystemRoot"],
])
QT_RUNTIME_DLLS = [
    "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "concrt140.dll", "d3dcompiler_47.dll",
    "opengl32sw.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "vcruntime140.dll", "vcruntime140_1.dll",
]

# The icon is embedded in the EXE and also available at runtime for the window
# and taskbar icon. Mutable user data is never bundled.
datas = [(str(ICON_FILE), ".")] if ICON_FILE.is_file() else []
# 사용 설명서는 실제 화면 캡처를 그대로 보여 준다.  함께 묶지 않으면 배포본에서
# 그림 자리가 비어 버린다.
MANUAL_DIR = PROJECT_ROOT / "assets" / "manual"
datas += [
    (str(path), "assets/manual")
    for path in sorted(MANUAL_DIR.glob("*.png"))
]
# Both files are required by TomaSpriteAtlas, including its metadata validator.
PET_DIR = PROJECT_ROOT / "alert_notes" / "toma_pet_assets"
for filename in ("pet.json", "spritesheet.webp"):
    path = PET_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Required TomaPet asset is missing: {path}")
    datas.append((str(path), "alert_notes/toma_pet_assets"))
hiddenimports = ["pythoncom", "pywintypes", "win32com.client"]
hiddenimports += [
    "winrt.runtime", "winrt.windows.foundation", "winrt.windows.foundation.collections",
    "winrt.windows.globalization", "winrt.windows.graphics.imaging", "winrt.windows.media.ocr",
    "winrt.windows.storage.streams",
]

a = Analysis(
    [str(PROJECT_ROOT / "A_shortcut_launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[
        (str(QT_BIN_DIR / name), "PyQt6/Qt6/bin")
        for name in QT_RUNTIME_DLLS
        if (QT_BIN_DIR / name).is_file()
    ],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(PROJECT_ROOT / "pyqt6_runtime_hook.py")],
    excludes=["pytest"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="toma_shortcut_program",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(ICON_FILE)] if ICON_FILE.is_file() else None,
)


