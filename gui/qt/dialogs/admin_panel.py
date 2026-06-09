"""
gui/qt/dialogs/admin_panel.py  —  لوحة الإدارة (المرحلة 8)
"""

from __future__ import annotations
import hashlib
import json
import os
import shutil
import sys
import time

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QLineEdit, QTextEdit, QScrollArea, QTabWidget,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFileDialog, QMessageBox, QSizePolicy,
    QToolButton, QApplication, QComboBox,
)
from PySide6.QtCore  import Qt, Signal, QThread, QTimer
from PySide6.QtGui   import QCursor, QFont, QColor, QPixmap

from gui.qt.theme import theme


DEFAULT_PIN_HASH = hashlib.sha256(b"1234").hexdigest()

FEATURE_DEFS = [
    ("cache_section",   "💾  قسم الكاش"),
    ("translate",       "🌐  زر ترجمة اللعبة"),
    ("edit_config",     "✏️   زر تعديل الإعدادات"),
    ("font_section",    "🔤  زر استبدال الخط"),
    ("locres_section",  "📄  قسم ملف Locres  (UE4)"),
    ("iostore_section", "📦  قسم IoStore / UAsset  (UE5)"),
    ("unreal_hook_section", "🪝  قسم Unreal Hook  (dxgi)"),
]
_SHOWN_ONLY = {"locres_section", "iostore_section", "unreal_hook_section"}

# أوضاع التعريب المتاحة لكل لعبة (engine + mod_mode + hook_mode)
MOD_MODES = [
    ("",                "— تلقائي / غير محدّد —"),
    ("datatable_pak",   "📦  DataTable .pak  (Manor Lords / UE5 ساكن)"),
    ("foundation_proxy","🏛️  Foundation proxy DLL  (Hurricane)"),
    ("unreal_hook",     "🪝  Unreal Hook dxgi  (UE5 حيّ)"),
    ("ue4ss",           "🔧  UE4SS mod"),
    ("bepinex",         "🎮  BepInEx + XUnity  (Unity)"),
    ("proxy",           "🌐  بروكسي حيّ فقط"),
]

# الأدوات الخارجية (المفتاح في config.json["tools"] ← التسمية + المسار الافتراضي)
TOOL_DEFS = [
    ("uassetgui_path", "UAssetGUI  (uasset⇄JSON)", "tools/UAssetGUI/UAssetGUI.exe"),
    ("repak_path",     "repak  (حزم pak V11)",       "tools/repak/repak.exe"),
    ("retoc_path",     "retoc  (IoStore ⇄ legacy)",  "tools/retoc/retoc.exe"),
    ("unrealpak_path", "UnrealPak  (pak قديم)",      ""),
    ("ue4loc_tool",    "UE4LocalizationsTool (.locres)", "tools/UE4localizationsTool/UE4localizationsTool.exe"),
]

_SCAN_EXTS = {".uasset", ".uexp", ".pak", ".utoc", ".ucas", ".locres", ".ttf", ".ufont"}


# ── Project root (3 levels up from gui/qt/dialogs/) ──────────────────────────

if getattr(sys, 'frozen', False):
    _PROJECT_ROOT = os.path.dirname(sys.executable)
else:
    _PROJECT_ROOT = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
    )


# ── Log dialog ────────────────────────────────────────────────────────────────

