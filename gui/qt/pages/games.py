"""
gui/qt/pages/games.py  —  صفحة الألعاب (المرحلة 5)
"""

from __future__ import annotations
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QMessageBox, QSpacerItem, QProgressBar,
    QSplitter, QPlainTextEdit, QCheckBox, QSpinBox, QComboBox, QDialog,
    QLineEdit,
)
from PySide6.QtCore  import Qt, Signal, QThread, QTimer
from PySide6.QtGui   import QCursor, QFont

from gui.qt.theme              import theme
from gui.qt.widgets.page_header import make_topbar


# ── Registry fetch worker ─────────────────────────────────────────────────────

class RegistryFetchWorker(QThread):
    done = Signal(dict, bool, str)   # translations, success, error_msg

    def run(self):
        try:
            from games.translation_registry import TranslationRegistry
            reg = TranslationRegistry()
            if reg.fetch(timeout=10):
                self.done.emit(reg.all_translations(), True, "")
                return
            err = getattr(reg, '_last_error', 'fetch returned False')
            self.done.emit({}, False, err)
        except Exception as e:
            self.done.emit({}, False, f"import error: {e}")


# ── Download worker ───────────────────────────────────────────────────────────

class DownloadWorker(QThread):
    progress = Signal(int, int)   # bytes_done, bytes_total
    file_done = Signal(str)       # filename
    finished  = Signal(bool, str) # success, message

    def __init__(self, game_id: str, translation_info: dict, ready_dir: str):
        super().__init__()
        self._game_id   = game_id
        self._info      = translation_info
        self._ready_dir = ready_dir
        self._cancel    = False

    def cancel(self):
        self._cancel = True

    def run(self):
        import requests, shutil
        from games.translation_package import TranslationPackage
        from games.security import requests_verify, verify_sha256

        os.makedirs(self._ready_dir, exist_ok=True)
        files = self._info.get("files", [])
        total_size = sum(f.get("size", 0) for f in files)
        done = 0
        verify = requests_verify()   # تحقّق SSL موثَّق (certifi)

        for fi in files:
            if self._cancel:
                self.finished.emit(False, "إلغاء")
                return
            name = fi["name"]
            url  = fi["url"]
            dest = os.path.join(self._ready_dir, name)
            try:
                r = requests.get(url, stream=True, timeout=60, verify=verify)
                r.raise_for_status()
                chunk_size = 65536
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=chunk_size):
                        if self._cancel:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        # estimate total from Content-Length if size=0
                        if total_size == 0:
                            cl = r.headers.get("Content-Length")
                            if cl:
                                total_size = int(cl) * len(files)
                        self.progress.emit(done, max(total_size, 1))
                # تحقّق checksum (إن وُفِّر في المنفست) — يمنع الملفات التالفة/المُتلاعَبة
                if not verify_sha256(dest, fi.get("sha256")):
                    try:
                        os.remove(dest)
                    except Exception:
                        pass
                    self.finished.emit(False, f"فشل التحقّق الأمني لـ {name} (sha256 لا يطابق)")
                    return
                self.file_done.emit(name)
            except Exception as e:
                self.finished.emit(False, f"فشل تحميل {name}: {e}")
                return

        if self._cancel:
            self.finished.emit(False, "إلغاء")
            return

        # Register files in package.json
        pkg = TranslationPackage()
        cfg = pkg.get_config(self._game_id)
        cfg["files"] = [
            {
                "name":        fi["name"],
                "game_target": fi.get("game_target", fi["name"]),
                "has_orig":    False,
            }
            for fi in files
        ]
        pkg._save_config(self._game_id, cfg)
        self.finished.emit(True, f"تم تحميل {len(files)} ملفات بنجاح")


class ForCacheWorker(QThread):
    """يحمّل أرشيف for_cache (مصدر البناء) ويفكّه في mods/<game>/for_cache/."""
    progress = Signal(int, int)        # done_bytes, total_bytes
    finished = Signal(bool, str)       # success, message

    def __init__(self, game_id: str, url: str, fc_dir: str, sha256: str = ""):
        super().__init__()
        self._game_id = game_id
        self._url     = url
        self._fc_dir  = fc_dir
        self._sha256  = sha256 or ""

    def run(self):
        import requests, zipfile, tempfile, os as _os
        from games.security import requests_verify, verify_sha256
        tmp = tempfile.mktemp(suffix=".zip")
        try:
            r = requests.get(self._url, stream=True, timeout=300, verify=requests_verify())
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        self.progress.emit(done, total)
            if not verify_sha256(tmp, self._sha256):
                _os.remove(tmp)
                self.finished.emit(False, "فشل التحقّق الأمني (sha256) لمصدر البناء")
                return
            _os.makedirs(self._fc_dir, exist_ok=True)
            with zipfile.ZipFile(tmp, "r") as z:
                z.extractall(self._fc_dir)
            _os.remove(tmp)
            self.finished.emit(True, "تم تحميل مصدر البناء (for_cache) بنجاح")
        except Exception as e:
            if _os.path.exists(tmp):
                try:
                    _os.remove(tmp)
                except Exception:
                    pass
            self.finished.emit(False, f"فشل تحميل مصدر البناء: {e}")


# ── Engine colors (same as home page) ────────────────────────────────────────

_ENGINE_COLOR = {
    "unity":  "purple",
    "unreal": "blue",
    "ue4":    "blue",
    "ue5":    "blue",
    "other":  "muted",
    "auto":   "muted",
}

_ENGINE_LABEL = {
    "unity":  "Unity",
    "unreal": "Unreal",
    "ue4":    "UE4",
    "ue5":    "UE5",
    "other":  "أخرى",
    "auto":   "غير محدد",
}


# ── Locres translation worker ─────────────────────────────────────────────────

class LocresWorker(QThread):
    progress = Signal(int, int, str)   # done, total, filename
    finished = Signal(bool, int, int)  # success, replaced, total

    def __init__(self, locres_folder: str, engine, cache, game_id: str):
        super().__init__()
        self._folder  = locres_folder
        self._engine  = engine
        self._cache   = cache
        self._game_id = game_id

    def run(self):
        try:
            from games.locres_patcher import LocresPatcher
            files = LocresPatcher.find_locres_files(self._folder)
            total_replaced = 0
            total_count    = 0
            for fi, path in enumerate(files):
                entries = LocresPatcher.read(path)
                if not entries:
                    continue
                unique_texts = list(dict.fromkeys(
                    e.value.strip() for e in entries if e.value.strip()
                ))
                translations: dict[str, str] = {}
                if self._cache and self._game_id:
                    for txt in unique_texts:
                        ar = self._cache.get(self._game_id, txt)
                        if ar:
                            translations[txt] = ar
                missing = [t for t in unique_texts if t not in translations]
                if missing and self._engine:
                    for i, txt in enumerate(missing):
                        self.progress.emit(i, len(missing),
                                           os.path.basename(path))
                        try:
                            ar = self._engine.translate(txt)
                            if ar and ar != txt:
                                translations[txt] = ar
                                if self._cache and self._game_id:
                                    self._cache.put(self._game_id, txt, ar)
                        except Exception:
                            pass
                replaced, count = LocresPatcher.patch(path, path, translations)
                total_replaced += replaced
                total_count    += count
            self.finished.emit(True, total_replaced, total_count)
        except Exception as e:
            print(f"[LocresWorker] {e}")
            self.finished.emit(False, 0, 0)


# ── Manor Lords mod build worker ──────────────────────────────────────────────

class ManorLordsBuildWorker(QThread):
    """يبني مود Manor Lords (كاش → uassets → pak) ويثبّته/يحدّثه في خيط منفصل."""
    progress = Signal(int, int, str)        # done, total, table_name
    finished = Signal(bool, str)            # success, log_text

    def __init__(self, cfg: dict, game_path: str, cache, action: str = "install"):
        super().__init__()
        self._cfg = cfg
        self._game_path = game_path
        self._cache = cache
        self._action = action   # install | update

    def run(self):
        try:
            from games.manorlords_mod import ManorLordsMod
            mod = ManorLordsMod()
            log: list = []
            cb = lambda i, n, name: self.progress.emit(i, n, name)
            if self._action == "uninstall":
                ok, log = mod.uninstall(self._cfg, self._game_path)
            else:
                ok, log = mod.install(self._cfg, self._game_path, self._cache,
                                      log=log, progress_cb=cb)
            self.finished.emit(ok, "\n".join(log))
        except Exception as e:
            import traceback
            self.finished.emit(False, f"خطأ: {e}\n{traceback.format_exc()}")


class IoStoreBuildWorker(QThread):
    """يبني/يثبّت/يحدّث/يلغي مود IoStore (كاش → uassets → retoc to-zen → ready → اللعبة)."""
    progress = Signal(int, int, str)        # done, total, file_name
    finished = Signal(bool, str)            # success, log_text

    def __init__(self, game_id: str, cfg: dict, game_path: str, cache,
                 action: str = "install", model_filter: str = ""):
        super().__init__()
        self._game_id = game_id
        self._cfg = cfg
        self._game_path = game_path
        self._cache = cache
        self._action = action   # install | update | uninstall
        self._model_filter = model_filter

    def run(self):
        try:
            from games.iostore_mod import IoStoreMod
            mod = IoStoreMod()
            cb = lambda i, n, name: self.progress.emit(i, n, name)
            if self._action == "uninstall":
                ok, log = mod.uninstall(self._game_id, self._game_path)
            elif self._action == "update":
                ok, log = mod.update_translations(
                    self._game_id, self._cfg, self._game_path, self._cache,
                    progress_cb=cb, model_filter=self._model_filter)
            else:
                ok, log = mod.install(
                    self._game_id, self._cfg, self._game_path, self._cache,
                    progress_cb=cb, model_filter=self._model_filter)
            self.finished.emit(ok, "\n".join(log))
        except Exception as e:
            import traceback
            self.finished.emit(False, f"خطأ: {e}\n{traceback.format_exc()}")


# ── Compact list card ─────────────────────────────────────────────────────────

class GameListItem(QFrame):
    """بطاقة مدمجة في قائمة الألعاب (يسار)."""

    clicked = Signal(str)   # game_id

    def __init__(self, game_id: str, cfg: dict, parent=None):
        super().__init__(parent)
        self._id  = game_id
        self._cfg = cfg
        self._active = False
        self._build()
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def _build(self):
        c   = theme.c
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)

        # Enabled dot
        enabled = self._cfg.get("enabled", True)
        dot = QLabel("●")
        dot.setStyleSheet(
            f"color: {c['green'] if enabled else c['muted']};"
            " font-size: 10px; background: transparent; border: none;"
        )
        lay.addWidget(dot)

        # Name + process
        info = QVBoxLayout()
        info.setSpacing(2)
        name_lbl = QLabel(self._cfg.get("name", self._id))
        name_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {c['primary']};"
            " background: transparent; border: none;"
        )
        name_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        proc = self._cfg.get("process_name", "")
        proc_lbl = QLabel(proc if proc else "—")
        proc_lbl.setStyleSheet(
            f"font-size: 10px; color: {c['muted']};"
            " background: transparent; border: none;"
        )
        proc_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        info.addWidget(name_lbl)
        info.addWidget(proc_lbl)
        lay.addLayout(info, 1)

        # Translation-update badge (مخفي حتى يُكتشَف تحديث ترجمة)
        self._upd_badge = QLabel("⬆ تحديث")
        self._upd_badge.setStyleSheet(
            f"background: {c['yellow']}; color: #1a1a1a; border-radius: 6px;"
            " padding: 1px 7px; font-size: 9px; font-weight: bold;"
        )
        self._upd_badge.setVisible(False)
        lay.addWidget(self._upd_badge)

        # Engine badge
        eng_raw = self._cfg.get("engine", "auto").lower()
        eng_key = next(
            (k for k in ("ue5", "ue4", "unreal", "unity") if k in eng_raw),
            eng_raw if eng_raw in _ENGINE_LABEL else "auto"
        )
        eng_color = c.get(_ENGINE_COLOR.get(eng_key, "muted"), c["muted"])
        badge = QLabel(_ENGINE_LABEL.get(eng_key, eng_raw))
        badge.setStyleSheet(f"""
            background: rgba(0,0,0,64);
            color: {eng_color};
            border: 1px solid {eng_color};
            border-radius: 6px;
            padding: 1px 7px;
            font-size: 9px;
            font-weight: bold;
        """)
        lay.addWidget(badge)

        self._refresh_style()

    def _refresh_style(self):
        c = theme.c
        if self._active:
            self.setStyleSheet(f"""
                QFrame {{
                    background: {c['hover']};
                    border-left: 3px solid {c['accent']};
                    border-top: 1px solid {c['border']};
                    border-bottom: 1px solid {c['border']};
                    border-right: none;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame {{
                    background: transparent;
                    border: none;
                    border-bottom: 1px solid {c['border']};
                }}
                QFrame:hover {{ background: {c['hover']}; }}
            """)

    def set_active(self, active: bool):
        self._active = active
        self._refresh_style()

    def set_update_available(self, online_ver: str):
        """يُظهر/يُخفي شارة «تحديث» حسب توفّر نسخة ترجمة أحدث."""
        b = getattr(self, "_upd_badge", None)
        if b is None:
            return
        if online_ver:
            b.setText(f"⬆ v{online_ver}")
            b.setToolTip(f"تحديث ترجمة متاح: v{online_ver}")
            b.setVisible(True)
        else:
            b.setVisible(False)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._id)
        super().mousePressEvent(event)


# ── Detail panel ──────────────────────────────────────────────────────────────

