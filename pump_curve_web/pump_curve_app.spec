# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


PROJECT_ROOT = Path(SPECPATH).resolve().parent
WEB_ROOT = PROJECT_ROOT / "pump_curve_web"

hiddenimports = [
    "pymysql",
    *collect_submodules("pymysql"),
]

a = Analysis(
    [str(WEB_ROOT / "backend" / "exe_entry.py")],
    pathex=[str(WEB_ROOT / "backend"), str(PROJECT_ROOT / "pump_curve_regression")],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / "pump_curve_regression"), "pump_curve_regression"),
        (str(PROJECT_ROOT / "pump_model_config"), "pump_model_config"),
        (str(WEB_ROOT / "frontend" / "dist"), "frontend_dist"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "matplotlib.tests",
        "tkinter",
        "IPython",
        "pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="pump_curve_app",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
