# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os

block_cipher = None

APP_NAME = "AdvancedNetworkTool"

project_dir = Path(os.getcwd()).resolve()

# Data files to bundle
datas = []
vendors = project_dir / "mac_vendors.json"
if vendors.exists():
    datas.append((str(vendors), "."))
assets_dir = project_dir / "assets"
if assets_dir.exists():
    datas.append((str(assets_dir), "assets"))

db_dir = project_dir / "db"
if db_dir.exists():
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
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_dir / "assets" / "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)
