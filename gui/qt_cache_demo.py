"""
gui/qt_cache_demo.py  —  PySide6 cache page demo
Run:  python -m gui.qt_cache_demo
"""

import sys
import os
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QDialog, QTextEdit, QScrollArea, QAbstractItemView,
    QSizePolicy, QMessageBox, QSplitter, QGraphicsDropShadowEffect,
    QToolButton, QButtonGroup, QStackedWidget, QProgressBar, QScrollBar
)
from PySide6.QtCore import (
    Qt, QThread, Signal, QTimer, QPropertyAnimation, QEasingCurve,
    QSize, QPoint, QRect, QSortFilterProxyModel
)
from PySide6.QtGui import (
    QFont, QColor, QPalette, QPainter, QBrush, QLinearGradient,
    QTextOption, QIcon, QPixmap, QFontDatabase, QCursor, QPen
)

from engine.cache import TranslationCache

# ── Palette ──────────────────────────────────────────────────────────────────
C = {
    "bg":        "#0d1117",
    "surface":   "#161b22",
    "card":      "#1c2333",
    "card2":     "#21262d",
    "border":    "#30363d",
    "accent":    "#e94560",
    "accent2":   "#f85c7a",
    "blue":      "#388bfd",
    "blue2":     "#58a6ff",
    "green":     "#3fb950",
    "green2":    "#56d364",
    "teal":      "#00d2ff",
    "yellow":    "#d29922",
    "muted":     "#8b949e",
    "secondary": "#c9d1d9",
    "primary":   "#e6edf3",
    "sidebar":   "#0d1117",
    "hover":     "#1f2937",
    "selected":  "#1d3a6e",
    "row_alt":   "#161b22",
    "row_even":  "#0d1117",
}

