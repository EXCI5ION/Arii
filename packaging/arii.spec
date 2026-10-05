# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.building.datastruct import TOC

project_root = Path(SPECPATH).parent
icon = project_root / "assets" / "icons" / "arii.ico"

a = Analysis(
    [str(project_root / "src" / "arii" / "gui.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[
        (str(project_root / "r"), "r"),
        (str(project_root / "assets" / "icons"), "assets/icons"),
    ],
    hiddenimports=["keyring.backends.Windows", "keyring.backends.fail"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)

# Qt on Windows links against the ICU compatibility DLLs provided by the
# operating system. PyInstaller may accidentally collect an unrelated ICU
# implementation from a tool present in PATH (for example Poppler), which
# makes QtCore fail with ERROR_PROC_NOT_FOUND at startup. Preserve a future
# ICU shipped by PySide6 itself, but reject foreign copies.
def _is_foreign_icu(entry):
    destination, source, _typecode = entry
    name = Path(destination).name.lower()
    is_icu = name == "icuuc.dll" or (name.startswith("icudt") and name.endswith(".dll"))
    source_parts = {part.lower() for part in Path(source).parts}
    return is_icu and "pyside6" not in source_parts


a.binaries = TOC(entry for entry in a.binaries if not _is_foreign_icu(entry))
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Arii",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon),
    version=str(project_root / "packaging" / "windows" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Arii",
)
