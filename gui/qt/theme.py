"""
gui/qt/theme.py  —  نظام الثيم الكامل لـ PySide6
يوفر: الألوان، QSS، الخطوط، وأدوات مساعدة للألوان
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict
import json, os


# ── Palette definitions ───────────────────────────────────────────────────────

THEMES: Dict[str, Dict[str, str]] = {
    "dark": {
        "bg":        "#0d1117",
        "surface":   "#161b22",
        "card":      "#1c2333",
        "card2":     "#21262d",
        "border":    "#30363d",
        "sidebar":   "#0d1117",
        "hover":     "#1f2937",
        "selected":  "#1d3a6e",
        "accent":    "#e94560",
        "accent2":   "#f85c7a",
        "blue":      "#388bfd",
        "blue2":     "#58a6ff",
        "green":     "#3fb950",
        "green2":    "#56d364",
        "teal":      "#00d2ff",
        "yellow":    "#d29922",
        "orange":    "#f78166",
        "purple":    "#bc8cff",
        "muted":     "#8b949e",
        "secondary": "#c9d1d9",
        "primary":   "#e6edf3",
        "row_alt":   "#161b22",
        "row_even":  "#0d1117",
        "success":   "#3fb950",
        "warning":   "#d29922",
        "error":     "#f85149",
    },
    "midnight": {
        "bg":        "#0a0f1a",
        "surface":   "#111827",
        "card":      "#1a2035",
        "card2":     "#1e2540",
        "border":    "#2a3550",
        "sidebar":   "#07090f",
        "hover":     "#1a2540",
        "selected":  "#1a3a6e",
        "accent":    "#6366f1",
        "accent2":   "#818cf8",
        "blue":      "#3b82f6",
        "blue2":     "#60a5fa",
        "green":     "#10b981",
        "green2":    "#34d399",
        "teal":      "#06b6d4",
        "yellow":    "#f59e0b",
        "orange":    "#f97316",
        "purple":    "#a855f7",
        "muted":     "#64748b",
        "secondary": "#94a3b8",
        "primary":   "#e2e8f0",
        "row_alt":   "#111827",
        "row_even":  "#0a0f1a",
        "success":   "#10b981",
        "warning":   "#f59e0b",
        "error":     "#ef4444",
    },
    "ocean": {
        "bg":        "#061322",
        "surface":   "#0a1f35",
        "card":      "#0f2a45",
        "card2":     "#143355",
        "border":    "#1e4a70",
        "sidebar":   "#040e1a",
        "hover":     "#102840",
        "selected":  "#0d3a6e",
        "accent":    "#00bbff",
        "accent2":   "#44ccff",
        "blue":      "#0ea5e9",
        "blue2":     "#38bdf8",
        "green":     "#00e5a0",
        "green2":    "#34d399",
        "teal":      "#22d3ee",
        "yellow":    "#fbbf24",
        "orange":    "#fb923c",
        "purple":    "#818cf8",
        "muted":     "#4a7a9b",
        "secondary": "#7fb5cc",
        "primary":   "#e0f0ff",
        "row_alt":   "#0a1f35",
        "row_even":  "#061322",
        "success":   "#00e5a0",
        "warning":   "#fbbf24",
        "error":     "#f87171",
    },
    "sunset": {
        "bg":        "#130a1a",
        "surface":   "#1e1030",
        "card":      "#271440",
        "card2":     "#2f1850",
        "border":    "#4a2568",
        "sidebar":   "#0d0612",
        "hover":     "#281540",
        "selected":  "#3a1060",
        "accent":    "#ff6b35",
        "accent2":   "#ff8c5a",
        "blue":      "#a78bfa",
        "blue2":     "#c4b5fd",
        "green":     "#4ade80",
        "green2":    "#86efac",
        "teal":      "#f0abfc",
        "yellow":    "#fde68a",
        "orange":    "#fb923c",
        "purple":    "#e879f9",
        "muted":     "#7c6a8a",
        "secondary": "#c4a8d8",
        "primary":   "#f5e8ff",
        "row_alt":   "#1e1030",
        "row_even":  "#130a1a",
        "success":   "#4ade80",
        "warning":   "#fde68a",
        "error":     "#fb7185",
    },
    "forest": {
        "bg":        "#0a1208",
        "surface":   "#111d0e",
        "card":      "#182616",
        "card2":     "#1e2e1c",
        "border":    "#2d4a2a",
        "sidebar":   "#060d04",
        "hover":     "#162214",
        "selected":  "#1a4020",
        "accent":    "#4ade80",
        "accent2":   "#86efac",
        "blue":      "#38bdf8",
        "blue2":     "#7dd3fc",
        "green":     "#22c55e",
        "green2":    "#4ade80",
        "teal":      "#2dd4bf",
        "yellow":    "#fbbf24",
        "orange":    "#fb923c",
        "purple":    "#a78bfa",
        "muted":     "#4a7050",
        "secondary": "#86a878",
        "primary":   "#d4f0d0",
        "row_alt":   "#111d0e",
        "row_even":  "#0a1208",
        "success":   "#22c55e",
        "warning":   "#fbbf24",
        "error":     "#f87171",
    },
}


# ── ThemeEngine ───────────────────────────────────────────────────────────────

class ThemeEngine:
    """
    يُدير الثيم الحالي ويُنشئ QSS كامل لكل التطبيق.
    استخدام:  theme = ThemeEngine();  app.setStyleSheet(theme.qss())
    """

    CONFIG_PATH = os.path.join("data", "qt_settings.json")

    def __init__(self):
        self._name = "dark"
        self._font_family = "Segoe UI"
        self._font_size   = 13
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self):
        try:
            with open(self.CONFIG_PATH, encoding="utf-8") as f:
                d = json.load(f)
            self._name        = d.get("theme",       self._name)
            self._font_family = d.get("font_family", self._font_family)
            self._font_size   = int(d.get("font_size", self._font_size))
        except Exception:
            pass

    def save(self):
        os.makedirs(os.path.dirname(self.CONFIG_PATH) or ".", exist_ok=True)
        try:
            with open(self.CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "theme":       self._name,
                    "font_family": self._font_family,
                    "font_size":   self._font_size,
                }, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # ── Accessors ─────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self._name

    @property
    def c(self) -> Dict[str, str]:
        return THEMES.get(self._name, THEMES["dark"])

    @property
    def font_family(self) -> str:
        return self._font_family

    @property
    def font_size(self) -> int:
        return self._font_size

    def theme_names(self) -> list[str]:
        return list(THEMES.keys())

    def set_theme(self, name: str):
        if name in THEMES:
            self._name = name
            self.save()

    def set_font(self, family: str, size: int):
        self._font_family = family
        self._font_size   = max(9, min(20, size))
        self.save()

    # ── QSS generation ───────────────────────────────────────────────────────

    def qss(self) -> str:
        c  = self.c
        ff = self._font_family
        fs = self._font_size
        return f"""
