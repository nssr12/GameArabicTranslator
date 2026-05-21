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
    QRadioButton, QButtonGroup, QFrame,
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

    def __init__(self, current_mode: str = "bulletproof", game_name: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("تأكيد وضع التاقات")
        self.setMinimumWidth(560)
        self._selected_mode = current_mode
        self._game_name = game_name
        self._open_tag_config_requested = False
        self._build(current_mode)

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

    def _on_confirm(self):
        btn = self._group.checkedButton()
        if btn:
            self._selected_mode = btn.property("mode_key") or "bulletproof"
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
