"""
gui/qt/dialogs/admin_panel.py  —  لوحة الإدارة (المرحلة 8)
"""

from __future__ import annotations
import hashlib
import json
import os
import shutil
import sys

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QLineEdit, QTextEdit, QScrollArea, QTabWidget,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFileDialog, QMessageBox, QSizePolicy,
    QToolButton, QApplication,
)
from PySide6.QtCore  import Qt, Signal, QTimer
from PySide6.QtGui   import QCursor, QFont, QColor

from gui.qt.theme import theme


DEFAULT_PIN_HASH = hashlib.sha256(b"1234").hexdigest()

FEATURE_DEFS = [
    ("cache_section",   "💾  قسم الكاش"),
    ("translate",       "🌐  زر ترجمة اللعبة"),
    ("edit_config",     "✏️   زر تعديل الإعدادات"),
    ("locres_section",  "📄  قسم ملف Locres  (UE4)"),
    ("iostore_section", "📦  قسم IoStore / UAsset  (UE5)"),
]
_SHOWN_ONLY = {"locres_section", "iostore_section"}

_SCAN_EXTS = {".uasset", ".uexp", ".pak", ".utoc", ".ucas", ".locres", ".ttf", ".ufont"}


# ── PIN dialog ────────────────────────────────────────────────────────────────

