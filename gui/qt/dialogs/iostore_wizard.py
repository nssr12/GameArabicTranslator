"""
gui/qt/dialogs/iostore_wizard.py  —  معالج IoStore / UAsset (المرحلة 7)
"""

from __future__ import annotations
import os

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QLineEdit, QComboBox, QTextEdit, QProgressBar,
    QScrollArea, QFileDialog, QSizePolicy, QCheckBox,
    QRadioButton, QButtonGroup, QToolButton, QApplication,
)
from PySide6.QtCore  import Qt, QThread, Signal, QTimer
from PySide6.QtGui   import QCursor, QTextCursor, QFont

from gui.qt.theme import theme

# Import constants from the engine
from games.iostore.translator import (
    IoStoreTranslator, UE_VERSIONS, ZEN_VERSIONS, EXTRACTION_MODES
)


# ── Generic step worker ───────────────────────────────────────────────────────

class StepWorker(QThread):
    """يُنفّذ دالة مُمرَّرة في thread خلفي ويُصدر الحالة."""

    log_line  = Signal(str)
    progress  = Signal(int, int)
    finished  = Signal(bool)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self._func   = func
        self._args   = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._func(*self._args, **self._kwargs)
            self.finished.emit(bool(result))
        except Exception as e:
            self.log_line.emit(f"[خطأ] {e}")
            self.finished.emit(False)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sep(c: dict) -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background: {c['border']}; border: none;")
    return f


def _browse_style(c: dict) -> str:
    return (
        f"QPushButton {{ background: {c['surface']}; border: 1px solid {c['border']};"
        f" border-radius: 6px; font-size: 14px; color: {c['primary']}; }}"
        f"QPushButton:hover {{ background: {c['hover']}; border-color: {c['accent']}; }}"
    )


# ── Step card widget ──────────────────────────────────────────────────────────

class StepCard(QFrame):
    """بطاقة خطوة واحدة في المعالج."""

    def __init__(self, number: int, title: str, parent=None):
        super().__init__(parent)
        c = theme.c
        self.setStyleSheet(f"""
            QFrame {{
                background: {c['card']};
                border: 1px solid {c['border']};
                border-radius: 10px;
            }}
        """)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(18, 14, 18, 14)
        self._lay.setSpacing(10)

        # Header row
        hdr = QHBoxLayout()
        num_badge = QLabel(str(number))
        num_badge.setFixedSize(26, 26)
        num_badge.setAlignment(Qt.AlignCenter)
        num_badge.setStyleSheet(f"""
            background: {c['accent']}; color: #fff;
            border-radius: 13px; font-weight: bold; font-size: 12px;
            border: none;
        """)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {c['primary']};"
            " background: transparent; border: none;"
        )
        self._badge = QLabel("⬜ معلّق")
        self._badge.setStyleSheet(
            f"font-size: 10px; color: {c['muted']};"
            " background: transparent; border: none;"
        )
        hdr.addWidget(num_badge)
        hdr.addWidget(title_lbl, 1)
        hdr.addWidget(self._badge)
        self._lay.addLayout(hdr)
        self._lay.addWidget(_sep(c))

    def set_status(self, text: str, color: str):
        self._badge.setText(text)
        self._badge.setStyleSheet(
            f"font-size: 10px; color: {color};"
            " background: transparent; border: none;"
        )

    def body(self) -> QVBoxLayout:
        return self._lay


# ── Main dialog ───────────────────────────────────────────────────────────────