QSS = f"""
/* ── Global ─────────────────────────────────────────────────────────── */
QWidget {{
    font-family: 'Segoe UI', 'Tahoma', sans-serif;
    font-size: 13px;
    color: {C['primary']};
    background-color: {C['bg']};
    outline: none;
}}
QMainWindow {{
    background-color: {C['bg']};
}}

/* ── Sidebar ─────────────────────────────────────────────────────────── */
#sidebar {{
    background-color: {C['sidebar']};
    border-right: 1px solid {C['border']};
    min-width: 220px;
    max-width: 220px;
}}
#sidebar_header {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 #1a1a3e, stop:1 #2a0f1e);
    border-bottom: 1px solid {C['border']};
    padding: 20px 15px;
}}
#app_title {{
    color: {C['accent']};
    font-size: 18px;
    font-weight: bold;
    letter-spacing: 1px;
}}
#app_sub {{
    color: {C['muted']};
    font-size: 11px;
}}

QPushButton#game_btn {{
    background: transparent;
    color: {C['secondary']};
    border: none;
    border-left: 3px solid transparent;
    padding: 9px 15px 9px 14px;
    text-align: left;
    font-size: 13px;
    border-radius: 0px;
}}
QPushButton#game_btn:hover {{
    background-color: {C['hover']};
    color: {C['primary']};
}}
QPushButton#game_btn[active=true] {{
    background-color: {C['hover']};
    border-left: 3px solid {C['accent']};
    color: {C['primary']};
    font-weight: bold;
}}

/* ── Top bar ─────────────────────────────────────────────────────────── */
#topbar {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {C['surface']}, stop:1 {C['card']});
    border-bottom: 1px solid {C['border']};
    padding: 0 20px;
    min-height: 58px;
    max-height: 58px;
}}
#page_title {{
    color: {C['primary']};
    font-size: 19px;
    font-weight: bold;
}}

/* ── Stat chips ──────────────────────────────────────────────────────── */
#stat_chip {{
    background-color: {C['card2']};
    border: 1px solid {C['border']};
    border-radius: 12px;
    padding: 3px 12px;
    font-size: 12px;
    color: {C['muted']};
}}
#stat_chip_green  {{ border-color: {C['green']};  color: {C['green2']}; }}
#stat_chip_blue   {{ border-color: {C['blue']};   color: {C['blue2']};  }}
#stat_chip_accent {{ border-color: {C['accent']}; color: {C['accent2']};}}

/* ── Toolbar ─────────────────────────────────────────────────────────── */
#toolbar {{
    background-color: {C['surface']};
    border-bottom: 1px solid {C['border']};
    padding: 8px 16px;
}}

QLineEdit#search_box {{
    background-color: {C['card2']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 6px 12px 6px 32px;
    color: {C['primary']};
    font-size: 13px;
    selection-background-color: {C['blue']};
}}
QLineEdit#search_box:focus {{
    border-color: {C['blue']};
    background-color: {C['card']};
}}

QComboBox {{
    background-color: {C['card2']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 5px 10px;
    color: {C['secondary']};
    selection-background-color: {C['card']};
}}
QComboBox:hover {{ border-color: {C['muted']}; }}
QComboBox:focus {{ border-color: {C['blue']}; }}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox::down-arrow {{
    width: 10px;
    height: 10px;
    image: none;
}}
QComboBox QAbstractItemView {{
    background-color: {C['card2']};
    border: 1px solid {C['border']};
    selection-background-color: {C['selected']};
    color: {C['primary']};
    outline: none;
}}

/* ── Action buttons ──────────────────────────────────────────────────── */
QPushButton#btn_edit {{
    background-color: {C['card2']};
    color: {C['secondary']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
}}
QPushButton#btn_edit:hover {{
    background-color: {C['hover']};
    border-color: {C['muted']};
    color: {C['primary']};
}}

QPushButton#btn_retrans {{
    background-color: rgba(56, 139, 253, 0.15);
    color: {C['blue2']};
    border: 1px solid rgba(56, 139, 253, 0.4);
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
}}
QPushButton#btn_retrans:hover {{
    background-color: rgba(56, 139, 253, 0.25);
    border-color: {C['blue']};
}}

QPushButton#btn_delete {{
    background-color: rgba(233, 69, 96, 0.15);
    color: {C['accent2']};
    border: 1px solid rgba(233, 69, 96, 0.4);
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
}}
QPushButton#btn_delete:hover {{
    background-color: rgba(233, 69, 96, 0.25);
    border-color: {C['accent']};
}}

QPushButton#btn_primary {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {C['accent']}, stop:1 #c0392b);
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: bold;
}}
QPushButton#btn_primary:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {C['accent2']}, stop:1 {C['accent']});
}}

QPushButton#btn_secondary {{
    background-color: {C['card2']};
    color: {C['secondary']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 13px;
}}
QPushButton#btn_secondary:hover {{
    background-color: {C['hover']};
    border-color: {C['muted']};
    color: {C['primary']};
}}

/* ── Table ───────────────────────────────────────────────────────────── */
QTableWidget {{
    background-color: {C['bg']};
    alternate-background-color: {C['row_alt']};
    gridline-color: {C['border']};
    border: none;
    color: {C['primary']};
    selection-background-color: {C['selected']};
    selection-color: {C['primary']};
    font-size: 13px;
}}
QTableWidget::item {{
    padding: 8px 14px;
    border-bottom: 1px solid {C['border']};
}}
QTableWidget::item:hover {{
    background-color: {C['hover']};
}}
QTableWidget::item:selected {{
    background-color: {C['selected']};
}}
QHeaderView::section {{
    background-color: {C['surface']};
    color: {C['muted']};
    padding: 10px 14px;
    border: none;
    border-bottom: 2px solid {C['border']};
    border-right: 1px solid {C['border']};
    font-weight: bold;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QHeaderView::section:last {{ border-right: none; }}

QScrollBar:vertical {{
    background: {C['surface']};
    width: 8px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {C['border']};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {C['muted']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {C['surface']};
    height: 8px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {C['border']};
    border-radius: 4px;
}}
QScrollBar::handle:horizontal:hover {{ background: {C['muted']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ── Pagination bar ──────────────────────────────────────────────────── */
#pagebar {{
    background-color: {C['surface']};
    border-top: 1px solid {C['border']};
    padding: 8px 16px;
}}

QPushButton#page_btn {{
    background-color: {C['card2']};
    color: {C['secondary']};
    border: 1px solid {C['border']};
    border-radius: 5px;
    padding: 5px 12px;
    font-size: 12px;
    min-width: 70px;
}}
QPushButton#page_btn:hover {{
    background-color: {C['hover']};
    border-color: {C['muted']};
    color: {C['primary']};
}}
QPushButton#page_btn:disabled {{
    color: {C['border']};
    border-color: {C['surface']};
}}

#page_info {{
    color: {C['muted']};
    font-size: 12px;
}}

/* ── Status bar ──────────────────────────────────────────────────────── */
QStatusBar {{
    background-color: {C['surface']};
    color: {C['muted']};
    border-top: 1px solid {C['border']};
    font-size: 12px;
    padding: 3px 12px;
}}

/* ── Dialog ──────────────────────────────────────────────────────────── */
QDialog {{
    background-color: {C['surface']};
}}
#dialog_header {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 #1a1a3e, stop:1 #2a0f1e);
    border-bottom: 1px solid {C['border']};
    padding: 20px 24px;
}}
#dialog_title {{
    color: {C['primary']};
    font-size: 16px;
    font-weight: bold;
}}
#dialog_game_label {{
    color: {C['muted']};
    font-size: 12px;
}}
#field_label {{
    color: {C['muted']};
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QTextEdit {{
    background-color: {C['card2']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    color: {C['primary']};
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 13px;
    padding: 10px;
    selection-background-color: {C['selected']};
}}
QTextEdit:focus {{
    border-color: {C['blue']};
}}
QTextEdit:read-only {{
    background-color: {C['card']};
    color: {C['muted']};
}}

/* ── Progress bar ────────────────────────────────────────────────────── */
QProgressBar {{
    background-color: {C['card2']};
    border: 1px solid {C['border']};
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {C['blue']}, stop:1 {C['teal']});
    border-radius: 4px;
}}
"""


