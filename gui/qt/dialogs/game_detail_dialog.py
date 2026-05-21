"""
gui/qt/dialogs/game_detail_dialog.py  —  نافذة تفاصيل اللعبة (تُفتح من الصفحة الرئيسية)
"""
from __future__ import annotations
import os
import sys

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QScrollArea, QWidget, QProgressBar, QMessageBox,
    QSizePolicy, QFileDialog,
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui  import QCursor, QPixmap, QPainter

from gui.qt.theme import theme


if getattr(sys, 'frozen', False):
    _IMG_DIR = os.path.join(os.path.dirname(sys.executable), "data", "game_images")
else:
    _IMG_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))),
        "data", "game_images"
    )

_ENGINE_COLORS = {
    "ue5":    ("purple", "UE5"),
    "ue4":    ("teal",   "UE4"),
    "unreal": ("teal",   "Unreal"),
    "unity":  ("blue",   "Unity"),
    "other":  ("muted",  "Other"),
}


def _version_gt(a: str, b: str) -> bool:
    """Return True if version string a is greater than b (e.g. '0.3' > '0.2')."""
    def _parts(v):
        return [int(x) for x in str(v).lstrip("v").split(".") if x.isdigit()]
    try:
        return _parts(a) > _parts(b)
    except Exception:
        return False


# ── Workers ───────────────────────────────────────────────────────────────────

class _RegistryWorker(QThread):
    done = Signal(dict, bool)

    def run(self):
        try:
            from games.translation_registry import TranslationRegistry
            reg = TranslationRegistry()
            if reg.fetch(timeout=10):
                self.done.emit(reg.all_translations(), True)
                return
        except Exception:
            pass
        self.done.emit({}, False)


class _DownloadWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(bool, str)

    def __init__(self, game_id: str, info: dict, ready_dir: str):
        super().__init__()
        self._game_id   = game_id
        self._info      = info
        self._ready_dir = ready_dir
        self._cancel    = False

    def cancel(self):
        self._cancel = True

    def run(self):
        import requests
        os.makedirs(self._ready_dir, exist_ok=True)
        files      = self._info.get("files", [])
        total_size = sum(f.get("size", 0) for f in files)
        done = 0
        for fi in files:
            if self._cancel:
                self.finished.emit(False, "إلغاء")
                return
            url  = fi["url"]
            dest = os.path.join(self._ready_dir, fi["name"])
            try:
                r = requests.get(url, stream=True, timeout=60)
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(65536):
                        if self._cancel:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if total_size:
                            self.progress.emit(done, total_size)
            except Exception as e:
                self.finished.emit(False, str(e))
                return
        self.finished.emit(True, "تم التحميل بنجاح")


class _ForCacheDownloadWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(bool, str)

    def __init__(self, url: str, fc_dir: str):
        super().__init__()
        self._url    = url
        self._fc_dir = fc_dir

    def run(self):
        import requests, zipfile, tempfile
        tmp_path = tempfile.mktemp(suffix=".zip")
        try:
            r = requests.get(self._url, timeout=300, stream=True)
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done  = 0
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        self.progress.emit(done, total)
            os.makedirs(self._fc_dir, exist_ok=True)
            with zipfile.ZipFile(tmp_path, "r") as z:
                z.extractall(self._fc_dir)
            os.remove(tmp_path)
            self.finished.emit(True, "تم التحميل بنجاح")
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            self.finished.emit(False, str(e))


# ── Cover label ───────────────────────────────────────────────────────────────

class _CoverLabel(QLabel):
    def __init__(self, path: str, height: int = 200, parent=None):
        super().__init__(parent)
        self._pm = QPixmap(path)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, event):
        if self._pm.isNull():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        scaled = self._pm.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = (scaled.width()  - w) // 2
        y = (scaled.height() - h) // 2
        painter.drawPixmap(0, 0, scaled, x, y, w, h)


# ── Dialog ────────────────────────────────────────────────────────────────────

