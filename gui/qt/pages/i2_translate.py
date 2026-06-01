"""
gui/qt/pages/i2_translate.py — صفحة ترجمة ملف I2Languages JSON

ميزات التحكم:
  - اختيار اللعبة (لتحديد قاعدة الكاش)
  - اختيار ملف JSON المصدر (المستخرج من UABEA)
  - تحليل الملف (إحصائيات: اللغات، الترمز، فتحة العربي)
  - خيارات تشغيل: استخدام الكاش (قراءة/كتابة)، skip_patterns، translations.txt، حد طول النص، tag_mode override
  - شريط تقدم تفصيلي + counters حية + ETA
  - تشغيل/إيقاف مؤقت/استئناف/إيقاف نهائي/تخطّى الترم الحالي
  - log حي للأحداث
  - حفظ الناتج: I2Languages معدّل كامل + Arabic-only JSON للمود
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QObject, QTimer
from PySide6.QtGui  import QCursor, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QLineEdit, QComboBox, QSpinBox, QCheckBox, QProgressBar,
    QPlainTextEdit, QFileDialog, QMessageBox, QGroupBox, QGridLayout,
    QSizePolicy, QToolButton,
)

from gui.qt.theme              import theme
from gui.qt.widgets.page_header import make_topbar

from engine.i2_translator import (
    I2BatchTranslator, I2Stats, I2Progress,
)
from engine.filtered_translator import get_global_tag_mode, VALID_MODES


# ── Worker thread: تشغيل الترجمة الدفعية في الخلفية ───────────────────────────

class _BatchWorker(QThread):
    progress_changed = Signal(object)   # I2Progress
    log_line         = Signal(str)
    term_done        = Signal(str, str, str, str)  # term, en, ar, source
    finished_ok      = Signal()

    def __init__(self, bt: I2BatchTranslator, parent=None):
        super().__init__(parent)
        self._bt = bt

    def run(self):
        try:
            self._bt.run(
                on_progress=lambda p: self.progress_changed.emit(p),
                on_log=lambda m: self.log_line.emit(m),
                on_term_done=lambda t, e, a, s: self.term_done.emit(t, e, a, s),
            )
        except Exception as e:
            self.log_line.emit(f"❌ استثناء worker: {e}")
        self.finished_ok.emit()


# ── الصفحة ──────────────────────────────────────────────────────────────────────

class I2TranslatePage(QWidget):
    """صفحة ترجمة ملفات I2Languages."""

    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine = None
        self._cache  = None
        self._game_manager = None
        self._bt: Optional[I2BatchTranslator] = None
        self._worker: Optional[_BatchWorker] = None
        self._ticker = QTimer(self)
        self._ticker.setInterval(500)
        self._ticker.timeout.connect(self._tick_eta)
        self._build()

    # ── Backend injection ───────────────────────────────────────────────────

    def set_backend(self, engine, cache, game_manager):
        self._engine = engine
        self._cache  = cache
        self._game_manager = game_manager
        self._refresh_game_list()
        self._refresh_tag_mode_default()

    # ── Build ───────────────────────────────────────────────────────────────

    def _build(self):
        c = theme.c
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # topbar
        bar, top_lay = make_topbar("🌍", "ترجمة I2Languages")
        self._mode_label = QLabel("الفلتر: —")
        self._mode_label.setStyleSheet(
            f"color: {c['muted']}; font-size: 11px; background: transparent; border: none;"
        )
        top_lay.addWidget(self._mode_label)
        lay.addWidget(bar)

        # main area (scrolling vertically would be nice for small windows, but we use full)
        main = QWidget()
        main.setObjectName("i2_main")
        ml = QVBoxLayout(main)
        ml.setContentsMargins(20, 14, 20, 14)
        ml.setSpacing(12)

        ml.addWidget(self._build_input_card())
        ml.addWidget(self._build_options_card())
        ml.addWidget(self._build_control_card())
        ml.addWidget(self._build_progress_card())
        ml.addWidget(self._build_log_card(), 1)
        ml.addWidget(self._build_output_card())

        lay.addWidget(main, 1)

    # ── Card 1: input (game + json path) ────────────────────────────────────

    def _build_input_card(self) -> QFrame:
        c = theme.c
        card = self._card("1️⃣  المدخلات")
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        grid.addWidget(self._lbl("اللعبة (للكاش):"), 0, 0)
        self.cmb_game = QComboBox()
        self.cmb_game.setStyleSheet(self._combo_qss())
        self.cmb_game.setMinimumHeight(30)
        grid.addWidget(self.cmb_game, 0, 1)

        grid.addWidget(self._lbl("ملف I2Languages JSON:"), 1, 0)
        path_row = QHBoxLayout()
        self.ed_path = QLineEdit()
        self.ed_path.setPlaceholderText("اختر ملف JSON المستخرج من UABEA…")
        self.ed_path.setStyleSheet(self._line_qss())
        self.ed_path.setMinimumHeight(30)
        path_row.addWidget(self.ed_path, 1)

        btn_browse = QPushButton("📂  تصفّح")
        btn_browse.setCursor(QCursor(Qt.PointingHandCursor))
        btn_browse.setStyleSheet(self._btn_qss(c["surface"]))
        btn_browse.clicked.connect(self._on_browse)
        path_row.addWidget(btn_browse)

        path_wrap = QWidget()
        path_wrap.setLayout(path_row)
        grid.addWidget(path_wrap, 1, 1)

        # Analyze + stats line
        analyze_row = QHBoxLayout()
        self.btn_analyze = QPushButton("🔍  تحليل الملف")
        self.btn_analyze.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_analyze.setStyleSheet(self._btn_qss(c["blue"], on_dark=True))
        self.btn_analyze.clicked.connect(self._on_analyze)
        analyze_row.addWidget(self.btn_analyze)

        self.lbl_stats = QLabel("لم يُحلَّل بعد")
        self.lbl_stats.setStyleSheet(
            f"color: {c['muted']}; font-size: 11px; background: transparent; border: none;"
        )
        self.lbl_stats.setWordWrap(True)
        analyze_row.addWidget(self.lbl_stats, 1)

        wrap2 = QWidget()
        wrap2.setLayout(analyze_row)
        grid.addWidget(wrap2, 2, 0, 1, 2)

        card.layout().addLayout(grid)
        return card

    # ── Card 2: options ─────────────────────────────────────────────────────

    def _build_options_card(self) -> QFrame:
        c = theme.c
        card = self._card("2️⃣  خيارات الترجمة")
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)

        # Row 0: cache options
        self.chk_cache_read  = QCheckBox("ابحث في الكاش أولاً (دمج هرمي)")
        self.chk_cache_read.setChecked(True)
        self.chk_cache_read.setStyleSheet(self._chk_qss())
        grid.addWidget(self.chk_cache_read, 0, 0, 1, 2)

        self.chk_cache_write = QCheckBox("احفظ كل ترجمة جديدة في الكاش")
        self.chk_cache_write.setChecked(True)
        self.chk_cache_write.setStyleSheet(self._chk_qss())
        grid.addWidget(self.chk_cache_write, 0, 2, 1, 2)

        # Row 1: skip patterns + static txt
        self.chk_skip = QCheckBox("تجاهل النصوص التي تطابق skip_patterns")
        self.chk_skip.setChecked(True)
        self.chk_skip.setStyleSheet(self._chk_qss())
        grid.addWidget(self.chk_skip, 1, 0, 1, 2)

        self.chk_static = QCheckBox("ابحث في translations.txt (المرجع اليدوي)")
        self.chk_static.setChecked(False)
        self.chk_static.setStyleSheet(self._chk_qss())
        grid.addWidget(self.chk_static, 1, 2, 1, 2)

        # Row 2: max length + tag mode + delay
        grid.addWidget(self._lbl("الحد الأقصى لطول النص (0 = بلا حد):"), 2, 0)
        self.spn_max_len = QSpinBox()
        self.spn_max_len.setRange(0, 100000)
        self.spn_max_len.setValue(0)
        self.spn_max_len.setSingleStep(100)
        self.spn_max_len.setStyleSheet(self._spin_qss())
        self.spn_max_len.setMinimumHeight(28)
        grid.addWidget(self.spn_max_len, 2, 1)

        grid.addWidget(self._lbl("tag_mode (override):"), 2, 2)
        self.cmb_tag_mode = QComboBox()
        self.cmb_tag_mode.setStyleSheet(self._combo_qss())
        self.cmb_tag_mode.setMinimumHeight(28)
        self.cmb_tag_mode.addItem("استخدم العام (من config.json)", "")
        for m in VALID_MODES:
            self.cmb_tag_mode.addItem(m, m)
        grid.addWidget(self.cmb_tag_mode, 2, 3)

        grid.addWidget(self._lbl("تأخير بين الترجمات (ms):"), 3, 0)
        self.spn_delay = QSpinBox()
        self.spn_delay.setRange(0, 5000)
        self.spn_delay.setValue(0)
        self.spn_delay.setSingleStep(50)
        self.spn_delay.setStyleSheet(self._spin_qss())
        self.spn_delay.setMinimumHeight(28)
        grid.addWidget(self.spn_delay, 3, 1)

        # Note about Arabic language slot
        self.lbl_arabic_slot = QLabel("ℹ سيُضاف فتحة لغة \"Arabic\" تلقائياً إن لم تكن موجودة")
        self.lbl_arabic_slot.setStyleSheet(
            f"color: {c['muted']}; font-size: 11px; background: transparent; border: none;"
        )
        grid.addWidget(self.lbl_arabic_slot, 3, 2, 1, 2)

        # Row 4: model suffix — لتمييز ترجمات I2 عن البروكسي
        self.chk_suffix = QCheckBox("ميّز ترجمات هذه الدفعة باللاحقة:")
        self.chk_suffix.setChecked(True)
        self.chk_suffix.setStyleSheet(self._chk_qss())
        self.chk_suffix.setToolTip(
            "تُضاف اللاحقة لاسم المودل عند الحفظ في الكاش.\n"
            "مثال: 'qwen2.5:14b' → 'qwen2.5:14b:i2'\n"
            "النتيجة: تظهر منفصلة في صفحة الكاش، ويمكن تصديرها وحدها\n"
            "أو دمجها هرمياً مع ترجمات البروكسي."
        )
        grid.addWidget(self.chk_suffix, 4, 0, 1, 2)

        self.ed_suffix = QLineEdit(":i2")
        self.ed_suffix.setMaxLength(32)
        self.ed_suffix.setStyleSheet(self._line_qss())
        self.ed_suffix.setMinimumHeight(28)
        self.ed_suffix.setPlaceholderText(":i2")
        self.ed_suffix.setToolTip(
            "ابدأ بـ ':' لتمييز اللاحقة عن اسم المودل\n"
            "أمثلة: ':i2'، ':i2_batch'، ':ff_i2'"
        )
        grid.addWidget(self.ed_suffix, 4, 2)

        self.chk_suffix.toggled.connect(self.ed_suffix.setEnabled)

        card.layout().addLayout(grid)
        return card

    # ── Card 3: control buttons ─────────────────────────────────────────────

    def _build_control_card(self) -> QFrame:
        c = theme.c
        card = self._card("3️⃣  التحكم")
        row = QHBoxLayout()
        row.setSpacing(8)

        self.btn_start = QPushButton("▶  ابدأ الترجمة")
        self.btn_start.setStyleSheet(self._btn_qss(c["green"], on_dark=True))
        self.btn_start.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_start.setMinimumHeight(36)
        self.btn_start.clicked.connect(self._on_start)
        row.addWidget(self.btn_start)

        self.btn_pause = QPushButton("⏸  إيقاف مؤقت")
        self.btn_pause.setStyleSheet(self._btn_qss(c["yellow"], on_dark=True))
        self.btn_pause.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_pause.setMinimumHeight(36)
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._on_pause_resume)
        row.addWidget(self.btn_pause)

        self.btn_skip = QPushButton("⏭  تخطّى الحالي")
        self.btn_skip.setStyleSheet(self._btn_qss(c["surface"]))
        self.btn_skip.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_skip.setMinimumHeight(36)
        self.btn_skip.setEnabled(False)
        self.btn_skip.clicked.connect(self._on_skip)
        row.addWidget(self.btn_skip)

        self.btn_stop = QPushButton("⏹  إيقاف")
        self.btn_stop.setStyleSheet(self._btn_qss(c["accent"], on_dark=True))
        self.btn_stop.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_stop.setMinimumHeight(36)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)
        row.addWidget(self.btn_stop)

        row.addStretch(1)

        # Resume from JSON
        self.btn_load_partial = QPushButton("📥  استئناف من ملف عربي")
        self.btn_load_partial.setStyleSheet(self._btn_qss(c["surface"]))
        self.btn_load_partial.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_load_partial.setMinimumHeight(36)
        self.btn_load_partial.setToolTip(
            "حمّل ملف arabic_only.json سابق ليُدمج في الترجمات الحالية\n"
            "(يمنع إعادة ترجمة ما تم سابقاً)"
        )
        self.btn_load_partial.clicked.connect(self._on_load_partial)
        row.addWidget(self.btn_load_partial)

        card.layout().addLayout(row)
        return card

    # ── Card 4: progress + counters ─────────────────────────────────────────

    def _build_progress_card(self) -> QFrame:
        c = theme.c
        card = self._card("4️⃣  التقدم")
        v = QVBoxLayout()
        v.setSpacing(8)

        # Progress bar
        self.pb = QProgressBar()
        self.pb.setRange(0, 100)
        self.pb.setValue(0)
        self.pb.setMinimumHeight(22)
        self.pb.setFormat("%p%  (%v / %m)")
        self.pb.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {c['border']}; border-radius: 6px;
                background: {c['surface']}; color: {c['primary']};
                text-align: center; font-size: 11px;
            }}
            QProgressBar::chunk {{
                background: {c['blue']}; border-radius: 4px;
            }}
        """)
        v.addWidget(self.pb)

        # Current term/text
        cur_row = QHBoxLayout()
        self.lbl_current = QLabel("جاهز")
        self.lbl_current.setStyleSheet(
            f"color: {c['muted']}; font-size: 11px; font-family: Consolas, monospace;"
            " background: transparent; border: none;"
        )
        self.lbl_current.setWordWrap(False)
        cur_row.addWidget(self.lbl_current, 1)
        v.addLayout(cur_row)

        # Counters (3 columns)
        counter_row = QHBoxLayout()
        counter_row.setSpacing(8)

        def _counter(label: str, color: str):
            f = QFrame()
            f.setStyleSheet(f"""
                QFrame {{
                    background: rgba(0,0,0,0.18);
                    border: 1px solid {c['border']}; border-radius: 6px;
                }}
            """)
            fl = QVBoxLayout(f)
            fl.setContentsMargins(10, 6, 10, 6)
            fl.setSpacing(2)
            l_top = QLabel(label)
            l_top.setStyleSheet(
                f"color: {c['muted']}; font-size: 10px; background: transparent; border: none;"
            )
            l_top.setAlignment(Qt.AlignCenter)
            l_val = QLabel("0")
            l_val.setStyleSheet(
                f"color: {color}; font-size: 18px; font-weight: bold;"
                " background: transparent; border: none;"
            )
            l_val.setAlignment(Qt.AlignCenter)
            fl.addWidget(l_top)
            fl.addWidget(l_val)
            return f, l_val

        f1, self.lbl_cache_hits = _counter("من الكاش", c["teal"])
        counter_row.addWidget(f1, 1)
        f2, self.lbl_new        = _counter("ترجمات جديدة (AI)", c["green"])
        counter_row.addWidget(f2, 1)
        f3, self.lbl_skipped    = _counter("متخطّاة", c["yellow"])
        counter_row.addWidget(f3, 1)
        f4, self.lbl_failed     = _counter("فشلت", c["accent"])
        counter_row.addWidget(f4, 1)
        f5, self.lbl_eta        = _counter("الوقت المتبقي", c["blue"])
        counter_row.addWidget(f5, 1)
        v.addLayout(counter_row)

        card.layout().addLayout(v)
        return card

    # ── Card 5: log ─────────────────────────────────────────────────────────

    def _build_log_card(self) -> QFrame:
        c = theme.c
        card = self._card("5️⃣  السجل")
        v = QVBoxLayout()
        v.setSpacing(6)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {c['surface']}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 6px;
                padding: 6px; font-family: Consolas, monospace; font-size: 11px;
            }}
        """)
        self.log.setMinimumHeight(160)
        v.addWidget(self.log, 1)

        row = QHBoxLayout()
        clear_btn = QPushButton("🗑  مسح")
        clear_btn.setStyleSheet(self._btn_qss(c["surface"]))
        clear_btn.setCursor(QCursor(Qt.PointingHandCursor))
        clear_btn.clicked.connect(lambda: self.log.clear())
        row.addStretch(1)
        row.addWidget(clear_btn)
        v.addLayout(row)

        card.layout().addLayout(v)
        return card

    # ── Card 6: output ──────────────────────────────────────────────────────

    def _build_output_card(self) -> QFrame:
        c = theme.c
        card = self._card("6️⃣  المخرجات")
        row = QHBoxLayout()
        row.setSpacing(8)

        self.btn_save_modified = QPushButton("💾  حفظ I2Languages المعدّل")
        self.btn_save_modified.setStyleSheet(self._btn_qss(c["green"], on_dark=True))
        self.btn_save_modified.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_save_modified.setEnabled(False)
        self.btn_save_modified.setMinimumHeight(34)
        self.btn_save_modified.setToolTip(
            "يحقن الترجمات في فتحة \"Arabic\" ويحفظ الملف الكامل\n"
            "للاستخدام مع UABEA Import Dump"
        )
        self.btn_save_modified.clicked.connect(self._on_save_modified)
        row.addWidget(self.btn_save_modified)

        self.btn_save_arabic = QPushButton("💾  حفظ arabic_only.json (للمود)")
        self.btn_save_arabic.setStyleSheet(self._btn_qss(c["blue"], on_dark=True))
        self.btn_save_arabic.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_save_arabic.setEnabled(False)
        self.btn_save_arabic.setMinimumHeight(34)
        self.btn_save_arabic.setToolTip(
            "يحفظ تلقائياً داخل:\n"
            "<game>/BepInEx/config/I2LanguageInjector/arabic_only.json\n\n"
            "ينشئ المجلد لو غير موجود، ويستبدل الملف لو موجود (بعد تأكيد).\n"
            "لو مسار اللعبة غير محدّد في الإعدادات، يُفتح حوار حفظ يدوي."
        )
        self.btn_save_arabic.clicked.connect(self._on_save_arabic)
        row.addWidget(self.btn_save_arabic)

        row.addStretch(1)
        card.layout().addLayout(row)

        # خيار pre-shape (Arabic presentation forms + BiDi reversal قبل الحفظ)
        shape_row = QHBoxLayout()
        self.chk_pre_shape = QCheckBox(
            "طبّق التشكيل والعكس البصري مسبقاً (للألعاب بدون ArabicFontFixer فقط)"
        )
        self.chk_pre_shape.setChecked(False)  # افتراضي: ArabicFontFixer يتولّى
        self.chk_pre_shape.setStyleSheet(self._chk_qss())
        self.chk_pre_shape.setToolTip(
            "⚠ الموصى به: اتركه غير مفعّل واستخدم ArabicFontFixer.dll\n"
            "    (تشكيل runtime + عكس صحيح + دعم الخطوط)\n\n"
            "✓ مفعّل: يحفظ النص بصيغة presentation forms معكوسة\n"
            "    استخدمه فقط لو ArabicFontFixer غير متاح/معطّل\n"
            "    (الخط الأصلي للعبة قد لا يدعم presentation forms)\n\n"
            "تحذير: تفعيله مع ArabicFontFixer = تشكيل مزدوج = نص مكسور"
        )
        shape_row.addWidget(self.chk_pre_shape)
        shape_row.addStretch(1)
        card.layout().addLayout(shape_row)

        return card

    # ── small helpers ───────────────────────────────────────────────────────

    def _card(self, title: str) -> QFrame:
        c = theme.c
        f = QFrame()
        f.setStyleSheet(f"""
            QFrame {{
                background: {c['card']};
                border: 1px solid {c['border']};
                border-radius: 8px;
            }}
        """)
        v = QVBoxLayout(f)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {c['primary']}; font-size: 13px; font-weight: bold;"
            " background: transparent; border: none;"
        )
        v.addWidget(title_lbl)
        return f

    def _lbl(self, t: str) -> QLabel:
        c = theme.c
        l = QLabel(t)
        l.setStyleSheet(
            f"color: {c['secondary']}; font-size: 11px;"
            " background: transparent; border: none;"
        )
        return l

    def _line_qss(self) -> str:
        c = theme.c
        return f"""
            QLineEdit {{
                background: {c['surface']}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 6px;
                padding: 2px 8px;
            }}
            QLineEdit:focus {{ border-color: {c['accent']}; }}
        """

    def _combo_qss(self) -> str:
        c = theme.c
        return f"""
            QComboBox {{
                background: {c['surface']}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 6px;
                padding: 2px 8px;
            }}
            QComboBox:focus {{ border-color: {c['accent']}; }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{
                background: {c['surface']}; color: {c['primary']};
                selection-background-color: {c['accent']};
            }}
        """

    def _spin_qss(self) -> str:
        c = theme.c
        return f"""
            QSpinBox {{
                background: {c['surface']}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 6px;
                padding: 2px 8px;
            }}
            QSpinBox:focus {{ border-color: {c['accent']}; }}
        """

    def _chk_qss(self) -> str:
        c = theme.c
        return f"color: {c['secondary']}; font-size: 12px; background: transparent;"

    def _btn_qss(self, bg: str, on_dark: bool = False) -> str:
        c = theme.c
        fg = "white" if on_dark else c["primary"]
        return f"""
            QPushButton {{
                background: {bg}; color: {fg};
                border: 1px solid {c['border']}; border-radius: 6px;
                padding: 6px 14px; font-size: 12px;
            }}
            QPushButton:hover {{ background: {c['hover']}; }}
            QPushButton:disabled {{
                background: {c['surface']}; color: {c['muted']};
                border-color: {c['border']};
            }}
        """

    # ── Helpers — backend ───────────────────────────────────────────────────

    def _refresh_game_list(self):
        self.cmb_game.clear()
        if not self._game_manager:
            return
        try:
            for g in self._game_manager.get_game_list():
                name = g.get("name", "") or g.get("id", "")
                gid  = g.get("id", name)
                if not name:
                    continue
                self.cmb_game.addItem(name, gid)
            idx = self.cmb_game.findText("Farthest Frontier", Qt.MatchFixedString)
            if idx >= 0:
                self.cmb_game.setCurrentIndex(idx)
        except Exception as e:
            self.log_line(f"⚠ فشل تحميل قائمة الألعاب: {e}")

    def _refresh_tag_mode_default(self):
        try:
            cur = get_global_tag_mode()
        except Exception:
            cur = "?"
        self._mode_label.setText(f"الفلتر العام: {cur}  (من Models)")

    # ── Helpers — مسارات اللعبة ─────────────────────────────────────────────

    def _current_game_path(self) -> str:
        """يُرجع مسار اللعبة المختارة (game_path/path) من config، أو ''."""
        if not self._game_manager:
            return ""
        gid = self.cmb_game.currentData()
        if not gid:
            return ""
        g = self._game_manager.get_game(gid) or {}
        return g.get("game_path") or g.get("path") or ""

    def _i2_inject_config_dir(self) -> str:
        """مسار `BepInEx/config/I2LanguageInjector/` (قد لا يكون موجوداً)."""
        gp = self._current_game_path()
        if not gp:
            return ""
        return os.path.join(gp, "BepInEx", "config", "I2LanguageInjector")

    # ── Slots — input ───────────────────────────────────────────────────────

    def _on_browse(self):
        # ابدأ من مسار اللعبة لو متاح
        start_dir = ""
        cur = self.ed_path.text().strip()
        if cur and os.path.isfile(cur):
            start_dir = os.path.dirname(cur)
        else:
            gp = self._current_game_path()
            if gp and os.path.isdir(gp):
                # المسار الشائع لـ I2Languages داخل اللعبة
                # مثال: <game>/<Game>_Data/I2Languages-resources.assets-*.json
                data_dir = ""
                try:
                    for d in os.listdir(gp):
                        full = os.path.join(gp, d)
                        if os.path.isdir(full) and d.endswith("_Data"):
                            data_dir = full
                            break
                except Exception:
                    pass
                start_dir = data_dir or gp

        path, _ = QFileDialog.getOpenFileName(
            self, "اختر ملف I2Languages JSON",
            start_dir, "JSON Files (*.json)"
        )
        if path:
            self.ed_path.setText(path)
            self.lbl_stats.setText("اضغط تحليل لقراءة الملف")

    def _on_analyze(self):
        path = self.ed_path.text().strip()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "خطأ", "اختر ملف JSON صالح أولاً")
            return
        game = self.cmb_game.currentText() or "Unknown"
        try:
            bt = I2BatchTranslator(
                json_path=path,
                game_name=game,
                engine=self._engine,
                cache=self._cache,
            )
            stats = bt.analyze()
            self._bt = bt
        except Exception as e:
            QMessageBox.critical(self, "فشل التحليل", str(e))
            self.lbl_stats.setText(f"✗ خطأ: {e}")
            return

        arabic_state = (
            f"✅ موجودة (فهرس {stats.arabic_index})" if stats.has_arabic_slot
            else "⚠ غير موجودة — ستُضاف تلقائياً"
        )
        langs_preview = ", ".join(
            f"{l['Code']}" for l in stats.languages[:6]
        )
        if len(stats.languages) > 6:
            langs_preview += f" … (+{len(stats.languages) - 6})"

        self.lbl_stats.setText(
            f"  📊  ترمز: {stats.total_terms}  |  للترجمة: {stats.translatable_terms}"
            f"  |  محجوبة: {stats.skip_pattern_hits}\n"
            f"  🌐  لغات: {stats.language_count} ({langs_preview})  |  العربية: {arabic_state}"
        )
        # تحضير الـ progress bar
        total = stats.translatable_terms or stats.total_terms
        self.pb.setRange(0, max(1, total))
        self.pb.setValue(0)

        # تفعيل الحفظ ولو ما اشتغلت ترجمة (لو حمّل من ملف عربي)
        self._update_save_buttons()

    # ── Slots — control ─────────────────────────────────────────────────────

    def _on_start(self):
        if not self._bt:
            QMessageBox.warning(self, "خطأ", "حلّل الملف أولاً")
            return
        if not self._engine:
            QMessageBox.warning(self, "خطأ", "المحرك غير جاهز")
            return
        if not self._cache:
            QMessageBox.warning(self, "خطأ", "الكاش غير جاهز")
            return

        # طبّق الخيارات الحالية على الـ batch translator
        self._bt.use_cache_read = self.chk_cache_read.isChecked()
        self._bt.use_cache_write = self.chk_cache_write.isChecked()
        self._bt.use_skip_patterns = self.chk_skip.isChecked()
        self._bt.use_static_txt = self.chk_static.isChecked()
        self._bt.max_text_len = self.spn_max_len.value()
        self._bt.tag_mode_override = self.cmb_tag_mode.currentData() or None
        self._bt.delay_ms = self.spn_delay.value()
        self._bt.model_suffix = (
            self.ed_suffix.text().strip() if self.chk_suffix.isChecked() else ""
        )

        # UI state
        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("⏸  إيقاف مؤقت")
        self.btn_skip.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self.btn_save_modified.setEnabled(False)
        self.btn_save_arabic.setEnabled(False)
        self.btn_analyze.setEnabled(False)
        self._set_options_enabled(False)

        # start worker
        self._worker = _BatchWorker(self._bt)
        self._worker.progress_changed.connect(self._on_progress)
        self._worker.log_line.connect(self.log_line)
        self._worker.finished_ok.connect(self._on_worker_done)
        self._worker.start()
        self._ticker.start()

        self.log_line("▶ بدأ التشغيل")
        self.status_message.emit("ترجمة I2Languages جارية…")

    def _on_pause_resume(self):
        if not self._bt:
            return
        if self._bt.is_paused():
            self._bt.resume()
            self.btn_pause.setText("⏸  إيقاف مؤقت")
            self.log_line("▶ استئناف")
        else:
            self._bt.pause()
            self.btn_pause.setText("▶  استئناف")
            self.log_line("⏸ إيقاف مؤقت")

    def _on_skip(self):
        if self._bt:
            self._bt.skip_current()
            self.log_line("⏭ تخطّى الحالي")

    def _on_stop(self):
        if not self._bt:
            return
        ret = QMessageBox.question(
            self, "تأكيد الإيقاف",
            "هل أنت متأكد؟ الترجمات المنجَزة ستبقى ويمكن حفظها.\n"
            "(الترجمات الناقصة ستترك الإنجليزية في الحقن).",
            QMessageBox.Yes | QMessageBox.No
        )
        if ret == QMessageBox.Yes:
            self._bt.stop()
            self.log_line("⏹ طلب الإيقاف…")

    def _on_load_partial(self):
        if not self._bt:
            # نسمح بفتح ملف حتى بدون تحليل — لكن نحتاج التحليل أولاً ليكون _bt جاهز
            QMessageBox.information(self, "ملاحظة", "حلّل الملف أولاً ثم استأنف")
            return

        # ابدأ من مجلد المود لو موجود، وإلا من مسار اللعبة
        inject_dir = self._i2_inject_config_dir()
        if inject_dir and os.path.isdir(inject_dir):
            start_dir = inject_dir
        else:
            start_dir = self._current_game_path() or ""

        path, _ = QFileDialog.getOpenFileName(
            self, "اختر ملف arabic_only.json سابق",
            start_dir, "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            added = self._bt.load_arabic_only(path)
            self.log_line(f"📥 حُمِّل {added} ترجمة سابقة من: {os.path.basename(path)}")
            self._update_save_buttons()
        except Exception as e:
            QMessageBox.critical(self, "فشل التحميل", str(e))

    # ── Slots — worker callbacks ────────────────────────────────────────────

    def _on_progress(self, p: I2Progress):
        self.pb.setMaximum(max(1, p.total))
        self.pb.setValue(p.done)
        self.lbl_cache_hits.setText(str(p.cache_hits))
        self.lbl_new.setText(str(p.new_translations))
        self.lbl_skipped.setText(str(p.skipped))
        self.lbl_failed.setText(str(p.failed))

        if p.current_term:
            cur = p.current_text or ""
            if len(cur) > 80:
                cur = cur[:77] + "…"
            self.lbl_current.setText(f"⏳ {p.current_term} → {cur}")

    def _tick_eta(self):
        if not self._bt:
            return
        p = self._bt.progress
        eta = p.eta_sec()
        if eta <= 0 or eta >= 36000:
            self.lbl_eta.setText("—")
        else:
            mm = int(eta // 60)
            ss = int(eta % 60)
            if mm >= 60:
                hh = mm // 60
                mm = mm % 60
                self.lbl_eta.setText(f"{hh}س {mm}د")
            else:
                self.lbl_eta.setText(f"{mm}د {ss}ث")

    def _on_worker_done(self):
        self._ticker.stop()
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸  إيقاف مؤقت")
        self.btn_skip.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_analyze.setEnabled(True)
        self._set_options_enabled(True)
        self._update_save_buttons()
        self.log_line("✅ انتهى التشغيل")
        self.status_message.emit("اكتملت الترجمة الدفعية")

    # ── Slots — outputs ─────────────────────────────────────────────────────

    def _on_save_modified(self):
        if not self._bt:
            return
        src = self.ed_path.text().strip()
        # افتراضي: بجوار الأصل بإضافة .arabic_injected.json
        if src:
            default = src.rsplit(".", 1)[0] + ".arabic_injected.json"
        else:
            default = ""
        path, _ = QFileDialog.getSaveFileName(
            self, "حفظ I2Languages المعدّل",
            default, "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            idx = self._bt.inject_arabic()
            self._bt.save_modified(path)
            QMessageBox.information(
                self, "تم الحفظ",
                f"✅ حُفظ في:\n{path}\n\nفهرس اللغة العربية: {idx}\n"
                f"ترجمات مدمَجة: {len(self._bt.translations)}\n\n"
                "الخطوة التالية: استورده عبر UABEA → Import Dump → اضغط Save → "
                "انسخ resources.assets الناتج فوق الأصلي (مع نسخة احتياطية).",
            )
            self.log_line(f"💾 حُفظ I2 معدّل: {path}")
        except Exception as e:
            QMessageBox.critical(self, "فشل الحفظ", str(e))

    def _on_save_arabic(self):
        if not self._bt:
            return
        pre_shape = self.chk_pre_shape.isChecked()
        shape_note = "✨ مع تشكيل وعكس مسبق" if pre_shape else "📝 منطقي (بلا تشكيل)"

        # المسار التلقائي = داخل مجلد المود في BepInEx
        inject_dir = self._i2_inject_config_dir()
        if inject_dir:
            try:
                os.makedirs(inject_dir, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(
                    self, "فشل إنشاء المجلد",
                    f"تعذّر إنشاء:\n{inject_dir}\n\n{e}\n\nسيُفتح حوار حفظ يدوي."
                )
                inject_dir = ""

        if inject_dir:
            target = os.path.join(inject_dir, "arabic_only.json")
            existed = os.path.exists(target)
            if existed:
                ret = QMessageBox.question(
                    self, "استبدال موجود",
                    f"الملف موجود مسبقاً في مجلد المود:\n{target}\n\n"
                    "هل تريد استبداله؟",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
                )
                if ret != QMessageBox.Yes:
                    return
            try:
                n = self._bt.export_arabic_only(target, pre_shape=pre_shape)
                action = "استُبدل" if existed else "أُنشئ"
                QMessageBox.information(
                    self, "تم الحفظ",
                    f"✅ {action} arabic_only.json ({n} ترم) {shape_note}\n\n"
                    f"المسار:\n{target}\n\n"
                    "اللعبة الآن جاهزة — شغّلها مباشرة."
                )
                self.log_line(f"💾 {action} {target} ({n} ترم) {shape_note}")
            except Exception as e:
                QMessageBox.critical(self, "فشل الحفظ", str(e))
            return

        # Fallback: لا game_path → افتح حوار يدوي
        default = ""
        try:
            game = self.cmb_game.currentText() or "i2"
            default = os.path.join(os.getcwd(), "data", f"{game}_arabic_only.json")
        except Exception:
            pass
        path, _ = QFileDialog.getSaveFileName(
            self, "حفظ arabic_only.json",
            default, "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            n = self._bt.export_arabic_only(path, pre_shape=pre_shape)
            QMessageBox.information(
                self, "تم الحفظ",
                f"✅ حُفظ ({n} ترم) {shape_note}\n{path}\n\n"
                "للاستخدام: ضع الملف داخل\n"
                "<game>/BepInEx/config/I2LanguageInjector/arabic_only.json"
            )
            self.log_line(f"💾 حُفظ arabic_only.json ({n} ترم) {shape_note}: {path}")
        except Exception as e:
            QMessageBox.critical(self, "فشل الحفظ", str(e))

    # ── helpers ─────────────────────────────────────────────────────────────

    def _set_options_enabled(self, on: bool):
        for w in (
            self.cmb_game, self.ed_path,
            self.chk_cache_read, self.chk_cache_write,
            self.chk_skip, self.chk_static,
            self.spn_max_len, self.cmb_tag_mode, self.spn_delay,
            self.chk_suffix, self.ed_suffix, self.chk_pre_shape,
            self.btn_load_partial,
        ):
            w.setEnabled(on)
        if on:
            # احترم حالة الـ checkbox لحقل الـ suffix
            self.ed_suffix.setEnabled(self.chk_suffix.isChecked())

    def _update_save_buttons(self):
        has_data = self._bt is not None and len(self._bt.translations) > 0
        self.btn_save_modified.setEnabled(has_data)
        self.btn_save_arabic.setEnabled(has_data)

    def log_line(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{ts}] {msg}")

    # ── Public — proper cancel on close ─────────────────────────────────────

    def cancel_worker(self):
        if self._bt and self._worker and self._worker.isRunning():
            self._bt.stop()
            self._worker.wait(2000)
