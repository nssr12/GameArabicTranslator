"""
gui/qt/dialogs/add_game.py  —  حوار إضافة/تعديل لعبة
"""

from __future__ import annotations
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame,
    QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox,
    QTextEdit, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui  import QCursor

from gui.qt.theme import theme


LANG_OPTIONS = [
    ("en", "English"),
    ("ar", "Arabic — العربية"),
    ("fr", "French"),
    ("de", "German"),
    ("es", "Spanish"),
    ("ja", "Japanese"),
    ("zh", "Chinese"),
    ("ko", "Korean"),
    ("ru", "Russian"),
    ("tr", "Turkish"),
]

ENGINE_OPTIONS = [
    ("auto",   "تلقائي (كشف)"),
    ("unity",  "Unity"),
    ("unreal", "Unreal Engine"),
    ("ue4",    "Unreal Engine 4"),
    ("ue5",    "Unreal Engine 5"),
    ("other",  "أخرى"),
]

HOOK_OPTIONS = [
    ("frida",  "Frida (اعتراض ديناميكي)"),
    ("file",   "ملف (ترجمة ملفات)"),
    ("memory", "ذاكرة (memory scan)"),
]


def _sep() -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background: {theme.c['border']}; border: none;")
    return f


class AddGameDialog(QDialog):
    """حوار إضافة أو تعديل لعبة."""

    saved = Signal(str, dict)

    def __init__(self, game_manager, game_id: str = None,
                 game_cfg: dict = None, parent=None):
        super().__init__(parent)
        self._gm      = game_manager
        self._edit_id = game_id
        self._cfg     = dict(game_cfg) if game_cfg else {}
        self._is_edit = game_id is not None

        self.setWindowTitle("تعديل اللعبة" if self._is_edit else "إضافة لعبة جديدة")
        self.setMinimumWidth(560)
        self.setModal(True)
        self._build()
        if self._cfg:
            self._populate()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        c = theme.c
        self.setStyleSheet(f"""
            QDialog {{ background: {c['bg']}; }}
            QLabel  {{ color: {c['primary']}; background: transparent; border: none; }}
            QLineEdit, QComboBox, QTextEdit {{
                background: {c['surface']}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 6px; padding: 5px 10px;
                selection-background-color: {c['accent']};
            }}
            QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{ border-color: {c['accent']}; }}
            QCheckBox {{ color: {c['primary']}; background: transparent; }}
            QCheckBox::indicator {{
                width: 16px; height: 16px;
                border: 1px solid {c['border']}; border-radius: 3px;
                background: {c['surface']};
            }}
            QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox QAbstractItemView {{
                background: {c['surface']}; color: {c['primary']};
                selection-background-color: {c['accent']};
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        title_lbl = QLabel("تعديل اللعبة" if self._is_edit else "➕  إضافة لعبة جديدة")
        title_lbl.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {c['accent']};"
            " background: transparent; border: none;"
        )
        root.addWidget(title_lbl)
        root.addWidget(_sep())

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        def _lbl(txt):
            l = QLabel(txt)
            l.setStyleSheet(
                f"color: {c['muted']}; font-size: 12px;"
                " background: transparent; border: none;"
            )
            return l

        def _browse_style():
            return (
                f"QPushButton {{ background: {c['surface']}; border: 1px solid {c['border']};"
                f" border-radius: 6px; font-size: 14px; }}"
                f"QPushButton:hover {{ background: {c['hover']}; border-color: {c['accent']}; }}"
            )

        # Game name
        self._name = QLineEdit()
        self._name.setPlaceholderText("اسم اللعبة (مطلوب)")
        form.addRow(_lbl("اسم اللعبة:"), self._name)

        # Process name
        self._proc = QLineEdit()
        self._proc.setPlaceholderText("مثال: Game.exe")
        form.addRow(_lbl("اسم العملية:"), self._proc)

        # Game path + browse + Steam auto-detect
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self._path = QLineEdit()
        self._path.setPlaceholderText("مسار مجلد اللعبة")
        browse_btn = QPushButton("📂")
        browse_btn.setFixedSize(34, 34)
        browse_btn.setCursor(QCursor(Qt.PointingHandCursor))
        browse_btn.setStyleSheet(_browse_style())
        browse_btn.clicked.connect(self._browse_path)
        steam_btn = QPushButton("🎮 Steam")
        steam_btn.setFixedHeight(34)
        steam_btn.setCursor(QCursor(Qt.PointingHandCursor))
        steam_btn.setToolTip("كشف مسار اللعبة تلقائياً من Steam")
        steam_btn.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; border: 1px solid {c['border']};"
            f" border-radius: 6px; color: {c['blue']}; padding: 0 10px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {c['hover']}; border-color: {c['blue']}; }}"
        )
        steam_btn.clicked.connect(self._detect_steam_path)
        path_row.addWidget(self._path, 1)
        path_row.addWidget(browse_btn)
        path_row.addWidget(steam_btn)
        form.addRow(_lbl("مسار اللعبة:"), path_row)

        # Engine
        self._engine = QComboBox()
        for val, label in ENGINE_OPTIONS:
            self._engine.addItem(label, val)
        form.addRow(_lbl("المحرك:"), self._engine)

        # Hook mode
        self._hook = QComboBox()
        for val, label in HOOK_OPTIONS:
            self._hook.addItem(label, val)
        form.addRow(_lbl("وضع الاعتراض:"), self._hook)

        # Source / Target language
        lang_row = QHBoxLayout()
        lang_row.setSpacing(10)
        self._src_lang = QComboBox()
        self._tgt_lang = QComboBox()
        for val, label in LANG_OPTIONS:
            self._src_lang.addItem(label, val)
            self._tgt_lang.addItem(label, val)
        self._src_lang.setCurrentIndex(0)
        self._tgt_lang.setCurrentIndex(1)

        def _mini_lbl(t):
            ll = QLabel(t)
            ll.setStyleSheet(f"color: {c['muted']}; background: transparent; border: none;")
            return ll

        lang_row.addWidget(_mini_lbl("من:"))
        lang_row.addWidget(self._src_lang, 1)
        lang_row.addSpacing(10)
        lang_row.addWidget(_mini_lbl("إلى:"))
        lang_row.addWidget(self._tgt_lang, 1)
        form.addRow(_lbl("اللغة:"), lang_row)

        # Font replacement
        font_row = QHBoxLayout()
        font_row.setSpacing(8)
        self._replace_font = QCheckBox("استبدال الخط")
        self._font_path    = QLineEdit()
        self._font_path.setPlaceholderText("مسار ملف الخط العربي (.ttf)")
        font_browse = QPushButton("📂")
        font_browse.setFixedSize(34, 34)
        font_browse.setCursor(QCursor(Qt.PointingHandCursor))
        font_browse.setStyleSheet(_browse_style())
        font_browse.clicked.connect(self._browse_font)
        font_row.addWidget(self._replace_font)
        font_row.addWidget(self._font_path, 1)
        font_row.addWidget(font_browse)
        form.addRow(_lbl("الخط:"), font_row)

        # Enabled
        self._enabled = QCheckBox("اللعبة مفعّلة")
        self._enabled.setChecked(True)
        form.addRow(_lbl("الحالة:"), self._enabled)

        # Notes
        self._notes = QTextEdit()
        self._notes.setPlaceholderText("ملاحظات اختيارية...")
        self._notes.setFixedHeight(70)
        form.addRow(_lbl("ملاحظات:"), self._notes)

        root.addLayout(form)
        root.addWidget(_sep())

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("إلغاء")
        cancel_btn.setFixedHeight(36)
        cancel_btn.setMinimumWidth(90)
        cancel_btn.setCursor(QCursor(Qt.PointingHandCursor))
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; color: {c['muted']};"
            f" border: 1px solid {c['border']}; border-radius: 8px; padding: 0 18px; }}"
            f"QPushButton:hover {{ background: {c['hover']}; color: {c['primary']}; }}"
        )
        cancel_btn.clicked.connect(self.reject)

        save_lbl = "💾  حفظ" if self._is_edit else "➕  إضافة"
        save_btn = QPushButton(save_lbl)
        save_btn.setFixedHeight(36)
        save_btn.setMinimumWidth(110)
        save_btn.setCursor(QCursor(Qt.PointingHandCursor))
        save_btn.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: #fff;"
            " border: none; border-radius: 8px; font-weight: bold; padding: 0 18px; }"
        )
        save_btn.clicked.connect(self._save)

        btn_row.addWidget(cancel_btn)
        btn_row.addSpacing(10)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

    # ── Populate (edit mode) ──────────────────────────────────────────────────

    def _populate(self):
        cfg = self._cfg
        self._name.setText(cfg.get("name", self._edit_id or ""))
        self._proc.setText(cfg.get("process_name", ""))
        self._path.setText(cfg.get("game_path", ""))
        self._notes.setPlainText(cfg.get("notes", ""))
        self._enabled.setChecked(cfg.get("enabled", True))
        self._replace_font.setChecked(cfg.get("replace_font", False))
        self._font_path.setText(cfg.get("font_path", ""))

        engine_val = cfg.get("engine", "auto")
        for i, (val, _) in enumerate(ENGINE_OPTIONS):
            if val == engine_val:
                self._engine.setCurrentIndex(i)
                break

        hook_val = cfg.get("hook_mode", "frida")
        for i, (val, _) in enumerate(HOOK_OPTIONS):
            if val == hook_val:
                self._hook.setCurrentIndex(i)
                break

        src = cfg.get("source_lang", "en")
        tgt = cfg.get("target_lang", "ar")
        for i, (val, _) in enumerate(LANG_OPTIONS):
            if val == src:
                self._src_lang.setCurrentIndex(i)
            if val == tgt:
                self._tgt_lang.setCurrentIndex(i)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _browse_path(self):
        d = QFileDialog.getExistingDirectory(self, "اختر مجلد اللعبة", "")
        if d:
            self._path.setText(d)

    def _browse_font(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "اختر ملف الخط", "", "Font Files (*.ttf *.otf)"
        )
        if path:
            self._font_path.setText(path)

    def _detect_steam_path(self):
        from games.steam_detector import find_game_path, is_known
        name   = self._name.text().strip()
        gid    = self._edit_id or name
        result = find_game_path(gid)

        if result:
            self._path.setText(result)
            # Also auto-detect engine from the found path
            self._detect_engine()
            self.statusBar().showMessage("✓  تم اكتشاف مسار Steam") if hasattr(self, "statusBar") else None
        else:
            # Try common default paths
            defaults = [
                f"C:/Program Files (x86)/Steam/steamapps/common/{gid}",
                f"C:/Program Files/Steam/steamapps/common/{gid}",
            ]
            found = next((p for p in defaults if os.path.isdir(p)), None)
            if found:
                self._path.setText(found)
                self._detect_engine()
            else:
                QMessageBox.information(
                    self, "اكتشاف Steam",
                    f"لم يتم العثور على «{name}» في مكتبات Steam.\n"
                    "تأكد من تثبيت اللعبة أو اختر المسار يدوياً."
                )

    def _detect_engine(self):
        p = self._path.text().strip()
        if not p or not os.path.isdir(p):
            return
        eng = self._gm.detect_game_engine(p) if self._gm else "unknown"
        val = {"unity": "unity", "unreal": "unreal"}.get(eng, "auto")
        for i, (v, _) in enumerate(ENGINE_OPTIONS):
            if v == val:
                self._engine.setCurrentIndex(i)
                break

    def _save(self):
        name = self._name.text().strip()
        if not name:
            QMessageBox.warning(self, "تنبيه", "اسم اللعبة مطلوب")
            return

        cfg = {
            "name":         name,
            "process_name": self._proc.text().strip(),
            "game_path":    self._path.text().strip(),
            "engine":       self._engine.currentData(),
            "hook_mode":    self._hook.currentData(),
            "source_lang":  self._src_lang.currentData(),
            "target_lang":  self._tgt_lang.currentData(),
            "replace_font": self._replace_font.isChecked(),
            "font_path":    self._font_path.text().strip(),
            "notes":        self._notes.toPlainText().strip(),
            "enabled":      self._enabled.isChecked(),
            "hooks":        self._cfg.get("hooks", []),
        }

        game_id = self._edit_id if self._is_edit else name
        if self._gm:
            if self._is_edit:
                ok = self._gm.update_game(game_id, cfg)
            else:
                ok = self._gm.add_game(game_id, cfg)
            if not ok:
                QMessageBox.critical(self, "خطأ", "فشل حفظ اللعبة")
                return

        self.saved.emit(game_id, cfg)
        self.accept()