class GameDetailDialog(QDialog):
    """نافذة تفاصيل اللعبة الكاملة — تُفتح عند النقر على بطاقة من الصفحة الرئيسية."""

    manage_requested = Signal(str)   # game_id → الانتقال لصفحة الألعاب

    def __init__(self, game_id: str, cfg: dict, cache,
                 game_manager=None, proxy=None, parent=None):
        super().__init__(parent)
        self._game_id         = game_id
        self._cfg             = cfg
        self._cache           = cache
        self._game_manager    = game_manager
        self._proxy           = proxy
        self._registry_info: dict = {}
        self._registry_loaded = False
        self._dl_worker       = None
        self._dl_progress     = None
        self._dl_lbl          = None
        self._fc_worker       = None
        self._fc_progress     = None

        self.setWindowTitle(cfg.get("name", game_id))
        self.setMinimumSize(560, 580)
        self.resize(600, 650)
        self.setModal(True)
        self._build()
        self._fetch_registry()

    # ── Build shell ───────────────────────────────────────────────────────────

    def _build(self):
        c = theme.c
        self.setStyleSheet(f"""
            QDialog  {{ background: {c['bg']}; }}
            QLabel   {{ color: {c['primary']}; background: transparent; border: none; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Cover
        cover_path = self._find_cover()
        if cover_path:
            root.addWidget(_CoverLabel(cover_path, 200))
        else:
            ph = QFrame()
            ph.setFixedHeight(110)
            ph.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            ph.setStyleSheet(
                f"QFrame {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                f" stop:0 {c['surface']}, stop:1 {c['card2']}); border: none; }}"
            )
            icon = QLabel("🎮")
            icon.setAlignment(Qt.AlignCenter)
            icon.setStyleSheet("font-size: 48px; background: transparent; border: none;")
            QVBoxLayout(ph).addWidget(icon)
            root.addWidget(ph)

        # Scroll content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")

        self._scroll_content = QWidget()
        self._scroll_content.setStyleSheet("background: transparent;")
        self._content_lay = QVBoxLayout(self._scroll_content)
        self._content_lay.setContentsMargins(24, 20, 24, 20)
        self._content_lay.setSpacing(16)
        scroll.setWidget(self._scroll_content)
        root.addWidget(scroll, 1)

        self._fill_content()

        # Bottom bar
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-top: 1px solid {c['border']}; }}"
        )
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(20, 12, 20, 12)
        bar_lay.setSpacing(10)

        manage_btn = QPushButton("⚙️  إدارة اللعبة")
        manage_btn.setFixedHeight(36)
        manage_btn.setCursor(QCursor(Qt.PointingHandCursor))
        manage_btn.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; color: {c['secondary']};"
            f" border: 1px solid {c['border']}; border-radius: 8px; padding: 0 16px; }}"
            f"QPushButton:hover {{ background: {c['hover']}; color: {c['primary']}; }}"
        )
        manage_btn.clicked.connect(lambda: (
            self.manage_requested.emit(self._game_id),
            self.accept(),
        ))
        bar_lay.addWidget(manage_btn)
        bar_lay.addStretch()

        close_btn = QPushButton("إغلاق")
        close_btn.setFixedHeight(36)
        close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        close_btn.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; color: {c['muted']};"
            f" border: 1px solid {c['border']}; border-radius: 8px; padding: 0 16px; }}"
            f"QPushButton:hover {{ background: {c['hover']}; color: {c['primary']}; }}"
        )
        close_btn.clicked.connect(self.accept)
        bar_lay.addWidget(close_btn)
        root.addWidget(bar)

    # ── Content ───────────────────────────────────────────────────────────────

    def _fill_content(self):
        """بناء/إعادة بناء المحتوى القابل للتمرير."""
        c   = theme.c
        cfg = self._cfg
        lay = self._content_lay

        # Clear
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Title + status
        hdr = QHBoxLayout()
        name_lbl = QLabel(cfg.get("name", self._game_id))
        name_lbl.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {c['primary']};"
        )
        name_lbl.setWordWrap(True)
        hdr.addWidget(name_lbl, 1)

        enabled = cfg.get("enabled", True)
        st = QLabel("● مفعّل" if enabled else "● معطّل")
        st.setStyleSheet(
            f"color: {c['green'] if enabled else c['muted']}; font-size: 11px;"
        )
        hdr.addWidget(st)
        lay.addLayout(hdr)

        # Info card
        info_card = self._card()
        info_lay  = QVBoxLayout(info_card)
        info_lay.setContentsMargins(16, 14, 16, 14)
        info_lay.setSpacing(8)

        engine_raw = cfg.get("engine", cfg.get("type", "other")).lower()
        eng_key    = ("ue5"    if "ue5"    in engine_raw else
                      "ue4"    if ("ue4" in engine_raw or "unreal" in engine_raw) else
                      "unity"  if "unity"  in engine_raw else "other")
        eng_clr_key, eng_label = _ENGINE_COLORS.get(eng_key, ("muted", engine_raw))
        eng_clr = c.get(eng_clr_key, c["muted"])

        # Engine badge
        badge = QLabel(eng_label)
        badge.setStyleSheet(
            f"color: {eng_clr}; border: 1px solid {eng_clr};"
            " border-radius: 8px; padding: 1px 9px; font-size: 10px; font-weight: bold;"
        )
        b_row = QHBoxLayout()
        b_row.addWidget(badge)
        b_row.addStretch()
        info_lay.addLayout(b_row)

        def _row(key: str, val: str, color: str = None):
            row = QHBoxLayout()
            kl  = QLabel(key)
            kl.setFixedWidth(110)
            kl.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
            vl  = QLabel(val or "—")
            vl.setWordWrap(True)
            vl.setStyleSheet(f"color: {color or c['secondary']}; font-size: 12px;")
            row.addWidget(kl)
            row.addWidget(vl, 1)
            info_lay.addLayout(row)

        path = cfg.get("game_path", "")
        if path:
            _row("المسار:", path if len(path) < 58 else "…" + path[-55:])

        _row("اللغة:",  f"{cfg.get('source_lang','en')} ← {cfg.get('target_lang','ar')}")

        cache_cnt = 0
        if self._cache:
            try:
                cache_cnt = self._cache.count_entries(cfg.get("name", self._game_id))
            except Exception:
                pass
        _row("الكاش:", f"{cache_cnt:,} ترجمة", c["teal"])

        notes = cfg.get("notes", "")
        if notes:
            _row("ملاحظات:", notes)

        lay.addWidget(info_card)

        # Package card
        self._build_pkg_card(lay)

        # BepInEx card
        self._build_bepinex_card(lay)

        lay.addStretch()

    def _build_pkg_card(self, lay):
        c = theme.c
        try:
            from games.translation_package import TranslationPackage
            pkg = TranslationPackage()
        except ImportError:
            return

        has_pkg   = pkg.has_files(self._game_id)
        game_path = self._cfg.get("game_path", "")
        reg_info  = self._registry_info.get(self._game_id)

        # Hide only when: no local pkg AND registry loaded AND no online entry
        if not has_pkg and self._registry_loaded and not reg_info:
            return

        if has_pkg and game_path:
            status = pkg.get_status(self._game_id, game_path)
        elif has_pkg:
            status = None
        else:
            status = "no_local"

        installed_ver    = pkg.get_installed_version(self._game_id)
        online_ver       = reg_info.get("version", "") if reg_info else ""
        # Use "0" as fallback so updates show even when installed_ver was never recorded
        _installed_cmp   = installed_ver if installed_ver else ("0" if status is True else "")
        has_update       = bool(
            status is True
            and online_ver
            and _installed_cmp
            and _version_gt(online_ver, _installed_cmp)
        )

        if has_update:
            status_text, status_color = f"● تحديث متاح ← v{online_ver}", c["yellow"]
        elif status is True:
            status_text, status_color = "● مُثبَّتة",          c["green"]
        elif status is False:
            status_text, status_color = "● غير مُثبَّتة",      c["accent"]
        elif status == "no_local" and reg_info:
            status_text, status_color = "● متاحة للتحميل",     c["blue"]
        elif status == "no_local":
            status_text, status_color = "● جارٍ التحقق…",      c["muted"]
        else:
            status_text, status_color = "● حدد مسار اللعبة أولاً", c["yellow"]

        card = self._card()
        cl   = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(10)

        # Header row
        hdr_row = QHBoxLayout()
        ttl = QLabel("📦  حزمة الترجمة")
        ttl.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {c['primary']};"
        )
        st_lbl = QLabel(status_text)
        st_lbl.setStyleSheet(f"color: {status_color}; font-size: 11px;")
        hdr_row.addWidget(ttl)
        hdr_row.addStretch()
        hdr_row.addWidget(st_lbl)
        cl.addLayout(hdr_row)

        # Progress bar (download)
        self._dl_progress = QProgressBar()
        self._dl_progress.setFixedHeight(6)
        self._dl_progress.setTextVisible(False)
        self._dl_progress.setVisible(False)
        self._dl_progress.setStyleSheet(
            f"QProgressBar {{ background: {c['border']}; border-radius: 3px; border: none; }}"
            f"QProgressBar::chunk {{ background: {c['blue']}; border-radius: 3px; }}"
        )
        cl.addWidget(self._dl_progress)

        self._dl_lbl = QLabel("")
        self._dl_lbl.setVisible(False)
        self._dl_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        cl.addWidget(self._dl_lbl)

        # Action button
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        if status == "no_local" and reg_info:
            size_mb  = reg_info.get("size_mb", 0)
            size_txt = f"  ({size_mb} MB)" if size_mb else ""
            dl_btn = QPushButton(f"⬇️  تحميل الترجمة{size_txt}")
            dl_btn.setFixedHeight(36)
            dl_btn.setCursor(QCursor(Qt.PointingHandCursor))
            dl_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {c['blue']}; color: #fff;
                    border: none; border-radius: 8px;
                    font-weight: bold; padding: 0 18px;
                }}
                QPushButton:hover {{ background: #1565c0; }}
            """)
            dl_btn.clicked.connect(lambda: self._do_download(reg_info))
            btn_row.addWidget(dl_btn)

        elif status == "no_local":
            retry_btn = QPushButton("🔄  تحقق من الترجمات المتاحة")
            retry_btn.setFixedHeight(36)
            retry_btn.setCursor(QCursor(Qt.PointingHandCursor))
            retry_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {c['muted']};
                    border: 1px solid {c['border']}; border-radius: 8px; padding: 0 18px;
                }}
                QPushButton:hover {{ color: {c['primary']}; border-color: {c['primary']}; }}
            """)
            retry_btn.clicked.connect(self._fetch_registry)
            btn_row.addWidget(retry_btn)

        elif status is False:
            inst_btn = QPushButton("✅  تثبيت الترجمة")
            inst_btn.setFixedHeight(36)
            inst_btn.setCursor(QCursor(Qt.PointingHandCursor))
            inst_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {c['green']}; color: #fff;
                    border: none; border-radius: 8px;
                    font-weight: bold; padding: 0 18px;
                }}
                QPushButton:hover {{ background: #2e7d32; }}
            """)
            inst_btn.clicked.connect(self._do_install)
            btn_row.addWidget(inst_btn)

        elif status is True:
            if has_update:
                upd_btn = QPushButton(f"🔄  تحديث إلى v{online_ver}")
                upd_btn.setFixedHeight(36)
                upd_btn.setCursor(QCursor(Qt.PointingHandCursor))
                upd_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {c['yellow']}; color: #000;
                        border: none; border-radius: 8px;
                        font-weight: bold; padding: 0 18px;
                    }}
                    QPushButton:hover {{ background: {c['yellow']}; color: #333;
                        border: 1px solid #333; }}
                """)
                upd_btn.clicked.connect(lambda: self._do_update(reg_info))
                btn_row.addWidget(upd_btn)

            uninst_btn = QPushButton("🗑️  إلغاء التثبيت")
            uninst_btn.setFixedHeight(36)
            uninst_btn.setCursor(QCursor(Qt.PointingHandCursor))
            uninst_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {c['accent']};
                    border: 1px solid {c['accent']}; border-radius: 8px;
                    font-weight: bold; padding: 0 18px;
                }}
                QPushButton:hover {{ background: {c['accent']}; color: #fff; }}
            """)
            uninst_btn.clicked.connect(self._do_uninstall)
            btn_row.addWidget(uninst_btn)

        elif status is None:
            hint = QLabel("حدد مسار اللعبة من «إدارة اللعبة» لتتمكن من التثبيت")
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
            cl.addWidget(hint)

        btn_row.addStretch()
        cl.addLayout(btn_row)

        if has_update:
            shown_inst = installed_ver if installed_ver else "غير معروف"
            ver_lbl = QLabel(f"مُثبَّت: v{shown_inst}  |  متاح: v{online_ver}")
        elif installed_ver:
            ver_lbl = QLabel(f"الإصدار المُثبَّت: v{installed_ver}")
        else:
            ver = online_ver or (reg_info.get("version", "1.0") if reg_info else "1.0")
            ver_lbl = QLabel(f"الإصدار: v{ver}")
        ver_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        cl.addWidget(ver_lbl)

        lay.addWidget(card)

        # for_cache card (if registry provides a URL)
        fc_url     = reg_info.get("for_cache_url", "")     if reg_info else ""
        fc_size_mb = reg_info.get("for_cache_size_mb", 0)  if reg_info else 0
        if fc_url:
            self._build_for_cache_card(lay, fc_url, fc_size_mb)

    def _build_bepinex_card(self, lay):
        """بطاقة BepInEx+XUnity مع معالجات inline."""
        try:
            from games.bepinex_mod import BepInExMod
        except ImportError:
            return
        mod = BepInExMod()
        cfg = self._cfg
        if not mod.is_supported(cfg):
            return

        c         = theme.c
        game_path = cfg.get("game_path", "")
        bm        = cfg.get("bepinex_mod", {})
        dll_name  = bm.get("dll_name", "")
        is_xunity_mode = not dll_name

        resolved_src    = mod._resolve_bepinex_source(cfg)
        has_bepinex_src = bool(resolved_src)
        src_label       = os.path.basename(resolved_src) if resolved_src else ""
        installed       = mod.get_install_status(cfg, game_path)
        bepinex_in_game = mod.is_bepinex_installed(game_path) if game_path else False

        xunity_ok     = mod.is_xunity_installed(game_path) if game_path else False
        font_fixer_ok = mod.is_font_fixer_installed(game_path) if game_path else False
        dll_ok        = mod.dll_src_exists(cfg) if dll_name else False
        json_ok       = mod.get_json_status(cfg, game_path) if dll_name else None

        if installed is True:
            status_text, status_color = "● مُثبَّت", c["green"]
        elif installed is False:
            status_text, status_color = "● غير مُثبَّت", c["yellow"]
        else:
            status_text, status_color = (
                ("● غير مُثبَّت", c["yellow"]) if game_path
                else ("● حدد مسار اللعبة", c["muted"])
            )

        card = self._card()
        cl   = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(8)

        hdr_row = QHBoxLayout()
        title = "🔌  BepInEx + XUnity AutoTranslator" if is_xunity_mode else "🔌  BepInEx Runtime Mod"
        ttl = QLabel(title)
        ttl.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {c['primary']};"
        )
        st_lbl = QLabel(status_text)
        st_lbl.setStyleSheet(f"color: {status_color}; font-size: 11px;")
        hdr_row.addWidget(ttl)
        hdr_row.addStretch()
        hdr_row.addWidget(st_lbl)
        cl.addLayout(hdr_row)

        def _status_line(icon, text, color):
            lbl = QLabel(f"{icon} {text}")
            lbl.setStyleSheet(f"color: {color}; font-size: 10px;")
            cl.addWidget(lbl)

        if has_bepinex_src:
            _status_line("✓", f"BepInEx — جاهز ({src_label})", c["green"])
        else:
            _status_line("✗", "BepInEx — غير موجود في mods/_bepinex_base/", c["accent"])

        if is_xunity_mode:
            if game_path:
                _status_line(
                    "✓" if xunity_ok else ("○" if not bepinex_in_game else "✗"),
                    "XUnity.AutoTranslator" + (" — مثبَّت" if xunity_ok else " — لم يُثبَّت بعد"),
                    c["green"] if xunity_ok else (c["muted"] if not bepinex_in_game else c["yellow"]),
                )
                _status_line(
                    "✓" if font_fixer_ok else ("○" if not bepinex_in_game else "✗"),
                    "ArabicFontFixer — " + ("خط عربي مثبَّت" if font_fixer_ok else "لم يُثبَّت بعد"),
                    c["green"] if font_fixer_ok else (c["muted"] if not bepinex_in_game else c["yellow"]),
                )
        else:
            _status_line(
                "✓" if dll_ok else "✗",
                dll_name + (" — موجود في mods/" if dll_ok else " — مفقود من mods/"),
                c["green"] if dll_ok else c["accent"],
            )
            if json_ok is not None:
                _status_line(
                    "✓" if json_ok else "✗",
                    "ملف الترجمات" + (" — موجود في اللعبة" if json_ok else " — غير موجود"),
                    c["green"] if json_ok else c["muted"],
                )

        def _mini_btn(label, color_key, slot):
            btn = QPushButton(label)
            btn.setFixedHeight(34)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            clr = c.get(color_key, c["accent"])
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {clr};
                    border: 1px solid {clr}; border-radius: 7px;
                    font-weight: bold; font-size: 11px; padding: 0 12px;
                }}
                QPushButton:hover {{ background: {clr}; color: #fff; }}
            """)
            btn.clicked.connect(slot)
            return btn

        if not game_path:
            hint = QLabel("حدد مسار اللعبة من «إدارة اللعبة» لتتمكن من التثبيت")
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
            cl.addWidget(hint)
        else:
            row1 = QHBoxLayout(); row1.setSpacing(6)
            if installed is False or installed is None:
                can_install = has_bepinex_src
                lbl = "✅  تثبيت BepInEx + XUnity" if is_xunity_mode else "✅  تثبيت المود الكامل"
                inst_btn = QPushButton(lbl)
                inst_btn.setFixedHeight(36)
                inst_btn.setEnabled(can_install)
                inst_btn.setCursor(QCursor(Qt.PointingHandCursor))
                inst_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {c['green'] if can_install else c['border']};
                        color: {'#fff' if can_install else c['muted']};
                        border: none; border-radius: 8px;
                        font-weight: bold; font-size: 12px; padding: 0 18px;
                    }}
                    QPushButton:hover {{ background: {'#2e7d32' if can_install else c['border']}; }}
                """)
                inst_btn.clicked.connect(self._do_bepinex_install)
                row1.addWidget(inst_btn)

            elif installed is True:
                if is_xunity_mode:
                    row1.addWidget(_mini_btn("🔄  تحديث الترجمات", "teal", self._do_bepinex_update))
                    row1.addWidget(_mini_btn("🔄  تحديث plugins",  "blue", self._do_bepinex_install))
                    row1.addWidget(_mini_btn("🗑️  إلغاء التثبيت", "accent", self._do_bepinex_uninstall))
                else:
                    row1.addWidget(_mini_btn("📥  استيراد الترجمات", "blue",  self._do_bepinex_import))
                    row1.addWidget(_mini_btn("📁  استيراد من مجلد",  "muted", self._do_bepinex_import_from))
                    row1.addWidget(_mini_btn("🔄  تحديث الترجمات",   "teal",  self._do_bepinex_update))
                    row1.addWidget(_mini_btn("🗑️  إلغاء التثبيت",   "accent", self._do_bepinex_uninstall))

            row1.addStretch()
            cl.addLayout(row1)

            # خادم الترجمة الفورية
            if installed is True:
                proxy  = self._proxy
                p_run  = proxy is not None and proxy.is_running
                p_this = p_run and proxy.game_name == self._game_id

                row_srv = QHBoxLayout(); row_srv.setSpacing(8)
                if p_this:
                    srv_badge = QLabel("🟢  خادم الترجمة الفورية يعمل")
                    srv_badge.setStyleSheet(
                        f"color: {c['green']}; font-size: 11px; font-weight: bold;"
                    )
                    row_srv.addWidget(srv_badge)
                    stop_btn = QPushButton("⏹  إيقاف الخادم")
                    stop_btn.setFixedHeight(32)
                    stop_btn.setCursor(QCursor(Qt.PointingHandCursor))
                    stop_btn.setStyleSheet(f"""
                        QPushButton {{
                            background: transparent; color: {c['accent']};
                            border: 1px solid {c['accent']}; border-radius: 7px;
                            font-weight: bold; font-size: 11px; padding: 0 12px;
                        }}
                        QPushButton:hover {{ background: {c['accent']}; color: #fff; }}
                    """)
                    stop_btn.clicked.connect(self._do_proxy_toggle)
                    row_srv.addWidget(stop_btn)
                else:
                    if p_run:
                        row_srv.addWidget(QLabel(
                            f"⚠️  الخادم يعمل للعبة «{proxy.game_name}»"
                        ))
                    lbl_s = "▶  تشغيل الخادم — شغّله قبل فتح اللعبة" if is_xunity_mode else "▶  تشغيل خادم الترجمة الفورية"
                    start_btn = QPushButton(lbl_s)
                    start_btn.setFixedHeight(32)
                    start_btn.setCursor(QCursor(Qt.PointingHandCursor))
                    start_btn.setStyleSheet(f"""
                        QPushButton {{
                            background: transparent; color: {c['green']};
                            border: 1px solid {c['green']}; border-radius: 7px;
                            font-weight: bold; font-size: 11px; padding: 0 12px;
                        }}
                        QPushButton:hover {{ background: {c['green']}; color: #fff; }}
                    """)
                    start_btn.clicked.connect(self._do_proxy_toggle)
                    row_srv.addWidget(start_btn)

                # زر تفعيل/إلغاء BiDi
                bidi_on = self._cfg.get("apply_bidi", True)
                bidi_btn = QPushButton("BiDi: مفعّل ✓" if bidi_on else "BiDi: معطّل ✗")
                bidi_btn.setFixedHeight(32)
                bidi_btn.setCursor(QCursor(Qt.PointingHandCursor))
                bidi_btn.setToolTip(
                    "وضع BiDi: يعكس ترتيب الأحرف للألعاب بدون دعم RTL مدمج.\n"
                    "عطّله للألعاب التي تحتوي على مود BepInEx/RTL."
                )
                _bc = c["blue"] if bidi_on else c["muted"]
                bidi_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent; color: {_bc};
                        border: 1px solid {_bc}; border-radius: 7px;
                        font-size: 11px; padding: 0 10px;
                    }}
                    QPushButton:hover {{ background: {_bc}; color: #fff; }}
                """)
                bidi_btn.clicked.connect(self._do_toggle_bidi)
                row_srv.addWidget(bidi_btn)
                row_srv.addStretch()
                cl.addLayout(row_srv)

            # أزرار الجمع عند غياب ملفات المصدر
            row2 = QHBoxLayout(); row2.setSpacing(6)
            has_collect = False
            if not has_bepinex_src and bepinex_in_game:
                row2.addWidget(_mini_btn("📦  جمع BepInEx من اللعبة", "muted", self._do_bepinex_collect))
                has_collect = True
            if not has_bepinex_src:
                row2.addWidget(_mini_btn("📁  جمع من مجلد آخر", "muted", self._do_bepinex_collect_from))
                has_collect = True
            if dll_name and not dll_ok and installed is True:
                row2.addWidget(_mini_btn("📋  نسخ DLL للمشروع", "muted", self._do_bepinex_copy_dll))
                has_collect = True
            if has_collect:
                row2.addStretch()
                cl.addLayout(row2)

        lay.addWidget(card)

    # ── BepInEx handlers ──────────────────────────────────────────────────────

    def _bepinex_cfg(self):
        if self._game_manager:
            try:
                return self._game_manager.get_game(self._game_id) or self._cfg
            except Exception:
                pass
        return self._cfg

    def _do_bepinex_install(self):
        from games.bepinex_mod import BepInExMod
        cfg = self._bepinex_cfg()
        ok, log = BepInExMod().install(cfg, cfg.get("game_path", ""), self._cache)
        msg = "\n".join(log)
        if ok:
            QMessageBox.information(self, "✅  تثبيت ناجح", f"تم تثبيت المود:\n\n{msg}")
        else:
            QMessageBox.critical(self, "❌  فشل التثبيت", msg)
        self._fill_content()

    def _do_bepinex_uninstall(self):
        reply = QMessageBox.question(
            self, "تأكيد الإلغاء",
            "هل تريد إزالة مود BepInEx وملف الترجمات من مجلد اللعبة؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        from games.bepinex_mod import BepInExMod
        cfg = self._bepinex_cfg()
        ok, log = BepInExMod().uninstall(cfg, cfg.get("game_path", ""))
        msg = "\n".join(log)
        if ok:
            QMessageBox.information(self, "تم الإلغاء", f"تم إلغاء التثبيت:\n\n{msg}")
        else:
            QMessageBox.warning(self, "خطأ في الإلغاء", msg)
        self._fill_content()

    def _do_bepinex_update(self):
        from games.bepinex_mod import BepInExMod
        from PySide6.QtWidgets import QInputDialog

        cfg = self._bepinex_cfg()
        game_name = cfg.get("name", "") or self._game_id

        # اعرض حوار اختيار النموذج — يُتيح للمستخدم اللعب بترجمات نموذج واحد فقط
        model_filter = ""
        try:
            models = self._cache.get_models_for_game(game_name) if self._cache else []
        except Exception:
            models = []

        if models:
            # اجمع الإحصاءات (عدد الترجمات لكل نموذج)
            total_all = self._cache.count_entries(game_name)
            items = [f"🌐 كل النماذج ({total_all:,} ترجمة)"]
            item_to_model = {items[0]: ""}
            for m in models:
                try:
                    cnt = self._cache.count_by_model(game_name, m)
                except Exception:
                    cnt = 0
                label = f"🤖 {m} ({cnt:,} ترجمة)"
                items.append(label)
                item_to_model[label] = m

            selected, ok_choice = QInputDialog.getItem(
                self,
                "اختر نموذج الترجمة",
                "أي نموذج تريد تصدير ترجماته لـ translations.txt؟\n"
                "يُفيد لاختبار اللعبة بترجمات نموذج واحد فقط.",
                items, 0, False,  # 0=default index, False=non-editable
            )
            if not ok_choice:
                return  # المستخدم ألغى
            model_filter = item_to_model.get(selected, "")

        ok, log = BepInExMod().update_translations(
            cfg, cfg.get("game_path", ""), self._cache,
            model_filter=model_filter,
        )
        msg = "\n".join(log)
        if ok:
            QMessageBox.information(self, "✅  تم التحديث", msg)
        else:
            QMessageBox.warning(self, "خطأ في التحديث", msg)
        self._fill_content()

    def _do_bepinex_import(self):
        from games.bepinex_mod import BepInExMod
        cfg = self._bepinex_cfg()
        ok, msg, _ = BepInExMod().import_translations_from_game(cfg, cfg.get("game_path", ""), self._cache)
        if ok:
            QMessageBox.information(self, "✅  استيراد ناجح", msg)
        else:
            QMessageBox.warning(self, "خطأ في الاستيراد", msg)
        self._fill_content()

    def _do_bepinex_import_from(self):
        src = QFileDialog.getExistingDirectory(
            self, "اختر مجلد اللعبة التي تحتوي على ترجمات جاهزة",
            "C:/Program Files (x86)/Steam/steamapps/common"
        )
        if not src:
            return
        from games.bepinex_mod import BepInExMod
        cfg = self._bepinex_cfg()
        game_path = cfg.get("game_path", "")
        ok, msg, _ = BepInExMod().import_translations_from_game(cfg, game_path, self._cache, source_path=src)
        if ok:
            reply = QMessageBox.question(
                self, "✅  استيراد ناجح",
                f"{msg}\n\nهل تريد تحديث ملف الترجمات في اللعبة الآن؟",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                BepInExMod().update_translations(cfg, game_path, self._cache)
        else:
            QMessageBox.warning(self, "خطأ في الاستيراد", msg)
        self._fill_content()

    def _do_bepinex_copy_dll(self):
        from games.bepinex_mod import BepInExMod
        cfg = self._bepinex_cfg()
        ok, msg = BepInExMod().copy_dll_from_game(cfg, cfg.get("game_path", ""))
        if ok:
            QMessageBox.information(self, "✅  تم النسخ", msg)
        else:
            QMessageBox.warning(self, "خطأ في النسخ", msg)
        self._fill_content()

    def _do_bepinex_collect(self):
        from games.bepinex_mod import BepInExMod
        cfg = self._bepinex_cfg()
        ok, msg = BepInExMod().collect_bepinex_from_game(cfg, cfg.get("game_path", ""))
        if ok:
            QMessageBox.information(self, "✅  تم الجمع", msg)
        else:
            QMessageBox.warning(self, "خطأ في الجمع", msg)
        self._fill_content()

    def _do_bepinex_collect_from(self):
        src = QFileDialog.getExistingDirectory(
            self, "اختر مجلد اللعبة التي تحتوي على BepInEx",
            "C:/Program Files (x86)/Steam/steamapps/common"
        )
        if not src:
            return
        from games.bepinex_mod import BepInExMod
        cfg = self._bepinex_cfg()
        ok, msg = BepInExMod().collect_bepinex_from_game(cfg, cfg.get("game_path", ""), source_path=src)
        if ok:
            QMessageBox.information(self, "✅  تم الجمع", msg)
        else:
            QMessageBox.warning(self, "خطأ في الجمع", msg)
        self._fill_content()

    def _do_proxy_toggle(self):
        proxy = self._proxy
        if proxy is None:
            QMessageBox.warning(self, "خطأ", "خادم الترجمة غير متاح — أعد تشغيل التطبيق")
            return
        game_name = self._cfg.get("name", self._game_id)
        if proxy.is_running and proxy.game_name == self._game_id:
            proxy.stop()
            # لا نُصدّر translations.txt تلقائياً — يتحكّم المستخدم
            # عبر زر "🔄 تحديث الترجمات" فقط
        else:
            ok, msg = proxy.start(self._game_id, cfg=self._cfg)
            if not ok:
                QMessageBox.warning(self, "خطأ في الخادم", msg)
        self._fill_content()

    def _do_toggle_bidi(self):
        """تفعيل/إلغاء وضع BiDi للعبة وحفظه في ملف الإعدادات فوراً."""
        current = self._cfg.get("apply_bidi", True)
        new_val = not current
        self._cfg["apply_bidi"] = new_val
        if self._game_manager:
            self._game_manager.update_game(self._game_id, {"apply_bidi": new_val})
        # تحديث البروكسي فوراً إن كان يعمل لهذه اللعبة
        if self._proxy and self._proxy.is_running and self._proxy.game_name == self._game_id:
            self._proxy._apply_bidi = new_val
        self._fill_content()

    def _build_for_cache_card(self, lay, url: str, size_mb: int):
        c = theme.c
        from games.translation_package import TranslationPackage
        fc_local = TranslationPackage().get_legacy_in_cache(self._game_id)

        card = self._card()
        cl   = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(10)

        hdr_row = QHBoxLayout()
        ttl = QLabel("📁  ملفات الكاش المرجعي")
        ttl.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {c['primary']};"
        )
        st_lbl = QLabel("● موجود" if fc_local else "● غير محمّل")
        st_lbl.setStyleSheet(
            f"color: {c['green'] if fc_local else c['muted']}; font-size: 11px;"
        )
        hdr_row.addWidget(ttl)
        hdr_row.addStretch()
        hdr_row.addWidget(st_lbl)
        cl.addLayout(hdr_row)

        self._fc_progress = QProgressBar()
        self._fc_progress.setFixedHeight(6)
        self._fc_progress.setTextVisible(False)
        self._fc_progress.setVisible(False)
        self._fc_progress.setStyleSheet(
            f"QProgressBar {{ background: {c['border']}; border-radius: 3px; border: none; }}"
            f"QProgressBar::chunk {{ background: {c['teal']}; border-radius: 3px; }}"
        )
        cl.addWidget(self._fc_progress)

        if not fc_local:
            size_txt = f"  ({size_mb} MB)" if size_mb else ""
            fc_btn = QPushButton(f"⬇️  تحميل ملفات الكاش{size_txt}")
            fc_btn.setFixedHeight(34)
            fc_btn.setCursor(QCursor(Qt.PointingHandCursor))
            fc_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(0,0,0,26); color: {c['teal']};
                    border: 1px solid {c['teal']}; border-radius: 8px;
                    font-weight: bold; padding: 0 16px;
                }}
                QPushButton:hover {{ background: {c['teal']}; color: #fff; }}
            """)
            fc_btn.clicked.connect(lambda: self._do_download_for_cache(url, size_mb))
            btn_r = QHBoxLayout()
            btn_r.addWidget(fc_btn)
            btn_r.addStretch()
            cl.addLayout(btn_r)

        hint = QLabel("ملفات uasset المرجعية لمزامنة الكاش — اختياري")
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        cl.addWidget(hint)

        lay.addWidget(card)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _card(self) -> QFrame:
        c    = theme.c
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']};"
            " border-radius: 10px; }"
        )
        return card

    def _find_cover(self) -> str:
        for stem in [self._cfg.get("name", self._game_id), self._game_id]:
            for ext in (".png", ".jpg", ".jpeg"):
                p = os.path.join(_IMG_DIR, stem + ext)
                if os.path.isfile(p):
                    return p
        return ""

    # ── Registry ──────────────────────────────────────────────────────────────

    def _fetch_registry(self):
        self._reg_worker = _RegistryWorker()
        self._reg_worker.done.connect(self._on_registry_done)
        self._reg_worker.start()

    def _on_registry_done(self, data: dict, success: bool):
        self._registry_info   = data
        self._registry_loaded = True
        self._fill_content()

    # ── Install / Uninstall / Download ────────────────────────────────────────

    def _do_install(self):
        from games.translation_package import TranslationPackage
        pkg = TranslationPackage()
        ok, log = pkg.install(self._game_id, self._cfg.get("game_path", ""))
        msg = "\n".join(log)
        if ok:
            reg_info = self._registry_info.get(self._game_id)
            if reg_info and reg_info.get("version"):
                pkg.set_installed_version(self._game_id, reg_info["version"])
            QMessageBox.information(self, "✅  تثبيت ناجح", f"تم تثبيت الترجمة:\n\n{msg}")
        else:
            QMessageBox.warning(self, "فشل التثبيت", f"حدث خطأ:\n\n{msg}")
        self._fill_content()

    def _do_uninstall(self):
        reply = QMessageBox.question(
            self, "تأكيد الإلغاء",
            "هل تريد إلغاء تثبيت ملفات الترجمة من مجلد اللعبة؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        from games.translation_package import TranslationPackage
        ok, log = TranslationPackage().uninstall(self._game_id, self._cfg.get("game_path", ""))
        msg = "\n".join(log)
        if ok:
            QMessageBox.information(self, "تم الإلغاء", f"تم إلغاء التثبيت:\n\n{msg}")
        else:
            QMessageBox.warning(self, "فشل الإلغاء", f"حدث خطأ:\n\n{msg}")
        self._fill_content()

    def _do_download(self, reg_info: dict):
        from games.translation_package import TranslationPackage
        ready_dir = TranslationPackage().get_ready_dir(self._game_id)
        self._pending_reg_info = reg_info   # keep for _on_dl_done
        self._dl_worker = _DownloadWorker(self._game_id, reg_info, ready_dir)
        if self._dl_progress:
            total = int(reg_info.get("size_mb", 0) * 1_048_576) or 1
            self._dl_progress.setMaximum(total)
            self._dl_progress.setVisible(True)
        if self._dl_lbl:
            self._dl_lbl.setText("جاري التحميل…")
            self._dl_lbl.setVisible(True)
        self._dl_worker.progress.connect(
            lambda d, t: (
                self._dl_progress.setValue(d) if self._dl_progress else None,
                self._dl_lbl.setText(f"{d // 1024:,} KB / {t // 1024:,} KB") if self._dl_lbl else None,
            )
        )
        self._dl_worker.finished.connect(self._on_dl_done)
        self._dl_worker.start()

    def _on_dl_done(self, ok: bool, msg: str):
        if self._dl_progress:
            self._dl_progress.setVisible(False)
        if self._dl_lbl:
            self._dl_lbl.setVisible(False)
        if ok:
            # Register downloaded files in package.json so install button appears
            try:
                from games.translation_package import TranslationPackage
                _pkg      = TranslationPackage()
                ready_dir = _pkg.get_ready_dir(self._game_id)
                reg       = getattr(self, "_pending_reg_info", {})
                for fi in reg.get("files", []):
                    if os.path.isfile(os.path.join(ready_dir, fi["name"])):
                        _pkg.register_file(
                            self._game_id,
                            fi["name"],
                            fi.get("game_target", fi["name"]),
                        )
                version = reg.get("version", "")
                if version:
                    _pkg.set_installed_version(self._game_id, version)
            except Exception:
                pass

            if getattr(self, "_auto_install", False):
                self._auto_install = False
                game_path = self._cfg.get("game_path", "")
                if game_path:
                    from games.translation_package import TranslationPackage
                    ok2, log2 = TranslationPackage().install(self._game_id, game_path)
                    if ok2:
                        QMessageBox.information(self, "✅  تم التحديث",
                                                "تم تحديث الترجمة وتثبيتها بنجاح!")
                    else:
                        QMessageBox.warning(self, "خطأ في التثبيت", "\n".join(log2))
                else:
                    QMessageBox.information(self, "✅  تم التحميل",
                                            "تم تحميل الترجمة. حدد مسار اللعبة للتثبيت.")
            else:
                QMessageBox.information(self, "✅  تم التحميل", msg)
        else:
            QMessageBox.warning(self, "فشل التحميل", msg)
        self._fill_content()

    def _do_update(self, reg_info: dict):
        reply = QMessageBox.question(
            self, "تأكيد التحديث",
            f"هل تريد تحديث الترجمة إلى الإصدار v{reg_info.get('version', '')}؟\n"
            "سيتم تحميل الملفات الجديدة وتثبيتها تلقائياً.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        self._auto_install = True
        self._do_download(reg_info)

    def _do_download_for_cache(self, url: str, size_mb: int = 0):
        from games.translation_package import TranslationPackage
        fc_dir = TranslationPackage().get_for_cache_dir(self._game_id)
        if self._fc_progress:
            total = size_mb * 1_048_576 or 1
            self._fc_progress.setMaximum(total)
            self._fc_progress.setVisible(True)
        self._fc_worker = _ForCacheDownloadWorker(url, fc_dir)
        self._fc_worker.progress.connect(
            lambda d, t: self._fc_progress.setValue(d) if self._fc_progress else None
        )
        self._fc_worker.finished.connect(self._on_fc_dl_done)
        self._fc_worker.start()

    def _on_fc_dl_done(self, ok: bool, msg: str):
        if self._fc_progress:
            self._fc_progress.setVisible(False)
        if ok:
            QMessageBox.information(self, "✅  تم التحميل", "تم تحميل ملفات الكاش المرجعي بنجاح!")
        else:
            QMessageBox.warning(self, "فشل التحميل", msg)
        self._fill_content()