/* ═══════════════════════════════════════════════════════════════════════
   Global
═══════════════════════════════════════════════════════════════════════ */
* {{
    font-family: '{ff}', 'Tahoma', 'Arial', sans-serif;
    font-size: {fs}px;
    color: {c['primary']};
    outline: none;
}}
QMainWindow, QDialog, QWidget {{
    background-color: {c['bg']};
}}
QToolTip {{
    background-color: {c['card2']};
    color: {c['primary']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: {fs - 1}px;
}}

/* ═══════════════════════════════════════════════════════════════════════
   Sidebar
═══════════════════════════════════════════════════════════════════════ */
#sidebar {{
    background-color: {c['sidebar']};
    border-right: 1px solid {c['border']};
    min-width: 230px;
    max-width: 230px;
}}
#sidebar_header {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 {c['card']}, stop:1 {c['card2']});
    border-bottom: 1px solid {c['border']};
    padding: 18px 16px 14px;
}}
#app_logo {{
    color: {c['accent']};
    font-size: {fs + 7}px;
    font-weight: bold;
    letter-spacing: 2px;
}}
#app_version {{
    color: {c['muted']};
    font-size: {fs - 3}px;
    letter-spacing: 1px;
}}
#nav_section_label {{
    color: {c['muted']};
    font-size: {fs - 3}px;
    font-weight: bold;
    letter-spacing: 2px;
    padding: 12px 18px 4px;
    text-transform: uppercase;
}}
#nav_btn {{
    background: transparent;
    color: {c['secondary']};
    border: none;
    border-left: 3px solid transparent;
    padding: 10px 16px 10px 13px;
    text-align: left;
    font-size: {fs}px;
    border-radius: 0px;
    qproperty-iconSize: 18px 18px;
}}
#nav_btn:hover {{
    background-color: {c['hover']};
    color: {c['primary']};
}}
#nav_btn[active=true] {{
    background-color: {c['hover']};
    border-left: 3px solid {c['accent']};
    color: {c['primary']};
    font-weight: bold;
}}
#model_chip {{
    background-color: {c['card2']};
    color: {c['teal']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    padding: 2px 10px;
    font-size: {fs - 3}px;
    margin: 4px 14px;
}}
#sidebar_footer {{
    border-top: 1px solid {c['border']};
    padding: 10px 16px;
}}
#sidebar_footer_text {{
    color: {c['border']};
    font-size: {fs - 3}px;
}}
#admin_btn {{
    background: transparent;
    border: 1px solid {c['border']};
    border-radius: 6px;
    color: {c['muted']};
    font-size: 14px;
}}
#admin_btn:hover {{
    background: {c['hover']};
    color: {c['primary']};
    border-color: {c['accent']};
}}

