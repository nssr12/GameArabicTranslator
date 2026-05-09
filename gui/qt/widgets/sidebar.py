"""
gui/qt/widgets/sidebar.py  —  الشريط الجانبي للتنقل
"""

from __future__ import annotations
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QToolButton, QScrollArea, QWidget, QSizePolicy
)
from PySide6.QtCore  import Qt, Signal, QSize
from PySide6.QtGui   import QCursor, QFont

from gui.qt.theme import theme


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
        hdr.setFixedHeight(78)

        lay = QVBoxLayout(hdr)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(3)

        logo = QLabel("🎮 GAT")
        logo.setObjectName("app_logo")

        ver = QLabel("v2.0  •  PySide6")
        ver.setObjectName("app_version")

        lay.addWidget(logo)
        lay.addWidget(ver)
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
