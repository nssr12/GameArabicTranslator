"""
gui/qt/dialogs/translation_window.py  —  نافذة تقدم الترجمة (غير معلقة)
"""

from __future__ import annotations
import logging
import os
import threading
import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QTextEdit, QProgressBar,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui  import QCursor, QTextCursor

from gui.qt.theme import theme
from games.iostore.translator import IoStoreTranslator

_log = logging.getLogger("TranslationWindow")


def _resolve_model_display(engine) -> str:
    """إرجاع اسم الموديل النشط بشكل مقروء للعرض في النافذة."""
    try:
        key = engine.get_active_model() or ""
        if not key:
            return "—"
        if key == "ollama" and hasattr(engine, "get_current_ollama_model"):
            sub = engine.get_current_ollama_model()
            return f"Ollama / {sub}" if sub else "Ollama"
        try:
            t = engine.get_translator(key)
            if t and hasattr(t, "name") and t.name and t.name != key:
                return t.name
        except Exception:
            pass
        return key
    except Exception:
        return "—"


def _fmt_dur(secs: float) -> str:
    secs = max(0, int(secs))
    h, rem = divmod(secs, 3600)
    m, s   = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class _GpuMonitor(QThread):
    """يستطلع Ollama /api/ps ونتيجة nvidia-smi كل 3 ثوانٍ."""
    stats = Signal(float, float)   # gpu_pct (-1 = غير معروف), vram_gb (-1 = غير معروف)

    def __init__(self, ollama_url: str):
        super().__init__()
        self._url  = ollama_url.rstrip("/")
        self._stop = False

    def run(self):
        try:
            import subprocess
            import requests as _req
            session = _req.Session()
        except Exception:
            return  # requests not available — exit silently

        while not self._stop:
            gpu_pct = -1.0
            vram_gb = -1.0
            try:
                r = session.get(f"{self._url}/api/ps", timeout=1)
                if r.status_code == 200:
                    total = sum(m.get("size_vram", 0)
                                for m in r.json().get("models", []))
                    if total > 0:
                        vram_gb = total / (1024 ** 3)
            except Exception:
                pass
            try:
                out = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=utilization.gpu",
                     "--format=csv,noheader,nounits"],
                    timeout=2, stderr=subprocess.DEVNULL
                ).decode().strip()
                gpu_pct = float(out.split("\n")[0].strip())
            except Exception:
                pass
            try:
                self.stats.emit(gpu_pct, vram_gb)
            except Exception:
                pass
            for _ in range(30):
                if self._stop:
                    break
                self.msleep(100)

    def request_stop(self):
        self._stop = True


class _TranslateWorker(QThread):
    finished = Signal(bool, object)   # ok, result dict
    progress = Signal(int, int)       # current, total
    logged   = Signal(str)            # log message

    def __init__(self, func, translator):
        super().__init__()
        self._func       = func
        self._translator = translator

    def run(self):
        self._translator.set_callbacks(
            log=self.logged.emit,
            progress=self.progress.emit,
        )
        try:
            ok, result = self._func()
            self.finished.emit(ok, result)
        except Exception as e:
            _log.error("Worker error: %s", e)
            self.finished.emit(False, {})


