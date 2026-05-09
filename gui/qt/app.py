"""
gui/qt/app.py  —  النافذة الرئيسية لـ PySide6
"""

from __future__ import annotations
import json
import os
import sys

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QStackedWidget
)
from PySide6.QtCore  import QThread, Signal
from PySide6.QtGui   import QFont

from gui.qt.theme           import theme
from gui.qt.widgets.sidebar import Sidebar


# ── Backend loader ────────────────────────────────────────────────────────────

class BackendLoader(QThread):
    ready = Signal(object, object, object)   # engine, cache, game_manager

    def run(self):
        try:
            from engine.translator  import TranslationEngine
            from engine.cache       import TranslationCache
            from games.game_manager import GameManager

            if getattr(sys, 'frozen', False):
                root = os.path.dirname(sys.executable)
            else:
                root = os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__))))

            engine       = TranslationEngine(os.path.join(root, "config.json"))
            cache        = TranslationCache(
                os.path.join(root, "data", "cache", "translations.db"))
            game_manager = GameManager(
                os.path.join(root, "games", "configs"))

            # Auto-load the active model on startup — fast for Ollama/Google/API,
            # skipped for HuggingFace (requires heavy download/RAM load).
            active = engine.get_active_model()
            if active:
                model_type = (engine._config.get("models", {})
                              .get(active, {}).get("type", ""))
                if model_type not in ("huggingface",):
                    try:
                        engine.load_model(active)
                    except Exception:
                        pass

            self.ready.emit(engine, cache, game_manager)
        except Exception as e:
            print(f"[BackendLoader] {e}")
            self.ready.emit(None, None, None)


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Game Arabic Translator  v2.0  🎮")
        self.setMinimumSize(1100, 660)
        self.resize(1350, 820)

        self._engine       = None
        self._cache        = None
        self._game_manager = None
        self._config:      dict = {}
        self._config_path: str  = ""
        self._pages: dict[str, QWidget] = {}

        self._build_ui()
        self._start_backend()

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        rl   = QHBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        self.setCentralWidget(root)

        self._sidebar = Sidebar()
        self._sidebar.page_requested.connect(self._navigate)
        self._sidebar.admin_requested.connect(self._open_admin)
        rl.addWidget(self._sidebar)

        self._stack = QStackedWidget()
        rl.addWidget(self._stack, 1)

        self.statusBar().showMessage("جاري تحميل المحرك...")
        self._register_pages()
        self._navigate("home")

    def _register_pages(self):
        # ── صفحات مكتملة ─────────────────────────────────────────────────────
        from gui.qt.pages.home     import HomePage
        from gui.qt.pages.settings import SettingsPage
        from gui.qt.pages.models   import ModelsPage
        from gui.qt.pages.cache    import CachePage

        home = HomePage()
        home.navigate_requested.connect(self._navigate)
        home.status_message.connect(self.statusBar().showMessage)
        self._pages["home"] = home
        self._stack.addWidget(home)

        settings = SettingsPage()
        settings.status_message.connect(self.statusBar().showMessage)
        self._pages["settings"] = settings
        self._stack.addWidget(settings)

        models = ModelsPage()
        models.model_activated.connect(self._sidebar.set_model_label)
        models.model_activated.connect(lambda _: home._update_stats())
        models.model_activated.connect(lambda _: self._pages.get("translate") and
                                       self._pages["translate"]._refresh_model_badge())
        models.status_message.connect(self.statusBar().showMessage)
        self._pages["models"] = models
        self._stack.addWidget(models)

        cache = CachePage(cache=None, engine=None)
        cache.status_message.connect(self.statusBar().showMessage)
        self._pages["cache"] = cache
        self._stack.addWidget(cache)

        # ── صفحة الألعاب (المرحلة 5) ─────────────────────────────────────────
        from gui.qt.pages.games import GamesPage
        games_page = GamesPage()
        games_page.status_message.connect(self.statusBar().showMessage)
        self._pages["games"] = games_page
        self._stack.addWidget(games_page)

        # ── صفحة الترجمة الفورية (المرحلة 6) ────────────────────────────────
        from gui.qt.pages.translate import TranslatePage
        translate_page = TranslatePage()
        translate_page.status_message.connect(self.statusBar().showMessage)
        translate_page.session_count.connect(self._on_session_translate)
        self._pages["translate"] = translate_page
        self._stack.addWidget(translate_page)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _navigate(self, page_id: str):
        if page_id not in self._pages:
            return
        self._stack.setCurrentWidget(self._pages[page_id])
        self._sidebar.set_active_page(page_id)

    # ── Backend init ──────────────────────────────────────────────────────────

    def _start_backend(self):
        self._loader = BackendLoader()
        self._loader.ready.connect(self._on_backend_ready)
        self._loader.start()

    def _open_admin(self):
        from gui.qt.dialogs.admin_panel import open_admin
        open_admin(
            game_manager=self._game_manager,
            cache=self._cache,
            config=self._config,
            config_path=self._config_path,
            parent=self,
        )

    def _on_backend_ready(self, engine, cache, game_manager):
        self._engine       = engine
        self._cache        = cache
        self._game_manager = game_manager

        # load config for admin panel
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        self._config_path = os.path.join(root, "config.json")
        try:
            with open(self._config_path, encoding="utf-8") as f:
                self._config = json.load(f)
        except Exception:
            self._config = {}

        # ── Inject into each page ─────────────────────────────────────────────

        home: "HomePage" = self._pages.get("home")
        if home:
            home.set_backend(engine, cache, game_manager)

        models_page: "ModelsPage" = self._pages.get("models")
        if models_page and engine:
            models_page.set_engine(engine)

        cache_page: "CachePage" = self._pages.get("cache")
        if cache_page:
            cache_page._cache  = cache
            cache_page._engine = engine
            cache_page.refresh()

        games_page: "GamesPage" = self._pages.get("games")
        if games_page:
            games_page.set_backend(engine, cache, game_manager)

        translate_page: "TranslatePage" = self._pages.get("translate")
        if translate_page:
            translate_page.set_backend(engine, cache)

        # ── Sidebar model chip ────────────────────────────────────────────────
        if engine:
            active = engine.get_active_model()
            if active:
                from gui.qt.pages.models import _meta
                self._sidebar.set_model_label(_meta(active)["ar"])

        self.statusBar().showMessage("✓  المحرك جاهز — مرحباً بك!")

    def closeEvent(self, event):
        tp = self._pages.get("translate")
        if tp and hasattr(tp, "cancel_worker"):
            tp.cancel_worker()
        event.accept()

    def _on_session_translate(self, count: int):
        home: "HomePage" = self._pages.get("home")
        if home:
            home.increment_session(count)
