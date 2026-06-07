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
        # نستخدم ue_richtext: يحمي كل تاقات UE (<...>, </>, {...}) كتوكنات معتمة
        # بـ regex — أقوى من tag_filter العام الذي يفوّت الإغلاق العام </> و<i> inline.
        from engine import ue_richtext as ue

        # حدّد اسم المودل النشط الفعلي (مثل qwen2.5:14b) لا المفتاح (ollama)
        # كي نحفظ صفاً جديداً تحت هذا المودل بدون لمس صفوف المودلات الأخرى.
        active_model = "unknown"
        try:
            if self._engine:
                key = self._engine.get_active_model() or ""
                tr  = (self._engine.get_translator(key)
                       if hasattr(self._engine, "get_translator") else None)
                actual = getattr(tr, "model", None) if tr else None
                active_model = (actual or key or "unknown").strip() or "unknown"
        except Exception:
            pass

        import re as _re
        _AR = _re.compile(r'[؀-ۿ]')

        done = failed = skipped = 0
        total = len(self._entries)
        for i, entry in enumerate(self._entries):
            if self._stop:
                break
            orig = entry["original"]
            game = entry.get("game", "")
            # ⚠ حارس: لا تُترجم نصّاً مصدره عربي (= صف تالف). الترجمة عربي→عربي
            # تُنشئ صفّاً جديداً original_text عربي وتُفسد الكاش. تخطّاه.
            if _AR.search(orig or ""):
                skipped += 1
                self.progress.emit(i + 1, total)
                continue
            try:
                result = ue.translate(orig, self._engine)
                if result and result != orig:
                    if self._cache:
                        # cache.put يستخدم ON CONFLICT(original_text, model_used)
                        # → ينشئ صفاً جديداً لو المودل مختلف، أو يُحدّث صف هذا المودل فقط.
                        # ترجمات المودلات الأخرى لنفس النص تبقى سليمة.
                        self._cache.put(
                            game, orig, result,
                            model=active_model, mode_used="ue_richtext",
                        )
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

    def __init__(self, game_name: str, entry: dict, cache: TranslationCache,
                 parent=None, is_failed: bool = False, active_model: str = ""):
        from PySide6.QtWidgets import QDialog, QTextEdit
        from PySide6.QtGui     import QTextOption
        super().__init__(parent)

        self._dlg = QDialog(parent)
        # عنوان النافذة يدلّ على وضع التحرير (فاشلة → تصحيح، عادي → تعديل)
        self._dlg.setWindowTitle("تصحيح ترجمة فاشلة" if is_failed else "تعديل الترجمة")
        # حد أدنى مرن — يعمل على شاشات صغيرة + قابلية التكبير الكامل
        self._dlg.setMinimumSize(640, 500)
        self._dlg.resize(1040, 760)
        self._dlg.setSizeGripEnabled(True)
        # نضيف min/max بدون استبدال أعلام النافذة الافتراضية (يحافظ على زر X)
        self._dlg.setWindowFlags(
            self._dlg.windowFlags()
            | Qt.Window
            | Qt.WindowMinMaxButtonsHint
            | Qt.WindowCloseButtonHint
        )
        self._dlg.setModal(False)
        self._game        = game_name
        self._entry       = entry
        self._cache       = cache
        self._is_failed   = is_failed
        # المودل الذي يُحفظ تحته عند التصحيح:
        # 1) المودل المسجَّل مع الإدخال الفاشل  2) المودل النشط حالياً  3) "unknown"
        self._save_model  = (entry.get("model") or active_model or "unknown").strip() or "unknown"
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
        if is_failed:
            t = QLabel("🩹   تصحيح ترجمة فاشلة")
        else:
            t = QLabel("✏️   تعديل الترجمة")
        t.setObjectName("dialog_title")
        g = QLabel(f"اللعبة:  {game_name}")
        g.setStyleSheet(f"color: {c['muted']}; font-size: {theme.font_size - 1}px;")
        hl.addWidget(t)
        hl.addWidget(g)
        # في وضع تصحيح الفاشلة: اعرض المودل + سبب الفشل
        if is_failed:
            reason = entry.get("reason", "") or "—"
            model  = self._save_model
            info = QLabel(
                f"<span style='color:{c.get('teal', '#00d2ff')};'>المودل:</span> "
                f"<b>{model}</b>"
                f" &nbsp;&nbsp;|&nbsp;&nbsp; "
                f"<span style='color:{c.get('accent', '#e94560')};'>السبب:</span> "
                f"{reason[:120]}"
            )
            info.setStyleSheet(
                f"color: {c['muted']}; font-size: {theme.font_size - 1}px; padding-top: 2px;"
            )
            info.setTextFormat(Qt.RichText)
            info.setWordWrap(True)
            hl.addWidget(info)
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
        self._orig.setMinimumHeight(220)
        lp.addWidget(ll)
        lp.addWidget(self._orig, 1)   # يتمدّد عمودياً مع النافذة

        div = QFrame()
        div.setFrameShape(QFrame.VLine)
        div.setStyleSheet(f"color: {c['border']};")

        # Arabic (editable) — يبدأ بـ LTR، قابل للتبديل عبر زر 🔁
        rp = QVBoxLayout()
        rp.setSpacing(6)

        # Header: عنوان + زر تبديل الاتجاه
        rh = QHBoxLayout()
        rh.setContentsMargins(0, 0, 0, 0)
        rl = QLabel("🌐  الترجمة العربية — قابل للتعديل")
        rl.setObjectName("field_label")
        rh.addWidget(rl)
        rh.addStretch()

        self._trans_dir = "LTR"
        self._trans_dir_btn = QPushButton("🔁 LTR")
        self._trans_dir_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._trans_dir_btn.setToolTip(
            "تبديل اتجاه العرض:\n"
            "LTR: نص خام بترتيبه الفعلي\n"
            "RTL: BiDi كما يظهر باللعبة"
        )
        self._trans_dir_btn.setFixedHeight(22)
        self._trans_dir_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {c['muted']};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 2px 8px; font-size: 10px;
            }}
            QPushButton:hover {{ color: {c['accent']}; border-color: {c['accent']}; }}
        """)
        self._trans_dir_btn.clicked.connect(self._toggle_trans_direction)
        rh.addWidget(self._trans_dir_btn)

        self._trans = QTextEdit()
        self._trans.setLayoutDirection(Qt.LeftToRight)
        from PySide6.QtGui import QTextOption
        opt = QTextOption()
        opt.setTextDirection(Qt.LeftToRight)
        self._trans.document().setDefaultTextOption(opt)
        self._trans.setPlainText(self._normalize(entry.get("translated", "")))
        self._trans.setMinimumWidth(340)
        self._trans.setMinimumHeight(220)
        self._trans.setStyleSheet(f"""
            QTextEdit {{
                background-color: {c['card2']};
                border: 1px solid rgba(0,210,255,89);
                border-radius: 6px;
                color: {c['primary']};
                font-size: {theme.font_size}px;
                padding: 10px;
                selection-background-color: {c['selected']};
            }}
            QTextEdit:focus {{ border-color: {c['teal']}; }}
        """)
        rp.addLayout(rh)
        rp.addWidget(self._trans, 1)   # يتمدّد عمودياً مع النافذة

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

        # ── لفّ RTL مخصّص لهذا النص (يطغى على العام عند تطبيق Foundation) ──────
        from PySide6.QtWidgets import QSlider
        from engine import wrap_overrides
        _cur_ov = wrap_overrides.get(game_name, entry.get("original", ""), 0)
        fl.addSpacing(20)
        _wl = QLabel("لفّ RTL مخصّص:")
        _wl.setStyleSheet(f"color:{c['muted']};font-size:11px;background:transparent;border:none;")
        _wl.setToolTip("عدد أحرف اللفّ لهذا النص فقط (للصناديق الضيّقة). 0=استخدم العام.")
        self._wrap_slider = QSlider(Qt.Horizontal)
        self._wrap_slider.setLayoutDirection(Qt.LeftToRight)
        self._wrap_slider.setRange(0, 120)
        self._wrap_slider.setValue(_cur_ov)
        self._wrap_slider.setFixedWidth(130)
        self._wrap_lbl = QLabel("عام" if not _cur_ov else str(_cur_ov))
        self._wrap_lbl.setFixedWidth(40)
        self._wrap_lbl.setAlignment(Qt.AlignCenter)
        self._wrap_lbl.setStyleSheet(
            f"color:{c['primary']};font-weight:bold;font-size:12px;"
            f"background:rgba(0,0,0,45);border:1px solid {c['muted']};border-radius:5px;")
        self._wrap_slider.valueChanged.connect(
            lambda v: self._wrap_lbl.setText("عام" if not v else str(v)))
        fl.addWidget(_wl)
        fl.addWidget(self._wrap_slider)
        fl.addWidget(self._wrap_lbl)

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
        # ⚠ لا نحذف المسافات المتعمَّدة (مهمّة لتباعد أجزاء الجمل المركّبة في RTL).
        # نطبّع \n → سطر فعلي فقط، ونرفض الفارغ تماماً (مسافات فقط).
        raw = self._normalize(self._trans.toPlainText())
        if not raw.strip() or not self._cache:
            return
        original = self._entry["original"]
        if self._is_failed:
            # تحويل الإدخال الفاشل إلى نجاح:
            # 1) أدخله في جدول الترجمات تحت المودل الذي فشل (أو النشط)
            # 2) أزله من جدول الفاشلة حتى لا يُرفَض مستقبلاً
            try:
                self._cache.put(self._game, original, raw,
                                model=self._save_model, mode_used="manual")
            except Exception:
                # fallback إذا فشل put لأي سبب — على الأقل أزل من الفاشلة
                pass
            try:
                self._cache.delete_failed(self._game, original)
            except Exception:
                pass
        else:
            self._cache.update_translation(self._game, original, raw)
        # احفظ لفّ RTL المخصّص لهذا النص (0=استخدم العام)
        try:
            from engine import wrap_overrides
            wrap_overrides.set_override(self._game, original, self._wrap_slider.value())
        except Exception:
            pass
        self.saved.emit()
        self._dlg.accept()

    def _toggle_trans_direction(self):
        """يبدّل اتجاه عرض حقل تعديل الترجمة بين LTR و RTL."""
        from PySide6.QtGui import QTextOption
        self._trans_dir = "RTL" if self._trans_dir == "LTR" else "LTR"
        self._trans_dir_btn.setText(f"🔁 {self._trans_dir}")
        qt_dir = Qt.RightToLeft if self._trans_dir == "RTL" else Qt.LeftToRight
        self._trans.setLayoutDirection(qt_dir)
        opt = QTextOption()
        opt.setTextDirection(qt_dir)
        self._trans.document().setDefaultTextOption(opt)

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
        self._view    = "translated"   # "translated" أو "failed"
        self._search  = ""
        self._exact_match = False     # بحث LIKE افتراضي؛ True = مطابقة تامة
        self._health_filter = ""      # ""|"broken"|"manual"|"preferred"|"conflict"
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
        lay.addWidget(self._build_filter_chips())
        lay.addWidget(self._build_table(), 1)
        lay.addWidget(self._build_pagebar())

    def _build_filter_chips(self) -> QFrame:
        """شريط فلاتر سريعة فوق الجدول — chips قابلة للنقر."""
        c = theme.c
        bar = QFrame()
        bar.setObjectName("filter_chips")
        bar.setStyleSheet(f"""
            QFrame#filter_chips {{
                background: {c.get('surface', c['card'])};
                border-bottom: 1px solid {c['border']};
            }}
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 6, 16, 6)
        lay.setSpacing(6)

        hint = QLabel("فلتر سريع:")
        hint.setStyleSheet(
            f"color: {c['muted']}; font-size: 11px;"
            " background: transparent; border: none;"
        )
        lay.addWidget(hint)

        # تعريف الـ chips: (key, label, tooltip, color)
        ACCENT = c.get('accent', '#e94560')
        chip_defs = [
            ("",          "الكل",         "إظهار كل الترجمات", c.get('primary', '#fff')),
            ("broken",    "⚠ معطوبة",     "تاقات مكسورة — تحتاج إعادة ترجمة", c.get('accent', '#e94560')),
            ("manual",    "🩹 يدوية",     "تصحيحات يدوية (mode_used='manual')", c.get('teal', '#00d2ff')),
            ("preferred", "🏆 مفضّلة",    "ترجمات حدّدتها يدوياً كأفضل (is_preferred=1)", c.get('yellow', '#f0c14b')),
            ("conflict",  "🔀 تعارض",    "نصوص لها ترجمات من مودلات متعدّدة", c.get('green', '#19c37d')),
        ]

        self._chip_buttons: dict[str, QPushButton] = {}
        for key, label, tip, color in chip_defs:
            btn = QPushButton(label)
            btn.setObjectName("filter_chip")
            btn.setCheckable(True)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setToolTip(tip)
            btn.setStyleSheet(f"""
                QPushButton#filter_chip {{
                    background: {c.get('card2', c['card'])};
                    color: {c['muted']};
                    border: 1px solid {c['border']};
                    border-radius: 12px;
                    padding: 3px 12px;
                    font-size: 11px;
                }}
                QPushButton#filter_chip:hover {{ border-color: {color}; }}
                QPushButton#filter_chip:checked {{
                    background: {color}; color: white;
                    border-color: {color}; font-weight: bold;
                }}
            """)
            btn.toggled.connect(lambda checked, k=key: self._on_chip_toggled(k, checked))
            self._chip_buttons[key] = btn
            lay.addWidget(btn)

        # الـ chip الافتراضي = "الكل"
        self._chip_buttons[""].setChecked(True)
        lay.addStretch()
        return bar

    def _on_chip_toggled(self, key: str, checked: bool):
        """يتعامل مع نقر chip — يضمن واحد فقط محدّد في كل مرة."""
        if not checked:
            # المستخدم ألغى تحديد الـ chip الحالي — رجوع للكل
            if self._health_filter == key:
                self._chip_buttons[""].blockSignals(True)
                self._chip_buttons[""].setChecked(True)
                self._chip_buttons[""].blockSignals(False)
                self._health_filter = ""
                self._page = 0
                self._load_table()
            return
        # ألغِ كل الباقي
        for k, btn in self._chip_buttons.items():
            if k != key:
                btn.blockSignals(True)
                btn.setChecked(False)
                btn.blockSignals(False)
        self._health_filter = key
        self._page = 0
        self._load_table()

    def _build_topbar(self) -> QFrame:
        bar, lay = make_topbar("💾", "ذاكرة الترجمة")

        self._chip_total  = self._chip("0 ترجمة", "blue")
        self._chip_games  = self._chip("0 لعبة",  "green")
        self._chip_failed = self._chip("0 فاشل",  "accent")
        self._chip_failed.setToolTip("نصوص فشل المحرّك في ترجمتها — انقر زر 'فاشل' في الشريط لعرضها")
        self._chip_sel    = self._chip("0 محدد", "accent")
        self._chip_sel.setVisible(False)

        for ch in (self._chip_total, self._chip_games, self._chip_failed, self._chip_sel):
            lay.addWidget(ch)

        # زر قائمة المنع — منقول لـ topbar (إجراء عام، ليس مرتبطاً بتحديد صف)
        self._btn_skip_manage = QPushButton("📋  قائمة المنع")
        self._btn_skip_manage.setObjectName("btn_secondary")
        self._btn_skip_manage.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_skip_manage.setToolTip(
            "إدارة قائمة المنع — النصوص المطابقة لا تُرسل لـ Ollama\n"
            "وتُستَبعَد عند تصدير translations.txt → تبقى بالإنجليزية في اللعبة"
        )
        self._btn_skip_manage.clicked.connect(self._open_skip_manager)
        lay.addWidget(self._btn_skip_manage)

        # زر تحديث — منقول من toolbar لتوفير مساحة لأزرار التحديد
        ref_btn = QPushButton("↻  تحديث")
        ref_btn.setObjectName("btn_secondary")
        ref_btn.setToolTip("تحديث قائمة الألعاب والإحصائيات")
        ref_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        ref_btn.clicked.connect(self.refresh)
        lay.addWidget(ref_btn)
        # ملاحظة: للتطبيق الفوري على اللعبة استخدم زر "تحديث الترجمات" في صفحة
        # اللعبة — ArabicFontFixer v3.1.8+ يكتشف translations.txt تلقائياً
        # ويطبّق التغييرات على TMP الظاهرة بدون إعادة تشغيل.

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
        self._game_combo.setMinimumWidth(120)
        self._game_combo.setMaximumWidth(160)
        self._game_combo.currentTextChanged.connect(self._game_changed)
        theme.style_combo(self._game_combo)
        lay.addWidget(game_lbl)
        lay.addWidget(self._game_combo)
        lay.addSpacing(8)

        # Model selector
        model_lbl = QLabel("الموديل:")
        model_lbl.setStyleSheet(f"color: {c['muted']}; font-size: {theme.font_size - 1}px;")
        self._model_combo = QComboBox()
        self._model_combo.setMinimumWidth(110)
        self._model_combo.setMaximumWidth(150)
        self._model_combo.currentTextChanged.connect(self._model_changed)
        theme.style_combo(self._model_combo)
        lay.addWidget(model_lbl)
        lay.addWidget(self._model_combo)
        lay.addSpacing(12)

        # View toggle: translated / failed
        self._btn_view_translated = QPushButton("✅  مترجَم")
        self._btn_view_failed     = QPushButton("❌  فاشل")
        for b in (self._btn_view_translated, self._btn_view_failed):
            b.setCheckable(True)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            b.setFixedHeight(28)
        self._btn_view_translated.setChecked(True)
        self._btn_view_translated.setToolTip("عرض الترجمات الناجحة")
        self._btn_view_failed.setToolTip("عرض النصوص التي فشل المحرّك في ترجمتها مع سبب الفشل")
        self._btn_view_translated.clicked.connect(lambda: self._switch_view("translated"))
        self._btn_view_failed.clicked.connect(lambda: self._switch_view("failed"))
        view_style = (
            f"QPushButton {{ background: transparent; color: {c['muted']};"
            f"               border: 1px solid {c['border']}; border-radius: 4px;"
            f"               padding: 4px 10px; font-size: 11px; }}"
            f"QPushButton:checked {{ background: {c['primary']}; color: white;"
            f"                       border-color: {c['primary']}; }}"
            f"QPushButton:hover:!checked {{ color: {c['primary']}; }}"
        )
        self._btn_view_translated.setStyleSheet(view_style)
        self._btn_view_failed.setStyleSheet(view_style)
        lay.addWidget(self._btn_view_translated)
        lay.addWidget(self._btn_view_failed)
        lay.addSpacing(12)

        # Search — stretches to fill remaining space
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("🔍  ابحث... (English أو عربي)")
        self._search_box.setMinimumWidth(150)
        self._search_box.textChanged.connect(lambda t: (
            setattr(self, '_search', t.strip()),
            self._search_timer.start(320)
        ))
        lay.addWidget(self._search_box, 1)

        # زر التبديل: بحث جزئي ⇄ مطابقة تامة
        c = theme.c
        self._exact_btn = QPushButton("≈")
        self._exact_btn.setObjectName("icon_btn")
        self._exact_btn.setCheckable(True)
        self._exact_btn.setFixedSize(28, 28)
        self._exact_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._exact_btn.setToolTip(
            "بحث جزئي (الافتراضي): ‘NO’ يطابق Cannot، No one، …\n"
            "مطابقة تامة (مفعّل): ‘NO’ يطابق ‘NO’ فقط (case-insensitive)"
        )
        self._exact_btn.setStyleSheet(f"""
            QPushButton#icon_btn {{ font-size: 14px; font-weight: bold; }}
            QPushButton#icon_btn:checked {{
                background: {c['accent']}; color: white;
                border: 1px solid {c['accent']};
            }}
        """)

        def _toggle_exact(checked: bool):
            self._exact_match = bool(checked)
            self._exact_btn.setText("=" if checked else "≈")
            self._page = 0
            self._load_table()

        self._exact_btn.toggled.connect(_toggle_exact)
        lay.addWidget(self._exact_btn)

        clr = QPushButton("✕")
        clr.setObjectName("icon_btn")
        clr.setFixedSize(28, 28)
        clr.clicked.connect(self._clear_search)
        lay.addWidget(clr)

        lay.addSpacing(8)

        # ملاحظة: زر "↻ تحديث" نُقل إلى topbar بجانب "حذف الكل" — لتوفير مساحة
        # لأزرار التحديد (منع، اكتشف التاقات) كي لا تتداخل.

        # Sync button (visible only for IoStore games with wizard config)
        self._btn_sync = QPushButton("🔄  مزامنة التعديل")
        self._btn_sync.setObjectName("btn_info")
        self._btn_sync.setVisible(False)
        self._btn_sync.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_sync.setToolTip("تطبيق كل ترجمات الكاش على ملفات اللعبة وبناء الحزمة")
        self._btn_sync.clicked.connect(self._do_sync)
        lay.addWidget(self._btn_sync)

        # أزرار التحديد (مرئية عند تحديد صفوف) — نص + أيقونة للوضوح
        # ملاحظة: 📋 (قائمة المنع) منقول لـ topbar الآن
        self._btn_skip_add = QPushButton("🚫  منع")
        self._btn_skip_add.setObjectName("btn_secondary")
        self._btn_skip_add.setVisible(False)
        self._btn_skip_add.setEnabled(False)
        self._btn_skip_add.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_skip_add.setToolTip(
            "إضافة النصوص المحدَّدة إلى قائمة المنع\n"
            "→ لن تُرسل لـ Ollama\n"
            "→ تُستَبعَد من translations.txt → تبقى بالإنجليزية"
        )
        self._btn_skip_add.clicked.connect(self._add_selected_to_skip)
        lay.addWidget(self._btn_skip_add)

        self._btn_tag_detect = QPushButton("🏷  التاقات")
        self._btn_tag_detect.setObjectName("btn_secondary")
        self._btn_tag_detect.setVisible(False)
        self._btn_tag_detect.setEnabled(False)
        self._btn_tag_detect.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_tag_detect.setToolTip(
            "اكتشف XML/HTML tags من النصوص المحدَّدة\n"
            "(مثل <itemName .../> و <characterName .../>)\n"
            "→ يفتح حواراً لإضافتها لقائمة الحماية"
        )
        self._btn_tag_detect.clicked.connect(self._detect_tags_from_selection)
        lay.addWidget(self._btn_tag_detect)
        lay.addSpacing(8)

        # أزرار الإجراء الرئيسية — نص كامل بالعربي
        self._btn_edit    = QPushButton("✏️  تعديل")
        self._btn_edit.setObjectName("btn_secondary")
        self._btn_edit.setEnabled(False)

        self._btn_retrans = QPushButton("🔄  إعادة ترجمة")
        self._btn_retrans.setObjectName("btn_info")
        self._btn_retrans.setEnabled(False)

        self._btn_delete  = QPushButton("🗑  حذف")
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
        self._table.setColumnCount(6)
        # الأعمدة: #  الحالة  إنجليزي  عربي  المودل  ع.مودلات
        self._table.setHorizontalHeaderLabels(
            ["#", "✓", "إنجليزي", "عربي", "المودل", "🔀"]
        )
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setShowGrid(True)
        self._table.verticalHeader().setVisible(False)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)   # #
        hdr.setSectionResizeMode(1, QHeaderView.Fixed)   # ✓ صحة
        hdr.setSectionResizeMode(2, QHeaderView.Stretch) # إنجليزي
        hdr.setSectionResizeMode(3, QHeaderView.Stretch) # عربي
        hdr.setSectionResizeMode(4, QHeaderView.Fixed)   # المودل
        hdr.setSectionResizeMode(5, QHeaderView.Fixed)   # 🔀 عدد المودلات
        self._table.setColumnWidth(0, 55)
        self._table.setColumnWidth(1, 36)
        self._table.setColumnWidth(4, 180)               # أوسع — يستوعب translategemma:12b
        self._table.setColumnWidth(5, 48)
        self._table.verticalHeader().setDefaultSectionSize(36)

        # tooltips للعناوين
        self._table.horizontalHeaderItem(1).setToolTip(
            "حالة الترجمة:\n"
            "✓ سليمة  |  ⚠ تاقات معطوبة  |  🩹 تصحيح يدوي  |  🏆 مفضّلة"
        )
        self._table.horizontalHeaderItem(5).setToolTip(
            "عدد المودلات التي ترجمت نفس النص — 1 = مودل واحد فقط، >1 = ترجمات متعدّدة (قارنها)"
        )

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

        # ترتيب الأسهم بالضبط كما طلب المستخدم — السهم يلامس الكلمة من الداخل:
        #   • السابق:  →  السابق   (السهم على يسار الكلمة)
        #   • التالي:  التالي  ←   (السهم على يمين الكلمة)
        self._prev_btn = QPushButton("→  السابق")
        self._prev_btn.setObjectName("btn_secondary")
        self._prev_btn.setLayoutDirection(Qt.LeftToRight)
        self._prev_btn.clicked.connect(lambda: self._change_page(-1))

        self._next_btn = QPushButton("التالي  ←")
        self._next_btn.setObjectName("btn_secondary")
        self._next_btn.setLayoutDirection(Qt.LeftToRight)
        self._next_btn.clicked.connect(lambda: self._change_page(1))

        self._page_lbl = QLabel("")
        self._page_lbl.setObjectName("statusbar_text")

        # اختيار حجم الصفحة
        c = theme.c
        size_lbl = QLabel("لكل صفحة:")
        size_lbl.setStyleSheet(
            f"color: {c['muted']}; font-size: 11px; background: transparent; border: none;"
        )
        self._page_size_combo = QComboBox()
        self._page_size_combo.setFixedHeight(26)
        for s in (60, 100, 200, 500):
            self._page_size_combo.addItem(str(s), s)
        self._page_size_combo.setCurrentIndex(0)
        self._page_size_combo.setStyleSheet(f"""
            QComboBox {{
                background: {c.get('card2', c['card'])}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 2px 8px; font-size: 11px; min-width: 70px;
            }}
        """)
        def _on_size_changed(_i: int):
            new = self._page_size_combo.currentData()
            if new and new != self.PAGE_SIZE:
                self.PAGE_SIZE = int(new)
                self._page = 0
                self._load_table()
        self._page_size_combo.currentIndexChanged.connect(_on_size_changed)

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
        lay.addWidget(size_lbl)
        lay.addWidget(self._page_size_combo)
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

    def refresh_theme(self):
        theme.style_combo(self._game_combo)
        theme.style_combo(self._model_combo)
        self._load_table()

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

        total_all  = sum(self._cache.count_entries(g) for g in games) if self._cache else 0
        failed_all = sum(self._cache.count_failed(g) for g in games) if self._cache else 0
        self._chip_total.setText(f"{total_all:,} ترجمة")
        self._chip_games.setText(f"{len(games)} لعبة")
        self._chip_failed.setText(f"{failed_all:,} فاشل")
        # نُلوّن الشريحة بلون التحذير عند وجود فاشلة
        self._chip_failed.setVisible(failed_all > 0)

        self._reload_model_combo()

    def _switch_view(self, view: str):
        if view == self._view:
            # حافظ على حالة الزر المُحدَّد
            self._btn_view_translated.setChecked(self._view == "translated")
            self._btn_view_failed.setChecked(self._view == "failed")
            return
        self._view = view
        self._btn_view_translated.setChecked(view == "translated")
        self._btn_view_failed.setChecked(view == "failed")
        self._page = 0
        # غيّر رؤوس الجدول حسب العرض
        if view == "failed":
            self._table.setColumnCount(4)
            self._table.setHorizontalHeaderLabels(["#", "إنجليزي", "سبب الفشل", "التاريخ"])
            hdr = self._table.horizontalHeader()
            hdr.setSectionResizeMode(0, QHeaderView.Fixed)
            hdr.setSectionResizeMode(1, QHeaderView.Stretch)
            hdr.setSectionResizeMode(2, QHeaderView.Stretch)
            hdr.setSectionResizeMode(3, QHeaderView.Fixed)
            self._table.setColumnWidth(3, 140)
            self._btn_retrans.setText("🔄  أعد المحاولة")
            self._btn_retrans.setToolTip("احذف من جدول الفاشلة → سيُستدعى الـ AI مرة أخرى عند الطلب التالي")
            # في عرض الفاشلة: زر التعديل يصبح "تصحيح يدوي" (يحفظ تحت المودل الفاشل)
            self._btn_edit.setText("🩹  تصحيح يدوي")
            self._btn_edit.setToolTip(
                "اكتب ترجمة عربية يدوياً — ستُحفظ تحت نفس المودل الذي فشل،\n"
                "وتُزال من قائمة الفاشلة."
            )
            self._btn_skip_manage.setVisible(True)
            self._btn_skip_add.setVisible(False)
            self._btn_tag_detect.setVisible(False)
        else:
            # عرض المترجَم — 6 أعمدة الجديدة
            self._btn_skip_manage.setVisible(True)
            self._btn_skip_add.setVisible(False)
            self._btn_tag_detect.setVisible(False)
            self._btn_edit.setText("✏️  تعديل")
            self._btn_edit.setToolTip("")
            self._table.setColumnCount(6)
            self._table.setHorizontalHeaderLabels(
                ["#", "✓", "إنجليزي", "عربي", "المودل", "🔀"]
            )
            hdr = self._table.horizontalHeader()
            hdr.setSectionResizeMode(0, QHeaderView.Fixed)
            hdr.setSectionResizeMode(1, QHeaderView.Fixed)
            hdr.setSectionResizeMode(2, QHeaderView.Stretch)
            hdr.setSectionResizeMode(3, QHeaderView.Stretch)
            hdr.setSectionResizeMode(4, QHeaderView.Fixed)
            hdr.setSectionResizeMode(5, QHeaderView.Fixed)
            self._table.setColumnWidth(1, 36)
            self._table.setColumnWidth(4, 180)
            self._table.setColumnWidth(5, 48)
            self._btn_retrans.setText("🔄  إعادة ترجمة")
            self._btn_retrans.setToolTip("")
        self._load_table()

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
        if self._view == "failed":
            self._load_failed_table()
            return
        c = theme.c

        model_f = "" if self._model == "All Models" else self._model
        games   = (self._cache.get_all_games()
                   if self._game == "All Games"
                   else [self._game])

        # فلتر "معطوبة" يتطلّب فحص كل الصفوف (regex على المحتوى) — مسار خاص
        if self._health_filter == "broken":
            from engine.tag_health import is_broken_translation
            broken_rows: list = []
            for g in games:
                for r in self._cache.iter_all_for_broken_check(
                    g, self._search, model_f, exact_match=self._exact_match
                ):
                    if is_broken_translation(r["original"], r["translated"]):
                        broken_rows.append({"game": g, **r})
            total = len(broken_rows)
            self._total = total
            pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
            self._page = max(0, min(self._page, pages - 1))
            start = self._page * self.PAGE_SIZE
            rows = broken_rows[start:start + self.PAGE_SIZE]
        else:
            total = sum(
                self._cache.count_entries(g, self._search, model_f,
                                          exact_match=self._exact_match,
                                          health_filter=self._health_filter)
                for g in games
            )
            self._total = total
            pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
            self._page  = max(0, min(self._page, pages - 1))

            rows, quota, skip = [], self.PAGE_SIZE, self._page * self.PAGE_SIZE
            for g in games:
                if quota <= 0:
                    break
                g_total = self._cache.count_entries(
                    g, self._search, model_f,
                    exact_match=self._exact_match,
                    health_filter=self._health_filter,
                )
                if skip >= g_total:
                    skip -= g_total
                    continue
                batch = self._cache.get_page(
                    g, skip, quota, self._search, model_f,
                    exact_match=self._exact_match,
                    health_filter=self._health_filter,
                )
                for row in batch:
                    rows.append({"game": g, **row})
                quota -= len(batch)
                skip = 0

        self._table.setRowCount(0)
        self._table.setRowCount(len(rows))
        offset = self._page * self.PAGE_SIZE

        # كاشف الصحة + خريطة عدد المودلات (نحسبها دفعة واحدة لتجنّب الاستعلامات الـ N)
        from engine.tag_health import is_broken_translation
        model_counts: dict[tuple[str, str], int] = {}
        try:
            unique_pairs = {(r["game"], r["original"]) for r in rows}
            for g, orig in unique_pairs:
                conn = self._cache._get_conn(g)
                cnt = conn.execute(
                    "SELECT COUNT(DISTINCT model_used) FROM translations "
                    "WHERE original_text = ?",
                    (orig,)
                ).fetchone()[0]
                model_counts[(g, orig)] = int(cnt or 0)
        except Exception:
            pass

        for i, row in enumerate(rows):
            # # — الرقم التسلسلي
            n = QTableWidgetItem(str(offset + i + 1))
            n.setTextAlignment(Qt.AlignCenter)
            n.setForeground(QColor(c['muted']))

            # ✓ — مؤشّر الصحة
            mode = (row.get("mode_used") or "").lower()
            is_preferred = bool(row.get("is_preferred"))
            broken = is_broken_translation(row["original"], row["translated"])
            if is_preferred:
                icon, tip, color = "🏆", "مفضّلة (اختيار يدوي)", c.get('yellow', '#f0c14b')
            elif mode == "manual":
                icon, tip, color = "🩹", "تصحيح يدوي", c.get('teal', '#00d2ff')
            elif broken:
                icon, tip, color = "⚠", "تاقات معطوبة — تحتاج إعادة ترجمة", c.get('accent', '#e94560')
            else:
                icon, tip, color = "✓", "ترجمة سليمة", c.get('success', '#19c37d')
            health = QTableWidgetItem(icon)
            health.setTextAlignment(Qt.AlignCenter)
            health.setForeground(QColor(color))
            health.setToolTip(tip)

            # إنجليزي
            orig = QTableWidgetItem(row["original"].replace("\\n", " ↵ ").replace("\n", " ↵ "))
            orig.setForeground(QColor(c['primary']))

            # عربي — محاذاة يمين
            ar = QTableWidgetItem(row["translated"].replace("\\n", " ↵ ").replace("\n", " ↵ "))
            ar.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            ar.setForeground(QColor(c['teal']))
            ar.setData(Qt.UserRole, row)   # نخزّن الصف الكامل

            # المودل — اسم كامل + tooltip
            model_name = row.get("model", "") or "—"
            mdl = QTableWidgetItem(model_name)
            mdl.setForeground(QColor(c['muted']))
            mdl.setFont(QFont("Consolas", theme.font_size - 2))
            mdl.setToolTip(model_name)

            # 🔀 — عدد المودلات التي ترجمت هذا النص
            mc = model_counts.get((row["game"], row["original"]), 1)
            mcount = QTableWidgetItem(str(mc))
            mcount.setTextAlignment(Qt.AlignCenter)
            if mc > 1:
                mcount.setForeground(QColor(c.get('yellow', '#f0c14b')))
                mcount.setToolTip(f"{mc} مودلات ترجمت هذا النص — انقر مرتين لمقارنتها")
            else:
                mcount.setForeground(QColor(c['muted']))
                mcount.setToolTip("مودل واحد فقط")

            self._table.setItem(i, 0, n)
            self._table.setItem(i, 1, health)
            self._table.setItem(i, 2, orig)
            self._table.setItem(i, 3, ar)
            self._table.setItem(i, 4, mdl)
            self._table.setItem(i, 5, mcount)

        self._prev_btn.setEnabled(self._page > 0)
        self._next_btn.setEnabled(self._page < pages - 1)
        self._page_lbl.setText(
            f"صفحة {self._page + 1} / {pages}   •   {total:,} إجمالي"
        )
        self.status_message.emit(
            f"{len(rows)} صف  |  صفحة {self._page + 1}/{pages}  |  {total:,} إجمالي"
        )

    def _load_failed_table(self):
        """يملأ الجدول بالنصوص الفاشلة + سبب فشلها."""
        c = theme.c
        games = (self._cache.get_all_games()
                 if self._game == "All Games"
                 else [self._game])
        total = sum(self._cache.count_failed(g, self._search,
                                              exact_match=self._exact_match)
                    for g in games)
        self._total = total
        pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self._page = max(0, min(self._page, pages - 1))

        rows, quota, skip = [], self.PAGE_SIZE, self._page * self.PAGE_SIZE
        for g in games:
            if quota <= 0:
                break
            g_total = self._cache.count_failed(g, self._search,
                                                exact_match=self._exact_match)
            if skip >= g_total:
                skip -= g_total
                continue
            batch = self._cache.get_failed_page(g, skip, quota, self._search,
                                                 exact_match=self._exact_match)
            for r in batch:
                rows.append({"game": g, **r})
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
            orig.setForeground(QColor(c['primary']))
            orig.setData(Qt.UserRole, row)

            # سبب الفشل (مُلوَّن حسب النوع)
            reason = row.get("reason", "") or "(بلا سبب)"
            reason_item = QTableWidgetItem(reason)
            reason_item.setForeground(QColor(self._reason_color(reason)))
            reason_item.setToolTip(reason)

            # التاريخ
            dt = QTableWidgetItem(str(row.get("created_at", ""))[:19])
            dt.setForeground(QColor(c['muted']))
            dt.setFont(QFont("Consolas", theme.font_size - 2))
            dt.setTextAlignment(Qt.AlignCenter)

            self._table.setItem(i, 0, n)
            self._table.setItem(i, 1, orig)
            self._table.setItem(i, 2, reason_item)
            self._table.setItem(i, 3, dt)

        self._prev_btn.setEnabled(self._page > 0)
        self._next_btn.setEnabled(self._page < pages - 1)
        self._page_lbl.setText(
            f"صفحة {self._page + 1} / {pages}   •   {total:,} فاشل"
        )
        self.status_message.emit(
            f"{len(rows)} صف فاشل  |  صفحة {self._page + 1}/{pages}  |  {total:,} إجمالي"
        )

    @staticmethod
    def _reason_color(reason: str) -> str:
        """يُرجع لوناً يدل على نوع السبب."""
        c = theme.c
        r = reason.lower()
        if "timeout" in r or "مهلة" in reason:
            return c.get("accent", "#e94560")
        if "unchanged" in r or "النموذج أعاد" in reason or "identity" in r:
            return c.get("yellow", "#ffa600")
        if "رفض" in reason or "refusal" in r or "هلوسة" in reason or "غير صالح" in reason:
            return c.get("accent", "#e94560")
        if "connection" in r or "اتصال" in reason:
            return c.get("accent", "#e94560")
        return c.get("muted", "#8a8a8a")

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
        # في وضع failed: التعديل = "تصحيح يدوي" (يحوّل الفشل → نجاح تحت المودل الفاشل)
        if self._view == "failed":
            self._btn_edit.setEnabled(count == 1)
            self._btn_retrans.setEnabled(count > 0)
        else:
            self._btn_edit.setEnabled(count == 1)
            self._btn_retrans.setEnabled(count > 0 and self._engine is not None)
        # زر "منع" يظهر مع تحديد في كلا العرضين (مترجم + فاشل)
        self._btn_skip_add.setVisible(count > 0)
        self._btn_skip_add.setEnabled(count > 0)
        if count > 0:
            self._btn_skip_add.setText(f"🚫  منع ({count})" if count > 1 else "🚫  منع")
        else:
            self._btn_skip_add.setText("🚫  منع")

        # زر "اكتشف التاقات" يظهر مع تحديد في كلا العرضين
        self._btn_tag_detect.setVisible(count > 0)
        self._btn_tag_detect.setEnabled(count > 0)
        if count > 0:
            self._btn_tag_detect.setText(
                f"🏷  اكتشف التاقات ({count})" if count > 1 else "🏷  اكتشف التاقات"
            )
        else:
            self._btn_tag_detect.setText("🏷  اكتشف التاقات")
        self._btn_delete.setEnabled(count > 0)
        if count > 0:
            self._chip_sel.setText(f"{count} محدد")
            self._chip_sel.setVisible(True)
        else:
            self._chip_sel.setVisible(False)

    def _get_selected_entries(self) -> list:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        # عمود الـ UserRole مختلف بين العرضين
        # عرض المترجَم: العمود 3 (عربي) يحوي UserRole مع الصف الكامل
        # عرض الفاشل:  العمود 1 (إنجليزي) يحوي UserRole
        data_col = 1 if self._view == "failed" else 3
        out  = []
        for r in rows:
            item = self._table.item(r, data_col)
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
        is_failed = (self._view == "failed")
        # اسم المودل الفعلي (مثل qwen2.5:14b) لا المفتاح (مثل ollama)
        # — fallback إذا الإدخال الفاشل قديم بلا model مسجَّل
        active_model = ""
        if self._engine:
            try:
                key = self._engine.get_active_model() or ""
                tr  = self._engine.get_translator(key) if key else None
                # OllamaTranslator يحفظ الاسم الحقيقي في .model
                actual = getattr(tr, "model", None) if tr else None
                active_model = actual or key
            except Exception:
                active_model = ""
        # نخزّن المرجع لتجنّب تجميع القمامة، ونفتح بـ show() بدل exec()
        # حتى لا يحجب الصفحة الرئيسية ولا حواراً آخر
        if not hasattr(self, "_open_edit_dialogs"):
            self._open_edit_dialogs = []
        dlg = EditDialog(
            game, entry, self._cache, self,
            is_failed=is_failed, active_model=active_model,
        )
        dlg.saved.connect(self._load_table)
        # رسالة الحالة تختلف بين تعديل وتصحيح
        if is_failed:
            dlg.saved.connect(lambda: self.status_message.emit(
                "✓  تم التصحيح اليدوي وحُفظ في كاش الترجمات"
            ))
            # حدّث الإحصاءات (عدد الفاشلة نقص)
            dlg.saved.connect(self._load_selectors)
        else:
            dlg.saved.connect(lambda: self.status_message.emit("✓  الترجمة حُفّظت"))
        # احذف المرجع عند الإغلاق
        dlg._dlg.finished.connect(lambda _r, d=dlg: self._open_edit_dialogs.remove(d) if d in self._open_edit_dialogs else None)
        self._open_edit_dialogs.append(dlg)
        dlg._dlg.show()
        dlg._dlg.raise_()
        dlg._dlg.activateWindow()

    def _delete_selected(self):
        entries = self._get_selected_entries()
        if not entries:
            return
        n = len(entries)
        what = "إدخال فاشل" if self._view == "failed" else "عنصر"
        if QMessageBox.question(
            self, "تأكيد الحذف",
            f"حذف {n} {what}{'' if n == 1 else 'اً'}؟\nلا يمكن التراجع.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        for e in entries:
            if self._view == "failed":
                self._cache.delete_failed(e.get("game", self._game), e["original"])
            else:
                self._cache.delete_entry(e.get("game", self._game), e["original"])
        self._load_table()
        self._load_selectors()
        self.status_message.emit(f"✓  حُذف {n}")

    def _delete_all(self):
        game  = self._game
        model = self._model   # "All Models"  أو اسم موديل محدد

        # ── بناء رسالة التأكيد حسب الفلاتر الحالية ──────────────────────
        games_list = (self._cache.get_all_games()
                      if game == "All Games" else [game])

        if model == "All Models":
            total = sum(self._cache.count_entries(g) for g in games_list)
            if game == "All Games":
                msg = f"حذف كل {total:,} ترجمة من جميع الألعاب؟"
            else:
                msg = f"حذف كل {total:,} ترجمة للعبة «{game}»؟"
        else:
            total = sum(
                self._cache.count_entries(g, model_filter=model)
                for g in games_list
            )
            if game == "All Games":
                msg = f"حذف {total:,} ترجمة للموديل «{model}» من جميع الألعاب؟"
            else:
                msg = f"حذف {total:,} ترجمة للموديل «{model}» في لعبة «{game}»؟"

        if total == 0:
            if game != "All Games":
                reply = QMessageBox.question(
                    self, "قاعدة البيانات فارغة",
                    f"اللعبة «{game}» لا تحتوي على ترجمات.\n"
                    "هل تريد إزالتها من قائمة الكاش نهائياً؟",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    self._cache.delete_game(game)
                    self._game = "All Games"
                    self._page = 0
                    self.refresh()
                    self.status_message.emit(f"✓  تم حذف «{game}» من الكاش")
            else:
                QMessageBox.information(self, "لا يوجد شيء", "لا توجد ترجمات مطابقة للحذف.")
            return

        if QMessageBox.question(
            self, "تأكيد الحذف", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return

        # ── تنفيذ الحذف ──────────────────────────────────────────────────
        for g in games_list:
            if model == "All Models":
                self._cache.delete_game(g)   # يمسح البيانات ويحذف الملف
            else:
                self._cache.delete_by_model(g, model)

        if game != "All Games":
            self._game = "All Games"
        self._page = 0
        self.refresh()
        self.status_message.emit("✓  تم حذف الكاش")

    def _retranslate_selected(self):
        entries = self._get_selected_entries()
        if not entries:
            return
        n = len(entries)

        # في وضع failed: فقط نحذف من جدول الفاشلة (لا نُترجم الآن)
        # — الطلب التالي من اللعبة سيستدعي الـ AI من جديد
        if self._view == "failed":
            if QMessageBox.question(
                self, "أعد المحاولة",
                f"إزالة {n} {'إدخال' if n == 1 else 'إدخالات'} من قائمة الفاشلة؟\n\n"
                "سيستدعي البروكسي الـ AI مرة أخرى عند الطلب التالي من اللعبة.\n"
                "غيّر إعدادات المهلة/التاقات في صفحة اللعبة قبل ذلك إن لزم.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            ) != QMessageBox.Yes:
                return
            for e in entries:
                self._cache.delete_failed(e.get("game", self._game), e["original"])
            self._load_table()
            self._load_selectors()
            self.status_message.emit(f"✓  أُزيل {n} من الفاشلة — الـ AI سيُجرّب مرة أخرى")
            return

        if not self._engine:
            QMessageBox.warning(self, "لا يوجد موديل",
                                "فعّل موديل الترجمة أولاً.")
            return
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

    # ── Skip-list (منع) ───────────────────────────────────────────────────────

    def _open_skip_manager(self, seeds: list[str] | None = None):
        """يفتح حوار قائمة المنع. seeds (اختياري) = نصوص فاشلة مقترَحة."""
        from gui.qt.dialogs.skip_list_dialog import SkipListDialog
        # نخزّن مرجعاً لتجنّب جمع القمامة، ونعرض غير modal
        if not hasattr(self, "_open_skip_dialogs"):
            self._open_skip_dialogs = []
        dlg = SkipListDialog(self, seed_texts=seeds)
        dlg.saved.connect(self._after_skip_change)
        dlg.finished.connect(
            lambda _r, d=dlg: self._open_skip_dialogs.remove(d)
            if d in self._open_skip_dialogs else None
        )
        self._open_skip_dialogs.append(dlg)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _add_selected_to_skip(self):
        entries = self._get_selected_entries()
        if not entries:
            return
        seeds = [e.get("original", "") for e in entries if e.get("original")]
        if not seeds:
            return
        self._open_skip_manager(seeds=seeds)

    def _after_skip_change(self):
        """يُستدعى بعد كل تعديل في قائمة المنع. لا نعيد تحميل الجدول
        لأن الأنماط تؤثر على:
          1) طلبات البروكسي المستقبلية
          2) تصدير translations.txt القادم (عبر زر «تحديث الترجمات» في صفحة اللعبة)
        """
        from engine import skip_patterns
        n = len(skip_patterns.get_patterns())
        self.status_message.emit(
            f"✓  قائمة المنع: {n} نمط — ستُستَبعَد من translations.txt عند التصدير التالي"
        )

    # ── Tag discovery (اكتشاف التاقات) ────────────────────────────────────

    def _detect_tags_from_selection(self):
        """يفحص النصوص المحدَّدة ويفتح حوار اكتشاف التاقات."""
        entries = self._get_selected_entries()
        if not entries:
            return
        texts = [e.get("original", "") for e in entries if e.get("original")]
        if not texts:
            return

        from gui.qt.dialogs.tag_discovery_dialog import TagDiscoveryDialog
        from engine.tag_discovery import discover_tags

        # فحص مسبق: لو ما فيه أي تاق، لا نفتح الحوار
        results = discover_tags(texts)
        if not results:
            QMessageBox.information(
                self, "لا توجد تاقات",
                f"تم فحص {len(texts)} نص ولم يُعثَر على أي XML/HTML tags فيها.\n\n"
                "التاقات التي يكتشفها الزر تبدو مثل:\n"
                "  • <itemName id=|X|/>\n"
                "  • <b>...</b>\n"
                "  • <sprite=0>"
            )
            return

        dlg = TagDiscoveryDialog(texts, self)
        dlg.saved.connect(self._after_tag_discovery)
        dlg.exec()

    def _after_tag_discovery(self, added_in: int, added_sf: int):
        total = added_in + added_sf
        self.status_message.emit(
            f"✓  تمت إضافة {total} تاق محمي (inline={added_in}, selfclosing={added_sf})"
            " — مفعّلة فوراً للترجمات القادمة"
        )
