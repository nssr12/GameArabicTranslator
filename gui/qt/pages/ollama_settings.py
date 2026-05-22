"""
gui/qt/pages/ollama_settings.py — تبويب إعدادات Ollama + مراقبة الموارد.

يسمح بـ:
  - تعديل ollama_options بصرياً وحفظها في config.json
  - مراقبة CPU/RAM/GPU/VRAM لحظياً
  - رؤية المودلات المُحمَّلة حالياً في Ollama
"""
from __future__ import annotations
import json
import os
import subprocess
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QLineEdit, QGridLayout, QProgressBar, QMessageBox, QSizePolicy,
    QScrollArea,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCursor

from gui.qt.theme import theme


# ── إعدادات Ollama قابلة للتعديل ──────────────────────────────────────────
# (key, label, default, hint, type)
_FIELDS = [
    ("num_gpu",        "num_gpu",        999,    "عدد الـlayers على GPU (999=الكل، 0=CPU فقط)", int),
    ("num_thread",     "num_thread",     8,      "عدد CPU threads (= عدد نوى المعالج)", int),
    ("num_ctx",        "num_ctx",        512,    "حجم الـcontext window (tokens)", int),
    ("num_batch",      "num_batch",      512,    "حجم batch (للسرعة في معالجة الـ prompt)", int),
    ("num_predict",    "num_predict",    256,    "أقصى tokens في الرد", int),
    ("temperature",    "temperature",    0.1,    "0.0 حتمي، 1.0 إبداعي (0.1 مثالي للترجمة)", float),
    ("top_k",          "top_k",          20,     "أفضل K كلمة عند التوليد (20 جيد)", int),
    ("top_p",          "top_p",          0.9,    "Nucleus sampling (0.9 جيد للترجمة)", float),
    ("repeat_penalty", "repeat_penalty", 1.1,    "عقوبة التكرار (1.0=بلا، 1.1 يمنع التكرار)", float),
    ("seed",           "seed",           -1,     "-1 عشوائي، رقم ثابت للنتائج المُكرَّرة", int),
    ("timeout",        "timeout (ث)",    60,     "مهلة الطلب بالثواني", int),
    ("keep_alive",     "keep_alive",     "30m",  "بقاء المودل بالذاكرة: 30m, 1h, -1 للأبد", str),
]