class GameDetailPanel(QFrame):
    """لوحة تفاصيل اللعبة المُحددة (يمين)."""

    edit_requested        = Signal(str)        # game_id
    delete_requested      = Signal(str)        # game_id
    translate_requested   = Signal(str)        # game_id
    iostore_requested     = Signal(str, dict)  # game_id, cfg
    install_requested     = Signal(str, str)   # game_id, game_path
    uninstall_requested   = Signal(str, str)   # game_id, game_path
    download_requested    = Signal(str)        # game_id
    download_install_requested = Signal(str, str)  # game_id, game_path (تحميل + تثبيت/تحديث)
    check_registry_requested = Signal()
    locres_requested      = Signal(str, str)   # game_id, folder_path
    font_requested        = Signal(str, str)   # game_id, game_path
    bepinex_install_requested    = Signal(str, str)  # game_id, game_path
    bepinex_uninstall_requested  = Signal(str, str)  # game_id, game_path
    bepinex_update_requested     = Signal(str, str)  # game_id, game_path
    bepinex_import_requested        = Signal(str, str)       # game_id, game_path
    bepinex_import_from_requested   = Signal(str, str, str)  # game_id, game_path, source_path
    bepinex_copy_dll_requested   = Signal(str, str)  # game_id, game_path
    bepinex_collect_requested      = Signal(str, str)  # game_id, game_path
    bepinex_collect_from_requested = Signal(str, str)  # game_id, source_path
    proxy_server_toggle_requested  = Signal(str, str)  # game_id, game_name
    model_priority_requested        = Signal(str)  # game_id — يفتح حوار أولوية المودلات
    ue4ss_install_requested         = Signal(str)  # game_id
    ue4ss_update_requested          = Signal(str)  # game_id — يصدّر القاموس
    ue4ss_import_missing_requested  = Signal(str)  # game_id — يقرأ missing.txt
    ue4ss_uninstall_requested       = Signal(str)  # game_id

    # Unreal Hook (dxgi.dll injection mod for UE5 games like Manor Lords/Palworld)
    unreal_hook_install_requested         = Signal(str, str)  # game_id, game_name
    unreal_hook_uninstall_requested       = Signal(str, str)  # game_id, game_name
    unreal_hook_launch_requested          = Signal(str, str)  # game_id, game_name
    unreal_hook_open_translate_requested  = Signal(str, str)  # game_id, game_name
    unreal_hook_update_translate_requested = Signal(str, str, str)  # game_id, game_name, model_filter
    unreal_hook_priority_requested        = Signal(str)        # game_id (opens priority dialog)

    # Foundation (Hurricane engine — proxy CrashRpt1403.dll + FreeType hook + RTL layout)
    foundation_install_requested   = Signal(str, str, int)  # game_id, game_path, wrap
    foundation_uninstall_requested = Signal(str, str)       # game_id, game_path
    foundation_update_requested    = Signal(str, str, int)  # game_id, game_path, wrap
    foundation_font_requested      = Signal(str, str)       # game_id, game_path

    # Manor Lords (DataTable .pak mod — repak V11)
    manorlords_install_requested   = Signal(str, str)       # game_id, game_path
    manorlords_uninstall_requested = Signal(str, str)       # game_id, game_path
    manorlords_update_requested    = Signal(str, str)       # game_id, game_path

    # IoStore mod (UE5 zen — retoc to-zen، بناء من الكاش)
    iostore_mod_install_requested   = Signal(str, str)      # game_id, game_path
    iostore_mod_uninstall_requested = Signal(str, str)      # game_id, game_path
    iostore_mod_update_requested    = Signal(str, str)      # game_id, game_path
    iostore_mod_rollback_requested  = Signal(str, str)      # game_id, game_path
    iostore_forcache_requested      = Signal(str)           # game_id (تحميل مصدر البناء)
    cache_export_requested          = Signal(str)           # game_id
    cache_import_requested          = Signal(str)           # game_id
    cache_delete_import_requested   = Signal(str, str)      # game_id, model

    def __init__(self, parent=None):
        super().__init__(parent)
        self._game_id       = None
        self._game_cfg      = {}
        self._cache         = None    # يُحدَّث في load() — مطلوب لقائمة المودلات
        self._registry_info: dict = {}
        self._registry_loaded: bool = False
        self._dl_progress   = None
        self._dl_lbl        = None
        self._proxy_server  = None
        # زر تشغيل/إغلاق اللعبة + مؤقّت تحديث حالته
        self._btn_launch_game: QPushButton | None = None
        self._launch_timer    = QTimer(self)
        self._launch_timer.setInterval(2000)   # كل ثانيتين
        self._launch_timer.timeout.connect(self._refresh_launch_btn)
        self._build_empty()

    def set_proxy_server(self, proxy):
        self._proxy_server = proxy

    def _build_empty(self):
        c   = theme.c
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { border: none; } QScrollArea > QWidget { background: transparent; }")
        outer.addWidget(self._scroll)

        # Placeholder content
        ph = QWidget()
        ph.setObjectName("games_placeholder")
        ph.setStyleSheet("QWidget#games_placeholder { background: transparent; }")
        ph_lay = QVBoxLayout(ph)
        placeholder = QLabel("اختر لعبة من القائمة لعرض تفاصيلها")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet(
            f"color: {c['muted']}; font-size: 14px;"
            " background: transparent; border: none;"
        )
        ph_lay.addStretch()
        ph_lay.addWidget(placeholder)
        ph_lay.addStretch()
        self._scroll.setWidget(ph)

    def load(self, game_id: str, cfg: dict, cache=None):
        self._game_id  = game_id
        self._game_cfg = cfg
        self._cache    = cache   # احفظه — تستخدمه بطاقات Unreal Hook + BepInEx لقوائم المودلات
        self._dl_progress = None
        self._dl_lbl      = None

        # Replace scroll content entirely — QScrollArea deletes the old widget automatically
        content = QWidget()
        content.setObjectName("games_detail_content")
        content.setStyleSheet("QWidget#games_detail_content { background: transparent; }")
        QVBoxLayout(content)   # empty layout; _render() will populate it
        self._scroll.setWidget(content)

        self._render(cfg, cache)

    def _render(self, cfg: dict, cache):
        c   = theme.c
        lay = self._scroll.widget().layout()
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(18)

        # نظّف زر تشغيل اللعبة السابق + أوقف مؤقّته قبل إعادة بناء البطاقة
        # (سيُعاد بناؤه إذا توفّرت بيانات اللعبة)
        self._launch_timer.stop()
        self._btn_launch_game = None

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        name_lbl = QLabel(cfg.get("name", self._game_id))
        name_lbl.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {c['primary']};"
            " background: transparent; border: none;"
        )
        name_lbl.setWordWrap(True)
        hdr.addWidget(name_lbl, 1)

        enabled = cfg.get("enabled", True)
        status_lbl = QLabel("● مفعّل" if enabled else "● معطّل")
        status_lbl.setStyleSheet(
            f"color: {c['green'] if enabled else c['muted']}; font-size: 12px;"
            " background: transparent; border: none;"
        )
        hdr.addWidget(status_lbl)
        lay.addLayout(hdr)

        # ── Info card ─────────────────────────────────────────────────────────
        info_card = self._card()
        info_lay  = QVBoxLayout(info_card)
        info_lay.setContentsMargins(16, 14, 16, 14)
        info_lay.setSpacing(10)

        def _row(key, val, color=None):
            row = QHBoxLayout()
            k_lbl = QLabel(key)
            k_lbl.setFixedWidth(120)
            k_lbl.setStyleSheet(
                f"color: {c['muted']}; font-size: 11px;"
                " background: transparent; border: none;"
            )
            v_lbl = QLabel(val or "—")
            v_lbl.setWordWrap(True)
            v_lbl.setStyleSheet(
                f"color: {color or c['secondary']}; font-size: 12px;"
                " background: transparent; border: none;"
            )
            row.addWidget(k_lbl)
            row.addWidget(v_lbl, 1)
            info_lay.addLayout(row)

        eng_raw = cfg.get("engine", "auto").lower()
        eng_key = next(
            (k for k in ("ue5", "ue4", "unreal", "unity") if k in eng_raw),
            eng_raw if eng_raw in _ENGINE_LABEL else "auto"
        )

        _row("اسم العملية:",  cfg.get("process_name", ""))
        _row("المحرك:",        _ENGINE_LABEL.get(eng_key, eng_raw),
             c.get(_ENGINE_COLOR.get(eng_key, "muted"), c["muted"]))
        _row("وضع الاعتراض:", cfg.get("hook_mode", "—"))
        _row("اللغة:",         f"{cfg.get('source_lang','en')} ← {cfg.get('target_lang','ar')}")

        path = cfg.get("game_path", "")
        if path:
            _row("المسار:", path if len(path) < 60 else "…" + path[-57:])

        if cfg.get("replace_font"):
            _row("الخط:", cfg.get("font_path", "") or "مُفعَّل")

        # Cache count
        cache_cnt = 0
        if cache:
            try:
                cache_cnt = cache.count_entries(cfg.get("name", self._game_id))
            except Exception:
                pass
        _row("الكاش:", f"{cache_cnt:,} ترجمة", c["teal"])

        notes = cfg.get("notes", "")
        if notes:
            _row("ملاحظات:", notes)

        lay.addWidget(info_card)

        # ── Feature visibility (from admin panel) ────────────────────────────
        hidden = set(cfg.get("hidden_features", []))
        shown  = set(cfg.get("shown_features",  []))
        gid_lower = (self._game_id or "").lower().replace(" ", "").replace("_", "")
        is_moe    = "myth" in gid_lower or "empires" in gid_lower or "moe" in gid_lower

        show_translate  = "translate"       not in hidden
        show_edit       = "edit_config"     not in hidden
        show_font       = "font_section"    not in hidden
        show_iostore    = ("iostore_section" in shown) and eng_key in ("ue4", "ue5", "unreal")
        if is_moe:
            show_locres = "locres_section" not in hidden
        else:
            show_locres = "locres_section" in shown
        show_pkg = "cache_section" not in hidden

        # ── Action buttons ────────────────────────────────────────────────────
        act_lbl = QLabel("الإجراءات")
        act_lbl.setStyleSheet(
            f"color: {c['muted']}; font-size: 11px; font-weight: bold;"
            " background: transparent; border: none;"
        )
        lay.addWidget(act_lbl)

        actions_card = self._card()
        actions_lay  = QVBoxLayout(actions_card)
        actions_lay.setContentsMargins(16, 14, 16, 14)
        actions_lay.setSpacing(10)

        def _btn(label, color_key, slot, icon=""):
            btn = QPushButton(f"{icon}  {label}" if icon else label)
            btn.setFixedHeight(38)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            clr = c.get(color_key, c["accent"])
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(0,0,0,38);
                    color: {clr};
                    border: 1px solid {clr};
                    border-radius: 8px;
                    font-weight: bold;
                    padding: 0 16px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background: {clr};
                    color: #fff;
                }}
            """)
            btn.clicked.connect(slot)
            return btn

        if show_translate:
            actions_lay.addWidget(
                _btn("ترجمة ملفات اللعبة", "accent",
                     lambda: self.translate_requested.emit(self._game_id), "🌐")
            )

        if show_iostore:
            actions_lay.addWidget(
                _btn("📦  IoStore / UAsset Wizard", "purple",
                     lambda gid=self._game_id, c=cfg: self.iostore_requested.emit(gid, c), "")
            )

        if show_locres:
            actions_lay.addWidget(
                _btn("📄  ترجمة .locres", "teal",
                     lambda: self.locres_requested.emit(
                         self._game_id, cfg.get("game_path", "")), "")
            )

        if show_font:
            actions_lay.addWidget(
                _btn("🔤  استبدال الخط", "orange",
                     lambda: self.font_requested.emit(
                         self._game_id, cfg.get("game_path", "")), "")
            )

        if show_edit:
            actions_lay.addWidget(
                _btn("تعديل الإعدادات", "blue",
                     lambda: self.edit_requested.emit(self._game_id), "✏️")
            )

        # زر تشغيل / إغلاق اللعبة — يظهر فقط إذا كان process_name + game_path معرَّفَين
        process_name = (cfg or {}).get("process_name", "").strip()
        game_path    = (cfg or {}).get("game_path", "").strip()
        if process_name and game_path and os.path.isdir(game_path):
            launch_btn = _btn("تشغيل اللعبة", "green",
                              self._on_launch_clicked, "🎮")
            self._btn_launch_game = launch_btn
            actions_lay.addWidget(launch_btn)
            # حدّث حالته فوراً + ابدأ المراقبة الدورية
            self._refresh_launch_btn()
            self._launch_timer.start()
        else:
            self._btn_launch_game = None
            self._launch_timer.stop()

        actions_lay.addWidget(
            _btn("حذف اللعبة", "accent",
                 lambda: self.delete_requested.emit(self._game_id), "🗑️")
        )

        lay.addWidget(actions_card)

        # ── UE4SS Arabic Translator card (للألعاب المضبوطة على هذا المسار فقط) ──
        # مسار بديل لـ UE (dict/translations.txt عبر UE4SS). لا يظهر إلا عند
        # اختياره صراحةً (mod_mode == "ue4ss" أو وجود إعداد ue4ss) — لئلا يزحم
        # كل صفحات ألعاب UE بمسار لا تستخدمه.
        if cfg.get("mod_mode") == "ue4ss" or "ue4ss" in cfg:
            self._render_ue4ss_card(lay, cfg)

        # ── Unreal Hook card (لألعاب UE5 اللي تحتاج dxgi injection) ────────────────
        shown = cfg.get("shown_features") or []
        if "unreal_hook_section" in shown or cfg.get("hook_mode") == "unreal_hook":
            self._render_unreal_hook_card(lay, cfg)

        # ── Foundation (Hurricane engine) card ──────────────────────────────────
        if cfg.get("engine") == "hurricane" or cfg.get("hook_mode") == "foundation_proxy":
            self._render_foundation_card(lay, cfg)

        # ── Manor Lords (DataTable .pak mod) card ───────────────────────────────
        if cfg.get("mod_mode") == "datatable_pak":
            self._render_manorlords_card(lay, cfg)

        # ── بطاقة الترجمة الموحَّدة (UE5 IoStore — Grounded2/Windrose…) ──────────
        # تظهر لألعاب IoStore التي لها: مصدر for_cache، أو حزمة ready، أو ترجمة
        # متاحة أونلاين (registry) — فتغطّي التحميل والبناء والتثبيت معاً.
        try:
            from games.iostore_mod import IoStoreMod
            if (cfg.get("mod_mode") != "datatable_pak"
                    and IoStoreMod.is_supported(cfg)):
                _iomod = IoStoreMod()
                _has_online = bool((getattr(self, "_registry_info", {}) or {})
                                   .get(self._game_id, {}).get("files"))
                if (_iomod.has_source(self._game_id) or _iomod.has_ready(self._game_id)
                        or _has_online):
                    self._render_iostore_mod_card(lay, cfg, _iomod)
        except Exception:
            pass

        # ── BepInEx + XUnity card (لألعاب Unity) ────────────────────────────────
        # نُظهره لألعاب Unity أو أي لعبة فيها قسم bepinex_mod في الـ config
        if eng_key == "unity" or "bepinex_mod" in cfg:
            self._render_bepinex_card(lay, cfg)

        # ── بطاقة كاش الترجمة (تصدير/استيراد — مشاركة بين المستخدمين) ────────────
        # مستقلّة عن cache_section (الذي يخفي بطاقة الحزمة القديمة) — تظهر لأي
        # لعبة لها كاش، فالتصدير/الاستيراد مفيد للجميع.
        self._render_cache_share_card(lay, cfg)

        lay.addStretch()

    def _render_cache_share_card(self, lay, cfg: dict):
        """بطاقة كاش الترجمة: تصدير/استيراد + مصادر مستوردة مستقلّة."""
        c = theme.c
        cache = getattr(self, "_cache", None)
        if not cache:
            return
        game = cfg.get("name", self._game_id) or self._game_id
        try:
            counts = cache.count_by_model(game) or {}
            imports = cache.list_import_sources(game) or {}
        except Exception:
            return
        total = sum(counts.values())
        if total == 0 and not imports:
            return  # لا كاش لهذه اللعبة

        title = QLabel("💾  كاش الترجمة (تصدير / استيراد / مشاركة)")
        title.setStyleSheet(
            f"color:{c['muted']};font-size:11px;font-weight:bold;background:transparent;border:none;")
        lay.addWidget(title)

        card = self._card()
        v = QVBoxLayout(card); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(10)

        own = total - sum(imports.values())
        info = QLabel(f"ترجماتك: {own:,}" + (f"  |  مستورَدة: {sum(imports.values()):,}" if imports else ""))
        info.setStyleSheet(f"color:{c['secondary']};font-size:12px;background:transparent;border:none;")
        v.addWidget(info)

        def mkbtn(label, color_key, slot, enabled=True):
            b = QPushButton(label); b.setFixedHeight(34)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            clr = c.get(color_key, c["accent"])
            b.setStyleSheet(
                f"QPushButton{{background:rgba(0,0,0,38);color:{clr};border:1px solid {clr};"
                f"border-radius:8px;font-weight:bold;padding:0 14px;text-align:left;}}"
                f"QPushButton:hover{{background:{clr};color:#fff;}}")
            b.setEnabled(enabled); b.clicked.connect(slot)
            return b

        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(mkbtn("📤  تصدير الكاش", "teal",
            lambda: self.cache_export_requested.emit(self._game_id), total > 0))
        row.addWidget(mkbtn("📥  استيراد كاش", "blue",
            lambda: self.cache_import_requested.emit(self._game_id)))
        v.addLayout(row)

        # مصادر الاستيراد المستقلّة (مستورد 1، مستورد 2…) — مع حذف
        for model, cnt in sorted(imports.items()):
            disp = model.split("import:", 1)[-1] or model
            r2 = QHBoxLayout()
            lbl = QLabel(f"🧩  {disp}  ({cnt:,})")
            lbl.setStyleSheet(f"color:{c['muted']};font-size:11px;background:transparent;border:none;")
            r2.addWidget(lbl, 1)
            del_b = QPushButton("🗑")
            del_b.setFixedWidth(34); del_b.setCursor(QCursor(Qt.PointingHandCursor))
            del_b.setStyleSheet(
                f"QPushButton{{background:transparent;color:#e06c6c;border:1px solid #e06c6c;border-radius:6px;}}"
                "QPushButton:hover{background:#e06c6c;color:#fff;}")
            del_b.clicked.connect(
                lambda _ck=False, m=model: self.cache_delete_import_requested.emit(self._game_id, m))
            r2.addWidget(del_b)
            v.addLayout(r2)

        hint = QLabel("ⓘ شارك ملف .gatcache مع غيرك (واتساب/درايف). الاستيراد لا يدهس ترجماتك "
                      "(دمج آمن) أو يحفظها كمصدر مستقل. بعدها «إعادة بناء» تطبّقها.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{c['muted']};font-size:9px;background:transparent;border:none;")
        v.addWidget(hint)

        lay.addWidget(card)

    # ====================== FOUNDATION (HURRICANE) CARD ======================
    def _render_foundation_card(self, lay, cfg: dict):
        """بطاقة Foundation: تثبيت/تحديث/إلغاء تعريب (proxy DLL + RTL) + ضبط لفّ الأسطر."""
        from PySide6.QtWidgets import QSpinBox
        from games.foundation_mod import FoundationMod
        c = theme.c
        game_path = cfg.get("game_path", "")
        mod = FoundationMod()
        status = mod.get_install_status(cfg, game_path)
        wrap_default = int(cfg.get("foundation", {}).get("wrap", 45))

        title = QLabel("🏛️  تعريب Foundation (proxy DLL + RTL)")
        title.setStyleSheet(
            f"color:{c['muted']};font-size:11px;font-weight:bold;background:transparent;border:none;")
        lay.addWidget(title)

        card = self._card()
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        if status is None:
            st, col = "⚠ حدّد مسار اللعبة أولاً", c["orange"]
        elif status:
            st, col = "✅ مُثبَّت — شغّل اللعبة عبر Steam عادي", c["green"]
        else:
            st, col = "○ غير مُثبَّت", c["muted"]
        st_lbl = QLabel(st)
        st_lbl.setStyleSheet(f"color:{col};font-size:12px;background:transparent;border:none;")
        v.addWidget(st_lbl)

        # الخط الحالي المُطبَّق (Regular + Bold لو مختلف)
        if status:
            reg = mod.current_font_name(game_path, "regular") or "—"
            bold = mod.current_font_name(game_path, "bold") or "—"
            txt = f"🔤  الخط الحالي: {reg}" + (f"   |   Bold: {bold}" if bold != reg else "")
            fi = QLabel(txt)
            fi.setWordWrap(True)
            fi.setStyleSheet(f"color:{c['secondary']};font-size:11px;background:transparent;border:none;")
            v.addWidget(fi)

        # عدد الأحرف لكل سطر (منزلق — أوضح من الأسهم في RTL)
        from PySide6.QtWidgets import QSlider
        whdr = QHBoxLayout()
        wlbl = QLabel("حرف لكل سطر (≤ أضيق صندوق):")
        wlbl.setStyleSheet(f"color:{c['muted']};font-size:11px;background:transparent;border:none;")
        wval = QLabel(str(wrap_default))
        wval.setFixedWidth(34)
        wval.setAlignment(Qt.AlignCenter)
        wval.setStyleSheet(
            f"color:{c['primary']};font-size:13px;font-weight:bold;"
            f"background:rgba(0,0,0,45);border:1px solid {c['muted']};border-radius:6px;")
        whdr.addWidget(wlbl)
        whdr.addStretch()
        whdr.addWidget(wval)
        v.addLayout(whdr)
        slider = QSlider(Qt.Horizontal)
        slider.setLayoutDirection(Qt.LeftToRight)
        slider.setRange(0, 120)
        slider.setValue(wrap_default)
        slider.setToolTip("0=فواصل صريحة فقط. قلّله لو انقلبت أسطر صناديق ضيّقة؛ زِده للعريضة.\n"
                          "ثم اضغط «تحديث الترجمة» لتطبيق القيمة.")
        slider.valueChanged.connect(lambda val: wval.setText(str(val)))
        v.addWidget(slider)
        hint = QLabel("ⓘ غيّر القيمة ثم اضغط «تحديث الترجمة» لتطبيقها.")
        hint.setStyleSheet(f"color:{c['muted']};font-size:10px;background:transparent;border:none;")
        v.addWidget(hint)

        def mkbtn(label, color_key, slot):
            b = QPushButton(label)
            b.setFixedHeight(36)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            clr = c.get(color_key, c["accent"])
            b.setStyleSheet(
                f"QPushButton{{background:rgba(0,0,0,38);color:{clr};border:1px solid {clr};"
                f"border-radius:8px;font-weight:bold;padding:0 14px;text-align:left;}}"
                f"QPushButton:hover{{background:{clr};color:#fff;}}")
            b.clicked.connect(slot)
            return b

        gp = game_path
        if status is True:
            v.addWidget(mkbtn("🔤  اختيار الخط العربي (تجربة)", "orange",
                lambda: self.foundation_font_requested.emit(self._game_id, gp)))
            v.addWidget(mkbtn("🔄  تحديث الترجمة (بعد تعديلها في الكاش)", "teal",
                lambda: self.foundation_update_requested.emit(self._game_id, gp, slider.value())))
            v.addWidget(mkbtn("🗑️  إلغاء التعريب (استعادة الأصل)", "accent",
                lambda: self.foundation_uninstall_requested.emit(self._game_id, gp)))
        elif status is False:
            ib = mkbtn("✅  تثبيت التعريب", "green",
                lambda: self.foundation_install_requested.emit(self._game_id, gp, slider.value()))
            ib.setEnabled(FoundationMod.proxy_src_exists())
            if not FoundationMod.proxy_src_exists():
                ib.setToolTip("الـ proxy غير موجود في mods/Foundation/")
            v.addWidget(ib)

        lay.addWidget(card)

    # ====================== MANOR LORDS (DATATABLE .PAK) CARD ======================
    def _render_manorlords_card(self, lay, cfg: dict):
        """بطاقة Manor Lords: تثبيت/تحديث/إلغاء مود DataTable (.pak) من الكاش."""
        from games.manorlords_mod import ManorLordsMod
        c = theme.c
        game_path = cfg.get("game_path", "")
        mod = ManorLordsMod()
        status = mod.get_install_status(cfg, game_path)
        tools_ok, tools_msg = ManorLordsMod.tools_exist()

        title = QLabel("🏰  تعريب Manor Lords (مود DataTable .pak — repak V11)")
        title.setStyleSheet(
            f"color:{c['muted']};font-size:11px;font-weight:bold;background:transparent;border:none;")
        lay.addWidget(title)

        card = self._card()
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        if status is None:
            st, col = "⚠ حدّد مسار اللعبة أولاً", c["orange"]
        elif status:
            st, col = "✅ مُثبَّت — شغّل اللعبة عبر Steam عادي", c["green"]
        else:
            st, col = "○ غير مُثبَّت", c["muted"]
        st_lbl = QLabel(st)
        st_lbl.setStyleSheet(f"color:{col};font-size:12px;background:transparent;border:none;")
        v.addWidget(st_lbl)

        if not tools_ok:
            w = QLabel("⚠ " + tools_msg)
            w.setWordWrap(True)
            w.setStyleSheet(f"color:{c['orange']};font-size:11px;background:transparent;border:none;")
            v.addWidget(w)

        info = QLabel("يطبّق ترجمات الكاش على جداول DT_Translation_* ويحزمها مود .pak.\n"
                      "الترجمة الدفعية للجداول: tools/manorlords/build_all.py")
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{c['muted']};font-size:10px;background:transparent;border:none;")
        v.addWidget(info)

        def mkbtn(label, color_key, slot, enabled=True):
            b = QPushButton(label)
            b.setFixedHeight(36)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            clr = c.get(color_key, c["accent"])
            b.setStyleSheet(
                f"QPushButton{{background:rgba(0,0,0,38);color:{clr};border:1px solid {clr};"
                f"border-radius:8px;font-weight:bold;padding:0 14px;text-align:left;}}"
                f"QPushButton:hover{{background:{clr};color:#fff;}}"
                f"QPushButton:disabled{{color:{c['muted']};border-color:{c['muted']};}}")
            b.setEnabled(enabled)
            b.clicked.connect(slot)
            return b

        gp = game_path
        if status is True:
            v.addWidget(mkbtn("🔄  تحديث الترجمة (بعد تعديلها في الكاش)", "teal",
                lambda: self.manorlords_update_requested.emit(self._game_id, gp), tools_ok))
            v.addWidget(mkbtn("🗑️  إلغاء التعريب (حذف المود)", "accent",
                lambda: self.manorlords_uninstall_requested.emit(self._game_id, gp)))
        elif status is False:
            v.addWidget(mkbtn("✅  تثبيت التعريب (بناء + حزم + تثبيت)", "green",
                lambda: self.manorlords_install_requested.emit(self._game_id, gp), tools_ok))

        lay.addWidget(card)

    def _render_iostore_mod_card(self, lay, cfg: dict, mod):
        """بطاقة الترجمة الموحَّدة لألعاب IoStore — تجمع كل دورة حياة الترجمة:
        تحميل/تحديث من GitHub + بناء محلي من الكاش + تثبيت/إلغاء."""
        c = theme.c
        game_path = cfg.get("game_path", "")
        status = mod.get_install_status(self._game_id, game_path)
        tools_ok, tools_msg = mod.tools_exist(self._game_id)
        has_src = mod.has_source(self._game_id)
        has_ready = mod.has_ready(self._game_id)
        path_ok = bool(game_path) and os.path.isdir(game_path)
        if status is None and path_ok:
            status = False

        # ── بيانات الإصدار من الـ registry (GitHub) ─────────────────────────
        reg_info   = (getattr(self, "_registry_info", {}) or {}).get(self._game_id) or {}
        online_ver = str(reg_info.get("version", "") or "")
        has_online = bool(reg_info.get("files"))
        try:
            from games.translation_package import TranslationPackage
            from games.translation_registry import _version_gt
            _pkg = TranslationPackage()
            installed_ver = _pkg.get_installed_version(self._game_id) or ""
            _inst_cmp = installed_ver if installed_ver else ("0" if status else "")
            has_update = bool(has_online and online_ver and _inst_cmp != ""
                              and _version_gt(online_ver, _inst_cmp))
        except Exception:
            installed_ver, has_update = "", False

        title = QLabel("📦  حزمة الترجمة (IoStore)")
        title.setStyleSheet(
            f"color:{c['muted']};font-size:11px;font-weight:bold;background:transparent;border:none;")
        lay.addWidget(title)

        card = self._card()
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        if has_update:
            st, col = f"🔄 تحديث متاح ← v{online_ver}", c["yellow"]
        elif status is None:
            st, col = "⚠ حدّد مسار اللعبة أولاً", c["orange"]
        elif status:
            st, col = "✅ مُثبَّت — شغّل اللعبة عبر Steam عادي", c["green"]
        else:
            st, col = "○ غير مُثبَّت", c["muted"]
        st_lbl = QLabel(st)
        st_lbl.setStyleSheet(f"color:{col};font-size:12px;background:transparent;border:none;")
        v.addWidget(st_lbl)

        # «ما الجديد» (ملاحظات الإصدار) عند توفّر تحديث
        if has_update and reg_info.get("release_notes"):
            notes_lbl = QLabel("📝 " + str(reg_info["release_notes"]))
            notes_lbl.setWordWrap(True)
            notes_lbl.setStyleSheet(f"color:{c['secondary']};font-size:10px;background:transparent;border:none;")
            v.addWidget(notes_lbl)

        # شريط تقدّم التحميل (مخفي حتى يبدأ التحميل) — يستخدمه _run_download
        self._dl_progress = QProgressBar()
        self._dl_progress.setFixedHeight(6); self._dl_progress.setTextVisible(False)
        self._dl_progress.setVisible(False)
        self._dl_progress.setStyleSheet(
            f"QProgressBar {{ background:{c['border']}; border-radius:3px; border:none; }}"
            f"QProgressBar::chunk {{ background:{c['blue']}; border-radius:3px; }}")
        v.addWidget(self._dl_progress)
        self._dl_lbl = QLabel(""); self._dl_lbl.setVisible(False)
        self._dl_lbl.setStyleSheet(f"color:{c['muted']};font-size:10px;background:transparent;border:none;")
        v.addWidget(self._dl_lbl)

        def mkbtn(label, color_key, slot, enabled=True):
            b = QPushButton(label)
            b.setFixedHeight(36)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            clr = c.get(color_key, c["accent"])
            b.setStyleSheet(
                f"QPushButton{{background:rgba(0,0,0,38);color:{clr};border:1px solid {clr};"
                f"border-radius:8px;font-weight:bold;padding:0 14px;text-align:left;}}"
                f"QPushButton:hover{{background:{clr};color:#fff;}}"
                f"QPushButton:disabled{{color:{c['muted']};border-color:{c['muted']};}}")
            b.setEnabled(enabled)
            b.clicked.connect(slot)
            return b

        gp = game_path
        can_build = tools_ok and has_src

        # ① تحديث من GitHub (الأولوية القصوى عند توفّره)
        if has_update:
            v.addWidget(mkbtn(f"🔄  تحديث إلى v{online_ver}  (تحميل + تثبيت)", "yellow",
                lambda: self.download_install_requested.emit(self._game_id, gp),
                enabled=path_ok))

        # ② التثبيت/التحميل عند عدم التثبيت
        if status is False:
            if has_ready or can_build:
                v.addWidget(mkbtn("✅  تثبيت الترجمة (من ملفات المود المحلية)", "green",
                    lambda: self.iostore_mod_install_requested.emit(self._game_id, gp),
                    enabled=(can_build or has_ready)))
            elif has_online:
                v.addWidget(mkbtn("⬇️  تحميل + تثبيت الترجمة", "blue",
                    lambda: self.download_install_requested.emit(self._game_id, gp),
                    enabled=path_ok))

        # ③ عند التثبيت: إلغاء + (إعادة بناء محلي للمطوّر)
        elif status is True:
            if can_build:
                v.addWidget(mkbtn("🔧  إعادة بناء من الكاش (تحديث محلي بعد تعديل الكاش)", "teal",
                    lambda: self.iostore_mod_update_requested.emit(self._game_id, gp)))
            v.addWidget(mkbtn("🗑️  إلغاء التعريب (حذف المود)", "accent",
                lambda: self.iostore_mod_uninstall_requested.emit(self._game_id, gp)))

        # ④ تمكين البناء المحلي: تحميل مصدر البناء (for_cache) لمن لا مصدر لديه
        #    بعده يصبح زر «إعادة بناء/تثبيت من الكاش» متاحاً (الأدوات مُضمَّنة).
        if not has_src and reg_info.get("for_cache_url"):
            fc_mb = reg_info.get("for_cache_size_mb", 0)
            fc_txt = f"  (~{fc_mb}MB)" if fc_mb else ""
            v.addWidget(mkbtn(f"🧩  تحميل مصدر البناء للتعديل المحلي{fc_txt}", "blue",
                lambda: self.iostore_forcache_requested.emit(self._game_id)))
            hint = QLabel("ⓘ لإعادة البناء من كاشك المحلي (بعد تعديل الترجمات في صفحة الكاش) "
                          "حمّل مصدر البناء مرّة واحدة — ثم يظهر زر «إعادة بناء».")
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color:{c['muted']};font-size:10px;background:transparent;border:none;")
            v.addWidget(hint)

        # ⑤ تراجع للنسخة السابقة (إن وُجدت لقطة)
        try:
            from games.translation_package import TranslationPackage as _TP
            _tp = _TP()
            if _tp.has_previous(self._game_id):
                _pv = _tp.previous_version(self._game_id)
                _lbl = f"↩  تراجع للنسخة السابقة" + (f" (v{_pv})" if _pv else "")
                v.addWidget(mkbtn(_lbl, "muted",
                    lambda: self.iostore_mod_rollback_requested.emit(self._game_id, gp),
                    enabled=path_ok))
        except Exception:
            pass

        # ⑤ سجل التغييرات (changelog)
        _clog = reg_info.get("changelog") or []
        if _clog:
            def _show_changelog(_ck=False, log=_clog, gname=self._game_id):
                lines = []
                for e in log[:10]:
                    ver = e.get("version", "?")
                    nt  = (e.get("notes", "") or "").strip() or "—"
                    lines.append(f"• v{ver}: {nt}")
                QMessageBox.information(self, f"📜 سجل تحديثات {gname}", "\n\n".join(lines))
            v.addWidget(mkbtn("📜  سجل التحديثات", "muted", _show_changelog))

        # تلميحات
        if not tools_ok and (has_src or status is True):
            w = QLabel("⚠ " + tools_msg + "  (البناء المحلي معطّل — التحميل من GitHub يعمل)")
            w.setWordWrap(True)
            w.setStyleSheet(f"color:{c['orange']};font-size:10px;background:transparent;border:none;")
            v.addWidget(w)

        if installed_ver or online_ver:
            parts = []
            if installed_ver: parts.append(f"مُثبَّت: v{installed_ver}")
            if online_ver:    parts.append(f"متاح: v{online_ver}")
            vl = QLabel("  |  ".join(parts))
            vl.setStyleSheet(f"color:{c['muted']};font-size:10px;background:transparent;border:none;")
            v.addWidget(vl)

        lay.addWidget(card)

    # ====================== UNREAL HOOK CARD ======================
    def _render_unreal_hook_card(self, lay, cfg: dict):
        """بطاقة Unreal Hook: تثبيت + تشغيل اللعبة + watcher + إحصاءات."""
        try:
            from games.unreal_hook_mod import UnrealHookMod
        except ImportError:
            return
        c = theme.c
        mod = UnrealHookMod()
        status = mod.get_status(cfg)

        # كرت Unreal Hook
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: {c['card']};
                border: 1px solid {c['border']};
                border-radius: 10px;
                padding: 14px;
            }}
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(8)

        # العنوان
        hdr = QHBoxLayout()
        title = QLabel("🌐  محرّك Unreal Hook — ترجمة UE5 (dxgi injection)")
        title.setStyleSheet(f"color: {c['primary']}; font-size: 13px; font-weight: bold; background: transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        if status["installed"]:
            badge = QLabel("✓ مُثبَّت")
            badge.setStyleSheet(f"color: {c['green']}; font-size: 10px; font-weight: bold; background: transparent;")
        else:
            badge = QLabel("✗ غير مُثبَّت")
            badge.setStyleSheet(f"color: {c['accent']}; font-size: 10px; font-weight: bold; background: transparent;")
        hdr.addWidget(badge)
        cl.addLayout(hdr)

        # وصف
        desc = QLabel(
            "يعترض نصوص UE5 عبر dxgi.dll hijack + suspended-launch injection. "
            "النصوص تُرسَل لبروكسي الترجمة في نظامنا (Ollama)."
        )
        desc.setStyleSheet(f"color: {c['muted']}; font-size: 10px; background: transparent;")
        desc.setWordWrap(True)
        cl.addWidget(desc)

        # حالة المسار
        if not status["win64_exists"]:
            warn = QLabel(f"⚠ مجلد اللعبة غير موجود: {status['win64_dir']}")
            warn.setStyleSheet(f"color: {c['yellow']}; font-size: 10px; background: transparent;")
            warn.setWordWrap(True)
            cl.addWidget(warn)
            lay.addWidget(card)
            return

        # ── إحصاءات ──
        if status["installed"]:
            stats_row = QHBoxLayout()
            stats_row.setSpacing(20)
            for label, value, color in [
                ("نصوص ملتقطة", status["captured_count"], c.get('accent2', c['primary'])),
                ("نصوص مترجمة", status["translated_count"], c['green']),
                ("في الانتظار", max(0, status["captured_count"] - status["translated_count"]), c['yellow']),
            ]:
                box = QVBoxLayout()
                box.setSpacing(2)
                val = QLabel(f"{value:,}")
                val.setStyleSheet(f"color: {color}; font-size: 18px; font-weight: bold; background: transparent;")
                val.setAlignment(Qt.AlignCenter)
                lbl = QLabel(label)
                lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px; background: transparent;")
                lbl.setAlignment(Qt.AlignCenter)
                box.addWidget(val)
                box.addWidget(lbl)
                wrap = QFrame()
                wrap.setStyleSheet(f"background: transparent; border: none;")
                wrap.setLayout(box)
                stats_row.addWidget(wrap, 1)
            cl.addLayout(stats_row)

        # ── أزرار العمل ──
        row_actions = QHBoxLayout()
        row_actions.setSpacing(8)

        def _btn_style(color):
            return f"""
                QPushButton {{
                    background: transparent; color: {color};
                    border: 1px solid {color}; border-radius: 7px;
                    font-weight: bold; font-size: 11px; padding: 0 14px;
                }}
                QPushButton:hover {{ background: {color}; color: #fff; }}
            """

        if not status["installed"]:
            install_btn = QPushButton("📥  تثبيت Unreal Hook")
            install_btn.setFixedHeight(34)
            install_btn.setCursor(QCursor(Qt.PointingHandCursor))
            install_btn.setStyleSheet(_btn_style(c['green']))
            install_btn.clicked.connect(lambda: self.unreal_hook_install_requested.emit(self._game_id, cfg.get("name", self._game_id)))
            row_actions.addWidget(install_btn)
        else:
            launch_btn = QPushButton("▶  تشغيل اللعبة + الترجمة")
            launch_btn.setFixedHeight(34)
            launch_btn.setCursor(QCursor(Qt.PointingHandCursor))
            launch_btn.setStyleSheet(_btn_style(c['green']))
            launch_btn.clicked.connect(lambda: self.unreal_hook_launch_requested.emit(self._game_id, cfg.get("name", self._game_id)))
            row_actions.addWidget(launch_btn)

            open_folder_btn = QPushButton("📂  Translate/")
            open_folder_btn.setFixedHeight(34)
            open_folder_btn.setCursor(QCursor(Qt.PointingHandCursor))
            open_folder_btn.setStyleSheet(_btn_style(c.get('accent2', c['primary'])))
            open_folder_btn.clicked.connect(lambda: self.unreal_hook_open_translate_requested.emit(self._game_id, cfg.get("name", self._game_id)))
            row_actions.addWidget(open_folder_btn)

            uninstall_btn = QPushButton("🗑  إلغاء التثبيت")
            uninstall_btn.setFixedHeight(34)
            uninstall_btn.setCursor(QCursor(Qt.PointingHandCursor))
            uninstall_btn.setStyleSheet(_btn_style(c['accent']))
            uninstall_btn.clicked.connect(lambda: self.unreal_hook_uninstall_requested.emit(self._game_id, cfg.get("name", self._game_id)))
            row_actions.addWidget(uninstall_btn)

        row_actions.addStretch()
        cl.addLayout(row_actions)

        # ── قسم تحديث Translate من الكاش (يظهر فقط لو مُثبَّت ولديه ترجمات) ──
        if status["installed"]:
            # شريط فاصل
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet(f"background: {c['border']}; max-height: 1px;")
            cl.addWidget(sep)

            # عنوان القسم
            update_title = QLabel("🔄  تحديث مجلد Translate من الكاش")
            update_title.setStyleSheet(
                f"color: {c['primary']}; font-size: 11px; font-weight: bold; "
                "background: transparent; padding-top: 4px;"
            )
            cl.addWidget(update_title)

            update_desc = QLabel(
                "يُعيد إنشاء ملفات .subtitle.txt من الكاش "
                "(للتطبيق الفوري بعد إضافة/تعديل ترجمات)."
            )
            update_desc.setStyleSheet(f"color: {c['muted']}; font-size: 9px; background: transparent;")
            update_desc.setWordWrap(True)
            cl.addWidget(update_desc)

            # صف dropdown + أزرار
            row_update = QHBoxLayout()
            row_update.setSpacing(8)

            # dropdown اختيار المودل
            from PySide6.QtWidgets import QComboBox
            model_combo = QComboBox()
            model_combo.setFixedHeight(32)
            model_combo.setStyleSheet(f"""
                QComboBox {{
                    background: {c.get('card2', c['card'])};
                    color: {c['primary']};
                    border: 1px solid {c['border']};
                    border-radius: 6px;
                    padding: 0 10px;
                    font-size: 11px;
                    min-width: 200px;
                }}
                QComboBox::drop-down {{ border: none; width: 24px; }}
                QComboBox QAbstractItemView {{
                    background: {c['card']};
                    color: {c['primary']};
                    selection-background-color: {c.get('accent2', c['accent'])};
                }}
            """)
            # نُضيف كل المودلات الموجودة في الكاش — مع العدد الإجمالي للهرمي
            try:
                if self._cache:
                    game_name = cfg.get("name", self._game_id)
                    counts = self._cache.count_by_model(game_name) or {}
                    total_all = 0
                    try:
                        total_all = self._cache.count_entries(game_name)
                    except Exception:
                        total_all = sum(counts.values()) if counts else 0
                    # خيار "دمج هرمي" (افتراضي) — نفس UX Flotsam
                    model_combo.addItem(
                        f"🏆  دمج هرمي ({total_all:,} ترجمة من كل المودلات)", ""
                    )
                    for model_name in sorted(counts.keys()):
                        cnt = counts[model_name]
                        if model_name:
                            model_combo.addItem(f"🤖 {model_name}  ({cnt:,} ترجمة)", model_name)
                else:
                    model_combo.addItem("🏆  دمج هرمي (الأفضل من كل المودلات)", "")
            except Exception:
                model_combo.addItem("🏆  دمج هرمي (الأفضل من كل المودلات)", "")
            row_update.addWidget(model_combo, 1)

            # زر تحديث
            update_btn = QPushButton("🔄  تحديث الآن")
            update_btn.setFixedHeight(32)
            update_btn.setCursor(QCursor(Qt.PointingHandCursor))
            update_btn.setStyleSheet(_btn_style(c['green']))
            update_btn.clicked.connect(
                lambda: self.unreal_hook_update_translate_requested.emit(
                    self._game_id,
                    cfg.get("name", self._game_id),
                    model_combo.currentData() or "",
                )
            )
            row_update.addWidget(update_btn)

            # زر أولوية المودلات (يفتح نفس حوار Flotsam)
            priority_btn = QPushButton("🎯  الأولوية")
            priority_btn.setFixedHeight(32)
            priority_btn.setCursor(QCursor(Qt.PointingHandCursor))
            priority_btn.setStyleSheet(_btn_style(c.get('accent2', c['accent'])))
            priority_btn.setToolTip("ترتيب أولوية المودلات للدمج الهرمي")
            priority_btn.clicked.connect(
                lambda: self.unreal_hook_priority_requested.emit(self._game_id)
            )
            row_update.addWidget(priority_btn)

            cl.addLayout(row_update)

        # ملاحظة
        note = QLabel(
            "💡 تأكّد Steam يعمل في الخلفية + Ollama في GUI الإعدادات. "
            "زر التشغيل سيفتح: بروكسي + watcher + اللعبة (مع injection)."
        )
        note.setStyleSheet(f"color: {c['muted']}; font-size: 9px; background: transparent; padding-top: 4px;")
        note.setWordWrap(True)
        cl.addWidget(note)

        lay.addWidget(card)

    def _render_ue4ss_card(self, lay, cfg: dict):
        """بطاقة تثبيت + إدارة UE4SS Arabic Translator لألعاب UE."""
        try:
            from games.ue4ss_mod import UE4SSMod
        except ImportError:
            return
        c          = theme.c
        game_path  = cfg.get("game_path", "")
        game_name  = cfg.get("name", self._game_id)
        if not game_path:
            return

        mod = UE4SSMod()
        ue4ss_ok = False
        mod_ok   = False
        ue4ss_runtime_error = ""
        try:
            ue4ss_ok = mod.is_ue4ss_installed(game_path, self._game_id)
            mod_ok   = mod.is_mod_installed(game_path, self._game_id)
            # افحص log إن وُجد لاكتشاف Fatal errors (PS scan failures مثلاً)
            if ue4ss_ok:
                w64 = mod._win64_dir(game_path, self._game_id)
                log_path = os.path.join(w64, "UE4SS.log")
                if os.path.isfile(log_path):
                    try:
                        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                            # اقرأ آخر 5KB فقط (سريع)
                            f.seek(0, 2)
                            size = f.tell()
                            f.seek(max(0, size - 5000))
                            tail = f.read()
                        if "Fatal Error" in tail or "PS scan timed out" in tail:
                            ue4ss_runtime_error = "فشل scan — UE4SS غير متوافق مع إصدار اللعبة"
                    except Exception:
                        pass
        except Exception:
            pass

        card = self._card()
        cl   = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(8)

        # ── رأس البطاقة ──
        hdr_row = QHBoxLayout()
        ttl = QLabel("🎮  UE4SS Arabic Translator (بدون lag)")
        ttl.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {c['primary']};"
            " background: transparent; border: none;"
        )
        if ue4ss_ok and mod_ok:
            st_text, st_color = "● مُثبَّت", c["green"]
        elif ue4ss_ok:
            st_text, st_color = "● UE4SS فقط (المود ناقص)", c["yellow"]
        else:
            st_text, st_color = "● غير مُثبَّت", c["muted"]
        st_lbl = QLabel(st_text)
        st_lbl.setStyleSheet(
            f"color: {st_color}; font-size: 11px;"
            " background: transparent; border: none;"
        )
        hdr_row.addWidget(ttl)
        hdr_row.addStretch()
        hdr_row.addWidget(st_lbl)
        cl.addLayout(hdr_row)

        # ── حالة المكوّنات ──
        def _status_line(icon, text, color):
            lbl = QLabel(f"{icon} {text}")
            lbl.setStyleSheet(
                f"color: {color}; font-size: 10px;"
                " background: transparent; border: none;"
            )
            cl.addWidget(lbl)

        _status_line("✓" if ue4ss_ok else "✗",
                     "UE4SS — " + ("مُحمَّل" if ue4ss_ok else "غير محمَّل"),
                     c["green"] if ue4ss_ok else c["muted"])
        _status_line("✓" if mod_ok else "✗",
                     "UE4ArabicTranslator — " + ("مُحمَّل" if mod_ok else "غير محمَّل"),
                     c["green"] if mod_ok else c["muted"])
        if ue4ss_runtime_error:
            _status_line("⚠", ue4ss_runtime_error, c.get("accent", "#e94560"))

        # عدد الترجمات في القاموس + missing
        dict_count = 0
        missing_count = 0
        if mod_ok:
            try:
                dict_path = os.path.join(
                    mod._mod_target(game_path, self._game_id),
                    "dict", "translations.txt"
                )
                if os.path.isfile(dict_path):
                    with open(dict_path, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip() and not line.startswith("#") and "=" in line:
                                dict_count += 1
                missing_count = len(mod.read_missing(game_path, self._game_id))
            except Exception:
                pass

        if mod_ok:
            _status_line("📖", f"القاموس — {dict_count:,} ترجمة في translations.txt",
                         c.get("teal", "#00d2ff"))
            if missing_count > 0:
                _status_line("⚠", f"نصوص جديدة بانتظار الترجمة — {missing_count}",
                             c.get("yellow", "#ffa600"))

        # ── أزرار ──
        def _mini_btn(label, color_key, slot):
            btn = QPushButton(label)
            btn.setFixedHeight(32)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            clr = c.get(color_key, c["accent"])
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(0,0,0,38);
                    color: {clr};
                    border: 1px solid {clr};
                    border-radius: 6px;
                    font-weight: bold;
                    padding: 0 12px;
                    font-size: 11px;
                }}
                QPushButton:hover {{ background: {clr}; color: #fff; }}
            """)
            btn.clicked.connect(slot)
            return btn

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        if not ue4ss_ok or not mod_ok:
            # غير مُثبَّت → زر تثبيت كبير
            install_btn = QPushButton("✅  تثبيت UE4SS + المود")
            install_btn.setFixedHeight(36)
            install_btn.setCursor(QCursor(Qt.PointingHandCursor))
            install_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {c['green']};
                    color: #fff;
                    border: none; border-radius: 8px;
                    font-weight: bold; font-size: 12px; padding: 0 18px;
                }}
                QPushButton:hover {{ background: #2e7d32; }}
            """)
            install_btn.clicked.connect(
                lambda: self.ue4ss_install_requested.emit(self._game_id)
            )
            row1.addWidget(install_btn)
        else:
            # مُثبَّت → أزرار التحديث + الاستيراد (دائماً مرئي) + إلغاء
            row1.addWidget(_mini_btn(
                "🔄  تحديث القاموس", "teal",
                lambda: self.ue4ss_update_requested.emit(self._game_id),
            ))
            # زر استيراد دائماً مرئي — لو لا يوجد نصوص يعرض رسالة معلوماتية
            import_label = (
                f"📥  استيراد {missing_count} نص جديد"
                if missing_count > 0
                else "📥  استيراد نصوص (لا يوجد)"
            )
            row1.addWidget(_mini_btn(
                import_label,
                "yellow" if missing_count > 0 else "muted",
                lambda: self.ue4ss_import_missing_requested.emit(self._game_id),
            ))
            row1.addWidget(_mini_btn(
                "🗑️  إلغاء التثبيت", "accent",
                lambda: self.ue4ss_uninstall_requested.emit(self._game_id),
            ))

        row1.addStretch()
        cl.addLayout(row1)
        lay.addWidget(card)

    def _render_bepinex_card(self, lay, cfg: dict):
        """بطاقة تثبيت BepInEx+XUnity (Method 2) أو plugin خاص (Method 1)."""
        try:
            from games.bepinex_mod import BepInExMod
        except ImportError:
            return
        mod = BepInExMod()
        if not mod.is_supported(cfg):
            return

        c         = theme.c
        game_path = cfg.get("game_path", "")
        bm        = cfg.get("bepinex_mod", {})
        dll_name  = bm.get("dll_name", "")
        is_xunity_mode = not dll_name   # Method 2: XUnity proxy, no custom DLL

        resolved_src    = mod._resolve_bepinex_source(cfg)
        has_bepinex_src = bool(resolved_src)
        src_label       = os.path.basename(resolved_src) if resolved_src else ""
        installed       = mod.get_install_status(cfg, game_path)
        bepinex_in_game = mod.is_bepinex_installed(game_path) if game_path else False

        # حالة المكونات في اللعبة (لـ Method 2)
        xunity_ok     = mod.is_xunity_installed(game_path) if game_path else False
        font_fixer_ok = mod.is_font_fixer_installed(game_path) if game_path else False
        # حالة DLL / JSON (لـ Method 1)
        dll_ok        = mod.dll_src_exists(cfg) if dll_name else False
        json_ok       = mod.get_json_status(cfg, game_path) if dll_name else None

        # ── حالة عامة ────────────────────────────────────────────────────────
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

        # ── رأس البطاقة ───────────────────────────────────────────────────────
        hdr_row = QHBoxLayout()
        title   = "🔌  BepInEx + XUnity AutoTranslator" if is_xunity_mode else "🔌  BepInEx Runtime Mod"
        ttl = QLabel(title)
        ttl.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {c['primary']};"
            " background: transparent; border: none;"
        )
        st_lbl = QLabel(status_text)
        st_lbl.setStyleSheet(
            f"color: {status_color}; font-size: 11px;"
            " background: transparent; border: none;"
        )
        hdr_row.addWidget(ttl)
        hdr_row.addStretch()
        hdr_row.addWidget(st_lbl)
        cl.addLayout(hdr_row)

        # ── حالة مكونات الحزمة ───────────────────────────────────────────────
        def _status_line(icon, text, color):
            lbl = QLabel(f"{icon} {text}")
            lbl.setStyleSheet(
                f"color: {color}; font-size: 10px;"
                " background: transparent; border: none;"
            )
            cl.addWidget(lbl)

        # مصدر BepInEx
        if has_bepinex_src:
            _status_line("✓", f"BepInEx — جاهز ({src_label})", c["green"])
        else:
            _status_line("✗", "BepInEx — غير موجود في mods/_bepinex_base/", c["accent"])

        if is_xunity_mode:
            # Method 2: أظهر حالة XUnity + ArabicFontFixer + الكاش
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
            # Method 1: أظهر حالة DLL + JSON
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

        # ── أزرار الإجراءات ───────────────────────────────────────────────────
        def _mini_btn(label, color_key, signal_emitter):
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
            btn.clicked.connect(signal_emitter)
            return btn

        if not game_path:
            hint = QLabel("حدد مسار اللعبة من «تعديل الإعدادات» لتتمكن من التثبيت")
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color: {c['muted']}; font-size: 11px; background: transparent; border: none;")
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
                inst_btn.clicked.connect(
                    lambda: self.bepinex_install_requested.emit(self._game_id, game_path)
                )
                row1.addWidget(inst_btn)

            elif installed is True:
                if is_xunity_mode:
                    # Method 2: تحديث plugins + تصدير translations.txt + إلغاء
                    row1.addWidget(_mini_btn(
                        "🔄  تحديث الترجمات", "teal",
                        lambda: self.bepinex_update_requested.emit(self._game_id, game_path)
                    ))
                    # زر أولوية المودلات — يُفعَّل للدمج الهرمي عند "كل النماذج"
                    row1.addWidget(_mini_btn(
                        "🎯  أولوية المودلات", "purple",
                        lambda: self.model_priority_requested.emit(self._game_id)
                    ))
                    row1.addWidget(_mini_btn(
                        "🔄  تحديث plugins", "blue",
                        lambda: self.bepinex_install_requested.emit(self._game_id, game_path)
                    ))
                    row1.addWidget(_mini_btn(
                        "🗑️  إلغاء التثبيت", "accent",
                        lambda: self.bepinex_uninstall_requested.emit(self._game_id, game_path)
                    ))
                else:
                    # Method 1: الأزرار الكاملة
                    row1.addWidget(_mini_btn(
                        "📥  استيراد الترجمات", "blue",
                        lambda: self.bepinex_import_requested.emit(self._game_id, game_path)
                    ))
                    row1.addWidget(_mini_btn(
                        "📁  استيراد من مجلد", "muted",
                        lambda: self.bepinex_import_from_requested.emit(self._game_id, game_path, "")
                    ))
                    row1.addWidget(_mini_btn(
                        "🔄  تحديث الترجمات", "teal",
                        lambda: self.bepinex_update_requested.emit(self._game_id, game_path)
                    ))
                    row1.addWidget(_mini_btn(
                        "🎯  أولوية المودلات", "purple",
                        lambda: self.model_priority_requested.emit(self._game_id)
                    ))
                    row1.addWidget(_mini_btn(
                        "🗑️  إلغاء التثبيت", "accent",
                        lambda: self.bepinex_uninstall_requested.emit(self._game_id, game_path)
                    ))

            row1.addStretch()
            cl.addLayout(row1)

            # ── خادم الترجمة الفورية ──────────────────────────────────────────
            if installed is True:
                proxy   = self._proxy_server
                p_run   = proxy is not None and proxy.is_running
                p_this  = p_run and proxy.game_name == self._game_id
                p_other = p_run and not p_this

                row_srv = QHBoxLayout(); row_srv.setSpacing(8)

                if p_this:
                    srv_badge = QLabel("🟢  خادم الترجمة الفورية يعمل")
                    srv_badge.setStyleSheet(
                        f"color: {c['green']}; font-size: 11px;"
                        " background: transparent; border: none; font-weight: bold;"
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
                    stop_btn.clicked.connect(
                        lambda: self.proxy_server_toggle_requested.emit(self._game_id, cfg.get("name", self._game_id))
                    )
                    row_srv.addWidget(stop_btn)
                else:
                    if p_other:
                        other_lbl = QLabel(f"⚠️  الخادم يعمل للعبة «{proxy.game_name}»")
                        other_lbl.setStyleSheet(
                            f"color: {c['yellow']}; font-size: 10px;"
                            " background: transparent; border: none;"
                        )
                        row_srv.addWidget(other_lbl)
                    lbl_start = "▶  تشغيل الخادم — شغّله قبل فتح اللعبة" if is_xunity_mode else "▶  تشغيل خادم الترجمة الفورية"
                    start_btn = QPushButton(lbl_start)
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
                    start_btn.clicked.connect(
                        lambda: self.proxy_server_toggle_requested.emit(self._game_id, cfg.get("name", self._game_id))
                    )
                    row_srv.addWidget(start_btn)

                row_srv.addStretch()
                cl.addLayout(row_srv)

            # ── صف أزرار الجمع (عند غياب ملفات المصدر) ──────────────────────
            row2 = QHBoxLayout(); row2.setSpacing(6)
            has_collect = False
            if not has_bepinex_src and bepinex_in_game:
                row2.addWidget(_mini_btn(
                    "📦  جمع BepInEx من اللعبة", "muted",
                    lambda: self.bepinex_collect_requested.emit(self._game_id, game_path)
                ))
                has_collect = True
            if not has_bepinex_src:
                row2.addWidget(_mini_btn(
                    "📁  جمع من مجلد آخر", "muted",
                    lambda: self.bepinex_collect_from_requested.emit(self._game_id, game_path)
                ))
                has_collect = True
            if dll_name and not dll_ok and installed is True:
                row2.addWidget(_mini_btn(
                    "📋  نسخ DLL للمشروع", "muted",
                    lambda: self.bepinex_copy_dll_requested.emit(self._game_id, game_path)
                ))
                has_collect = True
            if has_collect:
                row2.addStretch()
                cl.addLayout(row2)

        lay.addWidget(card)

    def _render_package_card(self, lay, cfg: dict):
        """بطاقة تحميل/تثبيت/إلغاء الترجمة."""
        from games.translation_package import TranslationPackage
        c   = theme.c
        pkg = TranslationPackage()

        has_pkg       = pkg.has_files(self._game_id)
        game_path     = cfg.get("game_path", "")
        registry_info = getattr(self, '_registry_info', {}).get(self._game_id)
        registry_loaded = getattr(self, '_registry_loaded', False)

        # Hide card only when: no local files AND registry already loaded with no entry
        if not has_pkg and registry_loaded and not registry_info:
            return

        # Determine local install status
        if has_pkg and game_path:
            status = pkg.get_status(self._game_id, game_path)
        elif has_pkg:
            status = None
        else:
            status = "no_local"

        # Labels
        if status is True:
            status_text  = "● مُثبَّتة"
            status_color = c["green"]
        elif status is False:
            status_text  = "● غير مُثبَّتة"
            status_color = c["accent"]
        elif status == "no_local" and registry_info:
            status_text  = "● متاحة للتحميل"
            status_color = c["blue"]
        elif status == "no_local" and not registry_info:
            status_text  = "● جارٍ التحقق…"
            status_color = c["muted"]
        else:
            status_text  = "● حدد مسار اللعبة أولاً"
            status_color = c["yellow"]

        card = self._card()
        cl   = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(10)

        hdr_row = QHBoxLayout()
        ttl = QLabel("📦  حزمة الترجمة")
        ttl.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {c['primary']};"
            " background: transparent; border: none;"
        )
        st_lbl = QLabel(status_text)
        st_lbl.setStyleSheet(
            f"color: {status_color}; font-size: 11px;"
            " background: transparent; border: none;"
        )
        hdr_row.addWidget(ttl)
        hdr_row.addStretch()
        hdr_row.addWidget(st_lbl)
        cl.addLayout(hdr_row)

        # Progress bar (hidden by default — shown during download)
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
        self._dl_lbl.setStyleSheet(
            f"color: {c['muted']}; font-size: 10px; background: transparent; border: none;"
        )
        cl.addWidget(self._dl_lbl)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        if status == "no_local" and registry_info:
            size_mb = registry_info.get("size_mb", 0)
            size_txt = f"  ({size_mb} MB)" if size_mb else ""
            dl_btn = QPushButton(f"⬇️  تحميل الترجمة{size_txt}")
            dl_btn.setFixedHeight(36)
            dl_btn.setCursor(QCursor(Qt.PointingHandCursor))
            dl_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {c['blue']}; color: #fff;
                    border: none; border-radius: 8px;
                    font-weight: bold; font-size: 13px; padding: 0 18px;
                }}
                QPushButton:hover {{ background: #1565c0; }}
            """)
            dl_btn.clicked.connect(
                lambda: self.download_requested.emit(self._game_id)
            )
            btn_row.addWidget(dl_btn)

        elif status == "no_local" and not registry_info:
            retry_btn = QPushButton("🔄  تحقق من الترجمات المتاحة")
            retry_btn.setFixedHeight(36)
            retry_btn.setCursor(QCursor(Qt.PointingHandCursor))
            retry_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {c['muted']};
                    border: 1px solid {c['border']}; border-radius: 8px;
                    font-size: 12px; padding: 0 18px;
                }}
                QPushButton:hover {{ color: {c['primary']}; border-color: {c['primary']}; }}
            """)
            retry_btn.clicked.connect(self.check_registry_requested)
            btn_row.addWidget(retry_btn)

        elif status is False:
            inst_btn = QPushButton("✅  تثبيت الترجمة")
            inst_btn.setFixedHeight(36)
            inst_btn.setCursor(QCursor(Qt.PointingHandCursor))
            inst_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {c['green']}; color: #fff;
                    border: none; border-radius: 8px;
                    font-weight: bold; font-size: 13px; padding: 0 18px;
                }}
                QPushButton:hover {{ background: #2e7d32; }}
            """)
            inst_btn.clicked.connect(
                lambda: self.install_requested.emit(self._game_id, game_path)
            )
            btn_row.addWidget(inst_btn)

        elif status is True:
            uninst_btn = QPushButton("🗑️  إلغاء التثبيت")
            uninst_btn.setFixedHeight(36)
            uninst_btn.setCursor(QCursor(Qt.PointingHandCursor))
            uninst_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {c['accent']};
                    border: 1px solid {c['accent']}; border-radius: 8px;
                    font-weight: bold; font-size: 12px; padding: 0 18px;
                }}
                QPushButton:hover {{ background: {c['accent']}; color: #fff; }}
            """)
            uninst_btn.clicked.connect(
                lambda: self.uninstall_requested.emit(self._game_id, game_path)
            )
            btn_row.addWidget(uninst_btn)

        elif status is None:
            hint = QLabel("حدد مسار اللعبة من «تعديل الإعدادات» لتتمكن من التثبيت")
            hint.setWordWrap(True)
            hint.setStyleSheet(
                f"color: {c['muted']}; font-size: 11px;"
                " background: transparent; border: none;"
            )
            cl.addWidget(hint)

        btn_row.addStretch()
        cl.addLayout(btn_row)

        # Version label
        ver = registry_info.get("version", "1.0") if registry_info else "1.0"
        lbl_row = QLabel(f"الإصدار: v{ver}")
        lbl_row.setStyleSheet(
            f"color: {c['muted']}; font-size: 10px;"
            " background: transparent; border: none;"
        )
        cl.addWidget(lbl_row)

        lay.addWidget(card)

    def _card(self) -> QFrame:
        c = theme.c
        f = QFrame()
        f.setStyleSheet(f"""
            QFrame {{
                background: {c['card']};
                border: 1px solid {c['border']};
                border-radius: 10px;
            }}
        """)
        return f

    # ── Launch / close game ───────────────────────────────────────────────────

    @staticmethod
    def _is_process_running(process_name: str) -> bool:
        """يفحص ما إذا كانت عملية بهذا الاسم تعمل حالياً (لا حساسية لحالة الأحرف)."""
        if not process_name:
            return False
        try:
            import psutil
        except ImportError:
            return False
        target = process_name.lower()
        try:
            for proc in psutil.process_iter(attrs=["name"]):
                try:
                    if (proc.info.get("name") or "").lower() == target:
                        return True
                except Exception:
                    continue
        except Exception:
            return False
        return False

    def _refresh_launch_btn(self):
        """يحدّث نص وألوان زر تشغيل/إغلاق اللعبة بناءً على حالة العملية."""
        btn = self._btn_launch_game
        if btn is None:
            return
        process_name = (self._game_cfg or {}).get("process_name", "").strip()
        if not process_name:
            return
        c = theme.c
        running = self._is_process_running(process_name)
        if running:
            label = "إغلاق اللعبة"
            icon  = "⏹"
            color = c.get("accent", "#e94560")    # أحمر = تحذيري
        else:
            label = "تشغيل اللعبة"
            icon  = "🎮"
            color = c.get("green", "#2e7d32")
        btn.setText(f"{icon}  {label}")
        btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0,0,0,38);
                color: {color};
                border: 1px solid {color};
                border-radius: 8px;
                font-weight: bold;
                padding: 0 16px;
                text-align: left;
            }}
            QPushButton:hover {{
                background: {color};
                color: #fff;
            }}
        """)

    def _on_launch_clicked(self):
        """تشغيل اللعبة أو إغلاقها حسب حالتها الحالية."""
        cfg = self._game_cfg or {}
        process_name = cfg.get("process_name", "").strip()
        game_path    = cfg.get("game_path", "").strip()
        if not process_name or not game_path:
            QMessageBox.warning(
                self, "إعداد ناقص",
                "اسم العملية أو مسار اللعبة غير محدّد — "
                "حدّدهما من «تعديل الإعدادات»."
            )
            return

        if self._is_process_running(process_name):
            # ── إغلاق ─────────────────────────────────────────────────────────
            if QMessageBox.question(
                self, "تأكيد الإغلاق",
                f"إغلاق «{process_name}»؟\n"
                "أي تقدّم لم يُحفَظ سيُفقد.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) != QMessageBox.Yes:
                return
            self._terminate_process(process_name)
            QTimer.singleShot(800, self._refresh_launch_btn)
            return

        # ── تشغيل ─────────────────────────────────────────────────────────────
        # الأولوية:
        #   1) Steam URL لو appid موجود (يتعامل مع Steam API init بشكل صحيح)
        #      → لو فيه نسخ متعدّدة، Steam يعرض picker (المستخدم يفعّل "Always use this option")
        #   2) exe مباشر فقط لو prefer_direct_launch=true أو لا يوجد appid
        appid = self._find_steam_appid(game_path) or (cfg.get("steam_appid") or "").strip()
        prefer_direct = bool(cfg.get("prefer_direct_launch"))
        direct_exe = os.path.join(game_path, process_name)
        has_direct_exe = os.path.isfile(direct_exe)
        # Direct فقط لو الإعداد يطلبها صراحةً أو لا يوجد Steam appid
        use_direct = has_direct_exe and (prefer_direct or not appid)

        try:
            if use_direct:
                # تشغيل مباشر — يضمن النسخة المحدَّدة في game_path
                os.startfile(direct_exe)
            elif appid:
                # Steam URL — يفتح Steam إن لم يكن يعمل، ثم يبدأ اللعبة
                os.startfile(f"steam://run/{appid}")
            else:
                # ليست لعبة Steam → نحتاج exe في موقع متوقّع
                exe_path = direct_exe if has_direct_exe else ""
                if not exe_path:
                    # جرّب موقع شائع: <game_path>/<game_name>/Binaries/Win64/<exe>
                    game_name = (cfg.get("name", "") or "").strip()
                    candidates = [
                        os.path.join(game_path, game_name, "Binaries", "Win64", process_name),
                        os.path.join(game_path, game_name.replace(" ", ""), "Binaries", "Win64", process_name),
                    ]
                    for c_path in candidates:
                        if os.path.isfile(c_path):
                            exe_path = c_path
                            break
                if not exe_path or not os.path.isfile(exe_path):
                    QMessageBox.warning(
                        self, "الملف غير موجود",
                        f"لم أجد ملف التشغيل:\n{process_name}\n\n"
                        f"بحثت في:\n  {game_path}\n\n"
                        "تحقق من مسار اللعبة في «تعديل الإعدادات»."
                    )
                    return
                os.startfile(exe_path)
        except Exception as e:
            QMessageBox.critical(
                self, "فشل التشغيل",
                f"تعذّر تشغيل اللعبة:\n{e}"
            )
            return
        # تأخير التحديث: Steam URL أبطأ، التشغيل المباشر أسرع
        delay = 1200 if use_direct else (3000 if appid else 1200)
        QTimer.singleShot(delay, self._refresh_launch_btn)

    @staticmethod
    def _find_steam_appid(game_path: str) -> str:
        """يستنتج appid اللعبة من Steam.
        المراحل (بالترتيب):
          1) steam_appid.txt في مجلد اللعبة (بعض المطوّرين يضعونه)
          2) مطابقة installdir في appmanifest_*.acf داخل steamapps/
        يُرجع '' إذا لم يجد.
        """
        if not game_path or not os.path.isdir(game_path):
            return ""

        # 1) steam_appid.txt مباشرة في مجلد اللعبة
        candidate = os.path.join(game_path, "steam_appid.txt")
        if os.path.isfile(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    appid = f.read().strip()
                if appid.isdigit():
                    return appid
            except Exception:
                pass

        # 2) ابحث عن مجلد steamapps في المسار الأبوي
        # game_path نموذجي: .../Steam/steamapps/common/<InstallDir>
        norm = os.path.normpath(game_path)
        parts = norm.split(os.sep)
        try:
            idx = next(i for i, p in enumerate(parts) if p.lower() == "steamapps")
        except StopIteration:
            return ""
        steamapps_dir = os.sep.join(parts[: idx + 1])
        install_dir   = parts[-1]   # اسم مجلد اللعبة (Flotsam)
        if not os.path.isdir(steamapps_dir):
            return ""

        # ابحث في كل appmanifest_*.acf عن installdir المطابق
        try:
            for fname in os.listdir(steamapps_dir):
                if not (fname.startswith("appmanifest_") and fname.endswith(".acf")):
                    continue
                try:
                    with open(os.path.join(steamapps_dir, fname),
                              "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except Exception:
                    continue
                # ابحث عن installdir "..." (case-insensitive)
                import re as _re
                m = _re.search(
                    r'"installdir"\s*"([^"]+)"', content, _re.IGNORECASE
                )
                if not m:
                    continue
                if m.group(1).strip().lower() == install_dir.lower():
                    # appid من اسم الملف: appmanifest_<APPID>.acf
                    appid = fname[len("appmanifest_"): -len(".acf")]
                    if appid.isdigit():
                        return appid
        except Exception:
            pass
        return ""

    @staticmethod
    def _terminate_process(process_name: str):
        """ينهي كل العمليات بهذا الاسم بأمان (terminate ثم kill عند الحاجة)."""
        try:
            import psutil
        except ImportError:
            return
        target = process_name.lower()
        victims = []
        try:
            for proc in psutil.process_iter(attrs=["name"]):
                try:
                    if (proc.info.get("name") or "").lower() == target:
                        victims.append(proc)
                except Exception:
                    continue
        except Exception:
            return
        for p in victims:
            try:
                p.terminate()
            except Exception:
                pass
        # امهلهم 3 ثوان للإغلاق النظيف، ثم اقتل المتعنّت
        try:
            _, alive = psutil.wait_procs(victims, timeout=3)
            for p in alive:
                try:
                    p.kill()
                except Exception:
                    pass
        except Exception:
            pass


# ── Log panel ─────────────────────────────────────────────────────────────────

class LogPanel(QWidget):
    """لوح سجل الترجمة والبروكسي — قابل للتمدد عبر QSplitter."""

    log_message = Signal(str)   # thread-safe: يُستدعى من خيط البروكسي
    stats_signal = Signal(dict) # thread-safe: لتحديث عدّاد الإحصاءات

    def __init__(self, parent=None):
        super().__init__(parent)
        c = theme.c
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 8)
        lay.setSpacing(4)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("📋  سجل الترجمة والبروكسي")
        title.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {c['muted']};"
            " background: transparent; border: none;"
        )
        clear_btn = QPushButton("مسح")
        clear_btn.setFixedSize(48, 22)
        clear_btn.setCursor(QCursor(Qt.PointingHandCursor))
        clear_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {c['muted']};"
            f" border: 1px solid {c['border']}; border-radius: 4px; font-size: 10px; }}"
            f"QPushButton:hover {{ color: {c['primary']}; border-color: {c['primary']}; }}"
        )
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(clear_btn)
        lay.addLayout(hdr)

        # شريط إحصاءات الترجمة الفورية — يُظهر العدّ والمعدل قبل الـ log
        self._stats_bar = QFrame()
        self._stats_bar.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']};"
            f"          border-radius: 6px; padding: 4px 8px; }}"
            f"QLabel  {{ background: transparent; border: none; font-size: 11px; }}"
        )
        sb_lay = QHBoxLayout(self._stats_bar)
        sb_lay.setContentsMargins(8, 2, 8, 2)
        sb_lay.setSpacing(14)

        self._pending_lbl = QLabel("⏳  في الانتظار: 0")
        self._pending_lbl.setStyleSheet(f"color: {c['accent']};")
        self._rate_lbl    = QLabel("⚡  المعدل: 0/ث")
        self._rate_lbl.setStyleSheet(f"color: {c['primary']};")
        self._engine_lbl  = QLabel("🔄  مترجَم: 0")
        self._engine_lbl.setStyleSheet(f"color: {c['secondary']};")
        self._cache_lbl   = QLabel("📦  من الكاش: 0")
        self._cache_lbl.setStyleSheet(f"color: {c['secondary']};")
        self._unchanged_lbl = QLabel("⏭  بلا تغيير: 0")
        self._unchanged_lbl.setStyleSheet(f"color: {c['muted']};")
        self._unchanged_lbl.setToolTip(
            "نصوص أعادها الـ AI كما هي (أسماء أعلام، أرقام، اختصارات).\n"
            "تُحفظ تلقائياً لتجنّب استدعاء الـ AI لها مرة أخرى."
        )
        # عدّاد الفشل + زر عرض التفاصيل
        self._failed_lbl = QLabel("❌  فشل: 0")
        self._failed_lbl.setStyleSheet(f"color: {c.get('accent', '#e94560')};")
        self._failed_lbl.setCursor(QCursor(Qt.PointingHandCursor))
        self._failed_lbl.setToolTip(
            "نصوص فشل المحرّك في ترجمتها.\nاضغط لعرض آخر الإخفاقات وأسبابها."
        )
        self._failed_lbl.mousePressEvent = lambda ev: self._show_recent_failures()

        sb_lay.addWidget(self._pending_lbl)
        sb_lay.addWidget(self._rate_lbl)
        sb_lay.addWidget(self._engine_lbl)
        sb_lay.addWidget(self._cache_lbl)
        sb_lay.addWidget(self._unchanged_lbl)
        sb_lay.addWidget(self._failed_lbl)
        sb_lay.addStretch()
        lay.addWidget(self._stats_bar)

        # شريط ضوابط الترجمة — يُطبَّق فوراً (بدون إعادة تشغيل الخادم)
        self._ctrl_bar = QFrame()
        self._ctrl_bar.setStyleSheet(
            f"QFrame    {{ background: {c['card']}; border: 1px solid {c['border']};"
            f"             border-radius: 6px; padding: 4px 8px; }}"
            f"QLabel    {{ background: transparent; border: none; font-size: 11px;"
            f"             color: {c['secondary']}; }}"
            f"QCheckBox {{ background: transparent; border: none; font-size: 11px;"
            f"             color: {c['secondary']}; }}"
            f"QSpinBox  {{ background: {c['bg']}; color: {c['secondary']};"
            f"             border: 1px solid {c['border']}; border-radius: 4px;"
            f"             padding: 2px 4px; font-size: 11px; max-width: 70px; }}"
        )
        cb_lay = QHBoxLayout(self._ctrl_bar)
        cb_lay.setContentsMargins(8, 2, 8, 2)
        cb_lay.setSpacing(14)

        # الوضع الحالي يُعرَض كـ label للقراءة فقط — اختيار الوضع يتم عبر
        # حوار التأكيد قبل تشغيل الخادم (نتجنّب الازدواجية)
        tag_lbl = QLabel("🏷  وضع التاقات:")
        self._tag_mode_label = QLabel("— غير محدد —")
        self._tag_mode_label.setStyleSheet(
            f"color: {c['accent']}; background: transparent;"
            f" font-size: 11px; font-weight: bold; padding: 0 8px;"
        )

        # زر تحرير قائمة التاقات المحمية — 🏷 emoji يظهر في كل الخطوط
        self._tag_config_btn = QPushButton("🏷  قائمة")
        self._tag_config_btn.setFixedHeight(26)
        self._tag_config_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._tag_config_btn.setToolTip(
            "تحرير قائمة التاقات المحمية\n"
            "أضف تاقات مخصصة لتُحمى مع Tiered/Bulletproof"
        )
        self._tag_config_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {c['secondary']};"
            f"               border: 1px solid {c['border']}; border-radius: 4px;"
            f"               padding: 0 10px; font-size: 11px; font-weight: 500; }}"
            f"QPushButton:hover {{ color: white; background: {c['accent']};"
            f"                     border-color: {c['accent']}; }}"
        )
        self._tag_config_btn.clicked.connect(self._on_open_tag_config)

        timeout_lbl = QLabel("⏱  مهلة الـ AI (ث):")
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(10, 600)
        self._timeout_spin.setValue(60)
        self._timeout_spin.setSingleStep(10)
        self._timeout_spin.setToolTip(
            "المهلة بالثواني قبل اعتبار الترجمة فاشلة.\n"
            "زِدها إذا كان النموذج بطيئاً (نموذج كبير، CPU، الخ).\n"
            "تُطبَّق فوراً على الطلبات الجديدة."
        )
        self._timeout_spin.valueChanged.connect(self._on_timeout_changed)

        cb_lay.addWidget(tag_lbl)
        cb_lay.addWidget(self._tag_mode_label)
        cb_lay.addWidget(self._tag_config_btn)
        cb_lay.addStretch()
        cb_lay.addWidget(timeout_lbl)
        cb_lay.addWidget(self._timeout_spin)
        lay.addWidget(self._ctrl_bar)

        # ⭐ شريط فلتر ديناميكي للسجل
        self._filter_bar = QFrame()
        self._filter_bar.setStyleSheet(
            f"QFrame    {{ background: {c['card']}; border: 1px solid {c['border']};"
            f"             border-radius: 6px; padding: 4px 8px; }}"
            f"QLabel    {{ background: transparent; border: none; font-size: 11px;"
            f"             color: {c['secondary']}; }}"
            f"QCheckBox {{ background: transparent; border: none; font-size: 10px;"
            f"             color: {c['secondary']}; spacing: 4px; }}"
            f"QLineEdit {{ background: {c['bg']}; color: {c['primary']};"
            f"             border: 1px solid {c['border']}; border-radius: 4px;"
            f"             padding: 2px 6px; font-size: 11px; }}"
        )
        fb_lay = QHBoxLayout(self._filter_bar)
        fb_lay.setContentsMargins(8, 2, 8, 2)
        fb_lay.setSpacing(10)

        fb_lay.addWidget(QLabel("🔎  فلتر:"))

        # checkboxes: ما يُخفى من السجل
        self._flt_show_translated = QCheckBox("ترجمات جديدة")
        self._flt_show_translated.setChecked(True)
        self._flt_show_translated.setToolTip("النصوص التي يترجمها الـ AI لأول مرة")

        self._flt_show_cache = QCheckBox("من الكاش")
        self._flt_show_cache.setChecked(False)
        self._flt_show_cache.setToolTip("ترجمات استُردّت من الكاش بدون استدعاء AI")

        self._flt_show_skip = QCheckBox("متخطّاة")
        self._flt_show_skip.setChecked(False)
        self._flt_show_skip.setToolTip("نصوص تطابق skip_patterns (Nexa Bold...) أو محرف فاضل")

        self._flt_show_failed = QCheckBox("فشل")
        self._flt_show_failed.setChecked(True)
        self._flt_show_failed.setToolTip("ترجمات فشلت")

        self._flt_show_unchanged = QCheckBox("بلا تغيير")
        self._flt_show_unchanged.setChecked(False)
        self._flt_show_unchanged.setToolTip("نصوص رجعت كما هي (أرقام، أعلام، …)")

        self._flt_show_other = QCheckBox("أخرى")
        self._flt_show_other.setChecked(False)
        self._flt_show_other.setToolTip("سطور لا تطابق أي فئة معروفة (تشخيص، أحداث، …)")

        for cb in (self._flt_show_translated, self._flt_show_cache, self._flt_show_skip,
                   self._flt_show_failed, self._flt_show_unchanged, self._flt_show_other):
            cb.toggled.connect(self._reapply_filter)
            fb_lay.addWidget(cb)

        fb_lay.addStretch(1)

        # بحث نصي
        self._flt_search = QLineEdit()
        self._flt_search.setPlaceholderText("ابحث في السجل…")
        self._flt_search.setFixedWidth(180)
        self._flt_search.textChanged.connect(self._reapply_filter)
        fb_lay.addWidget(self._flt_search)

        lay.addWidget(self._filter_bar)

        self._txt = QPlainTextEdit()
        self._txt.setReadOnly(True)
        self._txt.setMaximumBlockCount(600)
        self._txt.setStyleSheet(
            f"QPlainTextEdit {{"
            f"  background: {c['card']}; color: {c['secondary']};"
            f"  border: 1px solid {c['border']}; border-radius: 6px;"
            f"  font-family: 'Consolas', 'Courier New', monospace; font-size: 10px;"
            f"  padding: 6px;"
            f"}}"
        )
        lay.addWidget(self._txt)

        # buffer كل الـ logs (للفلترة الديناميكية)
        self._all_logs: list[str] = []

        self.setStyleSheet(
            f"LogPanel {{ background: {c['surface']};"
            f" border-top: 1px solid {c['border']}; }}"
        )

        def _clear_all():
            self._txt.clear()
            self._all_logs.clear()
        clear_btn.clicked.connect(_clear_all)
        self.log_message.connect(self._append)
        self.stats_signal.connect(self._on_stats)

        # مؤقّت يُحدّث المعدل كل نصف ثانية حتى لو لم تصل ترجمات جديدة
        self._proxy_ref = None
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(500)
        self._stats_timer.timeout.connect(self._poll_stats)
        self._stats_timer.start()

    def _append(self, msg: str):
        # احفظ في buffer كل الـ logs (للفلترة الديناميكية)
        self._all_logs.append(msg)
        if len(self._all_logs) > 2000:
            self._all_logs = self._all_logs[-1500:]
        # طبّق الفلتر — أضِف فقط لو يطابق
        if self._line_matches_filter(msg):
            self._txt.appendPlainText(msg)
            sb = self._txt.verticalScrollBar()
            sb.setValue(sb.maximum())

    def append(self, msg: str):
        """واجهة عامة — آمنة من أي خيط (تستخدم Signal داخلياً)."""
        self.log_message.emit(msg)

    # ── تصنيف وفلترة سطور السجل ─────────────────────────────────────────────

    def _classify_log_line(self, msg: str) -> str:
        """يصنّف السطر إلى أحد: translated, cache, skip, failed, unchanged, other.
        مطابقة دقيقة لرموز proxy_server.py."""

        # نصوص محجوبة (skip_patterns / مُمنَع / معروف فاشل / تخطّي)
        # ⚠ افحص قبل "ترجمة جديدة" لأنها قد تحوي ⟶ كذلك
        if any(t in msg for t in (
            "🚫", "⏭",
            "مُمنَع", "مُمنع", "ممنوع",
            "معروف فاشل", "معروف فاضل",
            "تخطّى", "تخطى", "تخطّي",
            "skip_pattern", "skipped",
        )):
            return "skip"

        # فشل
        if any(t in msg for t in (
            "❌", "✗", "⚠",
            "fail", "Fail",
            "تجاوز المهلة", "timeout", "Timeout",
            "exception", "Exception",
            "بلا ردّ", "بلا رد",
            "queue مليان",
        )):
            return "failed"

        # كاش / مرجع يدوي / استرجاع
        # ملاحظة: البروكسي لا يطبع log عند SQLite cache hit (هي صامتة).
        # لكن 📖 يدل على "يدوي من translations.txt" — استرجاع بدون استدعاء AI
        # → نصنّفه ضمن "كاش" لأنه ليس ترجمة جديدة فعلية.
        if any(t in msg for t in (
            "📖", "📦", "🗄",
            "يدوي:", "يدوي ⟶",
            "من الكاش", "cache hit", "[cache]", "[Cache]",
        )):
            return "cache"

        # بلا تغيير
        if any(t in msg for t in ("بلا تغيير", "unchanged", "نص كما هو")):
            return "unchanged"

        # جدولة خلفية (long text async) — اعتبرها "translated" لأنها قيد المعالجة
        if "⏳" in msg or "جدولة خلفية" in msg:
            return "translated"

        # ترجمة AI جديدة — البروكسي يطبع `text ⟶ arabic` (سطر 151)
        # هذه فقط بعد cache miss + استدعاء AI ناجح.
        if any(t in msg for t in (
            "⟶", "→", "⇨", "->",
            "🔄", "✓",
            "translated", "[AI]", "[Ollama]",
        )):
            return "translated"

        return "other"

    def _line_matches_filter(self, msg: str) -> bool:
        # filter checkboxes غير مرئية بعد (init) → اقبل كل شيء
        if not hasattr(self, "_flt_show_translated"):
            return True
        category = self._classify_log_line(msg)
        category_visible = {
            "translated": self._flt_show_translated.isChecked(),
            "cache":      self._flt_show_cache.isChecked(),
            "skip":       self._flt_show_skip.isChecked(),
            "failed":     self._flt_show_failed.isChecked(),
            "unchanged":  self._flt_show_unchanged.isChecked(),
            "other":      self._flt_show_other.isChecked(),
        }.get(category, True)
        if not category_visible:
            return False
        # بحث نصي
        q = self._flt_search.text().strip()
        if q and q.lower() not in msg.lower():
            return False
        return True

    def _reapply_filter(self):
        """يعيد رسم السجل بناءً على الفلتر الحالي. يبقي scrollbar في النهاية."""
        self._txt.clear()
        for line in self._all_logs:
            if self._line_matches_filter(line):
                self._txt.appendPlainText(line)
        sb = self._txt.verticalScrollBar()
        sb.setValue(sb.maximum())

    def attach_proxy(self, proxy):
        """يربط البروكسي لتحديث الإحصاءات وعرض الإعدادات الحالية."""
        self._proxy_ref = proxy
        if proxy:
            proxy.stats_callback = self.stats_signal.emit
            self._on_stats(proxy.get_stats())
            # نُحدّث label الوضع
            self._refresh_tag_mode_label()
            self._timeout_spin.blockSignals(True)
            self._timeout_spin.setValue(int(proxy.get_timeout()))
            self._timeout_spin.blockSignals(False)
        else:
            self._on_stats({"pending": 0, "engine_count": 0, "cache_count": 0, "rate_per_sec": 0})

    def _refresh_tag_mode_label(self):
        """يُحدّث label الوضع الحالي. يفضّل الفلتر العام (config.json)
        ويعود للبروكسي لو لم يكن متاحاً."""
        mode = None
        # 1) اقرأ من الفلتر العام (الأولوية)
        try:
            from engine.filtered_translator import get_global_tag_mode
            mode = get_global_tag_mode()
        except Exception:
            mode = None
        # 2) fallback للبروكسي
        if not mode and self._proxy_ref and hasattr(self._proxy_ref, "get_tag_mode"):
            mode = self._proxy_ref.get_tag_mode()
        if mode:
            mode_display = {
                "inline":      "🏷 Inline",
                "strip":       "🔒 Strip",
                "tiered":      "🎯 Tiered",
                "bulletproof": "🛡 Bulletproof",
            }.get(mode, mode)
            self._tag_mode_label.setText(mode_display)
        else:
            self._tag_mode_label.setText("— غير محدد —")

    def _poll_stats(self):
        if self._proxy_ref and self._proxy_ref.is_running:
            self._on_stats(self._proxy_ref.get_stats())
            self._refresh_tag_mode_label()

    def _on_open_tag_config(self):
        """يفتح حوار تحرير قائمة التاقات المحمية (غير-modal)."""
        from gui.qt.dialogs.tag_config_dialog import TagConfigDialog
        # إن وُجد حوار مفتوح، نُبرزه بدل فتح ثانٍ
        if getattr(self, "_tag_cfg_dlg", None) is not None:
            try:
                if self._tag_cfg_dlg.isVisible():
                    self._tag_cfg_dlg.raise_()
                    self._tag_cfg_dlg.activateWindow()
                    return
            except RuntimeError:
                pass
        self._tag_cfg_dlg = TagConfigDialog(parent=self)
        self._tag_cfg_dlg.saved.connect(
            lambda: self.log_message.emit("✓ حُفظت إعدادات التاقات وأُعيد تحميل الفلتر")
        )
        # إعادة المرجع للـ None عند الإغلاق
        self._tag_cfg_dlg.finished.connect(lambda _r: setattr(self, "_tag_cfg_dlg", None))
        self._tag_cfg_dlg.show()
        self._tag_cfg_dlg.raise_()
        self._tag_cfg_dlg.activateWindow()

    def _on_timeout_changed(self, value: int):
        if not self._proxy_ref:
            return
        try:
            self._proxy_ref.set_timeout(float(value))
        except Exception:
            pass

    def _on_stats(self, s: dict):
        c = theme.c
        self._pending_lbl.setText(f"⏳  في الانتظار: {s.get('pending', 0)}")
        self._rate_lbl.setText(f"⚡  المعدل: {s.get('rate_per_sec', 0)}/ث")
        self._engine_lbl.setText(f"🔄  مترجَم: {s.get('engine_count', 0)}")
        self._cache_lbl.setText(f"📦  من الكاش: {s.get('cache_count', 0)}")
        self._unchanged_lbl.setText(f"⏭  بلا تغيير: {s.get('unchanged_count', 0)}")
        failed = s.get('failed_count', 0)
        consec = s.get('consecutive_failures', 0)
        if consec >= 5:
            # تنبيه عند تتابع الفشل
            label = f"🚨  فشل: {failed} (متتالية: {consec})"
            self._failed_lbl.setStyleSheet(
                f"color: white; background: {c.get('accent', '#e94560')};"
                f" padding: 2px 6px; border-radius: 3px; font-weight: bold;"
            )
        else:
            label = f"❌  فشل: {failed}"
            self._failed_lbl.setStyleSheet(
                f"color: {c.get('accent', '#e94560')}; background: transparent;"
            )
        self._failed_lbl.setText(label)

    def _show_recent_failures(self):
        """يعرض حواراً قابلاً للتوسيع بآخر الإخفاقات وأسبابها لتشخيص المشاكل."""
        if not self._proxy_ref or not hasattr(self._proxy_ref, "get_recent_failures"):
            return
        failures = self._proxy_ref.get_recent_failures()
        if not failures:
            QMessageBox.information(self, "آخر الإخفاقات",
                                    "🎉 لا توجد إخفاقات حالياً.")
            return
        lines = []
        for i, f in enumerate(reversed(failures), 1):
            # نُظهر النص الكامل بلا قطع — الحوار قابل للتوسيع الآن
            text = (f.get("text") or "").replace("\n", " ↵ ")
            reason = (f.get("reason") or "")
            modes = f.get("modes_tried", "")
            modes_str = f"  [tried: {modes}]" if modes else ""
            lines.append(f"{i}. النص: {text!r}\n   السبب: {reason}{modes_str}")
        body = "\n\n".join(lines)

        from PySide6.QtWidgets import QDialog, QTextEdit, QSizeGrip
        c = theme.c
        dlg = QDialog(self)
        dlg.setWindowTitle(f"آخر {len(failures)} إخفاق")
        # حوار قابل للتوسيع — حجم افتراضي مريح، حد أدنى صغير
        dlg.setMinimumSize(520, 380)
        dlg.resize(820, 600)
        dlg.setSizeGripEnabled(True)
        # نضيف min/max + close بدون استبدال الأعلام الافتراضية
        dlg.setWindowFlags(
            dlg.windowFlags()
            | Qt.WindowMinMaxButtonsHint
            | Qt.WindowCloseButtonHint
        )
        dlg.setStyleSheet(f"QDialog {{ background: {c['bg']}; }}")

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        # Header
        hdr = QLabel(f"🛈  يُعرض من الأحدث إلى الأقدم  •  {len(failures)} إخفاق")
        hdr.setStyleSheet(
            f"color: {c['primary']}; font-size: 13px; font-weight: bold;"
            " background: transparent; border: none;"
        )
        lay.addWidget(hdr)

        # Body — قابل للتمرير ويتمدّد مع النافذة
        body_widget = QTextEdit()
        body_widget.setReadOnly(True)
        body_widget.setLineWrapMode(QTextEdit.NoWrap)
        body_widget.setLayoutDirection(Qt.LeftToRight)
        body_widget.setPlainText(body)
        body_widget.setStyleSheet(
            f"QTextEdit {{ background: {c['surface']}; color: {c['primary']};"
            f"             border: 1px solid {c['border']}; border-radius: 6px;"
            f"             padding: 8px; font-family: Consolas, monospace;"
            f"             font-size: 12px; selection-background-color: {c['accent']}; }}"
        )
        lay.addWidget(body_widget, 1)

        # Footer
        foot = QHBoxLayout()
        foot.addStretch()
        copy_btn = QPushButton("📋  نسخ الكل")
        copy_btn.setCursor(QCursor(Qt.PointingHandCursor))
        copy_btn.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; color: {c['primary']};"
            f"               border: 1px solid {c['border']}; border-radius: 4px;"
            f"               padding: 6px 14px; }}"
            f"QPushButton:hover {{ background: {c['hover']}; color: white;"
            f"                     border-color: {c['accent']}; }}"
        )
        copy_btn.clicked.connect(lambda: (
            __import__("PySide6.QtWidgets", fromlist=["QApplication"])
            .QApplication.clipboard().setText(body)
        ))
        close_btn = QPushButton("إغلاق")
        close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        close_btn.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: white;"
            f"               border: none; border-radius: 4px; padding: 6px 18px;"
            f"               font-weight: bold; }}"
            f"QPushButton:hover {{ background: {c.get('teal', '#00d2ff')}; }}"
        )
        close_btn.clicked.connect(dlg.accept)
        foot.addWidget(copy_btn)
        foot.addSpacing(8)
        foot.addWidget(close_btn)
        lay.addLayout(foot)

        dlg.exec()


