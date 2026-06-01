"""
gui/qt/pages/unrealpak.py  —  صفحة فك وحزم ملفات .pak  (UnrealPak)

العمليات المدعومة:
  - فك الحزمة:  UnrealPak.exe <pak> -extract <folder>
  - إنشاء حزمة: UnrealPak.exe <out.pak> -create=<responsefile>
"""
from __future__ import annotations
import base64
import binascii
import json
import os
import subprocess
import tempfile

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QLineEdit, QFileDialog, QProgressBar,
    QTextEdit, QScrollArea, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui  import QCursor, QTextCursor

from gui.qt.theme import theme

_CFG = "config.json"
_CREATE_NO_WINDOW = 0x08000000


# ── Config helpers ──────────────────────────────────────────────────────────────

def _load_pak_path() -> str:
    try:
        with open(_CFG, encoding="utf-8") as f:
            return json.load(f).get("tools", {}).get("unrealpak_path", "")
    except Exception:
        return ""


def _save_pak_path(path: str):
    try:
        with open(_CFG, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg.setdefault("tools", {})["unrealpak_path"] = path
        with open(_CFG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load_aes_key() -> str:
    try:
        with open(_CFG, encoding="utf-8") as f:
            return json.load(f).get("tools", {}).get("unrealpak_aes", "")
    except Exception:
        return ""


def _save_aes_key(key: str):
    try:
        with open(_CFG, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg.setdefault("tools", {})["unrealpak_aes"] = key
        with open(_CFG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _hex_to_b64(hex_key: str) -> str:
    """تحويل مفتاح AES من hex (64 حرف) إلى base64 (44 حرف)."""
    hex_key = hex_key.strip().lstrip("0x").lstrip("0X").replace(" ", "")
    raw = binascii.unhexlify(hex_key)
    return base64.b64encode(raw).decode()


def _key_to_b64(key: str) -> str:
    """قبول المفتاح بصيغة hex أو base64 وإعادته كـ base64 دائماً."""
    key = key.strip()
    clean = key.lstrip("0x").lstrip("0X").replace(" ", "")
    if len(clean) == 64 and all(c in "0123456789abcdefABCDEF" for c in clean):
        return _hex_to_b64(clean)
    return key   # already base64


def _write_crypto_json(b64_key: str) -> str:
    """كتابة ملف crypto.json مؤقت وإعادة مساره."""
    data = {
        "EncryptionKey": {"Name": "", "Guid": "00000000000000000000000000000000", "Key": b64_key},
        "SigningKey": {"PublicExponent": "", "PrivateExponent": "", "PublicModulus": ""},
        "bEnablePakIndexEncryption": True,
        "bEnablePakIniEncryption": True,
        "bEnablePakUAssetEncryption": False,
        "bEnablePakFullAssetEncryption": False,
        "bDataCryptoRequired": True,
        "SecondaryEncryptionKeys": [],
    }
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix="_crypto.json", delete=False, encoding="utf-8"
    )
    json.dump(data, tmp)
    tmp.close()
    return tmp.name


# ── Workers ─────────────────────────────────────────────────────────────────────

class _UnpackWorker(QThread):
    logged   = Signal(str, str)   # msg, color_key
    finished = Signal(bool, str)  # ok, message

    def __init__(self, tool: str, pak: str, out_dir: str,
                 aes_key: str = "", path_filter: str = ""):
        super().__init__()
        self._tool    = tool
        self._pak     = pak
        self._out_dir = out_dir
        self._aes     = aes_key.strip()
        self._filter  = path_filter.strip()

    def run(self):
        crypto_file = ""
        os.makedirs(self._out_dir, exist_ok=True)
        try:
            cmd = [self._tool, self._pak, "-extract", self._out_dir]
            if self._aes:
                try:
                    b64 = _key_to_b64(self._aes)
                    crypto_file = _write_crypto_json(b64)
                    cmd.append(f"-cryptokeys={crypto_file}")
                    self.logged.emit(f"🔑  مفتاح AES مُحمَّل ({len(self._aes)} حرف)", "teal")
                except Exception as e:
                    self.logged.emit(f"⚠  خطأ في تحويل المفتاح: {e}", "yellow")
            if self._filter:
                cmd.append(f"-Filter={self._filter}")
                self.logged.emit(f"🔍  تصفية: {self._filter}", "teal")

            self.logged.emit(f"⚡  {' '.join(cmd)}", "muted")
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600,
                creationflags=_CREATE_NO_WINDOW,
            )
            out = (r.stdout + r.stderr).strip()
            if r.returncode == 0:
                self.logged.emit("✅  اكتمل فك الحزمة", "green")
                if out:
                    self.logged.emit(out, "muted")
                self.finished.emit(True, f"✅  تم الفك إلى:\n{self._out_dir}")
            else:
                err = out or f"كود الخطأ: {r.returncode}"
                self.logged.emit(f"❌  {err}", "accent")
                self.finished.emit(False, f"❌  فشل فك الحزمة:\n{err}")
        except subprocess.TimeoutExpired:
            self.finished.emit(False, "❌  انتهت مهلة العملية (10 دقائق)")
        except Exception as e:
            self.finished.emit(False, f"❌  خطأ: {e}")
        finally:
            if crypto_file:
                try:
                    os.unlink(crypto_file)
                except Exception:
                    pass


class _PackWorker(QThread):
    logged   = Signal(str, str)
    progress = Signal(int, int)
    finished = Signal(bool, str)

    def __init__(self, tool: str, src_dir: str, out_pak: str, mount_prefix: str):
        super().__init__()
        self._tool   = tool
        self._src    = src_dir
        self._out    = out_pak
        self._prefix = mount_prefix.rstrip("/\\")

    def run(self):
        # جمع الملفات
        files: list[tuple[str, str]] = []
        for root, _, fnames in os.walk(self._src):
            for fn in fnames:
                abs_path = os.path.join(root, fn)
                rel      = os.path.relpath(abs_path, self._src).replace("\\", "/")
                mount    = f"{self._prefix}/{rel}"
                files.append((abs_path, mount))

        if not files:
            self.finished.emit(False, "❌  لا توجد ملفات في المجلد المحدد")
            return

        self.logged.emit(f"📁  وُجد {len(files):,} ملف", "teal")

        # كتابة ملف الاستجابة
        tmp_resp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        )
        try:
            for abs_path, mount in files:
                tmp_resp.write(f'"{abs_path}" "{mount}"\n')
            tmp_resp.close()
            self.logged.emit(f"📝  ملف الاستجابة: {tmp_resp.name}", "muted")

            cmd = [self._tool, self._out, f"-create={tmp_resp.name}"]
            self.logged.emit(f"⚡  {' '.join(cmd)}", "muted")

            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600,
                creationflags=_CREATE_NO_WINDOW,
            )
            out = (r.stdout + r.stderr).strip()
            if r.returncode == 0:
                size_mb = os.path.getsize(self._out) / (1024 * 1024) if os.path.isfile(self._out) else 0
                self.logged.emit(f"✅  تم إنشاء الحزمة  ({size_mb:.1f} MB)", "green")
                if out:
                    self.logged.emit(out, "muted")
                self.finished.emit(True, f"✅  الحزمة جاهزة:\n{self._out}")
            else:
                err = out or f"كود الخطأ: {r.returncode}"
                self.logged.emit(f"❌  {err}", "accent")
                self.finished.emit(False, f"❌  فشل إنشاء الحزمة:\n{err}")
        except subprocess.TimeoutExpired:
            self.finished.emit(False, "❌  انتهت مهلة العملية (10 دقائق)")
        except Exception as e:
            self.finished.emit(False, f"❌  خطأ: {e}")
        finally:
            try:
                os.unlink(tmp_resp.name)
            except Exception:
                pass


