"""
gui/qt/pages/cache.py  —  صفحة الكاش الكاملة (المرحلة 1)
"""

from __future__ import annotations
import os
import threading

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QLineEdit, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSizePolicy, QMessageBox, QProgressBar,
    QScrollArea
)
from PySide6.QtCore  import Qt, QThread, Signal, QTimer, QSize
from PySide6.QtGui   import QColor, QFont, QCursor

from gui.qt.theme              import theme
from gui.qt.widgets.page_header import make_topbar
from engine.cache    import TranslationCache


# ── Re-translate worker ───────────────────────────────────────────────────────

class RetranslateWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(int, int)

    def __init__(self, entries: list, engine, cache: TranslationCache):
        super().__init__()
        self._entries = entries
        self._engine  = engine
        self._cache   = cache
        self._stop    = False

    def stop(self):
        self._stop = True

    def run(self):
        done = failed = 0
        total = len(self._entries)
        for i, entry in enumerate(self._entries):
            if self._stop:
                break
            orig = entry["original"]
            game = entry.get("game", "")
            try:
                result = self._engine.translate(orig)
                if result and result != orig:
                    if self._cache:
                        self._cache.update_translation(game, orig, result)
                    done += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
            self.progress.emit(i + 1, total)
        self.finished.emit(done, failed)


# ── Sync worker ───────────────────────────────────────────────────────────────

class SyncWorker(QThread):
    log_line = Signal(str)
    finished = Signal(bool)

    def __init__(self, game_id: str, cache, wizard: dict):
        super().__init__()
        self._game_id = game_id
        self._cache   = cache
        self._wizard  = wizard

    def run(self):
        import shutil
        from games.translation_package import TranslationPackage
        from games.iostore.translator  import IoStoreTranslator

        ios = IoStoreTranslator()
        ios.set_callbacks(log=lambda m: self.log_line.emit(m))
        pkg = TranslationPackage()

        w               = self._wizard
        zen_version     = w.get("zen_version",     "UE5_6")
        ue_version      = w.get("ue_version",      "VER_UE5_6")
        mode            = w.get("extraction_mode", "default_text")
        mappings        = w.get("mappings",        "")
        output_base     = w.get("output_base",     "")
        game_target_dir = w.get("game_target_dir", "")

        # Step 1: Get translations from cache
        self.log_line.emit("📦  جلب الترجمات من الكاش...")
        translations = self._cache.get_all_for_game(self._game_id)
        self.log_line.emit(f"  {len(translations):,} ترجمة مخزّنة")
        if not translations:
            self.log_line.emit("⚠️  لا توجد ترجمات في الكاش — أضف ترجمات أولاً")
            self.finished.emit(False)
            return

        # Step 2: Locate for_cache/Paks_legacy folder
        legacy_dir = pkg.get_legacy_in_cache(self._game_id)
        if not legacy_dir or not os.path.isdir(legacy_dir):
            self.log_line.emit("❌  مجلد for_cache/Paks_legacy غير موجود")
            self.finished.emit(False)
            return
        self.log_line.emit(f"📁  {legacy_dir}")

        # Step 3: Apply translations to all JSON files (from .orig sources)
        self.log_line.emit("\n✏️  تطبيق الترجمات على ملفات JSON...")
        json_count = 0
        for root, _, files in os.walk(legacy_dir):
            for fname in files:
                if not fname.endswith(".uasset.json"):
                    continue
                json_path = os.path.join(root, fname)
                orig_path = json_path + ".orig"
                src = orig_path if os.path.exists(orig_path) else None
                if ios.apply_translations_to_json(json_path, translations, mode, source_path=src):
                    json_count += 1
        self.log_line.emit(f"  ✓ {json_count} ملف JSON")

        # Step 4: JSON → uasset
        self.log_line.emit("\n🔨  تحويل JSON → uasset...")
        converted = ios.json_folder_to_uasset(legacy_dir, ue_version, mappings)
        self.log_line.emit(f"  ✓ {converted} ملف")

        # Step 5: Build IoStore pak (to-zen)
        if not output_base:
            self.log_line.emit("❌  output_base غير محدد في wizard config")
            self.finished.emit(False)
            return
        self.log_line.emit("\n⚙️  بناء حزمة IoStore (to-zen)...")
        if not ios.to_zen(legacy_dir, output_base, zen_version):
            self.log_line.emit("❌  فشل to-zen")
            self.finished.emit(False)
            return

        # Step 6: Copy _P files to game directory
        if game_target_dir and os.path.isdir(game_target_dir):
            self.log_line.emit(f"\n📥  نسخ إلى مجلد اللعبة...")
            for ext in (".pak", ".ucas", ".utoc"):
                src = output_base + "_P" + ext
                if os.path.exists(src):
                    dst = os.path.join(game_target_dir, os.path.basename(src))
                    shutil.copy2(src, dst)
                    self.log_line.emit(f"  ✓ {os.path.basename(src)}")

        # Step 7: Save to ready/
        self.log_line.emit("\n💾  حفظ في ready/...")
        ok2, log2 = pkg.save_paks_to_ready(self._game_id, output_base + "_P", game_target_dir)
        for line in log2:
            self.log_line.emit(f"  {line}")

        self.log_line.emit("\n✅  اكتملت المزامنة بنجاح!")
        self.finished.emit(ok2)