class _LogDialog(QDialog):
    """حوار عرض مخرجات العمليات في الوقت الفعلي."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(640, 440)
        c = theme.c
        self.setStyleSheet(
            f"QDialog  {{ background: {c['bg']}; }}"
            f"QLabel   {{ color: {c['primary']}; background: transparent; border: none; }}"
            f"QTextEdit {{ background: {c['surface']}; color: {c['secondary']};"
            f" border: 1px solid {c['border']}; border-radius: 6px; padding: 8px; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        lay.addWidget(self._log, 1)

        self._status = QLabel("جاري العمل…")
        self._status.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        lay.addWidget(self._status)

        br = QHBoxLayout()
        br.addStretch()
        self._close_btn = QPushButton("إغلاق")
        self._close_btn.setEnabled(False)
        self._close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._close_btn.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: #fff;"
            " border: none; border-radius: 8px; font-weight: bold; padding: 6px 20px; }"
            "QPushButton:disabled { background: #555; color: #888; }"
        )
        self._close_btn.clicked.connect(self.accept)
        br.addWidget(self._close_btn)
        lay.addLayout(br)

    def append_line(self, line: str):
        self._log.append(line)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_finished(self, ok: bool):
        c = theme.c
        if ok:
            self._status.setText("✅ اكتملت العملية بنجاح")
            self._status.setStyleSheet(
                f"color: {c.get('green', '#4caf50')}; font-size: 11px; font-weight: bold;"
            )
        else:
            self._status.setText("✗ فشلت العملية — راجع السجل أعلاه")
            self._status.setStyleSheet(
                f"color: {c['accent']}; font-size: 11px; font-weight: bold;"
            )
        self._close_btn.setEnabled(True)


# ── App release worker ────────────────────────────────────────────────────────

class _AppReleaseWorker(QThread):
    """يشغّل publish_app.py ويُرسل مخرجاته سطراً بسطر."""
    log_line = Signal(str)
    finished = Signal(bool)

    def __init__(self, version: str):
        super().__init__()
        self._version = version

    def run(self):
        import subprocess
        script = os.path.join(_PROJECT_ROOT, "tools", "publish_app.py")
        try:
            proc = subprocess.Popen(
                [sys.executable, script, self._version],
                cwd=_PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            )
            for line in iter(proc.stdout.readline, ""):
                self.log_line.emit(line.rstrip())
            proc.wait()
            self.finished.emit(proc.returncode == 0)
        except Exception as exc:
            self.log_line.emit(f"✗ خطأ: {exc}")
            self.finished.emit(False)


# ── Translation release worker ────────────────────────────────────────────────

class _TranslationReleaseWorker(QThread):
    """ينشر ملفات ready/ كـ GitHub Release ويحدّث manifest.json."""
    log_line = Signal(str)
    finished = Signal(bool)

    _REPO = "nssr12/GameArabicTranslator"

    def __init__(self, game_id: str, version: str, ready_dir: str,
                 manifest_path: str, file_targets: dict):
        super().__init__()
        self._game_id       = game_id
        self._version       = version
        self._ready_dir     = ready_dir
        self._manifest_path = manifest_path
        self._file_targets  = file_targets   # {filename: game_target}

    def run(self):
        import subprocess
        game_id = self._game_id
        version = self._version
        tag     = f"translation-{game_id}-v{version}"
        REPO    = self._REPO

        # Collect ready/ files
        if not os.path.isdir(self._ready_dir):
            self.log_line.emit("✗ مجلد ready/ غير موجود")
            self.finished.emit(False)
            return
        files = sorted(
            os.path.join(self._ready_dir, f)
            for f in os.listdir(self._ready_dir)
            if os.path.isfile(os.path.join(self._ready_dir, f))
        )
        if not files:
            self.log_line.emit("✗ لا توجد ملفات في مجلد ready/")
            self.finished.emit(False)
            return
        self.log_line.emit(f"الملفات: {', '.join(os.path.basename(f) for f in files)}")

        # Delete old release if exists
        self.log_line.emit(f"\n>> التحقق من الإصدار القديم: {tag}")
        r = subprocess.run(
            ["gh", "release", "view", tag, "--repo", REPO],
            capture_output=True, cwd=_PROJECT_ROOT,
        )
        if r.returncode == 0:
            self.log_line.emit(f">> حذف الإصدار القديم {tag}…")
            subprocess.run(
                ["gh", "release", "delete", tag, "--repo", REPO,
                 "--yes", "--cleanup-tag"],
                cwd=_PROJECT_ROOT,
            )
            time.sleep(2)

        # Create GitHub release + upload files
        self.log_line.emit(f"\n>> إنشاء GitHub Release: {tag}  ({len(files)} ملف)…")
        cmd = [
            "gh", "release", "create", tag,
            "--repo", REPO,
            "--title", f"Translation {game_id} v{version}",
            "--notes", f"ترجمة عربية للعبة {game_id} - الإصدار {version}",
            *files,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=_PROJECT_ROOT)
        if r.returncode != 0:
            self.log_line.emit(f"✗ فشل إنشاء الإصدار:\n{r.stderr.strip()}")
            self.finished.emit(False)
            return
        self.log_line.emit(f"✓ GitHub Release: {tag}")

        # Build manifest file entries
        manifest_files = []
        total_bytes    = 0
        for fp in files:
            fname  = os.path.basename(fp)
            url    = f"https://github.com/{REPO}/releases/download/{tag}/{fname}"
            size   = os.path.getsize(fp)
            target = self._file_targets.get(fname, fname)
            total_bytes += size
            manifest_files.append({
                "name":        fname,
                "url":         url,
                "game_target": target,
                "size":        size,
            })

        # Update manifest.json
        self.log_line.emit("\n>> تحديث manifest.json…")
        with open(self._manifest_path, encoding="utf-8") as f:
            m = json.load(f)
        m.setdefault("translations", {})[game_id] = {
            "version": version,
            "size_mb": max(1, round(total_bytes / (1024 * 1024))),
            "files":   manifest_files,
        }
        with open(self._manifest_path, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
        self.log_line.emit("✓ manifest.json محدَّث")

        # Git commit + push
        self.log_line.emit("\n>> git add + commit + push…")
        subprocess.run(["git", "add", "manifest.json"], cwd=_PROJECT_ROOT)
        rc = subprocess.run(
            ["git", "commit", "-m", f"Release translation {game_id} v{version}"],
            cwd=_PROJECT_ROOT, capture_output=True,
        ).returncode
        if rc == 0:
            r2 = subprocess.run(
                ["git", "push", "origin", "main"],
                cwd=_PROJECT_ROOT, capture_output=True, text=True,
            )
            if r2.returncode == 0:
                self.log_line.emit("✓ تم الرفع إلى GitHub")
            else:
                self.log_line.emit(f"⚠ git push: {r2.stderr.strip()}")
        else:
            self.log_line.emit("manifest.json لم يتغير — تخطي commit")

        self.log_line.emit(f"\n✅ تم! ترجمة {game_id} v{version} متاحة للمستخدمين")
        self.finished.emit(True)


# ── for_cache upload worker ──────────────────────────────────────────────────

class _ForCacheUploadWorker(QThread):
    """يضغط مجلد for_cache ويرفعه كـ asset إلى GitHub Release."""
    log_line = Signal(str)
    finished = Signal(bool)

    _REPO = "nssr12/GameArabicTranslator"

    def __init__(self, game_id: str, version: str, for_cache_dir: str, manifest_path: str):
        super().__init__()
        self._game_id       = game_id
        self._version       = version
        self._for_cache_dir = for_cache_dir
        self._manifest_path = manifest_path

    def run(self):
        import subprocess, tempfile
        game_id  = self._game_id
        version  = self._version
        tag      = f"translation-{game_id}-v{version}"
        REPO     = self._REPO
        zip_name = f"{game_id}_for_cache.zip"

        # Zip the for_cache directory
        self.log_line.emit(">> ضغط مجلد for_cache…")
        tmp_dir  = tempfile.mkdtemp()
        zip_base = os.path.join(tmp_dir, zip_name[:-4])
        try:
            shutil.make_archive(zip_base, "zip", root_dir=self._for_cache_dir)
            zip_path = zip_base + ".zip"
            size_mb  = os.path.getsize(zip_path) / 1_048_576
            self.log_line.emit(f"✓ تم الضغط: {size_mb:.1f} MB")
        except Exception as e:
            self.log_line.emit(f"✗ خطأ في الضغط: {e}")
            self.finished.emit(False)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return

        # Verify release exists
        self.log_line.emit(f"\n>> التحقق من الإصدار: {tag}")
        r = subprocess.run(
            ["gh", "release", "view", tag, "--repo", REPO],
            capture_output=True, cwd=_PROJECT_ROOT,
        )
        if r.returncode != 0:
            self.log_line.emit(f"✗ الإصدار {tag} غير موجود — انشر الترجمة أولاً")
            self.finished.emit(False)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return

        # Upload (--clobber replaces existing asset)
        self.log_line.emit(f"\n>> رفع {zip_name}…")
        r = subprocess.run(
            ["gh", "release", "upload", tag, zip_path,
             "--repo", REPO, "--clobber"],
            capture_output=True, text=True, cwd=_PROJECT_ROOT,
        )
        if r.returncode != 0:
            self.log_line.emit(f"✗ فشل الرفع:\n{r.stderr.strip()}")
            self.finished.emit(False)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return
        self.log_line.emit("✓ تم الرفع بنجاح")

        # Update manifest.json
        url = f"https://github.com/{REPO}/releases/download/{tag}/{zip_name}"
        self.log_line.emit("\n>> تحديث manifest.json…")
        try:
            with open(self._manifest_path, encoding="utf-8") as f:
                m = json.load(f)
            m.setdefault("translations", {}).setdefault(game_id, {}).update({
                "for_cache_url":     url,
                "for_cache_size_mb": max(1, round(size_mb)),
            })
            with open(self._manifest_path, "w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False, indent=2)
            self.log_line.emit("✓ manifest.json محدَّث")
        except Exception as e:
            self.log_line.emit(f"✗ خطأ في manifest.json: {e}")
            self.finished.emit(False)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return

        # git commit + push
        self.log_line.emit("\n>> git add + commit + push…")
        subprocess.run(["git", "add", "manifest.json"], cwd=_PROJECT_ROOT)
        rc = subprocess.run(
            ["git", "commit", "-m", f"Add for_cache link for {game_id} v{version}"],
            cwd=_PROJECT_ROOT, capture_output=True,
        ).returncode
        if rc == 0:
            r2 = subprocess.run(
                ["git", "push", "origin", "main"],
                cwd=_PROJECT_ROOT, capture_output=True, text=True,
            )
            self.log_line.emit(
                "✓ تم الرفع إلى GitHub" if r2.returncode == 0
                else f"⚠ git push: {r2.stderr.strip()}"
            )
        else:
            self.log_line.emit("manifest.json لم يتغير — تخطي commit")

        self.log_line.emit(f"\n✅ for_cache لـ {game_id} متاح الآن للمستخدمين")
        self.finished.emit(True)
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── PIN dialog ────────────────────────────────────────────────────────────────

class PINDialog(QDialog):
    """حوار إدخال PIN للوصول إلى لوحة الإدارة."""

    verified = Signal()

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("🔐  وصول الإدارة")
        self.setFixedSize(340, 200)
        self.setModal(True)
        self._build()

    def _build(self):
        c = theme.c
        self.setStyleSheet(f"""
            QDialog {{ background: {c['bg']}; }}
            QLabel  {{ color: {c['primary']}; background: transparent; border: none; }}
            QLineEdit {{
                background: {c['surface']}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 8px;
                padding: 8px 12px; font-size: 18px; letter-spacing: 6px;
                selection-background-color: {c['accent']};
            }}
            QLineEdit:focus {{ border-color: {c['accent']}; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        title = QLabel("🔐  لوحة الإدارة")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {c['accent']};"
        )
        root.addWidget(title)

        hint = QLabel("أدخل رمز PIN للمتابعة")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"font-size: 11px; color: {c['muted']};")
        root.addWidget(hint)

        self._pin_field = QLineEdit()
        self._pin_field.setEchoMode(QLineEdit.Password)
        self._pin_field.setAlignment(Qt.AlignCenter)
        self._pin_field.setPlaceholderText("••••")
        self._pin_field.returnPressed.connect(self._verify)
        root.addWidget(self._pin_field)

        self._err_lbl = QLabel("")
        self._err_lbl.setAlignment(Qt.AlignCenter)
        self._err_lbl.setStyleSheet(f"color: {c['accent']}; font-size: 10px;")
        root.addWidget(self._err_lbl)

        btn_row = QHBoxLayout()
        cancel = QPushButton("إلغاء")
        cancel.setCursor(QCursor(Qt.PointingHandCursor))
        cancel.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; color: {c['muted']};"
            f" border: 1px solid {c['border']}; border-radius: 8px; padding: 6px 18px; }}"
            f"QPushButton:hover {{ background: {c['hover']}; }}"
        )
        cancel.clicked.connect(self.reject)

        ok_btn = QPushButton("دخول ←")
        ok_btn.setCursor(QCursor(Qt.PointingHandCursor))
        ok_btn.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: #fff;"
            " border: none; border-radius: 8px; font-weight: bold; padding: 6px 18px; }"
        )
        ok_btn.clicked.connect(self._verify)

        btn_row.addWidget(cancel)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        root.addLayout(btn_row)

    def _verify(self):
        pin  = self._pin_field.text()
        h    = hashlib.sha256(pin.encode()).hexdigest()
        stored = self._config.get("admin", {}).get("pin_hash", DEFAULT_PIN_HASH)
        if h == stored:
            self.verified.emit()
            self.accept()
        else:
            self._err_lbl.setText("✗  رمز PIN غير صحيح")
            self._pin_field.clear()
            self._pin_field.setFocus()


# ── Admin panel ───────────────────────────────────────────────────────────────