# ── UI helpers ──────────────────────────────────────────────────────────────────

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


def _card(c: dict) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setStyleSheet(
        f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']};"
        f" border-radius: 10px; }}"
    )
    lay = QVBoxLayout(card)
    lay.setContentsMargins(16, 14, 16, 16)
    lay.setSpacing(10)
    return card, lay


def _section_title(text: str, color: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"font-size: 13px; font-weight: bold; color: {color};"
        " background: transparent; border: none;"
    )
    return lbl


def _hint(text: str, c: dict) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px; background: transparent; border: none;")
    lbl.setWordWrap(True)
    return lbl


def _path_row(edit: QLineEdit, label: str, c: dict,
              is_dir: bool = False, save_file: bool = False) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(8)
    lbl = QLabel(label)
    lbl.setFixedWidth(100)
    lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px; background: transparent; border: none;")
    browse = _btn("📂", c["blue"], 30)
    browse.setFixedWidth(36)

    def _pick():
        if is_dir:
            path = QFileDialog.getExistingDirectory(None, label, edit.text() or "")
        elif save_file:
            path, _ = QFileDialog.getSaveFileName(
                None, label, edit.text() or "",
                "PAK Files (*.pak);;All Files (*)"
            )
        else:
            path, _ = QFileDialog.getOpenFileName(
                None, label, edit.text() or "",
                "PAK Files (*.pak);;All Files (*)"
            )
        if path:
            edit.setText(path)

    browse.clicked.connect(_pick)
    row.addWidget(lbl)
    row.addWidget(edit, 1)
    row.addWidget(browse)
    return row