class _ResourceBar(QWidget):
    """شريط أفقي يعرض نسبة استخدام مورد (CPU/RAM/...)."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        c = theme.c
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(8)

        self._label = QLabel(label)
        self._label.setFixedWidth(70)
        self._label.setStyleSheet(
            f"color: {c['secondary']}; font-size: 11px; background: transparent; border: none;"
        )

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setFixedHeight(16)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet(f"""
            QProgressBar {{
                background: {c['card']}; border: 1px solid {c['border']};
                border-radius: 6px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {c.get('teal', '#00d2ff')}, stop:1 {c.get('accent', '#e94560')});
                border-radius: 5px;
            }}
        """)

        self._value_lbl = QLabel("—")
        self._value_lbl.setFixedWidth(150)
        self._value_lbl.setStyleSheet(
            f"color: {c['primary']}; font-size: 11px; font-family: Consolas;"
            " background: transparent; border: none;"
        )
        self._value_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        lay.addWidget(self._label)
        lay.addWidget(self._bar, 1)
        lay.addWidget(self._value_lbl)

    def update_value(self, percent: float, text: str = ""):
        self._bar.setValue(int(max(0, min(100, percent))))
        self._value_lbl.setText(text or f"{percent:.0f}%")


class OllamaSettingsPage(QWidget):
    """تبويب إعدادات Ollama: تعديل options + مراقبة الموارد."""

    saved          = Signal()
    status_message = Signal(str)

    POLL_INTERVAL_MS = 1500

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))),
            "config.json"
        )
        self._fields: dict[str, QLineEdit] = {}
        self._build()
        self._load_values()

        # مؤقّت تحديث الموارد كل 1.5 ثانية
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self.POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._refresh_resources)
        self._poll_timer.start()
        self._refresh_resources()  # تحديث فوري

    # ── Build ─────────────────────────────────────────────────────────────

    def _build(self):
        c = theme.c
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { border: none; }"
            " QScrollArea > QWidget { background: transparent; }"
        )

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(28, 20, 28, 32)
        lay.setSpacing(20)

        lay.addWidget(self._build_options_section())
        lay.addWidget(self._build_resources_section())
        lay.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _build_options_section(self) -> QFrame:
        c = theme.c
        frame = QFrame()
        frame.setObjectName("section")
        frame.setStyleSheet(f"""
            QFrame#section {{
                background: {c['card']};
                border: 1px solid {c['border']};
                border-radius: 10px;
            }}
        """)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        title = QLabel("🧠  إعدادات Ollama")
        title.setStyleSheet(
            f"color: {c['accent']}; font-weight: bold; font-size: 14px;"
            " background: transparent; border: none;"
        )
        lay.addWidget(title)

        hint = QLabel(
            "هذه القيم تُرسَل لكل طلب ترجمة. تتطلب إعادة تشغيل التطبيق "
            "لتفعيلها (تُقرَأ عند تحميل المحرّك)."
        )
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 10px;"
                           " background: transparent; border: none;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # شبكة الحقول
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        for i, (key, label, default, h, type_) in enumerate(_FIELDS):
            row = i // 2
            col_label = (i % 2) * 3
            col_input = col_label + 1
            col_hint  = col_label + 2

            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"color: {c['primary']}; font-size: 11px; font-weight: bold;"
                " background: transparent; border: none;"
            )
            lbl.setFixedWidth(110)

            inp = QLineEdit()
            inp.setText(str(default))
            inp.setFixedHeight(26)
            inp.setStyleSheet(f"""
                QLineEdit {{
                    background: {c['card2']}; color: {c['primary']};
                    border: 1px solid {c['border']}; border-radius: 4px;
                    padding: 2px 8px; font-size: 11px;
                    font-family: Consolas, monospace;
                }}
                QLineEdit:focus {{ border-color: {c['accent']}; }}
            """)
            inp.setFixedWidth(110)
            self._fields[key] = inp

            hint_lbl = QLabel(h)
            hint_lbl.setStyleSheet(
                f"color: {c['muted']}; font-size: 9px;"
                " background: transparent; border: none;"
            )
            hint_lbl.setWordWrap(True)

            grid.addWidget(lbl,      row, col_label)
            grid.addWidget(inp,      row, col_input)
            grid.addWidget(hint_lbl, row, col_hint)

        lay.addLayout(grid)

        # أزرار التحكم
        btn_row = QHBoxLayout()
        reset_btn = QPushButton("↺  استعادة الافتراضي")
        reset_btn.setCursor(QCursor(Qt.PointingHandCursor))
        reset_btn.setStyleSheet(_btn_secondary_style(c))
        reset_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        save_btn = QPushButton("💾  حفظ")
        save_btn.setCursor(QCursor(Qt.PointingHandCursor))
        save_btn.setStyleSheet(_btn_primary_style(c))
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)

        return frame

    def _build_resources_section(self) -> QFrame:
        c = theme.c
        frame = QFrame()
        frame.setObjectName("section")
        frame.setStyleSheet(f"""
            QFrame#section {{
                background: {c['card']};
                border: 1px solid {c['border']};
                border-radius: 10px;
            }}
        """)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("📊  موارد النظام")
        title.setStyleSheet(
            f"color: {c['teal']}; font-weight: bold; font-size: 14px;"
            " background: transparent; border: none;"
        )
        title_row.addWidget(title)
        title_row.addStretch()
        self._refresh_lbl = QLabel("● live")
        self._refresh_lbl.setStyleSheet(
            f"color: {c.get('green', '#4caf50')}; font-size: 10px;"
            " background: transparent; border: none;"
        )
        title_row.addWidget(self._refresh_lbl)
        lay.addLayout(title_row)

        # أشرطة الموارد
        self._cpu_bar  = _ResourceBar("CPU")
        self._ram_bar  = _ResourceBar("RAM")
        self._gpu_bar  = _ResourceBar("GPU")
        self._vram_bar = _ResourceBar("VRAM")
        lay.addWidget(self._cpu_bar)
        lay.addWidget(self._ram_bar)
        lay.addWidget(self._gpu_bar)
        lay.addWidget(self._vram_bar)

        # معلومات GPU إضافية
        self._gpu_name_lbl = QLabel("—")
        self._gpu_name_lbl.setStyleSheet(
            f"color: {c['muted']}; font-size: 10px; font-family: Consolas;"
            " background: transparent; border: none; padding-top: 4px;"
        )
        lay.addWidget(self._gpu_name_lbl)

        # المودلات المُحمّلة في Ollama
        ollama_title = QLabel("🤖  مودلات Ollama المُحمَّلة الآن")
        ollama_title.setStyleSheet(
            f"color: {c['blue']}; font-weight: bold; font-size: 11px;"
            " background: transparent; border: none; padding-top: 6px;"
        )
        lay.addWidget(ollama_title)

        self._ollama_models_lbl = QLabel("(يُحدَّث تلقائياً…)")
        self._ollama_models_lbl.setStyleSheet(
            f"color: {c['secondary']}; font-size: 11px; font-family: Consolas;"
            f" background: {c['card2']}; border: 1px solid {c['border']};"
            " border-radius: 4px; padding: 8px; min-height: 40px;"
        )
        self._ollama_models_lbl.setTextFormat(Qt.PlainText)
        self._ollama_models_lbl.setWordWrap(True)
        self._ollama_models_lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lay.addWidget(self._ollama_models_lbl)

        return frame

    # ── Load / Save ───────────────────────────────────────────────────────

    def _load_values(self):
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            opts = cfg.get("ollama_options", {})
            for key, _label, default, _h, _type in _FIELDS:
                val = opts.get(key, default)
                self._fields[key].setText(str(val))
        except Exception as e:
            self.status_message.emit(f"⚠ تعذّر تحميل config.json: {e}")

    def _reset_defaults(self):
        if QMessageBox.question(
            self, "تأكيد",
            "استعادة جميع القيم إلى افتراضياتها؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        for key, _label, default, _h, _type in _FIELDS:
            self._fields[key].setText(str(default))

    def _save(self):
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "خطأ", f"تعذّر قراءة config.json:\n{e}")
            return

        opts = cfg.setdefault("ollama_options", {})
        for key, _label, _default, _h, type_ in _FIELDS:
            raw = self._fields[key].text().strip()
            try:
                if type_ is int:
                    opts[key] = int(raw)
                elif type_ is float:
                    opts[key] = float(raw)
                else:
                    opts[key] = raw
            except ValueError:
                QMessageBox.warning(
                    self, "قيمة غير صالحة",
                    f"قيمة «{raw}» للحقل «{key}» غير صالحة كـ {type_.__name__}"
                )
                return

        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "خطأ", f"تعذّر حفظ config.json:\n{e}")
            return

        self.saved.emit()
        self.status_message.emit("✓ حُفظت إعدادات Ollama (تحتاج إعادة تشغيل لتفعيل)")
        QMessageBox.information(
            self, "تم الحفظ",
            "حُفظت الإعدادات.\nأعد تشغيل التطبيق لتفعيلها."
        )

    # ── Resource monitoring ───────────────────────────────────────────────

    def _refresh_resources(self):
        # CPU + RAM via psutil
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            self._cpu_bar.update_value(cpu, f"{cpu:.0f}%")
            vm = psutil.virtual_memory()
            ram_pct = vm.percent
            used_gb  = vm.used  / (1024**3)
            total_gb = vm.total / (1024**3)
            self._ram_bar.update_value(ram_pct, f"{used_gb:.1f} / {total_gb:.1f} GB")
        except Exception:
            self._cpu_bar.update_value(0, "psutil غير متاح")
            self._ram_bar.update_value(0, "psutil غير متاح")

        # GPU + VRAM via nvidia-smi
        gpu_info = self._query_nvidia_smi()
        if gpu_info:
            name, mem_total, mem_used, util = gpu_info
            self._gpu_bar.update_value(util, f"{util:.0f}%")
            vram_pct = (mem_used / mem_total) * 100 if mem_total else 0
            self._vram_bar.update_value(
                vram_pct, f"{mem_used/1024:.1f} / {mem_total/1024:.1f} GB"
            )
            self._gpu_name_lbl.setText(f"  {name}")
        else:
            self._gpu_bar.update_value(0, "غير متوفر")
            self._vram_bar.update_value(0, "غير متوفر")
            self._gpu_name_lbl.setText("  (لم يُعثر على nvidia-smi)")

        # Ollama loaded models via /api/ps
        self._update_ollama_models()

    def _query_nvidia_smi(self) -> Optional[tuple[str, int, int, float]]:
        """يستعلم nvidia-smi: (name, mem_total_MiB, mem_used_MiB, gpu_util)."""
        try:
            result = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                return None
            line = result.stdout.strip().split("\n")[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                return (parts[0], int(parts[1]), int(parts[2]), float(parts[3]))
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError, OSError):
            pass
        return None

    def _update_ollama_models(self):
        try:
            import requests
            resp = requests.get("http://localhost:11434/api/ps", timeout=1.5)
            if resp.status_code != 200:
                self._ollama_models_lbl.setText("Ollama غير متاح على :11434")
                return
            data = resp.json()
            models = data.get("models", [])
            if not models:
                self._ollama_models_lbl.setText("(لا توجد مودلات مُحمّلة حالياً)")
                return
            lines = []
            for m in models:
                name = m.get("name", "?")
                size_bytes = m.get("size", 0)
                size_gb = size_bytes / (1024**3)
                expires = m.get("expires_at", "")
                expires_short = ""
                if expires:
                    # ISO date → جزء الوقت فقط
                    expires_short = f"  | حتى {expires[11:19]}"
                lines.append(f"  • {name:30s}  {size_gb:5.1f} GB{expires_short}")
            self._ollama_models_lbl.setText("\n".join(lines))
        except Exception:
            self._ollama_models_lbl.setText("(تعذّر الوصول لـ Ollama)")

    def closeEvent(self, ev):
        try:
            self._poll_timer.stop()
        except Exception:
            pass
        super().closeEvent(ev)


# ── أنماط الأزرار المشتركة ─────────────────────────────────────────────────
def _btn_primary_style(c: dict) -> str:
    return f"""
        QPushButton {{
            background: {c['accent']}; color: white;
            border: 1px solid {c['accent']}; border-radius: 4px;
            padding: 6px 18px; font-size: 11px; font-weight: bold;
        }}
        QPushButton:hover {{
            background: {c.get('teal', '#00d2ff')};
            border-color: {c.get('teal', '#00d2ff')};
        }}
    """

def _btn_secondary_style(c: dict) -> str:
    return f"""
        QPushButton {{
            background: {c['surface']}; color: {c['primary']};
            border: 1px solid {c['border']}; border-radius: 4px;
            padding: 6px 14px; font-size: 11px;
        }}
        QPushButton:hover {{
            background: {c['hover']}; color: white;
            border-color: {c['accent']};
        }}
    """
