"""
gui/qt/pages/settings.py  —  صفحة الإعدادات (المرحلة 2)
"""

from __future__ import annotations
import os, json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QComboBox, QSpinBox, QLineEdit, QScrollArea, QFileDialog,
    QSizePolicy, QGridLayout, QApplication
)
from PySide6.QtCore  import Qt, Signal
from PySide6.QtGui   import QCursor, QFont

from gui.qt.theme              import theme, THEMES
from gui.qt.widgets.page_header import make_topbar


# ── Theme card ────────────────────────────────────────────────────────────────

class ThemeCard(QFrame):
    """بطاقة ثيم قابلة للنقر تعرض عينة ألوان."""

    clicked = Signal(str)

    SWATCH_KEYS = ["accent", "blue", "green", "teal", "bg"]

    def __init__(self, theme_id: str, palette: dict, parent=None):
        super().__init__(parent)
        self._id = theme_id
        self._palette = palette
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setFixedSize(130, 100)
        self._build(palette)
        self._set_active(theme_id == theme.name)

    def _build(self, p: dict):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # Colour swatches row
        swatches = QHBoxLayout()
        swatches.setSpacing(4)
        for key in self.SWATCH_KEYS:
            dot = QLabel()
            dot.setFixedSize(18, 18)
            dot.setStyleSheet(
                f"background-color: {p.get(key, '#888')};"
                f"border-radius: 9px;"
            )
            swatches.addWidget(dot)
        lay.addLayout(swatches)

        # Name
        name_map = {
            "dark":     "داكن",
            "midnight": "منتصف الليل",
            "ocean":    "المحيط",
            "sunset":   "الغروب",
            "forest":   "الغابة",
        }
        lbl = QLabel(name_map.get(self._id, self._id))
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"color: {p.get('primary','#fff')}; font-size: 12px; font-weight: bold;")
        lay.addWidget(lbl)

    def _set_active(self, active: bool):
        p = self._palette
        border = p.get("accent", "#e94560") if active else p.get("border", "#444")
        bg     = p.get("card2", "#222") if active else p.get("bg", "#111")
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg};
                border: 2px solid {border};
                border-radius: 10px;
            }}
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._id)

    def set_active(self, active: bool):
        self._set_active(active)


# ── Section frame ─────────────────────────────────────────────────────────────

def _section(title: str) -> tuple[QFrame, QVBoxLayout]:
    """ينتج QFrame كبطاقة مع عنوان وبدنه layout."""
    frame = QFrame()
    frame.setObjectName("card")
    frame.setStyleSheet(f"""
        QFrame#card {{
            background-color: {theme.c['card']};
            border: 1px solid {theme.c['border']};
            border-radius: 10px;
        }}
    """)
    outer = QVBoxLayout(frame)
    outer.setContentsMargins(20, 16, 20, 18)
    outer.setSpacing(14)

    hdr = QLabel(title)
    hdr.setStyleSheet(
        f"color: {theme.c['primary']}; font-size: 15px; font-weight: bold;"
        f" border: none; background: transparent;"
    )
    outer.addWidget(hdr)

    div = QFrame()
    div.setFixedHeight(1)
    div.setStyleSheet(f"background: {theme.c['border']}; border: none;")
    outer.addWidget(div)

    return frame, outer


def _row_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {theme.c['muted']}; font-size: 12px;"
        f" background: transparent; border: none;"
    )
    lbl.setFixedWidth(140)
    return lbl


# ── Settings page ─────────────────────────────────────────────────────────────