def _log_widget(c: dict, h: int = 130) -> QTextEdit:
    w = QTextEdit()
    w.setReadOnly(True)
    w.setFixedHeight(h)
    w.setStyleSheet(
        f"QTextEdit {{ background: {c['bg']}; color: {c['secondary']};"
        f" border: 1px solid {c['border']}; border-radius: 6px;"
        f" font-family: Consolas, monospace; font-size: 10px; padding: 6px; }}"
    )
    return w


# ── Main page ───────────────────────────────────────────────────────────────────

class UnrealPakPage(QWidget):

    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._unpack_worker: _UnpackWorker | None = None
        self._pack_worker:   _PackWorker   | None = None
        self._build()

    # ── Build ──────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        lay = self.layout()
        if lay:
            while lay.count():
                item = lay.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        self.setStyleSheet("")
        self._build()

    def _build(self):
        c = theme.c

        root = self.layout()
        if root is None:
            root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header(c))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; } QScrollArea > QWidget { background: transparent; }")
        body_w = QWidget()
        body_w.setObjectName("unrealpak_body")
        body_w.setStyleSheet("QWidget#unrealpak_body { background: transparent; }")
        blay = QVBoxLayout(body_w)
        blay.setContentsMargins(20, 20, 20, 20)
        blay.setSpacing(16)

        # ── Tool path + AES key ────────────────────────────────────────────────
        tool_card, tool_lay = _card(c)
        tool_lay.addWidget(_section_title("🔧  مسار UnrealPak.exe", c["teal"]))
        self._tool_edit = QLineEdit(_load_pak_path())
        self._tool_edit.setPlaceholderText("مسار UnrealPak.exe …")
        self._tool_edit.textChanged.connect(lambda p: _save_pak_path(p.strip()))
        tr = _path_row(self._tool_edit, "UnrealPak:", c)
        # override browse to filter .exe
        browse_exe = _btn("📂", c["blue"], 30)
        browse_exe.setFixedWidth(36)
        def _pick_exe():
            p, _ = QFileDialog.getOpenFileName(
                None, "اختر UnrealPak.exe", self._tool_edit.text() or "",
                "EXE Files (*.exe);;All Files (*)"
            )
            if p:
                self._tool_edit.setText(p)
                _save_pak_path(p)
        browse_exe.clicked.connect(_pick_exe)
        tr.itemAt(2).widget().deleteLater()
        tr.addWidget(browse_exe)
        tool_lay.addLayout(tr)

        # AES key row
        aes_row = QHBoxLayout()
        aes_row.setSpacing(8)
        aes_lbl = QLabel("🔑  مفتاح AES:")
        aes_lbl.setFixedWidth(100)
        aes_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px; background: transparent; border: none;")
        self._aes_edit = QLineEdit(_load_aes_key())
        self._aes_edit.setPlaceholderText(
            "اختياري — مفتاح التشفير AES-256 (hex 64 حرف أو base64 44 حرف) …"
        )
        self._aes_edit.setEchoMode(QLineEdit.Password)
        self._aes_edit.textChanged.connect(lambda k: _save_aes_key(k.strip()))
        show_btn = _btn("👁", c["muted"], 30)
        show_btn.setFixedWidth(36)
        show_btn.setCheckable(True)
        show_btn.toggled.connect(
            lambda on: self._aes_edit.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password
            )
        )
        hint_lbl = QLabel("(للألعاب المشفّرة فقط — اتركه فارغاً إذا لم يكن الـ pak مشفّراً)")
        hint_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 9px; background: transparent; border: none;")
        aes_row.addWidget(aes_lbl)
        aes_row.addWidget(self._aes_edit, 1)
        aes_row.addWidget(show_btn)
        tool_lay.addLayout(aes_row)
        tool_lay.addWidget(hint_lbl)
        blay.addWidget(tool_card)

        # ── Two columns: Unpack | Pack ────────────────────────────────────────
        cols = QHBoxLayout()
        cols.setSpacing(16)
        cols.addWidget(self._build_unpack_card(c), 1)
        cols.addWidget(self._build_pack_card(c), 1)
        blay.addLayout(cols)

        # ── Shared log ────────────────────────────────────────────────────────
        log_card, log_lay = _card(c)
        log_lay.addWidget(_section_title("📋  السجل", c["muted"]))
        self._log = _log_widget(c, 200)
        log_lay.addWidget(self._log)
        blay.addWidget(log_card)

        blay.addStretch()
        scroll.setWidget(body_w)
        root.addWidget(scroll, 1)
        root.addWidget(self._build_statusbar(c))

    def _build_header(self, c: dict) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(58)
        bar.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-bottom: 1px solid {c['border']}; }}"
        )
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(22, 0, 22, 0)
        t = QLabel("📦  فك وحزم ملفات PAK  —  UnrealPak")
        t.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {c['teal']};")
        hl.addWidget(t)
        hl.addStretch()
        sub = QLabel("UE4 / UE5")
        sub.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        hl.addWidget(sub)
        return bar

    def _build_unpack_card(self, c: dict) -> QFrame:
        card, lay = _card(c)
        lay.addWidget(_section_title("📂  فك الحزمة  (.pak → مجلد)", c["blue"]))
        lay.addWidget(_hint(
            "اختر ملف .pak واضغط «فك» لاستخراج محتوياته إلى مجلد.", c
        ))

        self._unpack_pak    = QLineEdit()
        self._unpack_pak.setPlaceholderText("ملف .pak للاستخراج …")
        self._unpack_outdir = QLineEdit()
        self._unpack_outdir.setPlaceholderText("مجلد الإخراج …")

        lay.addLayout(_path_row(self._unpack_pak,    "ملف .pak:", c))
        lay.addLayout(_path_row(self._unpack_outdir, "مجلد الإخراج:", c, is_dir=True))

        # ── تصفية المسار (اختياري) ────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {c['border']}; background: {c['border']}; border: none; max-height: 1px;")
        lay.addWidget(sep)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        f_lbl = QLabel("🔍  تصفية المسار:")
        f_lbl.setFixedWidth(110)
        f_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px; background: transparent; border: none;")
        self._unpack_filter = QLineEdit()
        self._unpack_filter.setPlaceholderText("اختياري — مثال:  *Localization*  أو  */Content/Localization/*")
        self._unpack_filter.setStyleSheet(
            f"QLineEdit {{ background: {c['surface']}; color: {c['primary']};"
            f" border: 1px solid {c['border']}88; border-radius: 6px; padding: 4px 8px; font-size: 11px; }}"
            f"QLineEdit:focus {{ border: 1px solid {c['border']}; }}"
        )
        self._unpack_filter.setToolTip(
            "استخراج ملفات مطابقة للنمط فقط.\n"
            "أمثلة:\n"
            "  *Localization*         ← كل ملفات Localization\n"
            "  *Localization/Game/*   ← مجلد Game داخل Localization\n"
            "  *.locres               ← ملفات locres فقط\n"
            "اتركه فارغاً لاستخراج كل المحتويات."
        )
        filter_row.addWidget(f_lbl)
        filter_row.addWidget(self._unpack_filter, 1)
        lay.addLayout(filter_row)
        lay.addWidget(_hint(
            "تصفح المسار اختياري — فارغ = استخراج كل شيء  │  "
            "نمط: *Localization* أو *Localization/Game/*", c
        ))

        self._unpack_prog = QProgressBar()
        self._unpack_prog.setRange(0, 0)
        self._unpack_prog.setFixedHeight(6)
        self._unpack_prog.setTextVisible(False)
        self._unpack_prog.setVisible(False)
        self._unpack_prog.setStyleSheet(
            f"QProgressBar {{ background: {c['surface']}; border: none; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {c['blue']}; border-radius: 3px; }}"
        )
        lay.addWidget(self._unpack_prog)

        self._unpack_btn = _btn("▶  فك الحزمة", c["blue"])
        self._unpack_btn.clicked.connect(self._run_unpack)
        lay.addWidget(self._unpack_btn)
        return card

    def _build_pack_card(self, c: dict) -> QFrame:
        card, lay = _card(c)
        lay.addWidget(_section_title("📦  إنشاء حزمة  (مجلد → .pak)", c["teal"]))
        lay.addWidget(_hint(
            "اختر مجلد المصدر ومسار الإخراج. سيُنشأ ملف .pak جاهز للعبة.", c
        ))

        self._pack_srcdir  = QLineEdit()
        self._pack_srcdir.setPlaceholderText("مجلد المصدر (الجذر) …")
        self._pack_outpak  = QLineEdit()
        self._pack_outpak.setPlaceholderText("ملف .pak الناتج …")
        self._pack_mount   = QLineEdit("../../../")
        self._pack_mount.setPlaceholderText("../../../")
        self._pack_mount.setToolTip(
            "بادئة مسار التثبيت داخل الحزمة.\n"
            "القيمة الافتراضية  ../../../  صحيحة لمعظم ألعاب UE4/UE5."
        )

        lay.addLayout(_path_row(self._pack_srcdir, "مجلد المصدر:", c, is_dir=True))
        lay.addLayout(_path_row(self._pack_outpak, "ملف الإخراج:", c, save_file=True))

        mount_row = QHBoxLayout()
        mount_row.setSpacing(8)
        ml = QLabel("بادئة التثبيت:")
        ml.setFixedWidth(100)
        ml.setStyleSheet(f"color: {c['muted']}; font-size: 10px; background: transparent; border: none;")
        mount_row.addWidget(ml)
        mount_row.addWidget(self._pack_mount)
        lay.addLayout(mount_row)

        self._pack_prog = QProgressBar()
        self._pack_prog.setRange(0, 0)
        self._pack_prog.setFixedHeight(6)
        self._pack_prog.setTextVisible(False)
        self._pack_prog.setVisible(False)
        self._pack_prog.setStyleSheet(
            f"QProgressBar {{ background: {c['surface']}; border: none; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {c['teal']}; border-radius: 3px; }}"
        )
        lay.addWidget(self._pack_prog)

        self._pack_btn = _btn("▶  إنشاء حزمة", c["teal"])
        self._pack_btn.clicked.connect(self._run_pack)
        lay.addWidget(self._pack_btn)
        return card

    def _build_statusbar(self, c: dict) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(36)
        bar.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-top: 1px solid {c['border']}; }}"
        )
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(18, 0, 18, 0)
        self._status_lbl = QLabel("جاهز")
        self._status_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        hl.addWidget(self._status_lbl)
        return bar

    # ── Logic ──────────────────────────────────────────────────────────────────

    def _log_msg(self, msg: str, color_key: str = "secondary"):
        color = theme.c.get(color_key, theme.c["secondary"])
        self._log.append(f'<span style="color:{color};">{msg}</span>')
        self._log.moveCursor(QTextCursor.End)

    def _set_status(self, msg: str):
        self._status_lbl.setText(msg)
        self.status_message.emit(msg)

    def _tool_path(self) -> str:
        return self._tool_edit.text().strip()

    def _validate_tool(self) -> bool:
        if not self._tool_path() or not os.path.isfile(self._tool_path()):
            self._log_msg("❌  حدّد مسار UnrealPak.exe أولاً", "accent")
            self._set_status("⚠  UnrealPak.exe غير محدد")
            return False
        return True

    # ── Unpack ────────────────────────────────────────────────────────────────

    def _run_unpack(self):
        if not self._validate_tool():
            return
        pak = self._unpack_pak.text().strip()
        out = self._unpack_outdir.text().strip()
        if not pak or not os.path.isfile(pak):
            self._log_msg("❌  اختر ملف .pak صحيح أولاً", "accent")
            return
        if not out:
            self._log_msg("❌  حدّد مجلد الإخراج أولاً", "accent")
            return

        self._unpack_btn.setEnabled(False)
        self._unpack_prog.setVisible(True)
        self._set_status(f"🔄  جاري فك {os.path.basename(pak)} …")
        self._log_msg(f"🚀  فك الحزمة: {os.path.basename(pak)}", "teal")

        aes    = self._aes_edit.text().strip()
        filt   = self._unpack_filter.text().strip()
        self._unpack_worker = _UnpackWorker(self._tool_path(), pak, out, aes, filt)
        self._unpack_worker.logged.connect(self._log_msg)
        self._unpack_worker.finished.connect(self._on_unpack_done)
        self._unpack_worker.start()

    def _on_unpack_done(self, ok: bool, msg: str):
        self._unpack_btn.setEnabled(True)
        self._unpack_prog.setVisible(False)
        color = "green" if ok else "accent"
        self._set_status(msg.split("\n")[0])
        self._log_msg(msg.replace("\n", "  "), color)

    # ── Pack ──────────────────────────────────────────────────────────────────

    def _run_pack(self):
        if not self._validate_tool():
            return
        src    = self._pack_srcdir.text().strip()
        out    = self._pack_outpak.text().strip()
        prefix = self._pack_mount.text().strip() or "../../../"
        if not src or not os.path.isdir(src):
            self._log_msg("❌  اختر مجلد المصدر أولاً", "accent")
            return
        if not out:
            self._log_msg("❌  حدّد مسار ملف .pak الناتج", "accent")
            return
        if not out.lower().endswith(".pak"):
            out += ".pak"
            self._pack_outpak.setText(out)

        self._pack_btn.setEnabled(False)
        self._pack_prog.setVisible(True)
        self._set_status(f"🔄  جاري إنشاء {os.path.basename(out)} …")
        self._log_msg(f"🚀  إنشاء حزمة من: {os.path.basename(src)}", "teal")

        self._pack_worker = _PackWorker(self._tool_path(), src, out, prefix)
        self._pack_worker.logged.connect(self._log_msg)
        self._pack_worker.finished.connect(self._on_pack_done)
        self._pack_worker.start()

    def _on_pack_done(self, ok: bool, msg: str):
        self._pack_btn.setEnabled(True)
        self._pack_prog.setVisible(False)
        color = "green" if ok else "accent"
        self._set_status(msg.split("\n")[0])
        self._log_msg(msg.replace("\n", "  "), color)