class TranslationProgressWindow(QWidget):
    """
    Standalone non-blocking translation window.
    Signals:
      applied(new_trans, all_trans)  — user pressed Apply
      cancelled()                    — user pressed Cancel
    """

    applied   = Signal(dict, dict)
    cancelled = Signal()

    def __init__(self, translator: IoStoreTranslator, engine, cache,
                 texts: list, game_name: str, mode: str, exmode: str,
                 pre_cached: dict, json_paths: list, parent=None):
        super().__init__(
            parent,
            Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint
        )
        self._translator = translator
        self._engine     = engine
        self._cache      = cache
        self._texts      = list(texts)
        self._game_name  = game_name
        self._mode       = mode
        self._exmode     = exmode
        self._pre_cached = dict(pre_cached)
        self._json_paths = list(json_paths)

        self._new_trans: dict = {}
        self._all_trans: dict = dict(pre_cached)
        self._worker          = None
        self._started         = False
        self._stopped         = False
        self._fail_count      = 0

        # ETA / GPU tracking
        self._start_time:    float        = 0.0
        self._cur_count:     int          = 0
        self._tot_count:     int          = len(texts)
        self._elapsed_timer: QTimer|None  = None
        self._gpu_monitor:   _GpuMonitor|None = None

        self._model_key = _resolve_model_display(engine)
        self._is_ollama = (engine.get_active_model() == "ollama")

        self.setWindowTitle(f"🌐  ترجمة النصوص — {game_name}")
        self.setMinimumSize(800, 600)
        self.resize(900, 660)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        c   = theme.c
        self.setStyleSheet(f"""
            QWidget   {{ background: {c['bg']}; }}
            QLabel    {{ color: {c['primary']}; background: transparent; border: none; }}
            QTextEdit {{
                background: {c['surface']}; color: {c['secondary']};
                border: 1px solid {c['border']}; border-radius: 6px;
                font-family: Consolas, monospace; font-size: 10px;
                selection-background-color: {c['accent']};
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header(c))

        body = QVBoxLayout()
        body.setContentsMargins(20, 16, 20, 8)
        body.setSpacing(14)
        body.addWidget(self._build_progress_card(c))
        body.addWidget(self._build_log_card(c), 1)
        root.addLayout(body, 1)

        root.addWidget(self._build_controls(c))

    def _build_header(self, c: dict) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(60)
        bar.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-bottom: 1px solid {c['border']}; }}"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 20, 0)

        t = QLabel("🌐  ترجمة النصوص")
        t.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {c['accent']};"
        )
        lay.addWidget(t)
        lay.addSpacing(16)

        info = QLabel(
            f"🤖 {self._model_key}   │   📄 {len(self._texts):,} نص   │   🎮 {self._game_name}"
        )
        info.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        lay.addWidget(info, 1)
        return bar

    def _build_progress_card(self, c: dict) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']};"
            " border-radius: 10px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        # Counter row
        row = QHBoxLayout()
        self._count_lbl = QLabel("— / —")
        self._count_lbl.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {c['primary']};"
        )
        self._status_lbl = QLabel("جاهز — اضغط «بدء الترجمة»")
        self._status_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 12px;")
        row.addWidget(self._count_lbl)
        row.addStretch()
        row.addWidget(self._status_lbl)
        lay.addLayout(row)

        # Progress bar
        self._prog_bar = QProgressBar()
        self._prog_bar.setRange(0, 100)
        self._prog_bar.setValue(0)
        self._prog_bar.setFixedHeight(10)
        self._prog_bar.setTextVisible(False)
        self._prog_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {c['surface']}; border: none; border-radius: 5px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {c['accent']}, stop:1 {c['blue']});
                border-radius: 5px;
            }}
        """)
        lay.addWidget(self._prog_bar)

        # Stats chips
        chips = QHBoxLayout()
        chips.setSpacing(24)

        def _chip(txt, clr_key):
            lbl = QLabel(txt)
            lbl.setStyleSheet(
                f"color: {c[clr_key]}; font-size: 11px; background: transparent; border: none;"
            )
            return lbl

        self._chip_cache = _chip(f"💾  كاش: {len(self._pre_cached):,}", "teal")
        self._chip_new   = _chip("🌐  جديد: 0",   "muted")
        self._chip_done  = _chip("✅  مكتمل: 0",  "muted")
        self._chip_fail  = _chip("⚠  فشل: 0",    "muted")

        for ch in (self._chip_cache, self._chip_new, self._chip_done, self._chip_fail):
            chips.addWidget(ch)
        chips.addStretch()
        lay.addLayout(chips)

        # Time / ETA / GPU row
        info_row = QHBoxLayout()
        info_row.setSpacing(20)
        self._elapsed_lbl = _chip("⏱  مرّ: —",       "muted")
        self._eta_lbl     = _chip("⏳  متبقي: —",     "muted")
        self._speed_lbl   = _chip("⚡  — نص/د",       "muted")
        info_row.addWidget(self._elapsed_lbl)
        info_row.addWidget(self._eta_lbl)
        info_row.addWidget(self._speed_lbl)
        if self._is_ollama:
            self._gpu_lbl  = _chip("🖥  GPU: —",  "muted")
            self._vram_lbl = _chip("💾  VRAM: —", "muted")
            info_row.addWidget(self._gpu_lbl)
            info_row.addWidget(self._vram_lbl)
        else:
            self._gpu_lbl  = None
            self._vram_lbl = None
        info_row.addStretch()
        lay.addLayout(info_row)
        return card

    def _build_log_card(self, c: dict) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']};"
            " border-radius: 10px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hdr = QFrame()
        hdr.setFixedHeight(34)
        hdr.setStyleSheet(
            f"QFrame {{ background: {c['surface']};"
            f" border-top-left-radius: 10px; border-top-right-radius: 10px;"
            f" border-bottom-left-radius: 0; border-bottom-right-radius: 0;"
            f" border-bottom: 1px solid {c['border']}; }}"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 0, 14, 0)
        hl.addWidget(QLabel("📋  سجل الترجمة"))
        hl.addStretch()
        clr = QPushButton("مسح")
        clr.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none;"
            f" color: {c['muted']}; font-size: 10px; }}"
            f"QPushButton:hover {{ color: {c['accent']}; }}"
        )
        clr.clicked.connect(lambda: self._log_view.clear())
        hl.addWidget(clr)
        lay.addWidget(hdr)

        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setStyleSheet(
            f"QTextEdit {{ background: {c['bg']}; border: none;"
            " border-top-left-radius: 0; border-top-right-radius: 0;"
            " border-bottom-left-radius: 10px; border-bottom-right-radius: 10px;"
            " padding: 10px; }"
        )
        lay.addWidget(self._log_view, 1)
        return card

    def _build_controls(self, c: dict) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-top: 1px solid {c['border']}; }}"
        )
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        def _btn(label, color, h=36):
            b = QPushButton(label)
            b.setFixedHeight(h)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            b.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(0,0,0,38); color: {color};
                    border: 1px solid {color}; border-radius: 8px;
                    font-weight: bold; padding: 0 16px;
                }}
                QPushButton:hover  {{ background: {color}; color: #fff; }}
                QPushButton:disabled {{ opacity: 0.35; }}
            """)
            return b

        # Translation controls
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        self._start_btn  = _btn("▶  بدء الترجمة",  c["accent"])
        self._pause_btn  = _btn("⏸  إيقاف مؤقت",  c["yellow"])
        self._resume_btn = _btn("▶▶  استئناف",      c["green"])
        self._stop_btn   = _btn("⏹  إيقاف كامل",  c["muted"])
        self._pause_btn.setEnabled(False)
        self._resume_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._start)
        self._pause_btn.clicked.connect(self._pause)
        self._resume_btn.clicked.connect(self._resume)
        self._stop_btn.clicked.connect(self._stop)
        for b in (self._start_btn, self._pause_btn, self._resume_btn, self._stop_btn):
            ctrl.addWidget(b)
        ctrl.addStretch()
        outer.addLayout(ctrl)

        # Apply / Cancel (hidden until done)
        self._result_frame = QFrame()
        self._result_frame.setStyleSheet(
            f"QFrame {{ background: {c['surface']}; border: 1px solid {c['border']};"
            " border-radius: 8px; }"
        )
        rf = QHBoxLayout(self._result_frame)
        rf.setContentsMargins(14, 10, 14, 10)
        rf.setSpacing(12)
        self._result_lbl = QLabel("")
        self._result_lbl.setWordWrap(True)
        self._result_lbl.setStyleSheet(f"color: {c['secondary']}; font-size: 11px;")
        rf.addWidget(self._result_lbl, 1)
        self._apply_btn  = _btn("✅  تطبيق: حفظ في الكاش + JSON", c["green"], 38)
        self._cancel_btn = _btn("🗑  إلغاء: تجاهل الترجمات",      c["accent"], 38)
        self._apply_btn.clicked.connect(self._apply)
        self._cancel_btn.clicked.connect(self._cancel)
        rf.addWidget(self._apply_btn)
        rf.addWidget(self._cancel_btn)
        self._result_frame.setVisible(False)
        outer.addWidget(self._result_frame)
        return frame

    # ── Logging ───────────────────────────────────────────────────────────────

    def _append_log(self, msg: str, color: str = None):
        c = color or theme.c["secondary"]
        self._log_view.append(f'<span style="color:{c};">{msg}</span>')
        self._log_view.moveCursor(QTextCursor.End)

    # ── Controls ──────────────────────────────────────────────────────────────

    def _start(self):
        if self._started:
            return
        self._started = True
        c = theme.c
        self._start_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self._stop_btn.setEnabled(True)
        self._status_lbl.setText("🔄 جاري الترجمة…")
        self._status_lbl.setStyleSheet(f"color: {c['yellow']}; font-size: 12px;")

        texts      = self._texts
        mode       = self._mode
        gname      = self._game_name
        pre_cached = self._pre_cached
        translator = self._translator
        cache      = self._cache

        def _work():
            if mode == "cache_only":
                hits = cache.get_batch(gname, texts) if cache else {}
                return bool(hits), hits
            remaining = [tx for tx in texts if tx not in pre_cached] \
                        if mode == "missing" else texts
            new_trans = translator.translate_texts(remaining, gname, use_cache=False)
            return bool(new_trans) or bool(pre_cached), new_trans

        self._worker = _TranslateWorker(_work, self._translator)
        self._worker.finished.connect(self._on_done)
        self._worker.progress.connect(self._on_progress)
        self._worker.logged.connect(self._on_log)
        self._worker.start()

        # Start elapsed-time timer
        self._start_time = time.time()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._update_time)
        self._elapsed_timer.start(1000)

        # Start GPU monitor for Ollama
        if self._is_ollama:
            ollama_url = "http://localhost:11434"
            try:
                t = self._engine.get_translator("ollama")
                if t and hasattr(t, "url"):
                    ollama_url = t.url
            except Exception:
                pass
            self._gpu_monitor = _GpuMonitor(ollama_url)
            self._gpu_monitor.stats.connect(self._on_gpu_stats)
            self._gpu_monitor.start()

        self._append_log(
            f"🚀  بدأت الترجمة — النموذج: {self._model_key}"
            f" | النصوص: {len(texts):,} | كاش مسبق: {len(pre_cached):,}",
            c["teal"]
        )

    def _pause(self):
        self._translator.pause()
        self._pause_btn.setEnabled(False)
        self._resume_btn.setEnabled(True)
        c = theme.c
        self._status_lbl.setText("⏸ متوقف مؤقتاً")
        self._status_lbl.setStyleSheet(f"color: {c['yellow']}; font-size: 12px;")
        self._append_log("⏸  إيقاف مؤقت", c["yellow"])

    def _resume(self):
        self._translator.resume()
        self._pause_btn.setEnabled(True)
        self._resume_btn.setEnabled(False)
        c = theme.c
        self._status_lbl.setText("🔄 جاري الترجمة…")
        self._status_lbl.setStyleSheet(f"color: {c['yellow']}; font-size: 12px;")
        self._append_log("▶  تم الاستئناف", c["green"])

    def _stop(self):
        self._stopped = True
        self._translator.stop()
        self._pause_btn.setEnabled(False)
        self._resume_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._append_log("⏹  تم إيقاف الترجمة", theme.c["yellow"])

    # ── Callbacks from translator ─────────────────────────────────────────────

    def _on_log(self, msg: str):
        c = theme.c
        if "[ERROR]" in msg or "ERROR:" in msg:
            color = c["accent"]
        elif "[warn]" in msg:
            color = c["yellow"]
        elif "✓" in msg or "done" in msg.lower():
            color = c["green"]
        else:
            color = c["secondary"]
        self._append_log(msg, color)

        if "[warn] no translation" in msg:
            self._fail_count += 1
            self._chip_fail.setText(f"⚠  فشل: {self._fail_count}")
            self._chip_fail.setStyleSheet(
                f"color: {c['yellow']}; font-size: 11px;"
                " background: transparent; border: none;"
            )

    def _on_progress(self, current: int, total: int):
        if total <= 0:
            return
        c = theme.c
        pct = int(current / total * 100)
        self._prog_bar.setValue(pct)
        self._count_lbl.setText(f"{current:,} / {total:,}")
        self._cur_count = current
        self._tot_count = total
        new_count = max(0, current - len(self._pre_cached))
        self._chip_new.setText(f"🌐  جديد: {new_count:,}")
        self._chip_done.setText(f"✅  مكتمل: {current:,}")
        if new_count > 0:
            self._chip_new.setStyleSheet(
                f"color: {c['green']}; font-size: 11px;"
                " background: transparent; border: none;"
            )
        self._chip_done.setStyleSheet(
            f"color: {c['teal'] if current > 0 else c['muted']};"
            " font-size: 11px; background: transparent; border: none;"
        )

    def _update_time(self):
        if not self._start_time:
            return
        c = theme.c
        elapsed = time.time() - self._start_time
        self._elapsed_lbl.setText(f"⏱  مرّ: {_fmt_dur(elapsed)}")
        self._elapsed_lbl.setStyleSheet(
            f"color: {c['secondary']}; font-size: 11px; background: transparent; border: none;"
        )
        cur  = self._cur_count
        tot  = self._tot_count
        done = max(0, cur - len(self._pre_cached))
        if done > 0 and tot > 0 and elapsed > 0:
            rate      = done / elapsed          # نص/ثانية
            remaining = max(0, tot - cur) / rate
            speed_min = rate * 60
            self._eta_lbl.setText(f"⏳  متبقي: {_fmt_dur(remaining)}")
            self._speed_lbl.setText(f"⚡  {speed_min:.0f} نص/د")
            for lbl, clr in ((self._eta_lbl, "blue"), (self._speed_lbl, "green")):
                lbl.setStyleSheet(
                    f"color: {c[clr]}; font-size: 11px; background: transparent; border: none;"
                )

    def _on_gpu_stats(self, gpu_pct: float, vram_gb: float):
        c = theme.c
        if self._gpu_lbl and gpu_pct >= 0:
            color = c["green"] if gpu_pct > 60 else c["yellow"] if gpu_pct > 20 else c["muted"]
            self._gpu_lbl.setText(f"🖥  GPU: {gpu_pct:.0f}%")
            self._gpu_lbl.setStyleSheet(
                f"color: {color}; font-size: 11px; background: transparent; border: none;"
            )
        if self._vram_lbl and vram_gb >= 0:
            self._vram_lbl.setText(f"💾  VRAM: {vram_gb:.1f} GB")
            self._vram_lbl.setStyleSheet(
                f"color: {c['teal']}; font-size: 11px; background: transparent; border: none;"
            )

    def _stop_monitors(self):
        if self._elapsed_timer:
            self._elapsed_timer.stop()
            self._elapsed_timer = None
        if self._gpu_monitor:
            self._gpu_monitor.request_stop()
            self._gpu_monitor.wait(1500)
            self._gpu_monitor = None

    def _on_done(self, ok: bool, result):
        self._stop_monitors()
        c = theme.c
        self._pause_btn.setEnabled(False)
        self._resume_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._start_btn.setEnabled(True)
        self._started = False

        self._new_trans = result if isinstance(result, dict) else {}
        self._all_trans.update(self._new_trans)

        total = len(self._all_trans)
        new_c = len(self._new_trans)
        pre_c = len(self._pre_cached)

        if self._stopped:
            self._status_lbl.setText(f"⏹  توقف — {new_c:,} ترجمة محفوظة")
            self._status_lbl.setStyleSheet(f"color: {c['yellow']}; font-size: 12px;")
            self._append_log(
                f"⏹  توقف — {new_c:,} جديد + {pre_c:,} كاش = {total:,} إجمالاً",
                c["yellow"]
            )
        elif ok:
            self._status_lbl.setText("✅  اكتملت الترجمة")
            self._status_lbl.setStyleSheet(f"color: {c['green']}; font-size: 12px;")
            self._prog_bar.setValue(100)
            self._count_lbl.setText(f"{total:,} / {len(self._texts):,}")
            self._append_log(
                f"✅  اكتملت — {new_c:,} جديد + {pre_c:,} كاش = {total:,} إجمالاً",
                c["green"]
            )
        else:
            self._status_lbl.setText("⚠  لم تكتمل الترجمة")
            self._status_lbl.setStyleSheet(f"color: {c['accent']}; font-size: 12px;")
            self._append_log("⚠  انتهت مع أخطاء — راجع السجل أعلاه", c["accent"])

        if total > 0:
            if self._mode == "cache_only":
                self._new_trans = {}   # already in cache — no re-save needed
                self._apply_btn.setText("✅  تطبيق على JSON")
                self._result_lbl.setText(
                    f"الكاش: وُجد {total:,} ترجمة جاهزة\n"
                    "اضغط «تطبيق» لكتابتها على ملفات JSON."
                )
            else:
                self._result_lbl.setText(
                    f"تمت الترجمة:  {new_c:,} جديد  +  {pre_c:,} من الكاش  =  {total:,} إجمالاً\n"
                    "اضغط «تطبيق» لحفظها في الكاش وتطبيقها على ملفات JSON، أو «إلغاء» لتجاهلها."
                )
            self._result_frame.setVisible(True)

    def _apply(self):
        self._result_frame.setVisible(False)
        self._apply_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._append_log(
            f"✅  تطبيق {len(self._new_trans):,} ترجمة جديدة…", theme.c["green"]
        )
        self.applied.emit(dict(self._new_trans), dict(self._all_trans))

    def _cancel(self):
        self._result_frame.setVisible(False)
        self._append_log("🗑  تم الإلغاء — لم يُحفظ شيء", theme.c["yellow"])
        self.cancelled.emit()

    def closeEvent(self, event):
        self._stop_monitors()
        if self._worker and self._worker.isRunning():
            try:
                self._translator.stop()
            except Exception:
                pass
            self._worker.wait(2000)
        super().closeEvent(event)


# ── Locres Translation Window ─────────────────────────────────────────────────

class LocresTranslateWorker(QThread):
    """يقرأ ملفات .locres، يترجمها، ويكتب النتيجة مباشرة على الملفات."""

    progress = Signal(int, int)        # done, total
    logged   = Signal(str, str)        # message, color_key
    finished = Signal(bool, int, int)  # ok, replaced, total_count

    def __init__(self, folder: str, engine, cache, game_id: str, mode: str = "missing"):
        super().__init__()
        self._folder      = folder
        self._engine      = engine
        self._cache       = cache
        self._game_id     = game_id
        self._mode        = mode          # "missing" | "full" | "cache_only"
        self._stop_flag   = False
        self._pause_event = threading.Event()
        self._pause_event.set()

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def stop(self):
        self._stop_flag = True
        self._pause_event.set()

    def run(self):
        try:
            from games.locres_patcher import LocresPatcher, LocresTxtFile

            files = LocresPatcher.find_locres_files(self._folder)
            if not files:
                self.logged.emit("⚠  لم يُعثر على ملفات .locres/.locres.txt في المجلد", "yellow")
                self.finished.emit(False, 0, 0)
                return

            txt_files = [f for f in files if f.lower().endswith(".locres.txt")]
            bin_files = [f for f in files if not f.lower().endswith(".locres.txt")]
            self.logged.emit(
                f"📂  وُجد {len(bin_files)} ملف .locres + {len(txt_files)} ملف .locres.txt",
                "teal"
            )

            # ── قراءة كل الملفات وجمع النصوص الفريدة ──────────────────────
            file_entries: dict[str, list] = {}
            seen: dict[str, None] = {}

            for path in txt_files:
                entries = LocresTxtFile.read(path)
                self.logged.emit(
                    f"  📄 {os.path.basename(path)}: {len(entries)} مدخلة (txt)", "muted"
                )
                file_entries[path] = entries
                for e in entries:
                    t = e.value.strip()
                    if t:
                        seen[t] = None

            for path in bin_files:
                def _log_line(msg, _p=path):
                    self.logged.emit(msg, "muted")
                entries = LocresPatcher.read(path, logger=_log_line)
                self.logged.emit(
                    f"  📄 {os.path.basename(path)}: {len(entries)} مدخلة (bin)", "muted"
                )
                file_entries[path] = entries
                for e in entries:
                    t = e.value.strip()
                    if t:
                        seen[t] = None

            unique_texts  = list(seen.keys())
            total_unique  = len(unique_texts)
            total_entries = sum(len(v) for v in file_entries.values())

            if total_unique == 0:
                self.logged.emit("✅  لا توجد نصوص قابلة للترجمة", "green")
                self.finished.emit(True, 0, 0)
                return

            # سجل واضح: الإجمالي مقابل الفريد (النصوص المكررة تُترجم تلقائياً)
            dup_count = total_entries - total_unique
            if dup_count > 0:
                self.logged.emit(
                    f"📝  {total_entries:,} مدخلة إجمالاً  ←  {total_unique:,} نص فريد"
                    f" + {dup_count:,} مكرر/فارغ (ستُطبَّق الترجمة على جميع المدخلات)",
                    "secondary"
                )
            else:
                self.logged.emit(f"📝  {total_unique:,} نص فريد للترجمة", "secondary")

            # ── بحث في الكاش ──────────────────────────────────────────────
            translations: dict[str, str] = {}
            cache_hits = 0
            game_name = self._game_id
            try:
                active_model = self._engine.get_active_model() or "unknown"
            except Exception:
                active_model = "unknown"
            if self._cache:
                for txt in unique_texts:
                    ar = self._cache.get(game_name, txt)
                    if ar:
                        translations[txt] = ar
                        cache_hits += 1

            self.logged.emit(f"💾  كاش: {cache_hits:,} نص موجود مسبقاً", "teal")

            # ── تحديد النصوص للترجمة حسب الوضع المختار ───────────────────
            if self._mode == "cache_only":
                missing = []
                self.logged.emit("☐  وضع الكاش فقط — لن يتم استدعاء API", "muted")
            elif self._mode == "full":
                missing = unique_texts
                self.logged.emit(f"◆  ترجمة كاملة من الصفر — {total_unique:,} نص", "blue")
            else:
                missing = [t for t in unique_texts if t not in translations]
                self.logged.emit(f"◆  استكمال المفقود — {len(missing):,} نص يحتاج ترجمة", "orange")

            # ── ترجمة النصوص الجديدة ──────────────────────────────────────
            # التقدم يعتمد على عدد النصوص المطلوب ترجمتها فعلياً
            n_to_translate = len(missing)
            for i, txt in enumerate(missing):
                self._pause_event.wait()
                if self._stop_flag:
                    self.logged.emit("⏹  توقف بطلب المستخدم", "yellow")
                    break
                try:
                    ar = self._engine.translate(txt)
                    if ar and ar != txt:
                        translations[txt] = ar
                        if self._cache:
                            self._cache.put(game_name, txt, ar, active_model)
                except Exception as exc:
                    self.logged.emit(f"⚠  خطأ: {exc}", "accent")

                done_so_far = i + 1
                emit_total  = n_to_translate if n_to_translate > 0 else 1
                self.progress.emit(done_so_far, emit_total)
                if done_so_far % 20 == 0 or done_so_far == n_to_translate:
                    self.logged.emit(
                        f"✅  {done_so_far:,} / {n_to_translate:,}"
                        f"  ({int(done_so_far / emit_total * 100)}%)",
                        "green"
                    )

            # ── تطبيق الترجمات على الملفات (يشمل النصوص المكررة) ──────────
            total_replaced = 0
            total_count    = 0

            for path in txt_files:
                replaced, count = LocresTxtFile.patch(path, path, translations)
                total_replaced += replaced
                total_count    += count
                fname = os.path.basename(path)
                self.logged.emit(f"📄  {fname}: {replaced:,} / {count:,} مدخلة ← مكتوبة", "teal")

            for path in bin_files:
                entries = file_entries.get(path, [])
                if not entries:
                    continue
                replaced, count = LocresPatcher.patch(path, path, translations)
                total_replaced += replaced
                total_count    += count
                fname = os.path.basename(path)
                self.logged.emit(f"📄  {fname}: {replaced:,} / {count:,} مدخلة ← مكتوبة", "secondary")

            self.finished.emit(True, total_replaced, total_count)

        except Exception as exc:
            self.logged.emit(f"❌  خطأ فادح: {exc}", "accent")
            self.finished.emit(False, 0, 0)


class LocresTranslationWindow(QWidget):
    """نافذة ترجمة ملفات .locres — نفس تصميم TranslationProgressWindow."""

    done = Signal(int, int)   # replaced, total

    def __init__(self, folder: str, engine, cache,
                 game_id: str, game_name: str, parent=None):
        super().__init__(
            parent,
            Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint
        )
        self._folder    = folder
        self._engine    = engine
        self._cache     = cache
        self._game_id   = game_id
        self._game_name = game_name
        self._worker: LocresTranslateWorker | None = None
        self._started   = False
        self._start_time = 0.0
        self._cur = 0
        self._tot = 0
        self._elapsed_timer: QTimer | None = None

        self._model_key = _resolve_model_display(engine)

        self.setWindowTitle(f"🌐  ترجمة .locres — {game_name}")
        self.setMinimumSize(800, 580)
        self.resize(880, 640)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        c = theme.c
        self.setStyleSheet(f"""
            QWidget   {{ background: {c['bg']}; }}
            QLabel    {{ color: {c['primary']}; background: transparent; border: none; }}
            QTextEdit {{
                background: {c['surface']}; color: {c['secondary']};
                border: 1px solid {c['border']}; border-radius: 6px;
                font-family: Consolas, monospace; font-size: 10px;
                selection-background-color: {c['accent']};
            }}
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header(c))
        body = QVBoxLayout()
        body.setContentsMargins(20, 16, 20, 8)
        body.setSpacing(14)
        self._mode_card = self._build_mode_card(c)
        body.addWidget(self._mode_card)
        body.addWidget(self._build_progress_card(c))
        body.addWidget(self._build_log_card(c), 1)
        root.addLayout(body, 1)
        root.addWidget(self._build_controls(c))

    def _build_mode_card(self, c) -> QFrame:
        """بطاقة اختيار وضع الترجمة."""
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']};"
            " border-radius: 10px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 12, 20, 14)
        lay.setSpacing(10)

        title = QLabel("⚙️  وضع الترجمة")
        title.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {c['muted']}; border: none;"
        )
        lay.addWidget(title)

        btns_row = QHBoxLayout()
        btns_row.setSpacing(10)

        modes = [
            ("missing",    f"◆  استكمال المفقود",      c["orange"],
             "ترجمة النصوص الغائبة عن الكاش فقط  (افتراضي)"),
            ("full",       f"◆  ترجمة كاملة من الصفر", c["blue"],
             "إعادة ترجمة جميع النصوص حتى الموجودة في الكاش"),
            ("cache_only", f"☐  من الكاش فقط",          c["muted"],
             "تطبيق الترجمات المحفوظة فقط — بدون استدعاء API"),
        ]

        self._mode_btns: dict[str, QPushButton] = {}
        for key, label, color, tip in modes:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setToolTip(tip)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setChecked(key == "missing")
            self._mode_btns[key] = btn
            btn.clicked.connect(lambda _checked, k=key: self._select_mode(k))
            btns_row.addWidget(btn)
            self._apply_mode_btn_style(btn, color, c, checked=(key == "missing"))

        btns_row.addStretch()
        lay.addLayout(btns_row)
        return card

    def _apply_mode_btn_style(self, btn: QPushButton, color: str, c: dict,
                               checked: bool = False):
        if checked:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {color}33; color: {color};
                    border: 2px solid {color}; border-radius: 8px;
                    font-weight: bold; font-size: 11px; padding: 7px 16px;
                }}
                QPushButton:hover {{ background: {color}44; }}
                QPushButton:disabled {{ opacity: 0.4; }}
            """)
        else:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {c['muted']};
                    border: 1px solid {c['border']}; border-radius: 8px;
                    font-size: 11px; padding: 7px 16px;
                }}
                QPushButton:hover {{
                    background: {color}18; color: {color};
                    border-color: {color}88;
                }}
                QPushButton:disabled {{ opacity: 0.4; }}
            """)

    def _select_mode(self, key: str):
        c = theme.c
        colors = {
            "missing":    c["orange"],
            "full":       c["blue"],
            "cache_only": c["muted"],
        }
        for k, btn in self._mode_btns.items():
            btn.setChecked(k == key)
            self._apply_mode_btn_style(btn, colors[k], c, checked=(k == key))

    def _get_mode(self) -> str:
        for key, btn in self._mode_btns.items():
            if btn.isChecked():
                return key
        return "missing"

    def _build_header(self, c):
        bar = QFrame()
        bar.setFixedHeight(60)
        bar.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-bottom: 1px solid {c['border']}; }}"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 20, 0)
        t = QLabel("📄  ترجمة .locres")
        t.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {c['teal']};")
        lay.addWidget(t)
        lay.addSpacing(16)
        info = QLabel(
            f"🤖 {self._model_key}   │   📂 {os.path.basename(self._folder)}   │   🎮 {self._game_name}"
        )
        info.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        lay.addWidget(info, 1)
        return bar

    def _build_progress_card(self, c):
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']};"
            " border-radius: 10px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        row = QHBoxLayout()
        self._count_lbl = QLabel("— / —")
        self._count_lbl.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {c['primary']};"
        )
        self._status_lbl = QLabel("جاهز — اضغط «بدء الترجمة»")
        self._status_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 12px;")
        row.addWidget(self._count_lbl)
        row.addStretch()
        row.addWidget(self._status_lbl)
        lay.addLayout(row)

        self._prog_bar = QProgressBar()
        self._prog_bar.setRange(0, 100)
        self._prog_bar.setValue(0)
        self._prog_bar.setFixedHeight(10)
        self._prog_bar.setTextVisible(False)
        self._prog_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {c['surface']}; border: none; border-radius: 5px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {c['teal']}, stop:1 {c['blue']});
                border-radius: 5px;
            }}
        """)
        lay.addWidget(self._prog_bar)

        chips = QHBoxLayout()
        chips.setSpacing(24)

        def _chip(txt, clr_key):
            lbl = QLabel(txt)
            lbl.setStyleSheet(
                f"color: {c[clr_key]}; font-size: 11px; background: transparent; border: none;"
            )
            return lbl

        self._chip_cache = _chip("💾  كاش: —",    "teal")
        self._chip_new   = _chip("🌐  جديد: —",   "muted")
        self._chip_done  = _chip("✅  مكتمل: 0",  "muted")
        self._chip_fail  = _chip("⚠  فشل: 0",    "muted")
        for ch in (self._chip_cache, self._chip_new, self._chip_done, self._chip_fail):
            chips.addWidget(ch)
        chips.addStretch()
        lay.addLayout(chips)

        info_row = QHBoxLayout()
        info_row.setSpacing(20)
        self._elapsed_lbl = _chip("⏱  مرّ: —",     "muted")
        self._eta_lbl     = _chip("⏳  متبقي: —",   "muted")
        self._speed_lbl   = _chip("⚡  — نص/د",     "muted")
        for lbl in (self._elapsed_lbl, self._eta_lbl, self._speed_lbl):
            info_row.addWidget(lbl)
        info_row.addStretch()
        lay.addLayout(info_row)
        return card

    def _build_log_card(self, c):
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']};"
            " border-radius: 10px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hdr = QFrame()
        hdr.setFixedHeight(34)
        hdr.setStyleSheet(
            f"QFrame {{ background: {c['surface']};"
            f" border-top-left-radius: 10px; border-top-right-radius: 10px;"
            f" border-bottom-left-radius: 0; border-bottom-right-radius: 0;"
            f" border-bottom: 1px solid {c['border']}; }}"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 0, 14, 0)
        hl.addWidget(QLabel("📋  سجل الترجمة"))
        hl.addStretch()
        clr = QPushButton("مسح")
        clr.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none;"
            f" color: {c['muted']}; font-size: 10px; }}"
            f"QPushButton:hover {{ color: {c['teal']}; }}"
        )
        clr.clicked.connect(lambda: self._log_view.clear())
        hl.addWidget(clr)
        lay.addWidget(hdr)

        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setStyleSheet(
            f"QTextEdit {{ background: {c['bg']}; border: none;"
            " border-top-left-radius: 0; border-top-right-radius: 0;"
            " border-bottom-left-radius: 10px; border-bottom-right-radius: 10px;"
            " padding: 10px; }"
        )
        lay.addWidget(self._log_view, 1)
        return card

    def _build_controls(self, c):
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-top: 1px solid {c['border']}; }}"
        )
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        def _btn(label, color):
            b = QPushButton(label)
            b.setFixedHeight(36)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            b.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(0,0,0,38); color: {color};
                    border: 1px solid {color}; border-radius: 8px;
                    font-weight: bold; padding: 0 16px;
                }}
                QPushButton:hover     {{ background: {color}; color: #fff; }}
                QPushButton:disabled  {{ opacity: 0.35; }}
            """)
            return b

        self._start_btn  = _btn("▶  بدء الترجمة",  c["teal"])
        self._pause_btn  = _btn("⏸  إيقاف مؤقت",  c["yellow"])
        self._resume_btn = _btn("▶▶  استئناف",      c["green"])
        self._stop_btn   = _btn("⏹  إيقاف كامل",  c["muted"])
        self._pause_btn.setEnabled(False)
        self._resume_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._start)
        self._pause_btn.clicked.connect(self._pause)
        self._resume_btn.clicked.connect(self._resume)
        self._stop_btn.clicked.connect(self._stop)
        for b in (self._start_btn, self._pause_btn, self._resume_btn, self._stop_btn):
            lay.addWidget(b)
        lay.addStretch()
        return frame

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log(self, msg: str, color_key: str = "secondary"):
        color = theme.c.get(color_key, theme.c["secondary"])
        self._log_view.append(f'<span style="color:{color};">{msg}</span>')
        self._log_view.moveCursor(QTextCursor.End)

    # ── Controls ──────────────────────────────────────────────────────────────

    def _start(self):
        if self._started:
            return
        self._started = True
        mode = self._get_mode()
        self._mode_card.setEnabled(False)
        c = theme.c
        self._start_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self._stop_btn.setEnabled(True)
        self._status_lbl.setText("🔄  جاري الترجمة…")
        self._status_lbl.setStyleSheet(f"color: {c['yellow']}; font-size: 12px;")

        self._worker = LocresTranslateWorker(
            self._folder, self._engine, self._cache, self._game_id, mode=mode
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.logged.connect(self._log)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

        self._start_time = time.time()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._update_time)
        self._elapsed_timer.start(1000)

        self._log(f"🚀  بدأت الترجمة — النموذج: {self._model_key}", "teal")

    def _pause(self):
        if self._worker:
            self._worker.pause()
        self._pause_btn.setEnabled(False)
        self._resume_btn.setEnabled(True)
        self._status_lbl.setText("⏸  متوقف مؤقتاً")
        self._status_lbl.setStyleSheet(f"color: {theme.c['yellow']}; font-size: 12px;")
        self._log("⏸  إيقاف مؤقت", "yellow")

    def _resume(self):
        if self._worker:
            self._worker.resume()
        self._pause_btn.setEnabled(True)
        self._resume_btn.setEnabled(False)
        self._status_lbl.setText("🔄  جاري الترجمة…")
        self._status_lbl.setStyleSheet(f"color: {theme.c['yellow']}; font-size: 12px;")
        self._log("▶  تم الاستئناف", "green")

    def _stop(self):
        if self._worker:
            self._worker.stop()
        self._pause_btn.setEnabled(False)
        self._resume_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._log("⏹  تم إيقاف الترجمة", "yellow")

    def _on_progress(self, done: int, total: int):
        if total <= 0:
            return
        c = theme.c
        pct = int(done / total * 100)
        self._prog_bar.setValue(pct)
        self._count_lbl.setText(f"{done:,} / {total:,}")
        self._cur = done
        self._tot = total
        self._chip_done.setText(f"✅  مكتمل: {done:,}")
        self._chip_done.setStyleSheet(
            f"color: {c['teal']}; font-size: 11px; background: transparent; border: none;"
        )

    def _update_time(self):
        if not self._start_time:
            return
        c = theme.c
        elapsed = time.time() - self._start_time
        self._elapsed_lbl.setText(f"⏱  مرّ: {_fmt_dur(elapsed)}")
        self._elapsed_lbl.setStyleSheet(
            f"color: {c['secondary']}; font-size: 11px; background: transparent; border: none;"
        )
        cur = self._cur
        tot = self._tot
        if cur > 0 and tot > 0 and elapsed > 0:
            rate      = cur / elapsed
            remaining = max(0, tot - cur) / rate
            self._eta_lbl.setText(f"⏳  متبقي: {_fmt_dur(remaining)}")
            self._speed_lbl.setText(f"⚡  {rate * 60:.0f} نص/د")
            for lbl, clr in ((self._eta_lbl, "blue"), (self._speed_lbl, "green")):
                lbl.setStyleSheet(
                    f"color: {c[clr]}; font-size: 11px; background: transparent; border: none;"
                )

    def _on_done(self, ok: bool, replaced: int, total_count: int):
        if self._elapsed_timer:
            self._elapsed_timer.stop()
            self._elapsed_timer = None
        c = theme.c
        self._pause_btn.setEnabled(False)
        self._resume_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._start_btn.setEnabled(True)
        self._mode_card.setEnabled(True)
        self._started = False
        self._prog_bar.setValue(100)
        if ok:
            self._status_lbl.setText("✅  اكتملت الترجمة")
            self._status_lbl.setStyleSheet(f"color: {c['green']}; font-size: 12px;")
            self._log(
                f"✅  اكتملت — تم تطبيق {replaced:,} ترجمة على {total_count:,} نص في ملفات .locres",
                "green"
            )
        else:
            self._status_lbl.setText("⚠  انتهت مع أخطاء")
            self._status_lbl.setStyleSheet(f"color: {c['accent']}; font-size: 12px;")
        self.done.emit(replaced, total_count)

    def closeEvent(self, event):
        if self._elapsed_timer:
            self._elapsed_timer.stop()
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(2000)
        super().closeEvent(event)