# ── Sync log dialog ───────────────────────────────────────────────────────────

class SyncLogDialog:

    def __init__(self, game_id: str, cache, wizard: dict, parent=None):
        from PySide6.QtWidgets import QDialog, QTextEdit
        c = theme.c

        self._dlg = QDialog(parent)
        self._dlg.setWindowTitle(f"مزامنة الترجمة — {game_id}")
        self._dlg.setMinimumSize(700, 480)
        self._dlg.resize(800, 540)
        self._dlg.setStyleSheet(f"QDialog {{ background: {c['bg']}; }}")

        from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout
        root = QVBoxLayout(self._dlg)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        title = QLabel(f"🔄  مزامنة التعديل — {game_id}")
        title.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {c['accent']};"
            " background: transparent; border: none;"
        )
        root.addWidget(title)

        self._log_box = QTextEdit()
        self._log_box.setReadOnly(True)
        self._log_box.setLayoutDirection(Qt.LeftToRight)
        self._log_box.setStyleSheet(
            f"background: {c['surface']}; color: {c['primary']};"
            " font-family: Consolas, monospace; font-size: 12px;"
            f" border: 1px solid {c['border']}; border-radius: 6px; padding: 6px;"
        )
        root.addWidget(self._log_box, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._close_btn = QPushButton("إلغاء")
        self._close_btn.setObjectName("btn_secondary")
        self._close_btn.setFixedHeight(34)
        self._close_btn.setMinimumWidth(90)
        self._close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._close_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._close_btn)
        root.addLayout(btn_row)

        self._worker = SyncWorker(game_id, cache, wizard)
        self._worker.log_line.connect(self._append_log)
        self._worker.finished.connect(self._on_finished)

    def _append_log(self, text: str):
        self._log_box.append(text)
        sb = self._log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_cancel(self):
        if self._worker.isRunning():
            self._worker.terminate()
        self._dlg.reject()

    def _on_finished(self, ok: bool):
        self._close_btn.setText("إغلاق")
        self._close_btn.setObjectName("btn_primary" if ok else "btn_danger")
        self._close_btn.style().unpolish(self._close_btn)
        self._close_btn.style().polish(self._close_btn)
        self._close_btn.clicked.disconnect()
        self._close_btn.clicked.connect(self._dlg.accept)

    def exec(self):
        self._worker.start()
        return self._dlg.exec()


# ── Edit dialog ───────────────────────────────────────────────────────────────

