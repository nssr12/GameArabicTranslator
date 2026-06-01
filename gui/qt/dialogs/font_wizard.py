"""
gui/qt/dialogs/font_wizard.py  —  معالج استبدال خطوط الألعاب

يدعم جميع الألعاب (Unity / UE4 / UE5 / أخرى)
  - الخطوات: اختر الخط → اختر المجلد → مسح → استبدال
  - الامتدادات: .ttf  .otf  .ufont  .fnt
  - نسخة احتياطية تلقائية (.bak) قبل كل استبدال
"""
from __future__ import annotations
import os
import shutil

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QLineEdit, QFileDialog, QTextEdit,
    QRadioButton, QButtonGroup, QScrollArea, QProgressBar,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui  import QCursor, QTextCursor

from gui.qt.theme import theme

# ── Constants ─────────────────────────────────────────────────────────────────

_FONTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))),
    "assets", "fonts"
)

_FONT_EXTS = {".ttf", ".otf", ".ufont", ".fnt"}

_BUILTIN_FONTS: dict[str, str] = {
    "الجزيرة":      "Aljazeera.ttf",
    "حياة":          "Hayah.ttf",
    "ذا سان عربي":  "TheSanArabic.ttf",
}


def _builtin_path(filename: str) -> str:
    return os.path.join(_FONTS_DIR, filename)


# ── Worker ────────────────────────────────────────────────────────────────────

class _ReplaceWorker(QThread):
    logged   = Signal(str, str)   # msg, color_key
    progress = Signal(int, int)   # done, total
    finished = Signal(bool, int)  # all_ok, replaced_count

    def __init__(self, font_src: str, targets: list[str]):
        super().__init__()
        self._src     = font_src
        self._targets = targets

    def run(self):
        replaced = 0
        total    = len(self._targets)
        for i, path in enumerate(self._targets):
            fname = os.path.basename(path)
            bak   = path + ".bak"
            try:
                if not os.path.isfile(bak):
                    shutil.copy2(path, bak)
                    self.logged.emit(f"💾  نسخة احتياطية: {fname}.bak", "muted")
                shutil.copy2(self._src, path)
                replaced += 1
                self.logged.emit(f"✅  تم استبدال: {fname}", "green")
            except Exception as exc:
                self.logged.emit(f"❌  خطأ في {fname}: {exc}", "accent")
            self.progress.emit(i + 1, total)
        self.finished.emit(replaced == total, replaced)


# ── UI helpers ────────────────────────────────────────────────────────────────

def _card(c: dict) -> QFrame:
    f = QFrame()
    f.setStyleSheet(f"""
        QFrame {{
            background: {c['card']};
            border: 1px solid {c['border']};
            border-radius: 10px;
        }}
    """)
    return f


def _btn(label: str, color: str, h: int = 34) -> QPushButton:
    b = QPushButton(label)
    b.setFixedHeight(h)
    b.setCursor(QCursor(Qt.PointingHandCursor))
    b.setStyleSheet(f"""
        QPushButton {{
            background: rgba(0,0,0,31); color: {color};
            border: 1px solid {color}; border-radius: 7px;
            font-weight: bold; padding: 0 14px;
        }}
        QPushButton:hover    {{ background: {color}; color: #fff; }}
        QPushButton:disabled {{ opacity: 0.35; }}
    """)
    return b


def _section_hdr(text: str, color: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"font-size: 13px; font-weight: bold; color: {color};"
        " background: transparent; border: none;"
    )
    return lbl


# ── Main wizard ───────────────────────────────────────────────────────────────

