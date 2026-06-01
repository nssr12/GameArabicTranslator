"""
gui/qt/pages/models.py  —  صفحة نماذج الترجمة (المرحلة 3)
"""

from __future__ import annotations
import os, json, re
from collections import defaultdict

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QLineEdit, QComboBox, QTextEdit,
    QSizePolicy, QProgressBar, QApplication
)
from PySide6.QtCore  import Qt, Signal, QThread, QTimer
from PySide6.QtGui   import QCursor, QTextOption, QFont

from gui.qt.theme              import theme
from gui.qt.widgets.page_header import make_topbar


# ── Arabic names & icons for model types ─────────────────────────────────────

MODEL_META = {
    "google_free":      {"ar": "Google (مجاني)",      "icon": "🌐", "color": "blue"},
    "ollama":           {"ar": "Ollama (محلي)",        "icon": "🤖", "color": "green"},
    "deepl":            {"ar": "DeepL API",            "icon": "🔵", "color": "blue"},
    "huggingface":      {"ar": "HuggingFace",          "icon": "🤗", "color": "yellow"},
    "marianmt":         {"ar": "MarianMT (محلي)",      "icon": "⚡", "color": "teal"},
    "mbart":            {"ar": "mBART-50 (محلي)",      "icon": "🧠", "color": "purple"},
    "nllb":             {"ar": "NLLB-200 (محلي)",      "icon": "🔬", "color": "purple"},
    "custom_endpoint":  {"ar": "Endpoint مخصص",        "icon": "🔗", "color": "orange"},
}

def _meta(key: str) -> dict:
    return MODEL_META.get(key, {"ar": key, "icon": "⚙️", "color": "muted"})


# ── Ollama model helpers ───────────────────────────────────────────────────────

def _split_ollama_name(full_name: str) -> tuple[str, str]:
    """'aya:8b' → ('aya', '8b'),  'llama3:latest' → ('llama3', 'latest')."""
    if ":" in full_name:
        idx = full_name.index(":")
        return full_name[:idx], full_name[idx + 1:]
    return full_name, "latest"

# Keep old name for backward compat
def _split_ollama_quant(full_name: str) -> tuple[str, str]:
    base, tag = _split_ollama_name(full_name)
    return full_name, ""   # always return full_name as base so combo stores it correctly


def _group_ollama_models(raw_models: list) -> dict:
    """Group by base model name → list of (label, full_name)."""
    groups: dict = defaultdict(list)
    for item in raw_models:
        name = item.get("name", "") if isinstance(item, dict) else str(item)
        if not name:
            continue
        base, tag = _split_ollama_name(name)
        size_gb   = item.get("size_gb", 0) if isinstance(item, dict) else 0
        label     = f"{tag}  ({size_gb:.1f} GB)" if size_gb else tag
        groups[base].append((label, name))
    return dict(groups)


# ── Model load worker ─────────────────────────────────────────────────────────

class ModelWorker(QThread):
    done = Signal(bool, str)   # success, message

    def __init__(self, engine, key: str, action: str):
        super().__init__()
        self._engine = engine
        self._key    = key
        self._action = action   # "load" | "unload"

    def run(self):
        try:
            if self._action == "load":
                ok = self._engine.load_model(self._key)
                self.done.emit(ok, "تم التحميل" if ok else "فشل التحميل")
            else:
                self._engine.unload_model(self._key)
                self.done.emit(True, "تم الإيقاف")
        except Exception as e:
            self.done.emit(False, str(e))


class OllamaFetchWorker(QThread):
    done = Signal(list)

    def __init__(self, engine):
        super().__init__()
        self._engine = engine

    def run(self):
        try:
            models = self._engine.get_ollama_models()
            self.done.emit(models)
        except Exception:
            self.done.emit([])


# ── Model button (left panel) ─────────────────────────────────────────────────

class ModelButton(QPushButton):
    def __init__(self, key: str, parent=None):
        meta = _meta(key)
        super().__init__(f"  {meta['icon']}  {meta['ar']}", parent)
        self.model_key = key
        self.setObjectName("model_nav_btn")
        self.setCheckable(False)
        self.setProperty("active", False)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMinimumHeight(44)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Status chip on the right
        self._chip = QLabel("غير محمّل", self)
        self._chip.setStyleSheet(f"""
            background: {theme.c['card2']};
            color: {theme.c['muted']};
            border-radius: 8px;
            padding: 1px 8px;
            font-size: 10px;
        """)
        self._chip.setFixedHeight(18)
        self._chip.adjustSize()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Physical-left side so it doesn't overlap RTL Arabic text (which grows rightward→left)
        self._chip.move(8, (self.height() - self._chip.height()) // 2)

    def update_status(self, loaded: bool, active: bool):
        c = theme.c
        if active:
            text, bg, fg = "نشط ★", f"rgba(233,69,96,51)", c['accent2']
        elif loaded:
            text, bg, fg = "محمّل ✓", f"rgba(63,185,80,38)", c['green2']
        else:
            text, bg, fg = "غير محمّل", c['card2'], c['muted']
        self._chip.setText(text)
        self._chip.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:8px;"
            f" padding:1px 8px; font-size:10px;"
        )
        self._chip.adjustSize()
        self.resizeEvent(None)

    def set_active(self, active: bool):
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)


