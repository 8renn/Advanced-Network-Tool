# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for macOS (.app bundle). Build on a Mac runner.
#
# Example:
#   pyinstaller ANT-mac.spec
#
# Notes:
# - Does not bundle Windows-only binaries (e.g. assets/speedtest.exe).
# - Icon: set _MAC_ICONS below if you add assets/App.icns (or similar).

from pathlib import Path

block_cipher = None

APP_NAME = "AdvancedNetworkTool"
BUNDLE_ID = "com.advancednetworktool.app"

# Project root = directory containing this spec (repository root when run from CI)
project_dir = Path(SPECPATH).resolve().parent

# Prefer a single .icns under assets/; otherwise BUNDLE gets no custom icon.
_MAC_ICONS = sorted((project_dir / "assets").glob("*.icns")) if (project_dir / "assets").is_dir() else []
icon_path = str(_MAC_ICONS[0]) if _MAC_ICONS else None

datas = []

vendors = project_dir / "mac_vendors.json"
if vendors.is_file():
    datas.append((str(vendors), "."))

assets_dir = project_dir / "assets"
if assets_dir.is_dir():
    for child in sorted(assets_dir.iterdir()):
        if not child.is_file():
            continue
        if child.suffix.lower() == ".exe":
            continue
        datas.append((str(child), f"assets/{child.name}"))

db_dir = project_dir / "db"
if db_dir.is_dir():
    datas.append((str(db_dir), "db"))

a = Analysis(
    ["main.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtNetwork",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "pydoc",
        "doctest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=icon_path,
    bundle_identifier=BUNDLE_ID,
    info_plist={
        "CFBundleDisplayName": "Advanced Network Tool",
        "CFBundleName": APP_NAME,
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
    },
)
