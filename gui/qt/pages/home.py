"""
gui/qt/pages/home.py  —  الصفحة الرئيسية / Dashboard
"""
from __future__ import annotations
import os
import re
import sys
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QScrollArea, QGridLayout, QSizePolicy, QLineEdit, QComboBox,
    QButtonGroup,
)
from PySide6.QtCore  import Qt, Signal, QSize, QThread
from PySide6.QtGui   import QCursor, QPixmap, QPainter

from gui.qt.theme import theme


# ── Cover image label (CSS background-size: cover equivalent) ─────────────────

class _CoverLabel(QLabel):
    def __init__(self, path: str, height: int = 160, parent=None):
        super().__init__(parent)
        self._pm = QPixmap(path)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(
            "background: transparent; border: none;"
            " border-top-left-radius: 10px; border-top-right-radius: 10px;"
        )

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


# ── Stat card ─────────────────────────────────────────────────────────────────

class StatCard(QFrame):
    def __init__(self, icon: str, title: str, value: str,
                 color_key: str = "blue", parent=None):
        super().__init__(parent)
        self._color_key = color_key
        self._icon_str  = icon
        self._title_str = title
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(100)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(4)

        top = QHBoxLayout()
        self._ico_lbl = QLabel(icon)
        top.addWidget(self._ico_lbl)
        top.addStretch()

        self._val_lbl   = QLabel(value)
        self._title_lbl = QLabel(title)

        lay.addLayout(top)
        lay.addWidget(self._val_lbl)
        lay.addWidget(self._title_lbl)
        self._apply_theme()

    def _apply_theme(self):
        c     = theme.c
        color = c.get(self._color_key, c["blue"])
        self.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {c['card']}, stop:1 {c['card2']});
                border: 1px solid {c['border']};
                border-left: 3px solid {color};
                border-radius: 10px;
            }}
        """)
        self._ico_lbl.setStyleSheet(
            f"font-size: 22px; background: transparent; border: none; color: {color};"
        )
        self._val_lbl.setStyleSheet(
            f"font-size: 26px; font-weight: bold; color: {c['primary']};"
            " background: transparent; border: none;"
        )
        self._title_lbl.setStyleSheet(
            f"font-size: 11px; color: {c['muted']};"
            " background: transparent; border: none;"
        )

    def update_value(self, value: str):
        self._val_lbl.setText(value)

    def update_theme(self):
        self._apply_theme()


# ── Game card ─────────────────────────────────────────────────────────────────

ENGINE_COLORS = {
    "unity":  ("purple", "Unity"),
    "ue4":    ("blue",   "Unreal 4"),
    "ue5":    ("blue",   "Unreal 5"),
    "unreal": ("blue",   "Unreal"),
    "other":  ("muted",  "أخرى"),
}

if getattr(sys, 'frozen', False):
    _IMG_DIR = os.path.join(os.path.dirname(sys.executable), "data", "game_images")
else:
    _IMG_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))),
        "data", "game_images"
    )


def _find_steam_appid(game_path: str) -> str:
    """Find Steam appid from game_path by reading appmanifest ACF files."""
    if not game_path:
        return ""
    parts = os.path.normpath(game_path).replace("\\", "/").split("/")
    steamapps = ""
    install_dir = ""
    for i, part in enumerate(parts):
        if part.lower() == "steamapps":
            steamapps = "/".join(parts[:i + 1])
            if i + 2 < len(parts) and parts[i + 1].lower() == "common":
                install_dir = parts[i + 2]
            break
    if not steamapps or not install_dir or not os.path.isdir(steamapps):
        return ""
    idir_lower = install_dir.lower()
    for fname in os.listdir(steamapps):
        if not fname.startswith("appmanifest_") or not fname.endswith(".acf"):
            continue
        try:
            content = open(
                os.path.join(steamapps, fname), encoding="utf-8", errors="replace"
            ).read()
            appid_m = re.search(r'"appid"\s+"(\d+)"', content)
            dir_m   = re.search(r'"installdir"\s+"([^"]+)"', content)
            if appid_m and dir_m and dir_m.group(1).lower() == idir_lower:
                return appid_m.group(1)
        except Exception:
            pass
    return ""


class _CoverFetchWorker(QThread):
    """تحمّل صور الغلاف من Steam CDN لكل لعبة بدون صورة."""
    cover_ready = Signal(str)   # game_id

    def __init__(self, games: list, img_dir: str):
        super().__init__()
        self._games   = games    # [(game_id, cfg), ...]
        self._img_dir = img_dir

    def run(self):
        import urllib.request
        os.makedirs(self._img_dir, exist_ok=True)
        for game_id, cfg in self._games:
            game_name = cfg.get("name", game_id)
            appid     = _find_steam_appid(cfg.get("game_path", ""))
            if not appid:
                continue
            url  = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"
            dest = os.path.join(self._img_dir, game_name + ".jpg")
            try:
                urllib.request.urlretrieve(url, dest)
                self.cover_ready.emit(game_id)
            except Exception:
                pass


def _find_cover(game_id: str, cfg: dict) -> str:
    for stem in [cfg.get("name", game_id), game_id]:
        for ext in (".png", ".jpg", ".jpeg"):
            p = os.path.join(_IMG_DIR, stem + ext)
            if os.path.isfile(p):
                return p
    return ""


class GameCard(QFrame):
    translate_requested = Signal(str)
    detail_requested    = Signal(str)   # game_id — نقرة على جسم الكارد

    def __init__(self, game_id: str, game_config: dict,
                 cache_count: int = 0, parent=None):
        super().__init__(parent)
        c = theme.c
        self._id  = game_id
        self._cfg = game_config
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setObjectName("card_hover")
        self.setStyleSheet(f"""
            QFrame#card_hover {{
                background-color: {c['card']};
                border: 1px solid {c['border']};
                border-radius: 10px;
            }}
            QFrame#card_hover:hover {{
                background-color: {c['hover']};
                border-color: {c['muted']};
            }}
        """)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._build(game_id, game_config, cache_count)

    def _build(self, game_id: str, cfg: dict, cache_count: int):
        c          = theme.c
        cover_path = _find_cover(game_id, cfg)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Cover ──────────────────────────────────────────────────────────────
        if cover_path:
            lay.addWidget(_CoverLabel(cover_path, 155))
        else:
            # placeholder gradient
            ph = QFrame()
            ph.setFixedHeight(80)
            ph.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            ph.setStyleSheet(
                f"QFrame {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                f" stop:0 {c['surface']}, stop:1 {c['card2']});"
                " border: none; border-top-left-radius: 10px; border-top-right-radius: 10px; }"
            )
            icon_lbl = QLabel("🎮")
            icon_lbl.setAlignment(Qt.AlignCenter)
            icon_lbl.setStyleSheet("font-size: 32px; background: transparent; border: none;")
            ph_lay = QVBoxLayout(ph)
            ph_lay.setContentsMargins(0, 0, 0, 0)
            ph_lay.addWidget(icon_lbl)
            lay.addWidget(ph)

        # ── Info ───────────────────────────────────────────────────────────────
        inner = QVBoxLayout()
        inner.setContentsMargins(14, 10, 14, 10)
        inner.setSpacing(6)
        lay.addLayout(inner)

        # Engine badge + name
        engine_raw = cfg.get("engine", cfg.get("type", "other")).lower()
        eng_key    = ("ue5"   if "ue5"    in engine_raw else
                      "ue4"   if ("ue4" in engine_raw or "unreal" in engine_raw) else
                      "unity" if "unity"  in engine_raw else "other")
        eng_color, eng_label = ENGINE_COLORS.get(eng_key, ("muted", engine_raw))
        clr = c.get(eng_color, c["muted"])

        top = QHBoxLayout()
        badge = QLabel(eng_label)
        badge.setStyleSheet(
            f"background: rgba(0,0,0,89); color: {clr}; border: 1px solid {clr};"
            " border-radius: 8px; padding: 1px 9px; font-size: 10px; font-weight: bold;"
        )
        name_lbl = QLabel(cfg.get("name", game_id))
        name_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {c['primary']};"
            " background: transparent; border: none;"
        )
        name_lbl.setWordWrap(False)
        top.addWidget(badge)
        top.addWidget(name_lbl, 1)
        inner.addLayout(top)

        # Path
        path = cfg.get("game_path", "")
        if path:
            p = path if len(path) < 50 else "…" + path[-47:]
            pl = QLabel(p)
            pl.setStyleSheet(
                f"color: {c['muted']}; font-size: 10px; background: transparent; border: none;"
            )
            inner.addWidget(pl)

        inner.addStretch()

        # Cache + translate
        bot = QHBoxLayout()
        cl = QLabel(f"💾  {cache_count:,} ترجمة في الكاش")
        cl.setStyleSheet(
            f"color: {c['teal']}; font-size: 10px; background: transparent; border: none;"
        )
        tb = QPushButton("ترجمة ▶")
        tb.setObjectName("btn_primary")
        tb.setFixedHeight(28)
        tb.setCursor(QCursor(Qt.PointingHandCursor))
        tb.clicked.connect(lambda: self.translate_requested.emit(self._id))
        bot.addWidget(cl, 1)
        bot.addWidget(tb)
        inner.addLayout(bot)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.detail_requested.emit(self._id)
        super().mousePressEvent(event)


# ── Home page ─────────────────────────────────────────────────────────────────

class HomePage(QWidget):
    navigate_requested      = Signal(str)
    manage_game_requested   = Signal(str)   # game_id → فتح صفحة الألعاب على لعبة محدّدة
    status_message          = Signal(str)

    _MIN_CARD_W = 290   # minimum card width for column calculation
    _GRID_GAP   = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine       = None
        self._cache        = None
        self._game_manager = None
        self._proxy_server = None
        self._stat_cards:  dict[str, StatCard] = {}
        self._all_games:   list[tuple[str, dict, int]] = []   # (id, cfg, cache_cnt)
        self._current_cols = 3
        self._search_text  = ""
        self._engine_filter = ""
        self._sort_key     = "name"
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._hero = self._build_hero()
        lay.addWidget(self._hero)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; } QScrollArea > QWidget { background: transparent; }")
        self._scroll = scroll

        content = QWidget()
        content.setObjectName("home_content")
        self._content_lay = QVBoxLayout(content)
        self._content_lay.setContentsMargins(24, 20, 24, 28)
        self._content_lay.setSpacing(20)

        self._content_lay.addLayout(self._build_stats_row())
        self._content_lay.addWidget(self._build_games_section())
        self._content_lay.addStretch()

        scroll.setWidget(content)
        lay.addWidget(scroll, 1)

    # ── Hero ──────────────────────────────────────────────────────────────────

    def _build_hero(self) -> QFrame:
        c    = theme.c
        hero = QFrame()
        hero.setObjectName("home_hero")

        lay = QHBoxLayout(hero)
        lay.setContentsMargins(24, 14, 24, 14)

        vlay = QVBoxLayout()
        vlay.setSpacing(3)
        self._greeting_lbl = QLabel("🎮  مرحباً بك في Game Arabic Translator")
        now = datetime.now()
        self._date_lbl = QLabel(now.strftime("%A  •  %d / %m / %Y"))
        vlay.addWidget(self._greeting_lbl)
        vlay.addWidget(self._date_lbl)
        lay.addLayout(vlay, 1)

        cache_btn = QPushButton("💾  استعراض الكاش")
        cache_btn.setObjectName("btn_secondary")
        cache_btn.clicked.connect(lambda: self.navigate_requested.emit("cache"))
        lay.addWidget(cache_btn)

        self._apply_hero_theme(hero)
        return hero

    def _apply_hero_theme(self, hero: QFrame = None):
        c = theme.c
        h = hero or self._hero
        h.setStyleSheet(f"""
            QFrame#home_hero {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {c['card']}, stop:0.5 {c['card2']}, stop:1 {c['surface']});
                border-bottom: 1px solid {c['border']};
                min-height: 72px;
                max-height: 72px;
            }}
        """)
        self._greeting_lbl.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {c['primary']};"
            " background: transparent; border: none;"
        )
        self._date_lbl.setStyleSheet(
            f"font-size: 11px; color: {c['muted']}; background: transparent; border: none;"
        )

    # ── Stats row ─────────────────────────────────────────────────────────────

    def _build_stats_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)
        for key, icon, val, title, color in [
            ("games",   "🎮", "0", "الألعاب المُضافة",   "accent"),
            ("cache",   "💾", "0", "الترجمات المحفوظة",  "teal"),
            ("model",   "🤖", "—", "النموذج النشط",       "green"),
            ("session", "⚡", "0", "ترجمات هذه الجلسة",  "yellow"),
        ]:
            card = StatCard(icon, title, val, color)
            self._stat_cards[key] = card
            row.addWidget(card)
        return row

    # ── Games section ─────────────────────────────────────────────────────────

    def _build_games_section(self) -> QWidget:
        c  = theme.c
        w  = QWidget()
        w.setObjectName("home_games_section")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # ── Section header ────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("🎮  الألعاب المُضافة")
        title.setObjectName("page_section_lbl")
        hdr.addWidget(title)
        hdr.addStretch()
        all_btn = QPushButton("إدارة الألعاب ←")
        all_btn.setObjectName("btn_secondary")
        all_btn.clicked.connect(lambda: self.navigate_requested.emit("games"))
        hdr.addWidget(all_btn)
        lay.addLayout(hdr)

        # ── Search / filter toolbar ───────────────────────────────────────────
        toolbar = QFrame()
        toolbar.setObjectName("home_toolbar_frame")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(10, 8, 10, 8)
        tl.setSpacing(8)

        # Grid / List toggle
        self._grid_btn = QPushButton("⊞  شبكة")
        self._list_btn = QPushButton("≡  قائمة")
        for btn, active in ((self._grid_btn, True), (self._list_btn, False)):
            btn.setCheckable(True)
            btn.setChecked(active)
            btn.setFixedHeight(30)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._view_group = QButtonGroup(self)
        self._view_group.addButton(self._grid_btn, 0)
        self._view_group.addButton(self._list_btn, 1)
        self._view_group.setExclusive(True)
        self._grid_btn.clicked.connect(lambda: self._on_view_change(0))
        self._list_btn.clicked.connect(lambda: self._on_view_change(1))
        self._style_toggle_btns(c)
        tl.addWidget(self._grid_btn)
        tl.addWidget(self._list_btn)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color: {c['border']}; background: {c['border']}; max-width: 1px;")
        tl.addWidget(sep)

        # Engine filter
        self._engine_combo = QComboBox()
        self._engine_combo.setFixedHeight(30)
        self._engine_combo.setMinimumWidth(130)
        for label, val in [
            ("كل الأنواع", ""),
            ("Unity",      "unity"),
            ("Unreal 4",   "ue4"),
            ("Unreal 5",   "ue5"),
            ("أخرى",      "other"),
        ]:
            self._engine_combo.addItem(label, val)
        self._engine_combo.currentIndexChanged.connect(
            lambda _: self._on_filter_change()
        )
        theme.style_combo(self._engine_combo)
        tl.addWidget(self._engine_combo)

        # Sort by
        self._sort_combo = QComboBox()
        self._sort_combo.setFixedHeight(30)
        self._sort_combo.setMinimumWidth(130)
        for label, val in [
            ("ترتيب: الاسم",     "name"),
            ("ترتيب: الكاش",     "cache"),
        ]:
            self._sort_combo.addItem(label, val)
        self._sort_combo.currentIndexChanged.connect(
            lambda _: self._on_filter_change()
        )
        theme.style_combo(self._sort_combo)
        tl.addWidget(self._sort_combo)

        tl.addStretch()

        # Search
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("🔍  بحث عن لعبة…")
        self._search_edit.setFixedHeight(30)
        self._search_edit.setMinimumWidth(200)
        self._search_edit.textChanged.connect(self._on_search)
        tl.addWidget(self._search_edit)

        lay.addWidget(toolbar)

        # ── Games grid ────────────────────────────────────────────────────────
        self._grid_container = QWidget()
        self._grid_container.setObjectName("home_grid_container")
        self._games_grid = QGridLayout(self._grid_container)
        self._games_grid.setSpacing(self._GRID_GAP)
        lay.addWidget(self._grid_container)

        self._empty_lbl = QLabel("لا توجد ألعاب مُضافة — اذهب إلى صفحة الألعاب لإضافة لعبة")
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setObjectName("empty_state_lbl")
        lay.addWidget(self._empty_lbl)

        return w

    def _style_toggle_btns(self, c: dict):
        for btn, checked in ((self._grid_btn, self._grid_btn.isChecked()),
                              (self._list_btn, self._list_btn.isChecked())):
            if checked:
                btn.setStyleSheet(
                    f"QPushButton {{ background: {c['accent']}22; color: {c['accent']};"
                    f" border: 1px solid {c['accent']}; border-radius: 6px;"
                    f" font-size: 11px; padding: 0 12px; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background: transparent; color: {c['muted']};"
                    f" border: 1px solid {c['border']}; border-radius: 6px;"
                    f" font-size: 11px; padding: 0 12px; }}"
                    f"QPushButton:hover {{ color: {c['primary']}; border-color: {c['muted']}; }}"
                )

    # ── Filter / search logic ─────────────────────────────────────────────────

    def _on_search(self, text: str):
        self._search_text = text.strip().lower()
        self._rebuild_grid()

    def _on_filter_change(self):
        self._engine_filter = self._engine_combo.currentData() or ""
        self._sort_key      = self._sort_combo.currentData()   or "name"
        self._rebuild_grid()

    def _on_view_change(self, _):
        self._style_toggle_btns(theme.c)
        self._rebuild_grid()

    def _filtered_games(self) -> list[tuple[str, dict, int]]:
        games = list(self._all_games)
        if self._search_text:
            games = [
                g for g in games
                if self._search_text in g[1].get("name", g[0]).lower()
            ]
        if self._engine_filter:
            def _match(cfg):
                raw = cfg.get("engine", cfg.get("type", "other")).lower()
                if self._engine_filter == "ue4":
                    return "ue4" in raw or ("unreal" in raw and "ue5" not in raw)
                if self._engine_filter == "ue5":
                    return "ue5" in raw
                if self._engine_filter == "unity":
                    return "unity" in raw
                if self._engine_filter == "other":
                    return not any(k in raw for k in ("ue4", "ue5", "unreal", "unity"))
                return True
            games = [g for g in games if _match(g[1])]
        if self._sort_key == "cache":
            games.sort(key=lambda g: g[2], reverse=True)
        else:
            games.sort(key=lambda g: g[1].get("name", g[0]).lower())
        return games

    # ── Responsive grid ───────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._rebuild_grid()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebuild_grid()

    def _calc_cols(self) -> int:
        available = self.width() - 48 - 20   # margins + scrollbar
        if available <= 0:
            return 3
        cols = max(1, available // (self._MIN_CARD_W + self._GRID_GAP))
        return min(cols, 4)

    def _rebuild_grid(self):
        cols  = self._calc_cols()
        games = self._filtered_games()

        # Clear
        while self._games_grid.count():
            item = self._games_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not games:
            self._empty_lbl.setVisible(True)
            msg = "لا توجد نتائج مطابقة" if (self._search_text or self._engine_filter) else \
                  "لا توجد ألعاب مُضافة — اذهب إلى صفحة الألعاب لإضافة لعبة"
            self._empty_lbl.setText(msg)
            return

        self._empty_lbl.setVisible(False)
        for i, (game_id, cfg, cnt) in enumerate(games):
            card = GameCard(game_id, cfg, cnt)
            card.translate_requested.connect(
                lambda _: self.navigate_requested.emit("games")
            )
            card.detail_requested.connect(self._open_game_detail)
            self._games_grid.addWidget(card, i // cols, i % cols)

        self._current_cols = cols

    def _open_game_detail(self, game_id: str):
        from gui.qt.dialogs.game_detail_dialog import GameDetailDialog
        cfg = self._game_manager.get_game(game_id) if self._game_manager else {}
        if not cfg:
            return
        dlg = GameDetailDialog(
            game_id, cfg, self._cache,
            game_manager=self._game_manager,
            proxy=self._proxy_server,
            parent=self,
        )
        # ينقلنا لصفحة الألعاب ويختار اللعبة المحدَّدة (وليس أول لعبة)
        dlg.manage_requested.connect(
            lambda gid: self.manage_game_requested.emit(gid or game_id)
        )
        dlg.exec()

    # ── Data refresh ──────────────────────────────────────────────────────────

    def set_backend(self, engine, cache, game_manager):
        self._engine       = engine
        self._cache        = cache
        self._game_manager = game_manager
        self.refresh()

    def set_proxy_server(self, proxy):
        self._proxy_server = proxy

    def refresh(self):
        self._update_stats()
        self._update_games()

    def _update_stats(self):
        games = []
        if self._game_manager:
            try:
                games = self._game_manager.get_all_games()
            except Exception:
                pass
        self._stat_cards["games"].update_value(str(len(games)))

        total_cache = 0
        if self._cache:
            try:
                for g in self._cache.get_all_games():
                    total_cache += self._cache.count_entries(g)
            except Exception:
                pass
        self._stat_cards["cache"].update_value(f"{total_cache:,}")

        if self._engine:
            active = self._engine.get_active_model()
            from gui.qt.pages.models import _meta
            ar = _meta(active)["ar"] if active else "—"
            self._stat_cards["model"].update_value(ar if len(ar) < 14 else ar[:13] + "…")

    def _update_games(self):
        self._all_games.clear()
        games = []
        if self._game_manager:
            try:
                games = self._game_manager.get_all_games()
            except Exception:
                pass

        for game in games:
            game_id  = game if isinstance(game, str) else game.get("id", "")
            game_cfg = game if isinstance(game, dict) else {}
            if self._game_manager and hasattr(self._game_manager, "get_game"):
                try:
                    cfg = self._game_manager.get_game(game_id)
                    if cfg:
                        game_cfg = cfg
                except Exception:
                    pass
            cnt = 0
            if self._cache:
                try:
                    cnt = self._cache.count_entries(game_cfg.get("name", game_id))
                except Exception:
                    pass
            self._all_games.append((game_id, game_cfg, cnt))

        self._rebuild_grid()
        self._auto_fetch_covers()

    def _auto_fetch_covers(self):
        """تحميل صور الغلاف التلقائي لكل لعبة بدون صورة محلية (من Steam CDN)."""
        missing = [
            (gid, cfg) for gid, cfg, _ in self._all_games
            if not _find_cover(gid, cfg)
        ]
        if not missing:
            return
        if hasattr(self, '_cover_worker') and self._cover_worker.isRunning():
            return
        self._cover_worker = _CoverFetchWorker(missing, _IMG_DIR)
        self._cover_worker.cover_ready.connect(lambda _: self._rebuild_grid())
        self._cover_worker.start()

    def refresh_theme(self):
        self._apply_hero_theme()
        for card in self._stat_cards.values():
            card.update_theme()
        self._style_toggle_btns(theme.c)
        theme.style_combo(self._engine_combo)
        theme.style_combo(self._sort_combo)
        self._update_games()

    def increment_session(self, count: int = 1):
        try:
            cur = int(self._stat_cards["session"]._val_lbl.text().replace(",", ""))
        except Exception:
            cur = 0
        self._stat_cards["session"].update_value(f"{cur + count:,}")