/* ═══════════════════════════════════════════════════════════════════════
   Top bar (page header)
═══════════════════════════════════════════════════════════════════════ */
#topbar {{
    background: qlineargradient(x1:1,y1:0,x2:0,y2:0,
        stop:0 {c['bg']}, stop:0.45 {c['card']}, stop:1 {c['surface']});
    border-bottom: 1px solid {c['border']};
    min-height: 64px;
    max-height: 64px;
    padding: 0 24px;
}}
#page_title {{
    color: {c['primary']};
    font-size: {fs + 6}px;
    font-weight: bold;
}}
#page_subtitle {{
    color: {c['muted']};
    font-size: {fs - 1}px;
}}
#title_badge {{
    background: {_hex_to_rgba(c['accent'], 0.08)};
    border: 1px solid {_hex_to_rgba(c['accent'], 0.30)};
    border-radius: 10px;
}}
#title_badge_text {{
    color: {c['primary']};
    font-size: {fs + 3}px;
    font-weight: bold;
    background: transparent;
    border: none;
}}
#title_badge_dot {{
    color: {c['accent']};
    font-size: 9px;
    background: transparent;
    border: none;
}}
#title_badge_icon {{
    font-size: {fs + 3}px;
    background: transparent;
    border: none;
}}

/* ═══════════════════════════════════════════════════════════════════════
   Stat / badge chips
═══════════════════════════════════════════════════════════════════════ */
#chip {{
    background-color: {c['card2']};
    border: 1px solid {c['border']};
    border-radius: 12px;
    padding: 3px 12px;
    font-size: {fs - 2}px;
    color: {c['muted']};
}}
#chip_blue   {{ border-color: {c['blue']};   color: {c['blue2']};  }}
#chip_green  {{ border-color: {c['green']};  color: {c['green2']}; }}
#chip_accent {{ border-color: {c['accent']}; color: {c['accent2']};}}
#chip_teal   {{ border-color: {c['teal']};   color: {c['teal']};   }}
#chip_yellow {{ border-color: {c['yellow']}; color: {c['yellow']}; }}

/* ═══════════════════════════════════════════════════════════════════════
   Buttons
═══════════════════════════════════════════════════════════════════════ */
QPushButton {{
    background-color: {c['card2']};
    color: {c['secondary']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 7px 16px;
    font-size: {fs}px;
}}
QPushButton:hover {{
    background-color: {c['hover']};
    border-color: {c['muted']};
    color: {c['primary']};
}}
QPushButton:pressed {{
    background-color: {c['card']};
}}
QPushButton:disabled {{
    color: {c['border']};
    border-color: {c['surface']};
    background-color: {c['surface']};
}}

QPushButton#btn_primary {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {c['accent']}, stop:1 {_darken(c['accent'])});
    color: white;
    border: none;
    font-weight: bold;
    padding: 8px 22px;
}}
QPushButton#btn_primary:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {c['accent2']}, stop:1 {c['accent']});
}}
QPushButton#btn_secondary {{
    background-color: {c['card2']};
    color: {c['secondary']};
    border: 1px solid {c['border']};
}}
QPushButton#btn_danger {{
    background-color: rgba(248,81,73,0.12);
    color: {c['error']};
    border: 1px solid rgba(248,81,73,0.35);
}}
QPushButton#btn_danger:hover {{
    background-color: rgba(248,81,73,0.22);
    border-color: {c['error']};
}}
QPushButton#btn_info {{
    background-color: rgba(56,139,253,0.12);
    color: {c['blue2']};
    border: 1px solid rgba(56,139,253,0.35);
}}
QPushButton#btn_info:hover {{
    background-color: rgba(56,139,253,0.22);
    border-color: {c['blue']};
}}
QPushButton#btn_success {{
    background-color: rgba(63,185,80,0.12);
    color: {c['green2']};
    border: 1px solid rgba(63,185,80,0.35);
}}
QPushButton#btn_success:hover {{
    background-color: rgba(63,185,80,0.22);
    border-color: {c['green']};
}}
QPushButton#icon_btn {{
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 4px;
    color: {c['muted']};
    font-size: {fs + 2}px;
}}
QPushButton#icon_btn:hover {{
    background-color: {c['hover']};
    color: {c['primary']};
}}

