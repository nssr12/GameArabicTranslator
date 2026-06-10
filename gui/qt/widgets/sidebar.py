"""
gui/qt/widgets/sidebar.py  —  الشريط الجانبي للتنقل
"""

from __future__ import annotations
import os
import sys

from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QToolButton, QScrollArea, QWidget, QSizePolicy
)
from PySide6.QtCore  import Qt, Signal, QSize
from PySide6.QtGui   import QCursor, QFont, QPixmap

from gui.qt.theme import theme

if getattr(sys, 'frozen', False):
    _DATA_DIR = os.path.join(os.path.dirname(sys.executable), "data")
else:
    _DATA_DIR = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data")
    )


def _data_bases() -> list:
    """مجلّدات data المحتملة (نسخة مُغلّفة: بجانب exe + _internal + _MEIPASS)."""
    bases = [_DATA_DIR]
    if getattr(sys, 'frozen', False):
        exedir = os.path.dirname(sys.executable)
        bases.append(os.path.join(exedir, "_internal", "data"))
        mei = getattr(sys, "_MEIPASS", "")
        if mei:
            bases.append(os.path.join(mei, "data"))
    return bases


def _find_logo() -> str:
    for base in _data_bases():
        for name in ("logo.png", "logo.jpg", "logo.jpeg"):
            p = os.path.join(base, name)
            if os.path.isfile(p):
                return p
    return ""


# ── Nav item ──────────────────────────────────────────────────────────────────

class NavButton(QPushButton):
    """زر تنقل في الشريط الجانبي."""

    def __init__(self, icon: str, label: str, page_id: str, parent=None):
        super().__init__(f"  {icon}  {label}", parent)
        self.page_id = page_id
        self.setObjectName("nav_btn")
        self.setCheckable(False)
        self.setProperty("active", False)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMinimumHeight(42)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_active(self, active: bool):
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)


# ── Sidebar ───────────────────────────────────────────────────────────────────

NAV_ITEMS = [
    # (icon, label, page_id)
    ("🏠", "الرئيسية",       "home"),
    ("🎮", "الألعاب",        "games"),
    ("🌐", "الترجمة الفورية", "translate"),
    ("🌍", "ترجمة I2",       "i2_translate"),
    ("📦", "UnrealPak",      "unrealpak"),
    ("🤖", "AI Models",      "models"),
    ("💾", "الكاش",          "cache"),
    ("⚙️",  "الإعدادات",     "settings"),
]


class Sidebar(QFrame):
    """
    الشريط الجانبي الكامل.
    يُصدر إشارة page_requested(page_id) عند الضغط على أي زر.
    """

    page_requested  = Signal(str)
    admin_requested = Signal()
    toggle_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self._buttons: dict[str, NavButton] = {}
        self._model_chip: QLabel | None     = None
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._make_header())
        lay.addWidget(self._make_nav())
        lay.addStretch()
        lay.addWidget(self._make_footer())

    def _make_header(self) -> QFrame:
        hdr = QFrame()
        hdr.setObjectName("sidebar_header")
        hdr.setFixedHeight(108)

        logo_path = _find_logo()
        if logo_path:
            px = QPixmap(logo_path)
            if not px.isNull():
                # Logo fills the header area centered
                px = px.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                img_lbl = QLabel(hdr)
                img_lbl.setPixmap(px)
                img_lbl.setGeometry(0, 0, 230, 108)
                img_lbl.setAlignment(Qt.AlignCenter)
                img_lbl.setStyleSheet("background: transparent; border: none;")

                # ☰ toggle button — overlay at top-right corner (outer edge, away from content)
                toggle_btn = QToolButton(hdr)
                toggle_btn.setText("☰")
                toggle_btn.setObjectName("sidebar_toggle_btn")
                toggle_btn.setFixedSize(28, 28)
                toggle_btn.setCursor(QCursor(Qt.PointingHandCursor))
                toggle_btn.setToolTip("إخفاء القائمة")
                toggle_btn.clicked.connect(self.toggle_requested)
                toggle_btn.move(230 - 28 - 4, 4)   # outer-right of sidebar
                toggle_btn.raise_()
                return hdr

        # fallback: normal layout with text + toggle
        lay = QHBoxLayout(hdr)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        logo = QLabel("🎮 GAT")
        logo.setObjectName("app_logo")
        logo.setAlignment(Qt.AlignCenter)
        lay.addWidget(logo, 1)

        toggle_btn = QToolButton()
        toggle_btn.setText("☰")
        toggle_btn.setObjectName("sidebar_toggle_btn")
        toggle_btn.setFixedSize(28, 28)
        toggle_btn.setCursor(QCursor(Qt.PointingHandCursor))
        toggle_btn.setToolTip("إخفاء القائمة")
        toggle_btn.clicked.connect(self.toggle_requested)
        lay.addWidget(toggle_btn, 0, Qt.AlignTop)

        return hdr

    def _make_nav(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(wrapper)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(0)

        # Section label
        sec = QLabel("التنقل")
        sec.setObjectName("nav_section_label")
        lay.addWidget(sec)

        for icon, label, page_id in NAV_ITEMS:
            btn = NavButton(icon, label, page_id)
            btn.clicked.connect(lambda _, pid=page_id: self.page_requested.emit(pid))
            self._buttons[page_id] = btn
            lay.addWidget(btn)

        # Active model chip (under AI Models button)
        self._model_chip = QLabel("لا يوجد موديل نشط")
        self._model_chip.setObjectName("model_chip")
        self._model_chip.setAlignment(Qt.AlignCenter)
        self._model_chip.setWordWrap(False)
        lay.addWidget(self._model_chip)

        return wrapper

    def _make_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("sidebar_footer")

        lay = QHBoxLayout(footer)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(6)

        txt = QLabel("Game Arabic Translator")
        txt.setObjectName("sidebar_footer_text")
        lay.addWidget(txt, 1)

        admin_btn = QToolButton()
        admin_btn.setText("🔐")
        admin_btn.setObjectName("admin_btn")
        admin_btn.setToolTip("لوحة الإدارة")
        admin_btn.setCursor(QCursor(Qt.PointingHandCursor))
        admin_btn.setFixedSize(28, 28)
        admin_btn.clicked.connect(self.admin_requested)
        lay.addWidget(admin_btn)

        return footer

    # ── Public API ────────────────────────────────────────────────────────────

    def set_active_page(self, page_id: str):
        for pid, btn in self._buttons.items():
            btn.set_active(pid == page_id)

    def set_model_label(self, text: str):
        if self._model_chip:
            self._model_chip.setText(text or "لا يوجد موديل نشط")