class EditDialog(QWidget):
    """نافذة تعديل ترجمة واحدة — RTL كامل."""

    saved = Signal()

    @staticmethod
    def _normalize(text: str) -> str:
        """Converts two-char \\n to real newline for display/editing."""
        return text.replace("\\n", "\n")

    def __init__(self, game_name: str, entry: dict, cache: TranslationCache, parent=None):
        from PySide6.QtWidgets import QDialog, QTextEdit
        from PySide6.QtGui     import QTextOption
        super().__init__(parent)

        self._dlg = QDialog(parent)
        self._dlg.setWindowTitle("تعديل الترجمة")
        self._dlg.setMinimumSize(820, 640)
        self._dlg.resize(960, 700)
        self._game  = game_name
        self._entry = entry
        self._cache = cache
        c = theme.c

        root = QVBoxLayout(self._dlg)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setObjectName("dialog_header")
        hl  = QVBoxLayout(hdr)
        hl.setContentsMargins(24, 16, 24, 16)
        hl.setSpacing(4)
        t = QLabel("✏️   تعديل الترجمة")
        t.setObjectName("dialog_title")
        g = QLabel(f"اللعبة:  {game_name}")
        g.setStyleSheet(f"color: {c['muted']}; font-size: {theme.font_size - 1}px;")
        hl.addWidget(t)
        hl.addWidget(g)
        root.addWidget(hdr)

        # Body — two panels side by side
        body = QWidget()
        body.setStyleSheet(f"background-color: {c['surface']};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(24, 18, 24, 18)
        bl.setSpacing(18)

        from PySide6.QtWidgets import QTextEdit

        # English (read-only)
        lp = QVBoxLayout()
        lp.setSpacing(6)
        ll = QLabel("🔤  النص الأصلي (إنجليزي)")
        ll.setObjectName("field_label")
        self._orig = QTextEdit()
        self._orig.setReadOnly(True)
        self._orig.setPlainText(self._normalize(entry.get("original", "")))
        self._orig.setMinimumWidth(340)
        lp.addWidget(ll)
        lp.addWidget(self._orig)

        div = QFrame()
        div.setFrameShape(QFrame.VLine)
        div.setStyleSheet(f"color: {c['border']};")

        # Arabic (editable, RTL)
        rp = QVBoxLayout()
        rp.setSpacing(6)
        rl = QLabel("🌐  الترجمة العربية — قابل للتعديل")
        rl.setObjectName("field_label")
        self._trans = QTextEdit()
        self._trans.setLayoutDirection(Qt.RightToLeft)
        from PySide6.QtGui import QTextOption
        opt = QTextOption()
        opt.setTextDirection(Qt.RightToLeft)
        self._trans.document().setDefaultTextOption(opt)
        self._trans.setPlainText(self._normalize(entry.get("translated", "")))
        self._trans.setMinimumWidth(340)
        self._trans.setStyleSheet(f"""
            QTextEdit {{
                background-color: {c['card2']};
                border: 1px solid rgba(0,210,255,0.35);
                border-radius: 6px;
                color: {c['primary']};
                font-size: {theme.font_size}px;
                padding: 10px;
                selection-background-color: {c['selected']};
            }}
            QTextEdit:focus {{ border-color: {c['teal']}; }}
        """)
        rp.addWidget(rl)
        rp.addWidget(self._trans)

        bl.addLayout(lp, 1)
        bl.addWidget(div)
        bl.addLayout(rp, 1)
        root.addWidget(body, 1)

        # ── Token preview strip ───────────────────────────────────────────────
        prev_frame = QFrame()
        prev_frame.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-top: 1px solid {c['border']}; }}"
        )
        pl = QVBoxLayout(prev_frame)
        pl.setContentsMargins(24, 8, 24, 8)
        pl.setSpacing(4)

        prev_hdr = QHBoxLayout()
        prev_ttl = QLabel("👁  معاينة النص مع التاقات:")
        prev_ttl.setStyleSheet(
            f"color: {c['muted']}; font-size: 10px; background: transparent; border: none;"
        )
        legend = QLabel(
            '<span style="background:#b8860b;color:#fff;padding:1px 5px;border-radius:3px;">↵ سطر جديد</span>'
            '&nbsp;&nbsp;'
            '<span style="background:#1565c0;color:#fff;padding:1px 5px;border-radius:3px;">{N} متغير</span>'
            '&nbsp;&nbsp;'
            '<span style="background:#2e7d52;color:#fff;padding:1px 5px;border-radius:3px;">&lt;tag&gt; تاق</span>'
        )
        legend.setStyleSheet("background: transparent; border: none; font-size: 10px;")
        prev_hdr.addWidget(prev_ttl)
        prev_hdr.addStretch()
        prev_hdr.addWidget(legend)
        pl.addLayout(prev_hdr)

        self._preview_lbl = QLabel()
        self._preview_lbl.setWordWrap(True)
        self._preview_lbl.setTextFormat(Qt.RichText)
        self._preview_lbl.setLayoutDirection(Qt.RightToLeft)
        self._preview_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._preview_lbl.setStyleSheet(
            f"background: {c['surface']}; border: 1px solid {c['border']};"
            " border-radius: 4px; padding: 6px 10px; font-size: 12px;"
        )
        self._preview_lbl.setMinimumHeight(36)
        pl.addWidget(self._preview_lbl)
        root.addWidget(prev_frame)

        # Footer
        foot = QFrame()
        foot.setObjectName("dialog_footer")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(24, 10, 24, 10)
        hint = QLabel("Ctrl+Enter للحفظ   •   Esc للإلغاء")
        hint.setObjectName("hint_text")
        fl.addWidget(hint)
        fl.addStretch()
        cancel = QPushButton("إلغاء")
        cancel.setObjectName("btn_secondary")
        cancel.clicked.connect(self._dlg.reject)
        save = QPushButton("💾   حفظ")
        save.setObjectName("btn_primary")
        save.clicked.connect(self._save)
        save.setDefault(True)
        fl.addWidget(cancel)
        fl.addSpacing(8)
        fl.addWidget(save)
        root.addWidget(foot)

        self._dlg.keyPressEvent = self._key_press
        self._trans.textChanged.connect(self._update_preview)
        self._update_preview()

    def _update_preview(self):
        import html, re
        text = self._trans.toPlainText()
        text = self._normalize(text)   # ensure real newlines
        c    = theme.c
        esc  = html.escape(text)
        # ↵ newline markers (yellow-brown)
        esc = esc.replace(
            "\n",
            '<span style="background:#b8860b; color:#fff; border-radius:3px;'
            ' padding:0 4px; font-weight:bold; font-size:10px;">↵</span>'
        )
        # {N} variable tokens (blue)
        esc = re.sub(
            r'\{([^}]+)\}',
            lambda m: f'<span style="background:#1565c0; color:#fff; border-radius:3px;'
                      f' padding:0 4px; font-size:10px;">{{{m.group(1)}}}</span>',
            esc,
        )
        # <tag> / </tag> tokens (green)
        esc = re.sub(
            r'(&lt;/?[a-zA-Z][^&]*?&gt;)',
            lambda m: f'<span style="background:#2e7d52; color:#fff; border-radius:3px;'
                      f' padding:0 4px; font-size:10px;">{m.group(1)}</span>',
            esc,
        )
        self._preview_lbl.setText(
            f'<span dir="rtl" style="font-family: Consolas, monospace;">{esc}</span>'
        )

    def _key_press(self, event):
        from PySide6.QtCore import Qt
        if event.key() == Qt.Key_Return and event.modifiers() == Qt.ControlModifier:
            self._save()

    def _save(self):
        raw = self._trans.toPlainText().strip()
        if not raw or not self._cache:
            return
        # Normalize two-char \n → real newline before saving so json.dump
        # writes \n (newline) not \\n (backslash+n) in the JSON file.
        raw = self._normalize(raw)
        self._cache.update_translation(self._game, self._entry["original"], raw)
        self.saved.emit()
        self._dlg.accept()

    def exec(self) -> bool:
        return self._dlg.exec() == 1