/* ═══════════════════════════════════════════════════════════════════════
   Inputs
═══════════════════════════════════════════════════════════════════════ */
QLineEdit {{
    background-color: {c['card2']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 7px 12px;
    color: {c['primary']};
    selection-background-color: {c['selected']};
}}
QLineEdit:focus {{ border-color: {c['blue']}; background-color: {c['card']}; }}
QLineEdit:read-only {{ color: {c['muted']}; background-color: {c['surface']}; }}

QTextEdit, QPlainTextEdit {{
    background-color: {c['card2']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    color: {c['primary']};
    padding: 8px;
    selection-background-color: {c['selected']};
    font-size: {fs}px;
}}
QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {c['blue']}; }}
QTextEdit:read-only, QPlainTextEdit:read-only {{
    background-color: {c['card']};
    color: {c['muted']};
}}

QComboBox {{
    background-color: {c['card2']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 6px 10px;
    color: {c['secondary']};
    selection-background-color: {c['card']};
    min-height: 28px;
}}
QComboBox:hover {{ border-color: {c['muted']}; }}
QComboBox:focus {{ border-color: {c['blue']}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background-color: {c['card2']};
    border: 1px solid {c['border']};
    selection-background-color: {c['selected']};
    color: {c['primary']};
    outline: none;
    padding: 2px;
}}

QSpinBox {{
    background-color: {c['card2']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 6px 10px;
    color: {c['primary']};
}}
QSpinBox:focus {{ border-color: {c['blue']}; }}

/* ═══════════════════════════════════════════════════════════════════════
   Table / Tree
═══════════════════════════════════════════════════════════════════════ */
QTableWidget, QTreeWidget, QListWidget {{
    background-color: {c['bg']};
    alternate-background-color: {c['row_alt']};
    gridline-color: {c['border']};
    border: none;
    color: {c['primary']};
    selection-background-color: {c['selected']};
    selection-color: {c['primary']};
    font-size: {fs}px;
    outline: none;
}}
QTableWidget::item, QTreeWidget::item, QListWidget::item {{
    padding: 7px 14px;
    border-bottom: 1px solid {c['border']};
}}
QTableWidget::item:hover, QTreeWidget::item:hover, QListWidget::item:hover {{
    background-color: {c['hover']};
}}
QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
    background-color: {c['selected']};
}}
QHeaderView::section {{
    background-color: {c['surface']};
    color: {c['muted']};
    padding: 9px 14px;
    border: none;
    border-bottom: 2px solid {c['border']};
    border-right: 1px solid {c['border']};
    font-weight: bold;
    font-size: {fs - 2}px;
    letter-spacing: 1px;
}}
QHeaderView::section:last-child {{ border-right: none; }}
QHeaderView::section:checked {{ background-color: {c['card']}; }}

/* ═══════════════════════════════════════════════════════════════════════
   Scrollbars
═══════════════════════════════════════════════════════════════════════ */
QScrollBar:vertical {{
    background: {c['surface']};
    width: 7px;
    border: none;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {c['border']};
    border-radius: 3px;
    min-height: 28px;
    margin: 1px;
}}
QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {c['surface']};
    height: 7px;
    border: none;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {c['border']};
    border-radius: 3px;
    min-width: 28px;
    margin: 1px;
}}
QScrollBar::handle:horizontal:hover {{ background: {c['muted']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ═══════════════════════════════════════════════════════════════════════
   Cards / Frames
═══════════════════════════════════════════════════════════════════════ */
#card {{
    background-color: {c['card']};
    border: 1px solid {c['border']};
    border-radius: 8px;
}}
#card_hover:hover {{
    background-color: {c['hover']};
    border-color: {c['muted']};
}}
#surface {{
    background-color: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 6px;
}}
#divider {{
    background-color: {c['border']};
    max-height: 1px;
    min-height: 1px;
}}

/* ═══════════════════════════════════════════════════════════════════════
   Toolbar / Panels
═══════════════════════════════════════════════════════════════════════ */
#toolbar {{
    background-color: {c['surface']};
    border-bottom: 1px solid {c['border']};
    padding: 8px 16px;
}}
#pagebar {{
    background-color: {c['surface']};
    border-top: 1px solid {c['border']};
    padding: 7px 16px;
}}
#statusbar_text {{
    color: {c['muted']};
    font-size: {fs - 2}px;
}}

