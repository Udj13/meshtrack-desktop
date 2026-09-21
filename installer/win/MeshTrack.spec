# -*- mode: python ; coding: utf-8 -*-
"""MeshTrack PyInstaller spec (onedir, Windows). Запуск:
..\\..\\.venv\\Scripts\\pyinstaller --noconfirm installer\\win\\MeshTrack.spec
"""
import os

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
ROOT = os.path.abspath(os.path.join(SPEC_DIR, "..", ".."))

datas = [
    (os.path.join(ROOT, "assets", "web"), "assets/web"),
    (os.path.join(ROOT, "assets", "licenses"), "assets/licenses"),
    (os.path.join(ROOT, "assets", "wizard_watermark.png"), "assets"),
    (os.path.join(ROOT, "assets", "app-icon.png"), "assets"),
    (os.path.join(ROOT, "meshtrack", "i18n_data"), "meshtrack/i18n_data"),
]

hiddenimports = []

a = Analysis(
    [os.path.join(ROOT, "run_meshtrack.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MeshTrack",
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
    icon=[os.path.join(ROOT, "assets", "app.ico")],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MeshTrack",
)