# ── Cache Page ────────────────────────────────────────────────────────────────

class CachePage(QWidget):
    """
    صفحة الكاش الكاملة.
    يُمرَّر إليها cache و engine من app.py.
    """

    status_message = Signal(str)

    PAGE_SIZE = 60

    def __init__(self, cache: TranslationCache, engine=None, parent=None):
        super().__init__(parent)
        self._cache   = cache
        self._engine  = engine
        self._game    = "All Games"
        self._model   = "All Models"
        self._search  = ""
        self._page    = 0
        self._total   = 0
        self._worker: RetranslateWorker | None = None
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)
        self._build()
        self.refresh()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        c   = theme.c
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_topbar())
        lay.addWidget(self._build_toolbar())
        lay.addWidget(self._build_table(), 1)
        lay.addWidget(self._build_pagebar())

    def _build_topbar(self) -> QFrame:
        bar, lay = make_topbar("💾", "ذاكرة الترجمة")

        self._chip_total = self._chip("0 entries", "blue")
        self._chip_games = self._chip("0 games",   "green")
        self._chip_sel   = self._chip("0 selected", "accent")
        self._chip_sel.setVisible(False)

        for ch in (self._chip_total, self._chip_games, self._chip_sel):
            lay.addWidget(ch)

        del_btn = QPushButton("🗑  حذف الكل")
        del_btn.setObjectName("btn_danger")
        del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        del_btn.clicked.connect(self._delete_all)
        lay.addWidget(del_btn)

        return bar

    def _build_toolbar(self) -> QFrame:
        c   = theme.c
        bar = QFrame()
        bar.setObjectName("toolbar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(10)

        # Game selector
        game_lbl = QLabel("اللعبة:")
        game_lbl.setStyleSheet(f"color: {c['muted']}; font-size: {theme.font_size - 1}px;")
        self._game_combo = QComboBox()
        self._game_combo.setFixedWidth(170)
        self._game_combo.currentTextChanged.connect(self._game_changed)
        lay.addWidget(game_lbl)
        lay.addWidget(self._game_combo)
        lay.addSpacing(8)

        # Model selector
        model_lbl = QLabel("الموديل:")
        model_lbl.setStyleSheet(f"color: {c['muted']}; font-size: {theme.font_size - 1}px;")
        self._model_combo = QComboBox()
        self._model_combo.setFixedWidth(160)
        self._model_combo.currentTextChanged.connect(self._model_changed)
        lay.addWidget(model_lbl)
        lay.addWidget(self._model_combo)
        lay.addSpacing(12)

        # Search
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("🔍  ابحث... (English أو عربي)")
        self._search_box.setFixedWidth(280)
        self._search_box.textChanged.connect(lambda t: (
            setattr(self, '_search', t.strip()),
            self._search_timer.start(320)
        ))
        lay.addWidget(self._search_box)

        clr = QPushButton("✕")
        clr.setObjectName("icon_btn")
        clr.setFixedSize(28, 28)
        clr.clicked.connect(self._clear_search)
        lay.addWidget(clr)

        lay.addStretch()

        # Sync button (visible only for IoStore games with wizard config)
        self._btn_sync = QPushButton("🔄  مزامنة التعديل")
        self._btn_sync.setObjectName("btn_info")
        self._btn_sync.setVisible(False)
        self._btn_sync.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_sync.setToolTip("تطبيق كل ترجمات الكاش على ملفات اللعبة وبناء الحزمة")
        self._btn_sync.clicked.connect(self._do_sync)
        lay.addWidget(self._btn_sync)
        lay.addSpacing(8)

        # Action buttons
        self._btn_edit    = QPushButton("✏️  Edit")
        self._btn_edit.setObjectName("btn_secondary")
        self._btn_edit.setEnabled(False)

        self._btn_retrans = QPushButton("🔄  إعادة ترجمة")
        self._btn_retrans.setObjectName("btn_info")
        self._btn_retrans.setEnabled(False)

        self._btn_delete  = QPushButton("🗑  Delete")
        self._btn_delete.setObjectName("btn_danger")
        self._btn_delete.setEnabled(False)

        self._btn_edit.clicked.connect(self._edit_selected)
        self._btn_retrans.clicked.connect(self._retranslate_selected)
        self._btn_delete.clicked.connect(self._delete_selected)

        for btn in (self._btn_edit, self._btn_retrans, self._btn_delete):
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            lay.addWidget(btn)

        return bar

    def _build_table(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["#", "English", "عربي", "Model", "↻"])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setShowGrid(True)
        self._table.verticalHeader().setVisible(False)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.Fixed)
        hdr.setSectionResizeMode(4, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 55)
        self._table.setColumnWidth(3, 140)
        self._table.setColumnWidth(4, 45)
        self._table.verticalHeader().setDefaultSectionSize(36)

        self._table.doubleClicked.connect(self._edit_selected)
        self._table.itemSelectionChanged.connect(self._on_selection)

        lay.addWidget(self._table)
        return w

    def _build_pagebar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("pagebar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 6, 16, 6)
        lay.setSpacing(10)

        self._prev_btn = QPushButton("← Prev")
        self._prev_btn.setObjectName("btn_secondary")
        self._prev_btn.clicked.connect(lambda: self._change_page(-1))

        self._next_btn = QPushButton("Next →")
        self._next_btn.setObjectName("btn_secondary")
        self._next_btn.clicked.connect(lambda: self._change_page(1))

        self._page_lbl = QLabel("")
        self._page_lbl.setObjectName("statusbar_text")

        self._prog_bar = QProgressBar()
        self._prog_bar.setFixedHeight(5)
        self._prog_bar.setFixedWidth(180)
        self._prog_bar.setVisible(False)

        self._prog_lbl = QLabel("")
        self._prog_lbl.setStyleSheet(f"color: {theme.c['teal']}; font-size: {theme.font_size - 2}px;")
        self._prog_lbl.setVisible(False)

        lay.addWidget(self._prev_btn)
        lay.addWidget(self._next_btn)
        lay.addSpacing(10)
        lay.addWidget(self._page_lbl)
        lay.addStretch()
        lay.addWidget(self._prog_lbl)
        lay.addWidget(self._prog_bar)

        return bar

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _chip(text: str, variant: str = "") -> QLabel:
        lbl = QLabel(text)
        obj = f"chip_{variant}" if variant else "chip"
        lbl.setObjectName(obj)
        lbl.setAlignment(Qt.AlignCenter)
        return lbl

    # ── Data loading ──────────────────────────────────────────────────────────

    def refresh(self):
        """استدعاء خارجي لتحديث الصفحة بالكامل."""
        self._load_selectors()
        self._load_table()

    def set_engine(self, engine):
        self._engine = engine

    def _load_selectors(self):
        c = theme.c
        games = self._cache.get_all_games() if self._cache else []

        self._game_combo.blockSignals(True)
        self._game_combo.clear()
        self._game_combo.addItem("All Games")
        for g in sorted(games):
            self._game_combo.addItem(g)
        self._game_combo.setCurrentText(self._game)
        self._game_combo.blockSignals(False)

        total_all = sum(self._cache.count_entries(g) for g in games) if self._cache else 0
        self._chip_total.setText(f"{total_all:,} entries")
        self._chip_games.setText(f"{len(games)} games")

        self._reload_model_combo()

    def _reload_model_combo(self):
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        self._model_combo.addItem("All Models")
        if self._cache:
            games  = self._cache.get_all_games() if self._game == "All Games" else [self._game]
            models = set()
            for g in games:
                models.update(self._cache.get_models_for_game(g))
            for m in sorted(models):
                self._model_combo.addItem(m)
        idx = self._model_combo.findText(self._model)
        self._model_combo.setCurrentIndex(max(0, idx))
        self._model_combo.blockSignals(False)

    def _load_table(self):
        if not self._cache:
            return
        c = theme.c

        model_f = "" if self._model == "All Models" else self._model
        games   = (self._cache.get_all_games()
                   if self._game == "All Games"
                   else [self._game])

        total = sum(
            self._cache.count_entries(g, self._search, model_f)
            for g in games
        )
        self._total = total
        pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self._page  = max(0, min(self._page, pages - 1))

        rows, quota, skip = [], self.PAGE_SIZE, self._page * self.PAGE_SIZE
        for g in games:
            if quota <= 0:
                break
            g_total = self._cache.count_entries(g, self._search, model_f)
            if skip >= g_total:
                skip -= g_total
                continue
            batch = self._cache.get_page(g, skip, quota, self._search, model_f)
            for row in batch:
                rows.append({"game": g, **row})
            quota -= len(batch)
            skip = 0

        self._table.setRowCount(0)
        self._table.setRowCount(len(rows))
        offset = self._page * self.PAGE_SIZE

        for i, row in enumerate(rows):
            # #
            n = QTableWidgetItem(str(offset + i + 1))
            n.setTextAlignment(Qt.AlignCenter)
            n.setForeground(QColor(c['muted']))

            # English
            orig = QTableWidgetItem(row["original"].replace("\\n", " ↵ ").replace("\n", " ↵ "))
            orig.setForeground(QColor(c['secondary']))

            # Arabic — RTL alignment
            ar = QTableWidgetItem(row["translated"].replace("\\n", " ↵ ").replace("\n", " ↵ "))
            ar.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            ar.setForeground(QColor(c['teal']))
            ar.setData(Qt.UserRole, row)   # store full row

            # Model
            mdl = QTableWidgetItem(row.get("model", ""))
            mdl.setForeground(QColor(c['muted']))
            mdl.setFont(QFont("Consolas", theme.font_size - 2))

            # Hits
            hits = QTableWidgetItem(str(row.get("hits", 0)))
            hits.setTextAlignment(Qt.AlignCenter)
            hits.setForeground(QColor(c['yellow']))

            self._table.setItem(i, 0, n)
            self._table.setItem(i, 1, orig)
            self._table.setItem(i, 2, ar)
            self._table.setItem(i, 3, mdl)
            self._table.setItem(i, 4, hits)

        self._prev_btn.setEnabled(self._page > 0)
        self._next_btn.setEnabled(self._page < pages - 1)
        self._page_lbl.setText(
            f"صفحة {self._page + 1} / {pages}   •   {total:,} إجمالي"
        )
        self.status_message.emit(
            f"{len(rows)} صف  |  صفحة {self._page + 1}/{pages}  |  {total:,} إجمالي"
        )

    # ── Interaction ───────────────────────────────────────────────────────────

    def _game_changed(self, text: str):
        self._game  = text
        self._model = "All Models"
        self._page  = 0
        self._reload_model_combo()
        self._load_table()
        self._update_sync_btn()

    def _model_changed(self, text: str):
        self._model = text
        self._page  = 0
        self._load_table()

    def _do_search(self):
        self._page = 0
        self._load_table()

    def _clear_search(self):
        self._search_box.clear()
        self._search = ""
        self._page   = 0
        self._load_table()

    def _change_page(self, delta: int):
        self._page += delta
        self._load_table()

    def _on_selection(self):
        rows  = list({idx.row() for idx in self._table.selectedIndexes()})
        count = len(rows)
        self._btn_edit.setEnabled(count == 1)
        self._btn_retrans.setEnabled(count > 0 and self._engine is not None)
        self._btn_delete.setEnabled(count > 0)
        if count > 0:
            self._chip_sel.setText(f"{count} محدد")
            self._chip_sel.setVisible(True)
        else:
            self._chip_sel.setVisible(False)

    def _get_selected_entries(self) -> list:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        out  = []
        for r in rows:
            item = self._table.item(r, 2)
            if item:
                data = item.data(Qt.UserRole)
                if data:
                    out.append(data)
        return out

    def _edit_selected(self):
        entries = self._get_selected_entries()
        if len(entries) != 1:
            return
        entry = entries[0]
        game  = entry.get("game", self._game)
        dlg   = EditDialog(game, entry, self._cache, self)
        dlg.saved.connect(self._load_table)
        if dlg.exec():
            self.status_message.emit("✓  الترجمة حُفّظت")

    def _delete_selected(self):
        entries = self._get_selected_entries()
        if not entries:
            return
        n = len(entries)
        if QMessageBox.question(
            self, "تأكيد الحذف",
            f"حذف {n} {'عنصر' if n == 1 else 'عناصر'}؟\nلا يمكن التراجع.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        for e in entries:
            self._cache.delete_entry(e.get("game", self._game), e["original"])
        self._load_table()
        self._load_selectors()
        self.status_message.emit(f"✓  حُذف {n} {'عنصر' if n == 1 else 'عناصر'}")

    def _delete_all(self):
        game  = self._game
        if game == "All Games":
            msg = "حذف كل ترجمات جميع الألعاب؟\n\nهذا سيحذف كل قواعد البيانات."
        else:
            cnt = self._cache.count_entries(game)
            msg = f"حذف كل {cnt:,} ترجمة للعبة «{game}»؟"
        if QMessageBox.question(
            self, "تأكيد الحذف الكامل", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        if game == "All Games":
            self._cache.delete_all()
        else:
            self._cache.delete_game(game)
        self._game  = "All Games"
        self._page  = 0
        self.refresh()
        self.status_message.emit("✓  تم حذف الكاش")

    def _retranslate_selected(self):
        if not self._engine:
            QMessageBox.warning(self, "لا يوجد موديل",
                                "فعّل موديل الترجمة أولاً.")
            return
        entries = self._get_selected_entries()
        if not entries:
            return
        n = len(entries)
        if QMessageBox.question(
            self, "إعادة ترجمة",
            f"إعادة ترجمة {n} {'عنصر' if n == 1 else 'عناصر'} بالموديل النشط؟\n\n"
            "• التاغات والرموز محمية تلقائياً\n"
            "• الترجمة الحالية ستُستبدل",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return

        self._btn_retrans.setEnabled(False)
        self._prog_bar.setMaximum(n)
        self._prog_bar.setValue(0)
        self._prog_bar.setVisible(True)
        self._prog_lbl.setVisible(True)
        self._prog_lbl.setText(f"0/{n}")

        self._worker = RetranslateWorker(entries, self._engine, self._cache)
        self._worker.progress.connect(
            lambda d, t: (self._prog_bar.setValue(d),
                          self._prog_lbl.setText(f"{d}/{t}"))
        )
        self._worker.finished.connect(self._retrans_done)
        self._worker.start()

    def _retrans_done(self, done: int, failed: int):
        self._prog_bar.setVisible(False)
        self._prog_lbl.setVisible(False)
        self._btn_retrans.setEnabled(True)
        self._load_table()
        msg = f"✓  إعادة الترجمة: {done} نجح"
        if failed:
            msg += f"   ✗  {failed} فشل"
        self.status_message.emit(msg)

    # ── Sync ──────────────────────────────────────────────────────────────────

    def _update_sync_btn(self):
        visible = (self._game != "All Games" and self._has_wizard_config(self._game))
        self._btn_sync.setVisible(visible)

    def _has_wizard_config(self, game_id: str) -> bool:
        try:
            from games.translation_package import TranslationPackage
            w = TranslationPackage().get_wizard_config(game_id)
            return bool(w.get("output_base") and w.get("zen_version"))
        except Exception:
            return False

    def _do_sync(self):
        from games.translation_package import TranslationPackage
        wizard = TranslationPackage().get_wizard_config(self._game)
        if not wizard.get("output_base"):
            QMessageBox.warning(self, "إعداد مفقود",
                                "wizard config غير مكتمل — تحقق من package.json للعبة.")
            return
        dlg = SyncLogDialog(self._game, self._cache, wizard, self)
        dlg.exec()
