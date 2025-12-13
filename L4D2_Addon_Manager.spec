# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['l4d2_pyqt_main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('*.png', '.'),
        ('sans.ttf', '.'),
        ('modern_updater.py', '.'),
        ('update_config.py', '.')
    ],
    hiddenimports=['modern_updater', 'update_config'],
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
    a.binaries,
    a.datas,
    [],
    name='L4D2_Addon_Manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='logo.png',
)
