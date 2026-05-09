"""
gui/qt/pages/translate.py  —  صفحة الترجمة الفورية (المرحلة 6)
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QTextEdit, QSizePolicy, QScrollArea,
    QComboBox, QToolButton, QApplication,
)
from PySide6.QtCore  import Qt, QThread, Signal, QTimer
from PySide6.QtGui   import QCursor, QFont, QTextCursor, QKeySequence, QShortcut, QTextOption

from gui.qt.theme              import theme
from gui.qt.widgets.page_header import make_topbar


LANG_OPTIONS = [
    ("en", "English"),
    ("ar", "Arabic — عربي"),
    ("fr", "French"),
    ("de", "German"),
    ("es", "Spanish"),
    ("ja", "Japanese"),
    ("zh", "Chinese"),
    ("ko", "Korean"),
    ("ru", "Russian"),
    ("tr", "Turkish"),
]


# ── Translation worker ────────────────────────────────────────────────────────

class SingleTranslateWorker(QThread):
    done = Signal(str, str, bool)   # result, model_key, success

    def __init__(self, text: str, engine, src_lang: str = "en", tgt_lang: str = "ar"):
        super().__init__()
        self._text      = text
        self._engine    = engine
        self._src       = src_lang
        self._tgt       = tgt_lang
        self._cancelled = False

    def cancel(self):
        """Interrupt in-flight Ollama request by closing its session."""
        self._cancelled = True
        try:
            active = self._engine.get_active_model()
            if active:
                tr = self._engine.get_translator(active)
                if hasattr(tr, "cancel_current_request"):
                    tr.cancel_current_request()
        except Exception:
            pass

    def run(self):
        try:
            result = self._engine.translate(
                self._text,
                source_lang=self._src,
                target_lang=self._tgt,
            )
            if self._cancelled:
                self.done.emit("", "", False)
                return
            model = self._engine.get_active_model() or ""
            if result:
                self.done.emit(result, model, True)
            else:
                self.done.emit("", model, False)
        except Exception as e:
            if self._cancelled:
                self.done.emit("", "", False)
            else:
                self.done.emit(str(e), "", False)


# ── History entry ─────────────────────────────────────────────────────────────

class HistoryEntry(QFrame):
    """سطر واحد في سجل الترجمة."""

    copy_requested = Signal(str)   # text to copy

    def __init__(self, original: str, translated: str,
                 model: str, success: bool, parent=None):
        super().__init__(parent)
        c = theme.c
        self.setStyleSheet(f"""
            QFrame {{
                background: {c['card']};
                border: 1px solid {c['border']};
                border-radius: 8px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(6)

        # Top: original + model badge
        top = QHBoxLayout()
        orig_lbl = QLabel(original if len(original) < 100 else original[:97] + "…")
        orig_lbl.setStyleSheet(
            f"color: {c['muted']}; font-size: 11px;"
            " background: transparent; border: none;"
        )
        orig_lbl.setWordWrap(True)
        top.addWidget(orig_lbl, 1)

        if model:
            model_badge = QLabel(model)
            model_badge.setStyleSheet(f"""
                background: rgba(0,0,0,0.2);
                color: {c['blue']};
                border: 1px solid {c['blue']};
                border-radius: 6px;
                padding: 1px 7px;
                font-size: 9px;
            """)
            top.addWidget(model_badge)

        lay.addLayout(top)

        # Translation text
        if success and translated:
            trans_lbl = QLabel(translated if len(translated) < 200 else translated[:197] + "…")
            trans_lbl.setStyleSheet(
                f"color: {c['green']}; font-size: 13px; font-weight: bold;"
                " background: transparent; border: none;"
            )
            trans_lbl.setWordWrap(True)
            trans_lbl.setLayoutDirection(Qt.RightToLeft)
            lay.addWidget(trans_lbl)

            # Copy button
            copy_btn = QToolButton()
            copy_btn.setText("📋 نسخ")
            copy_btn.setCursor(QCursor(Qt.PointingHandCursor))
            copy_btn.setStyleSheet(f"""
                QToolButton {{
                    background: transparent; border: none;
                    color: {c['muted']}; font-size: 10px;
                }}
                QToolButton:hover {{ color: {c['accent']}; }}
            """)
            copy_btn.clicked.connect(lambda: self.copy_requested.emit(translated))
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            btn_row.addWidget(copy_btn)
            lay.addLayout(btn_row)
        else:
            err_lbl = QLabel(f"✗  {translated or 'فشلت الترجمة'}")
            err_lbl.setStyleSheet(
                f"color: {c['accent']}; font-size: 12px;"
                " background: transparent; border: none;"
            )
            lay.addWidget(err_lbl)


# ── Translate page ────────────────────────────────────────────────────────────

class TranslatePage(QWidget):
    """صفحة الترجمة الفورية."""

    status_message = Signal(str)
    session_count  = Signal(int)   # كل ترجمة ناجحة

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine  = None
        self._cache   = None
        self._worker: SingleTranslateWorker | None = None
        self._history: list[dict] = []
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        c   = theme.c
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_topbar())
        lay.addWidget(self._build_main_area(), 1)

    def _build_topbar(self) -> QFrame:
        bar, lay = make_topbar("🌐", "الترجمة الفورية")

        clear_btn = QPushButton("🗑️  مسح السجل")
        clear_btn.setObjectName("btn_secondary")
        clear_btn.setFixedHeight(34)
        clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        clear_btn.clicked.connect(self._clear_history)
        lay.addWidget(clear_btn)

        return bar

    def _build_main_area(self) -> QWidget:
        c   = theme.c
        w   = QWidget()
        w.setStyleSheet(f"background: {c['bg']};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        lay.addWidget(self._build_translator_card())
        lay.addWidget(self._build_history_section(), 1)

        return w

    def _build_translator_card(self) -> QFrame:
        c     = theme.c
        card  = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: {c['card']};
                border: 1px solid {c['border']};
                border-radius: 12px;
            }}
        """)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(20, 16, 20, 16)
        card_lay.setSpacing(12)

        # Language selector row
        lang_row = QHBoxLayout()
        lang_row.setSpacing(10)

        def _lang_lbl(t):
            l = QLabel(t)
            l.setStyleSheet(
                f"color: {c['muted']}; font-size: 11px;"
                " background: transparent; border: none;"
            )
            return l

        def _lang_combo():
            cb = QComboBox()
            cb.setFixedHeight(30)
            cb.setStyleSheet(f"""
                QComboBox {{
                    background: {c['surface']}; color: {c['primary']};
                    border: 1px solid {c['border']}; border-radius: 6px;
                    padding: 2px 8px; min-width: 130px;
                }}
                QComboBox:focus {{ border-color: {c['accent']}; }}
                QComboBox::drop-down {{ border: none; width: 20px; }}
                QComboBox QAbstractItemView {{
                    background: {c['surface']}; color: {c['primary']};
                    selection-background-color: {c['accent']};
                }}
            """)
            for val, label in LANG_OPTIONS:
                cb.addItem(label, val)
            return cb

        self._src_combo = _lang_combo()
        self._src_combo.setCurrentIndex(0)   # en

        swap_btn = QPushButton("⇄")
        swap_btn.setFixedSize(30, 30)
        swap_btn.setCursor(QCursor(Qt.PointingHandCursor))
        swap_btn.setToolTip("تبديل اللغتين")
        swap_btn.setStyleSheet(f"""
            QPushButton {{
                background: {c['surface']}; color: {c['secondary']};
                border: 1px solid {c['border']}; border-radius: 6px; font-size: 14px;
            }}
            QPushButton:hover {{ background: {c['hover']}; color: {c['accent']}; }}
        """)
        swap_btn.clicked.connect(self._swap_langs)

        self._tgt_combo = _lang_combo()
        self._tgt_combo.setCurrentIndex(1)   # ar

        lang_row.addWidget(_lang_lbl("من:"))
        lang_row.addWidget(self._src_combo)
        lang_row.addWidget(swap_btn)
        lang_row.addWidget(_lang_lbl("إلى:"))
        lang_row.addWidget(self._tgt_combo)
        lang_row.addStretch()

        # Model indicator
        self._model_badge = QLabel("—")
        self._model_badge.setStyleSheet(f"""
            background: rgba(0,0,0,0.2);
            color: {c['blue']};
            border: 1px solid {c['blue']};
            border-radius: 6px;
            padding: 2px 10px;
            font-size: 10px;
            background: transparent; border: none;
        """)
        lang_row.addWidget(_lang_lbl("النموذج:"))
        lang_row.addWidget(self._model_badge)

        card_lay.addLayout(lang_row)

        # ── Input / Output side by side ───────────────────────────────────────
        panels = QHBoxLayout()
        panels.setSpacing(14)

        # Input
        in_frame = QFrame()
        in_frame.setStyleSheet(f"""
            QFrame {{
                background: {c['surface']};
                border: 1px solid {c['border']};
                border-radius: 8px;
            }}
        """)
        in_lay = QVBoxLayout(in_frame)
        in_lay.setContentsMargins(0, 0, 0, 0)
        in_lay.setSpacing(0)

        in_hdr = QLabel("النص الأصلي")
        in_hdr.setStyleSheet(
            f"color: {c['muted']}; font-size: 10px; padding: 8px 12px 4px 12px;"
            " background: transparent; border: none; border-bottom: 1px solid {c['border']};"
        )
        in_lay.addWidget(in_hdr)

        self._input = QTextEdit()
        self._input.setPlaceholderText("اكتب النص هنا… (Ctrl+Enter للترجمة)")
        self._input.setMinimumHeight(130)
        self._input.setStyleSheet(f"""
            QTextEdit {{
                background: transparent; color: {c['primary']};
                border: none; padding: 10px 12px;
                font-size: 13px;
                selection-background-color: {c['accent']};
            }}
        """)
        self._input.textChanged.connect(self._on_input_changed)
        in_lay.addWidget(self._input, 1)

        # Char count
        in_foot = QHBoxLayout()
        in_foot.setContentsMargins(12, 4, 12, 8)
        self._char_lbl = QLabel("0 حرف")
        self._char_lbl.setStyleSheet(
            f"color: {c['muted']}; font-size: 10px; background: transparent; border: none;"
        )
        clear_input_btn = QToolButton()
        clear_input_btn.setText("✕")
        clear_input_btn.setCursor(QCursor(Qt.PointingHandCursor))
        clear_input_btn.setStyleSheet(f"""
            QToolButton {{ background: transparent; border: none;
                           color: {c['muted']}; font-size: 11px; }}
            QToolButton:hover {{ color: {c['accent']}; }}
        """)
        clear_input_btn.clicked.connect(self._input.clear)
        in_foot.addWidget(self._char_lbl)
        in_foot.addStretch()
        in_foot.addWidget(clear_input_btn)
        in_lay.addLayout(in_foot)

        # Output
        out_frame = QFrame()
        out_frame.setStyleSheet(f"""
            QFrame {{
                background: {c['surface']};
                border: 1px solid {c['border']};
                border-radius: 8px;
            }}
        """)
        out_lay = QVBoxLayout(out_frame)
        out_lay.setContentsMargins(0, 0, 0, 0)
        out_lay.setSpacing(0)

        out_hdr = QHBoxLayout()
        out_hdr.setContentsMargins(12, 8, 12, 4)
        out_hdr_lbl = QLabel("الترجمة")
        out_hdr_lbl.setStyleSheet(
            f"color: {c['muted']}; font-size: 10px; background: transparent; border: none;"
        )
        self._copy_btn = QToolButton()
        self._copy_btn.setText("📋 نسخ")
        self._copy_btn.setEnabled(False)
        self._copy_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._copy_btn.setStyleSheet(f"""
            QToolButton {{
                background: transparent; border: none;
                color: {c['muted']}; font-size: 10px;
            }}
            QToolButton:hover {{ color: {c['accent']}; }}
            QToolButton:disabled {{ color: {c['border']}; }}
        """)
        self._copy_btn.clicked.connect(self._copy_output)
        out_hdr.addWidget(out_hdr_lbl)
        out_hdr.addStretch()
        out_hdr.addWidget(self._copy_btn)

        out_hdr_frame = QFrame()
        out_hdr_frame.setStyleSheet(
            f"border-bottom: 1px solid {c['border']}; background: transparent;"
        )
        out_hdr_frame.setLayout(out_hdr)
        out_lay.addWidget(out_hdr_frame)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setPlaceholderText("ستظهر الترجمة هنا…")
        self._output.setMinimumHeight(130)
        self._output.setLayoutDirection(Qt.RightToLeft)
        opt = QTextOption()
        opt.setTextDirection(Qt.RightToLeft)
        self._output.document().setDefaultTextOption(opt)
        self._output.setStyleSheet(f"""
            QTextEdit {{
                background: transparent; color: {c['green']};
                border: none; padding: 10px 12px;
                font-size: 13px;
                selection-background-color: {c['accent']};
            }}
        """)
        out_lay.addWidget(self._output, 1)
        out_lay.addSpacing(12)

        panels.addWidget(in_frame, 1)
        panels.addWidget(out_frame, 1)
        card_lay.addLayout(panels)

        # ── Translate button + status ─────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(
            f"color: {c['muted']}; font-size: 11px; background: transparent; border: none;"
        )
        btn_row.addWidget(self._status_lbl, 1)

        self._translate_btn = QPushButton("🌐  ترجمة  (Ctrl+Enter)")
        self._translate_btn.setFixedHeight(40)
        self._translate_btn.setMinimumWidth(200)
        self._translate_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._translate_btn.setStyleSheet(f"""
            QPushButton {{
                background: {c['accent']}; color: #fff;
                border: none; border-radius: 10px;
                font-size: 13px; font-weight: bold; padding: 0 24px;
            }}
            QPushButton:hover {{ background: {c.get('blue', c['accent'])}; }}
            QPushButton:disabled {{ background: {c['surface']}; color: {c['muted']}; }}
        """)
        self._translate_btn.clicked.connect(self._do_translate)
        btn_row.addWidget(self._translate_btn)

        self._cancel_btn = QPushButton("✕  إلغاء")
        self._cancel_btn.setFixedHeight(40)
        self._cancel_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._cancel_btn.setVisible(False)
        self._cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: {c['surface']}; color: {c['accent']};
                border: 1px solid {c['accent']}; border-radius: 10px;
                font-size: 13px; font-weight: bold; padding: 0 18px;
            }}
            QPushButton:hover {{ background: {c['accent']}; color: #fff; }}
        """)
        self._cancel_btn.clicked.connect(self.cancel_worker)
        btn_row.addWidget(self._cancel_btn)

        card_lay.addLayout(btn_row)

        # Keyboard shortcut
        sc = QShortcut(QKeySequence("Ctrl+Return"), self)
        sc.activated.connect(self._do_translate)

        return card

    def _build_history_section(self) -> QWidget:
        c   = theme.c
        w   = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        hdr = QHBoxLayout()
        hdr_lbl = QLabel("📋  سجل الترجمات")
        hdr_lbl.setStyleSheet(
            f"color: {c['secondary']}; font-size: 14px; font-weight: bold;"
            " background: transparent; border: none;"
        )
        hdr.addWidget(hdr_lbl)
        hdr.addStretch()
        lay.addLayout(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background: transparent; border: none;")

        self._history_widget = QWidget()
        self._history_widget.setStyleSheet("background: transparent;")
        self._history_lay = QVBoxLayout(self._history_widget)
        self._history_lay.setContentsMargins(0, 0, 0, 0)
        self._history_lay.setSpacing(8)
        self._history_lay.addStretch()

        self._empty_history = QLabel("لا توجد ترجمات بعد — ابدأ بكتابة نص أعلاه")
        self._empty_history.setAlignment(Qt.AlignCenter)
        self._empty_history.setStyleSheet(
            f"color: {c['muted']}; font-size: 12px; padding: 20px;"
            " background: transparent; border: none;"
        )
        self._history_lay.insertWidget(0, self._empty_history)

        scroll.setWidget(self._history_widget)
        lay.addWidget(scroll, 1)
        return w

    # ── Backend injection ─────────────────────────────────────────────────────

    def set_backend(self, engine, cache, game_manager=None):
        self._engine = engine
        self._cache  = cache
        self._refresh_model_badge()

    def _refresh_model_badge(self):
        if self._engine:
            active = self._engine.get_active_model()
            if active:
                from gui.qt.pages.models import _meta
                self._model_badge.setText(_meta(active)["ar"])
                return
        self._model_badge.setText("لا يوجد نموذج")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_input_changed(self):
        text = self._input.toPlainText()
        n    = len(text)
        self._char_lbl.setText(f"{n:,} حرف")

    def _swap_langs(self):
        si = self._src_combo.currentIndex()
        ti = self._tgt_combo.currentIndex()
        self._src_combo.setCurrentIndex(ti)
        self._tgt_combo.setCurrentIndex(si)
        # Also swap text
        src_txt = self._input.toPlainText()
        out_txt = self._output.toPlainText()
        if out_txt:
            self._input.setPlainText(out_txt)
            self._output.setPlainText(src_txt)

    def _copy_output(self):
        txt = self._output.toPlainText()
        if txt:
            QApplication.clipboard().setText(txt)
            self.status_message.emit("✓  تم نسخ النص")

    def _do_translate(self):
        text = self._input.toPlainText().strip()
        if not text:
            return

        if not self._engine:
            self._set_status("✗  لا يوجد نموذج مُحمَّل — يرجى تحميل نموذج أولاً", False)
            return

        if not self._engine.get_active_model():
            self._set_status("✗  لا يوجد نموذج نشط — اختره من صفحة النماذج", False)
            return

        if self._worker and self._worker.isRunning():
            return

        # Reset the session-failed flag so Ollama is retried after user opens it
        try:
            active = self._engine.get_active_model()
            if active:
                tr = self._engine.get_translator(active)
                if tr:
                    tr._load_failed_session = False
        except Exception:
            pass

        self._translate_btn.setEnabled(False)
        self._translate_btn.setText("⏳  جاري الترجمة…")
        self._cancel_btn.setVisible(True)
        self._output.setPlainText("")
        self._copy_btn.setEnabled(False)
        self._set_status("جاري الترجمة…", None)

        src = self._src_combo.currentData()
        tgt = self._tgt_combo.currentData()

        w = SingleTranslateWorker(text, self._engine, src, tgt)
        w.done.connect(self._on_translate_done)
        w.done.connect(w.deleteLater)
        self._worker = w
        w.start()

    def cancel_worker(self):
        """Cancel in-flight translation and reset UI."""
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)  # wait up to 3s for clean exit
        self._worker = None
        self._translate_btn.setEnabled(True)
        self._translate_btn.setText("🌐  ترجمة  (Ctrl+Enter)")
        self._cancel_btn.setVisible(False)
        self._set_status("تم الإلغاء", None)

    def _on_translate_done(self, result: str, model: str, success: bool):
        self._worker = None
        self._cancel_btn.setVisible(False)
        self._translate_btn.setEnabled(True)
        self._translate_btn.setText("🌐  ترجمة  (Ctrl+Enter)")

        if success and result:
            self._output.setPlainText(result)
            self._copy_btn.setEnabled(True)
            self._set_status(f"✓  الترجمة اكتملت — النموذج: {model}", True)
            self.status_message.emit(f"✓  ترجمة ناجحة عبر: {model}")
            self.session_count.emit(1)
            self._add_history(
                self._input.toPlainText().strip(), result, model, True
            )
        else:
            self._output.setPlainText("")
            self._set_status(f"✗  {result or 'فشلت الترجمة'}", False)
            self._add_history(
                self._input.toPlainText().strip(), result, model, False
            )

        self._refresh_model_badge()

    def _set_status(self, msg: str, success):
        c = theme.c
        if success is True:
            color = c["green"]
        elif success is False:
            color = c["accent"]
        else:
            color = c["muted"]
        self._status_lbl.setStyleSheet(
            f"color: {color}; font-size: 11px; background: transparent; border: none;"
        )
        self._status_lbl.setText(msg)

    def _add_history(self, original: str, translated: str,
                     model: str, success: bool):
        self._history.append({
            "original":   original,
            "translated": translated,
            "model":      model,
            "success":    success,
        })

        try:
            # Remove empty-state label (guard: may be deleted if layout rebuilt)
            if self._empty_history.isVisible():
                self._empty_history.hide()
        except RuntimeError:
            pass

        entry = HistoryEntry(original, translated, model, success)
        entry.copy_requested.connect(
            lambda t: QApplication.clipboard().setText(t) or
                      self.status_message.emit("✓  تم نسخ الترجمة")
        )

        # Insert at top (entries sit before _empty_history and the stretch)
        self._history_lay.insertWidget(0, entry)

        # Layout = [entries..., _empty_history, stretch] → 3 fixed slots (+50 entries = 52)
        while self._history_lay.count() > 52:
            item = self._history_lay.takeAt(50)  # oldest entry, before _empty_history
            if item and item.widget():
                item.widget().deleteLater()

    def _clear_history(self):
        self._history.clear()
        # Remove all HistoryEntry widgets, keep _empty_history + stretch (last 2)
        while self._history_lay.count() > 2:
            item = self._history_lay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        try:
            self._empty_history.show()
        except RuntimeError:
            pass
        self.status_message.emit("✓  تم مسح السجل")