class FontWizard(QWidget):
    """نافذة استبدال خطوط اللعبة — تعمل مع جميع الألعاب."""

    done = Signal(int)   # عدد الملفات التي تم استبدالها

    def __init__(self, game_name: str, game_path: str = "", parent=None):
        super().__init__(
            parent,
            Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint
        )
        self._game_name  = game_name
        self._game_path  = game_path
        self._worker: _ReplaceWorker | None = None
        self._found_files: list[str] = []

        self.setWindowTitle(f"🔤  استبدال الخط — {game_name}")
        self.setMinimumSize(700, 600)
        self.resize(740, 640)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self._build()

    # ═══════════════════════════════════════════════════════════════════════════
    # Build
    # ═══════════════════════════════════════════════════════════════════════════

    def _build(self):
        c = theme.c
        self.setStyleSheet(f"""
            QWidget   {{ background: {c['bg']}; }}
            QLabel    {{ color: {c['primary']}; background: transparent; border: none; }}
            QLineEdit {{
                background: {c['surface']}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 6px;
                padding: 4px 8px; font-size: 11px;
            }}
            QRadioButton {{ color: {c['secondary']}; background: transparent; }}
            QRadioButton::indicator {{
                width: 14px; height: 14px;
                border: 1px solid {c['border']}; border-radius: 7px;
                background: {c['surface']};
            }}
            QRadioButton::indicator:checked {{
                background: {c['accent']}; border-color: {c['accent']};
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header(c))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        body_w = QWidget()
        body_w.setStyleSheet("background: transparent;")
        blay = QVBoxLayout(body_w)
        blay.setContentsMargins(20, 20, 20, 20)
        blay.setSpacing(14)

        blay.addWidget(self._build_font_card(c))
        blay.addWidget(self._build_folder_card(c))
        blay.addWidget(self._build_action_card(c))
        blay.addStretch()

        scroll.setWidget(body_w)
        root.addWidget(scroll, 1)

    # ── Header ─────────────────────────────────────────────────────────────────

    def _build_header(self, c: dict) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(58)
        bar.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-bottom: 1px solid {c['border']}; }}"
        )
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(22, 0, 22, 0)
        t = QLabel("🔤  استبدال الخط")
        t.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {c['teal']};")
        hl.addWidget(t)
        hl.addSpacing(16)
        sub = QLabel(f"🎮 {self._game_name}")
        sub.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        hl.addWidget(sub, 1)
        return bar

    # ── Card 1: Font selection ─────────────────────────────────────────────────

    def _build_font_card(self, c: dict) -> QFrame:
        card = _card(c)
        lay  = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        lay.addWidget(_section_hdr("① اختر الخط العربي", c["accent"]))

        self._font_group = QButtonGroup(self)
        self._font_radios: dict[str, QRadioButton] = {}
        first_available = True

        for name, filename in _BUILTIN_FONTS.items():
            path   = _builtin_path(filename)
            exists = os.path.isfile(path)
            suffix = "" if exists else "  ⚠ غير موجود"
            rb = QRadioButton(f"{name}  ({filename}){suffix}")
            rb.setEnabled(exists)
            if exists and first_available:
                rb.setChecked(True)
                first_available = False
            self._font_radios[filename] = rb
            self._font_group.addButton(rb)
            lay.addWidget(rb)

        # Custom font
        self._rb_custom = QRadioButton("خط مخصص:")
        self._font_group.addButton(self._rb_custom)
        custom_row = QHBoxLayout()
        custom_row.setSpacing(8)
        custom_row.addWidget(self._rb_custom)
        self._custom_font_edit = QLineEdit()
        self._custom_font_edit.setPlaceholderText("مسار ملف الخط (.ttf / .otf)…")
        browse_f = QPushButton("📂")
        browse_f.setFixedSize(30, 28)
        browse_f.setCursor(QCursor(Qt.PointingHandCursor))
        browse_f.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; border: 1px solid {c['border']};"
            f" border-radius: 5px; color: {c['primary']}; }}"
            f"QPushButton:hover {{ border-color: {c['accent']}; }}"
        )
        browse_f.clicked.connect(self._browse_font)
        custom_row.addWidget(self._custom_font_edit, 1)
        custom_row.addWidget(browse_f)
        lay.addLayout(custom_row)

        hint = QLabel(
            "ملاحظة: سيُستبدل محتوى كل ملف خط في المجلد المحدد بمحتوى الخط العربي.\n"
            "يُفضّل اختبار اللعبة بعد الاستبدال للتحقق من عمل الخط."
        )
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        return card

    # ── Card 2: Folder ────────────────────────────────────────────────────────

    def _build_folder_card(self, c: dict) -> QFrame:
        card = _card(c)
        lay  = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        lay.addWidget(_section_hdr("② اختر مجلد الخطوط في اللعبة", c["accent"]))

        hint = QLabel(
            "ابحث عن مجلد Fonts/ داخل مجلد اللعبة.\n"
            "الامتدادات المدعومة:  .ttf  ·  .otf  ·  .ufont  ·  .fnt"
        )
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("مسار مجلد الخطوط…")
        browse_d = QPushButton("📂  تصفح")
        browse_d.setFixedHeight(30)
        browse_d.setCursor(QCursor(Qt.PointingHandCursor))
        browse_d.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; border: 1px solid {c['border']};"
            f" border-radius: 6px; color: {c['primary']}; padding: 0 10px; }}"
            f"QPushButton:hover {{ border-color: {c['accent']}; }}"
        )
        browse_d.clicked.connect(self._browse_folder)
        row.addWidget(self._folder_edit, 1)
        row.addWidget(browse_d)
        lay.addLayout(row)

        scan_btn = _btn("🔍  مسح — عرض ملفات الخطوط في المجلد", c["blue"])
        scan_btn.clicked.connect(self._scan)
        lay.addWidget(scan_btn)

        return card

    # ── Card 3: Action ────────────────────────────────────────────────────────

    def _build_action_card(self, c: dict) -> QFrame:
        card = _card(c)
        lay  = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        lay.addWidget(_section_hdr("③ تنفيذ الاستبدال", c["accent"]))

        self._log_w = QTextEdit()
        self._log_w.setReadOnly(True)
        self._log_w.setFixedHeight(170)
        self._log_w.setStyleSheet(
            f"QTextEdit {{ background: {c['bg']}; color: {c['secondary']};"
            f" border: 1px solid {c['border']}; border-radius: 6px;"
            f" font-family: Consolas, monospace; font-size: 10px; padding: 6px; }}"
        )
        lay.addWidget(self._log_w)

        self._prog = QProgressBar()
        self._prog.setRange(0, 100)
        self._prog.setValue(0)
        self._prog.setFixedHeight(8)
        self._prog.setTextVisible(False)
        self._prog.setStyleSheet(
            f"QProgressBar {{ background: {c['surface']}; border: none; border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {c['teal']}; border-radius: 4px; }}"
        )
        lay.addWidget(self._prog)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self._replace_btn = _btn("✅  استبدال الكل", c["teal"])
        self._replace_btn.clicked.connect(self._replace)
        self._restore_btn = _btn("↩  استعادة النسخ الاحتياطية", c["orange"])
        self._restore_btn.clicked.connect(self._restore)
        btn_row.addWidget(self._replace_btn)
        btn_row.addWidget(self._restore_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        return card

    # ═══════════════════════════════════════════════════════════════════════════
    # Actions
    # ═══════════════════════════════════════════════════════════════════════════

    def _browse_font(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "اختر ملف الخط", "",
            "Font Files (*.ttf *.otf);;All Files (*)"
        )
        if path:
            self._custom_font_edit.setText(path)
            self._rb_custom.setChecked(True)

    def _browse_folder(self):
        start = self._game_path or ""
        folder = QFileDialog.getExistingDirectory(
            self, "اختر مجلد الخطوط", start
        )
        if folder:
            self._folder_edit.setText(folder)

    def _get_font_src(self) -> str | None:
        checked = self._font_group.checkedButton()
        if checked is self._rb_custom:
            path = self._custom_font_edit.text().strip()
            if not os.path.isfile(path):
                self._log("❌  اختر ملف خط مخصص صالح أولاً", "accent")
                return None
            return path
        for filename, rb in self._font_radios.items():
            if rb is checked:
                path = _builtin_path(filename)
                if os.path.isfile(path):
                    return path
        self._log("❌  اختر خطاً أولاً", "accent")
        return None

    def _scan(self):
        folder = self._folder_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            self._log("❌  اختر مجلداً صالحاً أولاً", "accent")
            return
        self._found_files = []
        for root, _, files in os.walk(folder):
            for fname in files:
                if os.path.splitext(fname.lower())[1] in _FONT_EXTS:
                    self._found_files.append(os.path.join(root, fname))
        self._log_w.clear()
        if self._found_files:
            self._log(f"🔍  وُجد {len(self._found_files)} ملف خط:", "teal")
            for p in self._found_files:
                self._log(f"  📄 {os.path.basename(p)}", "secondary")
        else:
            self._log("⚠  لم يُعثر على ملفات خطوط (.ttf / .otf / .ufont / .fnt)", "yellow")

    def _replace(self):
        if not self._found_files:
            self._log("⚠  نفّذ «مسح» أولاً للعثور على ملفات الخطوط", "yellow")
            return
        font_src = self._get_font_src()
        if not font_src:
            return
        self._log(f"🚀  بدء الاستبدال — الخط: {os.path.basename(font_src)}", "teal")
        self._replace_btn.setEnabled(False)
        self._prog.setValue(0)
        self._worker = _ReplaceWorker(font_src, list(self._found_files))
        self._worker.logged.connect(lambda m, k: self._log(m, k))
        self._worker.progress.connect(
            lambda d, t: self._prog.setValue(int(d / t * 100))
        )
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _restore(self):
        folder = self._folder_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            self._log("❌  اختر المجلد الذي يحتوي النسخ الاحتياطية أولاً", "accent")
            return
        restored = 0
        for root, _, files in os.walk(folder):
            for fname in files:
                if fname.endswith(".bak"):
                    bak  = os.path.join(root, fname)
                    orig = bak[:-4]
                    try:
                        shutil.copy2(bak, orig)
                        self._log(f"↩  تمت الاستعادة: {fname[:-4]}", "orange")
                        restored += 1
                    except Exception as exc:
                        self._log(f"❌  خطأ: {exc}", "accent")
        if restored:
            self._log(f"✅  تمت استعادة {restored} ملف", "green")
        else:
            self._log("⚠  لا توجد نسخ احتياطية (.bak) في هذا المجلد", "yellow")

    def _on_done(self, ok: bool, count: int):
        self._replace_btn.setEnabled(True)
        self._prog.setValue(100)
        total = len(self._found_files)
        if ok:
            self._log(f"✅  اكتمل — تم استبدال {count} / {total} ملف خط", "green")
        else:
            self._log(f"⚠  اكتمل مع أخطاء — {count} / {total}", "yellow")
        self.done.emit(count)

    def _log(self, msg: str, color_key: str = "secondary"):
        color = theme.c.get(color_key, theme.c["secondary"])
        self._log_w.append(f'<span style="color:{color};">{msg}</span>')
        self._log_w.moveCursor(QTextCursor.End)

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.wait(2000)
        super().closeEvent(event)