# ── Worker thread for re-translation ─────────────────────────────────────────
class RetranslateWorker(QThread):
    progress = Signal(int, int)       # done, total
    log      = Signal(str)
    finished = Signal(int, int)       # done, failed

    def __init__(self, entries, translation_engine, cache):
        super().__init__()
        self._entries = entries
        self._engine  = translation_engine
        self._cache   = cache
        self._stop    = False

    def stop(self):
        self._stop = True

    def run(self):
        done, failed = 0, 0
        total = len(self._entries)
        for i, entry in enumerate(self._entries):
            if self._stop:
                break
            orig  = entry["original"]
            game  = entry.get("game", "")
            try:
                result = self._engine.translate(orig)
                if result and result != orig:
                    if self._cache:
                        self._cache.update_translation(game, orig, result)
                    done += 1
                    self.log.emit(f"✓  {orig[:60]}...")
                else:
                    failed += 1
                    self.log.emit(f"✗  فشل: {orig[:60]}")
            except Exception as e:
                failed += 1
                self.log.emit(f"✗  خطأ: {e}")
            self.progress.emit(i + 1, total)
        self.finished.emit(done, failed)


# ── Sidebar game button ───────────────────────────────────────────────────────
class GameButton(QPushButton):
    def __init__(self, name: str, count: int, parent=None):
        label = f"  {name}" if name != "All Games" else f"  ★  {name}"
        super().__init__(label, parent)
        self.setObjectName("game_btn")
        self.game_name = name
        self._count = count
        self.setCheckable(False)
        self.setProperty("active", False)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMinimumHeight(38)
        self._badge = QLabel(str(count), self)
        self._badge.setStyleSheet(f"""
            background-color: {C['card2']};
            color: {C['muted']};
            border-radius: 9px;
            padding: 0px 6px;
            font-size: 10px;
        """)
        self._badge.setFixedHeight(18)
        self._badge.adjustSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._badge.move(self.width() - self._badge.width() - 8,
                         (self.height() - self._badge.height()) // 2)

    def set_active(self, active: bool):
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self._badge.setStyleSheet(f"""
            background-color: {'rgba(233,69,96,0.2)' if active else C['card2']};
            color: {C['accent2'] if active else C['muted']};
            border-radius: 9px;
            padding: 0px 6px;
            font-size: 10px;
        """)

    def update_count(self, count: int):
        self._count = count
        self._badge.setText(str(count))
        self._badge.adjustSize()


# ── Stat chip ─────────────────────────────────────────────────────────────────
class StatChip(QLabel):
    def __init__(self, text: str, variant: str = "", parent=None):
        super().__init__(text, parent)
        obj = f"stat_chip_{variant}" if variant else "stat_chip"
        self.setObjectName(obj)
        self.setAlignment(Qt.AlignCenter)


# ── Edit dialog ───────────────────────────────────────────────────────────────
class EditDialog(QDialog):
    def __init__(self, game_name: str, entry: dict, cache: TranslationCache, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تعديل الترجمة")
        self.setMinimumSize(800, 560)
        self.resize(900, 600)
        self._game = game_name
        self._entry = entry
        self._cache = cache
        self._saved = False
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setObjectName("dialog_header")
        hdr_lay = QVBoxLayout(hdr)
        hdr_lay.setContentsMargins(24, 18, 24, 18)
        hdr_lay.setSpacing(4)
        t = QLabel("✏️  تعديل الترجمة")
        t.setObjectName("dialog_title")
        g = QLabel(f"اللعبة: {self._game}")
        g.setObjectName("dialog_game_label")
        hdr_lay.addWidget(t)
        hdr_lay.addWidget(g)
        root.addWidget(hdr)

        # Body
        body = QWidget()
        body.setStyleSheet(f"background-color: {C['surface']};")
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(24, 20, 24, 20)
        body_lay.setSpacing(20)

        # Left — English (read-only)
        left = QVBoxLayout()
        left.setSpacing(8)
        el = QLabel("🔤  النص الأصلي (إنجليزي)")
        el.setObjectName("field_label")
        self._orig_edit = QTextEdit()
        self._orig_edit.setReadOnly(True)
        orig_display = self._entry.get("original", "").replace("\\n", "\n")
        self._orig_edit.setPlainText(orig_display)
        self._orig_edit.setMinimumWidth(340)
        left.addWidget(el)
        left.addWidget(self._orig_edit)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.VLine)
        div.setStyleSheet(f"color: {C['border']};")

        # Right — Arabic (editable, RTL)
        right = QVBoxLayout()
        right.setSpacing(8)
        al = QLabel("🌐  الترجمة العربية (قابل للتعديل)")
        al.setObjectName("field_label")
        self._trans_edit = QTextEdit()
        # ── RTL support — the key difference vs tkinter ──
        self._trans_edit.setLayoutDirection(Qt.RightToLeft)
        doc_opt = QTextOption()
        doc_opt.setTextDirection(Qt.RightToLeft)
        self._trans_edit.document().setDefaultTextOption(doc_opt)
        trans_display = self._entry.get("translated", "").replace("\\n", "\n")
        self._trans_edit.setPlainText(trans_display)
        self._trans_edit.setMinimumWidth(340)
        self._trans_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {C['card2']};
                border: 1px solid rgba(0, 210, 255, 0.4);
                border-radius: 6px;
                color: {C['primary']};
                font-size: 14px;
                padding: 10px;
                selection-background-color: {C['selected']};
            }}
            QTextEdit:focus {{ border-color: {C['teal']}; }}
        """)
        right.addWidget(al)
        right.addWidget(self._trans_edit)

        body_lay.addLayout(left, 1)
        body_lay.addWidget(div)
        body_lay.addLayout(right, 1)
        root.addWidget(body, 1)

        # Footer
        footer = QFrame()
        footer.setStyleSheet(f"""
            background-color: {C['card']};
            border-top: 1px solid {C['border']};
        """)
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(24, 12, 24, 12)

        # Shortcut hint
        hint = QLabel("Ctrl+Enter للحفظ  •  Esc للإلغاء")
        hint.setStyleSheet(f"color: {C['muted']}; font-size: 11px;")
        footer_lay.addWidget(hint)
        footer_lay.addStretch()

        cancel_btn = QPushButton("إلغاء")
        cancel_btn.setObjectName("btn_secondary")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("💾  حفظ")
        save_btn.setObjectName("btn_primary")
        save_btn.clicked.connect(self._save)
        save_btn.setDefault(True)
        footer_lay.addWidget(cancel_btn)
        footer_lay.addSpacing(8)
        footer_lay.addWidget(save_btn)
        root.addWidget(footer)

    def _save(self):
        raw = self._trans_edit.toPlainText().strip()
        if not raw or not self._cache:
            return
        new_trans = raw.replace("\n", "\\n")
        self._cache.update_translation(self._game, self._entry["original"], new_trans)
        self._saved = True
        self.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return and event.modifiers() == Qt.ControlModifier:
            self._save()
        else:
            super().keyPressEvent(event)


# ── Main window ───────────────────────────────────────────────────────────────
class CacheDemoWindow(QMainWindow):

    PAGE_SIZE = 60

    def __init__(self, cache: TranslationCache, translation_engine=None):
        super().__init__()
        self._cache   = cache
        self._engine  = translation_engine
        self._game    = "All Games"
        self._model   = "All Models"
        self._search  = ""
        self._page    = 0
        self._total   = 0
        self._worker  = None
        self._game_buttons: list[GameButton] = []
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)
        self.setWindowTitle("Game Arabic Translator  —  Translation Cache  (PySide6 Demo)")
        self.setMinimumSize(1100, 680)
        self.resize(1280, 780)
        self._build_ui()
        self._load_games()
        self._load_table()

    # ── UI build ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        root_widget = QWidget()
        root_lay    = QHBoxLayout(root_widget)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)
        self.setCentralWidget(root_widget)

        root_lay.addWidget(self._build_sidebar())
        root_lay.addWidget(self._build_main(), 1)

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setObjectName("sidebar_header")
        hdr_lay = QVBoxLayout(hdr)
        hdr_lay.setContentsMargins(16, 16, 16, 16)
        hdr_lay.setSpacing(3)
        t = QLabel("🎮  GAT")
        t.setObjectName("app_title")
        s = QLabel("Cache Browser Demo")
        s.setObjectName("app_sub")
        hdr_lay.addWidget(t)
        hdr_lay.addWidget(s)
        lay.addWidget(hdr)

        # Divider
        lay.addSpacing(6)

        # Games label
        gl = QLabel("  GAMES")
        gl.setStyleSheet(f"color: {C['muted']}; font-size: 10px; font-weight: bold; letter-spacing: 2px; padding: 6px 16px 3px;")
        lay.addWidget(gl)

        # Scroll area for game buttons
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")

        self._games_container = QWidget()
        self._games_container.setStyleSheet("background: transparent;")
        self._games_lay = QVBoxLayout(self._games_container)
        self._games_lay.setContentsMargins(0, 0, 0, 0)
        self._games_lay.setSpacing(0)
        self._games_lay.addStretch()

        scroll.setWidget(self._games_container)
        lay.addWidget(scroll, 1)

        # Bottom info
        bottom = QLabel("  PySide6 6.11 Demo")
        bottom.setStyleSheet(f"color: {C['border']}; font-size: 10px; padding: 10px 16px;")
        lay.addWidget(bottom)

        return sidebar

    def _build_main(self):
        main = QWidget()
        lay  = QVBoxLayout(main)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_topbar())
        lay.addWidget(self._build_toolbar())
        lay.addWidget(self._build_table(), 1)
        lay.addWidget(self._build_pagebar())

        return main

    def _build_topbar(self):
        bar = QFrame()
        bar.setObjectName("topbar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 20, 0)

        title = QLabel("Translation Cache")
        title.setObjectName("page_title")
        lay.addWidget(title)
        lay.addSpacing(20)

        self._chip_total = StatChip("0 entries", "blue")
        self._chip_games = StatChip("0 games",   "green")
        self._chip_sel   = StatChip("0 selected", "accent")
        self._chip_sel.setVisible(False)
        for c in (self._chip_total, self._chip_games, self._chip_sel):
            lay.addWidget(c)

        lay.addStretch()

        return bar

    def _build_toolbar(self):
        bar = QFrame()
        bar.setObjectName("toolbar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(10)

        # Search icon + input
        search_wrap = QFrame()
        search_wrap.setStyleSheet(f"""
            QFrame {{
                background-color: {C['card2']};
                border: 1px solid {C['border']};
                border-radius: 6px;
            }}
            QFrame:focus-within {{ border-color: {C['blue']}; }}
        """)
        sw_lay = QHBoxLayout(search_wrap)
        sw_lay.setContentsMargins(10, 0, 4, 0)
        sw_lay.setSpacing(6)
        icon_lbl = QLabel("🔍")
        icon_lbl.setStyleSheet(f"color: {C['muted']}; background: transparent; border: none; font-size: 14px;")
        sw_lay.addWidget(icon_lbl)
        self._search_box = QLineEdit()
        self._search_box.setObjectName("search_box")
        self._search_box.setPlaceholderText("ابحث في الترجمات... (English or عربي)")
        self._search_box.setFixedWidth(300)
        self._search_box.setStyleSheet(f"""
            QLineEdit {{
                background: transparent;
                border: none;
                color: {C['primary']};
                font-size: 13px;
                padding: 6px 0;
            }}
        """)
        self._search_box.textChanged.connect(self._search_changed)
        sw_lay.addWidget(self._search_box)
        clear_btn = QPushButton("✕")
        clear_btn.setFixedSize(20, 20)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {C['muted']};
                font-size: 11px;
                border-radius: 10px;
            }}
            QPushButton:hover {{ background: {C['border']}; color: {C['primary']}; }}
        """)
        clear_btn.clicked.connect(self._clear_search)
        sw_lay.addWidget(clear_btn)
        lay.addWidget(search_wrap)

        # Model filter
        m_lbl = QLabel("Model:")
        m_lbl.setStyleSheet(f"color: {C['muted']}; font-size: 12px;")
        self._model_combo = QComboBox()
        self._model_combo.setFixedWidth(180)
        self._model_combo.addItem("All Models")
        self._model_combo.currentTextChanged.connect(self._model_changed)
        lay.addWidget(m_lbl)
        lay.addWidget(self._model_combo)

        lay.addStretch()

        # Action buttons (right side)
        self._btn_edit     = QPushButton("✏️  Edit")
        self._btn_edit.setObjectName("btn_edit")
        self._btn_retrans  = QPushButton("🔄  إعادة ترجمة")
        self._btn_retrans.setObjectName("btn_retrans")
        self._btn_delete   = QPushButton("🗑  Delete")
        self._btn_delete.setObjectName("btn_delete")

        self._btn_edit.setEnabled(False)
        self._btn_retrans.setEnabled(False)
        self._btn_delete.setEnabled(False)

        self._btn_edit.clicked.connect(self._edit_selected)
        self._btn_retrans.clicked.connect(self._retranslate_selected)
        self._btn_delete.clicked.connect(self._delete_selected)

        for btn in (self._btn_edit, self._btn_retrans, self._btn_delete):
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            lay.addWidget(btn)

        return bar

    def _build_table(self):
        wrapper = QWidget()
        lay = QVBoxLayout(wrapper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["#", "English", "Arabic (عربي)", "Model", "Hits"])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setShowGrid(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(False)
        self._table.setWordWrap(False)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.Fixed)
        hdr.setSectionResizeMode(4, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 55)
        self._table.setColumnWidth(3, 140)
        self._table.setColumnWidth(4, 55)
        self._table.verticalHeader().setDefaultSectionSize(38)

        self._table.doubleClicked.connect(self._edit_selected)
        self._table.itemSelectionChanged.connect(self._selection_changed)

        lay.addWidget(self._table)
        return wrapper

    def _build_pagebar(self):
        bar = QFrame()
        bar.setObjectName("pagebar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(10)

        self._prev_btn = QPushButton("← Prev")
        self._prev_btn.setObjectName("page_btn")
        self._prev_btn.clicked.connect(lambda: self._change_page(-1))
        self._next_btn = QPushButton("Next →")
        self._next_btn.setObjectName("page_btn")
        self._next_btn.clicked.connect(lambda: self._change_page(1))

        self._page_lbl = QLabel("")
        self._page_lbl.setObjectName("page_info")

        self._prog_bar = QProgressBar()
        self._prog_bar.setFixedHeight(5)
        self._prog_bar.setFixedWidth(200)
        self._prog_bar.setVisible(False)

        self._prog_lbl = QLabel("")
        self._prog_lbl.setStyleSheet(f"color: {C['teal']}; font-size: 12px;")
        self._prog_lbl.setVisible(False)

        lay.addWidget(self._prev_btn)
        lay.addWidget(self._next_btn)
        lay.addSpacing(10)
        lay.addWidget(self._page_lbl)
        lay.addStretch()
        lay.addWidget(self._prog_lbl)
        lay.addWidget(self._prog_bar)

        return bar

    # ── Data loading ──────────────────────────────────────────────────────────
    def _load_games(self):
        # Clear existing
        for btn in self._game_buttons:
            btn.deleteLater()
        self._game_buttons.clear()

        lay = self._games_lay
        # Remove all except the stretch at the end
        while lay.count() > 1:
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        games = self._cache.get_all_games() if self._cache else []

        total_all = sum(self._cache.count_entries(g) for g in games) if self._cache else 0
        all_btn = GameButton("All Games", total_all)
        all_btn.clicked.connect(lambda: self._select_game("All Games"))
        lay.insertWidget(lay.count() - 1, all_btn)
        self._game_buttons.append(all_btn)

        for g in sorted(games):
            cnt = self._cache.count_entries(g)
            btn = GameButton(g, cnt)
            btn.clicked.connect(lambda checked=False, name=g: self._select_game(name))
            lay.insertWidget(lay.count() - 1, btn)
            self._game_buttons.append(btn)

        # Update chips
        self._chip_games.setText(f"{len(games)} games")
        self._chip_total.setText(f"{total_all:,} entries")

        # Activate current selection
        self._update_game_buttons()

    def _update_game_buttons(self):
        for btn in self._game_buttons:
            btn.set_active(btn.game_name == self._game)

    def _update_model_combo(self):
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        self._model_combo.addItem("All Models")
        if self._cache:
            games = self._cache.get_all_games() if self._game == "All Games" else [self._game]
            models = set()
            for g in games:
                models.update(self._cache.get_models_for_game(g))
            for m in sorted(models):
                self._model_combo.addItem(m)
        self._model_combo.setCurrentText(self._model)
        self._model_combo.blockSignals(False)

    def _load_table(self):
        if not self._cache:
            return

        model_f = self._model if self._model != "All Models" else ""
        games   = self._cache.get_all_games() if self._game == "All Games" else [self._game]

        # Count total
        total = sum(
            self._cache.count_entries(g, self._search, model_f)
            for g in games
        )
        self._total = total
        total_pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self._page  = max(0, min(self._page, total_pages - 1))

        # Gather rows across games
        rows  = []
        quota = self.PAGE_SIZE
        skip  = self._page * self.PAGE_SIZE
        for g in games:
            g_total = self._cache.count_entries(g, self._search, model_f)
            if skip >= g_total:
                skip -= g_total
                continue
            batch = self._cache.get_page(g, skip, quota, self._search, model_f)
            for row in batch:
                rows.append({"game": g, **row})
            quota -= len(batch)
            skip = 0
            if quota <= 0:
                break

        # Populate table
        self._table.setRowCount(0)
        self._table.setRowCount(len(rows))
        offset = self._page * self.PAGE_SIZE

        for i, row in enumerate(rows):
            num_item = QTableWidgetItem(str(offset + i + 1))
            num_item.setTextAlignment(Qt.AlignCenter)
            num_item.setForeground(QColor(C['muted']))

            orig_item = QTableWidgetItem(row["original"].replace("\\n", " ↵ "))
            orig_item.setForeground(QColor(C['secondary']))

            # Arabic item — RTL alignment
            ar_text = row["translated"].replace("\\n", " ↵ ")
            ar_item = QTableWidgetItem(ar_text)
            ar_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            ar_item.setForeground(QColor(C['teal']))
            ar_item.setData(Qt.UserRole, row)          # store full row

            model_item = QTableWidgetItem(row.get("model", ""))
            model_item.setForeground(QColor(C['muted']))
            model_item.setFont(QFont("Consolas", 10))

            hits_item = QTableWidgetItem(str(row.get("hits", 0)))
            hits_item.setTextAlignment(Qt.AlignCenter)
            hits_item.setForeground(QColor(C['yellow']))

            self._table.setItem(i, 0, num_item)
            self._table.setItem(i, 1, orig_item)
            self._table.setItem(i, 2, ar_item)
            self._table.setItem(i, 3, model_item)
            self._table.setItem(i, 4, hits_item)

        # Pagination label
        pg_txt = f"Page {self._page + 1} / {total_pages}  —  {total:,} total"
        self._page_lbl.setText(pg_txt)
        self._prev_btn.setEnabled(self._page > 0)
        self._next_btn.setEnabled(self._page < total_pages - 1)
        self.statusBar().showMessage(f"Loaded {len(rows)} rows  |  Page {self._page + 1}/{total_pages}  |  {total:,} entries total")
        self._update_model_combo()

    # ── Events ────────────────────────────────────────────────────────────────
    def _select_game(self, name: str):
        self._game  = name
        self._model = "All Models"
        self._page  = 0
        self._update_game_buttons()
        self._load_table()

    def _model_changed(self, text: str):
        self._model = text
        self._page  = 0
        self._load_table()

    def _search_changed(self, text: str):
        self._search = text.strip()
        self._search_timer.start(320)

    def _do_search(self):
        self._page = 0
        self._load_table()

    def _clear_search(self):
        self._search_box.clear()
        self._search = ""
        self._page   = 0
        self._load_table()

    def _change_page(self, delta: int):
        self._page += delta
        self._load_table()

    def _selection_changed(self):
        sel = self._table.selectedRows() if hasattr(self._table, 'selectedRows') else []
        sel_rows = list({idx.row() for idx in self._table.selectedIndexes()})
        count = len(sel_rows)
        self._btn_edit.setEnabled(count == 1)
        self._btn_retrans.setEnabled(count > 0 and self._engine is not None)
        self._btn_delete.setEnabled(count > 0)
        if count > 0:
            self._chip_sel.setText(f"{count} selected")
            self._chip_sel.setVisible(True)
        else:
            self._chip_sel.setVisible(False)

    def _get_selected_entries(self) -> list:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        entries = []
        for r in rows:
            ar_item = self._table.item(r, 2)
            if ar_item:
                data = ar_item.data(Qt.UserRole)
                if data:
                    entries.append(data)
        return entries

    def _edit_selected(self):
        entries = self._get_selected_entries()
        if len(entries) != 1:
            return
        entry = entries[0]
        game  = entry.get("game", self._game)
        dlg   = EditDialog(game, entry, self._cache, self)
        if dlg.exec() and dlg._saved:
            self._load_table()
            self.statusBar().showMessage("✓  الترجمة حُفّظت بنجاح")

    def _delete_selected(self):
        entries = self._get_selected_entries()
        if not entries:
            return
        n = len(entries)
        if QMessageBox.question(
            self, "تأكيد الحذف",
            f"حذف {n} {'عنصر' if n == 1 else 'عناصر'}؟\n\nلا يمكن التراجع عن هذه العملية.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        for e in entries:
            game = e.get("game", self._game)
            self._cache.delete_entry(game, e["original"])
        self._load_table()
        self._load_games()
        self.statusBar().showMessage(f"✓  حُذف {n} {'عنصر' if n == 1 else 'عناصر'}")

    def _retranslate_selected(self):
        if not self._engine:
            QMessageBox.warning(self, "لا يوجد موديل",
                "يجب تشغيل البرنامج الكامل لاستخدام الترجمة.\n\nهذا Demo للعرض فقط.")
            return
        entries = self._get_selected_entries()
        if not entries:
            return
        n = len(entries)
        reply = QMessageBox.question(
            self, "إعادة ترجمة",
            f"إعادة ترجمة {n} {'عنصر' if n == 1 else 'عناصر'} بالموديل النشط؟\n\n"
            "• التاغات والرموز محمية تلقائياً\n"
            "• الترجمة الحالية ستُستبدل",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self._btn_retrans.setEnabled(False)
        self._prog_bar.setMaximum(n)
        self._prog_bar.setValue(0)
        self._prog_bar.setVisible(True)
        self._prog_lbl.setVisible(True)

        self._worker = RetranslateWorker(entries, self._engine, self._cache)
        self._worker.progress.connect(self._retrans_progress)
        self._worker.finished.connect(self._retrans_done)
        self._worker.start()

    def _retrans_progress(self, done: int, total: int):
        self._prog_bar.setValue(done)
        self._prog_lbl.setText(f"جاري الترجمة... {done}/{total}")

    def _retrans_done(self, done: int, failed: int):
        self._prog_bar.setVisible(False)
        self._prog_lbl.setVisible(False)
        self._btn_retrans.setEnabled(True)
        self._load_table()
        msg = f"✓  إعادة الترجمة: {done} نجح"
        if failed:
            msg += f"  ✗  {failed} فشل"
        self.statusBar().showMessage(msg)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    app.setFont(QFont("Segoe UI", 13))

    cache_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "cache", "translations.db"
    )
    cache = TranslationCache(cache_path)

    win = CacheDemoWindow(cache)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
