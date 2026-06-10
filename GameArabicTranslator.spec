# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Game Arabic Translator v1.0
Build:  pyinstaller GameArabicTranslator.spec
"""

import os

block_cipher = None

# ── Data files to bundle ──────────────────────────────────────────────────────

added_datas = [
    # أدوات البناء — تُرفَق داخل _internal كي يتمكّن المستخدم النهائي من البناء/التحديث
    # محلياً (لا يعتمد على pak جاهز فقط). يحلّها games/tools_paths.py وقت التشغيل.
    ('tools/retoc',              'tools/retoc'),
    ('tools/UAssetGUI.exe',      'tools'),
    ('tools/UAssetGUI',          'tools/UAssetGUI'),                   # UAssetGUI.exe + Mappings
    ('tools/repak',              'tools/repak'),                       # حزم pak (V3/V11)
    ('tools/UE4localizationsTool', 'tools/UE4localizationsTool'),      # .locres import/export
    ('data/logo.png',            'data'),                              # شعار الشريط الجانبي
    ('data/icon.ico',            'data'),
    # Note: config.json, games/configs/, mods/ are copied NEXT TO the exe
    # by build_release.bat so users can edit them directly
]

# CA bundle (certifi) — لتحقّق SSL في النسخة المُغلَّفة (تحميل آمن للمنفست والملفات)
try:
    import certifi as _certifi
    added_datas.append((_certifi.where(), 'certifi'))
except Exception:
    pass

# ── Hidden imports ────────────────────────────────────────────────────────────

hidden_imports = [
    'certifi',
    'games.security',
    'games.tools_paths',
    'games.iostore_mod',
    'games.manorlords_mod',
    'games.locres_patcher',
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
    'games.translation_registry',
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
    icon='data/icon.ico',
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