class SettingsPage(QWidget):
    """صفحة الإعدادات الكاملة."""

    theme_changed  = Signal()   # app.py يستمع ليُطبّق QSS من جديد
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))),
            "config.json"
        )
        self._theme_cards: dict[str, ThemeCard] = {}
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        c   = theme.c
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        root.addWidget(self._build_topbar())

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background: {c['bg']}; border: none;")

        content = QWidget()
        content.setStyleSheet(f"background: {c['bg']};")
        lay = QVBoxLayout(content)
        lay.setContentsMargins(28, 24, 28, 32)
        lay.setSpacing(20)

        lay.addWidget(self._build_theme_section())
        lay.addWidget(self._build_font_section())
        lay.addWidget(self._build_tools_section())
        lay.addStretch()

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _build_topbar(self) -> QFrame:
        bar, _ = make_topbar("⚙️", "الإعدادات")
        return bar

    def _build_theme_section(self) -> QFrame:
        frame, lay = _section("🎨  المظهر")

        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)
        cards_row.setAlignment(Qt.AlignLeft)

        for tid, palette in THEMES.items():
            card = ThemeCard(tid, palette)
            card.clicked.connect(self._apply_theme)
            self._theme_cards[tid] = card
            cards_row.addWidget(card)

        cards_row.addStretch()
        lay.addLayout(cards_row)

        hint = QLabel("انقر على أي ثيم لتطبيقه فوراً")
        hint.setStyleSheet(f"color: {theme.c['muted']}; font-size: 11px; background: transparent; border: none;")
        lay.addWidget(hint)

        return frame

    def _build_font_section(self) -> QFrame:
        frame, lay = _section("🔤  الخط")

        row = QHBoxLayout()
        row.setSpacing(16)

        # Font family
        row.addWidget(_row_label("نوع الخط:"))
        self._font_combo = QComboBox()
        self._font_combo.addItems([
            "Segoe UI", "Arial", "Tahoma", "Calibri",
            "Verdana", "Times New Roman", "Consolas"
        ])
        self._font_combo.setCurrentText(theme.font_family)
        self._font_combo.setFixedWidth(200)
        self._font_combo.currentTextChanged.connect(self._apply_font)
        row.addWidget(self._font_combo)

        row.addSpacing(20)

        # Font size
        row.addWidget(_row_label("الحجم:"))
        self._font_spin = QSpinBox()
        self._font_spin.setRange(9, 20)
        self._font_spin.setValue(theme.font_size)
        self._font_spin.setSuffix(" px")
        self._font_spin.setFixedWidth(90)
        self._font_spin.valueChanged.connect(self._apply_font)
        row.addWidget(self._font_spin)

        row.addStretch()
        lay.addLayout(row)

        return frame

    def _build_tools_section(self) -> QFrame:
        frame, lay = _section("🔧  مسارات الأدوات")

        cfg = self._load_config()
        tools = cfg.get("tools", {})

        self._tool_fields: dict[str, QLineEdit] = {}

        tools_def = [
            ("unrealpak_path", "UnrealPak.exe",  "أداة حزم UE4/5  (.exe)"),
            ("retoc_path",     "retoc.exe",       "أداة فك/ضغط IoStore  (.exe)"),
            ("uassetgui_path", "UAssetGUI.exe",   "أداة تعديل UASSET  (.exe)"),
        ]

        for key, label, hint in tools_def:
            row = QHBoxLayout()
            row.setSpacing(10)
            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"color: {theme.c['secondary']}; min-width: 130px;"
                f" background: transparent; border: none;"
            )
            field = QLineEdit()
            field.setPlaceholderText(hint)
            field.setText(tools.get(key, ""))
            field.setObjectName("tool_field")
            self._tool_fields[key] = field

            browse = QPushButton("📂")
            browse.setObjectName("icon_btn")
            browse.setFixedSize(32, 32)
            browse.setToolTip("اختر الملف")
            browse.clicked.connect(lambda _, k=key: self._browse_tool(k))

            row.addWidget(lbl)
            row.addWidget(field, 1)
            row.addWidget(browse)
            lay.addLayout(row)

        # Save button
        save_row = QHBoxLayout()
        save_row.addStretch()
        save_btn = QPushButton("💾  حفظ المسارات")
        save_btn.setObjectName("btn_primary")
        save_btn.clicked.connect(self._save_tools)
        save_row.addWidget(save_btn)
        lay.addLayout(save_row)

        return frame

    # ── Actions ───────────────────────────────────────────────────────────────

    def _apply_theme(self, theme_id: str):
        theme.set_theme(theme_id)
        app = QApplication.instance()
        if app:
            app.setStyleSheet(theme.qss())
        # Update card borders
        for tid, card in self._theme_cards.items():
            card.set_active(tid == theme_id)
        self.theme_changed.emit()
        self.status_message.emit(f"✓  الثيم: {theme_id}")

    def _apply_font(self):
        family = self._font_combo.currentText()
        size   = self._font_spin.value()
        theme.set_font(family, size)
        app = QApplication.instance()
        if app:
            app.setFont(QFont(family, size))
            app.setStyleSheet(theme.qss())
        self.status_message.emit(f"✓  الخط: {family} {size}px")

    def _browse_tool(self, key: str):
        path, _ = QFileDialog.getOpenFileName(
            self, "اختر الأداة", "", "Executable (*.exe)"
        )
        if path:
            self._tool_fields[key].setText(path)

    def _save_tools(self):
        cfg = self._load_config()
        tools = cfg.setdefault("tools", {})
        for key, field in self._tool_fields.items():
            val = field.text().strip()
            if val:
                tools[key] = val
            else:
                tools.pop(key, None)
        self._write_config(cfg)
        self.status_message.emit("✓  تم حفظ مسارات الأدوات")

    # ── Config helpers ────────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        try:
            with open(self._config_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_config(self, cfg: dict):
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.status_message.emit(f"✗  خطأ في الحفظ: {e}")
