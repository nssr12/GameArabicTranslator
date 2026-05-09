"""
gui/qt/pages/home.py  —  الصفحة الرئيسية / Dashboard (المرحلة 4)
"""

from __future__ import annotations
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QScrollArea, QGridLayout, QSizePolicy
)
from PySide6.QtCore  import Qt, Signal
from PySide6.QtGui   import QCursor, QFont

from gui.qt.theme import theme


# ── Stat card ─────────────────────────────────────────────────────────────────

class StatCard(QFrame):
    def __init__(self, icon: str, title: str, value: str,
                 color_key: str = "blue", parent=None):
        super().__init__(parent)
        c = theme.c
        color = c.get(color_key, c["blue"])
        self.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 {c['card']}, stop:1 {c['card2']});
                border: 1px solid {c['border']};
                border-left: 3px solid {color};
                border-radius: 10px;
            }}
        """)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(100)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(6)

        top = QHBoxLayout()
        ico = QLabel(icon)
        ico.setStyleSheet(
            f"font-size: 22px; background: transparent; border: none; color: {color};"
        )
        top.addWidget(ico)
        top.addStretch()

        self._val_lbl = QLabel(value)
        self._val_lbl.setStyleSheet(
            f"font-size: 26px; font-weight: bold; color: {c['primary']};"
            f" background: transparent; border: none;"
        )

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"font-size: 12px; color: {c['muted']};"
            f" background: transparent; border: none;"
        )

        lay.addLayout(top)
        lay.addWidget(self._val_lbl)
        lay.addWidget(title_lbl)

    def update_value(self, value: str):
        self._val_lbl.setText(value)


# ── Game card ─────────────────────────────────────────────────────────────────

ENGINE_COLORS = {
    "unity":  ("purple", "Unity"),
    "ue4":    ("blue",   "Unreal 4"),
    "ue5":    ("blue",   "Unreal 5"),
    "unreal": ("blue",   "Unreal"),
    "other":  ("muted",  "أخرى"),
}

class GameCard(QFrame):
    """بطاقة لعبة واحدة في الشبكة."""

    translate_requested = Signal(str)  # game_id

    def __init__(self, game_id: str, game_config: dict,
                 cache_count: int = 0, parent=None):
        super().__init__(parent)
        c = theme.c
        self._id = game_id
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
        self.setFixedHeight(155)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._build(game_id, game_config, cache_count)

    def _build(self, game_id: str, cfg: dict, cache_count: int):
        c = theme.c
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        # Top row: name + engine badge
        top = QHBoxLayout()
        name = QLabel(cfg.get("name", game_id))
        name.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {c['primary']};"
            f" background: transparent; border: none;"
        )
        name.setWordWrap(False)

        engine_raw = cfg.get("engine", cfg.get("type", "other")).lower()
        eng_key    = "ue5" if "ue5" in engine_raw else \
                     "ue4" if "ue4" in engine_raw or "unreal" in engine_raw else \
                     "unity" if "unity" in engine_raw else "other"
        eng_color, eng_label = ENGINE_COLORS.get(eng_key, ("muted", engine_raw))
        clr = c.get(eng_color, c["muted"])

        badge = QLabel(eng_label)
        badge.setStyleSheet(f"""
            background: rgba(0,0,0,0.3);
            color: {clr};
            border: 1px solid {clr};
            border-radius: 8px;
            padding: 1px 9px;
            font-size: 10px;
            font-weight: bold;
        """)
        top.addWidget(name, 1)
        top.addWidget(badge)
        lay.addLayout(top)

        # Game path (truncated)
        path = cfg.get("game_path", "")
        if path:
            path_lbl = QLabel(path if len(path) < 55 else "…" + path[-52:])
            path_lbl.setStyleSheet(
                f"color: {c['muted']}; font-size: 10px;"
                f" background: transparent; border: none;"
            )
            lay.addWidget(path_lbl)

        lay.addStretch()

        # Bottom row: cache count + translate button
        bot = QHBoxLayout()
        cache_lbl = QLabel(f"💾  {cache_count:,} ترجمة في الكاش")
        cache_lbl.setStyleSheet(
            f"color: {c['teal']}; font-size: 11px;"
            f" background: transparent; border: none;"
        )
        bot.addWidget(cache_lbl, 1)

        trans_btn = QPushButton("ترجمة ▶")
        trans_btn.setObjectName("btn_primary")
        trans_btn.setFixedHeight(30)
        trans_btn.setCursor(QCursor(Qt.PointingHandCursor))
        trans_btn.clicked.connect(lambda: self.translate_requested.emit(self._id))
        bot.addWidget(trans_btn)
        lay.addLayout(bot)


# ── Section header ────────────────────────────────────────────────────────────

def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {theme.c['secondary']}; font-size: 15px; font-weight: bold;"
        f" background: transparent; border: none;"
    )
    return lbl


# ── Home page ─────────────────────────────────────────────────────────────────

class HomePage(QWidget):
    """الصفحة الرئيسية — لوحة المعلومات."""

    navigate_requested  = Signal(str)   # للتنقل من بطاقة لعبة إلى صفحة الألعاب
    status_message      = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine       = None
        self._cache        = None
        self._game_manager = None
        self._stat_cards: dict[str, StatCard] = {}
        self._game_cards: dict[str, GameCard] = {}
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        c   = theme.c
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_hero())

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background: {c['bg']}; border: none;")

        content = QWidget()
        content.setStyleSheet(f"background: {c['bg']};")
        self._content_lay = QVBoxLayout(content)
        self._content_lay.setContentsMargins(28, 22, 28, 30)
        self._content_lay.setSpacing(22)

        self._content_lay.addLayout(self._build_stats_row())
        self._content_lay.addWidget(self._build_games_section())
        self._content_lay.addStretch()

        scroll.setWidget(content)
        lay.addWidget(scroll, 1)

    def _build_hero(self) -> QFrame:
        c = theme.c
        hero = QFrame()
        hero.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 {c['card']}, stop:0.5 {c['card2']}, stop:1 {c['surface']});
                border-bottom: 1px solid {c['border']};
                min-height: 76px;
                max-height: 76px;
            }}
        """)
        lay = QHBoxLayout(hero)
        lay.setContentsMargins(28, 16, 28, 16)

        # Greeting
        vlay = QVBoxLayout()
        vlay.setSpacing(3)
        greeting = QLabel("🎮  مرحباً بك في Game Arabic Translator")
        greeting.setStyleSheet(
            f"font-size: 19px; font-weight: bold; color: {c['primary']};"
            f" background: transparent; border: none;"
        )
        now = datetime.now()
        date_lbl = QLabel(now.strftime("%A  •  %d / %m / %Y"))
        date_lbl.setStyleSheet(
            f"font-size: 12px; color: {c['muted']};"
            f" background: transparent; border: none;"
        )
        vlay.addWidget(greeting)
        vlay.addWidget(date_lbl)
        lay.addLayout(vlay, 1)

        # Quick action
        cache_btn = QPushButton("💾  استعراض الكاش")
        cache_btn.setObjectName("btn_secondary")
        cache_btn.clicked.connect(lambda: self.navigate_requested.emit("cache"))
        lay.addWidget(cache_btn)

        return hero

    def _build_stats_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(16)

        cards = [
            ("games",    "🎮",  "0", "الألعاب المُضافة",       "accent"),
            ("cache",    "💾",  "0", "الترجمات المحفوظة",      "teal"),
            ("model",    "🤖",  "—", "النموذج النشط",          "green"),
            ("session",  "⚡",  "0", "ترجمات هذه الجلسة",      "yellow"),
        ]
        for key, icon, val, title, color in cards:
            card = StatCard(icon, title, val, color)
            self._stat_cards[key] = card
            row.addWidget(card)

        return row

    def _build_games_section(self) -> QWidget:
        c = theme.c
        w = QWidget()
        w.setStyleSheet(f"background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        hdr = QHBoxLayout()
        hdr.addWidget(_section_label("🎮  الألعاب المُضافة"))
        hdr.addStretch()
        all_btn = QPushButton("إدارة الألعاب ←")
        all_btn.setObjectName("btn_secondary")
        all_btn.clicked.connect(lambda: self.navigate_requested.emit("games"))
        hdr.addWidget(all_btn)
        lay.addLayout(hdr)

        self._games_grid = QGridLayout()
        self._games_grid.setSpacing(14)
        lay.addLayout(self._games_grid)

        # Empty state (shown until games load)
        self._empty_lbl = QLabel("لا توجد ألعاب مُضافة — اذهب إلى صفحة الألعاب لإضافة لعبة")
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setStyleSheet(
            f"color: {c['muted']}; font-size: 13px; padding: 30px;"
            f" background: transparent; border: none;"
        )
        lay.addWidget(self._empty_lbl)

        return w

    # ── Data refresh ──────────────────────────────────────────────────────────

    def set_backend(self, engine, cache, game_manager):
        self._engine       = engine
        self._cache        = cache
        self._game_manager = game_manager
        self.refresh()

    def refresh(self):
        self._update_stats()
        self._update_games()

    def _update_stats(self):
        # Games count
        games = []
        if self._game_manager:
            try:
                games = self._game_manager.get_all_games()
            except Exception:
                pass
        self._stat_cards["games"].update_value(str(len(games)))

        # Cache count
        total_cache = 0
        if self._cache:
            try:
                for g in self._cache.get_all_games():
                    total_cache += self._cache.count_entries(g)
            except Exception:
                pass
        self._stat_cards["cache"].update_value(f"{total_cache:,}")

        # Active model
        if self._engine:
            active = self._engine.get_active_model()
            from gui.qt.pages.models import _meta
            ar = _meta(active)["ar"] if active else "—"
            self._stat_cards["model"].update_value(ar if len(ar) < 14 else ar[:13] + "…")

    def _update_games(self):
        # Clear grid
        while self._games_grid.count():
            item = self._games_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._game_cards.clear()

        games = []
        if self._game_manager:
            try:
                games = self._game_manager.get_all_games()
            except Exception:
                pass

        if not games:
            self._empty_lbl.setVisible(True)
            return

        self._empty_lbl.setVisible(False)
        cols = 3
        for i, game in enumerate(games):
            game_id  = game if isinstance(game, str) else game.get("id", str(i))
            game_cfg = game if isinstance(game, dict) else {}
            if self._game_manager and hasattr(self._game_manager, "get_game"):
                try:
                    cfg = self._game_manager.get_game(game_id)
                    if cfg:
                        game_cfg = cfg
                except Exception:
                    pass

            # Cache count for this game
            name       = game_cfg.get("name", game_id)
            cache_cnt  = 0
            if self._cache:
                try:
                    cache_cnt = self._cache.count_entries(name)
                except Exception:
                    pass

            card = GameCard(game_id, game_cfg, cache_cnt)
            card.translate_requested.connect(
                lambda gid: self.navigate_requested.emit("games")
            )
            self._game_cards[game_id] = card
            self._games_grid.addWidget(card, i // cols, i % cols)

    def increment_session(self, count: int = 1):
        """يُستدعى من خارج الصفحة عند كل ترجمة ناجحة."""
        try:
            cur = int(self._stat_cards["session"]._val_lbl.text().replace(",", ""))
        except Exception:
            cur = 0
        self._stat_cards["session"].update_value(f"{cur + count:,}")
