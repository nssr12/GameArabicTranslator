"""
gui/qt/pages/games.py  —  صفحة الألعاب (المرحلة 5)
"""

from __future__ import annotations
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QMessageBox, QSpacerItem, QProgressBar,
    QSplitter, QPlainTextEdit, QCheckBox, QSpinBox, QComboBox,
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

        os.makedirs(self._ready_dir, exist_ok=True)
        files = self._info.get("files", [])
        total_size = sum(f.get("size", 0) for f in files)
        done = 0

        for fi in files:
            if self._cancel:
                self.finished.emit(False, "إلغاء")
                return
            name = fi["name"]
            url  = fi["url"]
            dest = os.path.join(self._ready_dir, name)
            try:
                r = requests.get(url, stream=True, timeout=60)
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._game_id       = None
        self._game_cfg      = {}
        self._registry_info: dict = {}
        self._registry_loaded: bool = False
        self._dl_progress   = None
        self._dl_lbl        = None
        self._proxy_server  = None
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

        actions_lay.addWidget(
            _btn("حذف اللعبة", "accent",
                 lambda: self.delete_requested.emit(self._game_id), "🗑️")
        )

        lay.addWidget(actions_card)

        lay.addStretch()

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

        sb_lay.addWidget(self._pending_lbl)
        sb_lay.addWidget(self._rate_lbl)
        sb_lay.addWidget(self._engine_lbl)
        sb_lay.addWidget(self._cache_lbl)
        sb_lay.addWidget(self._unchanged_lbl)
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

        tag_lbl = QLabel("🏷  معالجة التاقات:")
        self._tag_mode_combo = QComboBox()
        self._tag_mode_combo.addItem("🏷 Inline — تاقات تبقى مع النص", "inline")
        self._tag_mode_combo.addItem("🔒 Strip — تجريد كامل بـ PUA", "strip")
        self._tag_mode_combo.addItem("🎯 Tiered — متدرّج", "tiered")
        self._tag_mode_combo.addItem("🛡 Bulletproof — ⟦N⟧ + تحقق + fallback (موصى به)", "bulletproof")
        self._tag_mode_combo.setToolTip(
            "Inline: تُترك التاقات داخل النص للمودل (سياق كامل، لكن قد يفشل مع تاقات معقدة).\n"
            "Strip: كل التاقات تُستبدل بمحارف PUA — قد يحذفها بعض المودلات.\n"
            "Tiered: <b>/<i> تبقى inline، <color>/<size>/<sprite> تُستبدل بـ [tN]/[sN].\n"
            "🛡 Bulletproof: علامات ⟦N⟧ + تحقق صارم + سلسلة fallback (bulletproof→tiered→strip).\n"
            "  عند فشل كل المحاولات، يُعاد النص الأصلي ويُسجَّل كـ failed لإعادة المحاولة بمودل آخر."
        )
        self._tag_mode_combo.currentIndexChanged.connect(self._on_tag_mode_changed)
        # نسق ColorBox مع الـ theme
        self._tag_mode_combo.setStyleSheet(
            f"QComboBox {{ background: {c['bg']}; color: {c['secondary']};"
            f"             border: 1px solid {c['border']}; border-radius: 4px;"
            f"             padding: 2px 4px; font-size: 11px; min-width: 220px; }}"
        )

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
        cb_lay.addWidget(self._tag_mode_combo)
        cb_lay.addStretch()
        cb_lay.addWidget(timeout_lbl)
        cb_lay.addWidget(self._timeout_spin)
        lay.addWidget(self._ctrl_bar)

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

        self.setStyleSheet(
            f"LogPanel {{ background: {c['surface']};"
            f" border-top: 1px solid {c['border']}; }}"
        )

        clear_btn.clicked.connect(self._txt.clear)
        self.log_message.connect(self._append)
        self.stats_signal.connect(self._on_stats)

        # مؤقّت يُحدّث المعدل كل نصف ثانية حتى لو لم تصل ترجمات جديدة
        self._proxy_ref = None
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(500)
        self._stats_timer.timeout.connect(self._poll_stats)
        self._stats_timer.start()

    def _append(self, msg: str):
        self._txt.appendPlainText(msg)
        sb = self._txt.verticalScrollBar()
        sb.setValue(sb.maximum())

    def append(self, msg: str):
        """واجهة عامة — آمنة من أي خيط (تستخدم Signal داخلياً)."""
        self.log_message.emit(msg)

    def attach_proxy(self, proxy):
        """يربط البروكسي لتحديث الإحصاءات وعرض الإعدادات الحالية."""
        self._proxy_ref = proxy
        if proxy:
            proxy.stats_callback = self.stats_signal.emit
            self._on_stats(proxy.get_stats())
            # زامن واجهة tag_mode مع البروكسي
            current = proxy.get_tag_mode() if hasattr(proxy, "get_tag_mode") else "inline"
            idx = self._tag_mode_combo.findData(current)
            if idx >= 0:
                self._tag_mode_combo.blockSignals(True)
                self._tag_mode_combo.setCurrentIndex(idx)
                self._tag_mode_combo.blockSignals(False)
            self._timeout_spin.blockSignals(True)
            self._timeout_spin.setValue(int(proxy.get_timeout()))
            self._timeout_spin.blockSignals(False)
        else:
            self._on_stats({"pending": 0, "engine_count": 0, "cache_count": 0, "rate_per_sec": 0})

    def _poll_stats(self):
        if self._proxy_ref and self._proxy_ref.is_running:
            self._on_stats(self._proxy_ref.get_stats())

    def _on_tag_mode_changed(self, index: int):
        if not self._proxy_ref:
            return
        mode = self._tag_mode_combo.itemData(index) or "inline"
        try:
            self._proxy_ref.set_tag_mode(mode)
        except Exception:
            pass

    def _on_timeout_changed(self, value: int):
        if not self._proxy_ref:
            return
        try:
            self._proxy_ref.set_timeout(float(value))
        except Exception:
            pass

    def _on_stats(self, s: dict):
        self._pending_lbl.setText(f"⏳  في الانتظار: {s.get('pending', 0)}")
        self._rate_lbl.setText(f"⚡  المعدل: {s.get('rate_per_sec', 0)}/ث")
        self._engine_lbl.setText(f"🔄  مترجَم: {s.get('engine_count', 0)}")
        self._cache_lbl.setText(f"📦  من الكاش: {s.get('cache_count', 0)}")
        self._unchanged_lbl.setText(f"⏭  بلا تغيير: {s.get('unchanged_count', 0)}")


