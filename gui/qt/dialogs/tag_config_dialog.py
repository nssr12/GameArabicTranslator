"""
gui/qt/dialogs/tag_config_dialog.py — تحرير قائمة التاقات المحمية.

يسمح للمستخدم بـ:
  - إضافة/حذف تاقات inline (تبقى مع النص للمودل)
  - إضافة/حذف تاقات self-closing (تُحمى بـ ⟦sN⟧)

التغييرات تُحفظ في data/tag_config.json وتُطبَّق فوراً عبر reload_tag_config().
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QMessageBox, QFrame,
    QTextEdit, QSplitter,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QTextOption

from gui.qt.theme import theme
from engine.tag_config import (
    load_config, save_config, reset_to_defaults,
    DEFAULT_INLINE_TAGS, DEFAULT_SELFCLOSE_TAGS,
)


class TagConfigDialog(QDialog):
    """حوار تحرير قائمة التاقات المحمية في Tiered/Bulletproof."""

    saved = Signal()   # يُطلَق بعد الحفظ بنجاح

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إعدادات حماية التاقات")
        self.setMinimumSize(780, 720)
        self._cfg = load_config()
        self._build()

    # ── Build UI ──────────────────────────────────────────────────────────

    def _build(self):
        c = theme.c
        self.setStyleSheet(f"""
            QDialog {{ background: {c['bg']}; }}
            QLabel  {{ color: {c['primary']}; background: transparent; }}
            QListWidget {{
                background: {c['card']}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 6px;
                font-family: Consolas, monospace; font-size: 12px;
                padding: 4px;
            }}
            QListWidget::item {{ padding: 4px 8px; }}
            QListWidget::item:selected {{
                background: {c['primary']}; color: white;
            }}
            QLineEdit {{
                background: {c['card2']}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 4px 8px; font-size: 12px;
            }}
            QPushButton {{
                background: {c['surface']}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 6px 14px; font-size: 12px;
            }}
            QPushButton:hover {{ background: {c['hover']}; }}
            QPushButton#primary {{
                background: {c['primary']}; color: white; border: none;
            }}
            QPushButton#danger {{
                background: {c['accent']}; color: white; border: none;
            }}
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # ── العنوان والتوضيح ─────────────────────────────────────────────
        title = QLabel("🏷  إعدادات حماية التاقات")
        title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {c['accent']};")
        root.addWidget(title)

        hint = QLabel(
            "هذه القوائم تتحكم في كيفية تعامل وضع Tiered/Bulletproof مع التاقات.\n"
            "التاقات مع سمات (مثل <color=red>) تُحمى تلقائياً ولا تحتاج إضافة هنا."
        )
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # ── قسم Inline tags ─────────────────────────────────────────────
        root.addWidget(self._build_section(
            "📌 تاقات Inline — تبقى مع النص للمودل",
            "تاقات بسيطة (مثل <b> <i> <u>) تُترك للمودل ليفهم سياق الجملة.\n"
            "إذا كان لها سمات، تُحمى تلقائياً بـ ⟦N⟧/⟦/N⟧.",
            "inline",
        ))

        # ── قسم Self-closing tags ───────────────────────────────────────
        root.addWidget(self._build_section(
            "🎯 تاقات Self-closing — تُحمى بـ ⟦sN⟧",
            "تاقات بلا محتوى داخلي (مثل <sprite>, <br>) — تُستخرَج وتُستعاد كاملة.\n"
            "⚠ لا تضع تاقات مزدوجة (<b>...</b>) هنا — لن تعمل بشكل صحيح.",
            "selfclose",
        ))

        # ── قسم المعاينة الحية ──────────────────────────────────────────
        root.addWidget(self._build_preview_section())

        # ── أزرار التحكم السفلية ───────────────────────────────────────
        bottom = QHBoxLayout()
        reset_btn = QPushButton("↺  استعادة الافتراضي")
        reset_btn.clicked.connect(self._on_reset)
        reset_btn.setCursor(QCursor(Qt.PointingHandCursor))
        bottom.addWidget(reset_btn)
        bottom.addStretch()
        cancel_btn = QPushButton("إلغاء")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setCursor(QCursor(Qt.PointingHandCursor))
        save_btn = QPushButton("💾  حفظ")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._on_save)
        save_btn.setCursor(QCursor(Qt.PointingHandCursor))
        bottom.addWidget(cancel_btn)
        bottom.addWidget(save_btn)
        root.addLayout(bottom)

        # استدعاء أوّلي للمعاينة بالقيم المُحمَّلة
        self._update_preview()

    def _build_section(self, title: str, hint: str, kind: str) -> QFrame:
        """يبني قسم قائمة + add/remove. kind: 'inline' | 'selfclose'."""
        c = theme.c
        frame = QFrame()
        frame.setStyleSheet(f"QFrame {{ background: {c['surface']}; border-radius: 8px; padding: 4px; }}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        head = QLabel(title)
        head.setStyleSheet(f"font-weight: bold; font-size: 12px; color: {c['primary']};")
        lay.addWidget(head)

        sub = QLabel(hint)
        sub.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # القائمة
        lst = QListWidget()
        lst.setSelectionMode(QListWidget.ExtendedSelection)
        lst.setMaximumHeight(140)
        key = "inline_tags" if kind == "inline" else "selfclosing_tags"
        for t in self._cfg.get(key, []):
            lst.addItem(t)

        # شريط إضافة + حذف
        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)
        input_box = QLineEdit()
        input_box.setPlaceholderText("اكتب اسم التاق (مثل: color، sprite) ثم Enter")
        add_btn = QPushButton("➕ إضافة")
        del_btn = QPushButton("🗑 حذف المحدَّد")
        del_btn.setObjectName("danger")
        add_btn.setCursor(QCursor(Qt.PointingHandCursor))
        del_btn.setCursor(QCursor(Qt.PointingHandCursor))

        def add_tag():
            name = input_box.text().strip().lower().lstrip("<").rstrip(">").rstrip("/")
            if not name:
                return
            # تحقق عدم تكرار
            for i in range(lst.count()):
                if lst.item(i).text() == name:
                    QMessageBox.information(self, "موجود مسبقاً", f"التاق «{name}» مُضاف بالفعل.")
                    return
            lst.addItem(name)
            input_box.clear()

        def del_selected():
            for item in lst.selectedItems():
                lst.takeItem(lst.row(item))

        add_btn.clicked.connect(add_tag)
        del_btn.clicked.connect(del_selected)
        input_box.returnPressed.connect(add_tag)

        ctrl.addWidget(input_box, 1)
        ctrl.addWidget(add_btn)
        ctrl.addWidget(del_btn)

        lay.addWidget(lst)
        lay.addLayout(ctrl)

        # احفظ references للوصول لها في save
        if kind == "inline":
            self._inline_list = lst
        else:
            self._selfclose_list = lst

        # حدّث المعاينة عند أي تغيير في القائمة
        def _trigger_preview():
            if hasattr(self, "_preview_input"):
                self._update_preview()
        lst.model().rowsInserted.connect(lambda *a: _trigger_preview())
        lst.model().rowsRemoved.connect(lambda *a: _trigger_preview())

        return frame

    def _build_preview_section(self) -> QFrame:
        """قسم معاينة الفلتر — اكتب نصاً وشاهد ما يُرسل للمحرّك مباشرة."""
        c = theme.c
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {c['surface']}; border-radius: 8px; }}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        head = QLabel("🔬  معاينة الفلتر — اختبر قبل تشغيل الخادم")
        head.setStyleSheet(f"font-weight: bold; font-size: 12px; color: {c['accent']};")
        lay.addWidget(head)

        sub = QLabel(
            "اكتب نصاً يحتوي تاقات لتشاهد ما يخرج بعد تطبيق إعداداتك الحالية.\n"
            "يُحدَّث تلقائياً مع كل تغيير."
        )
        sub.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # حقل الإدخال
        self._preview_input = QTextEdit()
        self._preview_input.setMaximumHeight(70)
        self._preview_input.setPlaceholderText(
            'مثلاً: Hello <b>World</b> with <color=red>RED</color> and <sprite name="x">'
        )
        self._preview_input.setLayoutDirection(Qt.LeftToRight)
        opt_in = QTextOption()
        opt_in.setTextDirection(Qt.LeftToRight)
        self._preview_input.document().setDefaultTextOption(opt_in)
        self._preview_input.setStyleSheet(
            f"QTextEdit {{ background: {c['card2']}; color: {c['primary']};"
            f"             border: 1px solid {c['border']}; border-radius: 4px;"
            f"             padding: 6px; font-family: Consolas, monospace; font-size: 11px; }}"
        )
        self._preview_input.setText(
            'Hello <b>World</b> with <color=red>RED</color> and <sprite name="x">'
        )
        self._preview_input.textChanged.connect(self._update_preview)
        lay.addWidget(self._preview_input)

        # حقل الإخراج (read-only)
        out_lbl = QLabel("📤 ما سيصل للمحرّك:")
        out_lbl.setStyleSheet(f"color: {c['teal']}; font-size: 10px;")
        lay.addWidget(out_lbl)

        self._preview_output = QTextEdit()
        self._preview_output.setReadOnly(True)
        self._preview_output.setMaximumHeight(60)
        self._preview_output.setLayoutDirection(Qt.LeftToRight)
        opt_out = QTextOption()
        opt_out.setTextDirection(Qt.LeftToRight)
        self._preview_output.document().setDefaultTextOption(opt_out)
        self._preview_output.setStyleSheet(
            f"QTextEdit {{ background: {c['card']}; color: {c['green']};"
            f"             border: 1px solid {c['border']}; border-radius: 4px;"
            f"             padding: 6px; font-family: Consolas, monospace; font-size: 11px; }}"
        )
        lay.addWidget(self._preview_output)

        # سجل التاقات المستخرجة
        self._preview_tokens = QLabel("")
        self._preview_tokens.setStyleSheet(
            f"color: {c['yellow']}; font-size: 10px; font-family: Consolas, monospace;"
        )
        self._preview_tokens.setWordWrap(True)
        self._preview_tokens.setTextFormat(Qt.PlainText)
        lay.addWidget(self._preview_tokens)

        return frame

    def _update_preview(self):
        """يُعيد حساب المعاينة من القوائم الحالية في الحوار."""
        # نبني فلتر مؤقّت بالقيم الحالية في القوائم (قبل الحفظ)
        try:
            from engine.tag_filter import BulletproofTagFilter, _build_selfclose_re
            inline_now = frozenset(
                self._inline_list.item(i).text()
                for i in range(self._inline_list.count())
            )
            selfclose_now = [
                self._selfclose_list.item(i).text()
                for i in range(self._selfclose_list.count())
            ]
            flt = BulletproofTagFilter(inline_tags=inline_now)
            flt._selfclose_re = _build_selfclose_re(selfclose_now)
            text = self._preview_input.toPlainText()
            cleaned, tokens = flt.strip(text)
            self._preview_output.setPlainText(cleaned)

            if tokens:
                lines = []
                for idx, (kind, name, attrs, _inner) in enumerate(tokens):
                    if kind == "paired":
                        lines.append(f"⟦{idx}⟧/⟦/{idx}⟧ ← <{name}{attrs}>...</{name}>")
                    else:
                        lines.append(f"⟦s{idx}⟧ ← <{name}{attrs}>")
                self._preview_tokens.setText("\n".join(lines))
            else:
                self._preview_tokens.setText(
                    "(لا توجد تاقات مُستخرَجة — كلها تبقى inline أو لا توجد تاقات)"
                )
        except Exception as e:
            self._preview_output.setPlainText(f"خطأ: {e}")
            self._preview_tokens.setText("")

    # ── Actions ───────────────────────────────────────────────────────────

    def _on_reset(self):
        if QMessageBox.question(
            self, "تأكيد",
            "استعادة القائمتين للقيم الافتراضية؟\n"
            "سيُلغى أي تاق أضفته يدوياً.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        self._inline_list.clear()
        for t in DEFAULT_INLINE_TAGS:
            self._inline_list.addItem(t)
        self._selfclose_list.clear()
        for t in DEFAULT_SELFCLOSE_TAGS:
            self._selfclose_list.addItem(t)

    def _on_save(self):
        inline = [self._inline_list.item(i).text()
                  for i in range(self._inline_list.count())]
        selfclose = [self._selfclose_list.item(i).text()
                     for i in range(self._selfclose_list.count())]
        try:
            save_config({
                "inline_tags": inline,
                "selfclosing_tags": selfclose,
            })
            # أعد تحميل الفلتر مباشرة دون انتظار إعادة التشغيل
            from engine.tag_filter import reload_tag_config
            reload_tag_config()
            self.saved.emit()
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "خطأ في الحفظ", str(e))
