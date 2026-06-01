"""
gui/qt/dialogs/skip_list_dialog.py — تحرير قائمة المنع (skip patterns).

النصوص المطابقة لأي نمط هنا لا تُرسل إلى المحرّك (Ollama):
  • توفير موارد + تجنّب فشل متكرّر على أسماء الأعلام (Nexa, * SDF, ...)
  • تُعدّ "بدون تغيير" بدل فشل

يمكن فتحه:
  - بدون نصوص بذور → لإدارة الأنماط فقط
  - مع نصوص بذور (failed_texts) → لاقتراح أنماط بناءً على ما اختاره المستخدم

الأنماط wildcard: * يطابق أي شيء، ? يطابق حرفاً واحداً.
"""
from __future__ import annotations

import re
from typing import Iterable

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QMessageBox, QFrame,
    QCheckBox, QScrollArea, QWidget,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor

from gui.qt.theme import theme
from engine import skip_patterns


# ── Pattern suggestion helpers ──────────────────────────────────────────────

def _suggest_patterns(text: str) -> list[str]:
    """يقترح أنماطاً معقولة من نص فاشل واحد."""
    text = (text or "").strip()
    if not text:
        return []
    out: list[str] = [text]  # النص الحرفي أولاً
    parts = text.split()
    if len(parts) == 1:
        # كلمة واحدة → جرّب prefix / suffix / contains
        if len(text) >= 3:
            out.append(f"{text}*")
            out.append(f"*{text}")
            out.append(f"*{text}*")
    else:
        # عدة كلمات: أبقِ أول/آخر كلمة
        first = parts[0]
        last = parts[-1]
        if len(first) >= 2:
            out.append(f"{first} *")
        if len(last) >= 2:
            out.append(f"* {last}")
        out.append(f"{first} *{last}")
    # أزل التكرار مع المحافظة على الترتيب
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


