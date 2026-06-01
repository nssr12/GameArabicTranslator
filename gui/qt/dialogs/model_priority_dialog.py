"""
gui/qt/dialogs/model_priority_dialog.py — تحديد أولوية المودلات (drag-drop).

يُستخدم في الدمج الهرمي عند تصدير translations.txt:
  • الأعلى في القائمة = priority أكبر = يفوز عند التعارض
  • النص الذي له ترجمات من مودلات متعدّدة يأخذ ترجمة المودل الأعلى أولوية
  • تتفعّل في المستوى 4 من خوارزمية cache.get_best()

البيانات تُحفظ في جدول model_priority (per-game) في قاعدة بيانات اللعبة.
"""
from __future__ import annotations
from typing import Iterable

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QMessageBox, QAbstractItemView,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QFont

from gui.qt.theme import theme


class ModelPriorityDialog(QDialog):
    """حوار ترتيب أولوية المودلات لاستخدامها في الدمج الهرمي."""

    saved = Signal()   # يُطلَق بعد الحفظ

    def __init__(self, game_name: str, cache, parent=None):
        super().__init__(parent)
        self._game_name = game_name
        self._cache = cache

        self.setWindowTitle(f"أولوية المودلات — {game_name}")
        self.setMinimumSize(540, 480)
        self.resize(720, 600)
        self.setSizeGripEnabled(True)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.Window
            | Qt.WindowMinMaxButtonsHint
            | Qt.WindowCloseButtonHint
        )
        self.setModal(False)
        self._build()
        self._load_models()

    def _build(self):
        c = theme.c
        TEXT_BRIGHT = c.get("secondary", "#e8e8e8")
        TEXT_MUTED  = c.get("muted", "#9a9a9a")
        ACCENT      = c.get("accent", "#e94560")
        TEAL        = c.get("teal", "#00d2ff")
        GREEN       = c.get("green", "#2e7d32")

        self.setStyleSheet(f"""
            QDialog {{ background: {c['bg']}; color: {TEXT_BRIGHT}; }}
            QLabel  {{ color: {TEXT_BRIGHT}; background: transparent; }}
            QListWidget {{
                background: {c['card']}; color: {TEXT_BRIGHT};
                border: 1px solid {c['border']}; border-radius: 6px;
                font-family: Consolas, monospace; font-size: 13px;
                padding: 6px;
                outline: 0;
            }}
            QListWidget::item {{
                padding: 10px 12px;
                border-bottom: 1px solid {c['border']};
                color: {TEXT_BRIGHT};
            }}
            QListWidget::item:selected {{
                background: {TEAL}; color: white;
                border-radius: 4px;
            }}
            QListWidget::item:hover {{
                background: {c['hover']};
            }}
            QPushButton {{
                background: {c['surface']}; color: {TEXT_BRIGHT};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 8px 16px; font-size: 12px;
            }}
            QPushButton:hover {{
                background: {c['hover']}; color: white;
                border-color: {ACCENT};
            }}
            QPushButton#primary {{
                background: {GREEN}; color: white;
                border: 1px solid {GREEN}; font-weight: bold;
            }}
            QPushButton#primary:hover {{ background: {TEAL}; border-color: {TEAL}; }}
            QPushButton#danger {{
                background: {c['surface']}; color: {ACCENT};
                border: 1px solid {ACCENT}; font-weight: bold;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        # ── Header ─────────────────────────────────────────────────────
        title = QLabel(f"🎯  أولوية المودلات — {self._game_name}")
        title.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {ACCENT};"
        )
        root.addWidget(title)

        hint = QLabel(
            "اسحب وأفلت لإعادة الترتيب. <b>الأعلى في القائمة</b> يفوز عند التعارض "
            "في الدمج الهرمي.\n"
            "تُستخدم هذه الأولوية عند تصدير <code>translations.txt</code> باختيار "
            "<b>«كل النماذج»</b> فقط."
        )
        hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.RichText)
        root.addWidget(hint)

        # شريط مساعد بصري
        legend = QFrame()
        legend.setStyleSheet(
            f"background: {c['surface']}; border-radius: 6px; padding: 8px;"
        )
        ll = QHBoxLayout(legend)
        ll.setContentsMargins(10, 6, 10, 6)
        up_lbl = QLabel("⬆ أعلى أولوية")
        up_lbl.setStyleSheet(f"color: {GREEN}; font-weight: bold; font-size: 11px;")
        dn_lbl = QLabel("⬇ أدنى أولوية")
        dn_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        ll.addWidget(up_lbl)
        ll.addStretch()
        ll.addWidget(dn_lbl)
        root.addWidget(legend)

        # ── القائمة (drag-drop) ────────────────────────────────────────
        self._list = QListWidget()
        self._list.setDragEnabled(True)
        self._list.setAcceptDrops(True)
        self._list.setDropIndicatorShown(True)
        self._list.setDragDropMode(QAbstractItemView.InternalMove)
        self._list.setDefaultDropAction(Qt.MoveAction)
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        # تحديث الأولويات المعروضة بعد كل عملية سحب
        self._list.model().rowsMoved.connect(self._refresh_display)
        root.addWidget(self._list, 1)

        # ── أزرار التحكم ──────────────────────────────────────────────
        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        reset_btn = QPushButton("↺  إعادة تعيين")
        reset_btn.setObjectName("danger")
        reset_btn.setCursor(QCursor(Qt.PointingHandCursor))
        reset_btn.setToolTip("يحذف الأولويات → يعود للترتيب التلقائي (الأحدث يفوز)")
        reset_btn.clicked.connect(self._on_reset)
        bottom.addWidget(reset_btn)

        bottom.addStretch()

        cancel_btn = QPushButton("إلغاء")
        cancel_btn.setCursor(QCursor(Qt.PointingHandCursor))
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)

        save_btn = QPushButton("💾  حفظ الأولوية")
        save_btn.setObjectName("primary")
        save_btn.setCursor(QCursor(Qt.PointingHandCursor))
        save_btn.clicked.connect(self._on_save)
        bottom.addWidget(save_btn)
        root.addLayout(bottom)

    # ── تحميل ─────────────────────────────────────────────────────────

    def _load_models(self):
        """يجلب كل المودلات المستخدَمة في كاش اللعبة + أولوياتها الحالية."""
        try:
            models = self._cache.get_models_for_game(self._game_name)
            counts = self._cache.count_by_model(self._game_name)
            priorities = self._cache.get_model_priorities(self._game_name)
        except Exception as e:
            QMessageBox.warning(
                self, "خطأ في القراءة",
                f"تعذّر قراءة المودلات من الكاش:\n{e}"
            )
            models, counts, priorities = [], {}, {}

        if not models:
            placeholder = QListWidgetItem("لا توجد ترجمات في الكاش لهذه اللعبة بعد.")
            placeholder.setFlags(Qt.NoItemFlags)   # غير قابل للسحب أو التحديد
            placeholder.setTextAlignment(Qt.AlignCenter)
            self._list.addItem(placeholder)
            return

        # رتّب: أولاً المودلات التي لها priority (الأعلى أولاً)،
        # ثم باقي المودلات (التي بلا priority) حسب الأبجدية
        with_prio = [(m, priorities[m]) for m in models if m in priorities]
        with_prio.sort(key=lambda x: -x[1])
        no_prio = sorted([m for m in models if m not in priorities])

        ordered = [m for m, _ in with_prio] + no_prio
        for model in ordered:
            count = counts.get(model, 0)
            self._add_item(model, count)
        self._refresh_display()

    def _add_item(self, model: str, count: int):
        c = theme.c
        item = QListWidgetItem()
        # نخزّن اسم المودل في UserRole للوصول السهل عند الحفظ
        item.setData(Qt.UserRole, model)
        item.setText(self._format_item(0, model, count))
        item.setFlags(item.flags() | Qt.ItemIsDragEnabled | Qt.ItemIsSelectable)
        # خط أكبر قليلاً للقراءة المريحة
        f = QFont("Consolas", 11)
        item.setFont(f)
        self._list.addItem(item)

    def _format_item(self, rank: int, model: str, count: int) -> str:
        """ينسّق نص الصف: ⋮⋮ <اسم المودل> [count]"""
        # rank سيُحدَّث بعد كل سحب — لكن نُظهر الترتيب الحالي للوضوح
        return f"  ⋮⋮   {model}   —   {count:,} ترجمة"

    # ── أحداث ─────────────────────────────────────────────────────────

    def _refresh_display(self, *args):
        """يحدّث نصوص الصفوف لتعكس الترتيب الحالي (لو احتجنا rank)."""
        # نُبقي العرض كما هو — اسم المودل + العداد
        # (الترتيب نفسه = priority، لا نحتاج عرض الرقم)
        pass

    def _on_save(self):
        """يحفظ الترتيب الحالي في model_priority. الأعلى يأخذ أكبر priority."""
        count_rows = self._list.count()
        if count_rows == 0:
            self.reject()
            return
        try:
            # الـ priority = (الرقم العكسي) — الأعلى في القائمة = أكبر priority
            # مثلاً 3 مودلات: الأول=3، الثاني=2، الثالث=1
            for i in range(count_rows):
                item = self._list.item(i)
                model = item.data(Qt.UserRole)
                if not model:
                    continue
                priority = count_rows - i   # الأعلى في القائمة = أكبر رقم
                self._cache.set_model_priority(self._game_name, model, priority)
            self.saved.emit()
            QMessageBox.information(
                self, "✅ حُفظت الأولوية",
                f"تم حفظ ترتيب {count_rows} مودل.\n"
                f"يُطبَّق عند تصدير translations.txt بـ «كل النماذج»."
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "خطأ في الحفظ", str(e))

    def _on_reset(self):
        """يحذف كل الأولويات → الدمج يعود للأحدث."""
        if QMessageBox.question(
            self, "تأكيد إعادة التعيين",
            "حذف كل أولويات المودلات؟\n\n"
            "الدمج الهرمي سيستخدم القاعدة الافتراضية:\n"
            "  1) is_preferred=1\n"
            "  2) mode='manual'\n"
            "  3) إجماع 2+ مودلات\n"
            "  4) (الأولوية — ستُلغى)\n"
            "  5) الأحدث (fallback)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        try:
            # نمسح بإعداد priority=0 لكل مودل (يتجاوزه get_best)
            for i in range(self._list.count()):
                item = self._list.item(i)
                model = item.data(Qt.UserRole)
                if model:
                    self._cache.set_model_priority(self._game_name, model, 0)
            self.saved.emit()
            QMessageBox.information(self, "✓", "تم إلغاء الأولويات.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "خطأ", str(e))
