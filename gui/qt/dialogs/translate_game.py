"""
gui/qt/dialogs/translate_game.py  —  حوار ترجمة اللعبة مع شريط التقدم
"""

from __future__ import annotations
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QProgressBar, QTextEdit, QButtonGroup,
    QRadioButton, QSizePolicy, QScrollBar,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui  import QColor, QCursor, QTextCursor

from gui.qt.theme import theme


# ── Translation worker ────────────────────────────────────────────────────────

class TranslateWorker(QThread):
    progress = Signal(int, int, str)   # done, total, current_text
    finished = Signal(int, int)        # translated, failed

    def __init__(self, game_id: str, game_cfg: dict,
                 engine, cache, mode: str = "missing"):
        super().__init__()
        self._game_id  = game_id
        self._game_cfg = game_cfg
        self._engine   = engine
        self._cache    = cache
        self._mode     = mode          # "fresh" | "missing" | "cache_only"
        self._stop     = False

    def stop(self):
        self._stop = True

    def run(self):
        translated = 0
        failed     = 0
        try:
            strings = self._collect_strings()
            total   = len(strings)
            if total == 0:
                self.finished.emit(0, 0)
                return

            game_name = self._game_cfg.get("name", self._game_id)

            for i, text in enumerate(strings):
                if self._stop:
                    break
                try:
                    cached = None
                    if self._cache:
                        cached = self._cache.get(game_name, text)

                    if self._mode == "cache_only":
                        if cached:
                            translated += 1
                        else:
                            failed += 1
                    elif self._mode == "missing" and cached:
                        translated += 1
                    else:
                        result = self._engine.translate(text) if self._engine else None
                        if result and result != text:
                            if self._cache:
                                self._cache.update_translation(game_name, text, result)
                            translated += 1
                        else:
                            failed += 1

                    self.progress.emit(i + 1, total, text[:60])
                except Exception as e:
                    failed += 1
                    self.progress.emit(i + 1, total, f"[خطأ] {e}")

        except Exception as e:
            self.progress.emit(0, 1, f"[خطأ فادح] {e}")

        self.finished.emit(translated, failed)

    def _collect_strings(self) -> list[str]:
        game_name = self._game_cfg.get("name", self._game_id)
        if self._cache:
            try:
                items = []
                page  = 0
                while True:
                    batch = self._cache.get_page(game_name, page, 200)
                    if not batch:
                        break
                    items.extend(r["original"] for r in batch)
                    if len(batch) < 200:
                        break
                    page += 1
                return items
            except Exception:
                pass
        return []


# ── Dialog ────────────────────────────────────────────────────────────────────