class PINDialog(QDialog):
    """حوار إدخال PIN للوصول إلى لوحة الإدارة."""

    verified = Signal()

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("🔐  وصول الإدارة")
        self.setFixedSize(340, 200)
        self.setModal(True)
        self._build()

    def _build(self):
        c = theme.c
        self.setStyleSheet(f"""
            QDialog {{ background: {c['bg']}; }}
            QLabel  {{ color: {c['primary']}; background: transparent; border: none; }}
            QLineEdit {{
                background: {c['surface']}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 8px;
                padding: 8px 12px; font-size: 18px; letter-spacing: 6px;
                selection-background-color: {c['accent']};
            }}
            QLineEdit:focus {{ border-color: {c['accent']}; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        title = QLabel("🔐  لوحة الإدارة")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {c['accent']};"
        )
        root.addWidget(title)

        hint = QLabel("أدخل رمز PIN للمتابعة")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"font-size: 11px; color: {c['muted']};")
        root.addWidget(hint)

        self._pin_field = QLineEdit()
        self._pin_field.setEchoMode(QLineEdit.Password)
        self._pin_field.setAlignment(Qt.AlignCenter)
        self._pin_field.setPlaceholderText("••••")
        self._pin_field.returnPressed.connect(self._verify)
        root.addWidget(self._pin_field)

        self._err_lbl = QLabel("")
        self._err_lbl.setAlignment(Qt.AlignCenter)
        self._err_lbl.setStyleSheet(f"color: {c['accent']}; font-size: 10px;")
        root.addWidget(self._err_lbl)

        btn_row = QHBoxLayout()
        cancel = QPushButton("إلغاء")
        cancel.setCursor(QCursor(Qt.PointingHandCursor))
        cancel.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; color: {c['muted']};"
            f" border: 1px solid {c['border']}; border-radius: 8px; padding: 6px 18px; }}"
            f"QPushButton:hover {{ background: {c['hover']}; }}"
        )
        cancel.clicked.connect(self.reject)

        ok_btn = QPushButton("دخول ←")
        ok_btn.setCursor(QCursor(Qt.PointingHandCursor))
        ok_btn.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: #fff;"
            " border: none; border-radius: 8px; font-weight: bold; padding: 6px 18px; }"
        )
        ok_btn.clicked.connect(self._verify)

        btn_row.addWidget(cancel)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        root.addLayout(btn_row)

    def _verify(self):
        pin  = self._pin_field.text()
        h    = hashlib.sha256(pin.encode()).hexdigest()
        stored = self._config.get("admin", {}).get("pin_hash", DEFAULT_PIN_HASH)
        if h == stored:
            self.verified.emit()
            self.accept()
        else:
            self._err_lbl.setText("✗  رمز PIN غير صحيح")
            self._pin_field.clear()
            self._pin_field.setFocus()


# ── Admin panel ───────────────────────────────────────────────────────────────

class AdminPanel(QDialog):
    """لوحة الإدارة الكاملة."""

    def __init__(self, game_manager, cache, config: dict,
                 config_path: str = "", parent=None):
        super().__init__(parent)
        self._gm          = game_manager
        self._cache       = cache
        self._config      = config
        self._config_path = config_path
        self._selected_id: str | None = None

        self.setWindowTitle("⚙️  لوحة الإدارة")
        self.setMinimumSize(960, 640)
        self.setModal(True)
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        c = theme.c
        self.setStyleSheet(f"""
            QDialog   {{ background: {c['bg']}; }}
            QLabel    {{ color: {c['primary']}; background: transparent; border: none; }}
            QLineEdit, QTextEdit {{
                background: {c['surface']}; color: {c['primary']};
                border: 1px solid {c['border']}; border-radius: 6px;
                padding: 4px 8px;
                selection-background-color: {c['accent']};
            }}
            QLineEdit:focus, QTextEdit:focus {{ border-color: {c['accent']}; }}
            QCheckBox {{ color: {c['primary']}; background: transparent; }}
            QCheckBox::indicator {{
                width: 15px; height: 15px;
                border: 1px solid {c['border']}; border-radius: 3px;
                background: {c['surface']};
            }}
            QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
            QTabWidget::pane {{
                border: 1px solid {c['border']}; border-radius: 8px;
                background: {c['card']};
            }}
            QTabBar::tab {{
                background: {c['surface']}; color: {c['muted']};
                border: 1px solid {c['border']}; border-bottom: none;
                border-radius: 6px 6px 0 0;
                padding: 6px 16px; margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background: {c['card']}; color: {c['primary']}; font-weight: bold;
            }}
            QTabBar::tab:hover {{ color: {c['accent']}; }}
            QTableWidget {{
                background: {c['surface']}; color: {c['primary']};
                border: none; gridline-color: {c['border']};
                selection-background-color: {c['accent']};
            }}
            QHeaderView::section {{
                background: {c['card2']}; color: {c['muted']};
                border: none; border-bottom: 1px solid {c['border']};
                padding: 4px 8px; font-size: 10px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Title bar
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-bottom: 1px solid {c['border']}; }}"
        )
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(20, 12, 20, 12)
        title = QLabel("⚙️  لوحة الإدارة")
        title.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {c['accent']};"
        )
        bar_lay.addWidget(title)
        bar_lay.addStretch()
        root.addWidget(bar)

        # Main split
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Left: game list
        left = QFrame()
        left.setFixedWidth(220)
        left.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-right: 1px solid {c['border']}; }}"
        )
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)

        list_hdr = QFrame()
        list_hdr.setStyleSheet(
            f"QFrame {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; }}"
        )
        list_hdr_lay = QHBoxLayout(list_hdr)
        list_hdr_lay.setContentsMargins(12, 8, 12, 8)
        list_hdr_lbl = QLabel("الألعاب")
        list_hdr_lbl.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {c['muted']};"
        )
        list_hdr_lay.addWidget(list_hdr_lbl)
        left_lay.addWidget(list_hdr)

        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QFrame.NoFrame)
        self._list_scroll.setStyleSheet("background: transparent; border: none;")
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_lay = QVBoxLayout(self._list_widget)
        self._list_lay.setContentsMargins(6, 6, 6, 6)
        self._list_lay.setSpacing(2)
        self._list_lay.addStretch()
        self._list_scroll.setWidget(self._list_widget)
        left_lay.addWidget(self._list_scroll, 1)

        # System info button at bottom of left
        sysinfo_btn = QPushButton("🖥️  معلومات النظام")
        sysinfo_btn.setCursor(QCursor(Qt.PointingHandCursor))
        sysinfo_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {c['muted']};"
            f" border: none; border-top: 1px solid {c['border']};"
            f" padding: 8px; font-size: 10px; }}"
            f"QPushButton:hover {{ color: {c['accent']}; }}"
        )
        sysinfo_btn.clicked.connect(self._show_sysinfo)
        left_lay.addWidget(sysinfo_btn)

        # Right: content tabs
        right = QWidget()
        right.setStyleSheet(f"background: {c['bg']};")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(16, 16, 16, 16)
        right_lay.setSpacing(12)

        self._placeholder = QLabel("← اختر لعبة من القائمة")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet(f"color: {c['muted']}; font-size: 14px;")
        right_lay.addWidget(self._placeholder)

        self._tabs = QTabWidget()
        self._tabs.hide()
        right_lay.addWidget(self._tabs, 1)

        body.addWidget(left)
        body.addWidget(right, 1)
        root.addLayout(body, 1)

        # Bottom bar: PIN change + close
        bottom = QFrame()
        bottom.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border-top: 1px solid {c['border']}; }}"
        )
        bot_lay = QHBoxLayout(bottom)
        bot_lay.setContentsMargins(16, 10, 16, 10)
        bot_lay.setSpacing(10)

        pin_lbl = QLabel("تغيير PIN:")
        pin_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        self._new_pin = QLineEdit()
        self._new_pin.setEchoMode(QLineEdit.Password)
        self._new_pin.setFixedWidth(100)
        self._new_pin.setPlaceholderText("••••")
        self._new_pin.setAlignment(Qt.AlignCenter)
        save_pin_btn = QPushButton("حفظ PIN")
        save_pin_btn.setCursor(QCursor(Qt.PointingHandCursor))
        save_pin_btn.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; color: {c['secondary']};"
            f" border: 1px solid {c['border']}; border-radius: 6px; padding: 4px 12px; }}"
            f"QPushButton:hover {{ background: {c['hover']}; border-color: {c['accent']}; }}"
        )
        save_pin_btn.clicked.connect(self._save_pin)

        bot_lay.addWidget(pin_lbl)
        bot_lay.addWidget(self._new_pin)
        bot_lay.addWidget(save_pin_btn)
        bot_lay.addStretch()

        close_btn = QPushButton("إغلاق")
        close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        close_btn.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: #fff;"
            " border: none; border-radius: 8px; padding: 6px 20px; font-weight: bold; }"
        )
        close_btn.clicked.connect(self.accept)
        bot_lay.addWidget(close_btn)
        root.addWidget(bottom)

        self._right_lay = right_lay
        self._populate_game_list()

    # ── Game list ─────────────────────────────────────────────────────────────

    def _populate_game_list(self):
        c = theme.c
        while self._list_lay.count() > 1:
            item = self._list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._gm:
            return

        games = self._gm.get_game_list()
        self._game_btns: dict[str, QPushButton] = {}

        for game in games:
            gid = game["id"]
            btn = QPushButton(gid)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {c['primary']};
                    border: none; border-radius: 6px;
                    padding: 7px 10px; text-align: left; font-size: 12px;
                }}
                QPushButton:hover {{ background: {c['hover']}; }}
                QPushButton:checked {{
                    background: {c['hover']};
                    border-left: 3px solid {c['accent']};
                    color: {c['accent']}; font-weight: bold;
                }}
            """)
            btn.clicked.connect(lambda checked, g=gid: self._select_game(g))
            self._game_btns[gid] = btn
            self._list_lay.insertWidget(self._list_lay.count() - 1, btn)

    def _select_game(self, game_id: str):
        # Deselect others
        for gid, btn in self._game_btns.items():
            btn.setChecked(gid == game_id)

        self._selected_id = game_id
        self._placeholder.hide()
        self._tabs.show()
        self._build_tabs(game_id)

    # ── Tabs builder ──────────────────────────────────────────────────────────

    def _build_tabs(self, game_id: str):
        self._tabs.clear()
        cfg = self._gm.get_game(game_id) or {} if self._gm else {}

        self._tabs.addTab(self._build_features_tab(game_id, cfg),   "👁  الميزات")
        self._tabs.addTab(self._build_package_tab(game_id, cfg),    "📦  حزمة التعريب")
        self._tabs.addTab(self._build_config_tab(game_id, cfg),     "🗒  الإعدادات الخام")
        self._tabs.addTab(self._build_cache_tab(game_id, cfg),      "💾  الكاش")

    # ── Features tab ──────────────────────────────────────────────────────────

    def _build_features_tab(self, game_id: str, cfg: dict) -> QWidget:
        c   = theme.c
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        title = QLabel("تحكم في الأقسام والأزرار الظاهرة في صفحة اللعبة")
        title.setStyleSheet(f"color: {c['muted']}; font-size: 11px;")
        lay.addWidget(title)

        hidden      = set(cfg.get("hidden_features", []))
        shown_extra = set(cfg.get("shown_features",  []))
        gid_lower   = game_id.lower().replace(" ", "").replace("_", "")
        is_moe      = "myth" in gid_lower or "empires" in gid_lower or "moe" in gid_lower

        self._feat_checks: dict[str, QCheckBox] = {}
        for key, label in FEATURE_DEFS:
            if key in _SHOWN_ONLY:
                if key == "locres_section" and is_moe:
                    checked = key not in hidden
                else:
                    checked = key in shown_extra
            else:
                checked = key not in hidden

            cb = QCheckBox(label)
            cb.setChecked(checked)
            cb.setStyleSheet(f"color: {c['primary']}; font-size: 13px;")
            self._feat_checks[key] = cb
            lay.addWidget(cb)

        lay.addStretch()

        save_btn = QPushButton("💾  حفظ الميزات")
        save_btn.setFixedHeight(36)
        save_btn.setCursor(QCursor(Qt.PointingHandCursor))
        save_btn.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: #fff;"
            " border: none; border-radius: 8px; font-weight: bold; padding: 0 20px; }"
        )
        save_btn.clicked.connect(
            lambda gid=game_id, moe=is_moe: self._save_features(gid, moe)
        )
        lay.addWidget(save_btn)
        return w

    def _save_features(self, game_id: str, is_moe: bool):
        new_hidden = []
        new_shown  = []
        for key, cb in self._feat_checks.items():
            checked = cb.isChecked()
            if key in _SHOWN_ONLY:
                if key == "locres_section":
                    if is_moe:
                        if not checked:
                            new_hidden.append(key)
                    else:
                        if checked:
                            new_shown.append(key)
                else:
                    if checked:
                        new_shown.append(key)
            else:
                if not checked:
                    new_hidden.append(key)

        if self._gm:
            self._gm.update_game(game_id, {
                "hidden_features": new_hidden,
                "shown_features":  new_shown,
            })
        QMessageBox.information(self, "✓", "تم حفظ إعدادات الميزات")

    # ── Translation Package tab ───────────────────────────────────────────────

    def _build_package_tab(self, game_id: str, cfg: dict) -> QWidget:
        c   = theme.c
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        try:
            from games.translation_package import TranslationPackage
            pkg = TranslationPackage()
        except ImportError:
            lay.addWidget(QLabel("✗  TranslationPackage غير متاح"))
            return w

        mod_dir = pkg.get_mod_dir(game_id)
        path_lbl = QLabel(f"مجلد الحزمة:  {mod_dir}")
        path_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        lay.addWidget(path_lbl)

        # Files table
        self._pkg_table = QTableWidget(0, 4)
        self._pkg_table.setHorizontalHeaderLabels(["الملف", "المسار الهدف", ".orig", ""])
        self._pkg_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._pkg_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._pkg_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._pkg_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._pkg_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._pkg_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._pkg_table.verticalHeader().hide()
        lay.addWidget(self._pkg_table, 1)

        def _refresh():
            self._pkg_table.setRowCount(0)
            pkg_cfg = pkg.get_config(game_id)
            for entry in pkg_cfg.get("files", []):
                r = self._pkg_table.rowCount()
                self._pkg_table.insertRow(r)
                self._pkg_table.setItem(r, 0, QTableWidgetItem(entry.get("name", "")))
                self._pkg_table.setItem(r, 1, QTableWidgetItem(entry.get("game_target", "")))
                orig_mark = "✓" if entry.get("has_orig") else "✗"
                orig_item = QTableWidgetItem(orig_mark)
                orig_item.setForeground(
                    QColor(c["green"] if entry.get("has_orig") else c["accent"])
                )
                orig_item.setTextAlignment(Qt.AlignCenter)
                self._pkg_table.setItem(r, 2, orig_item)

                del_btn = QToolButton()
                del_btn.setText("✕")
                del_btn.setStyleSheet(
                    f"QToolButton {{ background: transparent; color: {c['accent']};"
                    " border: none; font-weight: bold; }"
                    f"QToolButton:hover {{ color: #fff; background: {c['accent']};"
                    " border-radius: 3px; }}"
                )
                del_btn.clicked.connect(
                    lambda _, gt=entry["game_target"]: (
                        pkg.remove_file(game_id, gt), _refresh()
                    )
                )
                self._pkg_table.setCellWidget(r, 3, del_btn)

        _refresh()

        # Buttons row
        btn_row = QHBoxLayout()

        def _add_files():
            paths, _ = QFileDialog.getOpenFileNames(
                self, "اختر ملفات التعريب", "",
                "Game Files (*.uasset *.uexp *.pak *.utoc *.ucas *.locres *.ttf *.ufont);;All (*.*)"
            )
            game_path = cfg.get("game_path", "")
            for fp in paths:
                if not os.path.isfile(fp):
                    continue
                orig_p = fp + ".orig" if os.path.exists(fp + ".orig") else ""
                try:
                    rel = os.path.relpath(fp, game_path).replace("\\", "/")
                except ValueError:
                    rel = os.path.basename(fp)
                pkg.add_file(game_id, fp, orig_p, rel)
            _refresh()

        def _scan_folder():
            folder = QFileDialog.getExistingDirectory(self, "اختر مجلد المصدر", "")
            if not folder:
                return
            game_path = cfg.get("game_path", "")
            found = []
            for root_d, _, files in os.walk(folder):
                for f in files:
                    if os.path.splitext(f)[1].lower() in _SCAN_EXTS:
                        found.append(os.path.join(root_d, f))
            for fp in found:
                orig_p = fp + ".orig" if os.path.exists(fp + ".orig") else ""
                try:
                    rel = os.path.relpath(fp, folder).replace("\\", "/")
                except ValueError:
                    rel = os.path.basename(fp)
                pkg.add_file(game_id, fp, orig_p, rel)
            _refresh()
            QMessageBox.information(self, "✓", f"تمت إضافة {len(found)} ملف")

        def _open_ready():
            ready = pkg.get_ready_dir(game_id)
            os.makedirs(ready, exist_ok=True)
            os.startfile(ready)

        for label, color, slot in [
            ("📄  إضافة ملفات",  "accent", _add_files),
            ("📁  مسح مجلد",    "blue",   _scan_folder),
            ("📂  فتح ready/",  "teal",   _open_ready),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(32)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            clr = theme.c.get(color, theme.c["accent"])
            btn.setStyleSheet(
                f"QPushButton {{ background: rgba(0,0,0,0.1); color: {clr};"
                f" border: 1px solid {clr}; border-radius: 7px; padding: 0 12px; }}"
                f"QPushButton:hover {{ background: {clr}; color: #fff; }}"
            )
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)

        btn_row.addStretch()
        lay.addLayout(btn_row)
        return w

    # ── Raw config tab ────────────────────────────────────────────────────────

    def _build_config_tab(self, game_id: str, cfg: dict) -> QWidget:
        c   = theme.c
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        hint = QLabel("تحرير مباشر لملف إعدادات اللعبة JSON — تأكد من صحة الصياغة قبل الحفظ")
        hint.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
        lay.addWidget(hint)

        editor = QTextEdit()
        editor.setFont(QFont("Consolas", 10))
        editor.setPlainText(json.dumps(cfg, indent=2, ensure_ascii=False))
        lay.addWidget(editor, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        save_btn = QPushButton("💾  حفظ الإعدادات")
        save_btn.setFixedHeight(34)
        save_btn.setCursor(QCursor(Qt.PointingHandCursor))
        save_btn.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: #fff;"
            " border: none; border-radius: 8px; font-weight: bold; padding: 0 18px; }"
        )

        def _save():
            try:
                new_cfg = json.loads(editor.toPlainText())
            except json.JSONDecodeError as e:
                QMessageBox.critical(self, "خطأ", f"JSON غير صالح:\n{e}")
                return
            if self._gm:
                self._gm.update_game(game_id, new_cfg)
            QMessageBox.information(self, "✓", "تم حفظ الإعدادات")

        save_btn.clicked.connect(_save)
        btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)
        return w

    # ── Cache tab ─────────────────────────────────────────────────────────────

    def _build_cache_tab(self, game_id: str, cfg: dict) -> QWidget:
        c    = theme.c
        w    = QWidget()
        lay  = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(14)

        game_name = cfg.get("name", game_id)

        stats_card = QFrame()
        stats_card.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']};"
            " border-radius: 8px; }}"
        )
        sc_lay = QVBoxLayout(stats_card)
        sc_lay.setContentsMargins(16, 12, 16, 12)
        sc_lay.setSpacing(8)

        self._cache_stats_lbl = QLabel("جاري التحميل…")
        self._cache_stats_lbl.setStyleSheet(f"color: {c['secondary']}; font-size: 12px;")
        sc_lay.addWidget(self._cache_stats_lbl)
        lay.addWidget(stats_card)

        def _refresh_stats():
            if not self._cache:
                self._cache_stats_lbl.setText("لا يوجد كاش متاح")
                return
            try:
                count = self._cache.count_entries(game_name)
                stats = self._cache.get_stats(game_name) if hasattr(self._cache, "get_stats") else {}
                lines = [
                    f"إجمالي الترجمات:  {count:,}",
                    f"إجمالي الطلبات:   {stats.get('cache_hits', 0):,}",
                    f"الفاشلة:          {stats.get('failed_count', 0):,}",
                ]
                self._cache_stats_lbl.setText("\n".join(lines))
            except Exception as e:
                self._cache_stats_lbl.setText(f"خطأ: {e}")

        _refresh_stats()

        btn_row = QHBoxLayout()

        def _vacuum():
            reply = QMessageBox.question(
                self, "تأكيد",
                f"حذف كل ترجمات:\n«{game_name}»\nهذا الإجراء لا يمكن التراجع عنه.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes and self._cache:
                try:
                    self._cache.delete_game(game_name)
                    _refresh_stats()
                    QMessageBox.information(self, "✓", "تم مسح كاش اللعبة")
                except Exception as e:
                    QMessageBox.critical(self, "خطأ", str(e))

        del_btn = QPushButton("🗑️  مسح كاش هذه اللعبة")
        del_btn.setFixedHeight(34)
        del_btn.setCursor(QCursor(Qt.PointingHandCursor))
        del_btn.setStyleSheet(
            f"QPushButton {{ background: rgba(0,0,0,0.1); color: {c['accent']};"
            f" border: 1px solid {c['accent']}; border-radius: 8px; padding: 0 16px; }}"
            f"QPushButton:hover {{ background: {c['accent']}; color: #fff; }}"
        )
        del_btn.clicked.connect(_vacuum)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        lay.addStretch()
        return w

    # ── System info ───────────────────────────────────────────────────────────

    def _show_sysinfo(self):
        c = theme.c
        try:
            from PySide6 import __version__ as pyside_ver
        except Exception:
            pyside_ver = "?"
        try:
            import sqlite3
            sqlite_ver = sqlite3.sqlite_version
        except Exception:
            sqlite_ver = "?"

        lines = [
            f"Python:      {sys.version.split()[0]}",
            f"PySide6:     {pyside_ver}",
            f"SQLite:      {sqlite_ver}",
            f"Platform:    {sys.platform}",
            f"",
            f"Project:     {os.path.dirname(self._config_path) if self._config_path else '—'}",
        ]

        if self._cache:
            try:
                db_path = getattr(self._cache, "_db_path", None) or getattr(self._cache, "db_path", None)
                if db_path and os.path.exists(db_path):
                    size_mb = os.path.getsize(db_path) / 1_048_576
                    lines.append(f"Cache DB:    {db_path}")
                    lines.append(f"Cache size:  {size_mb:.2f} MB")
            except Exception:
                pass

        dlg = QDialog(self)
        dlg.setWindowTitle("🖥️  معلومات النظام")
        dlg.setFixedSize(460, 300)
        dlg.setStyleSheet(f"QDialog {{ background: {c['bg']}; }}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 16, 20, 16)

        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setFont(QFont("Consolas", 10))
        txt.setStyleSheet(
            f"background: {c['surface']}; color: {c['secondary']};"
            f" border: 1px solid {c['border']}; border-radius: 6px; padding: 8px;"
        )
        txt.setPlainText("\n".join(lines))
        lay.addWidget(txt)

        copy_btn = QPushButton("📋  نسخ")
        copy_btn.setCursor(QCursor(Qt.PointingHandCursor))
        copy_btn.setStyleSheet(
            f"QPushButton {{ background: {c['surface']}; color: {c['muted']};"
            f" border: 1px solid {c['border']}; border-radius: 6px; padding: 4px 14px; }}"
            f"QPushButton:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}"
        )
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(txt.toPlainText())
        )
        ok = QPushButton("موافق")
        ok.setCursor(QCursor(Qt.PointingHandCursor))
        ok.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: #fff;"
            " border: none; border-radius: 6px; padding: 4px 18px; font-weight: bold; }"
        )
        ok.clicked.connect(dlg.accept)
        br = QHBoxLayout()
        br.addWidget(copy_btn)
        br.addStretch()
        br.addWidget(ok)
        lay.addLayout(br)
        dlg.exec()

    # ── PIN save ──────────────────────────────────────────────────────────────

    def _save_pin(self):
        pin = self._new_pin.text().strip()
        if len(pin) < 4:
            QMessageBox.warning(self, "تنبيه", "يجب أن يكون PIN على الأقل 4 أرقام")
            return
        h = hashlib.sha256(pin.encode()).hexdigest()
        self._config.setdefault("admin", {})["pin_hash"] = h
        if self._config_path:
            try:
                with open(self._config_path, "w", encoding="utf-8") as f:
                    json.dump(self._config, f, indent=2, ensure_ascii=False)
            except Exception as e:
                QMessageBox.critical(self, "خطأ", f"فشل الحفظ: {e}")
                return
        self._new_pin.clear()
        QMessageBox.information(self, "✓", "تم حفظ PIN الجديد")


# ── Public launcher ───────────────────────────────────────────────────────────

def open_admin(game_manager, cache, config: dict, config_path: str, parent=None):
    """يعرض حوار PIN أولاً ثم لوحة الإدارة عند التحقق."""
    pin_dlg = PINDialog(config, parent=parent)
    result  = [False]

    def _on_verified():
        result[0] = True

    pin_dlg.verified.connect(_on_verified)
    pin_dlg.exec()

    if result[0]:
        admin = AdminPanel(game_manager, cache, config, config_path, parent=parent)
        admin.exec()
