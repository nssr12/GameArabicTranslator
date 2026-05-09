"""
صفحة placeholder مؤقتة — تُستبدل في مراحل لاحقة
"""
from __future__ import annotations
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore    import Qt
from gui.qt.theme      import theme


class PlaceholderPage(QWidget):
    def __init__(self, title: str, icon: str = "🚧", parent=None):
        super().__init__(parent)
        c   = theme.c
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(12)

        ico = QLabel(icon)
        ico.setAlignment(Qt.AlignCenter)
        ico.setStyleSheet(f"font-size: 52px; color: {c['border']};")

        lbl = QLabel(title)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {c['muted']};")

        sub = QLabel("هذه الصفحة قيد البناء — ستكون جاهزة قريباً")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(f"font-size: 13px; color: {c['border']};")

        lay.addWidget(ico)
        lay.addWidget(lbl)
        lay.addWidget(sub)
