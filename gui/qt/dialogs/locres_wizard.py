"""
gui/qt/dialogs/locres_wizard.py  —  معالج ترجمة .locres  (4 خطوات)

الخطوة 1 : اختيار مجلد التوطين
الخطوة 2 : استخراج  .locres → .locres.txt   (اختياري — UE4LocalizationsTool)
الخطوة 3 : ترجمة النصوص
الخطوة 4 : تجميع    .locres.txt → .locres   (اختياري — UE4LocalizationsTool)
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QLineEdit, QFileDialog, QProgressBar,
    QTextEdit, QScrollArea,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui  import QCursor, QTextCursor

from gui.qt.theme         import theme
from games.locres_patcher import LocresPatcher, LocresTxtFile

# ── Config helpers ─────────────────────────────────────────────────────────────

_CFG = "config.json"

# المسار الافتراضي للأداة بالنسبة لجذر المشروع
_DEFAULT_TOOL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))),
    "tools", "UE4localizationsTool", "UE4localizationsTool.exe"
)


def _load_tool_path() -> str:
    try:
        with open(_CFG, encoding="utf-8") as f:
            saved = json.load(f).get("tools", {}).get("ue4loc_tool", "")
            if saved:
                return saved
    except Exception:
        pass
    return _DEFAULT_TOOL


def _save_tool_path(path: str):
    try:
        with open(_CFG, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg.setdefault("tools", {})["ue4loc_tool"] = path
        with open(_CFG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ── Tool worker (extract / compile) ───────────────────────────────────────────

class _ToolWorker(QThread):
    """تشغيل UE4LocalizationsTool على مجموعة ملفات (export أو import)."""
    logged   = Signal(str, str)   # msg, color_key
    progress = Signal(int, int)   # done, total
    finished = Signal(bool, int)  # all_ok, count_done

    def __init__(self, tool_path: str, files: list[str], mode: str):
        super().__init__()
        self._tool  = tool_path   # مسار UE4LocalizationsTool.exe
        self._files = files       # قائمة الملفات
        self._mode  = mode        # "export"  أو  "import"

    def run(self):
        done  = 0
        total = len(self._files)
        for i, path in enumerate(self._files):
            fname   = os.path.basename(path)
            workdir = os.path.dirname(path) or "."

            # Expected output path
            if self._mode == "-import":
                out_path = path[:-4]        # Game.locres.txt → Game.locres
            else:
                out_path = path + ".txt"    # Game.locres     → Game.locres.txt

            # Print the full command exactly as run
            cmd = [self._tool, self._mode, path]
            cmd_display = " ".join(
                f'"{c}"' if " " in c else c for c in cmd
            )
            self.logged.emit(f"⚡  {cmd_display}", "muted")

            # For import: tool NEEDS the original .locres to exist (reads + updates it).
            # Create a backup if not already present so the user can restore if needed.
            if self._mode == "-import" and os.path.isfile(out_path):
                out_bak = out_path + ".bak"
                if not os.path.isfile(out_bak):
                    shutil.copy2(out_path, out_bak)
                    self.logged.emit(
                        f"💾  نسخة احتياطية: {os.path.basename(out_bak)}", "muted")

            try:
                r = subprocess.run(
                    cmd,
                    capture_output=True, text=True, timeout=120,
                    cwd=workdir,
                )
                tool_out = (r.stdout + r.stderr).strip()
                out_name = os.path.basename(out_path)

                if r.returncode == 0:
                    self.logged.emit(f"✅  {fname}  →  {out_name}", "green")
                    if tool_out:
                        self.logged.emit(f"    {tool_out}", "muted")
                    if os.path.isfile(out_path):
                        done += 1
                    else:
                        self.logged.emit(
                            f"⚠  الأداة أنهت بنجاح لكن الملف الناتج غير موجود: {out_name}",
                            "yellow")
                else:
                    err = (r.stderr or r.stdout or "").strip() or f"كود {r.returncode}"
                    self.logged.emit(f"❌  {fname}: {err}", "accent")

            except Exception as exc:
                self.logged.emit(f"❌  {fname}: {exc}", "accent")

            self.progress.emit(i + 1, total)
        self.finished.emit(done == total, done)


# ── Translation worker ─────────────────────────────────────────────────────────

class _TranslateWorker(QThread):
    """يقرأ .locres.txt / .locres ثم يترجم ويكتب — نفس منطق LocresTranslateWorker."""
    progress = Signal(int, int)
    logged   = Signal(str, str)
    finished = Signal(bool, int, int)  # ok, replaced, total_count

    def __init__(self, txt_files: list[str], bin_files: list[str],
                 engine, cache, game_id: str, mode: str):
        super().__init__()
        self._txt   = txt_files
        self._bin   = bin_files
        self._eng   = engine
        self._cache = cache
        self._gid   = game_id
        self._mode  = mode
        import threading
        self._stop  = False
        self._pause = threading.Event()
        self._pause.set()

    def pause(self):  self._pause.clear()
    def resume(self): self._pause.set()
    def stop(self):
        self._stop = True
        self._pause.set()

    def run(self):
        try:
            file_entries: dict[str, list] = {}
            seen: dict[str, None] = {}

            for path in self._txt:
                entries = LocresTxtFile.read(path)
                self.logged.emit(
                    f"  📄 {os.path.basename(path)}: {len(entries)} مدخلة (txt)", "muted")
                file_entries[path] = entries
                for e in entries:
                    t = e.value.strip()
                    if t:
                        seen[t] = None

            for path in self._bin:
                def _lg(m, _p=path): self.logged.emit(m, "muted")
                entries = LocresPatcher.read(path, logger=_lg)
                self.logged.emit(
                    f"  📄 {os.path.basename(path)}: {len(entries)} مدخلة (bin)", "muted")
                file_entries[path] = entries
                for e in entries:
                    t = e.value.strip()
                    if t:
                        seen[t] = None

            unique  = list(seen.keys())
            total_u = len(unique)
            total_e = sum(len(v) for v in file_entries.values())

            if total_u == 0:
                self.logged.emit("✅  لا توجد نصوص قابلة للترجمة", "green")
                self.finished.emit(True, 0, 0)
                return

            dup = total_e - total_u
            if dup > 0:
                self.logged.emit(
                    f"📝  {total_e:,} مدخلة إجمالاً  ←  {total_u:,} نص فريد"
                    f" + {dup:,} مكرر/فارغ (ستُطبَّق الترجمة على الكل)", "secondary")
            else:
                self.logged.emit(f"📝  {total_u:,} نص فريد للترجمة", "secondary")

            # ── كاش ──────────────────────────────────────────────────────
            translations: dict[str, str] = {}
            cache_hits = 0
            try:
                active_model = self._eng.get_active_model() or "unknown"
            except Exception:
                active_model = "unknown"

            if self._cache:
                for txt in unique:
                    ar = self._cache.get(self._gid, txt)
                    if ar:
                        translations[txt] = ar
                        cache_hits += 1
            self.logged.emit(f"💾  كاش: {cache_hits:,} نص موجود مسبقاً", "teal")

            # ── اختيار النصوص حسب الوضع ─────────────────────────────────
            if self._mode == "cache_only":
                missing = []
                self.logged.emit("☐  وضع الكاش فقط — بدون استدعاء API", "muted")
            elif self._mode == "full":
                missing = unique
                self.logged.emit(f"◆  ترجمة كاملة من الصفر — {total_u:,} نص", "blue")
            else:
                missing = [t for t in unique if t not in translations]
                self.logged.emit(
                    f"◆  استكمال المفقود — {len(missing):,} نص يحتاج ترجمة", "orange")

            # ── ترجمة ─────────────────────────────────────────────────────
            n = len(missing)
            for i, txt in enumerate(missing):
                self._pause.wait()
                if self._stop:
                    self.logged.emit("⏹  توقف بطلب المستخدم", "yellow")
                    break
                try:
                    ar = self._eng.translate(txt)
                    if ar and ar != txt:
                        translations[txt] = ar
                        if self._cache:
                            self._cache.put(self._gid, txt, ar, active_model)
                except Exception as exc:
                    self.logged.emit(f"⚠  خطأ: {exc}", "accent")

                d = i + 1
                self.progress.emit(d, n if n > 0 else 1)
                if d % 20 == 0 or d == n:
                    self.logged.emit(
                        f"✅  {d:,} / {n:,}  ({int(d / max(n, 1) * 100)}%)", "green")

            # ── تطبيق على الملفات ─────────────────────────────────────────
            replaced_total = 0
            count_total    = 0
            for path in self._txt:
                rep, cnt = LocresTxtFile.patch(path, path, translations)
                replaced_total += rep
                count_total    += cnt
                self.logged.emit(
                    f"📄  {os.path.basename(path)}: {rep:,} / {cnt:,} مدخلة ← مكتوبة", "teal")
            for path in self._bin:
                rep, cnt = LocresPatcher.patch(path, path, translations)
                replaced_total += rep
                count_total    += cnt
                self.logged.emit(
                    f"📄  {os.path.basename(path)}: {rep:,} / {cnt:,} مدخلة ← مكتوبة", "secondary")

            self.finished.emit(True, replaced_total, count_total)

        except Exception as exc:
            self.logged.emit(f"❌  خطأ فادح: {exc}", "accent")
            self.finished.emit(False, 0, 0)


# ── UI helpers ─────────────────────────────────────────────────────────────────

def _btn(label: str, color: str, h: int = 34) -> QPushButton:
    b = QPushButton(label)
    b.setFixedHeight(h)
    b.setCursor(QCursor(Qt.PointingHandCursor))
    b.setStyleSheet(f"""
        QPushButton {{
            background: rgba(0,0,0,31); color: {color};
            border: 1px solid {color}; border-radius: 7px;
            font-weight: bold; padding: 0 14px;
        }}
        QPushButton:hover    {{ background: {color}; color: #fff; }}
        QPushButton:disabled {{ opacity: 0.35; }}
    """)
    return b


def _step_card(number: str, title: str, c: dict) -> tuple[QFrame, QVBoxLayout, QLabel]:
    """يُنشئ بطاقة خطوة. يُعيد (card, body_layout, status_lbl)."""
    card = QFrame()
    card.setStyleSheet(
        f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']};"
        " border-radius: 10px; }"
    )
    vlay = QVBoxLayout(card)
    vlay.setContentsMargins(0, 0, 0, 0)
    vlay.setSpacing(0)

    # ── رأس البطاقة ──────────────────────────────────────────────────────
    hdr = QFrame()
    hdr.setFixedHeight(42)
    hdr.setStyleSheet(
        f"QFrame {{ background: {c['surface']};"
        f" border-top-left-radius: 10px; border-top-right-radius: 10px;"
        f" border-bottom-left-radius: 0; border-bottom-right-radius: 0;"
        f" border-bottom: 1px solid {c['border']}; }}"
    )
    hl = QHBoxLayout(hdr)
    hl.setContentsMargins(16, 0, 16, 0)
    hl.setSpacing(10)

    num_lbl = QLabel(number)
    num_lbl.setStyleSheet(
        f"background: {c['accent']}; color: #fff; border-radius: 10px;"
        " font-weight: bold; font-size: 11px; padding: 2px 8px; border: none;"
    )
    num_lbl.setFixedSize(26, 22)
    num_lbl.setAlignment(Qt.AlignCenter)

    ttl = QLabel(title)
    ttl.setStyleSheet(
        f"font-size: 12px; font-weight: bold; color: {c['primary']}; border: none;"
    )

    status_lbl = QLabel("—")
    status_lbl.setStyleSheet(
        f"font-size: 10px; color: {c['muted']}; border: none;"
    )

    hl.addWidget(num_lbl)
    hl.addWidget(ttl)
    hl.addStretch()
    hl.addWidget(status_lbl)
    vlay.addWidget(hdr)

    # ── جسم البطاقة ──────────────────────────────────────────────────────
    body = QFrame()
    body.setStyleSheet("QFrame { background: transparent; border: none; }")
    body_lay = QVBoxLayout(body)
    body_lay.setContentsMargins(16, 12, 16, 14)
    body_lay.setSpacing(10)
    vlay.addWidget(body)

    return card, body_lay, status_lbl


def _log_widget(c: dict, h: int = 100) -> QTextEdit:
    w = QTextEdit()
    w.setReadOnly(True)
    w.setFixedHeight(h)
    w.setStyleSheet(
        f"QTextEdit {{ background: {c['bg']}; color: {c['secondary']};"
        f" border: 1px solid {c['border']}; border-radius: 6px;"
        f" font-family: Consolas, monospace; font-size: 10px; padding: 6px; }}"
    )
    return w


def _tool_row(tool_edit: QLineEdit, c: dict) -> QHBoxLayout:
    """صف مسار UE4LocalizationsTool + زر تصفح."""
    row = QHBoxLayout()
    row.setSpacing(8)
    lbl = QLabel("UE4LocalizationsTool:")
    lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px; border: none;")
    browse = _btn("📂", c["blue"], 30)
    browse.setFixedWidth(36)
    browse.setToolTip("تصفح لاختيار UE4localizationsTool.exe")

    def _pick():
        path, _ = QFileDialog.getOpenFileName(
            None, "اختر UE4localizationsTool.exe", "",
            "EXE Files (*.exe);;All Files (*)"
        )
        if path:
            tool_edit.setText(path)
            _save_tool_path(path)

    browse.clicked.connect(_pick)
    row.addWidget(lbl)
    row.addWidget(tool_edit, 1)
    row.addWidget(browse)
    return row


# ── Main Wizard ────────────────────────────────────────────────────────────────

class LocresWizard(QWidget):
    """
    معالج ترجمة .locres — 4 خطوات:
    1) اختيار المجلد   2) استخراج (اختياري)   3) ترجمة   4) تجميع (اختياري)
    """
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

        # state
        self._txt_files: list[str] = []
        self._bin_files: list[str] = []
        self._tool_worker:  _ToolWorker      | None = None
        self._trans_worker: _TranslateWorker | None = None
        self._trans_mode  = "missing"
        self._trans_started = False
        self._elapsed_timer: QTimer | None = None
        self._start_time = 0.0

        self.setWindowTitle(f"📄  معالج .locres — {game_name}")
        self.setMinimumSize(900, 720)
        self.resize(940, 780)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self._build()
        self._scan_folder()

    # ═══════════════════════════════════════════════════════════════════════════
    # Build
    # ═══════════════════════════════════════════════════════════════════════════

    def _build(self):
        c = theme.c
        self.setStyleSheet(f"""
            QWidget   {{ background: {c['bg']}; }}
            QLabel    {{ color: {c['primary']}; background: transparent; border: none; }}
            QLineEdit {{
                background: {c['surface']}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 6px;
                padding: 4px 8px; font-size: 11px;
            }}
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header(c))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        body_w = QWidget()
        body_w.setStyleSheet("background: transparent;")
        blay = QVBoxLayout(body_w)
        blay.setContentsMargins(20, 20, 20, 20)
        blay.setSpacing(14)

        blay.addWidget(self._build_step1(c))
        blay.addWidget(self._build_step2(c))
        blay.addWidget(self._build_step3(c))
        blay.addWidget(self._build_step4(c))
        blay.addStretch()

        scroll.setWidget(body_w)
        root.addWidget(scroll, 1)
        root.addWidget(self._build_statusbar(c))

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self, c: dict) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(58)
        bar.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-bottom: 1px solid {c['border']}; }}"
        )
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(22, 0, 22, 0)

        t = QLabel("📄  معالج ترجمة .locres")
        t.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {c['teal']};")
        hl.addWidget(t)
        hl.addSpacing(16)

        self._header_info = QLabel(
            f"🎮 {self._game_name}   │   📂 {os.path.basename(self._folder)}"
        )
        self._header_info.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        hl.addWidget(self._header_info, 1)
        return bar

    # ── Step 1: Folder ────────────────────────────────────────────────────────

    def _build_step1(self, c: dict) -> QFrame:
        card, body, self._s1_status = _step_card("1", "اختيار مجلد التوطين", c)

        # path row
        row = QHBoxLayout()
        row.setSpacing(8)
        self._folder_edit = QLineEdit(self._folder)
        self._folder_edit.setReadOnly(True)
        self._folder_edit.setPlaceholderText("لم يُختر مجلد بعد…")
        browse_btn = _btn("📂  تصفح", c["blue"])
        browse_btn.clicked.connect(self._pick_folder)
        restore_btn = _btn("↩  استعادة .bak", c["yellow"])
        restore_btn.setToolTip(
            "استعادة ملفات .locres.txt من نسخ .bak\n"
            "(استخدم هذا إذا كانت الملفات تحتوي على ترجمة سابقة وتريد إعادة الترجمة من الإنجليزي)"
        )
        restore_btn.clicked.connect(self._restore_txt_backups)
        row.addWidget(self._folder_edit, 1)
        row.addWidget(restore_btn)
        row.addWidget(browse_btn)
        body.addLayout(row)

        self._s1_summary = QLabel("—")
        self._s1_summary.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        body.addWidget(self._s1_summary)
        return card

    # ── Step 2: Extract ───────────────────────────────────────────────────────

    def _build_step2(self, c: dict) -> QFrame:
        card, body, self._s2_status = _step_card(
            "2", "استخراج النصوص  .locres → .locres.txt  (اختياري)", c)

        hint = QLabel(
            "استخدم هذه الخطوة إذا كان لديك ملفات .locres ثنائية ولا تملك .locres.txt مقابلها."
        )
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        hint.setWordWrap(True)
        body.addWidget(hint)

        # tool path
        self._s2_tool_edit = QLineEdit(_load_tool_path())
        self._s2_tool_edit.setPlaceholderText("مسار UE4localizationsTool.exe …")
        self._s2_tool_edit.textChanged.connect(lambda p: _save_tool_path(p.strip()))
        body.addLayout(_tool_row(self._s2_tool_edit, c))

        # extract button + progress
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self._s2_run_btn = _btn("▶  استخراج  .locres → .locres.txt", c["teal"])
        self._s2_run_btn.clicked.connect(self._run_extract)
        self._s2_prog = QProgressBar()
        self._s2_prog.setRange(0, 100)
        self._s2_prog.setValue(0)
        self._s2_prog.setFixedHeight(8)
        self._s2_prog.setTextVisible(False)
        self._s2_prog.setStyleSheet(
            f"QProgressBar {{ background: {c['surface']}; border: none; border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {c['teal']}; border-radius: 4px; }}"
        )
        row2.addWidget(self._s2_run_btn)
        row2.addWidget(self._s2_prog, 1)
        body.addLayout(row2)

        self._s2_log = _log_widget(c, 90)
        body.addWidget(self._s2_log)
        return card

    # ── Step 3: Translate ─────────────────────────────────────────────────────

    def _build_step3(self, c: dict) -> QFrame:
        card, body, self._s3_status = _step_card("3", "ترجمة النصوص", c)

        # Mode selector
        body.addWidget(self._build_mode_selector(c))

        # Progress row
        prog_row = QHBoxLayout()
        self._s3_count = QLabel("— / —")
        self._s3_count.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {c['primary']};"
        )
        self._s3_status_lbl = QLabel("جاهز — اضغط «بدء الترجمة»")
        self._s3_status_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        prog_row.addWidget(self._s3_count)
        prog_row.addStretch()
        prog_row.addWidget(self._s3_status_lbl)
        body.addLayout(prog_row)

        self._s3_prog = QProgressBar()
        self._s3_prog.setRange(0, 100)
        self._s3_prog.setValue(0)
        self._s3_prog.setFixedHeight(10)
        self._s3_prog.setTextVisible(False)
        self._s3_prog.setStyleSheet(f"""
            QProgressBar {{ background: {c['surface']}; border: none; border-radius: 5px; }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {c['teal']}, stop:1 {c['blue']});
                border-radius: 5px;
            }}
        """)
        body.addWidget(self._s3_prog)

        # Stats chips
        chips = QHBoxLayout()
        chips.setSpacing(20)
        def _chip(txt, key):
            l = QLabel(txt)
            l.setStyleSheet(
                f"color: {c[key]}; font-size: 10px; background: transparent; border: none;"
            )
            return l
        self._chip_cache = _chip("💾  كاش: —",    "teal")
        self._chip_new   = _chip("🌐  جديد: —",   "muted")
        self._chip_done  = _chip("✅  مكتمل: 0",  "muted")
        self._chip_fail  = _chip("⚠  فشل: 0",    "muted")
        self._chip_time  = _chip("⏱  —",          "muted")
        for ch in (self._chip_cache, self._chip_new, self._chip_done,
                   self._chip_fail, self._chip_time):
            chips.addWidget(ch)
        chips.addStretch()
        body.addLayout(chips)

        # Buttons
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        self._s3_start  = _btn("▶  بدء الترجمة",  c["teal"])
        self._s3_pause  = _btn("⏸  إيقاف مؤقت",  c["yellow"])
        self._s3_resume = _btn("▶▶  استئناف",      c["green"])
        self._s3_stop   = _btn("⏹  إيقاف كامل",  c["muted"])
        self._s3_pause.setEnabled(False)
        self._s3_resume.setEnabled(False)
        self._s3_stop.setEnabled(False)
        self._s3_start.clicked.connect(self._trans_start)
        self._s3_pause.clicked.connect(self._trans_pause)
        self._s3_resume.clicked.connect(self._trans_resume)
        self._s3_stop.clicked.connect(self._trans_stop)
        for b in (self._s3_start, self._s3_pause, self._s3_resume, self._s3_stop):
            ctrl.addWidget(b)
        ctrl.addStretch()
        body.addLayout(ctrl)

        self._s3_log = _log_widget(c, 140)
        body.addWidget(self._s3_log)
        return card

    def _build_mode_selector(self, c: dict) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: transparent; border: none; }")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        lbl = QLabel("⚙️  وضع الترجمة")
        lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px; font-weight: bold;")
        lay.addWidget(lbl)

        row = QHBoxLayout()
        row.setSpacing(8)
        modes = [
            ("missing",    "◆  استكمال المفقود",      c["orange"]),
            ("full",       "◆  ترجمة كاملة من الصفر", c["blue"]),
            ("cache_only", "☐  من الكاش فقط",          c["muted"]),
        ]
        self._mode_btns: dict[str, QPushButton] = {}
        for key, label, color in modes:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == "missing")
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            self._mode_btns[key] = btn
            btn.clicked.connect(lambda _c, k=key: self._select_mode(k))
            row.addWidget(btn)
            self._style_mode_btn(btn, color, c, checked=(key == "missing"))
        row.addStretch()
        lay.addLayout(row)
        return frame

    def _style_mode_btn(self, btn, color, c, checked):
        if checked:
            btn.setStyleSheet(f"""
                QPushButton {{ background: {color}33; color: {color};
                    border: 2px solid {color}; border-radius: 7px;
                    font-weight: bold; font-size: 10px; padding: 5px 14px; }}
                QPushButton:hover {{ background: {color}44; }}
                QPushButton:disabled {{ opacity: 0.4; }}
            """)
        else:
            btn.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {c['muted']};
                    border: 1px solid {c['border']}; border-radius: 7px;
                    font-size: 10px; padding: 5px 14px; }}
                QPushButton:hover {{ background: {color}15; color: {color};
                    border-color: {color}88; }}
                QPushButton:disabled {{ opacity: 0.4; }}
            """)

    def _select_mode(self, key: str):
        c = theme.c
        colors = {"missing": c["orange"], "full": c["blue"], "cache_only": c["muted"]}
        self._trans_mode = key
        for k, btn in self._mode_btns.items():
            btn.setChecked(k == key)
            self._style_mode_btn(btn, colors[k], c, checked=(k == key))

    # ── Step 4: Compile ───────────────────────────────────────────────────────

    def _build_step4(self, c: dict) -> QFrame:
        card, body, self._s4_status = _step_card(
            "4", "تجميع النصوص  .locres.txt → .locres  (اختياري)", c)

        hint = QLabel(
            "بعد الترجمة، حوِّل .locres.txt المُترجَم إلى الصيغة الثنائية التي تقرأها اللعبة."
        )
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        hint.setWordWrap(True)
        body.addWidget(hint)

        # tool path (shared with step 2 — same tool)
        self._s4_tool_edit = QLineEdit(_load_tool_path())
        self._s4_tool_edit.setPlaceholderText("مسار UE4localizationsTool.exe …")
        self._s4_tool_edit.textChanged.connect(self._sync_tool_path)
        body.addLayout(_tool_row(self._s4_tool_edit, c))

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self._s4_run_btn = _btn("▶  تجميع  .locres.txt → .locres", c["purple"])
        self._s4_run_btn.clicked.connect(self._run_compile)
        self._s4_prog = QProgressBar()
        self._s4_prog.setRange(0, 100)
        self._s4_prog.setValue(0)
        self._s4_prog.setFixedHeight(8)
        self._s4_prog.setTextVisible(False)
        self._s4_prog.setStyleSheet(
            f"QProgressBar {{ background: {c['surface']}; border: none; border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {c['purple']}; border-radius: 4px; }}"
        )
        row2.addWidget(self._s4_run_btn)
        row2.addWidget(self._s4_prog, 1)
        body.addLayout(row2)

        self._s4_log = _log_widget(c, 90)
        body.addWidget(self._s4_log)
        return card

    # ── Status bar ────────────────────────────────────────────────────────────

    def _build_statusbar(self, c: dict) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(36)
        bar.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-top: 1px solid {c['border']}; }}"
        )
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(18, 0, 18, 0)
        self._status_lbl = QLabel("اختر مجلد التوطين للبدء")
        self._status_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        hl.addWidget(self._status_lbl)
        return bar

    # ═══════════════════════════════════════════════════════════════════════════
    # Step 1 logic — Folder
    # ═══════════════════════════════════════════════════════════════════════════

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "اختر مجلد Localization", self._folder or ""
        )
        if folder:
            self._folder = folder
            self._folder_edit.setText(folder)
            self._scan_folder()

    def _restore_txt_backups(self):
        """استعادة .locres.txt من .locres.txt.bak لكل الملفات الموجودة."""
        if not self._folder or not os.path.isdir(self._folder):
            self._set_status("⚠  اختر مجلداً أولاً")
            return
        files = LocresPatcher.find_locres_files(self._folder)
        txt_files = [f for f in files if f.lower().endswith(".locres.txt")]
        if not txt_files:
            self._set_status("⚠  لا توجد ملفات .locres.txt في هذا المجلد")
            return
        restored, missing = 0, 0
        for txt in txt_files:
            bak = txt + ".bak"
            if os.path.isfile(bak):
                shutil.copy2(bak, txt)
                restored += 1
            else:
                missing += 1
        if restored:
            self._scan_folder()
            self._set_status(
                f"✅  تمت استعادة {restored} ملف من .bak"
                + (f"  │  ⚠ {missing} بدون نسخة احتياطية" if missing else "")
            )
        else:
            self._set_status("⚠  لا توجد ملفات .bak — ربما لم تُترجَم الملفات بعد")

    def _scan_folder(self):
        if not self._folder or not os.path.isdir(self._folder):
            return
        files = LocresPatcher.find_locres_files(self._folder)
        all_txt = [f for f in files if f.lower().endswith(".locres.txt")]
        all_bin = [f for f in files if not f.lower().endswith(".locres.txt")]

        # If a .locres.txt exists alongside a .locres (same base name),
        # exclude the binary — translate .locres.txt then compile via tool.
        # This avoids writing a potentially incompatible legacy binary format.
        txt_bases = {f[:-4].lower() for f in all_txt}  # strip ".txt" → ".locres" path
        covered   = [f for f in all_bin if f.lower() in txt_bases]
        self._txt_files = all_txt
        self._bin_files = [f for f in all_bin if f.lower() not in txt_bases]

        c = theme.c
        parts = []
        if self._bin_files:
            parts.append(f"🔵 {len(self._bin_files)} ملف .locres")
        if self._txt_files:
            parts.append(f"📄 {len(self._txt_files)} ملف .locres.txt")
        if covered:
            parts.append(f"({len(covered)} ثنائي ← يُعالَج عبر .txt)")

        if not self._bin_files and not self._txt_files:
            self._s1_summary.setText("⚠  لم تُعثر على ملفات .locres / .locres.txt")
            self._s1_summary.setStyleSheet(f"color: {c['yellow']}; font-size: 11px;")
            self._s1_status.setText("⚠  لا يوجد")
        else:
            summary = "  │  ".join(parts)
            self._s1_summary.setText(summary)
            self._s1_summary.setStyleSheet(f"color: {c['teal']}; font-size: 11px;")
            self._s1_status.setText("✅  جاهز")
            self._s1_status.setStyleSheet(f"color: {c['green']}; font-size: 10px;")

        # Step 2 only relevant if there are binary files without a matching .txt
        self._s2_run_btn.setEnabled(bool(self._bin_files))
        self._set_status(f"وُجد {len(files)} ملف في: {os.path.basename(self._folder)}")

    # ═══════════════════════════════════════════════════════════════════════════
    # Step 2 logic — Extract
    # ═══════════════════════════════════════════════════════════════════════════

    def _run_extract(self):
        tool = self._s2_tool_edit.text().strip()
        if not tool or not os.path.isfile(tool):
            self._log(self._s2_log, "❌  حدّد مسار UE4localizationsTool.exe أولاً", "accent")
            return
        if not self._bin_files:
            self._log(self._s2_log, "⚠  لا توجد ملفات .locres للاستخراج", "yellow")
            return

        self._s2_run_btn.setEnabled(False)
        self._s2_prog.setValue(0)
        self._s2_status.setText("🔄  جارٍ…")
        self._log(self._s2_log,
                  f"🚀  استخراج {len(self._bin_files)} ملف .locres…", "teal")

        self._tool_worker = _ToolWorker(tool, self._bin_files, "export")
        self._tool_worker.logged.connect(
            lambda m, k: self._log(self._s2_log, m, k))
        self._tool_worker.progress.connect(
            lambda d, t: self._s2_prog.setValue(int(d / t * 100)))
        self._tool_worker.finished.connect(self._on_extract_done)
        self._tool_worker.start()

    def _on_extract_done(self, ok: bool, count: int):
        c = theme.c
        if ok:
            self._s2_status.setText(f"✅  {count} ملف")
            self._s2_status.setStyleSheet(f"color: {c['green']}; font-size: 10px;")
            self._s2_prog.setValue(100)
            self._log(self._s2_log,
                      f"✅  اكتمل الاستخراج — {count} ملف .locres.txt جاهز", "green")
            # Rescan to pick up new .locres.txt files
            self._scan_folder()
        else:
            self._s2_status.setText("❌  خطأ")
            self._s2_status.setStyleSheet(f"color: {c['accent']}; font-size: 10px;")
            self._log(self._s2_log, "❌  فشل الاستخراج — راجع السجل", "accent")
        self._s2_run_btn.setEnabled(bool(self._bin_files))
        self._set_status("اكتملت خطوة الاستخراج")

    # ═══════════════════════════════════════════════════════════════════════════
    # Step 3 logic — Translate
    # ═══════════════════════════════════════════════════════════════════════════

    def _trans_start(self):
        if self._trans_started:
            return
        if not self._txt_files and not self._bin_files:
            self._log(self._s3_log, "⚠  لا توجد ملفات — اختر مجلداً أولاً", "yellow")
            return
        if not self._engine:
            self._log(self._s3_log,
                      "❌  لا يوجد نموذج مُحمَّل — فعّل نموذجاً من صفحة النماذج", "accent")
            return

        self._trans_started = True
        for btn in self._mode_btns.values():
            btn.setEnabled(False)
        self._s3_start.setEnabled(False)
        self._s3_pause.setEnabled(True)
        self._s3_stop.setEnabled(True)
        c = theme.c
        self._s3_status_lbl.setText("🔄  جاري الترجمة…")
        self._s3_status_lbl.setStyleSheet(f"color: {c['yellow']}; font-size: 11px;")
        self._s3_status.setText("🔄  جارٍ…")

        self._trans_worker = _TranslateWorker(
            self._txt_files, self._bin_files,
            self._engine, self._cache, self._game_id, self._trans_mode
        )
        self._trans_worker.logged.connect(
            lambda m, k: self._log(self._s3_log, m, k))
        self._trans_worker.progress.connect(self._on_trans_progress)
        self._trans_worker.finished.connect(self._on_trans_done)
        self._trans_worker.start()

        self._start_time = time.time()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self._elapsed_timer.start(1000)

        from gui.qt.dialogs.translation_window import _resolve_model_display
        model = _resolve_model_display(self._engine)
        self._log(self._s3_log, f"🚀  بدأت الترجمة — النموذج: {model}", "teal")

    def _trans_pause(self):
        if self._trans_worker:
            self._trans_worker.pause()
        self._s3_pause.setEnabled(False)
        self._s3_resume.setEnabled(True)
        self._s3_status_lbl.setText("⏸  متوقف مؤقتاً")
        self._log(self._s3_log, "⏸  إيقاف مؤقت", "yellow")

    def _trans_resume(self):
        if self._trans_worker:
            self._trans_worker.resume()
        self._s3_pause.setEnabled(True)
        self._s3_resume.setEnabled(False)
        self._s3_status_lbl.setText("🔄  جاري الترجمة…")
        self._log(self._s3_log, "▶  تم الاستئناف", "green")

    def _trans_stop(self):
        if self._trans_worker:
            self._trans_worker.stop()
        self._s3_pause.setEnabled(False)
        self._s3_resume.setEnabled(False)
        self._s3_stop.setEnabled(False)
        self._log(self._s3_log, "⏹  تم إيقاف الترجمة", "yellow")

    def _on_trans_progress(self, done: int, total: int):
        if total <= 0:
            return
        c = theme.c
        pct = int(done / total * 100)
        self._s3_prog.setValue(pct)
        self._s3_count.setText(f"{done:,} / {total:,}")
        self._chip_done.setText(f"✅  مكتمل: {done:,}")
        self._chip_done.setStyleSheet(
            f"color: {c['teal']}; font-size: 10px; background: transparent; border: none;")

    def _update_elapsed(self):
        if not self._start_time:
            return
        elapsed = time.time() - self._start_time
        h, rem = divmod(int(elapsed), 3600)
        m, s   = divmod(rem, 60)
        t = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        self._chip_time.setText(f"⏱  {t}")

    def _on_trans_done(self, ok: bool, replaced: int, total_count: int):
        if self._elapsed_timer:
            self._elapsed_timer.stop()
            self._elapsed_timer = None

        c = theme.c
        self._s3_pause.setEnabled(False)
        self._s3_resume.setEnabled(False)
        self._s3_stop.setEnabled(False)
        self._s3_start.setEnabled(True)
        for btn in self._mode_btns.values():
            btn.setEnabled(True)
        self._trans_started = False

        if ok:
            self._s3_prog.setValue(100)
            self._s3_status_lbl.setText("✅  اكتملت الترجمة")
            self._s3_status_lbl.setStyleSheet(f"color: {c['green']}; font-size: 11px;")
            self._s3_status.setText(f"✅  {replaced:,}")
            self._s3_status.setStyleSheet(f"color: {c['green']}; font-size: 10px;")
            self._log(self._s3_log,
                      f"✅  اكتملت — طُبِّق {replaced:,} ترجمة على {total_count:,} مدخلة",
                      "green")
        else:
            self._s3_status_lbl.setText("⚠  انتهت مع أخطاء")
            self._s3_status_lbl.setStyleSheet(f"color: {c['accent']}; font-size: 11px;")
            self._s3_status.setText("⚠  خطأ")

        self._set_status(f"اكتملت الترجمة — {replaced:,} نص")
        self.done.emit(replaced, total_count)

    # ═══════════════════════════════════════════════════════════════════════════
    # Step 4 logic — Compile
    # ═══════════════════════════════════════════════════════════════════════════

    def _sync_tool_path(self, path: str):
        """يزامن مسار الأداة بين الخطوتين 2 و4."""
        p = path.strip()
        _save_tool_path(p)
        if self._s2_tool_edit.text().strip() != p:
            self._s2_tool_edit.blockSignals(True)
            self._s2_tool_edit.setText(p)
            self._s2_tool_edit.blockSignals(False)

    def _run_compile(self):
        tool = self._s4_tool_edit.text().strip()
        if not tool or not os.path.isfile(tool):
            self._log(self._s4_log, "❌  حدّد مسار UE4localizationsTool.exe أولاً", "accent")
            return

        # الملفات المطلوب تجميعها: كل .locres.txt موجودة
        txt_files = self._txt_files
        if not txt_files:
            self._log(self._s4_log,
                      "⚠  لا توجد ملفات .locres.txt — نفّذ الخطوة 2 أو الترجمة أولاً",
                      "yellow")
            return

        self._s4_run_btn.setEnabled(False)
        self._s4_prog.setValue(0)
        self._s4_status.setText("🔄  جارٍ…")
        self._log(self._s4_log,
                  f"🚀  تجميع {len(txt_files)} ملف .locres.txt…", "purple")

        self._tool_worker = _ToolWorker(tool, txt_files, "-import")
        self._tool_worker.logged.connect(
            lambda m, k: self._log(self._s4_log, m, k))
        self._tool_worker.progress.connect(
            lambda d, t: self._s4_prog.setValue(int(d / t * 100)))
        self._tool_worker.finished.connect(self._on_compile_done)
        self._tool_worker.start()

    def _on_compile_done(self, ok: bool, count: int):
        c = theme.c
        self._s4_run_btn.setEnabled(True)
        if ok:
            self._s4_prog.setValue(100)
            self._s4_status.setText(f"✅  {count} ملف")
            self._s4_status.setStyleSheet(f"color: {c['green']}; font-size: 10px;")
            self._log(self._s4_log,
                      f"✅  تم تجميع {count} ملف .locres — جاهز للعبة!", "green")
            # Show where the compiled files landed
            for p in self._txt_files:
                out = p[:-4]   # strip ".txt"  → .locres path
                if os.path.isfile(out):
                    self._log(self._s4_log, f"📁  {out}", "teal")
                else:
                    self._log(self._s4_log,
                              f"⚠  لم يُعثر على الناتج: {out}", "yellow")
            self._set_status(f"✅  تم التجميع — {count} ملف .locres جاهز للعبة")
        else:
            self._s4_status.setText("❌  خطأ")
            self._s4_status.setStyleSheet(f"color: {c['accent']}; font-size: 10px;")
            self._log(self._s4_log, "❌  فشل التجميع — راجع السجل", "accent")

    # ═══════════════════════════════════════════════════════════════════════════
    # Utilities
    # ═══════════════════════════════════════════════════════════════════════════

    def _log(self, widget: QTextEdit, msg: str, color_key: str = "secondary"):
        color = theme.c.get(color_key, theme.c["secondary"])
        widget.append(f'<span style="color:{color};">{msg}</span>')
        widget.moveCursor(QTextCursor.End)

    def _set_status(self, msg: str):
        self._status_lbl.setText(msg)

    def closeEvent(self, event):
        if self._elapsed_timer:
            self._elapsed_timer.stop()
        if self._trans_worker and self._trans_worker.isRunning():
            self._trans_worker.stop()
            self._trans_worker.wait(2000)
        if self._tool_worker and self._tool_worker.isRunning():
            self._tool_worker.wait(2000)
        super().closeEvent(event)