# ── Games page ────────────────────────────────────────────────────────────────

class GamesPage(QWidget):
    """صفحة إدارة الألعاب — قائمة يسار + تفاصيل يمين."""

    status_message = Signal(str)
    games_changed  = Signal()
    translation_updates_available = Signal(dict)   # {game_id: online_version}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine       = None
        self._registry_info: dict = {}
        self._cache        = None
        self._game_manager = None
        self._proxy_server = None
        self._items: dict[str, GameListItem] = {}
        self._selected_id: str | None = None
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        c   = theme.c
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_topbar())

        # Two-panel split
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Left: game list
        left = QFrame()
        left.setFixedWidth(300)
        self._left_panel = left
        left.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-right: 1px solid {c['border']}; }}"
        )
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(
            f"background: transparent; border: none;"
        )
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_lay = QVBoxLayout(self._list_widget)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(0)
        self._list_lay.addStretch()

        self._scroll.setWidget(self._list_widget)
        left_lay.addWidget(self._scroll)

        # Right: detail panel + log (vertical splitter)
        right = QWidget()
        self._right_panel = right
        right.setStyleSheet(f"background: {c['bg']};")

        self._detail = GameDetailPanel(right)
        self._detail.setStyleSheet(f"background: transparent;")
        self._detail.edit_requested.connect(self._on_edit)
        self._detail.delete_requested.connect(self._on_delete)
        self._detail.translate_requested.connect(self._on_translate)
        self._detail.iostore_requested.connect(self._open_iostore_wizard)
        self._detail.install_requested.connect(self._on_install)
        self._detail.uninstall_requested.connect(self._on_uninstall)
        self._detail.download_requested.connect(self._on_download)
        self._detail.download_install_requested.connect(self._on_download_install)
        self._detail.check_registry_requested.connect(self.retry_registry)
        self._detail.locres_requested.connect(self._on_locres_translate)
        self._detail.font_requested.connect(self._on_font_replace)
        self._detail.bepinex_install_requested.connect(self._on_bepinex_install)
        self._detail.bepinex_uninstall_requested.connect(self._on_bepinex_uninstall)
        self._detail.bepinex_update_requested.connect(self._on_bepinex_update)
        self._detail.foundation_install_requested.connect(self._on_foundation_install)
        self._detail.foundation_uninstall_requested.connect(self._on_foundation_uninstall)
        self._detail.foundation_update_requested.connect(self._on_foundation_update)
        self._detail.foundation_font_requested.connect(self._on_foundation_font)
        self._detail.manorlords_install_requested.connect(self._on_manorlords_install)
        self._detail.manorlords_uninstall_requested.connect(self._on_manorlords_uninstall)
        self._detail.manorlords_update_requested.connect(self._on_manorlords_update)
        self._detail.iostore_mod_install_requested.connect(self._on_iostore_mod_install)
        self._detail.iostore_mod_uninstall_requested.connect(self._on_iostore_mod_uninstall)
        self._detail.iostore_mod_update_requested.connect(self._on_iostore_mod_update)
        self._detail.iostore_mod_rollback_requested.connect(self._on_iostore_mod_rollback)
        self._detail.iostore_forcache_requested.connect(self._on_iostore_forcache)
        self._detail.cache_export_requested.connect(self._on_cache_export)
        self._detail.cache_import_requested.connect(self._on_cache_import)
        self._detail.cache_delete_import_requested.connect(self._on_cache_delete_import)
        self._detail.model_priority_requested.connect(self._on_model_priority)
        self._detail.ue4ss_install_requested.connect(self._on_ue4ss_install)
        self._detail.ue4ss_update_requested.connect(self._on_ue4ss_update)
        self._detail.ue4ss_import_missing_requested.connect(self._on_ue4ss_import_missing)
        self._detail.ue4ss_uninstall_requested.connect(self._on_ue4ss_uninstall)
        self._detail.bepinex_import_requested.connect(self._on_bepinex_import)
        self._detail.bepinex_import_from_requested.connect(self._on_bepinex_import_from)
        self._detail.bepinex_copy_dll_requested.connect(self._on_bepinex_copy_dll)
        self._detail.bepinex_collect_requested.connect(self._on_bepinex_collect)
        self._detail.bepinex_collect_from_requested.connect(self._on_bepinex_collect_from)
        self._detail.proxy_server_toggle_requested.connect(self._on_proxy_server_toggle)
        self._detail.unreal_hook_install_requested.connect(self._on_unreal_hook_install)
        self._detail.unreal_hook_uninstall_requested.connect(self._on_unreal_hook_uninstall)
        self._detail.unreal_hook_launch_requested.connect(self._on_unreal_hook_launch)
        self._detail.unreal_hook_open_translate_requested.connect(self._on_unreal_hook_open_translate)
        self._detail.unreal_hook_update_translate_requested.connect(self._on_unreal_hook_update_translate)
        self._detail.unreal_hook_priority_requested.connect(self._on_model_priority)  # reuse Flotsam dialog
        self._dl_worker: DownloadWorker | None = None

        self._log_panel = LogPanel()

        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.setChildrenCollapsible(False)
        right_splitter.setHandleWidth(6)
        right_splitter.setStyleSheet(
            "QSplitter::handle { background: " + c['border'] + "; }"
            "QSplitter::handle:hover { background: " + c['primary'] + "; }"
        )
        right_splitter.addWidget(self._detail)
        right_splitter.addWidget(self._log_panel)
        right_splitter.setSizes([600, 160])

        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        right_lay.addWidget(right_splitter)

        body.addWidget(left)
        body.addWidget(right, 1)
        lay.addLayout(body, 1)

        # Empty state label (shown over list when no games)
        self._empty_lbl = QLabel("لا توجد ألعاب — أضف لعبة أولاً")
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setStyleSheet(
            f"color: {c['muted']}; font-size: 13px; padding: 20px;"
        )

    def _build_topbar(self) -> QFrame:
        bar, lay = make_topbar("🎮", "إدارة الألعاب")

        refresh_btn = QPushButton("↻  تحديث")
        refresh_btn.setObjectName("btn_secondary")
        refresh_btn.setFixedHeight(34)
        refresh_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        refresh_btn.clicked.connect(self.refresh)
        lay.addWidget(refresh_btn)

        add_btn = QPushButton("➕  إضافة لعبة")
        add_btn.setObjectName("btn_primary")
        add_btn.setFixedHeight(34)
        add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_btn.clicked.connect(self._on_add)
        lay.addWidget(add_btn)

        return bar

    # ── Backend injection ─────────────────────────────────────────────────────

    def set_backend(self, engine, cache, game_manager):
        self._engine       = engine
        self._cache        = cache
        self._game_manager = game_manager
        self.refresh()

    def set_proxy_server(self, proxy):
        self._proxy_server = proxy
        self._detail.set_proxy_server(proxy)
        if proxy:
            proxy.log_callback = self._log_panel.log_message.emit
        self._log_panel.attach_proxy(proxy)

    def set_registry(self, registry_info: dict):
        """Pass {game_id: translation_info} from TranslationRegistry to detail panel."""
        self._registry_info = registry_info or {}
        self._detail._registry_info   = registry_info
        self._detail._registry_loaded = bool(registry_info)  # True only when data received
        if self._detail._game_id:
            self._detail.load(self._detail._game_id, self._detail._game_cfg)
        self._refresh_update_badges()

    def _translation_update_version(self, game_id: str) -> str:
        """يُرجع نسخة الترجمة المتاحة أونلاين إن كانت أحدث من المثبَّتة، وإلا ''."""
        info = (getattr(self, "_registry_info", {}) or {}).get(game_id)
        if not info:
            return ""
        online = str(info.get("version", "") or "")
        if not online:
            return ""
        try:
            from games.translation_package import TranslationPackage
            from games.translation_registry import _version_gt
            pkg = TranslationPackage()
            # نعرض التحديث فقط لو المستخدم يملك حزمة محلية (مثبَّتة/محمَّلة)
            if not pkg.has_files(game_id):
                return ""
            installed = pkg.get_installed_version(game_id) or "0"
            return online if _version_gt(online, installed) else ""
        except Exception:
            return ""

    def _refresh_update_badges(self):
        """يحدّث شارات «تحديث» على عناصر قائمة الألعاب + يطلق إشعار البانر."""
        items = getattr(self, "_items", {}) or {}
        updates = {}
        for gid, item in items.items():
            ver = self._translation_update_version(gid)
            if hasattr(item, "set_update_available"):
                item.set_update_available(ver)
            if ver:
                updates[gid] = ver
        # أبلغ النافذة الرئيسية بعدد التحديثات (لبانر/إشعار عام)
        if updates:
            names = "، ".join(sorted(updates))
            self.status_message.emit(
                f"🔄  تحديث ترجمة متاح لـ {len(updates)} لعبة: {names}"
            )
        self.translation_updates_available.emit(updates)

    def retry_registry(self):
        """Re-fetch registry in background and update the detail panel."""
        if hasattr(self, '_reg_fetcher') and self._reg_fetcher.isRunning():
            return
        self._reg_fetcher = RegistryFetchWorker()
        self._reg_fetcher.done.connect(self._on_registry_fetched)
        self._reg_fetcher.start()
        self.status_message.emit("🔄  جارٍ التحقق من الترجمات المتاحة…")

    def _on_registry_fetched(self, translations: dict, success: bool, error: str):
        if success and translations:
            self.set_registry(translations)
            self.status_message.emit("✅  تم تحميل بيانات الترجمة")
        else:
            msg = f"❌  {error}" if error else "❌  تعذّر الاتصال"
            self.status_message.emit(msg)

    def refresh_theme(self):
        c = theme.c
        self._left_panel.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-right: 1px solid {c['border']}; }}"
        )
        self._right_panel.setStyleSheet(f"background: {c['bg']};")
        self.refresh()

    # ── Refresh list ──────────────────────────────────────────────────────────

    def refresh(self):
        # Clear current items
        while self._list_lay.count() > 1:   # keep the trailing stretch
            item = self._list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._items.clear()

        if not self._game_manager:
            return

        try:
            games = self._game_manager.get_all_games()
        except Exception:
            games = {}

        if not games:
            self._list_lay.insertWidget(0, self._empty_lbl)
            self._empty_lbl.show()
            return

        self._empty_lbl.hide()

        prev_selected = self._selected_id
        self._selected_id = None

        for game_id, cfg in games.items():
            item = GameListItem(game_id, cfg)
            item.clicked.connect(self._select_game)
            self._items[game_id] = item
            self._list_lay.insertWidget(self._list_lay.count() - 1, item)

        # Restore selection if possible
        if prev_selected and prev_selected in self._items:
            self._select_game(prev_selected)
        elif games:
            self._select_game(next(iter(games)))

        # حدّث شارات «تحديث الترجمة» (لو وصلت بيانات الـ registry مسبقاً)
        self._refresh_update_badges()

    def refresh_game(self, game_id: str):
        """تحديث لوحة التفاصيل للعبة محددة بعد حفظ الإعدادات من لوحة الإدارة."""
        if not self._game_manager:
            return
        try:
            cfg = self._game_manager.get_game(game_id) or {}
        except Exception:
            return
        # Deactivate old selection
        if self._selected_id and self._selected_id != game_id and self._selected_id in self._items:
            self._items[self._selected_id].set_active(False)
        self._selected_id = game_id
        if game_id in self._items:
            self._items[game_id].set_active(True)
        self._detail.load(game_id, cfg, self._cache)
        self._update_log_panel_visibility(cfg)

    @staticmethod
    def _game_needs_proxy_log(cfg: dict) -> bool:
        """هل تستخدم اللعبة مسار الالتقاط الحيّ (بروكسي HTTP 5001)؟
        السجل يُظهَر فقط لها — أمّا الأوضاع الساكنة (datatable_pak / ue4ss /
        foundation / iostore) فلا تمرّ بالبروكسي إطلاقاً."""
        cfg = cfg or {}
        eng      = (cfg.get("engine", "") or "").lower()
        mod_mode = cfg.get("mod_mode", "")
        shown    = cfg.get("shown_features") or []
        # Unity (BepInEx + XUnity → proxy)
        if eng == "unity" or "bepinex_mod" in cfg:
            return True
        # UE5 Unreal Hook (watcher → proxy)
        if "unreal_hook_section" in shown or cfg.get("hook_mode") == "unreal_hook":
            return True
        # بروكسي حيّ صريح
        if mod_mode == "proxy":
            return True
        return False

    def _update_log_panel_visibility(self, cfg: dict):
        if hasattr(self, "_log_panel") and self._log_panel is not None:
            self._log_panel.setVisible(self._game_needs_proxy_log(cfg))

    def _select_game(self, game_id: str):
        # Deactivate previous
        if self._selected_id and self._selected_id in self._items:
            self._items[self._selected_id].set_active(False)

        self._selected_id = game_id
        if game_id in self._items:
            self._items[game_id].set_active(True)

        cfg = {}
        if self._game_manager:
            try:
                cfg = self._game_manager.get_game(game_id) or {}
            except Exception:
                pass

        self._detail.load(game_id, cfg, self._cache)
        self._update_log_panel_visibility(cfg)

    def select_game(self, game_id: str):
        """Public API — يُستخدَم من app.py عند الانتقال من home بزر 'إدارة اللعبة'."""
        if game_id:
            self._select_game(game_id)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_add(self):
        from gui.qt.dialogs.add_game import AddGameDialog
        dlg = AddGameDialog(self._game_manager, parent=self)
        dlg.saved.connect(self._after_save)
        dlg.exec()

    def _on_edit(self, game_id: str):
        if not self._game_manager:
            return
        cfg = self._game_manager.get_game(game_id) or {}
        from gui.qt.dialogs.add_game import AddGameDialog
        dlg = AddGameDialog(self._game_manager, game_id=game_id,
                            game_cfg=cfg, parent=self)
        dlg.saved.connect(self._after_save)
        dlg.exec()

    def _on_delete(self, game_id: str):
        cfg  = self._game_manager.get_game(game_id) or {} if self._game_manager else {}
        name = cfg.get("name", game_id)
        reply = QMessageBox.question(
            self, "تأكيد الحذف",
            f"هل أنت متأكد من حذف اللعبة:\n«{name}»؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if self._game_manager:
            self._game_manager.delete_game(game_id)
        self.status_message.emit(f"✓  تم حذف: {name}")
        self.refresh()
        self.games_changed.emit()

    def _on_translate(self, game_id: str):
        if not self._engine:
            QMessageBox.warning(
                self, "تنبيه",
                "لا يوجد نموذج مُحمَّل.\nيرجى تحميل نموذج من صفحة النماذج أولاً."
            )
            return
        cfg = self._game_manager.get_game(game_id) if self._game_manager else {}
        if not cfg:
            cfg = {}
        from gui.qt.dialogs.translate_game import TranslateGameDialog
        dlg = TranslateGameDialog(
            game_id, cfg, self._engine, self._cache, parent=self
        )
        dlg.translation_done.connect(
            lambda n: self.status_message.emit(f"✓  اكتملت الترجمة: {n} ترجمة جديدة")
        )
        dlg.exec()

    def _open_iostore_wizard(self, game_id: str, cfg: dict):
        import json, os
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))),
            "config.json"
        )
        try:
            with open(config_path, encoding="utf-8") as f:
                app_config = json.load(f)
        except Exception:
            app_config = {}
        from gui.qt.dialogs.iostore_wizard import IoStoreWizard
        dlg = IoStoreWizard(
            engine=self._engine,
            cache=self._cache,
            config=app_config,
            game_id=game_id,
            game_cfg=cfg,
            parent=self,
        )
        self._iostore_wizard = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_install(self, game_id: str, game_path: str):
        from games.translation_package import TranslationPackage
        pkg = TranslationPackage()
        ok, log = pkg.install(game_id, game_path)
        msg = "\n".join(log)
        if ok:
            self.status_message.emit(f"✅  تم تثبيت الترجمة في: {game_path}")
            QMessageBox.information(self, "تثبيت ناجح", f"تم تثبيت الترجمة بنجاح:\n\n{msg}")
        else:
            QMessageBox.warning(self, "فشل التثبيت", f"حدث خطأ:\n\n{msg}")
        self.refresh()

    def _on_uninstall(self, game_id: str, game_path: str):
        reply = QMessageBox.question(
            self, "تأكيد الإلغاء",
            "هل تريد إلغاء تثبيت ملفات الترجمة من مجلد اللعبة؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        from games.translation_package import TranslationPackage
        pkg = TranslationPackage()
        ok, log = pkg.uninstall(game_id, game_path)
        msg = "\n".join(log)
        if ok:
            self.status_message.emit("🗑️  تم إلغاء التثبيت")
            QMessageBox.information(self, "تم الإلغاء", f"تم إلغاء التثبيت:\n\n{msg}")
        else:
            QMessageBox.warning(self, "فشل الإلغاء", f"حدث خطأ:\n\n{msg}")
        self.refresh()

    def _on_download(self, game_id: str):
        self._run_download(game_id, auto_install=False, game_path="")

    def _on_download_install(self, game_id: str, game_path: str):
        """تحميل من GitHub ثم تثبيت تلقائي (للتحديث / تحميل+تثبيت)."""
        self._run_download(game_id, auto_install=True, game_path=game_path)

    def _run_download(self, game_id: str, auto_install: bool = False, game_path: str = ""):
        from games.translation_package import TranslationPackage
        registry_info = getattr(self._detail, '_registry_info', {})
        info = registry_info.get(game_id)
        if not info:
            QMessageBox.warning(self, "تحميل", "معلومات التحميل غير متاحة.")
            return
        if self._dl_worker and self._dl_worker.isRunning():
            return

        pkg = TranslationPackage()
        ready_dir = pkg.get_ready_dir(game_id)
        online_ver = str(info.get("version", "") or "")
        # لقطة للنسخة الحالية قبل التحميل فوقها (تتيح «↩ تراجع»)
        try:
            pkg.snapshot_ready(game_id)
        except Exception:
            pass
        self._dl_worker = DownloadWorker(game_id, info, ready_dir)

        # Wire progress to the detail panel's progress bar
        panel = self._detail
        if hasattr(panel, '_dl_progress'):
            panel._dl_progress.setVisible(True)
            panel._dl_progress.setMaximum(100)
            panel._dl_lbl.setVisible(True)

            def _on_progress(done, total):
                pct = int(done * 100 / total) if total else 0
                panel._dl_progress.setValue(pct)
                panel._dl_lbl.setText(
                    f"جارٍ التحميل… {done // 1024 // 1024} MB / {total // 1024 // 1024} MB"
                )

            def _on_file(name):
                self.status_message.emit(f"⬇️  تم تحميل: {name}")

            def _on_done(ok, msg):
                panel._dl_progress.setVisible(False)
                panel._dl_lbl.setVisible(False)
                if not ok:
                    QMessageBox.warning(self, "فشل التحميل", msg)
                    return
                # تثبيت تلقائي + تسجيل النسخة بعد التحميل الناجح
                if auto_install and game_path:
                    iok, ilog = pkg.install(game_id, game_path)
                    if online_ver:
                        pkg.set_installed_version(game_id, online_ver)
                    if iok:
                        self.status_message.emit(f"✅  حُمِّلت وثُبِّتت ترجمة {game_id}"
                                                 + (f" v{online_ver}" if online_ver else ""))
                        QMessageBox.information(self, "✅  تم", "تم تحميل وتثبيت الترجمة بنجاح:\n\n"
                                                + "\n".join(ilog))
                    else:
                        QMessageBox.warning(self, "فشل التثبيت", "\n".join(ilog))
                else:
                    if online_ver:
                        pkg.set_installed_version(game_id, online_ver)
                    self.status_message.emit(f"✅  {msg}")
                self.refresh()

            self._dl_worker.progress.connect(_on_progress)
            self._dl_worker.file_done.connect(_on_file)
            self._dl_worker.finished.connect(_on_done)

        self._dl_worker.start()
        self.status_message.emit(f"⬇️  بدء تحميل ترجمة {game_id}…")

    def _on_bepinex_install(self, game_id: str, game_path: str):
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        from games.bepinex_mod import BepInExMod
        ok, log = BepInExMod().install(cfg, game_path, self._cache)
        msg = "\n".join(log)
        if ok:
            warnings = [l for l in log if l.startswith("⚠")]
            if warnings:
                self.status_message.emit(f"⚠  مود BepInEx مُثبَّت مع تحذيرات: {game_id}")
            else:
                self.status_message.emit(f"✅  مود BepInEx مُثبَّت: {game_id}")
            QMessageBox.information(self, "✅  تثبيت ناجح", f"تم تثبيت المود:\n\n{msg}")
        else:
            QMessageBox.critical(self, "❌  فشل التثبيت", msg)
        self.refresh()

    def _on_bepinex_uninstall(self, game_id: str, game_path: str):
        reply = QMessageBox.question(
            self, "تأكيد الإلغاء",
            "هل تريد إزالة مود BepInEx وملف الترجمات من مجلد اللعبة؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        from games.bepinex_mod import BepInExMod
        ok, log = BepInExMod().uninstall(cfg, game_path)
        msg = "\n".join(log)
        if ok:
            self.status_message.emit(f"🗑  تم إلغاء مود BepInEx: {game_id}")
            QMessageBox.information(self, "تم الإلغاء", f"تم إلغاء التثبيت:\n\n{msg}")
        else:
            QMessageBox.warning(self, "خطأ في الإلغاء", msg)
        self.refresh()

    def _on_bepinex_update(self, game_id: str, game_path: str):
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        from games.bepinex_mod import BepInExMod
        ok, log = BepInExMod().update_translations(cfg, game_path, self._cache)
        msg = "\n".join(log)
        if ok:
            self.status_message.emit(log[0] if log else "✅  تم تحديث الترجمات")
            QMessageBox.information(self, "✅  تم التحديث", msg)
        else:
            QMessageBox.warning(self, "خطأ في التحديث", msg)
        self.refresh()

    # ── Foundation (Hurricane) handlers ─────────────────────────────────────

    def _persist_foundation_wrap(self, game_id: str, cfg: dict, wrap: int):
        if self._game_manager and wrap != cfg.get("foundation", {}).get("wrap"):
            f = dict(cfg.get("foundation", {}))
            f["wrap"] = wrap
            try:
                self._game_manager.update_game(game_id, {"foundation": f})
            except Exception:
                pass

    def _on_foundation_install(self, game_id: str, game_path: str, wrap: int):
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        self._persist_foundation_wrap(game_id, cfg, wrap)
        from games.foundation_mod import FoundationMod
        ok, log = FoundationMod().install(cfg, game_path, self._cache, wrap=wrap)
        msg = "\n".join(log)
        if ok:
            self.status_message.emit(f"✅  تعريب Foundation مُثبَّت: {game_id}")
            QMessageBox.information(self, "✅  تثبيت ناجح", msg)
        else:
            QMessageBox.critical(self, "❌  فشل التثبيت", msg)
        self.refresh()

    def _on_foundation_uninstall(self, game_id: str, game_path: str):
        reply = QMessageBox.question(
            self, "تأكيد الإلغاء",
            "إلغاء تعريب Foundation واستعادة CrashRpt1403.dll الأصلية + اللغة الإنجليزية؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        from games.foundation_mod import FoundationMod
        ok, log = FoundationMod().uninstall(cfg, game_path)
        msg = "\n".join(log)
        if ok:
            self.status_message.emit(f"🗑  أُلغي تعريب Foundation: {game_id}")
            QMessageBox.information(self, "تم الإلغاء", msg)
        else:
            QMessageBox.warning(self, "خطأ في الإلغاء", msg)
        self.refresh()

    def _on_foundation_update(self, game_id: str, game_path: str, wrap: int):
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        self._persist_foundation_wrap(game_id, cfg, wrap)
        from games.foundation_mod import FoundationMod
        ok, log = FoundationMod().update_translations(cfg, game_path, self._cache, wrap=wrap)
        msg = "\n".join(log)
        if ok:
            self.status_message.emit(log[-1] if log else "✅  تم تحديث الترجمة")
            QMessageBox.information(self, "✅  تم التحديث", msg)
        else:
            QMessageBox.warning(self, "خطأ في التحديث", msg)
        self.refresh()

    def _on_foundation_font(self, game_id: str, game_path: str):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from games.foundation_mod import FoundationMod
        path, _ = QFileDialog.getOpenFileName(
            self, "اختر خطاً عربياً للتجربة", "", "ملفات الخطوط (*.ttf *.otf *.ttc)")
        if not path:
            return
        cov = FoundationMod.font_coverage(path)
        if cov.get("error"):
            QMessageBox.critical(self, "خط غير صالح", f"تعذّر قراءة الخط:\n{cov['error']}")
            return
        warn = ""
        if cov["pf_a"] == 0 and cov["pf_b"] == 0:
            warn = ("\n\n⚠ هذا الخط لا يحوي presentation forms — الأرجح ستظهر الحروف "
                    "مقطّعة أو ؟ (لأننا نغذّي نصاً مُشكّلاً). جرّبه على مسؤوليتك.")
        box = QMessageBox(self)
        box.setWindowTitle("تطبيق الخط على")
        box.setText(
            f"تغطية الخط:  عربي={cov['arabic']}  PF-A={cov['pf_a']}  PF-B={cov['pf_b']}"
            f"{warn}\n\nطبّقه على أي فتحة؟")
        b_both = box.addButton("الكل (Regular+Bold)", QMessageBox.AcceptRole)
        b_reg  = box.addButton("Regular فقط", QMessageBox.AcceptRole)
        b_bold = box.addButton("Bold فقط", QMessageBox.AcceptRole)
        box.addButton("إلغاء", QMessageBox.RejectRole)
        box.exec()
        slot = {b_both: "both", b_reg: "regular", b_bold: "bold"}.get(box.clickedButton())
        if not slot:
            return
        ok, log = FoundationMod().set_font(game_path, path, slot)
        msg = "\n".join(log)
        if ok:
            self.status_message.emit("✅  طُبّق الخط — أعد تشغيل اللعبة")
            QMessageBox.information(self, "✅  تم تطبيق الخط",
                                    f"{msg}\n\nأعد تشغيل اللعبة عبر Steam لرؤية الخط.")
        else:
            QMessageBox.warning(self, "خطأ", msg)

    # ── Manor Lords (DataTable .pak) handlers ──────────────────────────────

    def _run_manorlords_build(self, game_id: str, game_path: str, action: str):
        """يشغّل بناء/تثبيت/تحديث المود في خيط مع شريط تقدّم."""
        from PySide6.QtWidgets import QProgressDialog
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        title = {"install": "تثبيت التعريب", "update": "تحديث الترجمة"}.get(action, "بناء المود")
        dlg = QProgressDialog(f"{title} — تجهيز…", "إلغاء", 0, 100, self)
        dlg.setWindowTitle(f"Manor Lords — {title}")
        dlg.setMinimumWidth(440)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)

        worker = ManorLordsBuildWorker(cfg, game_path, self._cache, action)

        def on_prog(i, n, name):
            dlg.setMaximum(n)
            dlg.setValue(i)
            dlg.setLabelText(f"{title}: {i}/{n}\n{name}")

        def on_done(ok, log):
            dlg.close()
            if ok:
                self.status_message.emit(f"✅  {title} Manor Lords: {game_id}")
                QMessageBox.information(self, f"✅  {title}", log)
            else:
                QMessageBox.critical(self, "❌  فشل", log)
            self.refresh()
            worker.deleteLater()

        worker.progress.connect(on_prog)
        worker.finished.connect(on_done)
        dlg.canceled.connect(worker.terminate)
        self._ml_worker = worker   # امنع جمع القمامة
        worker.start()
        dlg.show()

    def _on_manorlords_install(self, game_id: str, game_path: str):
        from games.manorlords_mod import ManorLordsMod
        ok, msg = ManorLordsMod.tools_exist()
        if not ok:
            QMessageBox.critical(self, "أدوات مفقودة", msg)
            return
        self._run_manorlords_build(game_id, game_path, "install")

    def _on_manorlords_update(self, game_id: str, game_path: str):
        self._run_manorlords_build(game_id, game_path, "update")

    def _on_manorlords_uninstall(self, game_id: str, game_path: str):
        reply = QMessageBox.question(
            self, "تأكيد الإلغاء",
            "حذف مود التعريب (zzz_ManorLords_Arabic_P.pak) وعودة اللعبة للإنجليزية؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        from games.manorlords_mod import ManorLordsMod
        ok, log = ManorLordsMod().uninstall(cfg, game_path)
        msg = "\n".join(log)
        if ok:
            self.status_message.emit(f"🗑  أُلغي تعريب Manor Lords: {game_id}")
            QMessageBox.information(self, "تم الإلغاء", msg)
        else:
            QMessageBox.warning(self, "خطأ في الإلغاء", msg)
        self.refresh()

    # ── IoStore mod (zen) handlers ─────────────────────────────────────────

    def _pick_build_source(self, game_id: str):
        """حوار اختيار مصدر الترجمة للبناء (أفضل دمج / مودل محدّد / مستورَد).
        يُرجع (model_filter, ok). model_filter='' = أفضل دمج (get_best)."""
        game = self._cache_game_key(game_id)
        try:
            counts = self._cache.count_by_model(game) if self._cache else {}
        except Exception:
            counts = {}
        # رتّب: المصادر المستورَدة أوّلاً ثم المودلات
        items = sorted(counts.items(), key=lambda kv: (not kv[0].startswith("import:"), kv[0]))
        box = QMessageBox(self)
        box.setWindowTitle("مصدر الترجمة للبناء")
        box.setIcon(QMessageBox.Question)
        box.setText("اختر مصدر الترجمة الذي يُبنى منه:")
        btn_best = box.addButton("🏆 أفضل دمج (موصى به)", QMessageBox.AcceptRole)
        btn_map = {}
        for model, cnt in items:
            disp = ("🧩 " + model.split("import:", 1)[-1]) if model.startswith("import:") else ("🤖 " + model)
            b = box.addButton(f"{disp} ({cnt:,})", QMessageBox.AcceptRole)
            btn_map[b] = model
        box.addButton("إلغاء", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == btn_best:
            return "", True
        if clicked in btn_map:
            return btn_map[clicked], True
        return "", False

    def _run_iostore_build(self, game_id: str, game_path: str, action: str,
                           model_filter: str = ""):
        """يشغّل بناء/تثبيت/تحديث/إلغاء مود IoStore في خيط مع شريط تقدّم."""
        from PySide6.QtWidgets import QProgressDialog
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        title = {"install": "تثبيت الترجمة", "update": "تحديث الترجمة",
                 "uninstall": "إلغاء التعريب"}.get(action, "بناء المود")
        dlg = QProgressDialog(f"{title} — تجهيز…", "إلغاء", 0, 100, self)
        dlg.setWindowTitle(f"IoStore — {title}")
        dlg.setMinimumWidth(440)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)

        worker = IoStoreBuildWorker(game_id, cfg, game_path, self._cache, action, model_filter)

        def on_prog(i, n, name):
            dlg.setMaximum(max(n, 1))
            dlg.setValue(i)
            dlg.setLabelText(f"{title}: {i}/{n}\n{name}")

        def on_done(ok, log):
            dlg.close()
            if ok:
                # بعد بناء/تثبيت محلي ناجح، اضبط النسخة المثبَّتة = النسخة الأونلاين
                # (إن وُجدت) كي لا يظهر إشعار «تحديث» كاذب على بناء محلي حديث.
                if action in ("install", "update"):
                    try:
                        from games.translation_package import TranslationPackage
                        _pkg = TranslationPackage()
                        _online = ((getattr(self, "_registry_info", {}) or {})
                                   .get(game_id, {}).get("version", ""))
                        if _online:
                            _pkg.set_installed_version(game_id, _online)
                    except Exception:
                        pass
                self.status_message.emit(f"✅  {title} IoStore: {game_id}")
                QMessageBox.information(self, f"✅  {title}", log)
            else:
                QMessageBox.critical(self, "❌  فشل", log)
            self.refresh()
            worker.deleteLater()

        worker.progress.connect(on_prog)
        worker.finished.connect(on_done)
        dlg.canceled.connect(worker.terminate)
        self._io_worker = worker   # امنع جمع القمامة
        worker.start()
        dlg.show()

    def _on_iostore_mod_install(self, game_id: str, game_path: str):
        from games.iostore_mod import IoStoreMod
        mod = IoStoreMod()
        ok, msg = mod.tools_exist(game_id)
        if not ok and mod.has_source(game_id):
            QMessageBox.critical(self, "أدوات مفقودة", msg)
            return
        # عند وجود مصدر للبناء → اسأل عن مصدر الترجمة (أفضل دمج/مودل/مستورَد)
        mf = ""
        if mod.has_source(game_id):
            mf, go = self._pick_build_source(game_id)
            if not go:
                return
        self._run_iostore_build(game_id, game_path, "install", mf)

    def _on_iostore_mod_update(self, game_id: str, game_path: str):
        from games.iostore_mod import IoStoreMod
        ok, msg = IoStoreMod().tools_exist(game_id)
        if not ok:
            QMessageBox.critical(self, "أدوات مفقودة", msg)
            return
        mf, go = self._pick_build_source(game_id)
        if not go:
            return
        self._run_iostore_build(game_id, game_path, "update", mf)

    def _on_iostore_mod_uninstall(self, game_id: str, game_path: str):
        reply = QMessageBox.question(
            self, "تأكيد الإلغاء",
            "حذف ملفات مود الترجمة (.pak/.ucas/.utoc) من مجلد اللعبة وعودتها للإنجليزية؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._run_iostore_build(game_id, game_path, "uninstall")

    # ── Cache export / import (مشاركة الكاش) ───────────────────────────────
    def _cache_game_key(self, game_id: str) -> str:
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        return cfg.get("name", game_id) or game_id

    def _on_cache_export(self, game_id: str):
        import json as _json
        from PySide6.QtWidgets import QFileDialog
        if not self._cache:
            return
        game = self._cache_game_key(game_id)
        try:
            rows = self._cache.export_rows(game)
        except Exception as e:
            QMessageBox.warning(self, "خطأ", f"تعذّر قراءة الكاش: {e}")
            return
        if not rows:
            QMessageBox.information(self, "تصدير", "لا توجد ترجمات لتصديرها.")
            return
        default = f"{game}.gatcache"
        path, _ = QFileDialog.getSaveFileName(
            self, "تصدير كاش الترجمة", default, "كاش الترجمة (*.gatcache);;كل الملفات (*.*)")
        if not path:
            return
        data = {"gatcache": 1, "game": game, "count": len(rows), "rows": rows}
        try:
            with open(path, "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False)
            self.status_message.emit(f"📤  صُدّر {len(rows):,} ترجمة → {os.path.basename(path)}")
            QMessageBox.information(self, "✅  تم التصدير",
                f"صُدّرت {len(rows):,} ترجمة إلى:\n{path}\n\nشاركه مع غيرك ليستورده.")
        except Exception as e:
            QMessageBox.warning(self, "فشل التصدير", str(e))

    def _on_cache_import(self, game_id: str):
        import json as _json
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        if not self._cache:
            return
        game = self._cache_game_key(game_id)
        path, _ = QFileDialog.getOpenFileName(
            self, "استيراد كاش الترجمة", "", "كاش الترجمة (*.gatcache *.json);;كل الملفات (*.*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = _json.load(f)
            rows = data.get("rows", data if isinstance(data, list) else [])
            src_game = data.get("game", "") if isinstance(data, dict) else ""
        except Exception as e:
            QMessageBox.warning(self, "ملف غير صالح", f"تعذّر قراءة الملف: {e}")
            return
        if not rows:
            QMessageBox.information(self, "استيراد", "الملف لا يحوي ترجمات.")
            return
        if src_game and src_game != game:
            if QMessageBox.question(self, "لعبة مختلفة",
                    f"الملف للعبة «{src_game}» وأنت تستورد إلى «{game}». متابعة؟",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        # اختيار وضع الاستيراد
        box = QMessageBox(self)
        box.setWindowTitle("طريقة الاستيراد")
        box.setText(f"الملف يحوي {len(rows):,} ترجمة.\n\nكيف تستوردها؟")
        b_merge = box.addButton("🔗 دمج آمن (لا يدهس ترجماتك)", QMessageBox.AcceptRole)
        b_sep   = box.addButton("🧩 احفظها كمصدر مستقل", QMessageBox.AcceptRole)
        box.addButton("إلغاء", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == b_merge:
            mode, label = "merge", ""
        elif clicked == b_sep:
            n = len(self._cache.list_import_sources(game)) + 1
            label, ok = QInputDialog.getText(self, "اسم المصدر", "اسم مصدر الاستيراد:",
                                             text=f"مستورد {n}")
            if not ok or not label.strip():
                return
            mode, label = "separate", label.strip()
        else:
            return
        try:
            stats = self._cache.import_rows(game, rows, mode=mode, label=label)
        except Exception as e:
            QMessageBox.warning(self, "فشل الاستيراد", str(e))
            return
        self.status_message.emit(f"📥  استُورد {stats['added']:,} ترجمة لـ {game}")
        QMessageBox.information(self, "✅  تم الاستيراد",
            f"أُضيف/حُدِّث: {stats['added']:,}\nتُخطّي: {stats['skipped']:,}\n\n"
            "استخدم «إعادة بناء من الكاش» لتطبيقها في اللعبة.")
        self.refresh()

    def _on_cache_delete_import(self, game_id: str, model: str):
        if not self._cache:
            return
        disp = model.split("import:", 1)[-1] or model
        if QMessageBox.question(self, "حذف مصدر مستورَد",
                f"حذف مصدر الاستيراد «{disp}» بالكامل؟ (لا يؤثّر على ترجماتك)",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        game = self._cache_game_key(game_id)
        try:
            self._cache.delete_by_model(game, model)
            self.status_message.emit(f"🗑  حُذف المصدر المستورَد: {disp}")
        except Exception as e:
            QMessageBox.warning(self, "خطأ", str(e))
        self.refresh()

    def _on_iostore_forcache(self, game_id: str):
        """يحمّل مصدر البناء (for_cache) ليُمكّن المستخدم من البناء من كاشه المحلي."""
        from games.translation_package import TranslationPackage
        registry_info = getattr(self._detail, '_registry_info', {})
        info = registry_info.get(game_id) or {}
        url = info.get("for_cache_url", "")
        if not url:
            QMessageBox.warning(self, "تحميل", "مصدر البناء غير متاح لهذه اللعبة.")
            return
        if getattr(self, "_fc_worker", None) and self._fc_worker.isRunning():
            return
        pkg = TranslationPackage()
        fc_dir = pkg.get_for_cache_dir(game_id)
        sha = info.get("for_cache_sha256", "")
        from PySide6.QtWidgets import QProgressDialog
        dlg = QProgressDialog("تحميل مصدر البناء…", "إلغاء", 0, 100, self)
        dlg.setWindowTitle(f"{game_id} — مصدر البناء")
        dlg.setMinimumWidth(420); dlg.setAutoClose(False); dlg.setValue(0)

        self._fc_worker = ForCacheWorker(game_id, url, fc_dir, sha)

        def _prog(done, total):
            if total:
                dlg.setValue(int(done * 100 / total))
                dlg.setLabelText(f"تحميل مصدر البناء… {done//1048576}/{total//1048576} MB")

        def _done(ok, msg):
            dlg.close()
            if ok:
                self.status_message.emit(f"✅  {msg} — الآن يمكنك «إعادة البناء من الكاش»")
                QMessageBox.information(self, "✅  جاهز للبناء",
                    f"{msg}\n\nعدّل الترجمات في صفحة الكاش ثم استخدم زر «تثبيت/إعادة بناء من الكاش».")
            else:
                QMessageBox.warning(self, "فشل", msg)
            self.refresh()
            self._fc_worker.deleteLater()

        self._fc_worker.progress.connect(_prog)
        self._fc_worker.finished.connect(_done)
        dlg.canceled.connect(self._fc_worker.terminate)
        self._fc_worker.start()
        dlg.show()

    def _on_iostore_mod_rollback(self, game_id: str, game_path: str):
        from games.translation_package import TranslationPackage
        pkg = TranslationPackage()
        pv = pkg.previous_version(game_id)
        reply = QMessageBox.question(
            self, "تأكيد التراجع",
            f"الاستعادة للنسخة السابقة" + (f" (v{pv})" if pv else "") +
            " وتثبيتها؟\n(النسخة الحالية تُحفظ كي يمكن الرجوع إليها لاحقاً)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        ok, log = pkg.rollback(game_id, game_path)
        msg = "\n".join(log)
        if ok:
            self.status_message.emit(f"↩  تمّ التراجع للنسخة السابقة: {game_id}")
            QMessageBox.information(self, "↩  تراجع ناجح", msg)
        else:
            QMessageBox.warning(self, "فشل التراجع", msg)
        self.refresh()

    # ── UE4SS Arabic Translator handlers ───────────────────────────────────

    def _on_ue4ss_install(self, game_id: str):
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        game_path = cfg.get("game_path", "")
        if not game_path:
            QMessageBox.warning(self, "خطأ", "مسار اللعبة غير محدد")
            return
        from games.ue4ss_mod import UE4SSMod
        mod = UE4SSMod()
        # 1) ثبّت UE4SS
        ok1, log1 = mod.install_ue4ss(game_path, game_id)
        # 2) ثبّت المود
        ok2, log2 = mod.install_translator_mod(game_path, game_id)
        # 3) صدّر القاموس فوراً من الكاش (إن وُجد)
        ok3 = False
        msg3 = ""
        count3 = 0
        try:
            ok3, msg3, count3 = mod.export_dict(
                game_path, game_id, self._cache,
                game_name=cfg.get("name", game_id),
            )
        except Exception as e:
            msg3 = str(e)

        all_log = log1 + log2
        if ok3:
            all_log.append(f"✓ {msg3}")
        elif msg3:
            all_log.append(f"⚠ تصدير القاموس: {msg3}")
        msg = "\n".join(all_log)
        if ok1 and ok2:
            QMessageBox.information(self, "✅  تم التثبيت",
                f"تم تثبيت UE4SS + المود بنجاح.\n\n{msg}\n\n"
                "شغّل اللعبة لاختبار الترجمة.")
            self.status_message.emit(f"✓ UE4SS مُثبَّت + {count3:,} ترجمة")
        else:
            QMessageBox.critical(self, "❌  فشل التثبيت", msg)
        self.refresh()

    def _on_ue4ss_update(self, game_id: str):
        """يُصدِّر القاموس من الكاش لـ UE4SS dict/translations.txt."""
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        game_path = cfg.get("game_path", "")
        if not game_path or not self._cache:
            QMessageBox.warning(self, "خطأ", "مسار اللعبة أو الكاش غير متاح")
            return
        from games.ue4ss_mod import UE4SSMod
        from PySide6.QtWidgets import QInputDialog
        mod = UE4SSMod()
        game_name = cfg.get("name", game_id)

        # حوار اختيار النموذج (نفس نمط BepInEx)
        model_filter = ""
        try:
            models = self._cache.get_models_for_game(game_name)
        except Exception:
            models = []
        if models:
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
            selected, ok_c = QInputDialog.getItem(
                self, "اختر نموذج",
                "أيّ نموذج تريد تصدير ترجماته لـ UE4SS dict؟",
                items, 0, False,
            )
            if not ok_c:
                return
            model_filter = item_to_model.get(selected, "")

        ok, msg, count = mod.export_dict(
            game_path, game_id, self._cache,
            game_name=game_name, model_filter=model_filter,
        )
        if ok:
            QMessageBox.information(self, "✅  تم التصدير", msg)
            self.status_message.emit(f"✓ {count:,} ترجمة → UE4SS dict")
        else:
            QMessageBox.warning(self, "خطأ", msg)
        self.refresh()

    def _on_ue4ss_import_missing(self, game_id: str):
        """يقرأ missing.txt + يُضيف النصوص للكاش كـ failed_translations
        لتعرض في صفحة الكاش ويستطيع المستخدم ترجمتها."""
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        game_path = cfg.get("game_path", "")
        game_name = cfg.get("name", game_id)
        if not game_path or not self._cache:
            QMessageBox.warning(self, "خطأ", "مسار اللعبة أو الكاش غير متاح")
            return
        from games.ue4ss_mod import UE4SSMod
        mod = UE4SSMod()
        missing = mod.read_missing(game_path, game_id)
        if not missing:
            QMessageBox.information(self, "لا يوجد",
                "ملف missing.txt فارغ — لا توجد نصوص جديدة بانتظار الترجمة.")
            return
        # أضِف للكاش كـ failed (سبب: pending_ue4ss)
        added = 0
        for text in missing:
            try:
                # mark_failed للسماح للمستخدم باستعراضها وترجمتها
                self._cache.mark_failed(
                    game_name, text, "pending_ue4ss", model_used=""
                )
                added += 1
            except Exception:
                pass
        # امسح missing.txt
        mod.clear_missing(game_path, game_id)
        QMessageBox.information(self, "✅  استيراد",
            f"تم استيراد {added} نص جديد إلى الكاش.\n\n"
            "اذهب إلى صفحة الكاش → عرض «فاشل» لرؤيتها وترجمتها.\n"
            "ثم اضغط «تحديث القاموس» لإعادة تصدير translations.txt.")
        self.status_message.emit(f"📥 {added} نص جديد من UE4SS")
        self.refresh()

    def _on_ue4ss_uninstall(self, game_id: str):
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        game_path = cfg.get("game_path", "")
        if not game_path:
            return
        reply = QMessageBox.question(
            self, "تأكيد الإلغاء",
            "ستُحذَف UE4SS + UE4ArabicTranslator من اللعبة.\n"
            "translations.txt و missing.txt سيُحذَفان أيضاً.\n\n"
            "متابعة؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        from games.ue4ss_mod import UE4SSMod
        mod = UE4SSMod()
        ok1, log1 = mod.uninstall_mod(game_path, game_id)
        ok2, log2 = mod.uninstall_ue4ss(game_path, game_id)
        msg = "\n".join(log1 + log2)
        if ok1 and ok2:
            QMessageBox.information(self, "تم الإلغاء", msg)
            self.status_message.emit("🗑 UE4SS أُلغي تثبيته")
        else:
            QMessageBox.warning(self, "خطأ", msg)
        self.refresh()

    def _on_model_priority(self, game_id: str):
        """يفتح حوار ترتيب أولوية المودلات للعبة (drag-drop)."""
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        game_name = cfg.get("name", game_id)
        if not self._cache:
            QMessageBox.warning(self, "خطأ", "الكاش غير متاح.")
            return
        from gui.qt.dialogs.model_priority_dialog import ModelPriorityDialog
        # نخزّن مرجعاً لتجنّب جمع القمامة (الحوار غير modal)
        if not hasattr(self, "_open_priority_dialogs"):
            self._open_priority_dialogs = []
        dlg = ModelPriorityDialog(game_name, self._cache, self)
        dlg.saved.connect(lambda: self.status_message.emit(
            "🎯  حُفظت أولوية المودلات — تُطبَّق عند الدمج الهرمي"
        ))
        dlg.finished.connect(
            lambda _r, d=dlg: self._open_priority_dialogs.remove(d)
            if d in self._open_priority_dialogs else None
        )
        self._open_priority_dialogs.append(dlg)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_bepinex_import(self, game_id: str, game_path: str):
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        from games.bepinex_mod import BepInExMod
        ok, msg, count = BepInExMod().import_translations_from_game(cfg, game_path, self._cache)
        if ok:
            self.status_message.emit(f"📥  {msg}")
            QMessageBox.information(self, "✅  استيراد ناجح", msg)
        else:
            QMessageBox.warning(self, "خطأ في الاستيراد", msg)
        self.refresh()

    def _on_bepinex_import_from(self, game_id: str, game_path: str, _src: str):
        from PySide6.QtWidgets import QFileDialog
        src = QFileDialog.getExistingDirectory(
            self, "اختر مجلد اللعبة التي تحتوي على ترجمات جاهزة",
            "C:/Program Files (x86)/Steam/steamapps/common"
        )
        if not src:
            return
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        from games.bepinex_mod import BepInExMod
        ok, msg, count = BepInExMod().import_translations_from_game(
            cfg, game_path, self._cache, source_path=src
        )
        if ok:
            self.status_message.emit(f"📥  {msg}")
            reply = QMessageBox.question(
                self, "✅  استيراد ناجح",
                f"{msg}\n\nهل تريد تحديث ملف الترجمات في اللعبة الآن؟",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                ok2, log = BepInExMod().update_translations(cfg, game_path, self._cache)
                if ok2:
                    self.status_message.emit(log[0] if log else "✅ تم تحديث الترجمات")
        else:
            QMessageBox.warning(self, "خطأ في الاستيراد", msg)
        self.refresh()

    def _on_bepinex_copy_dll(self, game_id: str, game_path: str):
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        from games.bepinex_mod import BepInExMod
        ok, msg = BepInExMod().copy_dll_from_game(cfg, game_path)
        if ok:
            self.status_message.emit(f"📋  {msg}")
            QMessageBox.information(self, "✅  تم النسخ", msg)
        else:
            QMessageBox.warning(self, "خطأ في النسخ", msg)
        self.refresh()

    def _on_bepinex_collect(self, game_id: str, game_path: str):
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        from games.bepinex_mod import BepInExMod
        ok, msg = BepInExMod().collect_bepinex_from_game(cfg, game_path)
        if ok:
            self.status_message.emit("📦  تم جمع ملفات BepInEx")
            QMessageBox.information(self, "✅  تم الجمع", msg)
        else:
            QMessageBox.warning(self, "خطأ في الجمع", msg)
        self.refresh()

    def _on_bepinex_collect_from(self, game_id: str, _game_path: str):
        from PySide6.QtWidgets import QFileDialog
        src = QFileDialog.getExistingDirectory(
            self, "اختر مجلد اللعبة التي تحتوي على BepInEx",
            "C:/Program Files (x86)/Steam/steamapps/common"
        )
        if not src:
            return
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        from games.bepinex_mod import BepInExMod
        ok, msg = BepInExMod().collect_bepinex_from_game(cfg, cfg.get("game_path",""), source_path=src)
        if ok:
            self.status_message.emit("📦  تم جمع ملفات BepInEx")
            QMessageBox.information(self, "✅  تم الجمع", msg)
        else:
            QMessageBox.warning(self, "خطأ في الجمع", msg)
        self.refresh()

    def _on_proxy_server_toggle(self, game_id: str, game_name: str):
        proxy = self._proxy_server
        if proxy is None:
            self.status_message.emit("❌  خادم الترجمة غير متاح — أعد تشغيل التطبيق")
            return

        if proxy.is_running and proxy.game_name == game_id:
            msg = proxy.stop()
            self.status_message.emit(msg)
            # ملاحظة: لا نُصدّر translations.txt تلقائياً — المستخدم يتحكم
            # عبر زر "🔄 تحديث الترجمات" في صفحة تفاصيل اللعبة فقط
        else:
            game_cfg = self._game_manager.get_game(game_id) if self._game_manager else {}
            # tag_mode يُقرأ من config.json (الفلتر العام في صفحة AI Models)
            from engine.filtered_translator import get_global_tag_mode
            chosen = get_global_tag_mode()
            game_cfg = dict(game_cfg or {})
            game_cfg["tag_mode"] = chosen
            ok, msg  = proxy.start(game_id, cfg=game_cfg)
            self.status_message.emit(msg)
            if ok:
                self.status_message.emit(f"🏷  فلتر التاقات: {chosen} (من إعدادات Models)")
            else:
                QMessageBox.warning(self, "خطأ في الخادم", msg)

        # تحديث البطاقة لتعكس الحالة الجديدة
        if self._detail._game_id == game_id:
            self._detail.load(game_id, self._detail._game_cfg)

    # ملاحظة: حُذِفت _auto_export_translations()
    # المستخدم يتحكّم بإنشاء translations.txt يدوياً عبر زر "🔄 تحديث الترجمات"
    # في صفحة تفاصيل اللعبة (مع اختيار النموذج).


    def _after_save(self, game_id: str, cfg: dict):
        self.status_message.emit(f"✓  تم حفظ: {cfg.get('name', game_id)}")
        self.refresh()
        self.games_changed.emit()

    def _on_font_replace(self, game_id: str, game_path: str):
        cfg       = self._game_manager.get_game(game_id) if self._game_manager else {}
        game_name = (cfg or {}).get("name", game_id)
        from gui.qt.dialogs.font_wizard import FontWizard
        win = FontWizard(game_name=game_name, game_path=game_path, parent=self)
        win.done.connect(
            lambda n: self.status_message.emit(
                f"🔤  تم استبدال {n} ملف خط في: {game_name}"
            )
        )
        self._font_win = win
        win.show()
        win.raise_()
        win.activateWindow()

    # ======================= UNREAL HOOK handlers =======================

    def _on_unreal_hook_install(self, game_id: str, game_name: str):
        """Install hook DLLs to the game's Win64 folder."""
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        from games.unreal_hook_mod import UnrealHookMod
        mod = UnrealHookMod()
        ok, msg = mod.install(cfg)
        icon = QMessageBox.Information if ok else QMessageBox.Warning
        QMessageBox(icon, "تثبيت Unreal Hook", msg, parent=self).exec()
        if ok:
            self.status_message.emit(f"✓ Unreal Hook مُثبَّت على {game_name}")
            self.refresh_game(game_id)

    def _on_unreal_hook_uninstall(self, game_id: str, game_name: str):
        """Remove hook DLLs from game folder."""
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        confirm = QMessageBox.question(
            self, "إلغاء تثبيت Unreal Hook",
            f"هل أنت متأكّد من إزالة Unreal Hook من {game_name}?\n\n"
            "سيُحذف الـ DLLs لكن مجلد Translate/ ستبقى ترجماته.",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        from games.unreal_hook_mod import UnrealHookMod
        mod = UnrealHookMod()
        ok, msg = mod.uninstall(cfg)
        QMessageBox.information(self, "إلغاء تثبيت Unreal Hook", msg)
        if ok:
            self.status_message.emit(f"✓ Unreal Hook أُزيل من {game_name}")
            self.refresh_game(game_id)

    def _on_unreal_hook_launch(self, game_id: str, game_name: str):
        """Launch game with Unreal Hook pre-injected (uses launch_unreal_game.py).
        tag_mode يُقرأ من الفلتر العام في صفحة AI Models (config.json).
        """
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}

        # 1. شغّل البروكسي (بدون حوار — الفلتر العام يُطبَّق تلقائياً)
        proxy = getattr(self, "_proxy_server", None)
        proxy_running_for_us = (
            proxy is not None and proxy.is_running and proxy.game_name == game_id
        )
        if not proxy_running_for_us:
            from engine.filtered_translator import get_global_tag_mode
            chosen_mode = get_global_tag_mode()
            try:
                if proxy is None:
                    from engine.proxy_server import ProxyServer
                    self._proxy_server = ProxyServer(
                        getattr(self, "_engine", None),
                        getattr(self, "_cache", None),
                    )
                    proxy = self._proxy_server
                proxy_cfg = {
                    "apply_bidi": False,                  # Unreal hook لا يحتاج bidi
                    "text_reorder_char_limit": 0,
                    "tag_mode": chosen_mode,
                    "translate_timeout": cfg.get("translate_timeout", 0),
                }
                ok, msg = proxy.start(game_id, proxy_cfg)
                if not ok:
                    QMessageBox.warning(self, "خطأ", f"فشل تشغيل البروكسي:\n{msg}")
                    return
                self.status_message.emit(f"✓ بروكسي شغّال لـ {game_name} (الفلتر: {chosen_mode})")
            except Exception as e:
                QMessageBox.warning(self, "خطأ في البروكسي", str(e))
                return

        # 2. Launch external scripts (each in its own console window)
        # Use CREATE_NEW_CONSOLE flag directly — no cmd shell needed
        import subprocess
        proj_root = Path(__file__).resolve().parents[3]
        # تحديد Python interpreter — نختار python.exe (console) بدل pythonw.exe
        # حتى لو التطبيق يستخدم pythonw، نريد console للنوافذ الجديدة
        py_candidates = [
            sys.executable,                              # نفس اللي شغّال
            "C:\\Python314\\python.exe",                 # المسار المتوقّع
            "C:\\Python313\\python.exe",
            "C:\\Python312\\python.exe",
        ]
        py = None
        for candidate in py_candidates:
            if candidate and Path(candidate).exists() and "pythonw" not in candidate.lower():
                py = candidate
                break
        if not py:
            # fallback: ابحث في PATH
            import shutil
            py = shutil.which("python") or shutil.which("python3")
        if not py:
            QMessageBox.critical(
                self, "Python غير موجود",
                "لم أجد python.exe (console version).\n\n"
                "تأكّد من تثبيت Python 3.12+ على المسار C:\\Python314\\ أو ضمن PATH."
            )
            return

        CREATE_NEW_CONSOLE = 0x00000010  # Windows API flag

        watcher_script  = proj_root / "tools" / "unreal_hook_watcher.py"
        launcher_script = proj_root / "tools" / "launch_unreal_game.py"

        # تأكّد من وجود السكريبتات
        for script in (watcher_script, launcher_script):
            if not script.exists():
                QMessageBox.critical(
                    self, "ملف ناقص",
                    f"السكريبت غير موجود:\n{script}\n\nأعد فحص التطبيق."
                )
                return

        # نقرأ translate_dir من config (مهم! وإلا الـ watcher يستخدم Manor Lords default)
        hook_cfg = cfg.get("unreal_hook", {})
        translate_dir = hook_cfg.get("translate_dir", "")
        if not translate_dir:
            # fallback: نحاول نشتقّه من win64_dir
            win64_dir = hook_cfg.get("win64_dir", "")
            if win64_dir:
                translate_dir = str(Path(win64_dir) / "Translate")
        if not translate_dir:
            QMessageBox.critical(
                self, "إعداد ناقص",
                f"لم أجد 'unreal_hook.translate_dir' في config اللعبة:\n{game_name}\n\n"
                "افحص games/configs/<اسم>.json"
            )
            return

        try:
            # Watcher in new console — نمرّر --translate-dir للعبة المحدّدة
            self.status_message.emit(f"▶ تشغيل Watcher: {watcher_script.name}")
            wp = subprocess.Popen(
                [py, str(watcher_script), "--translate-dir", translate_dir],
                cwd=str(proj_root),
                creationflags=CREATE_NEW_CONSOLE,
            )
            import time
            time.sleep(1)

            # Launcher in new console — يحتاج --game arg
            self.status_message.emit(f"▶ تشغيل Launcher: {launcher_script.name} --game {game_name}")
            lp = subprocess.Popen(
                [py, str(launcher_script), "--game", game_name],
                cwd=str(proj_root),
                creationflags=CREATE_NEW_CONSOLE,
            )

            self.status_message.emit(
                f"▶ {game_name}: watcher PID={wp.pid} | launcher PID={lp.pid}"
            )
            QMessageBox.information(
                self, "تم بدء التشغيل",
                f"تم بدء تشغيل {game_name}.\n\n"
                "ستفتح نافذتان:\n"
                f"  • Watcher (PID {wp.pid}): يترجم النصوص الجديدة\n"
                f"  • Launcher (PID {lp.pid}): يشغّل اللعبة مع injection\n\n"
                f"مجلد Translate:\n  {translate_dir}\n\n"
                f"Python: {py}\n\n"
                "تأكّد Steam شغّال في الخلفية.\n"
                "لو ما اشتغلت اللعبة: ابحث في النوافذ عن رسائل الأخطاء."
            )
        except Exception as e:
            QMessageBox.critical(
                self, "فشل التشغيل",
                f"فشل التشغيل:\n{type(e).__name__}: {e}\n\n"
                f"Python:   {py}\n"
                f"Watcher:  {watcher_script}\n"
                f"Launcher: {launcher_script}"
            )

    def _on_unreal_hook_open_translate(self, game_id: str, game_name: str):
        """Open the Translate/ folder in Explorer."""
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        from games.unreal_hook_mod import UnrealHookMod
        mod = UnrealHookMod()
        translate_dir = mod.get_translate_dir(cfg)
        if not translate_dir or not translate_dir.exists():
            QMessageBox.warning(self, "خطأ", f"مجلد Translate غير موجود:\n{translate_dir}")
            return
        try:
            os.startfile(str(translate_dir))
        except Exception as e:
            QMessageBox.warning(self, "خطأ", f"فشل فتح المجلد: {e}")

    def _on_unreal_hook_update_translate(self, game_id: str, game_name: str, model_filter: str):
        """Regenerate all .subtitle.txt files from cache using chosen model filter."""
        cfg = (self._game_manager.get_game(game_id) if self._game_manager else {}) or {}
        from games.unreal_hook_mod import UnrealHookMod
        mod = UnrealHookMod()

        if not self._cache:
            QMessageBox.warning(self, "خطأ", "الكاش غير متاح")
            return

        # تأكيد قبل الكتابة (سيستبدل ملفات موجودة)
        filter_desc = f"المودل: {model_filter}" if model_filter else "دمج هرمي (best of all)"
        confirm = QMessageBox.question(
            self, "تحديث مجلد Translate",
            f"سيُعاد إنشاء كل ملفات .subtitle.txt في مجلد Translate من الكاش.\n\n"
            f"الفلتر: {filter_desc}\n\n"
            "هذا سيستبدل أي ترجمات حالية (لكن .en.txt تبقى).\n\nمتابعة؟",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            ok, msg, stats = mod.export_translate_folder(
                cfg, self._cache, game_name, model_filter=model_filter, apply_reshape=True
            )
            icon = QMessageBox.Information if ok else QMessageBox.Warning
            QMessageBox(icon, "تحديث Translate", msg, parent=self).exec()
            if ok:
                written = stats.get("written", 0)
                self.status_message.emit(
                    f"🔄  {game_name}: تم تحديث {written:,} ملف ترجمة"
                )
                self.refresh_game(game_id)
        except Exception as e:
            QMessageBox.critical(self, "خطأ", f"فشل تحديث Translate:\n{e}")

    def _on_locres_translate(self, game_id: str, folder: str):
        cfg       = self._game_manager.get_game(game_id) if self._game_manager else {}
        game_name = (cfg or {}).get("name", game_id)
        from gui.qt.dialogs.locres_wizard import LocresWizard
        win = LocresWizard(
            folder=folder,
            engine=self._engine,
            cache=self._cache,
            game_id=game_id,
            game_name=game_name,
            parent=self,
        )
        win.done.connect(
            lambda rep, tot: self.status_message.emit(
                f"✅  .locres: تمت ترجمة {rep:,} من أصل {tot:,} نص"
            )
        )
        self._locres_win = win
        win.show()
        win.raise_()
        win.activateWindow()
