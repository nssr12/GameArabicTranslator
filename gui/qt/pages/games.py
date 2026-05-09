"""
gui/qt/pages/games.py  —  صفحة الألعاب (المرحلة 5)
"""

from __future__ import annotations
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QMessageBox, QSpacerItem, QProgressBar,
)
from PySide6.QtCore  import Qt, Signal, QThread
from PySide6.QtGui   import QCursor, QFont

from gui.qt.theme              import theme
from gui.qt.widgets.page_header import make_topbar


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
        proc = self._cfg.get("process_name", "")
        proc_lbl = QLabel(proc if proc else "—")
        proc_lbl.setStyleSheet(
            f"font-size: 10px; color: {c['muted']};"
            " background: transparent; border: none;"
        )
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
            background: rgba(0,0,0,0.25);
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

    edit_requested      = Signal(str)        # game_id
    delete_requested    = Signal(str)        # game_id
    translate_requested = Signal(str)        # game_id
    iostore_requested   = Signal(str, dict)  # game_id, cfg
    install_requested   = Signal(str, str)   # game_id, game_path
    uninstall_requested = Signal(str, str)   # game_id, game_path
    download_requested       = Signal(str)   # game_id
    check_registry_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._game_id       = None
        self._game_cfg      = {}
        self._registry_info: dict = {}
        self._registry_loaded: bool = False
        self._dl_progress   = None
        self._dl_lbl        = None
        self._build_empty()

    def _build_empty(self):
        c   = theme.c
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        placeholder = QLabel("اختر لعبة من القائمة لعرض تفاصيلها")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet(
            f"color: {c['muted']}; font-size: 14px;"
            " background: transparent; border: none;"
        )
        lay.addStretch()
        lay.addWidget(placeholder)
        lay.addStretch()
        self._placeholder_lay = lay

    def load(self, game_id: str, cfg: dict, cache=None):
        self._game_id  = game_id
        self._game_cfg = cfg

        # Clear existing layout — setParent(None) hides immediately, deleteLater frees memory
        while self.layout().count():
            item = self.layout().takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        self._render(cfg, cache)

    def _render(self, cfg: dict, cache):
        c   = theme.c
        lay = self.layout()
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
                    background: rgba(0,0,0,0.15);
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

        actions_lay.addWidget(
            _btn("ترجمة ملفات اللعبة", "accent",
                 lambda: self.translate_requested.emit(self._game_id), "🌐")
        )

        # IoStore wizard — only for Unreal games
        if eng_key in ("ue4", "ue5", "unreal"):
            actions_lay.addWidget(
                _btn("📦  IoStore / UAsset Wizard", "purple",
                     lambda gid=self._game_id, c=cfg: self.iostore_requested.emit(gid, c), "")
            )

        actions_lay.addWidget(
            _btn("تعديل الإعدادات", "blue",
                 lambda: self.edit_requested.emit(self._game_id), "✏️")
        )
        actions_lay.addWidget(
            _btn("حذف اللعبة", "accent",
                 lambda: self.delete_requested.emit(self._game_id), "🗑️")
        )

        lay.addWidget(actions_card)

        # ── Translation package card ──────────────────────────────────────────
        self._render_package_card(lay, cfg)

        lay.addStretch()

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


# ── Games page ────────────────────────────────────────────────────────────────

class GamesPage(QWidget):
    """صفحة إدارة الألعاب — قائمة يسار + تفاصيل يمين."""

    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine       = None
        self._cache        = None
        self._game_manager = None
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

        # Right: detail panel
        right = QWidget()
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
        self._dl_worker: DownloadWorker | None = None

        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        right_lay.addWidget(self._detail)

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

    def set_registry(self, registry_info: dict):
        """Pass {game_id: translation_info} from TranslationRegistry to detail panel."""
        self._detail._registry_info  = registry_info
        self._detail._registry_loaded = True
        if self._detail._game_id:
            self._detail.load(self._detail._game_id, self._detail._game_cfg)

    def retry_registry(self):
        """Re-fetch registry in background and update the detail panel."""
        from PySide6.QtCore import QThread, Signal as Sig

        class _Fetcher(QThread):
            done = Sig(dict)
            def run(self):
                try:
                    from games.translation_registry import TranslationRegistry
                    reg = TranslationRegistry()
                    self.done.emit(reg.all_translations() if reg.fetch() else {})
                except Exception:
                    self.done.emit({})

        self._reg_fetcher = _Fetcher()
        self._reg_fetcher.done.connect(self.set_registry)
        self._reg_fetcher.start()
        self.status_message.emit("🔄  جارٍ التحقق من الترجمات المتاحة…")

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

    def _after_save(self, game_id: str, cfg: dict):
        self.status_message.emit(f"✓  تم حفظ: {cfg.get('name', game_id)}")
        self.refresh()