class AdminPanel(QDialog):
    """لوحة الإدارة الكاملة."""

    features_saved = Signal(str)   # game_id — يُصدَر عند حفظ إعدادات الميزات

    def __init__(self, game_manager, cache, config: dict,
                 config_path: str = "", parent=None):
        super().__init__(parent)
        self._gm          = game_manager
        self._cache       = cache
        self._config      = config
        self._config_path = config_path
        self._selected_id: str | None = None

        self.setWindowTitle("⚙️  لوحة الإدارة")
        self.setMinimumSize(960, 640)
        self.setModal(False)
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        c = theme.c
        self.setStyleSheet(f"""
            QDialog   {{ background: {c['bg']}; }}
            QLabel    {{ color: {c['primary']}; background: transparent; border: none; }}
            QLineEdit, QTextEdit {{
                background: {c['surface']}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 6px;
                padding: 4px 8px;
                selection-background-color: {c['accent']};
            }}
            QLineEdit:focus, QTextEdit:focus {{ border-color: {c['accent']}; }}
            QCheckBox {{ color: {c['primary']}; background: transparent; }}
            QCheckBox::indicator {{
                width: 15px; height: 15px;
                border: 1px solid {c['border']}; border-radius: 3px;
                background: {c['surface']};
            }}
            QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
            QTabWidget::pane {{
                border: 1px solid {c['border']}; border-radius: 8px;
                background: {c['card']};
            }}
            QTabBar::tab {{
                background: {c['surface']}; color: {c['muted']};
                border: 1px solid {c['border']}; border-bottom: none;
                border-top-left-radius: 6px; border-top-right-radius: 6px;
                border-bottom-left-radius: 0; border-bottom-right-radius: 0;
                padding: 6px 16px; margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background: {c['card']}; color: {c['primary']}; font-weight: bold;
            }}
            QTabBar::tab:hover {{ color: {c['accent']}; }}
            QTableWidget {{
                background: {c['surface']}; color: {c['primary']};
                border: none; gridline-color: {c['border']};
                selection-background-color: {c['accent']};
            }}
            QHeaderView::section {{
                background: {c['card2']}; color: {c['muted']};
                border: none; border-bottom: 1px solid {c['border']};
                padding: 4px 8px; font-size: 10px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Title bar
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-bottom: 1px solid {c['border']}; }}"
        )
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(20, 12, 20, 12)
        title = QLabel("⚙️  لوحة الإدارة")
        title.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {c['accent']};"
        )
        bar_lay.addWidget(title)
        bar_lay.addStretch()
        root.addWidget(bar)

        # Main split
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Left: game list
        left = QFrame()
        left.setFixedWidth(220)
        left.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-right: 1px solid {c['border']}; }}"
        )
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)

        list_hdr = QFrame()
        list_hdr.setStyleSheet(
            f"QFrame {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; }}"
        )
        list_hdr_lay = QHBoxLayout(list_hdr)
        list_hdr_lay.setContentsMargins(12, 8, 12, 8)
        list_hdr_lbl = QLabel("الألعاب")
        list_hdr_lbl.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {c['muted']};"
        )
        list_hdr_lay.addWidget(list_hdr_lbl)
        left_lay.addWidget(list_hdr)

        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QFrame.NoFrame)
        self._list_scroll.setStyleSheet("background: transparent; border: none;")
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_lay = QVBoxLayout(self._list_widget)
        self._list_lay.setContentsMargins(6, 6, 6, 6)
        self._list_lay.setSpacing(2)
        self._list_lay.addStretch()
        self._list_scroll.setWidget(self._list_widget)
        left_lay.addWidget(self._list_scroll, 1)

        # System info button at bottom of left
        sysinfo_btn = QPushButton("🖥️  معلومات النظام")
        sysinfo_btn.setCursor(QCursor(Qt.PointingHandCursor))
        sysinfo_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {c['muted']};"
            f" border: none; border-top: 1px solid {c['border']};"
            f" padding: 8px; font-size: 10px; }}"
            f"QPushButton:hover {{ color: {c['accent']}; }}"
        )
        sysinfo_btn.clicked.connect(self._show_sysinfo)
        left_lay.addWidget(sysinfo_btn)

        # Right: content tabs
        right = QWidget()
        right.setStyleSheet(f"background: {c['bg']};")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(16, 16, 16, 16)
        right_lay.setSpacing(12)

        self._placeholder = QLabel("← اختر لعبة أو «لوحة المعلومات» / «إعدادات عامة»")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet(f"color: {c['muted']}; font-size: 14px;")
        right_lay.addWidget(self._placeholder)

        self._tabs = QTabWidget()
        self._tabs.hide()
        right_lay.addWidget(self._tabs, 1)

        # مضيف المحتوى العام (لوحة المعلومات / الإعدادات العامة) — يُملأ عند الطلب
        self._global_host = QWidget()
        self._global_host.hide()
        self._global_host_lay = QVBoxLayout(self._global_host)
        self._global_host_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.addWidget(self._global_host, 1)

        body.addWidget(left)
        body.addWidget(right, 1)
        root.addLayout(body, 1)

        # Bottom bar: PIN change + close
        bottom = QFrame()
        bottom.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-top: 1px solid {c['border']}; }}"
        )
        bot_lay = QHBoxLayout(bottom)
        bot_lay.setContentsMargins(16, 10, 16, 10)
        bot_lay.setSpacing(10)

        release_app_btn = QPushButton("🚀  إصدار التطبيق")
        release_app_btn.setCursor(QCursor(Qt.PointingHandCursor))
        release_app_btn.setStyleSheet(
            f"QPushButton {{ background: rgba(0,0,0,26); color: {c['accent']};"
            f" border: 1px solid {c['accent']}; border-radius: 6px;"
            f" padding: 4px 14px; font-size: 11px; }}"
            f"QPushButton:hover {{ background: {c['accent']}; color: #fff; }}"
        )
        release_app_btn.clicked.connect(self._open_app_release_dialog)
        bot_lay.addWidget(release_app_btn)
        bot_lay.addSpacing(16)

        pin_lbl = QLabel("تغيير PIN:")
        pin_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        self._new_pin = QLineEdit()
        self._new_pin.setEchoMode(QLineEdit.Password)
        self._new_pin.setFixedWidth(100)
        self._new_pin.setPlaceholderText("••••")
        self._new_pin.setAlignment(Qt.AlignCenter)
        save_pin_btn = QPushButton("حفظ PIN")
        save_pin_btn.setCursor(QCursor(Qt.PointingHandCursor))
        save_pin_btn.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; color: {c['secondary']};"
            f" border: 1px solid {c['border']}; border-radius: 6px; padding: 4px 12px; }}"
            f"QPushButton:hover {{ background: {c['hover']}; border-color: {c['accent']}; }}"
        )
        save_pin_btn.clicked.connect(self._save_pin)

        bot_lay.addWidget(pin_lbl)
        bot_lay.addWidget(self._new_pin)
        bot_lay.addWidget(save_pin_btn)
        bot_lay.addStretch()

        close_btn = QPushButton("إغلاق")
        close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        close_btn.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: #fff;"
            " border: none; border-radius: 8px; padding: 6px 20px; font-weight: bold; }"
        )
        close_btn.clicked.connect(self.accept)
        bot_lay.addWidget(close_btn)
        root.addWidget(bottom)

        self._right_lay = right_lay
        self._populate_game_list()

    # ── Game list ─────────────────────────────────────────────────────────────

    def _populate_game_list(self):
        c = theme.c
        while self._list_lay.count() > 1:
            item = self._list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # أزرار عامة (غير مرتبطة بلعبة) في الأعلى
        self._game_btns: dict[str, QPushButton] = {}
        for sid, slabel in [("__dashboard__", "📊  لوحة المعلومات"),
                            ("__general__",   "⚙️  إعدادات عامة")]:
            sb = QPushButton(slabel)
            sb.setCursor(QCursor(Qt.PointingHandCursor))
            sb.setCheckable(True)
            sb.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(0,0,0,30); color: {c['secondary']};
                    border: 1px solid {c['border']}; border-radius: 6px;
                    padding: 7px 10px; text-align: left; font-size: 12px; font-weight: bold;
                }}
                QPushButton:hover {{ background: {c['hover']}; color: {c['accent']}; }}
                QPushButton:checked {{ background: {c['hover']}; color: {c['accent']};
                    border-color: {c['accent']}; }}
            """)
            sb.clicked.connect(lambda _checked, k=sid: self._select_special(k))
            self._game_btns[sid] = sb
            self._list_lay.insertWidget(self._list_lay.count() - 1, sb)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"QFrame {{ background: {c['border']}; max-height: 1px; border: none; }}")
        self._list_lay.insertWidget(self._list_lay.count() - 1, sep)

        if not self._gm:
            return

        games = self._gm.get_game_list()

        for game in games:
            gid = game["id"]
            btn = QPushButton(gid)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {c['primary']};
                    border: none; border-radius: 6px;
                    padding: 7px 10px; text-align: left; font-size: 12px;
                }}
                QPushButton:hover {{ background: {c['hover']}; }}
                QPushButton:checked {{
                    background: {c['hover']};
                    border-left: 3px solid {c['accent']};
                    color: {c['accent']}; font-weight: bold;
                }}
            """)
            btn.clicked.connect(lambda checked, g=gid: self._select_game(g))
            self._game_btns[gid] = btn
            self._list_lay.insertWidget(self._list_lay.count() - 1, btn)

    def _select_game(self, game_id: str):
        # Deselect others
        for gid, btn in self._game_btns.items():
            btn.setChecked(gid == game_id)

        self._selected_id = game_id
        self._placeholder.hide()
        self._global_host.hide()
        self._tabs.show()
        self._build_tabs(game_id)

    def _clear_global_host(self):
        while self._global_host_lay.count():
            it = self._global_host_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _select_special(self, kind: str):
        for gid, btn in self._game_btns.items():
            btn.setChecked(gid == kind)
        self._selected_id = None
        self._placeholder.hide()
        self._tabs.hide()
        self._clear_global_host()
        if kind == "__dashboard__":
            self._global_host_lay.addWidget(self._build_dashboard_widget())
        else:
            self._global_host_lay.addWidget(self._build_general_widget())
        self._global_host.show()

    # ── Tabs builder ──────────────────────────────────────────────────────────

    def _build_tabs(self, game_id: str):
        self._tabs.clear()
        cfg = self._gm.get_game(game_id) or {} if self._gm else {}

        self._tabs.addTab(self._build_features_tab(game_id, cfg),   "👁  الميزات")
        self._tabs.addTab(self._build_cover_tab(game_id, cfg),      "🖼  صورة العرض")
        self._tabs.addTab(self._build_package_tab(game_id, cfg),    "📦  حزمة التعريب")
        self._tabs.addTab(self._build_release_tab(game_id, cfg),    "🚀  نشر الترجمة")
        self._tabs.addTab(self._build_config_tab(game_id, cfg),     "🗒  الإعدادات الخام")
        self._tabs.addTab(self._build_cache_tab(game_id, cfg),      "💾  الكاش")

    # ── Game health check (مشترك بين الـ dashboard وزر الفحص) ──────────────────

    def _game_health(self, game_id: str, cfg: dict) -> dict:
        """يفحص لعبة ويُرجع dict بالحالة: مسار، مود، ترجمات، أدوات."""
        game_path = cfg.get("game_path", "")
        eng = (cfg.get("engine") or "").lower()
        mod_mode = cfg.get("mod_mode", "")
        hook_mode = cfg.get("hook_mode", "")
        h = {
            "id": game_id,
            "mode": mod_mode or hook_mode or eng or "—",
            "path_ok": bool(game_path) and os.path.isdir(game_path),
            "installed": None,       # True/False/None(غير منطبق)
            "translations": 0,
            "issues": [],
        }
        if not h["path_ok"]:
            h["issues"].append("مسار اللعبة غير صالح")

        # حالة المود حسب النوع
        try:
            if mod_mode == "datatable_pak":
                from games.manorlords_mod import ManorLordsMod
                h["installed"] = ManorLordsMod().get_install_status(cfg, game_path)
                ok, msg = ManorLordsMod.tools_exist()
                if not ok:
                    h["issues"].append(msg)
            elif eng == "hurricane" or hook_mode == "foundation_proxy":
                from games.foundation_mod import FoundationMod
                h["installed"] = FoundationMod().get_install_status(cfg, game_path)
            elif eng == "unity" or "bepinex_mod" in cfg:
                from games.bepinex_mod import BepInExMod
                h["installed"] = BepInExMod().get_install_status(cfg, game_path)
            elif hook_mode == "unreal_hook" or "unreal_hook_section" in (cfg.get("shown_features") or []):
                from games.unreal_hook_mod import UnrealHookMod
                h["installed"] = UnrealHookMod().is_installed(cfg)
        except Exception as e:
            h["issues"].append(f"فحص المود: {e}")

        # عدد الترجمات بالكاش
        try:
            if self._cache:
                h["translations"] = self._cache.count_entries(cfg.get("name", game_id))
        except Exception:
            pass
        return h

    # ── Dashboard (نظرة شاملة لكل الألعاب) ─────────────────────────────────────

    def _build_dashboard_widget(self) -> QWidget:
        c = theme.c
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        hdr = QHBoxLayout()
        title = QLabel("📊  نظرة شاملة على كل الألعاب")
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {c['accent']};")
        hdr.addWidget(title)
        hdr.addStretch()
        refresh = QPushButton("🔄  تحديث")
        refresh.setCursor(QCursor(Qt.PointingHandCursor))
        refresh.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; color: {c['secondary']};"
            f" border: 1px solid {c['border']}; border-radius: 6px; padding: 4px 14px; }}"
            f"QPushButton:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}")
        hdr.addWidget(refresh)
        lay.addLayout(hdr)

        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(["اللعبة", "الوضع", "المسار", "المود", "ترجمات", "ملاحظات"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().hide()
        lay.addWidget(table, 1)

        def _yn(v, true_t="✓", false_t="✗"):
            if v is None:
                return ("—", c['muted'])
            return (true_t, c['green']) if v else (false_t, c['accent'])

        def _refresh():
            table.setRowCount(0)
            games = self._gm.get_game_list() if self._gm else []
            for g in games:
                gid = g["id"]
                cfg = self._gm.get_game(gid) or {}
                hh = self._game_health(gid, cfg)
                r = table.rowCount()
                table.insertRow(r)
                table.setItem(r, 0, QTableWidgetItem(gid))
                table.setItem(r, 1, QTableWidgetItem(str(hh["mode"])))
                for col, val in [(2, hh["path_ok"]), (3, hh["installed"])]:
                    txt, col_c = _yn(val)
                    it = QTableWidgetItem(txt)
                    it.setTextAlignment(Qt.AlignCenter)
                    it.setForeground(QColor(col_c))
                    table.setItem(r, col, it)
                tr = QTableWidgetItem(f"{hh['translations']:,}")
                tr.setTextAlignment(Qt.AlignCenter)
                table.setItem(r, 4, tr)
                notes = QTableWidgetItem("؛ ".join(hh["issues"]) if hh["issues"] else "سليم")
                notes.setForeground(QColor(c['accent'] if hh["issues"] else c['green']))
                table.setItem(r, 5, notes)

        refresh.clicked.connect(_refresh)
        _refresh()
        return w

    # ── General settings (أدوات + ترجمة + مفاتيح) ─────────────────────────────

    def _save_main_config(self):
        if self._config_path:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)

    def _build_general_widget(self) -> QWidget:
        c = theme.c
        tabs = QTabWidget()
        tabs.addTab(self._build_tools_subtab(), "🛠  الأدوات")
        tabs.addTab(self._build_translation_subtab(), "🌐  الترجمة")
        tabs.addTab(self._build_keys_subtab(), "🔑  المفاتيح")
        return tabs

    def _build_tools_subtab(self) -> QWidget:
        c = theme.c
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)
        lay.addWidget(QLabel("مسارات الأدوات الخارجية (محفوظة في config.json)"))

        tools = self._config.setdefault("tools", {})
        fields: dict[str, QLineEdit] = {}

        def _row(key, label, default):
            row = QFrame()
            row.setStyleSheet(f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']};"
                              " border-radius: 6px; }")
            rl = QVBoxLayout(row); rl.setContentsMargins(10, 8, 10, 8); rl.setSpacing(4)
            top = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {c['primary']}; font-size: 12px; font-weight: bold;")
            top.addWidget(lbl)
            top.addStretch()
            st = QLabel()
            top.addWidget(st)
            rl.addLayout(top)
            f = QLineEdit(tools.get(key, "") or "")
            cur = tools.get(key, "") or (os.path.join(_PROJECT_ROOT, default) if default else "")
            f.setText(cur)
            fields[key] = f
            ir = QHBoxLayout()
            ir.addWidget(f, 1)
            br = QPushButton("📂")
            br.setFixedWidth(36); br.setCursor(QCursor(Qt.PointingHandCursor))
            br.setStyleSheet(f"QPushButton {{ background: {c['surface']}; color: {c['secondary']};"
                             f" border: 1px solid {c['border']}; border-radius: 6px; }}")
            def _browse(fld=f):
                p, _ = QFileDialog.getOpenFileName(self, "اختر الأداة", "", "Executables (*.exe);;All (*.*)")
                if p:
                    fld.setText(p); _upd()
            br.clicked.connect(_browse)
            ir.addWidget(br)
            rl.addLayout(ir)
            def _upd(fld=f, lab=st):
                ok = bool(fld.text().strip()) and os.path.isfile(fld.text().strip())
                lab.setText("✓ موجود" if ok else "✗ مفقود")
                lab.setStyleSheet(f"color: {c['green'] if ok else c['accent']}; font-size: 10px;")
            f.textChanged.connect(lambda _t: _upd())
            _upd()
            lay.addWidget(row)

        for key, label, default in TOOL_DEFS:
            _row(key, label, default)

        lay.addStretch()
        save = QPushButton("💾  حفظ مسارات الأدوات")
        save.setFixedHeight(34); save.setCursor(QCursor(Qt.PointingHandCursor))
        save.setStyleSheet(f"QPushButton {{ background: {c['accent']}; color: #fff;"
                           " border: none; border-radius: 8px; font-weight: bold; padding: 0 18px; }")
        def _save():
            for key, f in fields.items():
                tools[key] = f.text().strip()
            self._save_main_config()
            QMessageBox.information(self, "✓", "حُفظت مسارات الأدوات")
        save.clicked.connect(_save)
        lay.addWidget(save)
        return w

    def _build_translation_subtab(self) -> QWidget:
        c = theme.c
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(12)
        lay.addWidget(QLabel("إعدادات الترجمة العامة (config.json)"))

        # الموديل النشط
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel("الموديل الافتراضي:"))
        model_combo = QComboBox()
        models = list((self._config.get("models") or {}).keys())
        model_combo.addItems(models)
        cur_model = self._config.get("default_model", "ollama")
        if cur_model in models:
            model_combo.setCurrentText(cur_model)
        mrow.addWidget(model_combo); mrow.addStretch()
        lay.addLayout(mrow)

        # اسم موديل Ollama
        orow = QHBoxLayout()
        orow.addWidget(QLabel("موديل Ollama:"))
        ollama_field = QLineEdit((self._config.get("models", {}).get("ollama", {}) or {}).get("model", ""))
        ollama_field.setFixedWidth(220)
        orow.addWidget(ollama_field); orow.addStretch()
        lay.addLayout(orow)

        # tag_mode
        trow = QHBoxLayout()
        trow.addWidget(QLabel("وضع حماية التاقات:"))
        tag_combo = QComboBox()
        tag_combo.addItems(["bulletproof", "tiered", "strip", "inline"])
        tag_combo.setCurrentText(self._config.get("tag_mode", "bulletproof"))
        trow.addWidget(tag_combo); trow.addStretch()
        lay.addLayout(trow)

        # number_templating
        num_cb = QCheckBox("تقويلب الأرقام (تقليل تكرار الكاش)")
        num_cb.setChecked(bool(self._config.get("number_templating", True)))
        lay.addWidget(num_cb)

        lay.addStretch()
        save = QPushButton("💾  حفظ إعدادات الترجمة")
        save.setFixedHeight(34); save.setCursor(QCursor(Qt.PointingHandCursor))
        save.setStyleSheet(f"QPushButton {{ background: {c['accent']}; color: #fff;"
                           " border: none; border-radius: 8px; font-weight: bold; padding: 0 18px; }")
        def _save():
            self._config["default_model"] = model_combo.currentText()
            self._config["tag_mode"] = tag_combo.currentText()
            self._config["number_templating"] = num_cb.isChecked()
            self._config.setdefault("models", {}).setdefault("ollama", {})["model"] = ollama_field.text().strip()
            self._save_main_config()
            QMessageBox.information(self, "✓", "حُفظت إعدادات الترجمة\n(أعد تشغيل التطبيق لتطبيقها)")
        save.clicked.connect(_save)
        lay.addWidget(save)
        return w

    def _build_keys_subtab(self) -> QWidget:
        c = theme.c
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(12)
        lay.addWidget(QLabel("مفاتيح AES (لفكّ/حزم paks المشفّرة)"))

        tools = self._config.setdefault("tools", {})
        gr = QHBoxLayout()
        gr.addWidget(QLabel("مفتاح UnrealPak العام:"))
        glob_field = QLineEdit(tools.get("unrealpak_aes", ""))
        gr.addWidget(glob_field, 1)
        lay.addLayout(gr)

        # مفتاح Manor Lords من keys.json
        keys_path = os.path.join(_PROJECT_ROOT, "games", "keys.json")
        ml_key = ""
        try:
            with open(keys_path, encoding="utf-8") as f:
                ml_key = (json.load(f).get("EncryptionKey", {}) or {}).get("Key", "")
        except Exception:
            pass
        mr = QHBoxLayout()
        mr.addWidget(QLabel("مفتاح Manor Lords (keys.json):"))
        ml_field = QLineEdit(ml_key)
        mr.addWidget(ml_field, 1)
        lay.addLayout(mr)

        note = QLabel("⚠ المفاتيح حسّاسة — لا تشاركها. تُستخدم في retoc/UnrealPak/repak.")
        note.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        note.setWordWrap(True)
        lay.addWidget(note)

        lay.addStretch()
        save = QPushButton("💾  حفظ المفاتيح")
        save.setFixedHeight(34); save.setCursor(QCursor(Qt.PointingHandCursor))
        save.setStyleSheet(f"QPushButton {{ background: {c['accent']}; color: #fff;"
                           " border: none; border-radius: 8px; font-weight: bold; padding: 0 18px; }")
        def _save():
            tools["unrealpak_aes"] = glob_field.text().strip()
            self._save_main_config()
            try:
                with open(keys_path, "w", encoding="utf-8") as f:
                    json.dump({"EncryptionKey": {"Key": ml_field.text().strip()}}, f, indent=2)
            except Exception as e:
                QMessageBox.warning(self, "خطأ", f"keys.json: {e}")
                return
            QMessageBox.information(self, "✓", "حُفظت المفاتيح")
        save.clicked.connect(_save)
        lay.addWidget(save)
        return w

    # ── Features tab ──────────────────────────────────────────────────────────

    def _build_features_tab(self, game_id: str, cfg: dict) -> QWidget:
        c   = theme.c
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        title = QLabel("تحكم في الأقسام والأزرار الظاهرة في صفحة اللعبة")
        title.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        lay.addWidget(title)

        # ── وضع التعريب (engine/mod_mode) + فحص صحّة ───────────────────────────
        mm_row = QHBoxLayout()
        mm_lbl = QLabel("وضع التعريب:")
        mm_lbl.setStyleSheet(f"color: {c['primary']}; font-size: 12px; font-weight: bold;")
        mm_row.addWidget(mm_lbl)
        self._mod_mode_combo = QComboBox()
        for val, label in MOD_MODES:
            self._mod_mode_combo.addItem(label, val)
        cur_mm = cfg.get("mod_mode", "") or cfg.get("hook_mode", "") or ""
        idx = next((i for i, (v, _l) in enumerate(MOD_MODES) if v == cur_mm), 0)
        self._mod_mode_combo.setCurrentIndex(idx)
        mm_row.addWidget(self._mod_mode_combo, 1)
        health_btn = QPushButton("🩺  فحص صحّة")
        health_btn.setCursor(QCursor(Qt.PointingHandCursor))
        health_btn.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; color: {c['secondary']};"
            f" border: 1px solid {c['border']}; border-radius: 6px; padding: 4px 12px; }}"
            f"QPushButton:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}")
        health_btn.clicked.connect(lambda _ck, g=game_id: self._show_health(g))
        mm_row.addWidget(health_btn)
        lay.addLayout(mm_row)

        mm_hint = QLabel("ⓘ يحدّد البطاقة/القسم المعروض في صفحة اللعبة (datatable_pak ⇐ Manor Lords).")
        mm_hint.setStyleSheet(f"color: {c['muted']}; font-size: 9px;")
        lay.addWidget(mm_hint)

        sep0 = QFrame(); sep0.setFrameShape(QFrame.HLine)
        sep0.setStyleSheet(f"QFrame {{ background: {c['border']}; max-height: 1px; border: none; }}")
        lay.addWidget(sep0)

        hidden      = set(cfg.get("hidden_features", []))
        shown_extra = set(cfg.get("shown_features",  []))
        gid_lower   = game_id.lower().replace(" ", "").replace("_", "")
        is_moe      = "myth" in gid_lower or "empires" in gid_lower or "moe" in gid_lower

        self._feat_checks: dict[str, QCheckBox] = {}
        for key, label in FEATURE_DEFS:
            if key in _SHOWN_ONLY:
                if key == "locres_section" and is_moe:
                    checked = key not in hidden
                else:
                    checked = key in shown_extra
            else:
                checked = key not in hidden

            cb = QCheckBox(label)
            cb.setChecked(checked)
            cb.setStyleSheet(f"color: {c['primary']}; font-size: 13px;")
            self._feat_checks[key] = cb
            lay.addWidget(cb)

        lay.addStretch()

        save_btn = QPushButton("💾  حفظ الميزات")
        save_btn.setFixedHeight(36)
        save_btn.setCursor(QCursor(Qt.PointingHandCursor))
        save_btn.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: #fff;"
            " border: none; border-radius: 8px; font-weight: bold; padding: 0 20px; }"
        )
        save_btn.clicked.connect(
            lambda checked, gid=game_id, moe=is_moe: self._save_features(gid, moe)
        )
        lay.addWidget(save_btn)
        return w

    def _save_features(self, game_id: str, is_moe: bool):
        new_hidden = []
        new_shown  = []
        for key, cb in self._feat_checks.items():
            checked = cb.isChecked()
            if key in _SHOWN_ONLY:
                if key == "locres_section":
                    if is_moe:
                        if not checked:
                            new_hidden.append(key)
                    else:
                        if checked:
                            new_shown.append(key)
                else:
                    if checked:
                        new_shown.append(key)
            else:
                if not checked:
                    new_hidden.append(key)

        updates = {"hidden_features": new_hidden, "shown_features": new_shown}
        # وضع التعريب (mod_mode)
        try:
            mm = self._mod_mode_combo.currentData()
            updates["mod_mode"] = mm or ""
        except Exception:
            pass

        saved = False
        if self._gm:
            saved = self._gm.update_game(game_id, updates)
        else:
            print("[AdminPanel] _save_features: game_manager is None!")

        if saved:
            self.features_saved.emit(game_id)
            QMessageBox.information(self, "✓", "تم حفظ إعدادات الميزات + وضع التعريب")
        else:
            QMessageBox.warning(self, "خطأ", "تعذّر حفظ الميزات — اللعبة غير موجودة في الإعدادات")

    def _show_health(self, game_id: str):
        cfg = (self._gm.get_game(game_id) if self._gm else {}) or {}
        h = self._game_health(game_id, cfg)
        def mark(v):
            return "✓ نعم" if v is True else ("✗ لا" if v is False else "— غير منطبق")
        lines = [
            f"اللعبة:          {game_id}",
            f"الوضع:           {h['mode']}",
            f"مسار اللعبة:     {mark(h['path_ok'])}  ({cfg.get('game_path','—')})",
            f"المود مثبّت:     {mark(h['installed'])}",
            f"ترجمات بالكاش:  {h['translations']:,}",
            "",
            "الملاحظات:",
        ]
        lines += ["  • " + s for s in h["issues"]] or ["  ✓ لا مشاكل"]
        QMessageBox.information(self, f"🩺  فحص صحّة — {game_id}", "\n".join(lines))

    # ── Cover Image tab ───────────────────────────────────────────────────────

    def _build_cover_tab(self, game_id: str, cfg: dict) -> QWidget:
        c         = theme.c
        w         = QWidget()
        lay       = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        game_name = cfg.get("name", game_id)
        img_dir   = os.path.join(_PROJECT_ROOT, "data", "game_images")

        hint = QLabel("صورة الغلاف التي تظهر على بطاقة اللعبة في الصفحة الرئيسية")
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        lay.addWidget(hint)

        # Preview frame
        preview_frame = QFrame()
        preview_frame.setFixedHeight(190)
        preview_frame.setStyleSheet(
            f"QFrame {{ background: {c['surface']}; border: 1px solid {c['border']};"
            " border-radius: 8px; }"
        )
        pf_lay = QVBoxLayout(preview_frame)
        pf_lay.setContentsMargins(0, 0, 0, 0)

        cover_lbl = QLabel()
        cover_lbl.setAlignment(Qt.AlignCenter)
        cover_lbl.setStyleSheet("background: transparent; border: none;")
        pf_lay.addWidget(cover_lbl, 1)
        lay.addWidget(preview_frame)

        path_lbl = QLabel()
        path_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        path_lbl.setWordWrap(True)
        lay.addWidget(path_lbl)

        def _refresh():
            found = ""
            for stem in [game_name, game_id]:
                for ext in (".png", ".jpg", ".jpeg"):
                    p = os.path.join(img_dir, stem + ext)
                    if os.path.isfile(p):
                        found = p
                        break
                if found:
                    break
            if found:
                px = QPixmap(found)
                if not px.isNull():
                    px = px.scaled(340, 170, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    cover_lbl.setPixmap(px)
                    cover_lbl.setStyleSheet("background: transparent; border: none;")
                    path_lbl.setText(f"📁  {found}")
                else:
                    cover_lbl.setPixmap(QPixmap())
                    cover_lbl.setText("⚠️  تعذّر تحميل الصورة")
                    path_lbl.setText("")
            else:
                cover_lbl.setPixmap(QPixmap())
                cover_lbl.setText("🎮")
                cover_lbl.setStyleSheet(
                    f"color: {c['muted']}; font-size: 36px; background: transparent; border: none;"
                )
                path_lbl.setText("لم تُضَف صورة غلاف بعد")

        _refresh()

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        pick_btn = QPushButton("📂  اختيار صورة")
        pick_btn.setFixedHeight(34)
        pick_btn.setCursor(QCursor(Qt.PointingHandCursor))
        pick_btn.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: #fff;"
            " border: none; border-radius: 8px; font-weight: bold; padding: 0 18px; }"
            f"QPushButton:hover {{ background: {c.get('accent_hover', c['accent'])}; }}"
        )

        def _pick():
            path, _ = QFileDialog.getOpenFileName(
                self, "اختر صورة الغلاف", "",
                "Images (*.png *.jpg *.jpeg)"
            )
            if not path or not os.path.isfile(path):
                return
            os.makedirs(img_dir, exist_ok=True)
            ext  = os.path.splitext(path)[1].lower()
            dest = os.path.join(img_dir, game_name + ext)
            for old_ext in (".png", ".jpg", ".jpeg"):
                old = os.path.join(img_dir, game_name + old_ext)
                if os.path.isfile(old) and old != dest:
                    os.remove(old)
            shutil.copy2(path, dest)
            _refresh()

        pick_btn.clicked.connect(_pick)
        btn_row.addWidget(pick_btn)

        del_btn = QPushButton("🗑  حذف الصورة")
        del_btn.setFixedHeight(34)
        del_btn.setCursor(QCursor(Qt.PointingHandCursor))
        del_btn.setStyleSheet(
            f"QPushButton {{ background: rgba(0,0,0,26); color: {c['accent']};"
            f" border: 1px solid {c['accent']}; border-radius: 8px; padding: 0 16px; }}"
            f"QPushButton:hover {{ background: {c['accent']}; color: #fff; }}"
        )

        def _delete():
            removed = False
            for stem in [game_name, game_id]:
                for ext in (".png", ".jpg", ".jpeg"):
                    p = os.path.join(img_dir, stem + ext)
                    if os.path.isfile(p):
                        os.remove(p)
                        removed = True
            if removed:
                _refresh()
            else:
                QMessageBox.information(self, "تنبيه", "لا توجد صورة لحذفها")

        del_btn.clicked.connect(_delete)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        lay.addStretch()
        return w

    # ── Translation Package tab ───────────────────────────────────────────────

    def _build_package_tab(self, game_id: str, cfg: dict) -> QWidget:
        c   = theme.c
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        try:
            from games.translation_package import TranslationPackage
            pkg = TranslationPackage()
        except ImportError:
            lay.addWidget(QLabel("✗  TranslationPackage غير متاح"))
            return w

        mod_dir = pkg.get_mod_dir(game_id)
        path_lbl = QLabel(f"مجلد الحزمة:  {mod_dir}")
        path_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        lay.addWidget(path_lbl)

        # Files table
        self._pkg_table = QTableWidget(0, 4)
        self._pkg_table.setHorizontalHeaderLabels(["الملف", "المسار الهدف", ".orig", ""])
        self._pkg_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._pkg_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._pkg_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._pkg_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._pkg_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._pkg_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._pkg_table.verticalHeader().hide()
        lay.addWidget(self._pkg_table, 1)

        def _refresh():
            self._pkg_table.setRowCount(0)
            pkg_cfg = pkg.get_config(game_id)
            for entry in pkg_cfg.get("files", []):
                r = self._pkg_table.rowCount()
                self._pkg_table.insertRow(r)
                self._pkg_table.setItem(r, 0, QTableWidgetItem(entry.get("name", "")))
                self._pkg_table.setItem(r, 1, QTableWidgetItem(entry.get("game_target", "")))
                orig_mark = "✓" if entry.get("has_orig") else "✗"
                orig_item = QTableWidgetItem(orig_mark)
                orig_item.setForeground(
                    QColor(c["green"] if entry.get("has_orig") else c["accent"])
                )
                orig_item.setTextAlignment(Qt.AlignCenter)
                self._pkg_table.setItem(r, 2, orig_item)

                del_btn = QToolButton()
                del_btn.setText("✕")
                del_btn.setStyleSheet(
                    f"QToolButton {{ background: transparent; color: {c['accent']};"
                    " border: none; font-weight: bold; }"
                    f"QToolButton:hover {{ color: #fff; background: {c['accent']};"
                    " border-radius: 3px; }"
                )
                del_btn.clicked.connect(
                    lambda _, gt=entry["game_target"]: (
                        pkg.remove_file(game_id, gt), _refresh()
                    )
                )
                self._pkg_table.setCellWidget(r, 3, del_btn)

        _refresh()

        # Buttons row
        btn_row = QHBoxLayout()

        def _add_files():
            paths, _ = QFileDialog.getOpenFileNames(
                self, "اختر ملفات التعريب", "",
                "Game Files (*.uasset *.uexp *.pak *.utoc *.ucas *.locres *.ttf *.ufont);;All (*.*)"
            )
            game_path = cfg.get("game_path", "")
            for fp in paths:
                if not os.path.isfile(fp):
                    continue
                orig_p = fp + ".orig" if os.path.exists(fp + ".orig") else ""
                try:
                    rel = os.path.relpath(fp, game_path).replace("\\", "/")
                except ValueError:
                    rel = os.path.basename(fp)
                pkg.add_file(game_id, fp, orig_p, rel)
            _refresh()

        def _scan_folder():
            folder = QFileDialog.getExistingDirectory(self, "اختر مجلد المصدر", "")
            if not folder:
                return
            game_path = cfg.get("game_path", "")
            found = []
            for root_d, _, files in os.walk(folder):
                for f in files:
                    if os.path.splitext(f)[1].lower() in _SCAN_EXTS:
                        found.append(os.path.join(root_d, f))
            for fp in found:
                orig_p = fp + ".orig" if os.path.exists(fp + ".orig") else ""
                try:
                    rel = os.path.relpath(fp, folder).replace("\\", "/")
                except ValueError:
                    rel = os.path.basename(fp)
                pkg.add_file(game_id, fp, orig_p, rel)
            _refresh()
            QMessageBox.information(self, "✓", f"تمت إضافة {len(found)} ملف")

        def _open_ready():
            ready = pkg.get_ready_dir(game_id)
            os.makedirs(ready, exist_ok=True)
            os.startfile(ready)

        for label, color, slot in [
            ("📄  إضافة ملفات",  "accent", _add_files),
            ("📁  مسح مجلد",    "blue",   _scan_folder),
            ("📂  فتح ready/",  "teal",   _open_ready),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(32)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            clr = theme.c.get(color, theme.c["accent"])
            btn.setStyleSheet(
                f"QPushButton {{ background: rgba(0,0,0,26); color: {clr};"
                f" border: 1px solid {clr}; border-radius: 7px; padding: 0 12px; }}"
                f"QPushButton:hover {{ background: {clr}; color: #fff; }}"
            )
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)

        btn_row.addStretch()
        lay.addLayout(btn_row)

        # ── for_cache section ──────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"QFrame {{ background: {c['border']}; max-height: 1px; border: none; }}")
        lay.addWidget(sep)

        fc_hdr = QHBoxLayout()
        fc_title_lbl = QLabel("📁  ملفات الكاش المرجعي  (for_cache)")
        fc_title_lbl.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {c['secondary']};"
        )
        fc_hdr.addWidget(fc_title_lbl)
        fc_hdr.addStretch()
        fc_st_lbl = QLabel()
        fc_hdr.addWidget(fc_st_lbl)
        lay.addLayout(fc_hdr)

        fc_dir = pkg.get_for_cache_dir(game_id)

        # Table of subfolders inside for_cache/
        fc_table = QTableWidget(0, 3)
        fc_table.setHorizontalHeaderLabels(["المجلد", "الحجم", ""])
        fc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        fc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        fc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        fc_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        fc_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        fc_table.verticalHeader().hide()
        fc_table.setMaximumHeight(120)
        lay.addWidget(fc_table)

        def _dir_size_mb(path: str) -> float:
            total = 0
            for rd, _, fnames in os.walk(path):
                for fn in fnames:
                    try:
                        total += os.path.getsize(os.path.join(rd, fn))
                    except OSError:
                        pass
            return total / 1_048_576

        def _refresh_fc():
            fc_table.setRowCount(0)
            if not os.path.isdir(fc_dir):
                fc_st_lbl.setText("● فارغ")
                fc_st_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
                return
            entries = [
                e for e in sorted(os.listdir(fc_dir))
                if os.path.isdir(os.path.join(fc_dir, e))
            ]
            if not entries:
                fc_st_lbl.setText("● فارغ")
                fc_st_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
                return
            fc_st_lbl.setText(f"● {len(entries)} مجلد")
            fc_st_lbl.setStyleSheet(f"color: {c['green']}; font-size: 10px;")
            for name in entries:
                fp = os.path.join(fc_dir, name)
                r_idx = fc_table.rowCount()
                fc_table.insertRow(r_idx)
                fc_table.setItem(r_idx, 0, QTableWidgetItem(name))
                sz = QTableWidgetItem(f"{_dir_size_mb(fp):.1f} MB")
                sz.setTextAlignment(Qt.AlignCenter)
                fc_table.setItem(r_idx, 1, sz)
                del_fc = QToolButton()
                del_fc.setText("✕")
                del_fc.setStyleSheet(
                    f"QToolButton {{ background: transparent; color: {c['accent']};"
                    " border: none; font-weight: bold; }"
                    f"QToolButton:hover {{ color: #fff; background: {c['accent']};"
                    " border-radius: 3px; }"
                )
                del_fc.clicked.connect(
                    lambda _, p=fp: (shutil.rmtree(p, ignore_errors=True), _refresh_fc())
                )
                fc_table.setCellWidget(r_idx, 2, del_fc)

        _refresh_fc()

        fc_btn_row = QHBoxLayout()

        def _pick_for_cache():
            folder = QFileDialog.getExistingDirectory(
                self, "اختر مجلد for_cache (مثلاً Paks_legacy)", ""
            )
            if not folder or not os.path.isdir(folder):
                return
            ok2, log2 = pkg.copy_to_for_cache(game_id, folder)
            if ok2:
                _refresh_fc()
            else:
                QMessageBox.warning(self, "خطأ", "\n".join(log2))

        def _upload_for_cache():
            if not os.path.isdir(fc_dir) or not any(
                os.path.isdir(os.path.join(fc_dir, e)) for e in os.listdir(fc_dir)
            ):
                QMessageBox.warning(
                    self, "تنبيه", "مجلد for_cache فارغ — اختر مجلداً أولاً"
                )
                return
            manifest_path2 = os.path.join(_PROJECT_ROOT, "manifest.json")
            cur_ver2 = ""
            try:
                with open(manifest_path2, encoding="utf-8") as fh2:
                    m2 = json.load(fh2)
                cur_ver2 = m2.get("translations", {}).get(game_id, {}).get("version", "")
            except Exception:
                pass
            if not cur_ver2:
                QMessageBox.warning(self, "تنبيه", "انشر الترجمة أولاً ثم ارفع for_cache")
                return
            log_dlg2 = _LogDialog(
                f"☁️  رفع for_cache — {game_id} v{cur_ver2}", parent=self
            )
            worker2 = _ForCacheUploadWorker(game_id, cur_ver2, fc_dir, manifest_path2)
            worker2.log_line.connect(log_dlg2.append_line)
            worker2.finished.connect(log_dlg2.set_finished)
            self._fc_worker = worker2
            worker2.start()
            log_dlg2.exec()

        for fc_label, fc_color, fc_slot in [
            ("📁  تحديد/تحديث",  "teal", _pick_for_cache),
            ("☁️  رفع للسحابة", "blue", _upload_for_cache),
        ]:
            fc_btn = QPushButton(fc_label)
            fc_btn.setFixedHeight(30)
            fc_btn.setCursor(QCursor(Qt.PointingHandCursor))
            fc_clr = theme.c.get(fc_color, theme.c["accent"])
            fc_btn.setStyleSheet(
                f"QPushButton {{ background: rgba(0,0,0,26); color: {fc_clr};"
                f" border: 1px solid {fc_clr}; border-radius: 7px; padding: 0 12px; }}"
                f"QPushButton:hover {{ background: {fc_clr}; color: #fff; }}"
            )
            fc_btn.clicked.connect(fc_slot)
            fc_btn_row.addWidget(fc_btn)

        fc_btn_row.addStretch()
        lay.addLayout(fc_btn_row)
        return w

    # ── Raw config tab ────────────────────────────────────────────────────────

    def _build_config_tab(self, game_id: str, cfg: dict) -> QWidget:
        c   = theme.c
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        hint = QLabel("تحرير مباشر لملف إعدادات اللعبة JSON — تأكد من صحة الصياغة قبل الحفظ")
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        lay.addWidget(hint)

        editor = QTextEdit()
        editor.setFont(QFont("Consolas", 10))
        editor.setPlainText(json.dumps(cfg, indent=2, ensure_ascii=False))
        lay.addWidget(editor, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        save_btn = QPushButton("💾  حفظ الإعدادات")
        save_btn.setFixedHeight(34)
        save_btn.setCursor(QCursor(Qt.PointingHandCursor))
        save_btn.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: #fff;"
            " border: none; border-radius: 8px; font-weight: bold; padding: 0 18px; }"
        )

        def _save():
            try:
                new_cfg = json.loads(editor.toPlainText())
            except json.JSONDecodeError as e:
                QMessageBox.critical(self, "خطأ", f"JSON غير صالح:\n{e}")
                return
            if self._gm:
                self._gm.update_game(game_id, new_cfg)
            QMessageBox.information(self, "✓", "تم حفظ الإعدادات")

        save_btn.clicked.connect(_save)
        btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)
        return w

    # ── Cache tab ─────────────────────────────────────────────────────────────

    def _build_cache_tab(self, game_id: str, cfg: dict) -> QWidget:
        c    = theme.c
        w    = QWidget()
        lay  = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(14)

        game_name = cfg.get("name", game_id)

        stats_card = QFrame()
        stats_card.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']};"
            " border-radius: 8px; }"
        )
        sc_lay = QVBoxLayout(stats_card)
        sc_lay.setContentsMargins(16, 12, 16, 12)
        sc_lay.setSpacing(8)

        self._cache_stats_lbl = QLabel("جاري التحميل…")
        self._cache_stats_lbl.setStyleSheet(f"color: {c['secondary']}; font-size: 12px;")
        sc_lay.addWidget(self._cache_stats_lbl)
        lay.addWidget(stats_card)

        def _refresh_stats():
            if not self._cache:
                self._cache_stats_lbl.setText("لا يوجد كاش متاح")
                return
            try:
                count = self._cache.count_entries(game_name)
                stats = self._cache.get_stats(game_name) if hasattr(self._cache, "get_stats") else {}
                lines = [
                    f"إجمالي الترجمات:  {count:,}",
                    f"إجمالي الطلبات:   {stats.get('cache_hits', 0):,}",
                    f"الفاشلة:          {stats.get('failed_count', 0):,}",
                ]
                self._cache_stats_lbl.setText("\n".join(lines))
            except Exception as e:
                self._cache_stats_lbl.setText(f"خطأ: {e}")

        _refresh_stats()

        btn_row = QHBoxLayout()

        def _vacuum():
            reply = QMessageBox.question(
                self, "تأكيد",
                f"حذف كل ترجمات:\n«{game_name}»\nهذا الإجراء لا يمكن التراجع عنه.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes and self._cache:
                try:
                    self._cache.delete_game(game_name)
                    _refresh_stats()
                    QMessageBox.information(self, "✓", "تم مسح كاش اللعبة")
                except Exception as e:
                    QMessageBox.critical(self, "خطأ", str(e))

        del_btn = QPushButton("🗑️  مسح كاش هذه اللعبة")
        del_btn.setFixedHeight(34)
        del_btn.setCursor(QCursor(Qt.PointingHandCursor))
        del_btn.setStyleSheet(
            f"QPushButton {{ background: rgba(0,0,0,26); color: {c['accent']};"
            f" border: 1px solid {c['accent']}; border-radius: 8px; padding: 0 16px; }}"
            f"QPushButton:hover {{ background: {c['accent']}; color: #fff; }}"
        )
        del_btn.clicked.connect(_vacuum)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        lay.addStretch()
        return w

    # ── Translation release tab ───────────────────────────────────────────────

    def _build_release_tab(self, game_id: str, cfg: dict) -> QWidget:
        c   = theme.c
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        manifest_path = os.path.join(_PROJECT_ROOT, "manifest.json")

        try:
            from games.translation_package import TranslationPackage
            pkg       = TranslationPackage()
            ready_dir = pkg.get_ready_dir(game_id)
        except ImportError:
            lay.addWidget(QLabel("✗  TranslationPackage غير متاح"))
            return w

        # Current published version from manifest
        cur_ver = "—"
        try:
            with open(manifest_path, encoding="utf-8") as f:
                m = json.load(f)
            cur_ver = m.get("translations", {}).get(game_id, {}).get("version", "—")
        except Exception:
            pass

        # Info card
        info_card = QFrame()
        info_card.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']};"
            " border-radius: 8px; }"
        )
        ic_lay = QVBoxLayout(info_card)
        ic_lay.setContentsMargins(14, 10, 14, 10)
        ic_lay.setSpacing(6)

        ver_lbl = QLabel(f"الإصدار المنشور:  <b>{cur_ver}</b>")
        ver_lbl.setStyleSheet(f"color: {c['secondary']}; font-size: 12px;")
        ic_lay.addWidget(ver_lbl)

        # Files in ready/
        ready_files: list[str] = []
        if os.path.isdir(ready_dir):
            ready_files = sorted(
                f for f in os.listdir(ready_dir)
                if os.path.isfile(os.path.join(ready_dir, f))
            )
        files_text = (
            "ملفات ready/:  " + "،  ".join(ready_files)
            if ready_files
            else "⚠  مجلد ready/ فارغ — أضف ملفات الترجمة أولاً"
        )
        files_lbl = QLabel(files_text)
        files_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        files_lbl.setWordWrap(True)
        ic_lay.addWidget(files_lbl)

        path_lbl = QLabel(f"المسار:  {ready_dir}")
        path_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 9px;")
        path_lbl.setWordWrap(True)
        ic_lay.addWidget(path_lbl)

        lay.addWidget(info_card)

        # New version input
        ver_row = QHBoxLayout()
        ver_row_lbl = QLabel("إصدار جديد:")
        ver_row_lbl.setStyleSheet(f"color: {c['primary']}; font-size: 12px;")
        ver_row.addWidget(ver_row_lbl)
        ver_input = QLineEdit()
        ver_input.setFixedWidth(110)
        ver_input.setPlaceholderText("مثال: 0.3")
        ver_row.addWidget(ver_input)
        ver_row.addStretch()
        lay.addLayout(ver_row)

        note = QLabel(
            "سيتم إنشاء GitHub Release ورفع الملفات، ثم تحديث manifest.json والـ git push.\n"
            "المستخدمون سيرون شارة التحديث عند فتح التطبيق."
        )
        note.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        note.setWordWrap(True)
        lay.addWidget(note)

        lay.addStretch()

        pub_btn = QPushButton("🚀  نشر الترجمة")
        pub_btn.setFixedHeight(38)
        pub_btn.setCursor(QCursor(Qt.PointingHandCursor))
        pub_btn.setEnabled(bool(ready_files))
        pub_btn.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: #fff;"
            " border: none; border-radius: 8px; font-weight: bold; padding: 0 20px; }"
            "QPushButton:disabled { background: #444; color: #666; }"
        )

        def _publish():
            version = ver_input.text().strip()
            if not version:
                QMessageBox.warning(w, "تنبيه", "أدخل رقم الإصدار الجديد")
                return
            # game_target map: from existing manifest first, fallback to filename
            file_targets: dict = {}
            try:
                with open(manifest_path, encoding="utf-8") as fh:
                    m2 = json.load(fh)
                for ef in m2.get("translations", {}).get(game_id, {}).get("files", []):
                    file_targets[ef["name"]] = ef.get("game_target", ef["name"])
            except Exception:
                pass

            log_dlg = _LogDialog(f"🚀  نشر ترجمة {game_id} v{version}", parent=self)
            worker  = _TranslationReleaseWorker(
                game_id, version, ready_dir, manifest_path, file_targets
            )
            worker.log_line.connect(log_dlg.append_line)
            worker.finished.connect(log_dlg.set_finished)
            self._tr_worker = worker   # prevent GC
            worker.start()
            log_dlg.exec()

        pub_btn.clicked.connect(_publish)
        lay.addWidget(pub_btn)
        return w

    # ── App release dialog ────────────────────────────────────────────────────

    def _open_app_release_dialog(self):
        c = theme.c

        cur_ver = "?"
        try:
            from games.translation_registry import APP_VERSION
            cur_ver = APP_VERSION
        except Exception:
            pass

        dlg = QDialog(self)
        dlg.setWindowTitle("🚀  إصدار تحديث التطبيق")
        dlg.setFixedSize(430, 215)
        dlg.setStyleSheet(
            f"QDialog  {{ background: {c['bg']}; }}"
            f"QLabel   {{ color: {c['primary']}; background: transparent; border: none; }}"
            f"QLineEdit {{ background: {c['surface']}; color: {c['primary']};"
            f" border: 1px solid {c['border']}; border-radius: 6px; padding: 4px 8px; }}"
            f"QLineEdit:focus {{ border-color: {c['accent']}; }}"
        )
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        cur_lbl = QLabel(f"الإصدار الحالي:  {cur_ver}")
        cur_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        lay.addWidget(cur_lbl)

        row = QHBoxLayout()
        row_lbl = QLabel("الإصدار الجديد:")
        row_lbl.setStyleSheet(f"color: {c['primary']}; font-size: 12px;")
        row.addWidget(row_lbl)
        ver_input = QLineEdit()
        ver_input.setFixedWidth(120)
        ver_input.setPlaceholderText("مثال: 1.6")
        row.addWidget(ver_input)
        row.addStretch()
        lay.addLayout(row)

        note = QLabel(
            "⚠  ستبدأ عملية البناء الكاملة بـ PyInstaller ثم النشر على GitHub.\n"
            "العملية قد تستغرق 5–15 دقيقة."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        lay.addWidget(note)

        br = QHBoxLayout()
        cancel = QPushButton("إلغاء")
        cancel.setCursor(QCursor(Qt.PointingHandCursor))
        cancel.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; color: {c['muted']};"
            f" border: 1px solid {c['border']}; border-radius: 8px; padding: 6px 18px; }}"
            f"QPushButton:hover {{ background: {c['hover']}; }}"
        )
        cancel.clicked.connect(dlg.reject)

        pub_btn = QPushButton("🚀  بدء النشر")
        pub_btn.setCursor(QCursor(Qt.PointingHandCursor))
        pub_btn.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: #fff;"
            " border: none; border-radius: 8px; font-weight: bold; padding: 6px 18px; }"
        )

        def _start():
            version = ver_input.text().strip()
            if not version:
                QMessageBox.warning(dlg, "تنبيه", "أدخل رقم الإصدار")
                return
            dlg.accept()
            log_dlg = _LogDialog(f"🚀  إصدار التطبيق v{version} — السجل", parent=self)
            worker  = _AppReleaseWorker(version)
            worker.log_line.connect(log_dlg.append_line)
            worker.finished.connect(log_dlg.set_finished)
            self._app_worker = worker   # prevent GC
            worker.start()
            log_dlg.exec()

        pub_btn.clicked.connect(_start)
        br.addWidget(cancel)
        br.addStretch()
        br.addWidget(pub_btn)
        lay.addLayout(br)
        dlg.exec()

    # ── System info ───────────────────────────────────────────────────────────

    def _show_sysinfo(self):
        c = theme.c
        try:
            from PySide6 import __version__ as pyside_ver
        except Exception:
            pyside_ver = "?"
        try:
            import sqlite3
            sqlite_ver = sqlite3.sqlite_version
        except Exception:
            sqlite_ver = "?"

        lines = [
            f"Python:      {sys.version.split()[0]}",
            f"PySide6:     {pyside_ver}",
            f"SQLite:      {sqlite_ver}",
            f"Platform:    {sys.platform}",
            f"",
            f"Project:     {os.path.dirname(self._config_path) if self._config_path else '—'}",
        ]

        if self._cache:
            try:
                db_path = getattr(self._cache, "_db_path", None) or getattr(self._cache, "db_path", None)
                if db_path and os.path.exists(db_path):
                    size_mb = os.path.getsize(db_path) / 1_048_576
                    lines.append(f"Cache DB:    {db_path}")
                    lines.append(f"Cache size:  {size_mb:.2f} MB")
            except Exception:
                pass

        dlg = QDialog(self)
        dlg.setWindowTitle("🖥️  معلومات النظام")
        dlg.setFixedSize(460, 300)
        dlg.setStyleSheet(f"QDialog {{ background: {c['bg']}; }}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 16, 20, 16)

        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setFont(QFont("Consolas", 10))
        txt.setStyleSheet(
            f"background: {c['surface']}; color: {c['secondary']};"
            f" border: 1px solid {c['border']}; border-radius: 6px; padding: 8px;"
        )
        txt.setPlainText("\n".join(lines))
        lay.addWidget(txt)

        copy_btn = QPushButton("📋  نسخ")
        copy_btn.setCursor(QCursor(Qt.PointingHandCursor))
        copy_btn.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; color: {c['muted']};"
            f" border: 1px solid {c['border']}; border-radius: 6px; padding: 4px 14px; }}"
            f"QPushButton:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}"
        )
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(txt.toPlainText())
        )
        ok = QPushButton("موافق")
        ok.setCursor(QCursor(Qt.PointingHandCursor))
        ok.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: #fff;"
            " border: none; border-radius: 6px; padding: 4px 18px; font-weight: bold; }"
        )
        ok.clicked.connect(dlg.accept)
        br = QHBoxLayout()
        br.addWidget(copy_btn)
        br.addStretch()
        br.addWidget(ok)
        lay.addLayout(br)
        dlg.exec()

    # ── PIN save ──────────────────────────────────────────────────────────────

    def _save_pin(self):
        pin = self._new_pin.text().strip()
        if len(pin) < 4:
            QMessageBox.warning(self, "تنبيه", "يجب أن يكون PIN على الأقل 4 أرقام")
            return
        h = hashlib.sha256(pin.encode()).hexdigest()
        self._config.setdefault("admin", {})["pin_hash"] = h
        if self._config_path:
            try:
                with open(self._config_path, "w", encoding="utf-8") as f:
                    json.dump(self._config, f, indent=2, ensure_ascii=False)
            except Exception as e:
                QMessageBox.critical(self, "خطأ", f"فشل الحفظ: {e}")
                return
        self._new_pin.clear()
        QMessageBox.information(self, "✓", "تم حفظ PIN الجديد")


# ── Public launcher ───────────────────────────────────────────────────────────

def open_admin(game_manager, cache, config: dict, config_path: str,
               parent=None) -> "AdminPanel | None":
    """
    يعرض حوار PIN أولاً (modal) ثم يفتح لوحة الإدارة بدون حجب التطبيق.
    يُعيد instance اللوحة لربط الـ signals خارجياً، أو None إذا أُلغي PIN.
    """
    pin_dlg = PINDialog(config, parent=parent)
    result  = [False]

    def _on_verified():
        result[0] = True

    pin_dlg.verified.connect(_on_verified)
    pin_dlg.exec()   # PIN يبقى modal

    if not result[0]:
        return None

    admin = AdminPanel(game_manager, cache, config, config_path, parent=parent)
    admin.setModal(False)          # لا يحجب التطبيق
    admin.setAttribute(Qt.WA_DeleteOnClose, False)
    admin.show()
    admin.raise_()
    admin.activateWindow()
    return admin
