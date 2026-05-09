# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Game Arabic Translator v1.0
Build:  pyinstaller GameArabicTranslator.spec
"""

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ── Data files to bundle ──────────────────────────────────────────────────────

added_datas = [
    # App config
    ('config.json',              '.'),
    # Game configs
    ('games/configs',            'games/configs'),
    # Pre-packaged Grounded2 mod data (enus JSON + .orig files only)
    ('mods',                     'mods'),
    # IoStore tools — retoc, UAssetGUI
    ('tools/retoc',              'tools/retoc'),
    ('tools/UAssetGUI.exe',      'tools'),
    ('tools/oo2core_9_win64.dll','tools'),
]

# PySide6 data files
added_datas += collect_data_files('PySide6')

# ── Hidden imports ────────────────────────────────────────────────────────────

hidden_imports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtNetwork',
    'engine.translator',
    'engine.cache',
    'engine.models.api_translator',
    'engine.models.base',
    'games.game_manager',
    'games.translation_package',
    'games.iostore.translator',
    'games.steam_detector',
    'gui.qt.app',
    'gui.qt.theme',
    'gui.qt.pages.home',
    'gui.qt.pages.translate',
    'gui.qt.pages.cache',
    'gui.qt.pages.games',
    'gui.qt.pages.models',
    'gui.qt.pages.settings',
    'gui.qt.widgets.sidebar',
    'gui.qt.widgets.page_header',
    'gui.qt.dialogs.add_game',
    'requests',
    'arabic_reshaper',
    'bidi.algorithm',
    'sqlite3',
    'winreg',
]

# ── Analysis ──────────────────────────────────────────────────────────────────

a = Analysis(
    ['main_qt.py'],
    pathex=['.'],
    binaries=[],
    datas=added_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 'transformers', 'tensorflow',
        'matplotlib', 'numpy', 'scipy',
        'tkinter', 'frida', 'UnityPy',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GameArabicTranslator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                  # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='GameArabicTranslator',
)