class SkipListDialog(QDialog):
    """حوار إدارة قائمة المنع."""

    saved = Signal()   # يُطلَق بعد كل تعديل ينعكس على الملف

    def __init__(self, parent=None, seed_texts: Iterable[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("قائمة المنع — Skip Patterns")
        # حد أدنى مرن + حجم افتراضي مريح + قابلية التكبير
        self.setMinimumSize(560, 480)
        self.resize(820, 700)
        self.setSizeGripEnabled(True)
        # نضيف min/max بدون استبدال أعلام النافذة الافتراضية (يحافظ على زر X)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.Window
            | Qt.WindowMinMaxButtonsHint
            | Qt.WindowCloseButtonHint
        )
        self.setModal(False)
        self._seeds: list[str] = list(seed_texts or [])
        self._build()
        self._refresh_list()
        self._refresh_seeds_view()

    # ── Build ────────────────────────────────────────────────────────────

    def _build(self):
        c = theme.c
        TEXT_BRIGHT = c.get('secondary', '#e8e8e8')
        TEXT_MUTED  = c.get('muted', '#9a9a9a')
        ACCENT      = c.get('accent', '#e94560')
        TEAL        = c.get('teal', '#00d2ff')
        self.setStyleSheet(f"""
            QDialog {{ background: {c['bg']}; color: {TEXT_BRIGHT}; }}
            QLabel  {{ color: {TEXT_BRIGHT}; background: transparent; }}
            QListWidget {{
                background: {c['card']}; color: {TEXT_BRIGHT};
                border: 1px solid {c['border']}; border-radius: 6px;
                font-family: Consolas, monospace; font-size: 12px;
                padding: 4px;
            }}
            QListWidget::item {{ padding: 4px 8px; color: {TEXT_BRIGHT}; }}
            QListWidget::item:selected {{
                background: {ACCENT}; color: white;
            }}
            QLineEdit {{
                background: {c['card2']}; color: {TEXT_BRIGHT};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 6px 8px; font-size: 12px;
                selection-background-color: {ACCENT};
            }}
            QPushButton {{
                background: {c['surface']}; color: {TEXT_BRIGHT};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 6px 14px; font-size: 12px;
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
            QPushButton#danger {{
                background: {c['accent']}; color: white;
                border: 1px solid {c['accent']}; font-weight: bold;
            }}
            QPushButton#chip {{
                background: {c['card2']}; color: {TEXT_BRIGHT};
                border: 1px solid {c['border']}; border-radius: 12px;
                padding: 3px 10px; font-size: 11px;
                font-family: Consolas, monospace;
            }}
            QPushButton#chip:hover {{
                background: {ACCENT}; color: white; border-color: {ACCENT};
            }}
            QPushButton:disabled {{
                background: {c['card']}; color: {TEXT_MUTED};
                border-color: {c['border']};
            }}
            QCheckBox {{ color: {TEXT_BRIGHT}; spacing: 6px; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        # ── Title ────────────────────────────────────────────────────────
        title = QLabel("🚫  قائمة المنع — Skip Patterns")
        title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {c['accent']};")
        root.addWidget(title)

        hint = QLabel(
            "النصوص المطابقة لأي نمط هنا لا تُرسَل لـ Ollama "
            "(تُعدّ \"بدون تغيير\"، لا فشل).\n"
            "استخدم * للمطابقة الجزئية:  \"Nexa *\"  أو  \"* SDF\""
        )
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # ── Section 1: seed texts (if any) ────────────────────────────────
        if self._seeds:
            root.addWidget(self._build_seeds_section())

        # ── Section 2: add new pattern ────────────────────────────────────
        root.addWidget(self._build_add_section())

        # ── Section 3: current patterns ────────────────────────────────────
        root.addWidget(self._build_list_section(), 1)

        # ── Bottom buttons ────────────────────────────────────────────────
        bottom = QHBoxLayout()
        reset_btn = QPushButton("↺  استعادة الافتراضي")
        reset_btn.clicked.connect(self._on_reset)
        reset_btn.setCursor(QCursor(Qt.PointingHandCursor))
        bottom.addWidget(reset_btn)
        bottom.addStretch()
        close_btn = QPushButton("إغلاق")
        close_btn.setObjectName("primary")
        close_btn.clicked.connect(self.accept)
        close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

    # ── Section: seed texts ───────────────────────────────────────────────

    def _build_seeds_section(self) -> QFrame:
        c = theme.c
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {c['surface']}; border-radius: 8px; }}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        head = QLabel(f"📝  النصوص المختارة ({len(self._seeds)}) — اضغط نمطاً مقترَحاً لإضافته")
        head.setStyleSheet(f"font-weight: bold; font-size: 12px; color: {c['primary']};")
        lay.addWidget(head)

        # سكرول للنصوص + أنماطها المقترحة
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(200)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: 1px solid {c['border']}; border-radius: 6px; }}"
        )
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self._seeds_layout = QVBoxLayout(inner)
        self._seeds_layout.setContentsMargins(8, 6, 8, 6)
        self._seeds_layout.setSpacing(8)
        scroll.setWidget(inner)
        lay.addWidget(scroll)

        return frame

    def _refresh_seeds_view(self):
        if not self._seeds or not hasattr(self, "_seeds_layout"):
            return
        # نظّف القديم
        while self._seeds_layout.count():
            item = self._seeds_layout.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.deleteLater()

        c = theme.c
        current_pats = skip_patterns.get_patterns()
        for text in self._seeds:
            row = QFrame()
            row.setStyleSheet(
                f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 6px; }}"
            )
            rl = QVBoxLayout(row)
            rl.setContentsMargins(8, 6, 8, 6)
            rl.setSpacing(4)

            # سطر النص + هل هو ممنوع حالياً؟
            already = skip_patterns.matches(text, current_pats)
            head_row = QHBoxLayout()
            head_row.setSpacing(8)
            lbl = QLabel(f"«{text}»")
            lbl.setStyleSheet(f"color: {c['primary']}; font-family: Consolas, monospace;")
            head_row.addWidget(lbl)
            head_row.addStretch()
            if already:
                st = QLabel(f"✅ ممنوع بـ  {already}")
                st.setStyleSheet(f"color: {c.get('teal', '#00d2ff')}; font-size: 11px;")
                head_row.addWidget(st)
            rl.addLayout(head_row)

            # شارات الأنماط المقترحة
            chips = QHBoxLayout()
            chips.setSpacing(6)
            chips.setContentsMargins(0, 0, 0, 0)
            for sug in _suggest_patterns(text):
                btn = QPushButton(sug)
                btn.setObjectName("chip")
                btn.setCursor(QCursor(Qt.PointingHandCursor))
                btn.setToolTip(f"إضافة النمط:  {sug}")
                btn.clicked.connect(lambda _c=False, p=sug: self._quick_add(p))
                chips.addWidget(btn)
            chips.addStretch()
            rl.addLayout(chips)
            self._seeds_layout.addWidget(row)
        self._seeds_layout.addStretch()

    # ── Section: add new pattern ──────────────────────────────────────────

    def _build_add_section(self) -> QFrame:
        c = theme.c
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {c['surface']}; border-radius: 8px; }}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        head = QLabel("➕  إضافة نمط جديد")
        head.setStyleSheet(f"font-weight: bold; font-size: 12px; color: {c['primary']};")
        lay.addWidget(head)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._input = QLineEdit()
        self._input.setPlaceholderText("مثال:  Nexa *   أو   * SDF   أو   Continue")
        self._input.returnPressed.connect(self._on_add)
        self._input.textChanged.connect(self._update_match_preview)
        row.addWidget(self._input, 1)

        add_btn = QPushButton("➕  أضف")
        add_btn.setObjectName("primary")
        add_btn.setCursor(QCursor(Qt.PointingHandCursor))
        add_btn.clicked.connect(self._on_add)
        row.addWidget(add_btn)
        lay.addLayout(row)

        self._preview_lbl = QLabel(" ")
        self._preview_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        lay.addWidget(self._preview_lbl)

        return frame

    def _update_match_preview(self, text: str):
        text = (text or "").strip()
        c = theme.c
        if not text:
            self._preview_lbl.setText(" ")
            return
        if not self._seeds:
            self._preview_lbl.setText(
                f"النمط:  {text}  —  سيُطبَّق على كل النصوص الجديدة"
            )
            self._preview_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
            return
        n = skip_patterns.count_matching(self._seeds, [text])
        total = len(self._seeds)
        if n == 0:
            color = c.get('accent', '#e94560')
            msg = f"⚠ النمط «{text}» لا يطابق أيّاً من الـ {total} نصاً المُختار"
        elif n == total:
            color = c.get('teal', '#00d2ff')
            msg = f"✅ النمط «{text}» يطابق كل الـ {total} نصاً"
        else:
            color = c.get('yellow', '#ffa600')
            msg = f"النمط «{text}» يطابق {n} من {total} نصاً مختاراً"
        self._preview_lbl.setText(msg)
        self._preview_lbl.setStyleSheet(f"color: {color}; font-size: 11px;")

    # ── Section: current patterns list ────────────────────────────────────

    def _build_list_section(self) -> QFrame:
        c = theme.c
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {c['surface']}; border-radius: 8px; }}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        head_row = QHBoxLayout()
        self._list_head = QLabel("📋  الأنماط الحالية (0)")
        self._list_head.setStyleSheet(f"font-weight: bold; font-size: 12px; color: {c['primary']};")
        head_row.addWidget(self._list_head)
        head_row.addStretch()

        del_btn = QPushButton("🗑  حذف المحدَّد")
        del_btn.setObjectName("danger")
        del_btn.setCursor(QCursor(Qt.PointingHandCursor))
        del_btn.clicked.connect(self._on_remove)
        head_row.addWidget(del_btn)
        lay.addLayout(head_row)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.ExtendedSelection)
        lay.addWidget(self._list, 1)

        return frame

    def _refresh_list(self):
        pats = skip_patterns.get_patterns()
        self._list.clear()
        for p in pats:
            self._list.addItem(p)
        self._list_head.setText(f"📋  الأنماط الحالية ({len(pats)})")
        # حدّث معاينة المُدخَل لأن الأنماط الجديدة قد تغيّر العد
        if hasattr(self, "_input"):
            self._update_match_preview(self._input.text())
        # حدّث حالة "ممنوع" في صف البذور
        self._refresh_seeds_view()

    # ── Actions ──────────────────────────────────────────────────────────

    def _on_add(self):
        pat = self._input.text().strip()
        if not pat:
            return
        if skip_patterns.add_pattern(pat):
            self._input.clear()
            self._refresh_list()
            self.saved.emit()
        else:
            QMessageBox.information(self, "موجود مسبقاً", f"النمط «{pat}» مضاف بالفعل.")

    def _quick_add(self, pattern: str):
        if skip_patterns.add_pattern(pattern):
            self._refresh_list()
            self.saved.emit()
        else:
            # موجود سلفاً — لا حاجة لإزعاج المستخدم بمربع حوار
            self._refresh_list()

    def _on_remove(self):
        items = self._list.selectedItems()
        if not items:
            return
        if len(items) == 1:
            msg = f"حذف النمط «{items[0].text()}»؟"
        else:
            msg = f"حذف {len(items)} أنماط محدّدة؟"
        if QMessageBox.question(
            self, "تأكيد الحذف", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        for it in items:
            skip_patterns.remove_pattern(it.text())
        self._refresh_list()
        self.saved.emit()

    def _on_reset(self):
        if QMessageBox.question(
            self, "استعادة الافتراضي",
            "سيتم استبدال القائمة الحالية بالأنماط الافتراضية\n"
            "(Nexa*, * SDF, * Bold, ...).\nمتابعة؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        skip_patterns.reset_to_defaults()
        self._refresh_list()
        self.saved.emit()