class TranslateGameDialog(QDialog):
    """حوار ترجمة اللعبة — يعرض التقدم والسجل."""

    translation_done = Signal(int)   # عدد الترجمات الناجحة

    def __init__(self, game_id: str, game_cfg: dict,
                 engine, cache, parent=None):
        super().__init__(parent)
        self._game_id  = game_id
        self._game_cfg = game_cfg
        self._engine   = engine
        self._cache    = cache
        self._worker: TranslateWorker | None = None

        self.setWindowTitle(f"ترجمة — {game_cfg.get('name', game_id)}")
        self.setMinimumSize(580, 500)
        self.setModal(True)
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        c = theme.c
        self.setStyleSheet(f"""
            QDialog   {{ background: {c['bg']}; }}
            QLabel    {{ color: {c['primary']}; background: transparent; border: none; }}
            QTextEdit {{
                background: {c['surface']}; color: {c['secondary']};
                border: 1px solid {c['border']}; border-radius: 6px;
                font-family: Consolas, monospace; font-size: 11px;
            }}
            QRadioButton {{ color: {c['primary']}; background: transparent; }}
            QRadioButton::indicator {{
                width: 14px; height: 14px;
                border: 1px solid {c['border']}; border-radius: 7px;
                background: {c['surface']};
            }}
            QRadioButton::indicator:checked {{
                background: {c['accent']}; border-color: {c['accent']};
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # Title
        game_name = self._game_cfg.get("name", self._game_id)
        title = QLabel(f"🌐  ترجمة:  {game_name}")
        title.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {c['accent']};"
            " background: transparent; border: none;"
        )
        root.addWidget(title)

        # Mode selection
        mode_frame = QFrame()
        mode_frame.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']};"
            " border-radius: 8px; }}"
        )
        mode_lay = QHBoxLayout(mode_frame)
        mode_lay.setContentsMargins(16, 12, 16, 12)
        mode_lay.setSpacing(20)

        mode_lbl = QLabel("وضع الترجمة:")
        mode_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 12px;")
        mode_lay.addWidget(mode_lbl)

        self._mode_group = QButtonGroup(self)
        modes = [
            ("missing",    "الناقصة فقط",   "ترجم ما لم يُترجم بعد"),
            ("fresh",      "ترجمة كاملة",    "أعد ترجمة كل شيء من الصفر"),
            ("cache_only", "من الكاش فقط",  "استخدم الكاش دون طلب API"),
        ]
        for i, (val, label, tip) in enumerate(modes):
            rb = QRadioButton(label)
            rb.setProperty("mode_val", val)
            rb.setToolTip(tip)
            if i == 0:
                rb.setChecked(True)
            self._mode_group.addButton(rb, i)
            mode_lay.addWidget(rb)

        mode_lay.addStretch()
        root.addWidget(mode_frame)

        # Progress bar
        self._prog_label = QLabel("جاهز للبدء...")
        self._prog_label.setStyleSheet(
            f"color: {c['muted']}; font-size: 11px; background: transparent; border: none;"
        )
        root.addWidget(self._prog_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(14)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                background: {c['surface']}; border: none; border-radius: 7px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {c['accent']}, stop:1 {c['blue']});
                border-radius: 7px;
            }}
        """)
        root.addWidget(self._progress)

        # Stats row
        stats_row = QHBoxLayout()
        self._lbl_done   = self._stat_lbl("0", "مترجم", c["green"])
        self._lbl_fail   = self._stat_lbl("0", "فشل",   c["accent"])
        self._lbl_total  = self._stat_lbl("0", "إجمالي",c["muted"])
        stats_row.addWidget(self._lbl_done[0])
        stats_row.addWidget(self._lbl_fail[0])
        stats_row.addWidget(self._lbl_total[0])
        stats_row.addStretch()
        root.addLayout(stats_row)

        # Log area
        log_lbl = QLabel("سجل العمليات:")
        log_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 12px;")
        root.addWidget(log_lbl)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("سيظهر هنا تفاصيل الترجمة...")
        root.addWidget(self._log, 1)

        # Buttons
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {c['border']}; border: none;")
        root.addWidget(sep)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._close_btn = QPushButton("إغلاق")
        self._close_btn.setFixedHeight(36)
        self._close_btn.setMinimumWidth(90)
        self._close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._close_btn.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; color: {c['muted']};"
            f" border: 1px solid {c['border']}; border-radius: 8px; padding: 0 18px; }}"
            f"QPushButton:hover {{ background: {c['hover']}; color: {c['primary']}; }}"
        )
        self._close_btn.clicked.connect(self.close)

        self._start_btn = QPushButton("▶  ابدأ الترجمة")
        self._start_btn.setFixedHeight(36)
        self._start_btn.setMinimumWidth(130)
        self._start_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._start_btn.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: #fff;"
            " border: none; border-radius: 8px; font-weight: bold; padding: 0 18px; }"
            f"QPushButton:hover {{ background: {c.get('accent_hover', c['accent'])}; }}"
        )
        self._start_btn.clicked.connect(self._start)

        btn_row.addWidget(self._close_btn)
        btn_row.addSpacing(10)
        btn_row.addWidget(self._start_btn)
        root.addLayout(btn_row)

    def _stat_lbl(self, val: str, title: str, color: str):
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {theme.c['card']}; border: 1px solid {theme.c['border']};"
            " border-radius: 8px; }}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(2)
        v = QLabel(val)
        v.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {color};"
            " background: transparent; border: none;"
        )
        t = QLabel(title)
        t.setStyleSheet(
            f"font-size: 10px; color: {theme.c['muted']};"
            " background: transparent; border: none;"
        )
        lay.addWidget(v)
        lay.addWidget(t)
        return frame, v

    # ── Start / Stop ──────────────────────────────────────────────────────────

    def _get_mode(self) -> str:
        btn = self._mode_group.checkedButton()
        if btn:
            return btn.property("mode_val") or "missing"
        return "missing"

    def _start(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._start_btn.setText("▶  ابدأ الترجمة")
            self._start_btn.setStyleSheet(
                f"QPushButton {{ background: {theme.c['accent']}; color: #fff;"
                " border: none; border-radius: 8px; font-weight: bold; padding: 0 18px; }"
            )
            return

        if not self._engine:
            self._append_log("✗  لا يوجد نموذج مُحمَّل — يرجى تحميل نموذج أولاً", "#e94560")
            return

        mode = self._get_mode()
        self._log.clear()
        self._progress.setValue(0)
        self._lbl_done[1].setText("0")
        self._lbl_fail[1].setText("0")
        self._lbl_total[1].setText("0")
        self._append_log(f"▶  بدء الترجمة — الوضع: {mode}", theme.c["accent"])

        self._worker = TranslateWorker(
            self._game_id, self._game_cfg, self._engine, self._cache, mode
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

        self._start_btn.setText("⏹  إيقاف")
        self._start_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.c['accent']}; color: #fff;"
            " border: none; border-radius: 8px; font-weight: bold; padding: 0 18px; }"
        )

    def _on_progress(self, done: int, total: int, text: str):
        pct = int(done / total * 100) if total else 0
        self._progress.setValue(pct)
        self._prog_label.setText(f"{done} / {total}  ({pct}%)")
        self._lbl_total[1].setText(str(total))
        self._append_log(f"[{done}/{total}]  {text}", theme.c["secondary"])

    def _on_finished(self, translated: int, failed: int):
        self._lbl_done[1].setText(str(translated))
        self._lbl_fail[1].setText(str(failed))
        self._progress.setValue(100)
        self._prog_label.setText("✓  اكتملت الترجمة")
        self._append_log(
            f"✓  انتهت الترجمة:  {translated} ناجحة  /  {failed} فشل",
            theme.c["green"]
        )
        self._start_btn.setText("▶  ابدأ الترجمة")
        self._start_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.c['accent']}; color: #fff;"
            " border: none; border-radius: 8px; font-weight: bold; padding: 0 18px; }"
        )
        self.translation_done.emit(translated)

    def _append_log(self, msg: str, color: str = None):
        c = color or theme.c["primary"]
        self._log.append(f'<span style="color:{c};">{msg}</span>')
        self._log.moveCursor(QTextCursor.End)

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(2000)
        super().closeEvent(event)