/* ═══════════════════════════════════════════════════════════════════════
   Progress bar
═══════════════════════════════════════════════════════════════════════ */
QProgressBar {{
    background-color: {c['card2']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    text-align: center;
    color: transparent;
    height: 6px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {c['blue']}, stop:1 {c['teal']});
    border-radius: 4px;
}}

/* ═══════════════════════════════════════════════════════════════════════
   Check / Radio
═══════════════════════════════════════════════════════════════════════ */
QCheckBox {{
    spacing: 8px;
    color: {c['secondary']};
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {c['border']};
    border-radius: 3px;
    background: {c['card2']};
}}
QCheckBox::indicator:checked {{
    background: {c['accent']};
    border-color: {c['accent']};
}}
QCheckBox::indicator:hover {{ border-color: {c['muted']}; }}

QRadioButton {{
    spacing: 8px;
    color: {c['secondary']};
}}
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {c['border']};
    border-radius: 8px;
    background: {c['card2']};
}}
QRadioButton::indicator:checked {{
    background: {c['accent']};
    border-color: {c['accent']};
}}

/* ═══════════════════════════════════════════════════════════════════════
   Tab widget
═══════════════════════════════════════════════════════════════════════ */
QTabWidget::pane {{
    border: 1px solid {c['border']};
    border-radius: 0 6px 6px 6px;
    background-color: {c['surface']};
}}
QTabBar::tab {{
    background-color: {c['card2']};
    color: {c['muted']};
    border: 1px solid {c['border']};
    border-bottom: none;
    border-radius: 6px 6px 0 0;
    padding: 7px 18px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background-color: {c['surface']};
    color: {c['primary']};
    border-bottom: 2px solid {c['accent']};
}}
QTabBar::tab:hover:!selected {{
    background-color: {c['hover']};
    color: {c['secondary']};
}}

/* ═══════════════════════════════════════════════════════════════════════
   Status bar
═══════════════════════════════════════════════════════════════════════ */
QStatusBar {{
    background-color: {c['surface']};
    color: {c['muted']};
    border-top: 1px solid {c['border']};
    font-size: {fs - 2}px;
    padding: 2px 12px;
}}
QStatusBar::item {{ border: none; }}

/* ═══════════════════════════════════════════════════════════════════════
   Message box
═══════════════════════════════════════════════════════════════════════ */
QMessageBox {{
    background-color: {c['surface']};
}}
QMessageBox QLabel {{
    color: {c['primary']};
    font-size: {fs}px;
}}

/* ═══════════════════════════════════════════════════════════════════════
   Splitter
═══════════════════════════════════════════════════════════════════════ */
QSplitter::handle {{
    background-color: {c['border']};
}}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical   {{ height: 1px; }}

/* ═══════════════════════════════════════════════════════════════════════
   Dialog
═══════════════════════════════════════════════════════════════════════ */
#dialog_header {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 {c['card']}, stop:1 {c['card2']});
    border-bottom: 1px solid {c['border']};
    padding: 20px 24px;
}}
#dialog_title {{
    color: {c['primary']};
    font-size: {fs + 3}px;
    font-weight: bold;
}}
#dialog_footer {{
    background-color: {c['card']};
    border-top: 1px solid {c['border']};
    padding: 12px 24px;
}}
#field_label {{
    color: {c['muted']};
    font-size: {fs - 2}px;
    font-weight: bold;
    letter-spacing: 1px;
}}
#hint_text {{
    color: {c['muted']};
    font-size: {fs - 2}px;
}}

/* ═══════════════════════════════════════════════════════════════════════
   Log / Terminal panel
═══════════════════════════════════════════════════════════════════════ */
#log_panel {{
    background-color: {c['bg']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    color: {c['green2']};
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: {fs - 1}px;
    padding: 8px;
}}
"""

    # ── Colour helper ─────────────────────────────────────────────────────────

    def color(self, key: str) -> str:
        """Return a palette colour by key."""
        return self.c.get(key, "#ffffff")


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert #rrggbb + alpha (0–1) to rgba(r,g,b,a) for QSS."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{int(alpha * 255)})"


def _darken(hex_color: str, factor: float = 0.75) -> str:
    """Return a darkened version of a hex colour (simple multiply)."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return "#" + hex_color
    r = int(int(hex_color[0:2], 16) * factor)
    g = int(int(hex_color[2:4], 16) * factor)
    b = int(int(hex_color[4:6], 16) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


# Singleton — the rest of the app imports this
theme = ThemeEngine()