class IoStoreWizard(QWidget):
    """معالج IoStore — استخراج وترجمة وإعادة تعبئة حزم UE5."""

    def __init__(self, engine=None, cache=None, config: dict = None,
                 game_id: str = None, game_cfg: dict = None, parent=None):
        super().__init__(
            parent,
            Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint
        )
        self._engine   = engine
        self._cache    = cache
        self._config   = config or {}
        self._game_id  = game_id or "IoStore"
        self._game_cfg = game_cfg or {}

        # Runtime state shared across steps
        self._legacy_folder:   str | None = None
        self._json_paths:      list[str]  = []
        self._all_texts:       list[str]  = []
        self._translations:    dict       = {}
        self._s3_gname:        str        = ""
        self._s3_exmode:       str        = ""
        self._worker: StepWorker | None   = None
        self._translation_window          = None

        self.setWindowTitle("📦  IoStore / UAsset Wizard")
        self.setMinimumSize(900, 700)
        self.resize(1100, 780)
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        c = theme.c
        self.setStyleSheet(f"""
            QDialog   {{ background: {c['bg']}; }}
            QLabel    {{ color: {c['primary']}; background: transparent; border: none; }}
            QLineEdit, QComboBox {{
                background: {c['surface']}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 6px; padding: 4px 8px;
                selection-background-color: {c['accent']};
            }}
            QLineEdit:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
            QComboBox::drop-down {{ border: none; width: 22px; }}
            QComboBox QAbstractItemView {{
                background: {c['surface']}; color: {c['primary']};
                selection-background-color: {c['accent']};
            }}
            QRadioButton, QCheckBox {{
                color: {c['secondary']}; background: transparent;
            }}
            QRadioButton::indicator, QCheckBox::indicator {{
                width: 14px; height: 14px;
                border: 1px solid {c['border']}; border-radius: 3px;
                background: {c['surface']};
            }}
            QRadioButton::indicator {{ border-radius: 7px; }}
            QRadioButton::indicator:checked, QCheckBox::indicator:checked {{
                background: {c['accent']}; border-color: {c['accent']};
            }}
            QTextEdit {{
                background: {c['surface']}; color: {c['secondary']};
                border: 1px solid {c['border']}; border-radius: 6px;
                font-family: Consolas, monospace; font-size: 10px;
                selection-background-color: {c['accent']};
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Title bar
        title_bar = QFrame()
        title_bar.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-bottom: 1px solid {c['border']}; }}"
        )
        tb_lay = QHBoxLayout(title_bar)
        tb_lay.setContentsMargins(20, 12, 20, 12)
        t = QLabel("📦  IoStore / UAsset Wizard")
        t.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {c['accent']};"
            " background: transparent; border: none;"
        )
        sub = QLabel("استخراج • ترجمة • إعادة التعبئة — UE5 IoStore containers")
        sub.setStyleSheet(
            f"font-size: 11px; color: {c['muted']}; background: transparent; border: none;"
        )
        tb_lay.addWidget(t)
        tb_lay.addSpacing(16)
        tb_lay.addWidget(sub, 1)
        root.addWidget(title_bar)

        # Main split: left (wizard) | right (log)
        split = QHBoxLayout()
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(0)

        # ── Left: scrollable wizard steps ─────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background: {c['bg']}; border: none;")

        wizard_widget = QWidget()
        wizard_widget.setStyleSheet(f"background: {c['bg']};")
        self._wiz_lay = QVBoxLayout(wizard_widget)
        self._wiz_lay.setContentsMargins(16, 16, 16, 16)
        self._wiz_lay.setSpacing(12)

        self._build_config_card()
        self._build_step1()
        self._build_step2()
        self._build_step3()
        self._build_step4()
        self._build_step5()
        self._build_step6()
        self._wiz_lay.addStretch()

        scroll.setWidget(wizard_widget)
        split.addWidget(scroll, 3)

        # ── Right: log panel ──────────────────────────────────────────────────
        log_panel = QFrame()
        log_panel.setFixedWidth(310)
        log_panel.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-left: 1px solid {c['border']}; }}"
        )
        log_lay = QVBoxLayout(log_panel)
        log_lay.setContentsMargins(0, 0, 0, 0)
        log_lay.setSpacing(0)

        log_hdr = QFrame()
        log_hdr.setStyleSheet(
            f"QFrame {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; }}"
        )
        log_hdr_lay = QHBoxLayout(log_hdr)
        log_hdr_lay.setContentsMargins(12, 8, 12, 8)
        log_hdr_lay.addWidget(QLabel("📋  السجل"))
        clear_log_btn = QToolButton()
        clear_log_btn.setText("مسح")
        clear_log_btn.setCursor(QCursor(Qt.PointingHandCursor))
        clear_log_btn.setStyleSheet(
            f"QToolButton {{ background: transparent; border: none;"
            f" color: {c['muted']}; font-size: 10px; }}"
            f"QToolButton:hover {{ color: {c['accent']}; }}"
        )
        clear_log_btn.clicked.connect(lambda: self._log.clear())
        log_hdr_lay.addStretch()
        log_hdr_lay.addWidget(clear_log_btn)
        log_lay.addWidget(log_hdr)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("سيظهر هنا مخرجات كل خطوة…")
        self._log.setStyleSheet(
            f"QTextEdit {{ background: {c['bg']}; color: {c['secondary']};"
            f" border: none; border-radius: 0; padding: 8px; font-size: 10px; }}"
        )
        log_lay.addWidget(self._log, 1)

        # Progress bar
        self._prog_bar = QProgressBar()
        self._prog_bar.setRange(0, 100)
        self._prog_bar.setValue(0)
        self._prog_bar.setFixedHeight(6)
        self._prog_bar.setTextVisible(False)
        self._prog_bar.setStyleSheet(f"""
            QProgressBar {{ background: {c['surface']}; border: none; border-radius: 0; }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {c['accent']}, stop:1 {c['blue']});
            }}
        """)
        log_lay.addWidget(self._prog_bar)

        split.addWidget(log_panel)
        root.addLayout(split, 1)

        # Bottom close button
        bottom = QFrame()
        bottom.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-top: 1px solid {c['border']}; }}"
        )
        bot_lay = QHBoxLayout(bottom)
        bot_lay.setContentsMargins(16, 10, 16, 10)
        bot_lay.addStretch()
        close_btn = QPushButton("إغلاق")
        close_btn.setFixedHeight(34)
        close_btn.setMinimumWidth(90)
        close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        close_btn.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; color: {c['muted']};"
            f" border: 1px solid {c['border']}; border-radius: 8px; padding: 0 18px; }}"
            f"QPushButton:hover {{ background: {c['hover']}; color: {c['primary']}; }}"
        )
        close_btn.clicked.connect(self.close)
        bot_lay.addWidget(close_btn)
        root.addWidget(bottom)

    # ── Config card ───────────────────────────────────────────────────────────

    def _build_config_card(self):
        c    = theme.c
        card = StepCard(0, "⚙️  الإعدادات العامة")
        lay  = card.body()
        card.set_status("", c["muted"])

        tools = self._config.get("tools", {})
        cfg   = self._game_cfg

        def _field(label: str, default: str = "", placeholder: str = "") -> QLineEdit:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(130)
            lbl.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
            le  = QLineEdit()
            le.setText(default)
            le.setPlaceholderText(placeholder)
            row.addWidget(lbl)
            row.addWidget(le, 1)
            lay.addLayout(row)
            return le

        def _combo_field(label: str, items: list, default: str = "") -> QComboBox:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(130)
            lbl.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
            cb  = QComboBox()
            cb.addItems(items)
            if default in items:
                cb.setCurrentText(default)
            row.addWidget(lbl)
            row.addWidget(cb, 1)
            lay.addLayout(row)
            return cb

        def _path_field(label: str, default: str, placeholder: str,
                        folder: bool = False, filt: str = ""):
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(130)
            lbl.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
            le  = QLineEdit()
            le.setText(default)
            le.setPlaceholderText(placeholder)
            btn = QPushButton("📂")
            btn.setFixedSize(30, 30)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setStyleSheet(_browse_style(c))

            def _browse():
                if folder:
                    p = QFileDialog.getExistingDirectory(self, label, "")
                else:
                    p, _ = QFileDialog.getOpenFileName(
                        self, label, "", filt or "Executable (*.exe)"
                    )
                if p:
                    le.setText(p)

            btn.clicked.connect(_browse)
            row.addWidget(lbl)
            row.addWidget(le, 1)
            row.addWidget(btn)
            lay.addLayout(row)
            return le

        # Game name — prefer display name from config over raw game_id
        _default_name = self._game_cfg.get("name", "") or self._game_id
        self._game_name_field = _field(
            "اسم اللعبة (كاش):",
            _default_name,
            "اسم اللعبة كما في الكاش"
        )

        # UE Version
        self._ue_ver_combo = _combo_field(
            "إصدار Unreal:",
            UE_VERSIONS,
            UE_VERSIONS[0]
        )

        # Zen Version (for step 5)
        self._zen_ver_combo = _combo_field(
            "إصدار Zen (repack):",
            ZEN_VERSIONS,
            ZEN_VERSIONS[0]
        )

        # Extraction mode
        mode_vals   = [m[0] for m in EXTRACTION_MODES]
        mode_labels = [m[1] for m in EXTRACTION_MODES]
        row_mode = QHBoxLayout()
        lbl_mode = QLabel("وضع الاستخراج:")
        lbl_mode.setFixedWidth(130)
        lbl_mode.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        self._extr_mode_combo = QComboBox()
        for val, label in EXTRACTION_MODES:
            self._extr_mode_combo.addItem(label, val)
        row_mode.addWidget(lbl_mode)
        row_mode.addWidget(self._extr_mode_combo, 1)
        lay.addLayout(row_mode)

        # AES Key
        self._aes_field = _field("مفتاح AES:", "", "اختياري — للحزم المشفّرة")
        self._aes_field.setEchoMode(QLineEdit.Password)

        # Tool paths
        self._retoc_field = _path_field(
            "retoc.exe:",
            tools.get("retoc_path", ""),
            "مسار retoc.exe",
            folder=False, filt="retoc (retoc.exe);;Exe (*.exe);;All (*.*)"
        )
        self._uagui_field = _path_field(
            "UAssetGUI.exe:",
            tools.get("uassetgui_path", ""),
            "مسار UAssetGUI.exe",
            folder=False, filt="UAssetGUI (UAssetGUI.exe);;Exe (*.exe);;All (*.*)"
        )

        # Mappings
        self._mappings_field = _field(
            "Mappings (.usmap):",
            "",
            "اختياري — اسم الملف بدون الامتداد"
        )

        self._wiz_lay.addWidget(card)

    # ── Step 1: to-legacy ─────────────────────────────────────────────────────

    def _build_step1(self):
        c    = theme.c
        card = StepCard(1, "Step 1 — استخراج IoStore → ملفات Legacy")
        lay  = card.body()
        self._s1_card = card

        hint = QLabel("اختر مجلد Paks الخاص باللعبة (يحتوي .utoc / .ucas / .pak)")
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        lay.addWidget(hint)

        def _path_row(label, placeholder, folder=True):
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(110)
            lbl.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
            le  = QLineEdit()
            le.setPlaceholderText(placeholder)
            btn = QPushButton("📂")
            btn.setFixedSize(30, 30)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setStyleSheet(_browse_style(c))

            def _browse():
                if folder:
                    p = QFileDialog.getExistingDirectory(self, label, "")
                else:
                    p, _ = QFileDialog.getOpenFileName(self, label, "")
                if p:
                    le.setText(p)

            btn.clicked.connect(_browse)
            row.addWidget(lbl)
            row.addWidget(le, 1)
            row.addWidget(btn)
            lay.addLayout(row)
            return le

        self._paks_field   = _path_row("مجلد Paks:", "مسار مجلد Paks")
        self._out1_field   = _path_row("مجلد الإخراج:", "سيُملأ تلقائياً")

        # Auto-fill output
        def _autofill():
            p = self._paks_field.text().strip().rstrip("/\\")
            if p and not self._out1_field.text().strip():
                parent = os.path.dirname(p)
                name   = os.path.basename(p)
                self._out1_field.setText(os.path.join(parent, name + "_legacy"))

        self._paks_field.textChanged.connect(_autofill)

        # Buttons
        btn_row = QHBoxLayout()
        run_btn = self._step_btn("▶  تشغيل الخطوة 1", c["accent"])
        run_btn.clicked.connect(self._run_step1)
        self._s1_cache_btn = self._step_btn("📦  حفظ في for_cache", c["muted"])
        self._s1_cache_btn.setEnabled(False)
        self._s1_cache_btn.clicked.connect(self._save_step1_to_cache)
        btn_row.addWidget(run_btn)
        btn_row.addWidget(self._s1_cache_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._wiz_lay.addWidget(card)

    # ── Step 2: uasset → JSON ─────────────────────────────────────────────────

    def _build_step2(self):
        c    = theme.c
        card = StepCard(2, "Step 2 — تحويل .uasset → JSON")
        lay  = card.body()
        self._s2_card = card

        # Mode radios
        mode_row = QHBoxLayout()
        self._s2_mode_group = QButtonGroup(self)
        rb_all = QRadioButton("كل ملفات .uasset في مجلد Legacy")
        rb_all.setChecked(True)
        rb_single = QRadioButton("ملف واحد فقط")
        self._s2_mode_group.addButton(rb_all, 0)
        self._s2_mode_group.addButton(rb_single, 1)
        mode_row.addWidget(rb_all)
        mode_row.addSpacing(16)
        mode_row.addWidget(rb_single)
        mode_row.addStretch()
        lay.addLayout(mode_row)

        # Single file row
        single_row = QHBoxLayout()
        lbl_s = QLabel("ملف .uasset:")
        lbl_s.setFixedWidth(110)
        lbl_s.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        self._s2_single_field = QLineEdit()
        self._s2_single_field.setPlaceholderText("مطلوب عند اختيار 'ملف واحد'")
        btn_s = QPushButton("📂")
        btn_s.setFixedSize(30, 30)
        btn_s.setCursor(QCursor(Qt.PointingHandCursor))
        btn_s.setStyleSheet(_browse_style(c))
        btn_s.clicked.connect(lambda: self._browse_to(
            self._s2_single_field,
            "UAsset (*.uasset);;All (*.*)", folder=False
        ))
        single_row.addWidget(lbl_s)
        single_row.addWidget(self._s2_single_field, 1)
        single_row.addWidget(btn_s)
        lay.addLayout(single_row)

        self._s2_info = QLabel("")
        self._s2_info.setStyleSheet(f"color: {c['teal']}; font-size: 11px;")
        lay.addWidget(self._s2_info)

        btn_row = QHBoxLayout()
        run_btn = self._step_btn("▶  تشغيل الخطوة 2", c["accent"])
        run_btn.clicked.connect(self._run_step2)
        btn_row.addWidget(run_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._wiz_lay.addWidget(card)

    # ── Step 3: Translate ─────────────────────────────────────────────────────

    def _build_step3(self):
        c    = theme.c
        card = StepCard(3, "Step 3 — الترجمة")
        lay  = card.body()
        self._s3_card = card

        self._s3_strings_lbl = QLabel("النصوص المكتشفة: —")
        self._s3_strings_lbl.setStyleSheet(f"color: {c['secondary']}; font-size: 12px;")
        lay.addWidget(self._s3_strings_lbl)

        # Load existing JSON shortcut
        load_frame = QFrame()
        load_frame.setStyleSheet(
            f"QFrame {{ background: {c['surface']}; border: 1px solid {c['border']};"
            " border-radius: 8px; }}"
        )
        load_lay = QVBoxLayout(load_frame)
        load_lay.setContentsMargins(12, 10, 12, 10)
        load_lay.setSpacing(6)
        hint_lbl = QLabel("📂  تحميل ملف .uasset.json موجود مسبقاً (تجاوز الخطوتين 1 و2)")
        hint_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        load_lay.addWidget(hint_lbl)
        load_row = QHBoxLayout()
        self._load_json_field = QLineEdit()
        self._load_json_field.setPlaceholderText("مسار ملف .uasset.json")
        browse_j = QPushButton("📂")
        browse_j.setFixedSize(30, 30)
        browse_j.setCursor(QCursor(Qt.PointingHandCursor))
        browse_j.setStyleSheet(_browse_style(c))
        browse_j.clicked.connect(lambda: self._browse_to(
            self._load_json_field, "JSON (*.json);;All (*.*)", folder=False
        ))
        load_btn = self._step_btn("تحميل ←", c["teal"], height=30)
        load_btn.clicked.connect(self._load_json_into_step3)
        load_row.addWidget(self._load_json_field, 1)
        load_row.addWidget(browse_j)
        load_row.addWidget(load_btn)
        load_lay.addLayout(load_row)
        lay.addWidget(load_frame)

        # Translation mode
        mode_lbl = QLabel("وضع الترجمة:")
        mode_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        lay.addWidget(mode_lbl)

        self._s3_mode_group = QButtonGroup(self)
        for i, (val, label) in enumerate([
            ("missing",    "🔄  استكمال المفقود (الافتراضي)"),
            ("fresh",      "🆕  ترجمة كاملة من الصفر"),
            ("cache_only", "📦  من الكاش فقط (بدون API)"),
        ]):
            rb = QRadioButton(label)
            rb.setProperty("mode_val", val)
            if i == 0:
                rb.setChecked(True)
            self._s3_mode_group.addButton(rb, i)
            lay.addWidget(rb)

        # Single button — opens the non-blocking translation window
        btn_row = QHBoxLayout()
        self._s3_run_btn = self._step_btn("▶  فتح نافذة الترجمة", c["accent"])
        self._s3_run_btn.clicked.connect(self._run_step3)
        btn_row.addWidget(self._s3_run_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._wiz_lay.addWidget(card)

    # ── Step 4: Apply translations + JSON → .uasset ───────────────────────────

    def _build_step4(self):
        c    = theme.c
        card = StepCard(4, "Step 4 — تطبيق الترجمات + JSON → .uasset")
        lay  = card.body()
        self._s4_card = card

        hint = QLabel(
            "يُطبّق الترجمات على ملفات JSON ثم يُحوّلها مجدداً إلى .uasset باستخدام UAssetGUI"
        )
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # ── Status panel ──────────────────────────────────────────────────────
        s4_status = QFrame()
        s4_status.setStyleSheet(
            f"QFrame {{ background: {c['surface']}; border: 1px solid {c['border']};"
            " border-radius: 6px; }}"
        )
        sl4 = QHBoxLayout(s4_status)
        sl4.setContentsMargins(12, 7, 12, 7)
        sl4.setSpacing(16)

        def _chip4(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {c['muted']}; font-size: 10px;"
                " background: transparent; border: none;"
            )
            return lbl

        self._s4_chip_json  = _chip4("📄  JSON: —")
        self._s4_chip_orig  = _chip4("📋  .orig: —")
        self._s4_chip_uasset = _chip4("📦  .uasset: —")

        for ch in (self._s4_chip_json, self._s4_chip_orig, self._s4_chip_uasset):
            sl4.addWidget(ch)
        sl4.addStretch()
        lay.addWidget(s4_status)

        btn_row = QHBoxLayout()
        run_btn = self._step_btn("▶  تشغيل الخطوة 4", c["accent"])
        run_btn.clicked.connect(self._run_step4)
        btn_row.addWidget(run_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._wiz_lay.addWidget(card)

    # ── Step 5: to-zen (repack) ───────────────────────────────────────────────

    def _build_step5(self):
        c    = theme.c
        card = StepCard(5, "Step 5 — إعادة التعبئة (retoc to-zen)")
        lay  = card.body()
        self._s5_card = card

        hint = QLabel("يُعيد تعبئة الملفات إلى حزمة .utoc/.ucas/.pak للعبة")
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        lay.addWidget(hint)

        # Output base path — same as Paks_legacy folder from Step 1
        out_row = QHBoxLayout()
        lbl_out = QLabel("مجلد Paks_legacy:")
        lbl_out.setFixedWidth(160)
        lbl_out.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        self._out5_field = QLineEdit()
        self._out5_field.setPlaceholderText(
            "مجلد Paks_legacy — يُملأ تلقائياً من الخطوة 1"
        )
        btn_out = QPushButton("📂")
        btn_out.setFixedSize(30, 30)
        btn_out.setCursor(QCursor(Qt.PointingHandCursor))
        btn_out.setStyleSheet(_browse_style(c))
        btn_out.clicked.connect(lambda: self._browse_to(
            self._out5_field, folder=True
        ))
        out_row.addWidget(lbl_out)
        out_row.addWidget(self._out5_field, 1)
        out_row.addWidget(btn_out)
        lay.addLayout(out_row)

        # Game target dir (for auto-install)
        tgt_row = QHBoxLayout()
        lbl_tgt = QLabel("مجلد Paks الهدف (تثبيت مباشر):")
        lbl_tgt.setFixedWidth(160)
        lbl_tgt.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        self._tgt5_field = QLineEdit()
        game_path = self._game_cfg.get("game_path", "")
        self._tgt5_field.setText(game_path)
        self._tgt5_field.setPlaceholderText("اختياري — مجلد Paks للتثبيت الفوري")
        btn_tgt = QPushButton("📂")
        btn_tgt.setFixedSize(30, 30)
        btn_tgt.setCursor(QCursor(Qt.PointingHandCursor))
        btn_tgt.setStyleSheet(_browse_style(c))
        btn_tgt.clicked.connect(lambda: self._browse_to(
            self._tgt5_field, folder=True
        ))
        tgt_row.addWidget(lbl_tgt)
        tgt_row.addWidget(self._tgt5_field, 1)
        tgt_row.addWidget(btn_tgt)
        lay.addLayout(tgt_row)

        btn_row = QHBoxLayout()
        run_btn = self._step_btn("▶  تشغيل الخطوة 5", c["accent"])
        run_btn.clicked.connect(self._run_step5)
        btn_row.addWidget(run_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._wiz_lay.addWidget(card)

    # ── Step 6: Save package (ready + for_cache + package.json) ─────────────────

    def _build_step6(self):
        c    = theme.c
        card = StepCard(6, "Step 6 — حفظ الحزمة (ready + for_cache)")
        lay  = card.body()
        self._s6_card = card

        hint = QLabel(
            "يحفظ ملفات .pak/.ucas/.utoc في mods/<لعبة>/ready/  |  "
            "يحفظ مجلد Paks_legacy في mods/<لعبة>/for_cache/  |  "
            "يُحدّث package.json — لا يتطلب اكتمال الخطوة 5."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        lay.addWidget(hint)

        # Info chips
        info_row = QHBoxLayout()
        info_row.setSpacing(20)
        muted = f"color: {c['muted']}; font-size: 10px; background: transparent; border: none;"

        self._s6_mod_lbl    = QLabel("📦  mods/—/")
        self._s6_pak_lbl    = QLabel("🗜  pak: —")
        self._s6_legacy_lbl = QLabel("📂  legacy: —")
        for lbl in (self._s6_mod_lbl, self._s6_pak_lbl, self._s6_legacy_lbl):
            lbl.setStyleSheet(muted)
            info_row.addWidget(lbl)
        info_row.addStretch()
        lay.addLayout(info_row)

        # Status label
        status_row = QHBoxLayout()
        self._s6_status_lbl = QLabel("—")
        self._s6_status_lbl.setStyleSheet(muted)
        status_row.addWidget(self._s6_status_lbl)
        status_row.addStretch()
        lay.addLayout(status_row)

        btn_row = QHBoxLayout()
        run_btn = self._step_btn("💾  حفظ الحزمة", c["green"])
        run_btn.clicked.connect(self._run_step6)
        btn_row.addWidget(run_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._wiz_lay.addWidget(card)

    # ── Widget helpers ────────────────────────────────────────────────────────

    def _step_btn(self, label: str, color: str, height: int = 34) -> QPushButton:
        c   = theme.c
        btn = QPushButton(label)
        btn.setFixedHeight(height)
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0,0,0,0.15); color: {color};
                border: 1px solid {color}; border-radius: 8px;
                font-weight: bold; padding: 0 14px;
            }}
            QPushButton:hover {{ background: {color}; color: #fff; }}
            QPushButton:disabled {{ opacity: 0.4; }}
        """)
        return btn

    def _browse_to(self, field: QLineEdit, filt: str = "", folder: bool = False):
        if folder:
            p = QFileDialog.getExistingDirectory(self, "اختر مجلداً", "")
        else:
            p, _ = QFileDialog.getOpenFileName(self, "اختر ملفاً", "", filt)
        if p:
            field.setText(p)

    # ── Shared log + translator factory ──────────────────────────────────────

    def _append_log(self, msg: str, color: str = None):
        # ── Intercept engine status messages for Step 4 chip updates ─────────
        tc = theme.c
        if "Saved original backup:" in msg:
            fname = msg.split(":")[-1].strip()
            self._s4_chip_orig.setText(f"📋  .orig: {fname}")
            self._s4_chip_orig.setStyleSheet(
                f"color:{tc['green']};font-size:10px;background:transparent;border:none;"
            )
        elif "Applied translations:" in msg:
            fname = msg.split(":")[-1].strip()
            self._s4_chip_json.setText(f"📄  JSON: {fname}")
            self._s4_chip_json.setStyleSheet(
                f"color:{tc['blue2']};font-size:10px;background:transparent;border:none;"
            )
        elif "uasset" in msg.lower() and ("convert" in msg.lower() or "→" in msg or "done" in msg.lower()):
            self._s4_chip_uasset.setStyleSheet(
                f"color:{tc['green']};font-size:10px;background:transparent;border:none;"
            )
        # ── Write to log ──────────────────────────────────────────────────────
        c = color or tc["secondary"]
        self._log.append(f'<span style="color:{c};">{msg}</span>')
        self._log.moveCursor(QTextCursor.End)

    def _make_translator(self, retoc: str = "", uagui: str = "") -> IoStoreTranslator:
        t = IoStoreTranslator(
            translator_engine=self._engine,
            cache=self._cache,
            retoc_path=retoc or None,
            uassetgui_path=uagui or None,
        )
        t.set_callbacks(
            log=lambda m: QTimer.singleShot(
                0, lambda msg=m: self._append_log(msg)
            ),
            progress=lambda cur, tot: QTimer.singleShot(
                0, lambda c=cur, t=tot: self._prog_bar.setValue(
                    int(c / t * 100) if t else 0
                )
            ),
        )
        return t

    def _new_translator(self) -> IoStoreTranslator:
        """يُنشئ translator بعد قراءة المسارات من الـ UI (استدعاء من main thread فقط)."""
        return self._make_translator(
            retoc=self._retoc_field.text().strip(),
            uagui=self._uagui_field.text().strip(),
        )

    # ── Step 1 actions ────────────────────────────────────────────────────────

    def _run_step1(self):
        paks = self._paks_field.text().strip()
        out  = self._out1_field.text().strip()
        if not paks:
            self._append_log("✗  اختر مجلد Paks أولاً", theme.c["accent"])
            return
        if not out:
            self._append_log("✗  حدد مجلد الإخراج", theme.c["accent"])
            return

        self._s1_card.set_status("🔄 جاري التنفيذ…", theme.c["yellow"])
        self._prog_bar.setValue(0)
        aes = self._aes_field.text().strip()
        tr  = self._new_translator()

        def _work():
            ok = tr.to_legacy(paks, out, aes)
            if ok:
                self._legacy_folder = out
            return ok

        self._run_worker(_work, self._s1_card, on_success=self._after_step1)

    def _after_step1(self):
        self._s1_cache_btn.setEnabled(True)
        self._s1_cache_btn.setStyleSheet(
            f"QPushButton {{ background: rgba(0,0,0,0.15); color: {theme.c['green']};"
            f" border: 1px solid {theme.c['green']}; border-radius: 8px;"
            f" font-weight: bold; padding: 0 14px; }}"
            f"QPushButton:hover {{ background: {theme.c['green']}; color: #fff; }}"
        )
        self._append_log(
            f"✓  الإخراج: {self._legacy_folder}", theme.c["green"]
        )
        # Auto-fill Step 5 Paks_legacy field
        if self._legacy_folder and not self._out5_field.text().strip():
            self._out5_field.setText(self._legacy_folder)
        # Update Step 6 info chips
        if self._legacy_folder and hasattr(self, "_s6_legacy_lbl"):
            self._s6_legacy_lbl.setText(
                f"📂  legacy: {os.path.basename(self._legacy_folder)}"
            )
            self._s6_legacy_lbl.setStyleSheet(
                f"color: {theme.c['teal']}; font-size: 10px;"
                " background: transparent; border: none;"
            )
        if hasattr(self, "_s6_mod_lbl"):
            from games.translation_package import TranslationPackage
            gname = self._game_name_field.text().strip() or self._game_id
            mod_dir = TranslationPackage().get_mod_dir(gname)
            self._s6_mod_lbl.setText(f"📦  {mod_dir}")
            self._s6_mod_lbl.setStyleSheet(
                f"color: {theme.c['teal']}; font-size: 10px;"
                " background: transparent; border: none;"
            )

    def _save_step1_to_cache(self):
        try:
            from games.translation_package import TranslationPackage
            gname  = self._game_name_field.text().strip() or self._game_id
            legacy = self._legacy_folder or self._out1_field.text().strip()
            if not legacy or not os.path.isdir(legacy):
                self._append_log("✗  لا يوجد مجلد legacy — نفّذ الخطوة 1 أولاً",
                                  theme.c["accent"])
                return
            p = TranslationPackage()
            ok, lines = p.copy_to_for_cache(gname, legacy)
            for ln in lines:
                self._append_log(ln)
            if ok:
                p.save_wizard_config(gname, {
                    "legacy_name": os.path.basename(legacy),
                    "cache_game_name": gname,
                })
                self._append_log("✓  تم الحفظ في for_cache", theme.c["green"])
        except ImportError:
            self._append_log("✗  TranslationPackage غير متاح", theme.c["accent"])

    # ── Step 2 actions ────────────────────────────────────────────────────────

    def _run_step2(self):
        ue   = self._ue_ver_combo.currentText()
        maps = self._mappings_field.text().strip()
        mode = self._s2_mode_group.checkedId()   # 0=all, 1=single
        folder = self._legacy_folder or self._out1_field.text().strip()

        # capture UI values in main thread before entering worker
        single_file = ""
        if mode == 1:
            single_file = self._s2_single_field.text().strip()
            if not single_file:
                self._append_log("✗  اختر ملف .uasset", theme.c["accent"])
                return
        else:
            if not folder or not os.path.isdir(folder):
                self._append_log("✗  مجلد Legacy غير موجود — نفّذ الخطوة 1 أولاً",
                                  theme.c["accent"])
                return

        self._s2_card.set_status("🔄 جاري التنفيذ…", theme.c["yellow"])
        self._s2_info.setText("")
        extr_mode = self._extr_mode_combo.currentData()
        tr = self._new_translator()

        def _work():
            if mode == 1:
                path = tr.uasset_to_json(single_file, ue, maps)
                paths = [path] if path else []
            else:
                paths = tr.uasset_folder_to_json(folder, ue, maps)

            if not paths:
                return False

            self._json_paths = paths
            all_t: list[str] = []
            for jp in paths:
                all_t.extend(tr.extract_texts_from_json(jp, extr_mode))
            seen:  set = set()
            uniq = [x for x in all_t if x not in seen and not seen.add(x)]
            self._all_texts = uniq

            msg = f"{len(paths)} ملف JSON — {len(uniq)} نص فريد"
            QTimer.singleShot(0, lambda: self._s2_info.setText(msg))
            QTimer.singleShot(0, lambda: self._s3_strings_lbl.setText(
                f"النصوص المكتشفة: {len(uniq)}"
            ))
            return True

        self._run_worker(_work, self._s2_card)

    # ── Step 3 actions ────────────────────────────────────────────────────────

    def _get_s3_mode(self) -> str:
        btn = self._s3_mode_group.checkedButton()
        return btn.property("mode_val") if btn else "missing"

    def _load_json_into_step3(self):
        jp = self._load_json_field.text().strip()
        if not jp or not os.path.isfile(jp):
            self._append_log("✗  اختر ملف .uasset.json أولاً", theme.c["accent"])
            return
        tr    = self._new_translator()
        mode  = self._extr_mode_combo.currentData()
        texts = tr.extract_texts_from_json(jp, mode)
        if not texts:
            self._append_log(f"⚠  لا توجد نصوص في: {os.path.basename(jp)}",
                             theme.c["yellow"])
            return
        self._json_paths = [jp]
        self._all_texts  = texts
        msg = f"تم التحميل: {os.path.basename(jp)} ← {len(texts)} نص"
        self._append_log(msg, theme.c["teal"])
        self._s3_strings_lbl.setText(f"النصوص المكتشفة: {len(texts)}")

    def _run_step3(self):
        if not self._all_texts:
            self._append_log("✗  لا توجد نصوص — نفّذ الخطوة 2 أولاً", theme.c["accent"])
            return
        if not self._engine:
            self._append_log("✗  لا يوجد نموذج مُحمَّل", theme.c["accent"])
            return

        active_model = self._engine.get_active_model()
        if not active_model:
            self._append_log(
                "✗  لا يوجد نموذج نشط — اختر نموذجاً من صفحة النماذج",
                theme.c["accent"]
            )
            return

        mode       = self._get_s3_mode()
        gname      = self._game_name_field.text().strip() or self._game_id
        texts      = self._all_texts
        exmode     = self._extr_mode_combo.currentData()
        retoc_path = self._retoc_field.text().strip()
        uagui_path = self._uagui_field.text().strip()

        self._s3_gname  = gname
        self._s3_exmode = exmode

        if mode == "fresh":
            self._translations = {}

        # Pre-load cache hits
        pre_cached: dict = {}
        if self._cache and mode == "missing":
            pre_cached = self._cache.get_batch(gname, texts)
            self._translations.update(pre_cached)

        # Build translator (cache disabled — manual save after user confirms)
        tr = self._make_translator(retoc_path, uagui_path)
        tr.cache = None

        # For cache_only: re-extract from .orig if available so we get English keys
        if mode == "cache_only" and self._json_paths:
            orig_texts: list = []
            for jp in self._json_paths:
                orig = jp + ".orig"
                src  = orig if os.path.exists(orig) else jp
                orig_texts.extend(tr.extract_texts_from_json(src, exmode))
            if orig_texts:
                seen: set = set()
                texts = [x for x in orig_texts if x not in seen and not seen.add(x)]

        # Open the standalone non-blocking translation window
        from gui.qt.dialogs.translation_window import TranslationProgressWindow
        win = TranslationProgressWindow(
            translator=tr,
            engine=self._engine,
            cache=self._cache,
            texts=texts,
            game_name=gname,
            mode=mode,
            exmode=exmode,
            pre_cached=pre_cached,
            json_paths=list(self._json_paths),
            parent=None,
        )
        win.applied.connect(self._on_translation_applied)
        win.cancelled.connect(self._on_translation_cancelled)
        win.show()
        win.raise_()
        self._translation_window = win   # keep reference to prevent GC

        self._s3_card.set_status("🔄 نافذة الترجمة مفتوحة…", theme.c["yellow"])
        self._append_log(
            f"🌐  فُتحت نافذة الترجمة — {len(texts):,} نص | النموذج: {active_model}",
            theme.c["teal"]
        )

    def _on_translation_applied(self, new_trans: dict, all_trans: dict):
        """Called when user presses Apply in TranslationProgressWindow."""
        self._translations.update(all_trans)
        gname  = self._s3_gname
        exmode = self._s3_exmode
        tc     = theme.c

        # Save new translations to cache
        saved = 0
        if self._cache and new_trans:
            try:
                model = self._engine.get_active_model() or "unknown"
            except Exception:
                model = "unknown"
            for orig, trans in new_trans.items():
                self._cache.put(gname, orig, trans, model)
                saved += 1
            if saved:
                self._append_log(
                    f"✓  حُفظ {saved:,} ترجمة في الكاش ({gname})", tc["green"]
                )

        # Apply to JSON files
        if self._json_paths:
            tr = self._make_translator(
                self._retoc_field.text().strip(),
                self._uagui_field.text().strip(),
            )
            applied = 0
            for jp in self._json_paths:
                orig = jp + ".orig"
                src  = orig if os.path.exists(orig) else None
                if tr.apply_translations_to_json(jp, all_trans, exmode, source_path=src):
                    applied += 1
            self._append_log(
                f"✓  طُبِّقت على {applied}/{len(self._json_paths)} ملف JSON",
                tc["green"]
            )
        self._s3_card.set_status("✅ مكتمل + مُطبَّق", tc["green"])

    def _on_translation_cancelled(self):
        """Called when user presses Cancel in TranslationProgressWindow."""
        self._translations = {}
        self._s3_card.set_status("🗑 مُلغى", theme.c["muted"])
        self._append_log("🗑  تم إلغاء الترجمة — لم يُحفظ شيء", theme.c["yellow"])

    # ── Step 4 actions ────────────────────────────────────────────────────────

    def _run_step4(self):
        if not self._json_paths:
            self._append_log("✗  لا توجد ملفات JSON — نفّذ الخطوة 2 أولاً",
                             theme.c["accent"])
            return
        if not self._translations:
            self._append_log("✗  لا توجد ترجمات — نفّذ الخطوة 3 أولاً",
                             theme.c["accent"])
            return

        self._s4_card.set_status("🔄 جاري التنفيذ…", theme.c["yellow"])
        ue    = self._ue_ver_combo.currentText()
        maps  = self._mappings_field.text().strip()
        exmode = self._extr_mode_combo.currentData()
        trans = dict(self._translations)
        paths = list(self._json_paths)
        t4    = self._new_translator()

        # Reset step-4 chips
        _ms4 = f"color:{theme.c['muted']};font-size:10px;background:transparent;border:none;"
        self._s4_chip_json.setText("📄  JSON: …")
        self._s4_chip_json.setStyleSheet(_ms4)
        self._s4_chip_orig.setText("📋  .orig: …")
        self._s4_chip_orig.setStyleSheet(_ms4)
        self._s4_chip_uasset.setText("📦  .uasset: …")
        self._s4_chip_uasset.setStyleSheet(_ms4)

        def _work():
            for jp in paths:
                orig = jp + ".orig"
                src  = orig if os.path.exists(orig) else None
                t4.apply_translations_to_json(jp, trans, exmode, source_path=src)
            count = t4.json_folder_to_uasset(
                os.path.dirname(paths[0]) if paths else "", ue, maps
            )
            return count > 0

        def _s4_done(ok):
            tc = theme.c
            self._s4_chip_uasset.setText(f"📦  .uasset: {'✓  ' + str(len(paths)) + ' ملف' if ok else '✗'}")
            clr = tc["green"] if ok else tc["accent"]
            self._s4_chip_uasset.setStyleSheet(
                f"color:{clr};font-size:10px;background:transparent;border:none;"
            )

        self._run_worker(_work, self._s4_card, extra_done=_s4_done)

    # ── Step 5 actions ────────────────────────────────────────────────────────

    def _run_step5(self):
        legacy = self._legacy_folder or self._out1_field.text().strip()
        out5   = self._out5_field.text().strip()
        if not legacy or not os.path.isdir(legacy):
            self._append_log("✗  مجلد Legacy غير موجود", theme.c["accent"])
            return
        if not out5:
            self._append_log("✗  حدد مسار الإخراج الأساسي", theme.c["accent"])
            return

        self._s5_card.set_status("🔄 جاري التنفيذ…", theme.c["yellow"])
        zen  = self._zen_ver_combo.currentText()
        aes  = self._aes_field.text().strip()
        tgt  = self._tgt5_field.text().strip()
        t5   = self._new_translator()

        def _work():
            ok = t5.to_zen(legacy, out5, zen, aes)
            if ok and tgt and os.path.isdir(tgt):
                import shutil
                base   = out5[:-5] if out5.endswith(".utoc") else out5
                actual = base + "_P"
                for ext in (".pak", ".ucas", ".utoc"):
                    src = actual + ext
                    if os.path.isfile(src):
                        dst = os.path.join(tgt, os.path.basename(src))
                        try:
                            shutil.copy2(src, dst)
                            QTimer.singleShot(0, lambda d=dst: self._append_log(
                                f"✓  مُثبَّت: {os.path.basename(d)}", theme.c["green"]
                            ))
                        except Exception as e:
                            QTimer.singleShot(0, lambda err=str(e): self._append_log(
                                f"✗  خطأ: {err}", theme.c["accent"]
                            ))
                        try:
                            os.remove(src)
                        except Exception:
                            pass
            return ok

        self._run_worker(_work, self._s5_card)

    # ── Step 6 actions ────────────────────────────────────────────────────────

    def _run_step6(self):
        from games.translation_package import TranslationPackage

        gname  = self._game_name_field.text().strip() or self._game_id
        legacy = self._legacy_folder or self._out1_field.text().strip()
        out5   = self._out5_field.text().strip()
        tgt    = getattr(self, "_tgt5_field", None)
        tgt    = tgt.text().strip() if tgt else ""
        zen    = self._zen_ver_combo.currentText()
        ue     = self._ue_ver_combo.currentText()
        maps   = self._mappings_field.text().strip()
        exmode = self._extr_mode_combo.currentData()

        if not gname:
            self._append_log("✗  حدد اسم اللعبة أولاً", theme.c["accent"])
            return

        tc  = theme.c
        pkg = TranslationPackage()

        # Update info chips
        mod_dir = pkg.get_mod_dir(gname)
        self._s6_mod_lbl.setText(f"📦  {mod_dir}")
        self._s6_mod_lbl.setStyleSheet(
            f"color: {tc['teal']}; font-size: 10px; background: transparent; border: none;"
        )

        self._s6_card.set_status("🔄 جاري الحفظ…", tc["yellow"])
        saved_any = False

        # 1. Copy _P.pak / _P.ucas / _P.utoc → mods/<game>/ready/ + register in package.json
        # Step 5 deletes source after copying to tgt, so we look in tgt first
        pak_base = ""
        if out5:
            base_path = out5[:-5] if out5.endswith(".utoc") else out5
            pak_name  = os.path.basename(base_path.rstrip("/\\")) + "_P"
            if tgt and os.path.isdir(tgt):
                pak_base = os.path.join(tgt, pak_name)
            else:
                pak_base = os.path.join(os.path.dirname(base_path.rstrip("/\\")), pak_name)

        self._s6_pak_lbl.setText(f"🗜  pak: {os.path.basename(pak_base) if pak_base else '—'}")
        if pak_base:
            ok, lines = pkg.save_paks_to_ready(gname, pak_base, tgt)
            for ln in lines:
                color = tc["green"] if ln.startswith("✓") else (
                    tc["yellow"] if ln.startswith("  (") else tc["accent"]
                )
                self._append_log(ln, color)
            if ok:
                saved_any = True

        # 2. Copy entire Paks_legacy folder → mods/<game>/for_cache/
        self._s6_legacy_lbl.setText(
            f"📂  legacy: {os.path.basename(legacy) if legacy else '—'}"
        )
        if legacy and os.path.isdir(legacy):
            ok2, lines2 = pkg.copy_to_for_cache(gname, legacy)
            for ln in lines2:
                color = tc["green"] if "✓" in ln else tc["accent"]
                self._append_log(ln, color)
            if ok2:
                saved_any = True
        else:
            self._append_log(
                "⚠  مجلد Paks_legacy غير موجود — لن يُحفظ for_cache", tc["yellow"]
            )

        # 3. Save wizard settings to package.json
        pkg.save_wizard_config(gname, {
            "zen_version":    zen,
            "ue_version":     ue,
            "extraction_mode": exmode,
            "mappings":       maps,
            "output_base":    out5,
            "game_target_dir": tgt,
        })

        if saved_any:
            status_text = f"✅  محفوظ في: {mod_dir}"
            self._s6_status_lbl.setText(status_text)
            self._s6_status_lbl.setStyleSheet(
                f"color: {tc['green']}; font-size: 10px; background: transparent; border: none;"
            )
            self._append_log(f"✓  الحزمة محفوظة في: {mod_dir}", tc["green"])
            self._s6_card.set_status("✅ مكتمل", tc["green"])
            self._prog_bar.setValue(100)
        else:
            self._s6_card.set_status("⚠ لم يُحفظ شيء", tc["yellow"])

    # ── Worker runner ─────────────────────────────────────────────────────────

    def _run_worker(self, func, card: StepCard,
                    on_success=None, extra_done=None):
        c = theme.c

        def _done(ok):
            if ok:
                card.set_status("✅ مكتمل", c["green"])
                self._prog_bar.setValue(100)
            else:
                card.set_status("❌ فشل", c["accent"])
            if on_success and ok:
                QTimer.singleShot(0, on_success)
            if extra_done:
                QTimer.singleShot(0, lambda: extra_done(ok))
            self._worker = None

        worker = StepWorker(func)
        worker.log_line.connect(self._append_log)
        worker.finished.connect(_done)
        self._worker = worker
        worker.start()

    # ── Close guard ───────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.wait(1500)
        if self._translation_window:
            try:
                self._translation_window.close()
            except Exception:
                pass
        super().closeEvent(event)