# ── Detail panel ──────────────────────────────────────────────────────────────

class DetailPanel(QFrame):
    """يعرض تفاصيل وإعدادات النموذج المحدد."""

    action_done = Signal(str)   # رسالة نجاح/فشل

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("surface")
        self._engine       = None
        self._current      = None
        self._worker: ModelWorker | None = None
        self._worker_fetch: OllamaFetchWorker | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(14)
        self._lay = lay
        self._show_empty()

    def set_engine(self, engine):
        self._engine = engine

    def _clear(self):
        def _clear_layout(lay):
            while lay.count():
                item = lay.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    _clear_layout(item.layout())
        _clear_layout(self._lay)

    def _show_empty(self):
        self._clear()
        lbl = QLabel("← اختر نموذجاً من القائمة")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"color: {theme.c['muted']}; font-size: 15px;")
        self._lay.addWidget(lbl)
        self._lay.addStretch()

    def load_model_detail(self, key: str, info: dict):
        self._clear()
        self._current = key
        c = theme.c
        meta = _meta(key)

        # Header
        hdr = QHBoxLayout()
        icon = QLabel(meta["icon"])
        icon.setStyleSheet(
            f"font-size: 26px; color: {c['primary']};"
            f" background: transparent; border: none;"
        )
        icon.setFixedWidth(36)
        name = QLabel(meta["ar"])
        name.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {c['primary']};"
            f" background: transparent; border: none;"
        )
        desc_text = info.get("description", "")
        nt = QVBoxLayout()
        nt.setSpacing(2)
        nt.addWidget(name)
        if desc_text:
            desc = QLabel(desc_text)
            desc.setWordWrap(False)
            desc.setMaximumWidth(500)
            desc.setStyleSheet(
                f"color: {c['muted']}; font-size: 11px;"
                f" background: transparent; border: none;"
            )
            nt.addWidget(desc)

        hdr.addWidget(icon)
        hdr.addSpacing(8)
        hdr.addLayout(nt, 1)
        self._lay.addLayout(hdr)

        # Divider
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {c['border']}; border: none;")
        self._lay.addWidget(div)

        is_loaded = info.get("is_loaded", info.get("loaded", False))
        is_active = info.get("is_active", info.get("active", False))

        # Extra config per model type (Ollama handles its own buttons inside)
        config_type = info.get("type", "")
        self._build_config_fields(key, config_type, info)

        # Generic action buttons — Ollama builds its own inside _build_ollama_fields
        if key != "ollama":
            btn_row = QHBoxLayout()

            self._load_btn = QPushButton("⏹  إيقاف" if is_loaded else "▶  تحميل")
            self._load_btn.setObjectName("btn_danger" if is_loaded else "btn_success")
            self._load_btn.clicked.connect(lambda: self._toggle_load(key, is_loaded))
            btn_row.addWidget(self._load_btn)

            if not is_active:
                act_btn = QPushButton("★  تعيين نشطاً")
                act_btn.setObjectName("btn_info")
                act_btn.clicked.connect(lambda: self._set_active(key))
                btn_row.addWidget(act_btn)
            else:
                badge = QLabel("★  النموذج النشط الآن")
                badge.setStyleSheet(
                    f"color: {c['accent2']}; font-weight: bold;"
                    f" background: transparent; border: none;"
                )
                btn_row.addWidget(badge)

            btn_row.addStretch()
            self._lay.addLayout(btn_row)

            self._prog = QProgressBar()
            self._prog.setRange(0, 0)
            self._prog.setFixedHeight(4)
            self._prog.setVisible(False)
            self._lay.addWidget(self._prog)

        self._lay.addStretch()

    def _build_config_fields(self, key: str, config_type: str, info: dict):
        """يُنشئ حقول الإعداد الخاصة بكل نوع نموذج."""
        c = theme.c

        if key == "ollama":
            self._build_ollama_fields(info)

        elif config_type == "deepl":
            self._field_row("🔑  مفتاح API:", QLineEdit(), "deepl_key_field",
                            info.get("api_key", ""), is_password=True,
                            save_fn=lambda v: self._save_config_field(key, "api_key", v))

        elif config_type == "custom":
            self._field_row("🔗  عنوان URL:", QLineEdit(), "custom_url_field",
                            info.get("url", "http://localhost:5001/translate"),
                            save_fn=lambda v: self._save_config_field(key, "url", v))

    def _field_row(self, label: str, widget: QLineEdit, obj_name: str,
                   value: str, is_password: bool = False, save_fn=None):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {theme.c['muted']}; min-width: 120px;"
            f" background: transparent; border: none;"
        )
        widget.setObjectName(obj_name)
        widget.setText(value)
        if is_password:
            widget.setEchoMode(QLineEdit.Password)
        row.addWidget(lbl)
        row.addWidget(widget, 1)
        if save_fn:
            save = QPushButton("حفظ")
            save.setObjectName("btn_secondary")
            save.setFixedWidth(70)
            save.clicked.connect(lambda: save_fn(widget.text().strip()))
            row.addWidget(save)
        self._lay.addLayout(row)

    def _build_ollama_fields(self, info: dict):
        c = theme.c
        lbl_style = (f"color: {c['muted']}; min-width: 130px;"
                     f" background: transparent; border: none;")

        is_loaded = info.get("is_loaded", info.get("loaded", False))
        is_active = info.get("is_active", info.get("active", False))
        current   = info.get("current_model", "")
        self._ollama_loaded = is_loaded
        self._ollama_active = is_active
        self._ollama_groups: dict = {}

        # ── Status indicator ─────────────────────────────────
        status_row = QHBoxLayout()
        self._ollama_dot = QLabel("●")
        self._ollama_dot.setStyleSheet(
            f"color: {c['green2'] if is_loaded else c['muted']};"
            f" font-size: 16px; background: transparent; border: none;"
        )
        self._ollama_dot.setFixedWidth(22)
        self._ollama_model_lbl = QLabel(current if is_loaded and current else "غير متصل")
        self._ollama_model_lbl.setStyleSheet(
            f"color: {c['primary'] if is_loaded else c['muted']};"
            f" font-size: 13px; {'font-weight: bold;' if is_loaded else ''}"
            f" background: transparent; border: none;"
        )
        status_row.addWidget(self._ollama_dot)
        status_row.addWidget(self._ollama_model_lbl, 1)
        self._lay.addLayout(status_row)

        # ── URL row ──────────────────────────────────────────
        url_row = QHBoxLayout()
        url_lbl = QLabel("🌐  عنوان Ollama:")
        url_lbl.setStyleSheet(lbl_style)
        self._ollama_url = QLineEdit()
        self._ollama_url.setText(info.get("url", "http://localhost:11434"))
        url_row.addWidget(url_lbl)
        url_row.addWidget(self._ollama_url, 1)
        self._lay.addLayout(url_row)

        # ── Model (base) row ─────────────────────────────────
        mdl_row = QHBoxLayout()
        mdl_lbl = QLabel("🤖  النموذج:")
        mdl_lbl.setStyleSheet(lbl_style)
        self._ollama_combo = QComboBox()
        self._ollama_combo.setMinimumWidth(200)
        base, tag = _split_ollama_name(current) if current else ("", "")
        self._ollama_combo.addItem(base or current, base or current)
        self._ollama_combo.currentIndexChanged.connect(self._on_ollama_base_changed)
        theme.style_combo(self._ollama_combo)

        refresh_btn = QPushButton("🔄")
        refresh_btn.setObjectName("icon_btn")
        refresh_btn.setFixedSize(32, 32)
        refresh_btn.setToolTip("جلب قائمة النماذج من الخادم")
        refresh_btn.clicked.connect(self._fetch_ollama_models)

        mdl_row.addWidget(mdl_lbl)
        mdl_row.addWidget(self._ollama_combo, 1)
        mdl_row.addWidget(refresh_btn)
        self._lay.addLayout(mdl_row)

        # ── Version/tag row ──────────────────────────────────
        quant_row = QHBoxLayout()
        quant_lbl = QLabel("⚡  الإصدار:")
        quant_lbl.setStyleSheet(lbl_style)
        self._ollama_quant_combo = QComboBox()
        self._ollama_quant_combo.setMinimumWidth(200)
        if current:
            self._ollama_quant_combo.addItem(tag or current, current)
        else:
            self._ollama_quant_combo.addItem("—", "")
        theme.style_combo(self._ollama_quant_combo)
        quant_row.addWidget(quant_lbl)
        quant_row.addWidget(self._ollama_quant_combo, 1)
        self._lay.addLayout(quant_row)

        # ── Action buttons (2 dynamic) ───────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._load_btn = QPushButton("⏹  إلغاء تحميل" if is_loaded else "▶  تحميل")
        self._load_btn.setObjectName("btn_danger" if is_loaded else "btn_success")
        self._load_btn.setFixedHeight(36)
        self._load_btn.clicked.connect(self._on_ollama_load_toggle)
        btn_row.addWidget(self._load_btn)

        self._act_btn = QPushButton("★  نشط" if is_active else "★  تنشيط")
        self._act_btn.setObjectName("btn_success" if is_active else "btn_danger")
        self._act_btn.setFixedHeight(36)
        self._act_btn.clicked.connect(self._on_ollama_activate)
        btn_row.addWidget(self._act_btn)

        btn_row.addStretch()
        self._lay.addLayout(btn_row)

        # Progress bar (hidden until loading)
        self._prog = QProgressBar()
        self._prog.setRange(0, 0)
        self._prog.setFixedHeight(4)
        self._prog.setVisible(False)
        self._lay.addWidget(self._prog)

        # Auto-fetch after short delay
        QTimer.singleShot(200, self._fetch_ollama_models)

    def _on_ollama_base_changed(self, _idx: int):
        """يُحدّث قائمة الـ quant عند تغيير النموذج الأساسي."""
        base = self._ollama_combo.currentData() or self._ollama_combo.currentText()
        variants = self._ollama_groups.get(base, [])
        self._ollama_quant_combo.blockSignals(True)
        self._ollama_quant_combo.clear()
        if not variants:
            self._ollama_quant_combo.addItem("افتراضي (كامل)", "")
        else:
            for label, full_name in variants:
                self._ollama_quant_combo.addItem(label, full_name)
        self._ollama_quant_combo.blockSignals(False)

    def _fetch_ollama_models(self):
        if not self._engine:
            return
        if self._worker_fetch and self._worker_fetch.isRunning():
            return
        w = OllamaFetchWorker(self._engine)
        w.done.connect(self._on_ollama_models)
        w.done.connect(w.deleteLater)
        self._worker_fetch = w
        w.start()
        self.action_done.emit("جاري جلب النماذج...")

    def _on_ollama_models(self, models: list):
        self._worker_fetch = None
        if not models:
            self.action_done.emit("⚠  Ollama غير متاح أو لا توجد نماذج مثبتة")
            return

        self._ollama_groups = _group_ollama_models(models)
        current = self._engine.get_current_ollama_model() if self._engine else ""
        cur_base, cur_tag = _split_ollama_name(current) if current else ("", "")

        # Populate base combo
        self._ollama_combo.blockSignals(True)
        self._ollama_combo.clear()
        for base in self._ollama_groups:
            self._ollama_combo.addItem(base, base)
        idx = self._ollama_combo.findData(cur_base)
        if idx < 0:
            idx = self._ollama_combo.findText(cur_base)
        self._ollama_combo.setCurrentIndex(max(idx, 0))
        self._ollama_combo.blockSignals(False)

        # Populate version combo for current base
        self._on_ollama_base_changed(0)
        # Select the current version
        if current:
            qi = self._ollama_quant_combo.findData(current)
            if qi >= 0:
                self._ollama_quant_combo.setCurrentIndex(qi)

        self.action_done.emit(
            f"✓  {len(models)} نموذج في {len(self._ollama_groups)} مجموعة"
        )

    def _on_ollama_load_toggle(self):
        """تحميل أو إلغاء تحميل نموذج Ollama."""
        if not self._engine:
            return
        if self._worker and self._worker.isRunning():
            return

        c = theme.c
        if self._ollama_loaded:
            # Unload
            self._load_btn.setEnabled(False)
            self._load_btn.setText("⏳  جاري الإيقاف…")
            self._act_btn.setEnabled(False)
            self._prog.setVisible(True)
            w = ModelWorker(self._engine, "ollama", "unload")
            w.done.connect(self._on_ollama_load_done)
            w.done.connect(w.deleteLater)
            self._worker = w
            w.start()
        else:
            # Load selected model
            full_name = self._ollama_quant_combo.currentData() or ""
            if not full_name:
                full_name = self._ollama_combo.currentData() or self._ollama_combo.currentText()
            if not full_name:
                self.action_done.emit("⚠  اختر نموذجاً أولاً")
                return
            self._engine.set_ollama_model(full_name)
            self._load_btn.setEnabled(False)
            self._load_btn.setText("⏳  جاري التحميل…")
            self._act_btn.setEnabled(False)
            self._prog.setVisible(True)
            w = ModelWorker(self._engine, "ollama", "load")
            w.done.connect(self._on_ollama_load_done)
            w.done.connect(w.deleteLater)
            self._worker = w
            w.start()
            self.action_done.emit(f"⏳  جاري تحميل واختبار ← {full_name} (قد يستغرق دقيقة للنماذج الكبيرة)")

    def _on_ollama_load_done(self, ok: bool, msg: str):
        self._worker = None
        self._prog.setVisible(False)
        self._load_btn.setEnabled(True)
        self._act_btn.setEnabled(True)
        c = theme.c

        if ok:
            if self._ollama_loaded:
                # Was loaded → now unloaded
                self._ollama_loaded = False
                self._ollama_active = False
                self._load_btn.setText("▶  تحميل")
                self._load_btn.setObjectName("btn_success")
                self._act_btn.setText("★  تنشيط")
                self._act_btn.setObjectName("btn_danger")
                self._ollama_dot.setStyleSheet(
                    f"color: {c['muted']}; font-size: 16px;"
                    f" background: transparent; border: none;"
                )
                self._ollama_model_lbl.setText("غير متصل")
                self._ollama_model_lbl.setStyleSheet(
                    f"color: {c['muted']}; font-size: 13px;"
                    f" background: transparent; border: none;"
                )
            else:
                # Was unloaded → now loaded
                self._ollama_loaded = True
                model_name = self._engine.get_current_ollama_model() if self._engine else ""
                self._load_btn.setText("⏹  إلغاء تحميل")
                self._load_btn.setObjectName("btn_danger")
                self._ollama_dot.setStyleSheet(
                    f"color: {c['green2']}; font-size: 16px;"
                    f" background: transparent; border: none;"
                )
                self._ollama_model_lbl.setText(model_name or "متصل")
                self._ollama_model_lbl.setStyleSheet(
                    f"color: {c['primary']}; font-size: 13px; font-weight: bold;"
                    f" background: transparent; border: none;"
                )
            for btn in (self._load_btn, self._act_btn):
                btn.style().unpolish(btn)
                btn.style().polish(btn)
        else:
            # Operation failed — restore button to previous state
            if self._ollama_loaded:
                self._load_btn.setText("⏹  إلغاء تحميل")
                self._load_btn.setObjectName("btn_danger")
            else:
                self._load_btn.setText("▶  تحميل")
                self._load_btn.setObjectName("btn_success")
            self._load_btn.style().unpolish(self._load_btn)
            self._load_btn.style().polish(self._load_btn)

            tr  = self._engine.get_translator("ollama") if self._engine else None
            err = getattr(tr, "_last_error", "") or msg
            self._ollama_dot.setStyleSheet(
                f"color: {c['accent']}; font-size: 16px;"
                f" background: transparent; border: none;"
            )
            self._ollama_model_lbl.setText(err[:100] if err else "فشل التحميل")
            self._ollama_model_lbl.setStyleSheet(
                f"color: {c['accent']}; font-size: 11px;"
                f" background: transparent; border: none;"
            )

        self.action_done.emit(("✓  " if ok else "✗  ") + msg)

    def _on_ollama_activate(self):
        """تعيين Ollama كنموذج نشط أو إلغاء تنشيطه."""
        if not self._engine:
            return
        c = theme.c
        if not self._ollama_loaded:
            self.action_done.emit("⚠  حمّل النموذج أولاً قبل التنشيط")
            return
        self._engine.set_active_model("ollama")
        self._ollama_active = True
        self._act_btn.setText("★  نشط")
        self._act_btn.setObjectName("btn_success")
        self._act_btn.style().unpolish(self._act_btn)
        self._act_btn.style().polish(self._act_btn)
        model_name = self._engine.get_current_ollama_model() if self._engine else ""
        self.action_done.emit(f"★  Ollama نشط ← {model_name}")

    def _toggle_load(self, key: str, currently_loaded: bool):
        if not self._engine:
            return
        if self._worker and self._worker.isRunning():
            return
        action = "unload" if currently_loaded else "load"
        self._load_btn.setEnabled(False)
        self._prog.setVisible(True)
        w = ModelWorker(self._engine, key, action)
        w.done.connect(self._on_load_done)
        w.done.connect(w.deleteLater)
        self._worker = w
        w.start()

    def _on_load_done(self, ok: bool, msg: str):
        self._worker = None
        if hasattr(self, "_prog"):
            self._prog.setVisible(False)
        if hasattr(self, "_load_btn"):
            self._load_btn.setEnabled(True)
            if ok:
                self._load_btn.setText("⏹  إيقاف")
                self._load_btn.setObjectName("btn_danger")
                self._load_btn.style().unpolish(self._load_btn)
                self._load_btn.style().polish(self._load_btn)
        self.action_done.emit(("✓  " if ok else "✗  ") + msg)

    def _set_active(self, key: str):
        if self._engine:
            self._engine.set_active_model(key)
            self.action_done.emit(f"★  النموذج النشط: {_meta(key)['ar']}")

    def _save_config_field(self, model_key: str, field: str, value: str):
        self.action_done.emit(f"✓  تم الحفظ (يُطبَّق عند إعادة التشغيل)")


