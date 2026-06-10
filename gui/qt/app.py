"""
gui/qt/app.py  —  النافذة الرئيسية لـ PySide6
"""

from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import zipfile

_CREATE_NO_WINDOW = 0x08000000   # win32 flag — suppresses console window entirely

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QStackedWidget,
    QLabel, QPushButton, QVBoxLayout, QFrame, QProgressBar, QMessageBox,
    QToolButton, QApplication
)
from PySide6.QtCore  import QThread, Signal, Qt
from PySide6.QtGui   import QFont, QDesktopServices, QCursor
from PySide6.QtCore  import QUrl

from gui.qt.theme           import theme
from gui.qt.widgets.sidebar import Sidebar


# ── Backend loader ────────────────────────────────────────────────────────────

class BackendLoader(QThread):
    ready          = Signal(object, object, object)   # engine, cache, game_manager
    registry_ready = Signal(object, object)           # translations_dict, update_info_or_None

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

        # Fetch online registry — only emit on success so retry button stays visible on failure
        try:
            from games.translation_registry import TranslationRegistry
            reg = TranslationRegistry()
            if reg.fetch(timeout=8):
                self.registry_ready.emit(reg.all_translations(), reg.has_update())
        except Exception as e:
            print(f"[BackendLoader registry] {e}")


# ── Update downloader ─────────────────────────────────────────────────────────

