"""
gui/qt/dialogs/tag_mode_confirm_dialog.py — تأكيد وضع التاقات قبل تشغيل الخادم.

يظهر عند الضغط على "تشغيل الخادم" ليُتيح للمستخدم:
  - رؤية الوضع الحالي
  - تغييره قبل البدء بنقرة واحدة
  - فتح إعدادات قائمة التاقات (الـ ⚙) من نفس النافذة
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QButtonGroup, QFrame, QComboBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor

from gui.qt.theme import theme


_MODES = [
    ("inline",      "🏷  Inline",      "تاقات تبقى مع النص للمودل (الأسرع، السياق كامل)"),
    ("strip",       "🔒  Strip",       "كل التاقات تُستبدل بمحارف PUA — للنماذج الصغيرة"),
    ("tiered",      "🎯  Tiered",      "بسيطة inline، معقدة → [tN]/[sN]"),
    ("bulletproof", "🛡  Bulletproof", "⟦N⟧ + تحقق صارم + cascade fallback (موصى به)"),
]


class TagModeConfirmDialog(QDialog):
    """حوار صغير لاختيار وضع التاقات قبل تشغيل خادم الترجمة."""

    def __init__(self, current_mode: str = "bulletproof", game_name: str = "",
                 cache=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تأكيد وضع التاقات")
        self.setMinimumWidth(560)
        self._selected_mode = current_mode
        self._selected_cache_filter = ""   # كل النماذج (افتراضي)
        self._game_name = game_name
        self._cache = cache
        self._open_tag_config_requested = False
        self._build(current_mode)

    @property
    def selected_cache_filter(self) -> str:
        """يُرجع: '' (كل النماذج)، 'none' (بدون كاش)، أو اسم نموذج محدد."""
        return self._selected_cache_filter

    @property
    def selected_mode(self) -> str:
        return self._selected_mode

    @property
    def open_tag_config_requested(self) -> bool:
        """True لو ضغط المستخدم زر فتح إعدادات قائمة التاقات."""
        return self._open_tag_config_requested

    def _build(self, current_mode: str):
        c = theme.c
        self.setStyleSheet(f"""
            QDialog {{ background: {c['bg']}; }}
            QLabel  {{ color: {c['primary']}; background: transparent; }}
            QRadioButton {{
                color: {c['primary']}; background: transparent;
                font-size: 12px; padding: 6px 4px;
            }}
            QRadioButton:checked {{ color: {c['accent']}; font-weight: bold; }}
            QPushButton {{
                background: {c['surface']}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 6px 14px; font-size: 12px;
            }}
            QPushButton:hover {{ background: {c['hover']}; }}
            QPushButton#primary {{
                background: {c['primary']}; color: white; border: none;
            }}
            QPushButton:disabled {{ color: {c['muted']}; }}
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        # العنوان
        title = QLabel("🏷  أكّد وضع التاقات قبل تشغيل الخادم")
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {c['accent']};")
        root.addWidget(title)

        if self._game_name:
            sub = QLabel(f"اللعبة: <b>{self._game_name}</b>")
            sub.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
            sub.setTextFormat(Qt.RichText)
            root.addWidget(sub)

        hint = QLabel(
            "اختر كيف يتعامل الـ proxy مع التاقات في نصوص اللعبة.\n"
            "يمكن تغييره لاحقاً من شريط الإحصاءات فوق الـ log."
        )
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # ── خيارات الـ radio ────────────────────────────────────────────
        self._group = QButtonGroup(self)
        modes_frame = QFrame()
        modes_frame.setStyleSheet(
            f"QFrame {{ background: {c['surface']}; border-radius: 6px; padding: 6px; }}"
        )
        mlay = QVBoxLayout(modes_frame)
        mlay.setSpacing(4)
        mlay.setContentsMargins(10, 8, 10, 8)

        for key, label, desc in _MODES:
            row = QVBoxLayout()
            row.setContentsMargins(0, 0, 0, 4)
            row.setSpacing(0)
            rb = QRadioButton(label)
            rb.setProperty("mode_key", key)
            if key == current_mode:
                rb.setChecked(True)
            self._group.addButton(rb)
            desc_lbl = QLabel(f"   ↳  {desc}")
            desc_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px; padding-right: 28px;")
            desc_lbl.setWordWrap(True)
            row.addWidget(rb)
            row.addWidget(desc_lbl)
            mlay.addLayout(row)

        root.addWidget(modes_frame)

        # ── قسم اختيار مصدر الكاش ───────────────────────────────────────
        root.addWidget(self._build_cache_filter_section())

        # ── شريط الأزرار السفلي ─────────────────────────────────────────
        bottom = QHBoxLayout()

        cfg_btn = QPushButton("⚙  إعدادات قائمة التاقات")
        cfg_btn.setToolTip("افتح حوار تحرير التاقات المحمية (paired/self-closing)")
        cfg_btn.setCursor(QCursor(Qt.PointingHandCursor))
        cfg_btn.clicked.connect(self._on_open_tag_config)
        bottom.addWidget(cfg_btn)
        bottom.addStretch()

        cancel_btn = QPushButton("إلغاء")
        cancel_btn.setCursor(QCursor(Qt.PointingHandCursor))
        cancel_btn.clicked.connect(self.reject)

        start_btn = QPushButton("▶  تشغيل الخادم")
        start_btn.setObjectName("primary")
        start_btn.setCursor(QCursor(Qt.PointingHandCursor))
        start_btn.setDefault(True)
        start_btn.clicked.connect(self._on_confirm)

        bottom.addWidget(cancel_btn)
        bottom.addWidget(start_btn)
        root.addLayout(bottom)

    def _build_cache_filter_section(self) -> QFrame:
        """قسم اختيار مصدر الكاش — لتجربة موديل واحد أو ترجمة من الصفر."""
        c = theme.c
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {c['surface']}; border-radius: 6px; padding: 6px; }}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)

        title = QLabel("💾  مصدر الكاش")
        title.setStyleSheet(f"font-weight: bold; font-size: 12px; color: {c.get('teal', '#00d2ff')};")
        lay.addWidget(title)

        hint = QLabel(
            "اختر أي ترجمات سابقة تُستخدَم. مفيد لتجربة الموديلات بعد التحديثات."
        )
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self._cache_combo = QComboBox()
        self._cache_combo.setStyleSheet(f"""
            QComboBox {{
                background: {c['card']}; color: {c['secondary']};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 4px 8px; font-size: 11px; min-width: 280px;
            }}
            QComboBox QAbstractItemView {{
                background: {c['card']}; color: {c['secondary']};
                selection-background-color: {c.get('accent', '#e94560')};
            }}
        """)

        # ابني القائمة من الكاش الفعلي
        models_with_counts: list[tuple[str, int]] = []
        total_all = 0
        if self._cache and self._game_name:
            try:
                models = self._cache.get_models_for_game(self._game_name)
                for m in models:
                    try:
                        cnt = self._cache.count_by_model(self._game_name, m)
                    except Exception:
                        cnt = 0
                    models_with_counts.append((m, cnt))
                try:
                    total_all = self._cache.count_entries(self._game_name)
                except Exception:
                    total_all = sum(c for _, c in models_with_counts)
            except Exception:
                pass

        self._cache_combo.addItem(f"🌐 كل النماذج ({total_all:,} ترجمة)", "")
        for m, cnt in models_with_counts:
            self._cache_combo.addItem(f"🤖 {m} ({cnt:,} ترجمة)", m)
        self._cache_combo.addItem("❌ بدون كاش — ترجم من الصفر", "none")

        self._cache_combo.setToolTip(
            "كل النماذج: يستخدم أي ترجمة سابقة موجودة (الأسرع).\n"
            "موديل محدد: فقط ترجماته تُسترجَع — البقية تُترجَم من جديد.\n"
            "بدون كاش: يتجاهل كل الكاش، يرسل كل نص للمحرّك (للاختبار من الصفر)."
        )

        lay.addWidget(self._cache_combo)
        return frame

    def _on_confirm(self):
        btn = self._group.checkedButton()
        if btn:
            self._selected_mode = btn.property("mode_key") or "bulletproof"
        if hasattr(self, "_cache_combo"):
            self._selected_cache_filter = self._cache_combo.currentData() or ""
        self.accept()

    def _on_open_tag_config(self):
        """يفتح حوار إعدادات التاقات. عند الإغلاق، يبقى هذا الحوار مفتوحاً."""
        try:
            from gui.qt.dialogs.tag_config_dialog import TagConfigDialog
            dlg = TagConfigDialog(parent=self)
            dlg.exec()
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "خطأ", f"تعذّر فتح إعدادات التاقات:\n{e}")
