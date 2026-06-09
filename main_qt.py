"""
main_qt.py  —  نقطة الدخول لنسخة PySide6
تشغيل:  python main_qt.py
"""

import sys
import os
import logging
import traceback
from datetime import datetime

# تأكد من أن جذر المشروع في الـ path
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


# ── Logging setup ─────────────────────────────────────────────────────────────

def _setup_logging() -> logging.Logger:
    logs_dir = os.path.join(ROOT, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    # Keep last 10 log files — rotate by date+session
    stamp   = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logfile = os.path.join(logs_dir, f"gat_{stamp}.log")

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    # File handler — captures everything DEBUG+
    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Console handler — WARNING+ only (keeps terminal clean)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(fh)
    root_logger.addHandler(ch)

    # Redirect bare print() from engine/backend modules to DEBUG log
    class _PrintInterceptor:
        def __init__(self, original, level):
            self._orig  = original
            self._level = level
        def write(self, msg):
            msg = msg.rstrip("\n")
            if msg:
                logging.log(self._level, msg)
            self._orig.write(msg + "\n" if msg else "")
        def flush(self):
            self._orig.flush()
        def isatty(self):
            return False

    sys.stdout = _PrintInterceptor(sys.__stdout__, logging.DEBUG)
    sys.stderr = _PrintInterceptor(sys.__stderr__, logging.ERROR)

    # Clean old logs — keep newest 10
    try:
        all_logs = sorted(
            [f for f in os.listdir(logs_dir) if f.startswith("gat_") and f.endswith(".log")],
            reverse=True,
        )
        for old in all_logs[10:]:
            os.remove(os.path.join(logs_dir, old))
    except Exception:
        pass

    return logging.getLogger("GAT"), logfile


# ── Uncaught exception hook ───────────────────────────────────────────────────

def _install_exception_hook(logger: logging.Logger):
    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical("UNCAUGHT EXCEPTION:\n%s", tb_str)
        # Still print to original stderr so the terminal shows it
        sys.__stderr__.write(tb_str)

    sys.excepthook = _hook

    # PySide6 threads swallow exceptions — catch them too
    try:
        from PySide6.QtCore import qInstallMessageHandler, QtMsgType

        def _qt_msg(msg_type, context, message):
            level_map = {
                QtMsgType.QtDebugMsg:    logging.DEBUG,
                QtMsgType.QtInfoMsg:     logging.INFO,
                QtMsgType.QtWarningMsg:  logging.WARNING,
                QtMsgType.QtCriticalMsg: logging.ERROR,
                QtMsgType.QtFatalMsg:    logging.CRITICAL,
            }
            lvl = level_map.get(msg_type, logging.WARNING)
            logging.getLogger("Qt").log(lvl, "[Qt] %s", message)

        qInstallMessageHandler(_qt_msg)
    except Exception:
        pass


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger, logfile = _setup_logging()
    _install_exception_hook(logger)

    logger.info("=" * 60)
    logger.info("Game Arabic Translator v1.1  —  بدء التشغيل")
    logger.info("Log file: %s", logfile)
    logger.info("Python: %s", sys.version.split()[0])
    logger.info("Platform: %s", sys.platform)
    logger.info("=" * 60)

    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui     import QFont, QIcon
        from PySide6.QtCore    import Qt

        from gui.qt.theme import theme
        from gui.qt.app   import MainWindow

        # HiDPI support
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

        from PySide6.QtCore import qInstallMessageHandler, QtMsgType
        # تحذيرات Qt حميدة معروفة نتجاهلها (ضوضاء console بلا أثر وظيفي):
        # - "Point size <= 0 (-1)": ينبعث من رسم الإيموجي/الرموز (🎮 ◆) عبر خط احتياطي
        #   لا يحمل حجماً صريحاً — Qt يستخدم الحجم الافتراضي تلقائياً، لا تأثير بصري.
        _QT_NOISE = ("point size", "qfont::setpointsize")
        def _qt_msg(mode, ctx, msg):
            low = msg.lower()
            if any(n in low for n in _QT_NOISE):
                return   # تجاهل صامت
            if 'parse' in low or 'stylesheet' in low:
                prefix = {QtMsgType.QtWarningMsg: 'WARN', QtMsgType.QtCriticalMsg: 'CRIT'}.get(mode, 'INFO')
                print(f"[QSS-{prefix}] {msg}")
                if ctx.file:
                    print(f"         file={ctx.file}:{ctx.line} fn={ctx.function}")
            else:
                if mode == QtMsgType.QtWarningMsg:
                    print(f"[Qt-WARN] {msg}")
        qInstallMessageHandler(_qt_msg)

        app = QApplication(sys.argv)
        app.setApplicationName("Game Arabic Translator")
        app.setApplicationVersion("1.1")

        # App icon — next to exe in frozen builds, next to main_qt.py in dev
        _app_root  = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else ROOT
        _icon_path = os.path.join(_app_root, "data", "icon.ico")
        if os.path.isfile(_icon_path):
            app.setWindowIcon(QIcon(_icon_path))

        app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        app.setFont(QFont(theme.font_family, theme.font_size))
        app.setStyleSheet(theme.qss())

        win = MainWindow()
        win.show()

        logger.info("النافذة الرئيسية جاهزة")
        exit_code = app.exec()
        logger.info("إغلاق التطبيق — exit code: %d", exit_code)
        sys.exit(exit_code)

    except Exception:
        logger.critical("فشل تشغيل التطبيق:\n%s", traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