# ── Games page ────────────────────────────────────────────────────────────────

class GamesPage(QWidget):
    """صفحة إدارة الألعاب — قائمة يسار + تفاصيل يمين."""

    status_message = Signal(str)
    games_changed  = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine       = None
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
        self._detail.check_registry_requested.connect(self.retry_registry)
        self._detail.locres_requested.connect(self._on_locres_translate)
        self._detail.font_requested.connect(self._on_font_replace)
        self._detail.bepinex_install_requested.connect(self._on_bepinex_install)
        self._detail.bepinex_uninstall_requested.connect(self._on_bepinex_uninstall)
        self._detail.bepinex_update_requested.connect(self._on_bepinex_update)
        self._detail.bepinex_import_requested.connect(self._on_bepinex_import)
        self._detail.bepinex_import_from_requested.connect(self._on_bepinex_import_from)
        self._detail.bepinex_copy_dll_requested.connect(self._on_bepinex_copy_dll)
        self._detail.bepinex_collect_requested.connect(self._on_bepinex_collect)
        self._detail.bepinex_collect_from_requested.connect(self._on_bepinex_collect_from)
        self._detail.proxy_server_toggle_requested.connect(self._on_proxy_server_toggle)
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
        self._detail._registry_info   = registry_info
        self._detail._registry_loaded = bool(registry_info)  # True only when data received
        if self._detail._game_id:
            self._detail.load(self._detail._game_id, self._detail._game_cfg)

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
        from games.translation_package import TranslationPackage
        registry_info = getattr(self._detail, '_registry_info', {})
        info = registry_info.get(game_id)
        if not info:
            QMessageBox.warning(self, "تحميل", "معلومات التحميل غير متاحة.")
            return
        if self._dl_worker and self._dl_worker.isRunning():
            return

        ready_dir = TranslationPackage().get_ready_dir(game_id)
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
                if ok:
                    self.status_message.emit(f"✅  {msg}")
                    self.refresh()
                else:
                    QMessageBox.warning(self, "فشل التحميل", msg)

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
            # توليد translations.txt تلقائياً بعد إيقاف الـ proxy
            self._auto_export_translations(game_id)
        else:
            game_cfg = self._game_manager.get_game(game_id) if self._game_manager else {}
            ok, msg  = proxy.start(game_id, cfg=game_cfg or {})
            self.status_message.emit(msg)
            if not ok:
                QMessageBox.warning(self, "خطأ في الخادم", msg)

        # تحديث البطاقة لتعكس الحالة الجديدة
        if self._detail._game_id == game_id:
            self._detail.load(game_id, self._detail._game_cfg)

    def _auto_export_translations(self, game_id: str):
        """يُولِّد translations.txt من الكاش بعد جلسة الترجمة — صامت، لا يُظهر رسائل خطأ."""
        try:
            if not self._game_manager or not self._cache:
                return
            cfg = self._game_manager.get_game(game_id) or {}
            if "bepinex_mod" not in cfg:
                return
            game_path = cfg.get("game_path", "")
            if not game_path or not os.path.isdir(game_path):
                return
            from games.bepinex_mod import BepInExMod
            ok, msg, count = BepInExMod().export_static_translations_txt(cfg, game_path, self._cache)
            if ok and count:
                self.status_message.emit(f"📝  تم تحديث translations.txt  ({count:,} ترجمة)")
        except Exception as e:
            print(f"[auto_export] {e}")


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
