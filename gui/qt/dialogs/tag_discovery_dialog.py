"""
gui/qt/dialogs/tag_discovery_dialog.py — حوار اكتشاف التاقات من نصوص الكاش.

يعرض كل التاقات المكتشفة في النصوص المحدَّدة، مع checkbox لكل واحد +
قائمة منسدلة لاختيار نوعه (inline أو selfclosing)، ثم يضيفها لـ tag_config.json.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QCheckBox, QMessageBox, QFrame, QWidget,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QColor

from gui.qt.theme import theme
from engine.tag_discovery import discover_tags, TagInfo
from engine.tag_config import add_tags, load_config


class TagDiscoveryDialog(QDialog):
    """حوار يكتشف التاقات من نصوص ويسمح بإضافتها لقائمة الحماية."""

    saved = Signal(int, int)   # (added_inline, added_selfclose)

    def __init__(self, texts: list[str], parent=None):
        super().__init__(parent)
        self._texts = [t for t in texts if t]
        self._existing = load_config()
        self._existing_all = (
            set(self._existing.get("inline_tags", []))
            | set(self._existing.get("selfclosing_tags", []))
        )
        self._results: list[TagInfo] = discover_tags(self._texts)
        # الـ rows في الجدول: نخزّن (TagInfo, checkbox, combo)
        self._rows: list[tuple[TagInfo, QCheckBox, QComboBox]] = []

        self.setWindowTitle("🏷  اكتشاف التاقات من النصوص")
        self.setMinimumSize(720, 520)
        self.resize(900, 680)
        self.setSizeGripEnabled(True)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.Window
            | Qt.WindowMinMaxButtonsHint
            | Qt.WindowCloseButtonHint
        )
        self.setModal(True)
        self._build()

    # ── Build UI ──────────────────────────────────────────────────────────

    def _build(self):
        c = theme.c
        TEXT_BRIGHT = c.get('secondary', '#e8e8e8')
        TEXT_MUTED  = c.get('muted', '#9a9a9a')
        ACCENT      = c.get('accent', '#e94560')
        TEAL        = c.get('teal', '#00d2ff')
        OK          = c.get('success', '#19c37d')

        self.setStyleSheet(f"""
            QDialog {{ background: {c['bg']}; color: {TEXT_BRIGHT}; }}
            QLabel  {{ color: {TEXT_BRIGHT}; background: transparent; }}
            QTableWidget {{
                background: {c['card']}; color: {TEXT_BRIGHT};
                gridline-color: {c['border']};
                border: 1px solid {c['border']}; border-radius: 6px;
                font-size: 12px;
                selection-background-color: {ACCENT};
                selection-color: white;
            }}
            QHeaderView::section {{
                background: {c['surface']}; color: {TEXT_BRIGHT};
                padding: 6px 8px; border: 0; border-bottom: 1px solid {c['border']};
                font-weight: bold;
            }}
            QComboBox {{
                background: {c['card2']}; color: {TEXT_BRIGHT};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 4px 8px; font-size: 11px;
            }}
            QCheckBox {{ color: {TEXT_BRIGHT}; }}
            QPushButton {{
                background: {c['surface']}; color: {TEXT_BRIGHT};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 6px 14px; font-size: 12px; font-weight: 500;
            }}
            QPushButton:hover {{
                background: {c['hover']}; color: white;
                border-color: {ACCENT};
            }}
            QPushButton#primary {{
                background: {ACCENT}; color: white; border: 1px solid {ACCENT};
                font-weight: bold;
            }}
            QPushButton#primary:hover {{ background: {TEAL}; border-color: {TEAL}; }}
            QPushButton:disabled {{
                background: {c['card']}; color: {TEXT_MUTED};
                border-color: {c['border']};
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # ── العنوان ────────────────────────────────────────────────────
        title = QLabel("🏷  التاقات المكتشفة في النصوص المحدَّدة")
        title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {ACCENT};")
        root.addWidget(title)

        hint = QLabel(
            f"تم فحص {len(self._texts)} نص — وُجد {len(self._results)} تاق فريد.\n"
            "اختر التاقات التي تريد حمايتها، ثم حدّد نوعها:\n"
            "  • Inline  → تبقى مع النص للمودل (مفيد لـ <b> <i> الإلخ)\n"
            "  • Selfclosing → تُحمى بـ ⟦sN⟧ ولا تذهب للمودل (للتاقات الخاصة مثل <itemName .../>)"
        )
        hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # ── شريط الإجراءات السريعة ─────────────────────────────────────
        actions = QHBoxLayout()
        actions.setSpacing(6)
        btn_select_all = QPushButton("☑  حدّد الكل")
        btn_select_new = QPushButton("☑  الجديدة فقط")
        btn_clear      = QPushButton("☐  إلغاء التحديد")
        for b in (btn_select_all, btn_select_new, btn_clear):
            b.setCursor(QCursor(Qt.PointingHandCursor))
        btn_select_all.clicked.connect(self._select_all)
        btn_select_new.clicked.connect(self._select_new_only)
        btn_clear.clicked.connect(self._clear_selection)
        actions.addWidget(btn_select_all)
        actions.addWidget(btn_select_new)
        actions.addWidget(btn_clear)
        actions.addStretch()
        root.addLayout(actions)

        # ── الجدول ──────────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "✓", "اسم التاق", "النوع المقترح", "العدد", "الحالة", "مثال"
        ])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(34)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.Fixed)
        hdr.setSectionResizeMode(4, QHeaderView.Fixed)
        hdr.setSectionResizeMode(5, QHeaderView.Stretch)
        self._table.setColumnWidth(0, 40)
        self._table.setColumnWidth(2, 140)
        self._table.setColumnWidth(3, 70)
        self._table.setColumnWidth(4, 100)

        self._populate_table()
        root.addWidget(self._table, 1)

        # ── أزرار التحكم السفلية ───────────────────────────────────────
        bottom = QHBoxLayout()
        self._summary = QLabel("لم يُحدَّد شيء بعد")
        self._summary.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        bottom.addWidget(self._summary)
        bottom.addStretch()

        cancel_btn = QPushButton("إلغاء")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setCursor(QCursor(Qt.PointingHandCursor))
        bottom.addWidget(cancel_btn)

        self._save_btn = QPushButton("💾  أضِف للقائمة")
        self._save_btn.setObjectName("primary")
        self._save_btn.clicked.connect(self._on_save)
        self._save_btn.setCursor(QCursor(Qt.PointingHandCursor))
        bottom.addWidget(self._save_btn)

        root.addLayout(bottom)
        self._update_summary()

    def _populate_table(self):
        """يملأ الجدول بكل التاقات المكتشفة."""
        c = theme.c
        OK_COLOR     = QColor(c.get('success', '#19c37d'))
        MUTED_COLOR  = QColor(c.get('muted', '#9a9a9a'))

        self._table.setRowCount(len(self._results))
        for i, ti in enumerate(self._results):
            is_existing = ti.name in self._existing_all

            # عمود 0: checkbox (داخل widget مركزي)
            cb_wrap = QWidget()
            cb_lay  = QHBoxLayout(cb_wrap)
            cb_lay.setContentsMargins(0, 0, 0, 0)
            cb_lay.setAlignment(Qt.AlignCenter)
            cb = QCheckBox()
            cb.setChecked(not is_existing)   # افتراضياً نحدّد الجديد
            cb.stateChanged.connect(self._update_summary)
            cb_lay.addWidget(cb)
            self._table.setCellWidget(i, 0, cb_wrap)

            # عمود 1: اسم التاق
            name_item = QTableWidgetItem(ti.name)
            name_item.setFont(self._mono_font())
            if is_existing:
                name_item.setForeground(MUTED_COLOR)
            self._table.setItem(i, 1, name_item)

            # عمود 2: combo للنوع
            combo = QComboBox()
            combo.addItem("Selfclosing  (⟦sN⟧)", "selfclosing")
            combo.addItem("Inline  (للمودل)",    "inline")
            default_idx = 0 if ti.suggested_kind == "selfclosing" else 1
            combo.setCurrentIndex(default_idx)
            self._table.setCellWidget(i, 2, combo)

            # عمود 3: العدد
            cnt_item = QTableWidgetItem(str(ti.count))
            cnt_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(i, 3, cnt_item)

            # عمود 4: الحالة (موجود/جديد)
            if is_existing:
                status = QTableWidgetItem("موجود")
                status.setForeground(MUTED_COLOR)
            else:
                status = QTableWidgetItem("🆕 جديد")
                status.setForeground(OK_COLOR)
            status.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(i, 4, status)

            # عمود 5: مثال
            ex_item = QTableWidgetItem(ti.example)
            ex_item.setFont(self._mono_font())
            ex_item.setToolTip(
                "\n\n".join(ti.sources[:3]) if ti.sources else ti.example
            )
            self._table.setItem(i, 5, ex_item)

            self._rows.append((ti, cb, combo))

    def _mono_font(self):
        from PySide6.QtGui import QFont
        f = QFont("Consolas", 10)
        f.setStyleHint(QFont.Monospace)
        return f

    # ── Actions ───────────────────────────────────────────────────────────

    def _select_all(self):
        for _ti, cb, _co in self._rows:
            cb.setChecked(True)

    def _select_new_only(self):
        for ti, cb, _co in self._rows:
            cb.setChecked(ti.name not in self._existing_all)

    def _clear_selection(self):
        for _ti, cb, _co in self._rows:
            cb.setChecked(False)

    def _update_summary(self):
        selected = [(ti, co) for ti, cb, co in self._rows if cb.isChecked()]
        new_count = sum(1 for ti, _ in selected if ti.name not in self._existing_all)
        dup_count = len(selected) - new_count
        c = theme.c
        TEXT_MUTED = c.get('muted', '#9a9a9a')
        if not selected:
            self._summary.setText("لم يُحدَّد شيء بعد")
            self._summary.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
            self._save_btn.setEnabled(False)
        else:
            parts = [f"محدَّد: {len(selected)}"]
            if new_count:
                parts.append(f"جديد: {new_count}")
            if dup_count:
                parts.append(f"موجود: {dup_count} (سيُتجاوَز)")
            self._summary.setText("  ·  ".join(parts))
            self._summary.setStyleSheet(
                f"color: {c.get('secondary','#e8e8e8')}; font-size: 11px;"
            )
            self._save_btn.setEnabled(new_count > 0)

    def _on_save(self):
        inline: list[str] = []
        selfclose: list[str] = []
        for ti, cb, combo in self._rows:
            if not cb.isChecked():
                continue
            kind = combo.currentData()
            if kind == "inline":
                inline.append(ti.name)
            else:
                selfclose.append(ti.name)

        if not inline and not selfclose:
            QMessageBox.information(self, "لا يوجد تحديد", "لم تختر أي تاق لإضافته.")
            return

        added_in, added_sf = add_tags(inline=inline, selfclosing=selfclose)

        # طبّق التغيير فوراً على tag_filter
        try:
            from engine import tag_filter
            if hasattr(tag_filter, "reload_tag_config"):
                tag_filter.reload_tag_config()
        except Exception:
            pass

        QMessageBox.information(
            self, "تمت الإضافة",
            f"✓  تمت إضافة {added_in + added_sf} تاق جديد:\n"
            f"   • Inline: {added_in}\n"
            f"   • Selfclosing: {added_sf}\n\n"
            "التغييرات مفعّلة فوراً — الترجمات القادمة ستحمي هذه التاقات."
        )
        self.saved.emit(added_in, added_sf)
        self.accept()


__all__ = ["TagDiscoveryDialog"]