class UpdateDownloader(QThread):
    progress = Signal(int)        # 0-100
    done     = Signal(bool, str)  # success, extracted_dir_or_error

    def __init__(self, url: str, sha256: str = ""):
        super().__init__()
        self._url    = url
        self._sha256 = sha256 or ""

    def run(self):
        try:
            import urllib.request
            from games.security import ssl_context, verify_sha256
            ctx = ssl_context()   # تحقّق SSL موثَّق (certifi)

            tmp_dir  = tempfile.mkdtemp(prefix="GAT_update_")
            zip_path = os.path.join(tmp_dir, "update.zip")

            # تحميل مع إعادة محاولة (يعالج تقطّع الاتصال على النسخ الكبيرة)
            last_err = ""
            ok = False
            for attempt in range(3):
                try:
                    req = urllib.request.Request(
                        self._url, headers={"User-Agent": "GameArabicTranslator/1.0"})
                    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
                        total = int(resp.headers.get("Content-Length", 0))
                        downloaded = 0
                        with open(zip_path, "wb") as f:
                            while True:
                                chunk = resp.read(1 << 18)   # 256KB
                                if not chunk:
                                    break
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total:
                                    self.progress.emit(int(downloaded * 100 / total))
                    # تأكّد أن التحميل اكتمل (الحجم يطابق المتوقّع)
                    if total and os.path.getsize(zip_path) < total:
                        raise IOError(f"تحميل ناقص ({os.path.getsize(zip_path)}/{total})")
                    ok = True
                    break
                except Exception as e:
                    last_err = str(e)
                    if attempt < 2:
                        self.progress.emit(0)
            if not ok:
                self.done.emit(False, f"تعذّر إكمال التحميل بعد عدّة محاولات:\n{last_err}")
                return

            self.progress.emit(100)

            # تحقّق checksum (إن وُجد في المنفست) قبل الفكّ/التثبيت
            if not verify_sha256(zip_path, self._sha256):
                self.done.emit(False, "فشل التحقّق الأمني (sha256 لا يطابق) — أُلغي التحديث.")
                return

            # Extract ZIP — مسار قصير لتجنّب حدّ MAX_PATH (260) مع الملفات العميقة
            extract_dir = os.path.join(tempfile.gettempdir(), "GATx")
            try:
                if os.path.isdir(extract_dir):
                    import shutil as _sh
                    _sh.rmtree(extract_dir, ignore_errors=True)
            except Exception:
                pass
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(extract_dir)

            # ZIP contains GameArabicTranslator/ subfolder
            inner = os.path.join(extract_dir, "GameArabicTranslator")
            if not os.path.isdir(inner):
                inner = extract_dir   # fallback: files directly in zip root

            self.done.emit(True, inner)
        except Exception as e:
            self.done.emit(False, str(e))


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        try:
            from games.translation_registry import APP_VERSION as _ver
        except Exception:
            _ver = "?"
        self.setWindowTitle(f"Game Arabic Translator  v{_ver}  🎮")
        self.setMinimumSize(1100, 660)
        self.resize(1350, 820)

        self._engine       = None
        self._cache        = None
        self._game_manager = None
        self._proxy_server = None
        self._config:      dict = {}
        self._config_path: str  = ""
        self._pages: dict[str, QWidget] = {}

        self._build_ui()
        self._start_backend()

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.setCentralWidget(central)

        # ── Update banner (hidden until a newer version is detected) ─────────
        self._update_banner = QFrame()
        self._update_banner.setObjectName("updateBanner")
        self._update_banner.setStyleSheet(
            "#updateBanner { background: #2d6a2d; border-bottom: 1px solid #4a9e4a; }"
        )
        self._update_banner.setVisible(False)
        bl = QHBoxLayout(self._update_banner)
        bl.setContentsMargins(16, 6, 16, 6)
        bl.setSpacing(8)

        self._update_lbl = QLabel()
        self._update_lbl.setStyleSheet("color: #c8ffc8; font-size: 13px;")
        self._update_lbl.setLayoutDirection(Qt.RightToLeft)
        bl.addWidget(self._update_lbl, 1)

        # Progress bar (hidden while idle)
        self._update_progress = QProgressBar()
        self._update_progress.setRange(0, 100)
        self._update_progress.setFixedWidth(180)
        self._update_progress.setFixedHeight(18)
        self._update_progress.setVisible(False)
        self._update_progress.setStyleSheet(
            "QProgressBar { border:1px solid #4a9e4a; border-radius:3px;"
            " background:#1a3d1a; color:white; font-size:11px; text-align:center; }"
            "QProgressBar::chunk { background:#6fcf6f; border-radius:2px; }"
        )
        bl.addWidget(self._update_progress)

        self._update_btn = QPushButton("⬇️  تثبيت التحديث")
        self._update_btn.setStyleSheet(
            "QPushButton { background:#4a9e4a; color:white; border-radius:4px;"
            " padding:3px 12px; font-size:12px; }"
            "QPushButton:hover { background:#5abf5a; }"
            "QPushButton:disabled { background:#2d5a2d; color:#7ab07a; }"
        )
        self._update_btn.clicked.connect(self._start_update)
        bl.addWidget(self._update_btn)

        dismiss = QPushButton("✕")
        dismiss.setFixedWidth(28)
        dismiss.setStyleSheet(
            "QPushButton { background:transparent; color:#c8ffc8; border:none; font-size:14px; }"
        )
        dismiss.clicked.connect(lambda: self._update_banner.setVisible(False))
        bl.addWidget(dismiss)

        cl.addWidget(self._update_banner)

        # ── Translation-update banner (إشعار تحديث ترجمات الألعاب) ────────────
        self._trans_banner = QFrame()
        self._trans_banner.setObjectName("transBanner")
        self._trans_banner.setStyleSheet(
            "#transBanner { background: #1f4e79; border-bottom: 1px solid #2d6aa0; }"
        )
        self._trans_banner.setVisible(False)
        tbl = QHBoxLayout(self._trans_banner)
        tbl.setContentsMargins(16, 6, 16, 6)
        tbl.setSpacing(8)
        self._trans_lbl = QLabel()
        self._trans_lbl.setStyleSheet("color: #cfe6ff; font-size: 13px;")
        self._trans_lbl.setLayoutDirection(Qt.RightToLeft)
        tbl.addWidget(self._trans_lbl, 1)
        trans_btn = QPushButton("📥  عرض الألعاب")
        trans_btn.setStyleSheet(
            "QPushButton { background:#2d6aa0; color:white; border-radius:4px;"
            " padding:3px 12px; font-size:12px; }"
            "QPushButton:hover { background:#3a82c4; }"
        )
        trans_btn.clicked.connect(lambda: self._navigate("games"))
        tbl.addWidget(trans_btn)
        tdismiss = QPushButton("✕")
        tdismiss.setFixedWidth(28)
        tdismiss.setStyleSheet(
            "QPushButton { background:transparent; color:#cfe6ff; border:none; font-size:14px; }"
        )
        tdismiss.clicked.connect(lambda: self._trans_banner.setVisible(False))
        tbl.addWidget(tdismiss)
        cl.addWidget(self._trans_banner)

        # ── Main row: sidebar + page stack ───────────────────────────────────
        self._row = QWidget()
        rl  = QHBoxLayout(self._row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        cl.addWidget(self._row, 1)

        self._sidebar = Sidebar()
        self._sidebar.page_requested.connect(self._navigate)
        self._sidebar.admin_requested.connect(self._open_admin)
        self._sidebar.toggle_requested.connect(self._toggle_sidebar)
        rl.addWidget(self._sidebar)

        self._stack = QStackedWidget()
        rl.addWidget(self._stack, 1)

        # Floating ☰ button — visible only when sidebar is hidden
        self._sidebar_show_btn = QToolButton(self._row)
        self._sidebar_show_btn.setText("☰")
        self._sidebar_show_btn.setObjectName("sidebar_toggle_btn")
        self._sidebar_show_btn.setFixedSize(32, 32)
        self._sidebar_show_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._sidebar_show_btn.setToolTip("إظهار القائمة")
        self._sidebar_show_btn.clicked.connect(self._toggle_sidebar)
        self._sidebar_show_btn.setVisible(False)
        self._sidebar_show_btn.raise_()

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
        home.manage_game_requested.connect(self._manage_game)
        home.status_message.connect(self.statusBar().showMessage)
        self._pages["home"] = home
        self._stack.addWidget(home)

        settings = SettingsPage()
        settings.status_message.connect(self.statusBar().showMessage)
        settings.theme_changed.connect(self._on_theme_changed)
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
        games_page.games_changed.connect(
            lambda: self._pages["home"].refresh() if "home" in self._pages else None
        )
        games_page.translation_updates_available.connect(self._on_translation_updates)
        self._pages["games"] = games_page
        self._stack.addWidget(games_page)

        # ── صفحة الترجمة الفورية (المرحلة 6) ────────────────────────────────
        from gui.qt.pages.translate import TranslatePage
        translate_page = TranslatePage()
        translate_page.status_message.connect(self.statusBar().showMessage)
        translate_page.session_count.connect(self._on_session_translate)
        self._pages["translate"] = translate_page
        self._stack.addWidget(translate_page)

        # ── صفحة UnrealPak ──────────────────────────────────────────────────
        from gui.qt.pages.unrealpak import UnrealPakPage
        unrealpak_page = UnrealPakPage()
        unrealpak_page.status_message.connect(self.statusBar().showMessage)
        self._pages["unrealpak"] = unrealpak_page
        self._stack.addWidget(unrealpak_page)

        # ── صفحة ترجمة I2Languages JSON ─────────────────────────────────────
        from gui.qt.pages.i2_translate import I2TranslatePage
        i2_page = I2TranslatePage()
        i2_page.status_message.connect(self.statusBar().showMessage)
        self._pages["i2_translate"] = i2_page
        self._stack.addWidget(i2_page)

    # ── Theme refresh ─────────────────────────────────────────────────────────

    def _on_theme_changed(self):
        app = QApplication.instance()
        if app:
            app.setStyleSheet(theme.qss())
        for page in self._pages.values():
            if hasattr(page, "refresh_theme"):
                page.refresh_theme()

    # ── Navigation ────────────────────────────────────────────────────────────

    def _navigate(self, page_id: str):
        if page_id not in self._pages:
            return
        self._stack.setCurrentWidget(self._pages[page_id])
        self._sidebar.set_active_page(page_id)

    def _manage_game(self, game_id: str):
        """انتقل لصفحة الألعاب واختر اللعبة المحدَّدة (من زر 'إدارة اللعبة')."""
        self._navigate("games")
        games_page = self._pages.get("games")
        if games_page and hasattr(games_page, "select_game") and game_id:
            games_page.select_game(game_id)

    # ── Backend init ──────────────────────────────────────────────────────────

    def _start_backend(self):
        self._update_url: str = ""
        self._loader = BackendLoader()
        self._loader.ready.connect(self._on_backend_ready)
        self._loader.registry_ready.connect(self._on_registry_ready)
        self._loader.start()

    def _open_admin(self):
        from gui.qt.dialogs.admin_panel import open_admin
        panel = open_admin(
            game_manager=self._game_manager,
            cache=self._cache,
            config=self._config,
            config_path=self._config_path,
            parent=self,
        )
        if panel is None:
            return
        # Keep reference so GC doesn't collect it
        self._admin_panel = panel
        # Refresh games page whenever features are saved
        games_page = self._pages.get("games")
        if games_page:
            panel.features_saved.connect(games_page.refresh_game)

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

        # ── Translation proxy server ──────────────────────────────────────────
        from engine.proxy_server import ProxyServer
        self._proxy_server = ProxyServer(engine, cache)
        if games_page:
            games_page.set_proxy_server(self._proxy_server)
        if home:
            home.set_proxy_server(self._proxy_server)

        translate_page: "TranslatePage" = self._pages.get("translate")
        if translate_page:
            translate_page.set_backend(engine, cache)

        i2_page = self._pages.get("i2_translate")
        if i2_page and hasattr(i2_page, "set_backend"):
            i2_page.set_backend(engine, cache, game_manager)

        # ── Sidebar model chip ────────────────────────────────────────────────
        if engine:
            active = engine.get_active_model()
            if active:
                from gui.qt.pages.models import _meta
                self._sidebar.set_model_label(_meta(active)["ar"])

        self.statusBar().showMessage("✓  المحرك جاهز — مرحباً بك!")

    def _on_registry_ready(self, translations: dict, update_info):
        # Push translation data to Games page
        games_page = self._pages.get("games")
        if games_page and hasattr(games_page, "set_registry"):
            games_page.set_registry(translations)

        # Show update banner if a newer app version exists
        if update_info:
            ver   = update_info.get("version", "")
            notes = update_info.get("release_notes", "")
            self._update_url    = update_info.get("download_url", "")
            self._update_sha256 = update_info.get("sha256", "")
            self._update_lbl.setText(
                f"🚀  يتوفر إصدار جديد: v{ver}  —  انقر لتثبيت التحديث"
            )
            self._update_banner.setVisible(True)

    def _on_translation_updates(self, updates: dict):
        """يُظهر بانر إشعار عند توفّر تحديث لترجمة لعبة واحدة أو أكثر."""
        if not updates:
            self._trans_banner.setVisible(False)
            return
        n = len(updates)
        if n == 1:
            gid, ver = next(iter(updates.items()))
            txt = f"🔄  تحديث ترجمة متاح لـ «{gid}» ← v{ver}"
        else:
            txt = f"🔄  تحديث ترجمة متاح لـ {n} ألعاب: " + "، ".join(sorted(updates))
        self._trans_lbl.setText(txt)
        self._trans_banner.setVisible(True)

    # ── In-app update ─────────────────────────────────────────────────────────

    def _start_update(self):
        if not self._update_url:
            return

        # In dev (non-frozen) mode fall back to browser — no exe to replace
        if not getattr(sys, "frozen", False):
            QDesktopServices.openUrl(QUrl(self._update_url))
            return

        self._update_btn.setEnabled(False)
        self._update_btn.setText("جارٍ التحميل…")
        self._update_progress.setValue(0)
        self._update_progress.setVisible(True)
        self.statusBar().showMessage("⬇️  جارٍ تحميل التحديث…")

        self._downloader = UpdateDownloader(self._update_url, getattr(self, "_update_sha256", ""))
        self._downloader.progress.connect(self._on_update_progress)
        self._downloader.done.connect(self._on_update_done)
        self._downloader.start()

    def _on_update_progress(self, pct: int):
        self._update_progress.setValue(pct)
        self._update_btn.setText(f"جارٍ التحميل… {pct}%")
        self.statusBar().showMessage(f"⬇️  تحميل التحديث: {pct}%")

    def _update_log(self, msg: str):
        """يكتب خطوات التحديث في logs/update.log للتشخيص."""
        try:
            base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
            logdir = os.path.join(base, "logs")
            os.makedirs(logdir, exist_ok=True)
            with open(os.path.join(logdir, "update.log"), "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass

    def _update_failed(self, reason: str):
        """يُظهر فشل التحديث بوضوح + خيار التحميل اليدوي عبر المتصفّح."""
        self._update_log(f"FAILED: {reason}")
        self._update_progress.setVisible(False)
        self._update_btn.setEnabled(True)
        self._update_btn.setText("⬇️  تثبيت التحديث")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("تعذّر التحديث التلقائي")
        box.setText("لم يكتمل التحديث التلقائي:\n\n" + reason +
                    "\n\nيمكنك التحميل يدوياً من المتصفّح ثم استبدال الملفات.")
        b_browser = box.addButton("🌐 افتح صفحة التحميل", QMessageBox.AcceptRole)
        box.addButton("إغلاق", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == b_browser and getattr(self, "_update_url", ""):
            QDesktopServices.openUrl(QUrl(self._update_url))

    def _on_update_done(self, success: bool, path_or_error: str):
        if not success:
            self._update_failed(str(path_or_error))
            return
        try:
            self._apply_update(path_or_error)
        except Exception as e:
            import traceback
            self._update_log("EXC in _apply_update:\n" + traceback.format_exc())
            self._update_failed(f"خطأ أثناء تطبيق التحديث: {e}")

    def _apply_update(self, src: str):
        install_dir = os.path.dirname(sys.executable)
        exe_name    = os.path.basename(sys.executable)   # GameArabicTranslator.exe
        exe_path    = sys.executable

        # تحقّق أن النسخة الجديدة سليمة قبل لمس التثبيت
        new_exe = os.path.join(src, exe_name)
        if not os.path.isfile(new_exe):
            self._update_failed(f"الملف التنفيذي الجديد غير موجود في الأرشيف:\n{new_exe}")
            return
        self._update_log(f"apply: src={src} install={install_dir} new_exe_ok=True")

        bat_log   = os.path.join(install_dir, "logs", "update_bat.log")
        cache_dir = os.path.join(src, "data", "cache")
        logs_dir  = os.path.join(install_dir, "logs")
        # سجلّ الـ batch + استراتيجية آمنة (استثناء بيانات المستخدم + تبديل exe قابل للاستعادة)
        bat = "\r\n".join([
            "@echo off",
            "chcp 65001 >nul",
            f'echo [update] start %DATE% %TIME% > "{bat_log}"',
            "timeout /t 5 /nobreak >nul",
            f'robocopy "{src}" "{install_dir}" /E /IS /IT /NFL /NDL /NJH /NJS'
            f' /XF "{exe_name}" "config.json" /XD "{cache_dir}" "{logs_dir}"'
            f' /W:0 /R:1 >> "{bat_log}" 2>&1',
            f'echo [update] robocopy exit=%ERRORLEVEL% >> "{bat_log}"',
            f'if exist "{install_dir}\\{exe_name}.old" del /f /q "{install_dir}\\{exe_name}.old"',
            # حلقة: انتظر حتى يُفكّ قفل exe القديم (حتى ~15ث) ثم بدّله
            f'set /a _try=0',
            f':_renloop',
            f'ren "{install_dir}\\{exe_name}" "{exe_name}.old" 2>nul',
            f'if exist "{install_dir}\\{exe_name}" (',
            f'  set /a _try+=1',
            f'  if %_try% lss 15 ( timeout /t 1 /nobreak >nul & goto _renloop )',
            f')',
            f'copy /y "{src}\\{exe_name}" "{install_dir}\\{exe_name}" >> "{bat_log}" 2>&1',
            f'if exist "{install_dir}\\{exe_name}" (',
            f'  del /f /q "{install_dir}\\{exe_name}.old" 2>nul',
            f'  echo [update] exe replaced OK >> "{bat_log}"',
            f') else (',
            f'  ren "{install_dir}\\{exe_name}.old" "{exe_name}"',
            f'  echo [update] exe copy FAILED - restored old >> "{bat_log}"',
            f')',
            f'rmdir /s /q "{os.path.dirname(src)}" 2>nul',
            f'echo [update] launching >> "{bat_log}"',
            f'start "" "{exe_path}"',
            'del "%~f0"',
        ])
        bat_path = os.path.join(tempfile.gettempdir(), "gat_update.bat")
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(bat)
        self._update_log(f"apply: wrote bat → {bat_path}")

        subprocess.Popen(
            ["cmd", "/c", bat_path],
            creationflags=_CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._update_log("apply: launched updater, exiting in 600ms")
        self.statusBar().showMessage("✅  اكتمل التحميل — سيُغلق التطبيق ويُعاد تشغيله…")

        from PySide6.QtCore import QTimer
        QTimer.singleShot(600, lambda: os._exit(0))

    # ── Sidebar toggle ────────────────────────────────────────────────────────

    def _toggle_sidebar(self):
        if self._sidebar.isVisible():
            self._sidebar.setVisible(False)
            self._sidebar_show_btn.setVisible(True)
            self._position_show_btn()
        else:
            self._sidebar.setVisible(True)
            self._sidebar_show_btn.setVisible(False)

    def _position_show_btn(self):
        btn = self._sidebar_show_btn
        row = self._row
        # Sidebar is on the physical right (RTL layout) → button at top-right
        btn.move(row.width() - btn.width() - 6, 6)
        btn.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, '_sidebar_show_btn') and self._sidebar_show_btn.isVisible():
            self._position_show_btn()

    # ── Window events ─────────────────────────────────────────────────────────

    def closeEvent(self, event):
        tp = self._pages.get("translate")
        if tp and hasattr(tp, "cancel_worker"):
            tp.cancel_worker()
        i2p = self._pages.get("i2_translate")
        if i2p and hasattr(i2p, "cancel_worker"):
            i2p.cancel_worker()
        if self._proxy_server and self._proxy_server.is_running:
            self._proxy_server.stop()
        event.accept()

    def _on_session_translate(self, count: int):
        home: "HomePage" = self._pages.get("home")
        if home:
            home.increment_session(count)