# ── System prompt editor ──────────────────────────────────────────────────────

class SystemPromptEditor(QFrame):
    status_message = Signal(str)

    def __init__(self, engine, config_path: str, parent=None):
        super().__init__(parent)
        self._engine      = engine
        self._config_path = config_path
        self.setObjectName("card")
        self._build()
        self._load()

    def _build(self):
        c = theme.c
        self.setStyleSheet(f"""
            QFrame#card {{
                background: {c['card']};
                border: 1px solid {c['border']};
                border-radius: 10px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(10)

        # Header row
        hdr = QHBoxLayout()
        t = QLabel("📝  برومت الترجمة")
        t.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {c['primary']};"
            f" background: transparent; border: none;"
        )
        hdr.addWidget(t)
        hdr.addStretch()

        reset_btn = QPushButton("إعادة تعيين")
        reset_btn.setObjectName("btn_secondary")
        reset_btn.clicked.connect(self._reset)
        save_btn = QPushButton("💾  حفظ")
        save_btn.setObjectName("btn_primary")
        save_btn.clicked.connect(self._save)
        hdr.addWidget(reset_btn)
        hdr.addSpacing(8)
        hdr.addWidget(save_btn)
        lay.addLayout(hdr)

        # Text editor — عربي RTL
        self._edit = QTextEdit()
        self._edit.setMinimumHeight(160)
        self._edit.setPlaceholderText("اكتب برومت الترجمة هنا...")
        self._edit.setStyleSheet(f"""
            QTextEdit {{
                background: {c['card2']};
                border: 1px solid {c['border']};
                border-radius: 6px;
                color: {c['primary']};
                font-family: 'Consolas', monospace;
                font-size: 12px;
                padding: 10px;
            }}
            QTextEdit:focus {{ border-color: {c['blue']}; }}
        """)
        lay.addWidget(self._edit)

        hint = QLabel("يُطبَّق على نماذج Ollama والـ Endpoints المخصصة")
        hint.setStyleSheet(
            f"color: {c['muted']}; font-size: 11px;"
            f" background: transparent; border: none;"
        )
        lay.addWidget(hint)

    def _load(self):
        try:
            with open(self._config_path, encoding="utf-8") as f:
                cfg = json.load(f)
            prompt = cfg.get("system_prompt", "")
            if not prompt:
                from engine.models.api_translator import _default_ollama_system_prompt
                prompt = _default_ollama_system_prompt()
            self._edit.setPlainText(prompt)
        except Exception:
            pass

    def _save(self):
        prompt = self._edit.toPlainText().strip()
        if not prompt:
            return
        try:
            with open(self._config_path, encoding="utf-8") as f:
                cfg = json.load(f)
            cfg["system_prompt"] = prompt
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            # Apply to live translators
            if self._engine:
                for key in ("ollama", "custom_endpoint"):
                    t = self._engine.get_translator(key)
                    if t and hasattr(t, "system_prompt"):
                        t.system_prompt = prompt
            self.status_message.emit("✓  تم حفظ البرومت وتطبيقه")
        except Exception as e:
            self.status_message.emit(f"✗  خطأ: {e}")

    def _reset(self):
        from engine.models.api_translator import _default_ollama_system_prompt
        self._edit.setPlainText(_default_ollama_system_prompt())
        self.status_message.emit("تم إعادة تعيين البرومت — اضغط «حفظ» لتطبيقه")

    def refresh_theme(self):
        c = theme.c
        self.setStyleSheet(f"""
            QFrame#card {{
                background: {c['card']};
                border: 1px solid {c['border']};
                border-radius: 10px;
            }}
        """)
        self._edit.setStyleSheet(f"""
            QTextEdit {{
                background: {c['card2']};
                border: 1px solid {c['border']};
                border-radius: 6px;
                color: {c['primary']};
                font-family: 'Consolas', monospace;
                font-size: 12px;
                padding: 10px;
            }}
            QTextEdit:focus {{ border-color: {c['blue']}; }}
        """)

    def set_engine(self, engine):
        self._engine = engine


# ── Models page ───────────────────────────────────────────────────────────────

class ModelsPage(QWidget):
    """صفحة نماذج الترجمة الكاملة."""

    model_activated = Signal(str)   # يُرسَل إلى sidebar
    status_message  = Signal(str)

    def __init__(self, engine=None, parent=None):
        super().__init__(parent)
        self._engine  = engine
        self._buttons: dict[str, ModelButton] = {}
        self._worker: ModelWorker | None = None
        self._config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))),
            "config.json"
        )
        self._build()
        if engine:
            self.refresh()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        c   = theme.c
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_topbar())

        body = QWidget()
        body.setObjectName("models_body")
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)
        self._model_list_frame = self._build_model_list()
        body_lay.addWidget(self._model_list_frame)
        body_lay.addWidget(self._build_right_panel(), 1)

        lay.addWidget(body, 1)

    def _build_topbar(self) -> QFrame:
        bar, lay = make_topbar("🤖", "نماذج الترجمة")

        self._active_lbl = QLabel("لا يوجد نموذج نشط")
        self._active_lbl.setStyleSheet(
            f"color: {theme.c['muted']}; font-size: 12px;"
        )
        lay.addWidget(self._active_lbl)

        # فلتر حماية التاقات (عام لكل التطبيق)
        from engine.filtered_translator import get_global_tag_mode, set_global_tag_mode
        c = theme.c
        tag_lbl = QLabel("🛡 الفلتر:")
        tag_lbl.setStyleSheet(
            f"color: {c['muted']}; font-size: 12px; background: transparent; border: none;"
        )
        lay.addSpacing(12)
        lay.addWidget(tag_lbl)

        self._tag_mode_combo = QComboBox()
        self._tag_mode_combo.addItem("🛡 Bulletproof — ⟦N⟧ + cascade  (موصى)", "bulletproof")
        self._tag_mode_combo.addItem("🎯 Tiered — [tN]/[sN]",                  "tiered")
        self._tag_mode_combo.addItem("🔒 Strip — PUA characters",              "strip")
        self._tag_mode_combo.addItem("🏷 Inline — تاقات تبقى مع النص",         "inline")
        self._tag_mode_combo.setToolTip(
            "فلتر حماية التاقات (يُطبَّق على كل ترجمات البروكسي وزر إعادة الترجمة).\n"
            "Bulletproof: الأقوى — يحمي بـ ⟦N⟧ ويتراجع تلقائياً عند الفشل.\n"
            "Tiered: علامات [tN]/[sN] للمودلات المتوسطة.\n"
            "Strip: محارف PUA للمودلات الصغيرة.\n"
            "Inline: لا حماية — للمودلات الذكية فقط."
        )
        self._tag_mode_combo.setStyleSheet(f"""
            QComboBox {{
                background: {c['card2']}; color: {c.get('secondary', '#e8e8e8')};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 4px 10px; font-size: 12px; min-width: 240px;
            }}
            QComboBox:hover {{ border-color: {c['accent']}; }}
        """)
        current = get_global_tag_mode()
        idx = self._tag_mode_combo.findData(current)
        if idx >= 0:
            self._tag_mode_combo.setCurrentIndex(idx)

        def _on_tag_mode_changed(_i: int):
            mode = self._tag_mode_combo.currentData()
            if not mode:
                return
            try:
                set_global_tag_mode(mode)
            except Exception as e:
                self.status_message.emit(f"✗  تعذّر حفظ الفلتر: {e}")
                return
            self.status_message.emit(f"✓  الفلتر العام: {mode}  (يُطبَّق فوراً)")
            # طبّق على البروكسي إذا كان يعمل
            try:
                from engine import proxy_server as _ps  # noqa
                # البروكسي سيقرأ من config.json عند start() القادم؛
                # لكن لو يعمل الآن، حدّثه مباشرة عبر set_tag_mode إذا متاح
                proxy = getattr(self, "_proxy_ref", None)
                if proxy and hasattr(proxy, "set_tag_mode"):
                    proxy.set_tag_mode(mode)
            except Exception:
                pass

        self._tag_mode_combo.currentIndexChanged.connect(_on_tag_mode_changed)
        lay.addWidget(self._tag_mode_combo)

        reload_btn = QPushButton("🔄  تحديث")
        reload_btn.setObjectName("btn_secondary")
        reload_btn.clicked.connect(self.refresh)
        lay.addWidget(reload_btn)
        return bar

    def set_proxy_ref(self, proxy):
        """يستلم مرجع البروكسي لتطبيق tag_mode فوراً عند التغيير."""
        self._proxy_ref = proxy

    def _build_model_list(self) -> QFrame:
        c = theme.c
        frame = QFrame()
        frame.setObjectName("sidebar")
        frame.setStyleSheet(f"""
            QFrame#sidebar {{
                background: {c['surface']};
                border-right: 1px solid {c['border']};
                min-width: 220px;
                max-width: 260px;
            }}
        """)
        frame.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 8, 0, 8)
        lay.setSpacing(0)

        sec = QLabel("  النماذج المتاحة")
        sec.setObjectName("nav_section_label")
        lay.addWidget(sec)

        self._model_list_lay = QVBoxLayout()
        self._model_list_lay.setSpacing(0)
        self._model_list_lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(self._model_list_lay)
        lay.addStretch()

        return frame

    def _build_right_panel(self) -> QWidget:
        c = theme.c
        w = QWidget()
        w.setObjectName("model_right_panel")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(16)

        self._detail = DetailPanel()
        self._detail.action_done.connect(self._on_action_done)
        lay.addWidget(self._detail, 1)

        # System prompt editor
        self._prompt_editor = SystemPromptEditor(self._engine, self._config_path)
        self._prompt_editor.status_message.connect(self.status_message)
        lay.addWidget(self._prompt_editor)

        return w

    def refresh_theme(self):
        c = theme.c
        self._model_list_frame.setStyleSheet(f"""
            QFrame#sidebar {{
                background: {c['surface']};
                border-right: 1px solid {c['border']};
                min-width: 220px;
                max-width: 260px;
            }}
        """)
        self._prompt_editor.refresh_theme()
        self.refresh()

    # ── Data ──────────────────────────────────────────────────────────────────

    def refresh(self):
        if not self._engine:
            return

        # Clear existing buttons
        while self._model_list_lay.count():
            item = self._model_list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._buttons.clear()

        models   = self._engine.get_available_models()
        active   = self._engine.get_active_model()
        cfg      = self._load_config()
        mdl_cfg  = cfg.get("models", {})

        for info in models:
            key      = info["key"]
            btn      = ModelButton(key)
            btn.update_status(info["is_loaded"], info["is_active"])
            btn.clicked.connect(lambda _, k=key: self._select_model(k))
            self._model_list_lay.addWidget(btn)
            self._buttons[key] = btn

        self._model_list_lay.addStretch()

        # Update active label
        if active:
            ar = _meta(active)["ar"]
            self._active_lbl.setText(f"نشط: {ar}")
            self.model_activated.emit(ar)
        else:
            self._active_lbl.setText("لا يوجد نموذج نشط")

        self._detail.set_engine(self._engine)
        self._prompt_editor.set_engine(self._engine)

        # Auto-select and open the active model detail panel
        if active and active in self._buttons:
            self._buttons[active].set_active(True)
            QTimer.singleShot(50, lambda: self._select_model(active))

    def _select_model(self, key: str):
        models  = self._engine.get_available_models()
        active  = self._engine.get_active_model()
        cfg     = self._load_config()
        mdl_cfg = cfg.get("models", {})

        # Update button highlight
        for k, btn in self._buttons.items():
            btn.set_active(k == key)

        # Find model info
        info_map = {m["key"]: m for m in models}
        info     = dict(info_map.get(key, {}))
        info["active"] = (key == active)
        # Merge config extras (url, api_key, etc.)
        for k, v in mdl_cfg.get(key, {}).items():
            info.setdefault(k, v)
        info["current_model"] = self._engine.get_current_ollama_model() if key == "ollama" else ""

        self._detail.load_model_detail(key, info)

    def _on_action_done(self, msg: str):
        self.status_message.emit(msg)
        # Refresh button statuses
        if self._engine:
            models = self._engine.get_available_models()
            active = self._engine.get_active_model()
            for info in models:
                k = info["key"]
                if k in self._buttons:
                    self._buttons[k].update_status(info["is_loaded"], info["is_active"])
            # Update active label + emit signal
            if active:
                ar = _meta(active)["ar"]
                self._active_lbl.setText(f"نشط: {ar}")
                self.model_activated.emit(ar)

    def set_engine(self, engine):
        self._engine = engine
        self._detail.set_engine(engine)
        self._prompt_editor.set_engine(engine)
        self.refresh()

    def _load_config(self) -> dict:
        try:
            with open(self._config_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
