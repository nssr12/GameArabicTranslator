"""
gui/qt/widgets/page_header.py
Factory مشترك لبناء شريط العنوان العلوي بالأسلوب الموحّد.
"""
from __future__ import annotations
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel
from PySide6.QtCore    import Qt
from gui.qt.theme      import theme


def make_topbar(icon: str, title: str) -> tuple[QFrame, QHBoxLayout]:
    """
    يُنشئ شريط العنوان العلوي الموحّد.

    Returns (bar, lay):
      - bar  : QFrame الجاهز للإضافة في الـ layout الرئيسي
      - lay  : QHBoxLayout — المتصل يُضيف widgets اليمنى مباشرةً
               (في RTL هي تظهر على اليسار البصري)

    مثال:
        bar, lay = make_topbar("🎮", "إدارة الألعاب")
        lay.addWidget(my_button)
        main_layout.addWidget(bar)
    """
    bar = QFrame()
    bar.setObjectName("topbar")
    bar.setFixedHeight(64)

    lay = QHBoxLayout(bar)
    lay.setContentsMargins(24, 0, 24, 0)
    lay.setSpacing(12)

    # ── Title badge ───────────────────────────────────────────────────────────
    badge = QFrame()
    badge.setObjectName("title_badge")
    badge.setFixedHeight(42)

    b_lay = QHBoxLayout(badge)
    b_lay.setContentsMargins(14, 0, 14, 0)
    b_lay.setSpacing(8)

    dot = QLabel("◆")
    dot.setObjectName("title_badge_dot")

    text = QLabel(title)
    text.setObjectName("title_badge_text")

    icon_lbl = QLabel(icon)
    icon_lbl.setObjectName("title_badge_icon")
    icon_lbl.setFixedWidth(28)

    b_lay.addWidget(dot)
    b_lay.addWidget(text)
    b_lay.addSpacing(4)
    b_lay.addWidget(icon_lbl)

    lay.addWidget(badge)
    lay.addStretch()

    return bar, lay
