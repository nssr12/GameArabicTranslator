import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import json
import os
import re
import sys
import threading
import time
from typing import Optional
from gui.theme import ThemeManager


AVAILABLE_FONTS = ["Segoe UI", "Arial", "Tahoma", "Calibri", "Consolas", "Courier New", "Verdana", "Times New Roman"]


class AppColors:
    _colors = {}
    
    @classmethod
    def update(cls, colors: dict):
        cls._colors = colors
        for k, v in colors.items():
            setattr(cls, k, v)
    
    def __getattr__(self, name):
        if name in self._colors:
            return self._colors[name]
        return "#000000"


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, bg_color="#1a1a2e", **kwargs):
        super().__init__(parent, **kwargs)

        self.canvas = tk.Canvas(self, bg=bg_color, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg_color)

        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)
        self.inner.bind("<Enter>", self._bind_mousewheel)
        self.inner.bind("<Leave>", self._unbind_mousewheel)

    def _bind_mousewheel(self, event):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))

    def _unbind_mousewheel(self, event):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class MainWindow:
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Game Arabic Translator v1.0")
        self.root.geometry("1200x750")
        self.root.minsize(900, 600)
        
        def _copy(e):
            w = e.widget
            try:
                if isinstance(w, tk.Text):
                    text = w.get(tk.SEL_FIRST, tk.SEL_LAST)
                else:
                    s, end = w.index(tk.SEL_FIRST), w.index(tk.SEL_LAST)
                    text = w.get()[s:end]
                w.clipboard_clear()
                w.clipboard_append(text)
                return "break"
            except Exception:
                return  # no selection — let native handler proceed

        def _cut(e):
            w = e.widget
            try:
                if isinstance(w, tk.Text):
                    text = w.get(tk.SEL_FIRST, tk.SEL_LAST)
                    w.clipboard_clear()
                    w.clipboard_append(text)
                    w.delete(tk.SEL_FIRST, tk.SEL_LAST)
                else:
                    s, end = w.index(tk.SEL_FIRST), w.index(tk.SEL_LAST)
                    text = w.get()[s:end]
                    w.clipboard_clear()
                    w.clipboard_append(text)
                    w.delete(tk.SEL_FIRST, tk.SEL_LAST)
                return "break"
            except Exception:
                return

        def _paste(e):
            w = e.widget
            try:
                text = w.clipboard_get()
            except Exception:
                return
            try:
                w.delete(tk.SEL_FIRST, tk.SEL_LAST)
            except Exception:
                pass
            w.insert(tk.INSERT, text)
            return "break"

        def _select_all_entry(e):
            e.widget.select_range(0, tk.END)
            e.widget.icursor(tk.END)
            return "break"

        def _select_all_text(e):
            e.widget.tag_add("sel", "1.0", "end")
            return "break"

        for cls in ("Entry", "TEntry", "TCombobox"):
            self.root.bind_class(cls, "<Control-c>", _copy)
            self.root.bind_class(cls, "<Control-v>", _paste)
            self.root.bind_class(cls, "<Control-x>", _cut)
            self.root.bind_class(cls, "<Control-a>", _select_all_entry)

        self.root.bind_class("Text", "<Control-c>", _copy)
        self.root.bind_class("Text", "<Control-v>", _paste)
        self.root.bind_class("Text", "<Control-x>", _cut)
        self.root.bind_class("Text", "<Control-a>", _select_all_text)

        self.root.bind_class("Entry",    "<Button-3>", self._show_context_menu)
        self.root.bind_class("TEntry",   "<Button-3>", self._show_context_menu)
        self.root.bind_class("Text",     "<Button-3>", self._show_context_menu)
        self.root.bind_class("TCombobox","<Button-3>", self._show_context_menu)
        
        self._theme = ThemeManager(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
        self._C = self._theme.get_colors()
        
        self._config = self._load_config()
        self._translation_engine = None
        self._cache = None
        self._game_manager = None
        self._frida_manager = None
        self._current_attached_game = None
        self._ror2_translator = None
        self._game_images = {}
        self._translation_running = False
        self._system_prompt = self._config.get("system_prompt") or self._default_system_prompt()
        
        self.root.configure(bg=self._C["BG_DARK"])
        AppColors.update(self._C)
        self._build_ui()
        self._init_backend()
    
    def _load_config(self) -> dict:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}

    def _save_config(self):
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._set_status(f"Config save error: {e}")

    # ------------------------------------------------------------------
    # Admin Panel (secret: click v1.0 label 5 times rapidly)
    # ------------------------------------------------------------------

    def _handle_admin_click(self, event):
        self._admin_click_count += 1
        if self._admin_click_timer:
            self.root.after_cancel(self._admin_click_timer)
        if self._admin_click_count >= 5:
            self._admin_click_count = 0
            self._show_admin_pin_dialog()
        else:
            self._admin_click_timer = self.root.after(1500, self._reset_admin_clicks)

    def _reset_admin_clicks(self):
        self._admin_click_count = 0

    def _show_admin_pin_dialog(self):
        import hashlib as _hl
        dialog = tk.Toplevel(self.root)
        dialog.title("")
        dialog.geometry("300x180")
        dialog.resizable(False, False)
        dialog.configure(bg=AppColors.BG_DARK)
        dialog.transient(self.root)
        dialog.grab_set()
        x = self.root.winfo_x() + (self.root.winfo_width() - 300) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 180) // 2
        dialog.geometry(f"+{x}+{y}")

        tk.Label(dialog, text="🔐 Admin Access", font=self._theme.get_header_font(),
                 bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(pady=(20, 5))
        tk.Label(dialog, text="Enter PIN:", font=self._theme.get_font(),
                 bg=AppColors.BG_DARK, fg=AppColors.TEXT_SECONDARY).pack()

        pin_var = tk.StringVar()
        pin_entry = tk.Entry(dialog, textvariable=pin_var, show="●", font=self._theme.get_font(),
                             bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY,
                             insertbackground=AppColors.TEXT_PRIMARY, relief="flat",
                             width=12, justify="center")
        pin_entry.pack(pady=8, ipady=5)
        pin_entry.focus()

        err_lbl = tk.Label(dialog, text="", font=self._theme.get_small_font(),
                           bg=AppColors.BG_DARK, fg=AppColors.ERROR)
        err_lbl.pack()

        def verify(event=None):
            stored_hash = self._config.get("admin", {}).get("pin_hash",
                _hl.sha256(b"1234").hexdigest())
            entered_hash = _hl.sha256(pin_var.get().encode()).hexdigest()
            if entered_hash == stored_hash:
                dialog.destroy()
                self._open_admin_window()
            else:
                err_lbl.configure(text="PIN incorrect")
                pin_var.set("")

        pin_entry.bind("<Return>", verify)
        tk.Button(dialog, text="Enter", font=self._theme.get_font(style="bold"),
                  bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY, relief="flat",
                  padx=20, pady=4, command=verify).pack(pady=(0, 10))

    def _open_admin_window(self):
        win = tk.Toplevel(self.root)
        win.title("Admin Panel")
        win.geometry("820x560")
        win.minsize(700, 480)
        win.configure(bg=AppColors.BG_DARK)
        win.transient(self.root)
        x = self.root.winfo_x() + (self.root.winfo_width() - 820) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 560) // 2
        win.geometry(f"+{x}+{y}")

        tk.Label(win, text="⚙️  Admin Panel", font=self._theme.get_title_font(),
                 bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", padx=20, pady=(15, 5))
        tk.Frame(win, bg=AppColors.BORDER, height=1).pack(fill="x", padx=20, pady=(0, 10))

        body = tk.Frame(win, bg=AppColors.BG_DARK)
        body.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        # Left: game list
        left = tk.Frame(body, bg=AppColors.BG_CARD, width=200)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        tk.Label(left, text="Games", font=self._theme.get_font(style="bold"),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY).pack(anchor="w", padx=10, pady=(10, 5))

        games_list_frame = ScrollableFrame(left, bg_color=AppColors.BG_CARD)
        games_list_frame.pack(fill="both", expand=True)

        # Right: settings panel
        right = tk.Frame(body, bg=AppColors.BG_DARK)
        right.pack(side="left", fill="both", expand=True)

        right_scroll = ScrollableFrame(right, bg_color=AppColors.BG_DARK)
        right_scroll.pack(fill="both", expand=True)
        settings_panel = right_scroll.inner

        placeholder = tk.Label(settings_panel, text="← Select a game", font=self._theme.get_font(),
                               bg=AppColors.BG_DARK, fg=AppColors.TEXT_MUTED)
        placeholder.pack(pady=40)

        selected_game = [None]

        def load_game_settings(game_id):
            selected_game[0] = game_id
            for w in settings_panel.winfo_children():
                w.destroy()
            game_cfg = self._game_manager.get_game(game_id) if self._game_manager else None
            if not game_cfg:
                return

            hidden = set(game_cfg.get("hidden_features", []))
            shown_extra = set(game_cfg.get("shown_features", []))
            gid_lower = game_id.lower().replace(" ", "").replace("_", "")
            is_moe_game = "myth" in gid_lower or "empires" in gid_lower or "moe" in gid_lower

            tk.Label(settings_panel, text=game_id, font=self._theme.get_header_font(),
                     bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 10))

            # ── Image ──────────────────────────────────────────────
            img_card = tk.Frame(settings_panel, bg=AppColors.BG_CARD, padx=15, pady=12)
            img_card.pack(fill="x", pady=(0, 8))
            tk.Label(img_card, text="🖼  Game Image", font=self._theme.get_font(style="bold"),
                     bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 6))

            img_path_var = tk.StringVar(value=game_cfg.get("image_path", "No image"))
            tk.Label(img_card, textvariable=img_path_var, font=self._theme.get_small_font(),
                     bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED, anchor="w").pack(fill="x")

            def browse_image(gid=game_id, var=img_path_var):
                path = filedialog.askopenfilename(
                    title="Select Game Image",
                    filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"), ("All", "*.*")]
                )
                if path and self._game_manager:
                    self._game_manager.update_game(gid, {"image_path": path})
                    var.set(path)
                    self._load_game_image(gid, path)
                    self._set_status(f"Image updated for {gid}")

            tk.Button(img_card, text="📂 Browse Image", font=self._theme.get_font(),
                      bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY, relief="flat",
                      padx=12, pady=3, cursor="hand2", command=browse_image).pack(anchor="w", pady=(6, 0))

            # ── Visible Features ───────────────────────────────────
            feat_card = tk.Frame(settings_panel, bg=AppColors.BG_CARD, padx=15, pady=12)
            feat_card.pack(fill="x", pady=(0, 8))
            tk.Label(feat_card, text="👁  Visible Features on Game Page",
                     font=self._theme.get_font(style="bold"),
                     bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 8))

            feature_defs = [
                ("cache_section",  "💾 Translation Cache section"),
                ("mod_section",    "🔧 Mod Status section"),
                ("translate",      "🌐 Translate Game button"),
                ("attach",         "🔗 Attach to Game button"),
                ("server",         "🖥️  Start Server button"),
                ("sync_from",      "📥 Sync from Game button"),
                ("sync_to",        "📤 Sync to Game button"),
                ("edit_config",    "✏️  Edit Config button"),
                ("locres_section",   "📄 Locres File section (UE4)"),
                ("iostore_section",  "📦 IoStore / UAsset section (UE5)"),
            ]

            # Features that are OFF by default for ALL games (controlled via shown_features)
            _shown_only_features = {"locres_section", "iostore_section"}

            feat_vars = {}
            for key, label in feature_defs:
                if key in _shown_only_features:
                    # locres: MoE = default ON; others OFF
                    # iostore: always OFF by default
                    if key == "locres_section" and is_moe_game:
                        default_val = key not in hidden
                    else:
                        default_val = key in shown_extra
                else:
                    default_val = key not in hidden
                var = tk.BooleanVar(value=default_val)
                feat_vars[key] = var
                cb = tk.Checkbutton(feat_card, text=label, variable=var,
                                    font=self._theme.get_font(),
                                    bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY,
                                    selectcolor=AppColors.BG_LIGHT,
                                    activebackground=AppColors.BG_CARD,
                                    activeforeground=AppColors.TEXT_PRIMARY,
                                    anchor="w")
                cb.pack(fill="x", pady=1)

            def save_features(gid=game_id, fvars=feat_vars, moe=is_moe_game):
                new_hidden = [k for k, v in fvars.items()
                              if not v.get() and k not in ("locres_section", "iostore_section")]
                new_shown = []

                # locres: MoE = hidden_features, non-MoE = shown_features
                locres_checked = fvars["locres_section"].get()
                if moe:
                    if not locres_checked:
                        new_hidden.append("locres_section")
                else:
                    if locres_checked:
                        new_shown.append("locres_section")

                # iostore: always shown_features (OFF by default for all games)
                if fvars["iostore_section"].get():
                    new_shown.append("iostore_section")

                if self._game_manager:
                    self._game_manager.update_game(gid, {
                        "hidden_features": new_hidden,
                        "shown_features": new_shown,
                    })
                    self._set_status(f"Features saved for {gid}")

            tk.Button(feat_card, text="💾 Save Features", font=self._theme.get_font(style="bold"),
                      bg=AppColors.SUCCESS, fg="black", relief="flat",
                      padx=14, pady=4, cursor="hand2", command=save_features).pack(anchor="w", pady=(10, 0))

            # ── Translation Package (Mod Files) ────────────────────
            from games.translation_package import TranslationPackage
            pkg = TranslationPackage()
            game_cfg_now = self._game_manager.get_game(game_id) if self._game_manager else {}
            game_path_now = game_cfg_now.get("game_path", "")

            mod_card = tk.Frame(settings_panel, bg=AppColors.BG_CARD, padx=15, pady=12)
            mod_card.pack(fill="x", pady=(0, 8))
            tk.Label(mod_card, text="📂  Translation Package",
                     font=self._theme.get_font(style="bold"),
                     bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 2))

            mod_dir_str = pkg.get_mod_dir(game_id)
            tk.Label(mod_card,
                     text=f"Folder: {mod_dir_str}",
                     font=self._theme.get_small_font(),
                     bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED, anchor="w").pack(fill="x")

            tk.Frame(mod_card, bg=AppColors.BORDER, height=1).pack(fill="x", pady=(6, 6))

            files_frame = tk.Frame(mod_card, bg=AppColors.BG_CARD)
            files_frame.pack(fill="x")

            def _refresh_pkg_table(container=files_frame, gid=game_id, p=pkg):
                for w in container.winfo_children():
                    w.destroy()
                cfg = p.get_config(gid)
                if not cfg["files"]:
                    tk.Label(container, text="No files configured yet.",
                             font=self._theme.get_small_font(),
                             bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED).pack(anchor="w", pady=4)
                    return
                hdr = tk.Frame(container, bg=AppColors.BG_LIGHT)
                hdr.pack(fill="x", pady=(0, 2))
                for col, w in [("File", 18), ("Game Target Path", 36), (".orig", 5)]:
                    tk.Label(hdr, text=col, font=self._theme.get_small_font(),
                             bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_SECONDARY,
                             width=w, anchor="w").pack(side="left", padx=3)
                for entry in cfg["files"]:
                    row = tk.Frame(container, bg=AppColors.BG_CARD)
                    row.pack(fill="x", pady=1)
                    tk.Label(row, text=entry["name"], font=self._theme.get_small_font(),
                             bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY,
                             width=18, anchor="w").pack(side="left", padx=3)
                    tk.Label(row, text=entry.get("game_target", ""), font=self._theme.get_small_font(),
                             bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED,
                             width=36, anchor="w").pack(side="left", padx=3)
                    tk.Label(row,
                             text="✓" if entry.get("has_orig") else "✗",
                             font=self._theme.get_small_font(),
                             bg=AppColors.BG_CARD,
                             fg=AppColors.SUCCESS if entry.get("has_orig") else AppColors.ERROR,
                             width=5, anchor="w").pack(side="left", padx=3)
                    tk.Button(row, text="✕", font=self._theme.get_small_font(),
                              bg=AppColors.ERROR, fg="white", relief="flat",
                              padx=6, pady=0, cursor="hand2",
                              command=lambda gt=entry["game_target"]: (
                                  p.remove_file(gid, gt),
                                  _refresh_pkg_table()
                              )).pack(side="left", padx=4)

            _refresh_pkg_table()

            def _add_mod_file(gid=game_id, gpath=game_path_now, p=pkg):
                dlg = tk.Toplevel(win)
                dlg.title("Add Translation Files")
                dlg.geometry("700x520")
                dlg.minsize(600, 420)
                dlg.configure(bg=AppColors.BG_DARK)
                dlg.transient(win)
                dlg.grab_set()

                # pending = list of [mod_path, orig_path_or_"", target_rel]
                pending = []

                # ── helpers ───────────────────────────────────────────
                def _auto_target(file_path, src_root_var):
                    """Compute relative target path."""
                    root = src_root_var.get().strip()
                    # prefer explicit source root
                    if root and os.path.isdir(root):
                        try:
                            return os.path.relpath(file_path, root).replace("\\", "/")
                        except ValueError:
                            pass
                    # fallback: game_path
                    if gpath:
                        try:
                            return os.path.relpath(file_path, gpath).replace("\\", "/")
                        except ValueError:
                            pass
                    return os.path.basename(file_path)

                def _find_orig(file_path, orig_folder_var):
                    """Find .orig beside the file or in orig_folder."""
                    beside = file_path + ".orig"
                    if os.path.exists(beside):
                        return beside
                    ofolder = orig_folder_var.get().strip()
                    if ofolder and os.path.isdir(ofolder):
                        candidate = os.path.join(ofolder, os.path.basename(file_path) + ".orig")
                        if os.path.exists(candidate):
                            return candidate
                        candidate2 = os.path.join(ofolder, os.path.basename(file_path))
                        if os.path.exists(candidate2):
                            return candidate2
                    return ""

                # ── top controls ──────────────────────────────────────
                top = tk.Frame(dlg, bg=AppColors.BG_DARK, padx=12, pady=8)
                top.pack(fill="x")

                src_root_var   = tk.StringVar()
                orig_folder_var = tk.StringVar()

                for row_idx, (lbl_text, var, btn_title, is_dir) in enumerate([
                    ("Source root (مجلد المصدر):", src_root_var,    "Browse", True),
                    ("Orig folder (.orig files):", orig_folder_var, "Browse", True),
                ]):
                    tk.Label(top, text=lbl_text, font=self._theme.get_small_font(),
                             bg=AppColors.BG_DARK, fg=AppColors.TEXT_SECONDARY,
                             width=24, anchor="e").grid(row=row_idx, column=0, padx=(0,6), pady=3)
                    tk.Entry(top, textvariable=var, font=self._theme.get_small_font(),
                             bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY,
                             insertbackground=AppColors.TEXT_PRIMARY,
                             relief="flat", width=44).grid(row=row_idx, column=1, pady=3)
                    def _browse_dir(v=var):
                        d = filedialog.askdirectory(parent=dlg, title="Select Folder")
                        if d:
                            v.set(d)
                    tk.Button(top, text=btn_title, font=self._theme.get_small_font(),
                              bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY,
                              relief="flat", padx=8, cursor="hand2",
                              command=_browse_dir).grid(row=row_idx, column=2, padx=6, pady=3)

                tk.Label(top,
                         text="Source root: مجلد الملفات المترجمة لحساب المسار النسبي تلقائياً.\n"
                              "Orig folder: اختياري — مجلد الملفات الأصلية (.orig) للإلغاء.",
                         font=self._theme.get_small_font(),
                         bg=AppColors.BG_DARK, fg=AppColors.TEXT_MUTED,
                         justify="left").grid(row=2, column=0, columnspan=3, sticky="w", padx=4, pady=(0,4))

                # ── file list (treeview) ───────────────────────────────
                tk.Frame(dlg, bg=AppColors.BORDER, height=1).pack(fill="x")
                list_frame = tk.Frame(dlg, bg=AppColors.BG_DARK)
                list_frame.pack(fill="both", expand=True, padx=12, pady=6)

                cols = ("file", "target", "orig")
                tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=10)
                tree.heading("file",   text="File")
                tree.heading("target", text="Game Target Path")
                tree.heading("orig",   text=".orig")
                tree.column("file",   width=180, stretch=False)
                tree.column("target", width=340)
                tree.column("orig",   width=60, anchor="center", stretch=False)
                vsb = ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
                tree.configure(yscrollcommand=vsb.set)
                tree.pack(side="left", fill="both", expand=True)
                vsb.pack(side="right", fill="y")

                count_var = tk.StringVar(value="0 files selected")

                def _refresh_tree():
                    tree.delete(*tree.get_children())
                    for mod_p, orig_p, tgt in pending:
                        tree.insert("", "end", values=(
                            os.path.basename(mod_p),
                            tgt,
                            "✓" if orig_p else "✗"
                        ))
                    count_var.set(f"{len(pending)} file(s) selected")

                def _add_files_to_pending(paths):
                    for fp in paths:
                        if not os.path.isfile(fp):
                            continue
                        tgt  = _auto_target(fp, src_root_var)
                        orig = _find_orig(fp, orig_folder_var)
                        # avoid duplicates
                        if not any(e[0] == fp for e in pending):
                            pending.append([fp, orig, tgt])
                    _refresh_tree()

                def _browse_files():
                    paths = filedialog.askopenfilenames(
                        parent=dlg,
                        title="Select translated files",
                        filetypes=[
                            ("Game files", "*.uasset *.uexp *.pak *.utoc *.ucas *.locres *.ttf *.ufont"),
                            ("All files", "*.*"),
                        ])
                    if paths:
                        _add_files_to_pending(list(paths))

                _SCAN_EXTS = {".uasset", ".uexp", ".pak", ".utoc", ".ucas", ".locres", ".ttf", ".ufont"}

                def _browse_folder():
                    folder = filedialog.askdirectory(parent=dlg, title="Select folder to scan")
                    if not folder:
                        return
                    found = []
                    for root_d, _, files in os.walk(folder):
                        for f in files:
                            if os.path.splitext(f)[1].lower() in _SCAN_EXTS:
                                found.append(os.path.join(root_d, f))
                    if found:
                        # auto-set source root if empty
                        if not src_root_var.get().strip():
                            src_root_var.set(folder)
                        _add_files_to_pending(found)
                    else:
                        messagebox.showinfo("No files", f"No game files found in:\n{folder}", parent=dlg)

                def _remove_selected():
                    sel = tree.selection()
                    if not sel:
                        return
                    indices = sorted([tree.index(s) for s in sel], reverse=True)
                    for idx in indices:
                        del pending[idx]
                    _refresh_tree()

                def _refresh_origs():
                    for entry in pending:
                        entry[1] = _find_orig(entry[0], orig_folder_var)
                    _refresh_tree()

                # ── button bar below list ─────────────────────────────
                bar = tk.Frame(dlg, bg=AppColors.BG_DARK, padx=12)
                bar.pack(fill="x", pady=(0, 4))

                tk.Button(bar, text="📄  Add Files",
                          font=self._theme.get_font(),
                          bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY,
                          relief="flat", padx=10, pady=4, cursor="hand2",
                          command=_browse_files).pack(side="left", padx=(0, 6))
                tk.Button(bar, text="📁  Add Folder",
                          font=self._theme.get_font(),
                          bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY,
                          relief="flat", padx=10, pady=4, cursor="hand2",
                          command=_browse_folder).pack(side="left", padx=(0, 6))
                tk.Button(bar, text="🔄  Re-scan Origs",
                          font=self._theme.get_font(),
                          bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY,
                          relief="flat", padx=10, pady=4, cursor="hand2",
                          command=_refresh_origs).pack(side="left", padx=(0, 6))
                tk.Button(bar, text="✕  Remove Selected",
                          font=self._theme.get_font(),
                          bg=AppColors.ERROR, fg="white",
                          relief="flat", padx=10, pady=4, cursor="hand2",
                          command=_remove_selected).pack(side="left")
                tk.Label(bar, textvariable=count_var,
                         font=self._theme.get_small_font(),
                         bg=AppColors.BG_DARK, fg=AppColors.TEXT_MUTED).pack(side="right")

                # ── add all / cancel ──────────────────────────────────
                tk.Frame(dlg, bg=AppColors.BORDER, height=1).pack(fill="x")
                bottom = tk.Frame(dlg, bg=AppColors.BG_DARK, padx=12, pady=8)
                bottom.pack(fill="x")

                result_var = tk.StringVar()
                tk.Label(bottom, textvariable=result_var,
                         font=self._theme.get_small_font(),
                         bg=AppColors.BG_DARK, fg=AppColors.TEXT_MUTED,
                         anchor="w").pack(side="left", fill="x", expand=True)

                def _do_add_all():
                    if not pending:
                        messagebox.showwarning("Empty", "Add at least one file first.", parent=dlg)
                        return
                    errors, added = [], 0
                    for mod_p, orig_p, tgt in pending:
                        ok, msg = p.add_file(gid, mod_p, orig_p, tgt)
                        if ok:
                            added += 1
                        else:
                            errors.append(msg)
                    if errors:
                        result_var.set(f"Added {added}, errors: {len(errors)}: {errors[0]}")
                    else:
                        dlg.destroy()
                        _refresh_pkg_table()

                tk.Button(bottom, text="✅  Add All Files",
                          font=self._theme.get_font(style="bold"),
                          bg=AppColors.SUCCESS, fg="black",
                          relief="flat", padx=16, pady=5, cursor="hand2",
                          command=_do_add_all).pack(side="right", padx=(8, 0))
                tk.Button(bottom, text="Cancel",
                          font=self._theme.get_font(),
                          bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY,
                          relief="flat", padx=12, pady=5, cursor="hand2",
                          command=dlg.destroy).pack(side="right")

            tk.Button(mod_card, text="+ Add File", font=self._theme.get_font(),
                      bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY, relief="flat",
                      padx=12, pady=3, cursor="hand2",
                      command=_add_mod_file).pack(anchor="w", pady=(8, 0))

        # Populate game list
        games = self._game_manager.get_game_list() if self._game_manager else []
        for game in games:
            gid = game["id"]
            btn = tk.Button(games_list_frame.inner, text=gid,
                            font=self._theme.get_font(), bg=AppColors.BG_CARD,
                            fg=AppColors.TEXT_PRIMARY, relief="flat",
                            padx=10, pady=6, anchor="w", cursor="hand2",
                            command=lambda g=gid: load_game_settings(g))
            btn.pack(fill="x", pady=1, padx=4)
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=AppColors.SIDEBAR_ACTIVE))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=AppColors.BG_CARD))

        # ── PIN change ─────────────────────────────────────────────
        pin_bar = tk.Frame(win, bg=AppColors.BG_MEDIUM, padx=15, pady=8)
        pin_bar.pack(fill="x", side="bottom")
        tk.Label(pin_bar, text="Change PIN:", font=self._theme.get_font(),
                 bg=AppColors.BG_MEDIUM, fg=AppColors.TEXT_SECONDARY).pack(side="left")
        new_pin_var = tk.StringVar()
        new_pin_entry = tk.Entry(pin_bar, textvariable=new_pin_var, show="●",
                                 font=self._theme.get_font(), bg=AppColors.ENTRY_BG,
                                 fg=AppColors.TEXT_PRIMARY, insertbackground=AppColors.TEXT_PRIMARY,
                                 relief="flat", width=8, justify="center")
        new_pin_entry.pack(side="left", padx=8, ipady=3)

        def change_pin():
            import hashlib
            new_pin = new_pin_var.get().strip()
            if len(new_pin) < 4:
                return
            new_hash = hashlib.sha256(new_pin.encode()).hexdigest()
            self._config.setdefault("admin", {})["pin_hash"] = new_hash
            self._save_config()
            new_pin_var.set("")
            self._set_status("Admin PIN changed")

        tk.Button(pin_bar, text="Update PIN", font=self._theme.get_small_font(),
                  bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY, relief="flat",
                  padx=10, pady=2, command=change_pin).pack(side="left")

    def _load_game_image(self, game_id: str, path: str):
        try:
            from PIL import Image, ImageTk
            img = Image.open(path).resize((200, 120), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._game_images[game_id] = photo
        except Exception:
            pass

    def _show_context_menu(self, event):
        widget = event.widget
        menu = tk.Menu(widget, tearoff=0, bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY,
                       activebackground=AppColors.ACCENT, activeforeground=AppColors.TEXT_PRIMARY,
                       relief="flat", bd=0)
        menu.add_command(label="Cut", command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label="Copy", command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label="Paste", command=lambda: widget.event_generate("<<Paste>>"))
        menu.add_separator()
        menu.add_command(label="Select All", command=lambda: widget.event_generate("<<SelectAll>>"))
        menu.tk_popup(event.x_root, event.y_root)

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        style.configure(".", background=AppColors.BG_DARK, foreground=AppColors.TEXT_PRIMARY)
        style.configure("TFrame", background=AppColors.BG_DARK)
        style.configure("TLabel", background=AppColors.BG_DARK, foreground=AppColors.TEXT_PRIMARY, font=("Segoe UI", 10))
        style.configure("TButton", background=AppColors.ACCENT, foreground=AppColors.TEXT_PRIMARY, font=("Segoe UI", 10), padding=(12, 6))
        style.map("TButton", background=[("active", AppColors.ACCENT_HOVER)])
        
        style.configure("Sidebar.TFrame", background=AppColors.SIDEBAR_BG)
        style.configure("Sidebar.TLabel", background=AppColors.SIDEBAR_BG, foreground=AppColors.TEXT_SECONDARY, font=("Segoe UI", 10))
        style.configure("SidebarActive.TLabel", background=AppColors.SIDEBAR_ACTIVE, foreground=AppColors.TEXT_PRIMARY, font=("Segoe UI", 10, "bold"))
        
        style.configure("Header.TLabel", background=AppColors.BG_DARK, foreground=AppColors.TEXT_PRIMARY, font=("Segoe UI", 16, "bold"))
        style.configure("SubHeader.TLabel", background=AppColors.BG_DARK, foreground=AppColors.TEXT_SECONDARY, font=("Segoe UI", 11))
        style.configure("Status.TLabel", background=AppColors.BG_MEDIUM, foreground=AppColors.TEXT_MUTED, font=("Segoe UI", 9))
        
        style.configure("Card.TFrame", background=AppColors.BG_CARD)
        style.configure("Card.TLabel", background=AppColors.BG_CARD, foreground=AppColors.TEXT_PRIMARY, font=("Segoe UI", 10))
        style.configure("CardHeader.TLabel", background=AppColors.BG_CARD, foreground=AppColors.TEXT_PRIMARY, font=("Segoe UI", 12, "bold"))
        
        style.configure("Success.TLabel", background=AppColors.BG_DARK, foreground=AppColors.SUCCESS, font=("Segoe UI", 10))
        style.configure("Error.TLabel", background=AppColors.BG_DARK, foreground=AppColors.ERROR, font=("Segoe UI", 10))
        
        style.configure("Accent.TButton", background=AppColors.ACCENT, foreground=AppColors.TEXT_PRIMARY, font=("Segoe UI", 10, "bold"), padding=(16, 8))
        style.map("Accent.TButton", background=[("active", AppColors.ACCENT_HOVER)])
        
        style.configure("Secondary.TButton", background=AppColors.BG_LIGHT, foreground=AppColors.TEXT_PRIMARY, font=("Segoe UI", 10), padding=(12, 6))
        style.map("Secondary.TButton", background=[("active", AppColors.BORDER)])
    
    def _build_ui(self):
        main_container = tk.Frame(self.root, bg=AppColors.BG_DARK)
        main_container.pack(fill="both", expand=True)
        
        sidebar = tk.Frame(main_container, bg=AppColors.SIDEBAR_BG, width=220)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        
        content_area = tk.Frame(main_container, bg=AppColors.BG_DARK)
        content_area.pack(side="left", fill="both", expand=True)
        
        self._build_sidebar(sidebar)
        self._build_content(content_area)
        self._build_status_bar()
    
    def _build_sidebar(self, parent):
        logo_frame = tk.Frame(parent, bg=AppColors.SIDEBAR_BG)
        logo_frame.pack(fill="x", pady=(15, 25), padx=15)
        
        tk.Label(logo_frame, text="🎮", font=("Segoe UI", 24), bg=AppColors.SIDEBAR_BG, fg=AppColors.ACCENT).pack()
        tk.Label(logo_frame, text="Game Arabic\nTranslator", font=("Segoe UI", 13, "bold"), bg=AppColors.SIDEBAR_BG, fg=AppColors.TEXT_PRIMARY, justify="center").pack(pady=(5, 0))
        version_lbl = tk.Label(logo_frame, text="v1.0", font=("Segoe UI", 9), bg=AppColors.SIDEBAR_BG, fg=AppColors.TEXT_MUTED, cursor="arrow")
        version_lbl.pack()
        self._admin_click_count = 0
        self._admin_click_timer = None
        version_lbl.bind("<Button-1>", self._handle_admin_click)
        
        separator = tk.Frame(parent, bg=AppColors.BORDER, height=1)
        separator.pack(fill="x", padx=15, pady=5)
        
        self._nav_buttons = {}
        nav_items = [
            ("home", "🏠  Home", self._show_home),
            ("games", "🎮  Games", self._show_games),
            ("translate", "🌐  Translate", self._show_translate),
            ("models", "🤖  AI Models", self._show_models),
            ("cache", "💾  Cache", self._show_cache),
            ("settings", "⚙️  Settings", self._show_settings),
        ]
        
        for key, label, command in nav_items:
            btn_frame = tk.Frame(parent, bg=AppColors.SIDEBAR_BG, cursor="hand2")
            btn_frame.pack(fill="x", padx=8, pady=2)
            
            lbl = tk.Label(btn_frame, text=label, font=("Segoe UI", 11), bg=AppColors.SIDEBAR_BG, fg=AppColors.TEXT_SECONDARY, anchor="w", padx=15, pady=10)
            lbl.pack(fill="x")
            
            lbl.bind("<Button-1>", lambda e, k=key, cmd=command: self._navigate(k, cmd))
            btn_frame.bind("<Button-1>", lambda e, k=key, cmd=command: self._navigate(k, cmd))
            lbl.bind("<Enter>", lambda e, l=lbl: l.configure(bg=AppColors.SIDEBAR_ACTIVE))
            lbl.bind("<Leave>", lambda e, l=lbl, k=key: l.configure(bg=AppColors.SIDEBAR_ACTIVE if k == self._current_page else AppColors.SIDEBAR_BG))
            
            self._nav_buttons[key] = lbl
        
        self._current_page = "home"
        self._nav_buttons["home"].configure(bg=AppColors.SIDEBAR_ACTIVE, fg=AppColors.TEXT_PRIMARY)
        
        bottom_frame = tk.Frame(parent, bg=AppColors.SIDEBAR_BG)
        bottom_frame.pack(side="bottom", fill="x", padx=15, pady=15)
        
        self._model_indicator = tk.Label(bottom_frame, text="🔴 No model loaded", font=("Segoe UI", 9), bg=AppColors.SIDEBAR_BG, fg=AppColors.ERROR, anchor="w")
        self._model_indicator.pack(fill="x")
        
        self._process_indicator = tk.Label(bottom_frame, text="⚪ No game attached", font=("Segoe UI", 9), bg=AppColors.SIDEBAR_BG, fg=AppColors.TEXT_MUTED, anchor="w")
        self._process_indicator.pack(fill="x", pady=(3, 0))
    
    def _build_content(self, parent):
        self._content_frame = tk.Frame(parent, bg=AppColors.BG_DARK)
        self._content_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        self._pages = {}
        self._build_home_page()
        self._build_games_page()
        self._build_translate_page()
        self._build_models_page()
        self._build_cache_page()
        self._build_settings_page()
        
        self._show_page("home")
    
    def _build_home_page(self):
        page = tk.Frame(self._content_frame, bg=AppColors.BG_DARK)
        self._pages["home"] = page

        tk.Label(page, text="الألعاب المتاحة للتعريب",
                 font=("Segoe UI", 20, "bold"),
                 bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        tk.Label(page, text="اختر لعبة لتركيب أو إزالة التعريب",
                 font=("Segoe UI", 11),
                 bg=AppColors.BG_DARK, fg=AppColors.TEXT_SECONDARY).pack(anchor="w", pady=(0, 16))

        self._home_games_container = ScrollableFrame(page)
        self._home_games_container.pack(fill="both", expand=True)

    def _refresh_home_games(self):
        for widget in self._home_games_container.inner.winfo_children():
            widget.destroy()

        if not self._game_manager:
            return

        from games.translation_package import TranslationPackage
        pkg = TranslationPackage()

        all_games = self._game_manager.get_game_list()
        ready = [g for g in all_games if pkg.has_files(g["id"])]

        if not ready:
            tk.Label(self._home_games_container.inner,
                     text="لا توجد ألعاب جاهزة بعد.\nأضف ملفات التعريب من صفحة Games ثم لوحة Admin.",
                     font=("Segoe UI", 12), bg=AppColors.BG_DARK,
                     fg=AppColors.TEXT_MUTED, justify="center").pack(pady=60)
            return

        grid_frame = tk.Frame(self._home_games_container.inner, bg=AppColors.BG_DARK)
        grid_frame.pack(fill="x", padx=5)

        cols = 3
        for i, game in enumerate(ready):
            row, col = divmod(i, cols)
            game_id  = game["id"]
            gpath    = game.get("game_path", "")

            card = tk.Frame(grid_frame, bg=AppColors.BG_CARD, padx=12, pady=12)
            card.grid(row=row, column=col, padx=8, pady=8, sticky="ew")
            grid_frame.grid_columnconfigure(col, weight=1)

            # image
            img_frame = tk.Frame(card, bg=AppColors.BG_LIGHT, height=110, width=180)
            img_frame.pack(fill="x", pady=(0, 8))
            img_frame.pack_propagate(False)
            if game_id in self._game_images:
                try:
                    tk.Label(img_frame, image=self._game_images[game_id],
                             bg=AppColors.BG_LIGHT).pack(fill="both", expand=True)
                except:
                    tk.Label(img_frame, text="🎮", font=("Segoe UI", 32),
                             bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_MUTED).pack(expand=True)
            else:
                tk.Label(img_frame, text="🎮", font=("Segoe UI", 32),
                         bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_MUTED).pack(expand=True)

            # name
            tk.Label(card, text=game["name"], font=("Segoe UI", 12, "bold"),
                     bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY,
                     wraplength=200).pack(anchor="w")

            # status
            st = pkg.get_status(game_id, gpath)
            if st is True:
                st_text, st_color = "✅  التعريب مثبّت", AppColors.SUCCESS
            elif st is False:
                st_text, st_color = "⭕  غير مثبّت", AppColors.TEXT_SECONDARY
            else:
                st_text, st_color = "❓  غير معروف", AppColors.WARNING

            st_lbl = tk.Label(card, text=st_text, font=("Segoe UI", 9, "bold"),
                              bg=AppColors.BG_CARD, fg=st_color)
            st_lbl.pack(anchor="w", pady=(3, 8))

            # log label
            log_var = tk.StringVar()
            log_lbl = tk.Label(card, textvariable=log_var, font=("Segoe UI", 8),
                               bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED,
                               justify="left", anchor="w", wraplength=200)
            log_lbl.pack(fill="x")

            def _install(gid=game_id, gp=gpath, p=pkg, sl=st_lbl, lv=log_var):
                ok, lines = p.install(gid, gp)
                lv.set("\n".join(lines[-4:]))
                sl.configure(
                    text="✅  التعريب مثبّت" if ok else "⚠️  خطأ في التركيب",
                    fg=AppColors.SUCCESS if ok else AppColors.WARNING)

            def _uninstall(gid=game_id, gp=gpath, p=pkg, sl=st_lbl, lv=log_var):
                ok, lines = p.uninstall(gid, gp)
                lv.set("\n".join(lines[-4:]))
                sl.configure(
                    text="⭕  غير مثبّت" if ok else "⚠️  خطأ في الإزالة",
                    fg=AppColors.TEXT_SECONDARY if ok else AppColors.WARNING)

            btn_row = tk.Frame(card, bg=AppColors.BG_CARD)
            btn_row.pack(anchor="w", pady=(6, 0))
            tk.Button(btn_row, text="🔧  تركيب التعريب",
                      font=("Segoe UI", 10, "bold"),
                      bg=AppColors.SUCCESS, fg="black",
                      relief="flat", padx=14, pady=5, cursor="hand2",
                      command=_install).pack(side="left", padx=(0, 6))
            tk.Button(btn_row, text="🗑  إزالة",
                      font=("Segoe UI", 10),
                      bg=AppColors.ERROR, fg="white",
                      relief="flat", padx=10, pady=5, cursor="hand2",
                      command=_uninstall).pack(side="left")
    
    def _set_game_image(self, game_id):
        filepath = filedialog.askopenfilename(
            title="Select Game Image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp"), ("All files", "*.*")]
        )
        if not filepath:
            return
        
        try:
            from PIL import Image, ImageTk
            img = Image.open(filepath)
            img = img.resize((160, 100), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._game_images[game_id] = photo
            
            images_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "game_images")
            os.makedirs(images_dir, exist_ok=True)
            save_path = os.path.join(images_dir, f"{game_id}.png")
            img.save(save_path, "PNG")
            
            self._refresh_home_games()
            self._set_status(f"Image set for {game_id}")
        except ImportError:
            messagebox.showinfo("Info", "Install Pillow for image support: pip install Pillow")
        except Exception as e:
            self._set_status(f"Image error: {e}")
    
    def _load_game_images(self):
        images_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "game_images")
        if not os.path.exists(images_dir):
            return
        
        try:
            from PIL import Image, ImageTk
            for filename in os.listdir(images_dir):
                if filename.endswith((".png", ".jpg", ".jpeg")):
                    game_id = os.path.splitext(filename)[0]
                    filepath = os.path.join(images_dir, filename)
                    img = Image.open(filepath)
                    img = img.resize((160, 100), Image.LANCZOS)
                    self._game_images[game_id] = ImageTk.PhotoImage(img)
        except:
            pass
    
    def _show_game_detail(self, game_id):
        if "game_detail" in self._pages:
            self._pages["game_detail"].destroy()
            del self._pages["game_detail"]
        
        game_config = self._game_manager.get_game(game_id) if self._game_manager else None
        if not game_config:
            return

        game_name = game_config.get("name", game_id)
        hidden = set(game_config.get("hidden_features", []))
        shown_extra = set(game_config.get("shown_features", []))
        
        page = tk.Frame(self._content_frame, bg=AppColors.BG_DARK)
        self._pages["game_detail"] = page

        self._show_page("game_detail")

        header = tk.Frame(page, bg=AppColors.BG_DARK)
        header.pack(fill="x", pady=(0, 10))

        back_btn = tk.Button(header, text="← Back", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=12, pady=4, cursor="hand2", command=lambda: self._navigate("home", self._show_home))
        back_btn.pack(side="left")

        tk.Label(header, text=f"  {game_name}", font=self._theme.get_title_font(), bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(side="left")

        scroll = ScrollableFrame(page, bg_color=AppColors.BG_DARK)
        scroll.pack(fill="both", expand=True)
        content = scroll.inner

        top_frame = tk.Frame(content, bg=AppColors.BG_DARK)
        top_frame.pack(fill="x", pady=(0, 15))
        
        img_frame = tk.Frame(top_frame, bg=AppColors.BG_LIGHT, height=120, width=200)
        img_frame.pack(side="left", padx=(0, 15))
        img_frame.pack_propagate(False)
        
        if game_id in self._game_images:
            try:
                img_label = tk.Label(img_frame, image=self._game_images[game_id], bg=AppColors.BG_LIGHT)
                img_label.pack(fill="both", expand=True)
            except:
                tk.Label(img_frame, text="🎮", font=("Segoe UI", 32), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_MUTED).pack(expand=True)
        else:
            tk.Label(img_frame, text="🎮", font=("Segoe UI", 32), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_MUTED).pack(expand=True)
        
        info_frame = tk.Frame(top_frame, bg=AppColors.BG_CARD, padx=20, pady=15)
        info_frame.pack(side="left", fill="both", expand=True)
        
        details = [
            ("Game ID:", game_id),
            ("Process:", game_config.get("process_name", "Not set")),
            ("Engine:", game_config.get("engine", "auto")),
            ("Path:", game_config.get("game_path", "Not set")),
            ("Hook:", game_config.get("hook_mode", "frida")),
        ]
        
        for label, value in details:
            row = tk.Frame(info_frame, bg=AppColors.BG_CARD)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, width=10, anchor="w").pack(side="left")
            tk.Label(row, text=value, font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY, anchor="w").pack(side="left")
        
        img_change_btn = tk.Button(info_frame, text="📷 Change Image", font=self._theme.get_small_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=2, cursor="hand2", command=lambda: self._set_game_image(game_id))
        img_change_btn.pack(anchor="w", pady=(8, 0))

        # ── Translation Package ──────────────────────────────────────────
        from games.translation_package import TranslationPackage
        _pkg = TranslationPackage()
        _game_path = game_config.get("game_path", "")

        if _pkg.has_files(game_id):
            pkg_frame = tk.Frame(content, bg=AppColors.BG_CARD, padx=20, pady=15)
            pkg_frame.pack(fill="x", pady=(0, 10))

            tk.Label(pkg_frame, text="📦  Translation Package",
                     font=self._theme.get_header_font(),
                     bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 8))

            status = _pkg.get_status(game_id, _game_path)
            if status is True:
                status_text  = "✅  Installed"
                status_color = AppColors.SUCCESS
            elif status is False:
                status_text  = "⭕  Not installed (original files active)"
                status_color = AppColors.TEXT_SECONDARY
            else:
                status_text  = "❓  Unknown status"
                status_color = AppColors.WARNING

            status_lbl = tk.Label(pkg_frame, text=status_text,
                                  font=self._theme.get_font(style="bold"),
                                  bg=AppColors.BG_CARD, fg=status_color)
            status_lbl.pack(anchor="w", pady=(0, 8))

            cfg_files = _pkg.get_config(game_id)["files"]
            for entry in cfg_files:
                orig_mark = "✓ .orig" if entry.get("has_orig") else "✗ no .orig"
                tk.Label(pkg_frame,
                         text=f"  • {entry['name']}   →   {entry.get('game_target','')}   [{orig_mark}]",
                         font=self._theme.get_small_font(),
                         bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED, anchor="w").pack(fill="x")

            pkg_log_var = tk.StringVar()
            pkg_log_lbl = tk.Label(pkg_frame, textvariable=pkg_log_var,
                                   font=self._theme.get_small_font(),
                                   bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED,
                                   justify="left", anchor="w")
            pkg_log_lbl.pack(fill="x", pady=(6, 0))

            def _run_install(gid=game_id, gpath=_game_path, p=_pkg,
                             slbl=status_lbl, logv=pkg_log_var):
                ok, lines = p.install(gid, gpath)
                logv.set("\n".join(lines))
                if ok:
                    slbl.configure(text="✅  Installed", fg=AppColors.SUCCESS)
                    self._safe_after(100, self._refresh_home_games)
                else:
                    slbl.configure(text="⚠️  Install errors — check log", fg=AppColors.WARNING)

            def _run_uninstall(gid=game_id, gpath=_game_path, p=_pkg,
                               slbl=status_lbl, logv=pkg_log_var):
                ok, lines = p.uninstall(gid, gpath)
                logv.set("\n".join(lines))
                if ok:
                    slbl.configure(text="⭕  Not installed (original files active)", fg=AppColors.TEXT_SECONDARY)
                    self._safe_after(100, self._refresh_home_games)
                else:
                    slbl.configure(text="⚠️  Uninstall errors — check log", fg=AppColors.WARNING)

            btn_row = tk.Frame(pkg_frame, bg=AppColors.BG_CARD)
            btn_row.pack(anchor="w", pady=(10, 0))
            tk.Button(btn_row, text="🔧  تركيب التعريب",
                      font=self._theme.get_font(style="bold"),
                      bg=AppColors.SUCCESS, fg="black",
                      relief="flat", padx=18, pady=6, cursor="hand2",
                      command=_run_install).pack(side="left", padx=(0, 8))
            tk.Button(btn_row, text="🗑  إزالة التعريب",
                      font=self._theme.get_font(style="bold"),
                      bg=AppColors.ERROR, fg="white",
                      relief="flat", padx=18, pady=6, cursor="hand2",
                      command=_run_uninstall).pack(side="left")

        # ── Update from Cache card ────────────────────────────────────
        _legacy_in_cache = _pkg.get_legacy_in_cache(game_id)
        if _legacy_in_cache:
            _wcfg = _pkg.get_wizard_config(game_id)
            upd_frame = tk.Frame(content, bg=AppColors.BG_CARD, padx=20, pady=15)
            upd_frame.pack(fill="x", pady=(0, 10))

            tk.Label(upd_frame, text="🔄  تحديث من الكاش",
                     font=self._theme.get_header_font(),
                     bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
            tk.Label(upd_frame,
                     text="يُطبّق التعديلات من الكاش على ملفات for_cache ثم يُعيد الـPak ويحفظه في ready/",
                     font=self._theme.get_small_font(),
                     bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED).pack(anchor="w", pady=(0, 8))

            # show current wizard config
            ue_v   = _wcfg.get("ue_version", "VER_UE5_6")
            zen_v  = _wcfg.get("zen_version", "UE5_6")
            mode_v = _wcfg.get("extraction_mode", "default_text")
            maps_v = _wcfg.get("mappings", "")
            base_v = _wcfg.get("output_base", "")
            cname  = _wcfg.get("cache_game_name", game_name)

            for lbl, val in [("Cache name:", cname), ("UE Version:", ue_v),
                              ("Zen Version:", zen_v), ("Legacy folder:", _legacy_in_cache)]:
                r = tk.Frame(upd_frame, bg=AppColors.BG_CARD)
                r.pack(fill="x", pady=1)
                tk.Label(r, text=lbl, font=self._theme.get_small_font(),
                         bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY,
                         width=14, anchor="w").pack(side="left")
                tk.Label(r, text=val, font=self._theme.get_small_font(),
                         bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY,
                         anchor="w").pack(side="left")

            upd_log_var = tk.StringVar()
            upd_log_lbl = tk.Label(upd_frame, textvariable=upd_log_var,
                                   font=("Consolas", 8),
                                   bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED,
                                   justify="left", anchor="w")
            upd_log_lbl.pack(fill="x", pady=(6, 0))

            def _run_update_cache(
                    gid=game_id, gpath=_game_path, p=_pkg,
                    legacy=_legacy_in_cache, wcfg=_wcfg,
                    logv=upd_log_var, cache_name=cname):
                import threading
                from games.iostore.translator import IoStoreTranslator

                def _thread():
                    lines = []
                    def _log(m): lines.append(m); logv.set("\n".join(lines[-8:]))

                    _log("▶ Step 1 — Re-sync cache → JSON files…")
                    _tools = self._config.get("tools", {})
                    t = IoStoreTranslator(
                        translator_engine=self._translation_engine,
                        cache=self._cache,
                        retoc_path=_tools.get("retoc_path") or None,
                        uassetgui_path=_tools.get("uassetgui_path") or None)
                    t.set_callbacks(log=_log)

                    _mode  = wcfg.get("extraction_mode", "default_text")
                    _maps  = wcfg.get("mappings", "")
                    _ue    = wcfg.get("ue_version", "VER_UE5_6")
                    _zen   = wcfg.get("zen_version", "UE5_6")
                    _base  = wcfg.get("output_base", "")
                    _gtdir = wcfg.get("game_target_dir", "")

                    import os as _os

                    # Collect .uasset.json files — must exist (saved via Step 6 → "حفظ الحالة في for_cache")
                    json_files = []
                    for root_d, _, files in _os.walk(legacy):
                        for f in files:
                            if f.endswith(".uasset.json"):
                                json_files.append(_os.path.join(root_d, f))

                    if not json_files:
                        _log("ERROR: No .uasset.json files in for_cache/")
                        _log("  → Run Step 6 in the IoStore wizard, then click '📦 حفظ الحالة في for_cache'")
                        return

                    _log(f"▶ Step A — {len(json_files)} JSON files found in for_cache")

                    # Step B — apply cache (reads from .orig English backup)
                    _log("▶ Step B — apply cache → JSON…")
                    applied_total = 0
                    for jf in json_files:
                        orig_jf = jf + ".orig"
                        src_jf  = orig_jf if _os.path.exists(orig_jf) else jf
                        texts   = t.extract_texts_from_json(src_jf, _mode)
                        if not texts:
                            continue
                        cached  = self._cache.get_batch(cache_name, texts) if self._cache else {}
                        if not cached:
                            continue
                        src_arg = orig_jf if _os.path.exists(orig_jf) else None
                        t.apply_translations_to_json(jf, cached, _mode, source_path=src_arg)
                        applied_total += len(cached)
                        _log(f"  {_os.path.basename(jf)}: {len(cached)} applied")

                    _log(f"  Total: {applied_total} strings across {len(json_files)} files")
                    if applied_total == 0:
                        _log("⚠ 0 cache hits — populate cache via Step 3 in IoStore wizard first")
                        _log("❌ Aborted — no translations applied, game files unchanged")
                        return

                    _log("▶ Step C — fromjson → .uasset…")
                    count = t.json_folder_to_uasset(legacy, _ue, _maps)
                    _log(f"  Converted {count} files")

                    _log("▶ Step 3 — to-zen (repack)…")
                    if _base:
                        ok3 = t.to_zen(legacy, _base, _zen)
                        if ok3:
                            _clean = _base[:-5] if _base.endswith(".utoc") else _base
                            _actual = _clean + "_P"
                            ok4, pak_lines = p.save_paks_to_ready(gid, _actual, _gtdir)
                            for ln in pak_lines:
                                _log(ln)
                            # direct install to game Paks folder if absolute path
                            import shutil as _sh
                            if _gtdir and _os.path.isdir(_gtdir):
                                for _ext in (".pak", ".ucas", ".utoc"):
                                    _src = _actual + _ext
                                    if _os.path.isfile(_src):
                                        _dst = _os.path.join(_gtdir, _os.path.basename(_src))
                                        try:
                                            _sh.copy2(_src, _dst)
                                            _log(f"✓ Installed: {_os.path.basename(_src)}  →  {_gtdir}")
                                        except Exception as _e:
                                            _log(f"ERROR installing: {_e}")
                            # cleanup output files
                            for _ext in (".pak", ".ucas", ".utoc"):
                                _f = _actual + _ext
                                if _os.path.isfile(_f):
                                    try:
                                        _os.remove(_f)
                                    except Exception:
                                        pass
                            _log("✅ تحديث مكتمل — ready/ محدّث")
                        else:
                            _log("❌ to-zen failed")
                    else:
                        _log("⚠️ output_base not set in wizard config — run Step 5 first")

                threading.Thread(target=_thread, daemon=True).start()

            tk.Button(upd_frame, text="🔄  تحديث من الكاش  +  إعادة Pak",
                      font=self._theme.get_font(style="bold"),
                      bg="#9b59b6", fg="white",
                      relief="flat", padx=18, pady=6, cursor="hand2",
                      command=_run_update_cache).pack(anchor="w", pady=(8, 0))

        cache_frame = tk.Frame(content, bg=AppColors.BG_CARD, padx=20, pady=15)
        if "cache_section" not in hidden:
            cache_frame.pack(fill="x", pady=(0, 10))

        tk.Label(cache_frame, text="💾 Translation Cache", font=self._theme.get_header_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 10))
        
        cache_stats_frame = tk.Frame(cache_frame, bg=AppColors.BG_CARD)
        cache_stats_frame.pack(fill="x", pady=(0, 10))
        
        if self._cache:
            stats = self._cache.get_stats(game_name)
            models = self._cache.get_models_for_game(game_name)
            
            stat_items = [
                ("Total Translations:", str(stats.get("total_translations", 0))),
                ("Cache Hits:", str(stats.get("cache_hits", 0))),
                ("Failed:", str(stats.get("failed_count", 0))),
                ("Models Used:", ", ".join(models) if models else "None"),
            ]
            
            for label, value in stat_items:
                row = tk.Frame(cache_stats_frame, bg=AppColors.BG_CARD)
                row.pack(fill="x", pady=2)
                tk.Label(row, text=label, font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, width=16, anchor="w").pack(side="left")
                tk.Label(row, text=value, font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY, anchor="w").pack(side="left")
        
        cache_btn_frame = tk.Frame(cache_frame, bg=AppColors.BG_CARD)
        cache_btn_frame.pack(fill="x")
        
        def delete_game_cache():
            if messagebox.askyesno("Confirm", f"Delete all cached translations for {game_name}?"):
                if self._cache:
                    self._cache.delete_game(game_name)
                    self._show_game_detail(game_id)
                    self._set_status(f"Cache deleted for {game_name}")
        
        tk.Button(cache_btn_frame, text="🗑 Delete Cache", font=self._theme.get_font(), bg=AppColors.ERROR, fg="white", relief="flat", padx=15, pady=5, cursor="hand2", command=delete_game_cache).pack(side="left", padx=3)
        
        mod_frame = tk.Frame(content, bg=AppColors.BG_CARD, padx=20, pady=15)
        if "mod_section" not in hidden:
            mod_frame.pack(fill="x", pady=(0, 10))

        tk.Label(mod_frame, text="🔧 Mod Status", font=self._theme.get_header_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 10))
        
        game_path = game_config.get("game_path", "")
        engine_type = game_config.get("engine", "auto")
        
        mod_status_frame = tk.Frame(mod_frame, bg=AppColors.BG_CARD)
        mod_status_frame.pack(fill="x", pady=(0, 10))
        
        has_mod = False
        translate_dir = ""
        subtitle_count = 0
        
        if game_path:
            win64_path = os.path.join(game_path, "ManorLords", "Binaries", "Win64")
            if not os.path.exists(win64_path):
                win64_path = os.path.join(game_path, "Binaries", "Win64")
            
            if os.path.exists(win64_path):
                has_dxgi = os.path.exists(os.path.join(win64_path, "dxgi.dll"))
                has_mod_dll = os.path.exists(os.path.join(win64_path, "ZXSOSZXMod.dll"))
                has_mod = has_dxgi and has_mod_dll
                
                translate_dir = os.path.join(win64_path, "Translate")
                if os.path.exists(translate_dir):
                    subtitle_count = len([f for f in os.listdir(translate_dir) if f.endswith(".subtitle.txt") and not f.endswith(".en.txt")])
        
        mod_details = [
            ("Mod Installed:", "✅ Yes" if has_mod else "❌ No"),
            ("Translate Dir:", translate_dir if translate_dir else "Not found"),
            ("Subtitle Files:", str(subtitle_count)),
            ("Engine Type:", engine_type),
        ]
        
        for label, value in mod_details:
            row = tk.Frame(mod_status_frame, bg=AppColors.BG_CARD)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, width=16, anchor="w").pack(side="left")
            tk.Label(row, text=value, font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY, anchor="w").pack(side="left")
        
        mod_btn_frame = tk.Frame(mod_frame, bg=AppColors.BG_CARD)
        mod_btn_frame.pack(fill="x")
        
        def apply_mod():
            if not game_path:
                messagebox.showwarning("Warning", "Game path not configured")
                return
            
            flath_game_dir = r"D:\FLTAH_Translator_by_zxsoszx\Game"
            zip_path = None
            
            exact_path = os.path.join(flath_game_dir, game_id)
            if os.path.isdir(exact_path):
                for f in os.listdir(exact_path):
                    if f.endswith('.zip'):
                        zip_path = os.path.join(exact_path, f)
                        break
            
            if not zip_path:
                game_id_clean = game_id.replace("_", "").replace(" ", "").lower()
                if os.path.isdir(flath_game_dir):
                    for folder in os.listdir(flath_game_dir):
                        folder_clean = folder.replace("_", "").replace(" ", "").lower()
                        if folder_clean == game_id_clean or game_id_clean.startswith(folder_clean) or folder_clean.startswith(game_id_clean):
                            folder_path = os.path.join(flath_game_dir, folder)
                            if os.path.isdir(folder_path):
                                for f in os.listdir(folder_path):
                                    if f.endswith('.zip'):
                                        zip_path = os.path.join(folder_path, f)
                                        break
                            if zip_path:
                                break
            
            if zip_path and os.path.exists(zip_path):
                import zipfile
                with zipfile.ZipFile(zip_path, 'r') as z:
                    z.extractall(game_path)
                self._show_game_detail(game_id)
                self._set_status(f"Mod installed for {game_name}")
            else:
                messagebox.showinfo("Info", "Mod bundle not found for this game")
        
        def delete_mod():
            if not game_path:
                return
            
            if messagebox.askyesno("Confirm", f"Delete all mod files for {game_name}?\nThis will remove the translation mod from the game directory."):
                win64_path = os.path.join(game_path, "ManorLords", "Binaries", "Win64")
                if not os.path.exists(win64_path):
                    win64_path = os.path.join(game_path, "Binaries", "Win64")
                
                if os.path.exists(win64_path):
                    mod_files = ["dxgi.dll", "ZXSOSZXMod.dll", "ZXSOSZXNMod.dll", "ZXSOSZXSubtitle.exe",
                                 "ZXSOSZXFont.ttf", "ZXSOSZXFormat.ini", "ZXSOSZXHandle.ini", "ZXSOSZXLog.ini",
                                 "ZXSOSZXSubtitle.exe.config", "ZXSOSZXSubtitleReadUni.ini", "ZXSOSZXSubtitleUseUni.ini",
                                 "GameID.ini", "GameName.ini", "GameName1.ini", "zxsoszx_pid.ini",
                                 "mod_addr1.ini", "mod_addr50.ini", "mod_addr51.ini", "mod_addr99.ini"]
                    
                    deleted = 0
                    for f in mod_files:
                        fpath = os.path.join(win64_path, f)
                        if os.path.exists(fpath):
                            os.remove(fpath)
                            deleted += 1
                    
                    translate_dir = os.path.join(win64_path, "Translate")
                    if os.path.exists(translate_dir):
                        import shutil
                        shutil.rmtree(translate_dir)
                        deleted += 1
                    
                    self._show_game_detail(game_id)
                    self._set_status(f"Mod deleted: {deleted} files removed from {game_name}")
        
        tk.Button(mod_btn_frame, text="📦 Install Mod", font=self._theme.get_font(), bg=AppColors.SUCCESS, fg="black", relief="flat", padx=15, pady=5, cursor="hand2", command=apply_mod).pack(side="left", padx=3)
        tk.Button(mod_btn_frame, text="🗑 Delete Mod", font=self._theme.get_font(), bg=AppColors.ERROR, fg="white", relief="flat", padx=15, pady=5, cursor="hand2", command=delete_mod).pack(side="left", padx=3)
        
        trans_frame = tk.Frame(content, bg=AppColors.BG_CARD, padx=20, pady=15)
        trans_frame.pack(fill="x", pady=(0, 10))
        
        tk.Label(trans_frame, text="🌐 Quick Actions", font=self._theme.get_header_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 10))
        
        action_btn_frame = tk.Frame(trans_frame, bg=AppColors.BG_CARD)
        action_btn_frame.pack(fill="x")
        
        if "translate" not in hidden:
            tk.Button(action_btn_frame, text="🌐 Translate Game", font=self._theme.get_font(), bg="#9b59b6", fg="white", relief="flat", padx=15, pady=5, cursor="hand2", command=lambda: self._translate_game({"id": game_id, "name": game_name})).pack(side="left", padx=3)
        if "attach" not in hidden:
            tk.Button(action_btn_frame, text="🔗 Attach to Game", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=15, pady=5, cursor="hand2", command=lambda: self._attach_to_game({"id": game_id, "name": game_name, "process_name": game_config.get("process_name", "")})).pack(side="left", padx=3)

        if "server" not in hidden and (game_config.get("hook_mode") == "bepinex" or "flotsam" in game_id.lower()):
            tk.Button(action_btn_frame, text="🖥️ Start Server", font=self._theme.get_font(), bg=AppColors.SUCCESS, fg="black", relief="flat", padx=15, pady=5, cursor="hand2", command=lambda: self._start_translation_server()).pack(side="left", padx=3)

        if "sync_from" not in hidden:
            tk.Button(action_btn_frame, text="📥 Sync from Game", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=15, pady=5, cursor="hand2", command=lambda: self._sync_from_game(game_id, game_name, game_config)).pack(side="left", padx=3)
        if "sync_to" not in hidden:
            tk.Button(action_btn_frame, text="📤 Sync to Game", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=15, pady=5, cursor="hand2", command=lambda: self._sync_to_game(game_id, game_name, game_config)).pack(side="left", padx=3)
        if "edit_config" not in hidden:
            tk.Button(action_btn_frame, text="✏️ Edit Config", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=15, pady=5, cursor="hand2", command=lambda: self._edit_game_dialog(game_id)).pack(side="left", padx=3)
        
        game_id_lower = game_id.lower().replace(" ", "").replace("_", "")
        _is_moe = "myth" in game_id_lower or "empires" in game_id_lower or "moe" in game_id_lower
        if "locres_section" not in hidden and (_is_moe or "locres_section" in shown_extra):
            locres_frame = tk.Frame(content, bg=AppColors.BG_CARD, padx=20, pady=10)
            locres_frame.pack(fill="x", pady=(0, 10))
            
            saved_locres = game_config.get("locres_path", "")
            locres_label_text = saved_locres if saved_locres and os.path.exists(saved_locres) else "No .locres file selected"
            
            tk.Label(locres_frame, text="📄 Locres File:", font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(side="left")
            locres_var = tk.StringVar(value=locres_label_text)
            locres_entry = tk.Entry(locres_frame, textvariable=locres_var, font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", width=60)
            locres_entry.pack(side="left", padx=5, fill="x", expand=True)
            
            def browse_locres():
                path = filedialog.askopenfilename(
                    title="Select .locres file",
                    initialdir=game_path,
                    filetypes=[("UE4 Localization", "*.locres"), ("All files", "*.*")]
                )
                if path:
                    locres_var.set(path)
                    if self._game_manager:
                        self._game_manager.update_game(game_id, {"locres_path": path})
                    self._set_status(f"Locres path saved: {os.path.basename(path)}")
            
            tk.Button(locres_frame, text="Browse", font=self._theme.get_font(), bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=3, cursor="hand2", command=browse_locres).pack(side="left", padx=3)

        if "iostore_section" not in hidden and "iostore_section" in shown_extra:
            iostore_frame = tk.Frame(content, bg=AppColors.BG_CARD, padx=20, pady=15)
            iostore_frame.pack(fill="x", pady=(0, 10))

            hdr = tk.Frame(iostore_frame, bg=AppColors.BG_CARD)
            hdr.pack(fill="x", pady=(0, 8))
            tk.Label(hdr, text="📦 IoStore / UAsset Translator",
                     font=self._theme.get_header_font(),
                     bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(side="left")
            tk.Label(hdr, text="UE5 IoStore (.utoc/.ucas)",
                     font=self._theme.get_small_font(),
                     bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED).pack(side="left", padx=10)

            tk.Label(iostore_frame,
                     text="Extract → Translate → Repack UE5 IoStore containers using retoc + UAssetGUI",
                     font=self._theme.get_small_font(),
                     bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED).pack(anchor="w", pady=(0, 10))

            open_btn = tk.Button(iostore_frame, text="📦  Open IoStore Wizard",
                                 font=self._theme.get_font(style="bold"),
                                 bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY,
                                 relief="flat", padx=18, pady=6, cursor="hand2",
                                 command=lambda gid=game_id: self._open_iostore_wizard(gid))
            open_btn.pack(anchor="w")
            open_btn.bind("<Enter>", lambda e: open_btn.configure(bg=AppColors.ACCENT_HOVER))
            open_btn.bind("<Leave>", lambda e: open_btn.configure(bg=AppColors.ACCENT))

    def _build_games_page(self):
        page = tk.Frame(self._content_frame, bg=AppColors.BG_DARK)
        self._pages["games"] = page

        header_frame = tk.Frame(page, bg=AppColors.BG_DARK)
        header_frame.pack(fill="x", pady=(0, 10))

        tk.Label(header_frame, text="Game Arabic Translator",
                 font=("Segoe UI", 20, "bold"),
                 bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(side="left")

        add_btn = tk.Button(header_frame, text="+ Add Game",
                            font=("Segoe UI", 10, "bold"),
                            bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY,
                            relief="flat", padx=15, pady=6, cursor="hand2",
                            command=self._add_game_dialog)
        add_btn.pack(side="right")
        add_btn.bind("<Enter>", lambda e: add_btn.configure(bg=AppColors.ACCENT_HOVER))
        add_btn.bind("<Leave>", lambda e: add_btn.configure(bg=AppColors.ACCENT))

        # stats bar
        stats_frame = tk.Frame(page, bg=AppColors.BG_DARK)
        stats_frame.pack(fill="x", pady=(0, 12))

        self._home_stats = {}
        stat_items = [
            ("games_count",       "Games",        "0",    AppColors.ACCENT),
            ("translations_count","Translations", "0",    AppColors.SUCCESS),
            ("model_status",      "Active Model", "None", AppColors.WARNING),
            ("cache_size",        "Cache Entries","0",    "#9b59b6"),
        ]
        for i, (key, label, value, color) in enumerate(stat_items):
            sc = tk.Frame(stats_frame, bg=AppColors.BG_CARD, padx=20, pady=12)
            sc.grid(row=0, column=i, padx=4, sticky="ew")
            stats_frame.grid_columnconfigure(i, weight=1)
            tk.Label(sc, text=value, font=("Segoe UI", 20, "bold"),
                     bg=AppColors.BG_CARD, fg=color).pack(anchor="w")
            tk.Label(sc, text=label, font=("Segoe UI", 9),
                     bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY).pack(anchor="w")
            self._home_stats[key] = sc.winfo_children()[0]

        tk.Label(page, text="My Games", font=("Segoe UI", 14, "bold"),
                 bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 8))

        self._games_list_frame = ScrollableFrame(page)
        self._games_list_frame.pack(fill="both", expand=True)
    
    def _build_translate_page(self):
        page = tk.Frame(self._content_frame, bg=AppColors.BG_DARK)
        self._pages["translate"] = page
        
        tk.Label(page, text="Translate Text", font=("Segoe UI", 18, "bold"), bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 15))
        
        input_frame = tk.Frame(page, bg=AppColors.BG_CARD, padx=20, pady=15)
        input_frame.pack(fill="x", pady=(0, 10))
        
        tk.Label(input_frame, text="English Text:", font=("Segoe UI", 11, "bold"), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w")
        
        self._translate_input = tk.Text(input_frame, height=4, font=("Segoe UI", 12), bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY, insertbackground=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=8, wrap="word")
        self._translate_input.pack(fill="x", pady=(5, 10))
        
        translate_btn = tk.Button(input_frame, text="🌐 Translate", font=("Segoe UI", 11, "bold"), bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=20, pady=8, cursor="hand2", command=self._do_translate)
        translate_btn.pack(anchor="w")
        translate_btn.bind("<Enter>", lambda e: translate_btn.configure(bg=AppColors.ACCENT_HOVER))
        translate_btn.bind("<Leave>", lambda e: translate_btn.configure(bg=AppColors.ACCENT))
        
        output_frame = tk.Frame(page, bg=AppColors.BG_CARD, padx=20, pady=15)
        output_frame.pack(fill="x", pady=(0, 10))
        
        tk.Label(output_frame, text="Arabic Translation:", font=("Segoe UI", 11, "bold"), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w")
        
        self._translate_output = tk.Text(output_frame, height=4, font=("Segoe UI", 12), bg=AppColors.ENTRY_BG, fg=AppColors.SUCCESS, relief="flat", padx=10, pady=8, wrap="word", state="disabled")
        self._translate_output.pack(fill="x", pady=(5, 10))
        
        self._translate_status = tk.Label(page, text="", font=("Segoe UI", 10), bg=AppColors.BG_DARK, fg=AppColors.TEXT_MUTED)
        self._translate_status.pack(anchor="w")

        batch_frame = tk.Frame(page, bg=AppColors.BG_CARD, padx=20, pady=15)
        batch_frame.pack(fill="both", expand=True, pady=(10, 0))
        
        tk.Label(batch_frame, text="Translation Log", font=("Segoe UI", 11, "bold"), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 5))
        
        log_container = tk.Frame(batch_frame, bg=AppColors.ENTRY_BG)
        log_container.pack(fill="both", expand=True)
        
        self._translate_log = tk.Text(log_container, height=8, font=("Consolas", 10), bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_SECONDARY, relief="flat", padx=10, pady=8, wrap="word", state="disabled")
        scrollbar = ttk.Scrollbar(log_container, command=self._translate_log.yview)
        self._translate_log.configure(yscrollcommand=scrollbar.set)
        self._translate_log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
    
    def _build_models_page(self):
        page = tk.Frame(self._content_frame, bg=AppColors.BG_DARK)
        self._pages["models"] = page
        
        tk.Label(page, text="AI Translation Models", font=("Segoe UI", 18, "bold"), bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 5))
        tk.Label(page, text="Select, load, and configure translation models", font=("Segoe UI", 11), bg=AppColors.BG_DARK, fg=AppColors.TEXT_SECONDARY).pack(anchor="w", pady=(0, 15))
        
        prompt_frame = tk.Frame(page, bg=AppColors.BG_CARD, padx=15, pady=12)
        prompt_frame.pack(fill="x", pady=(0, 10))
        
        tk.Label(prompt_frame, text="System Prompt (used by Ollama & Custom models):", font=("Segoe UI", 10, "bold"), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 6))
        
        self._system_prompt_text = tk.Text(prompt_frame, height=4, font=("Segoe UI", 10), bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY, insertbackground=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=6, wrap="word")
        self._system_prompt_text.pack(fill="x", pady=(0, 6))
        self._system_prompt_text.insert("1.0", self._system_prompt)
        
        btn_row = tk.Frame(prompt_frame, bg=AppColors.BG_CARD)
        btn_row.pack(fill="x")
        
        save_prompt_btn = tk.Button(btn_row, text="💾 Save Prompt", font=("Segoe UI", 9), bg=AppColors.SUCCESS, fg="black", relief="flat", padx=12, pady=3, cursor="hand2", command=self._save_system_prompt)
        save_prompt_btn.pack(side="left")
        
        reset_prompt_btn = tk.Button(btn_row, text="↩ Reset", font=("Segoe UI", 9), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=3, cursor="hand2", command=self._reset_system_prompt)
        reset_prompt_btn.pack(side="left", padx=8)
        
        self._models_container = ScrollableFrame(page)
        self._models_container.pack(fill="both", expand=True)
    
    def _build_cache_page(self):
        page = tk.Frame(self._content_frame, bg=AppColors.BG_DARK)
        self._pages["cache"] = page
        
        header = tk.Frame(page, bg=AppColors.BG_DARK)
        header.pack(fill="x", pady=(0, 10))
        
        tk.Label(header, text="Translation Cache", font=("Segoe UI", 18, "bold"), bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(side="left")
        
        self._cache_delete_all_btn = tk.Button(header, text="🗑 Delete ALL",
            font=("Segoe UI", 9), bg=AppColors.ERROR, fg="white",
            relief="flat", padx=12, pady=4, cursor="hand2",
            command=self._cache_delete_all)
        self._cache_delete_all_btn.pack(side="right", padx=5)
        
        selector_frame = tk.Frame(page, bg=AppColors.BG_CARD, padx=15, pady=10)
        selector_frame.pack(fill="x", pady=(0, 5))
        
        row1 = tk.Frame(selector_frame, bg=AppColors.BG_CARD)
        row1.pack(fill="x", pady=(0, 6))
        
        tk.Label(row1, text="Game:", font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY).pack(side="left")
        
        self._cache_game_var = tk.StringVar(value="All Games")
        self._cache_game_combo = ttk.Combobox(row1, textvariable=self._cache_game_var, state="readonly", width=25, font=self._theme.get_font())
        self._cache_game_combo.pack(side="left", padx=8)
        self._cache_game_combo.bind("<<ComboboxSelected>>", lambda e: self._cache_select_game())
        
        tk.Label(row1, text="Model:", font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY).pack(side="left", padx=(15, 0))
        
        self._cache_model_var = tk.StringVar(value="All Models")
        self._cache_model_combo = ttk.Combobox(row1, textvariable=self._cache_model_var, state="readonly", width=20, font=self._theme.get_font())
        self._cache_model_combo.pack(side="left", padx=8)
        self._cache_model_combo.bind("<<ComboboxSelected>>", lambda e: self._cache_select_model())

        self._cache_delete_model_btn = tk.Button(row1, text="🗑 Delete Model",
            font=self._theme.get_small_font(),
            bg="#5a1a1a", fg="#888888",          # disabled: dark red bg, grey text
            activebackground="#c0392b", activeforeground="white",
            disabledforeground="#555555",
            relief="flat", padx=10, pady=3, cursor="hand2",
            state="disabled", command=self._cache_delete_model)
        self._cache_delete_model_btn.pack(side="left", padx=(4, 0))

        tk.Button(row1, text="🧹 Clean Bad",
            font=self._theme.get_small_font(),
            bg="#1a3a5a", fg="#88bbdd",
            activebackground="#2255aa", activeforeground="white",
            relief="flat", padx=10, pady=3, cursor="hand2",
            command=self._cache_clean_bad).pack(side="left", padx=(4, 0))

        row2 = tk.Frame(selector_frame, bg=AppColors.BG_CARD)
        row2.pack(fill="x")
        
        tk.Label(row2, text="Search:", font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY).pack(side="left")
        
        self._cache_search_var = tk.StringVar()
        search_entry = tk.Entry(row2, textvariable=self._cache_search_var, font=self._theme.get_font(), bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY, insertbackground=AppColors.TEXT_PRIMARY, relief="flat", width=30)
        search_entry.pack(side="left", padx=8, ipady=3)
        search_entry.bind("<Return>", lambda e: self._cache_do_search())

        search_btn = tk.Button(row2, text="🔍 Search", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=2, cursor="hand2", command=self._cache_do_search)
        search_btn.pack(side="left", padx=3)
        
        clear_btn = tk.Button(row2, text="✕ Clear", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=8, pady=2, cursor="hand2", command=self._cache_clear_search)
        clear_btn.pack(side="left", padx=3)
        
        self._cache_stats_label = tk.Label(row2, text="", font=self._theme.get_small_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
        self._cache_stats_label.pack(side="right")
        
        
        self._cache_nav_frame = tk.Frame(page, bg=AppColors.BG_DARK)
        self._cache_nav_frame.pack(fill="x", pady=(5, 3))

        self._cache_page_label = tk.Label(self._cache_nav_frame, text="", font=self._theme.get_small_font(), bg=AppColors.BG_DARK, fg=AppColors.TEXT_MUTED)
        self._cache_page_label.pack(side="left")

        self._cache_next_btn = tk.Button(self._cache_nav_frame, text="Next →", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=2, command=lambda: self._cache_change_page(1))
        self._cache_next_btn.pack(side="right", padx=3)

        self._cache_prev_btn = tk.Button(self._cache_nav_frame, text="← Prev", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=2, command=lambda: self._cache_change_page(-1))
        self._cache_prev_btn.pack(side="right", padx=3)

        self._cache_del_btn = tk.Button(self._cache_nav_frame, text="🗑 Delete", font=self._theme.get_small_font(), bg=AppColors.ERROR, fg="white", relief="flat", padx=10, pady=2, cursor="hand2", command=self._cache_delete_selected)
        self._cache_del_btn.pack(side="right", padx=(3, 8))

        self._cache_retrans_btn = tk.Button(self._cache_nav_frame, text="🔄 إعادة ترجمة",
            font=self._theme.get_small_font(),
            bg="#1a3a5a", fg="#88bbdd",
            activebackground="#2255aa", activeforeground="white",
            relief="flat", padx=10, pady=2, cursor="hand2",
            command=self._cache_retranslate_selected)
        self._cache_retrans_btn.pack(side="right", padx=3)

        self._cache_edit_btn = tk.Button(self._cache_nav_frame, text="✏️ Edit", font=self._theme.get_small_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=2, cursor="hand2", command=self._cache_edit_selected)
        self._cache_edit_btn.pack(side="right", padx=3)

        tk.Label(self._cache_nav_frame, text="← double-click row to edit  |  Ctrl+Click for multi-select", font=self._theme.get_small_font(), bg=AppColors.BG_DARK, fg=AppColors.TEXT_MUTED).pack(side="right", padx=8)

        # ── Treeview ─────────────────────────────────────────────────────
        _s = ttk.Style()
        _s.configure("CacheTV.Treeview",
            background=AppColors.BG_CARD,
            foreground=AppColors.TEXT_PRIMARY,
            fieldbackground=AppColors.BG_CARD,
            rowheight=28)
        _s.configure("CacheTV.Treeview.Heading",
            background=AppColors.BG_MEDIUM,
            foreground=AppColors.TEXT_SECONDARY,
            relief="flat")
        _s.map("CacheTV.Treeview",
            background=[("selected", "#2a4070")],
            foreground=[("selected", "white")])

        tree_wrap = tk.Frame(page, bg=AppColors.BG_DARK)
        tree_wrap.pack(fill="both", expand=True)
        tree_wrap.grid_rowconfigure(0, weight=1)
        tree_wrap.grid_columnconfigure(0, weight=1)

        self._cache_tree = ttk.Treeview(tree_wrap,
            columns=("num", "original", "translated", "model"),
            show="headings",
            style="CacheTV.Treeview",
            selectmode="extended")

        self._cache_tree.heading("num",        text="#",       anchor="center")
        self._cache_tree.heading("original",   text="English", anchor="w")
        self._cache_tree.heading("translated", text="Arabic",  anchor="e")
        self._cache_tree.heading("model",      text="Model",   anchor="w")

        # stretch=False → columns keep their dragged widths; horizontal scrollbar handles overflow
        self._cache_tree.column("num",        width=55,  minwidth=40,  stretch=False, anchor="center")
        self._cache_tree.column("original",   width=400, minwidth=120, stretch=False, anchor="w")
        self._cache_tree.column("translated", width=400, minwidth=120, stretch=False, anchor="e")
        self._cache_tree.column("model",      width=130, minwidth=70,  stretch=False, anchor="w")

        tv_vsb = ttk.Scrollbar(tree_wrap, orient="vertical",   command=self._cache_tree.yview)
        tv_hsb = ttk.Scrollbar(tree_wrap, orient="horizontal", command=self._cache_tree.xview)
        self._cache_tree.configure(yscrollcommand=tv_vsb.set, xscrollcommand=tv_hsb.set)

        self._cache_tree.grid(row=0, column=0, sticky="nsew")
        tv_vsb.grid(row=0, column=1, sticky="ns")
        tv_hsb.grid(row=1, column=0, sticky="ew")

        self._cache_tree.tag_configure("odd",  background=AppColors.BG_CARD)
        self._cache_tree.tag_configure("even", background=AppColors.BG_MEDIUM)

        self._cache_tree.bind("<Double-1>",  lambda e: self._cache_edit_selected())
        self._cache_tree.bind("<Button-3>",  self._cache_tree_rclick)
        self._cache_tree.bind("<Delete>",    lambda e: self._cache_delete_selected())

        self._cache_entry_map: dict = {}
        self._cache_current_page = 0
        self._cache_page_size = 50
        self._cache_selected_game = ""
    
    def _build_settings_page(self):
        page = tk.Frame(self._content_frame, bg=AppColors.BG_DARK)
        self._pages["settings"] = page
        
        tk.Label(page, text="Settings", font=self._theme.get_title_font(), bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 15))
        
        scroll = ScrollableFrame(page, bg_color=AppColors.BG_DARK)
        scroll.pack(fill="both", expand=True)
        settings_content = scroll.inner
        
        ui_frame = tk.Frame(settings_content, bg=AppColors.BG_CARD, padx=25, pady=20)
        ui_frame.pack(fill="x", pady=(0, 12))
        
        tk.Label(ui_frame, text="🎨 Appearance", font=self._theme.get_header_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 12))
        
        r = tk.Frame(ui_frame, bg=AppColors.BG_CARD)
        r.pack(fill="x", pady=4)
        tk.Label(r, text="Theme:", font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, width=16, anchor="w").pack(side="left")
        self._setting_theme_var = tk.StringVar(value=self._theme.current_theme)
        theme_combo = ttk.Combobox(r, textvariable=self._setting_theme_var, values=self._theme.get_theme_names(), state="readonly", width=20, font=self._theme.get_font())
        theme_combo.pack(side="left", padx=10)
        
        r = tk.Frame(ui_frame, bg=AppColors.BG_CARD)
        r.pack(fill="x", pady=4)
        tk.Label(r, text="Font Family:", font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, width=16, anchor="w").pack(side="left")
        self._setting_font_var = tk.StringVar(value=self._theme.font_family)
        font_combo = ttk.Combobox(r, textvariable=self._setting_font_var, values=AVAILABLE_FONTS, state="readonly", width=20, font=self._theme.get_font())
        font_combo.pack(side="left", padx=10)
        
        r = tk.Frame(ui_frame, bg=AppColors.BG_CARD)
        r.pack(fill="x", pady=4)
        tk.Label(r, text="Font Size:", font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, width=16, anchor="w").pack(side="left")
        self._setting_size_var = tk.IntVar(value=self._theme.font_size)
        size_spin = tk.Spinbox(r, from_=8, to=24, textvariable=self._setting_size_var, width=5, font=self._theme.get_font(), bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY, insertbackground=AppColors.TEXT_PRIMARY, relief="flat")
        size_spin.pack(side="left", padx=10, ipady=3)
        
        preview_label = tk.Label(ui_frame, text="Aa بب 123 Preview نص تجريبي", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, padx=15, pady=8)
        preview_label.pack(fill="x", pady=(10, 8))
        
        def apply_ui_settings():
            theme_name = self._setting_theme_var.get()
            font_family = self._setting_font_var.get()
            font_size = self._setting_size_var.get()
            
            self._theme.set_theme(theme_name)
            self._theme.set_font(font_family, font_size)
            self._C = self._theme.get_colors()
            AppColors.update(self._C)
            self._rebuild_ui()
            self._set_status(f"Theme: {theme_name} | Font: {font_family} {font_size}pt")
        
        apply_btn = tk.Button(ui_frame, text="💾 Apply Appearance", font=self._theme.get_font(style="bold"), bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=20, pady=6, cursor="hand2", command=apply_ui_settings)
        apply_btn.pack(anchor="w", pady=(5, 0))
        apply_btn.bind("<Enter>", lambda e: apply_btn.configure(bg=AppColors.ACCENT_HOVER))
        apply_btn.bind("<Leave>", lambda e: apply_btn.configure(bg=AppColors.ACCENT))
        
        trans_frame = tk.Frame(settings_content, bg=AppColors.BG_CARD, padx=25, pady=20)
        trans_frame.pack(fill="x", pady=(0, 12))
        
        tk.Label(trans_frame, text="🌐 Translation", font=self._theme.get_header_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 12))
        
        r = tk.Frame(trans_frame, bg=AppColors.BG_CARD)
        r.pack(fill="x", pady=4)
        tk.Label(r, text="Source Language:", font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, width=16, anchor="w").pack(side="left")
        self._setting_src_lang = tk.Entry(r, font=self._theme.get_font(), bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY, insertbackground=AppColors.TEXT_PRIMARY, relief="flat", width=20)
        self._setting_src_lang.pack(side="left", padx=10, ipady=4)
        self._setting_src_lang.insert(0, "en")
        
        r = tk.Frame(trans_frame, bg=AppColors.BG_CARD)
        r.pack(fill="x", pady=4)
        tk.Label(r, text="Target Language:", font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, width=16, anchor="w").pack(side="left")
        self._setting_tgt_lang = tk.Entry(r, font=self._theme.get_font(), bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY, insertbackground=AppColors.TEXT_PRIMARY, relief="flat", width=20)
        self._setting_tgt_lang.pack(side="left", padx=10, ipady=4)
        self._setting_tgt_lang.insert(0, "ar")
        
        deepl_frame = tk.Frame(settings_content, bg=AppColors.BG_CARD, padx=25, pady=20)
        deepl_frame.pack(fill="x", pady=(0, 12))
        
        tk.Label(deepl_frame, text="🔑 DeepL API", font=self._theme.get_header_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 12))
        
        tk.Label(deepl_frame, text="Get free API key at: deepl.com/pro-api", font=self._theme.get_small_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED).pack(anchor="w", pady=(0, 8))
        
        r = tk.Frame(deepl_frame, bg=AppColors.BG_CARD)
        r.pack(fill="x", pady=4)
        tk.Label(r, text="API Key:", font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, width=16, anchor="w").pack(side="left")
        self._setting_deepl_key = tk.Entry(r, font=self._theme.get_font(), bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY, insertbackground=AppColors.TEXT_PRIMARY, relief="flat", width=40, show="*")
        self._setting_deepl_key.pack(side="left", padx=10, ipady=4)
        
        def save_deepl_key():
            key = self._setting_deepl_key.get().strip()
            if key and self._translation_engine:
                deepl = self._translation_engine.get_translator("deepl")
                if deepl and hasattr(deepl, 'set_api_key'):
                    deepl.set_api_key(key)
                    self._config.setdefault("models", {}).setdefault("deepl", {})["api_key"] = key
                    self._set_status("DeepL API key saved")
        
        tk.Button(r, text="Save", font=self._theme.get_small_font(), bg=AppColors.SUCCESS, fg="black", relief="flat", padx=8, pady=2, command=save_deepl_key).pack(side="left", padx=5)
        
        ue4_frame = tk.Frame(settings_content, bg=AppColors.BG_CARD, padx=25, pady=20)
        ue4_frame.pack(fill="x", pady=(0, 12))

        tk.Label(ue4_frame, text="🔧 UE4 Tools", font=self._theme.get_header_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        tk.Label(ue4_frame, text="Required for packing .pak files after translating Myth of Empires (and other UE4 games).", font=self._theme.get_small_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED).pack(anchor="w", pady=(0, 10))

        r = tk.Frame(ue4_frame, bg=AppColors.BG_CARD)
        r.pack(fill="x", pady=4)
        tk.Label(r, text="UnrealPak.exe:", font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, width=16, anchor="w").pack(side="left")
        self._setting_unrealpak_var = tk.StringVar(value=self._config.get("tools", {}).get("unrealpak_path", ""))
        unrealpak_entry = tk.Entry(r, textvariable=self._setting_unrealpak_var, font=self._theme.get_font(), bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY, insertbackground=AppColors.TEXT_PRIMARY, relief="flat", width=45)
        unrealpak_entry.pack(side="left", padx=10, ipady=4, fill="x", expand=True)

        def browse_unrealpak():
            path = filedialog.askopenfilename(
                title="Select UnrealPak.exe",
                filetypes=[("UnrealPak executable", "UnrealPak.exe"), ("Executable", "*.exe"), ("All files", "*.*")]
            )
            if path:
                self._setting_unrealpak_var.set(path)
                self._config.setdefault("tools", {})["unrealpak_path"] = path
                self._save_config()
                self._set_status(f"UnrealPak: {os.path.basename(path)}")

        tk.Button(r, text="Browse", font=self._theme.get_small_font(), bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=2, cursor="hand2", command=browse_unrealpak).pack(side="left", padx=3)

        def save_unrealpak():
            path = self._setting_unrealpak_var.get().strip()
            self._config.setdefault("tools", {})["unrealpak_path"] = path
            self._save_config()
            self._set_status("UnrealPak path saved" if path else "UnrealPak path cleared")

        tk.Button(r, text="Save", font=self._theme.get_small_font(), bg=AppColors.SUCCESS, fg="black", relief="flat", padx=8, pady=2, cursor="hand2", command=save_unrealpak).pack(side="left", padx=3)

        iostore_frame = tk.Frame(settings_content, bg=AppColors.BG_CARD, padx=25, pady=20)
        iostore_frame.pack(fill="x", pady=(0, 12))

        tk.Label(iostore_frame, text="📦 IoStore Tools (UE5)", font=self._theme.get_header_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        tk.Label(iostore_frame,
                 text="Required for IoStore (.utoc/.ucas) ↔ UAsset translation workflow.",
                 font=self._theme.get_small_font(), bg=AppColors.BG_CARD,
                 fg=AppColors.TEXT_MUTED).pack(anchor="w", pady=(0, 10))

        r = tk.Frame(iostore_frame, bg=AppColors.BG_CARD)
        r.pack(fill="x", pady=4)
        tk.Label(r, text="retoc.exe:", font=self._theme.get_font(), bg=AppColors.BG_CARD,
                 fg=AppColors.TEXT_SECONDARY, width=16, anchor="w").pack(side="left")
        self._setting_retoc_var = tk.StringVar(
            value=self._config.get("tools", {}).get("retoc_path", ""))
        retoc_entry = tk.Entry(r, textvariable=self._setting_retoc_var,
                               font=self._theme.get_font(), bg=AppColors.ENTRY_BG,
                               fg=AppColors.TEXT_PRIMARY, insertbackground=AppColors.TEXT_PRIMARY,
                               relief="flat", width=45)
        retoc_entry.pack(side="left", padx=10, ipady=4, fill="x", expand=True)

        def browse_retoc():
            path = filedialog.askopenfilename(
                title="Select retoc.exe",
                filetypes=[("retoc executable", "retoc.exe"), ("Executable", "*.exe"), ("All", "*.*")])
            if path:
                self._setting_retoc_var.set(path)
                self._config.setdefault("tools", {})["retoc_path"] = path
                self._save_config()

        def save_retoc():
            path = self._setting_retoc_var.get().strip()
            self._config.setdefault("tools", {})["retoc_path"] = path
            self._save_config()
            self._set_status("retoc path saved" if path else "retoc path cleared")

        tk.Button(r, text="Browse", font=self._theme.get_small_font(), bg=AppColors.ACCENT,
                  fg=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=2,
                  cursor="hand2", command=browse_retoc).pack(side="left", padx=3)
        tk.Button(r, text="Save", font=self._theme.get_small_font(), bg=AppColors.SUCCESS,
                  fg="black", relief="flat", padx=8, pady=2,
                  cursor="hand2", command=save_retoc).pack(side="left", padx=3)

        r2 = tk.Frame(iostore_frame, bg=AppColors.BG_CARD)
        r2.pack(fill="x", pady=4)
        tk.Label(r2, text="UAssetGUI.exe:", font=self._theme.get_font(), bg=AppColors.BG_CARD,
                 fg=AppColors.TEXT_SECONDARY, width=16, anchor="w").pack(side="left")
        self._setting_uassetgui_var = tk.StringVar(
            value=self._config.get("tools", {}).get("uassetgui_path", ""))
        uassetgui_entry = tk.Entry(r2, textvariable=self._setting_uassetgui_var,
                                   font=self._theme.get_font(), bg=AppColors.ENTRY_BG,
                                   fg=AppColors.TEXT_PRIMARY, insertbackground=AppColors.TEXT_PRIMARY,
                                   relief="flat", width=45)
        uassetgui_entry.pack(side="left", padx=10, ipady=4, fill="x", expand=True)

        def browse_uassetgui():
            path = filedialog.askopenfilename(
                title="Select UAssetGUI.exe",
                filetypes=[("UAssetGUI executable", "UAssetGUI.exe"), ("Executable", "*.exe"), ("All", "*.*")])
            if path:
                self._setting_uassetgui_var.set(path)
                self._config.setdefault("tools", {})["uassetgui_path"] = path
                self._save_config()

        def save_uassetgui():
            path = self._setting_uassetgui_var.get().strip()
            self._config.setdefault("tools", {})["uassetgui_path"] = path
            self._save_config()
            self._set_status("UAssetGUI path saved" if path else "UAssetGUI path cleared")

        tk.Button(r2, text="Browse", font=self._theme.get_small_font(), bg=AppColors.ACCENT,
                  fg=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=2,
                  cursor="hand2", command=browse_uassetgui).pack(side="left", padx=3)
        tk.Button(r2, text="Save", font=self._theme.get_small_font(), bg=AppColors.SUCCESS,
                  fg="black", relief="flat", padx=8, pady=2,
                  cursor="hand2", command=save_uassetgui).pack(side="left", padx=3)

        frida_frame = tk.Frame(settings_content, bg=AppColors.BG_CARD, padx=25, pady=20)
        frida_frame.pack(fill="x", pady=(0, 12))

        tk.Label(frida_frame, text="💉 Frida", font=self._theme.get_header_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 12))
        
        self._setting_frida_enabled = tk.BooleanVar(value=True)
        cb = tk.Checkbutton(frida_frame, text="Enable Frida runtime injection", font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, selectcolor=AppColors.ENTRY_BG, activebackground=AppColors.BG_CARD, activeforeground=AppColors.TEXT_PRIMARY, variable=self._setting_frida_enabled)
        cb.pack(anchor="w")
        
        about_frame = tk.Frame(settings_content, bg=AppColors.BG_CARD, padx=25, pady=20)
        about_frame.pack(fill="x", pady=(0, 12))
        
        tk.Label(about_frame, text="ℹ️ About", font=self._theme.get_header_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 10))
        
        about_text = "Game Arabic Translator v1.0\nOpen-source game translation tool\nSupports: Frida injection, BepInEx, UE4/5\nThemes: Dark, Light, Sunset, Ocean, Forest, Purple"
        tk.Label(about_frame, text=about_text, font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, justify="left").pack(anchor="w")
    
    def _rebuild_ui(self):
        for widget in self.root.winfo_children():
            widget.destroy()
        
        self._C = self._theme.get_colors()
        AppColors.update(self._C)
        self.root.configure(bg=self._C["BG_DARK"])
        
        self._build_ui()
        
        if self._game_manager:
            self._refresh_home_stats()
            self._load_game_images()
            self._refresh_home_games()
    
    def _build_status_bar(self):
        self._status_bar = tk.Frame(self.root, bg=AppColors.BG_MEDIUM, height=28)
        self._status_bar.pack(side="bottom", fill="x")
        self._status_bar.pack_propagate(False)
        
        self._status_text = tk.Label(self._status_bar, text="Ready", font=("Segoe UI", 9), bg=AppColors.BG_MEDIUM, fg=AppColors.TEXT_MUTED, anchor="w", padx=10)
        self._status_text.pack(side="left", fill="x", expand=True)
        
        self._status_right = tk.Label(self._status_bar, text="Game Arabic Translator v1.0", font=("Segoe UI", 9), bg=AppColors.BG_MEDIUM, fg=AppColors.TEXT_MUTED, anchor="e", padx=10)
        self._status_right.pack(side="right")
    
    def _navigate(self, page_key, command):
        for key, btn in self._nav_buttons.items():
            if key == page_key:
                btn.configure(bg=AppColors.SIDEBAR_ACTIVE, fg=AppColors.TEXT_PRIMARY)
            else:
                btn.configure(bg=AppColors.SIDEBAR_BG, fg=AppColors.TEXT_SECONDARY)
        
        self._current_page = page_key
        command()
    
    def _show_page(self, page_key):
        for key, page in self._pages.items():
            page.pack_forget()
        
        if page_key in self._pages:
            self._pages[page_key].pack(fill="both", expand=True)
    
    def _show_home(self):
        self._show_page("home")
        self._refresh_home_stats()
        self._refresh_home_games()
    
    def _show_games(self):
        self._show_page("games")
        self._refresh_home_stats()
        self._refresh_games_list()
    
    def _show_translate(self):
        self._show_page("translate")
    
    def _show_models(self):
        self._show_page("models")
        self._refresh_models_list()
    
    def _show_cache(self):
        self._show_page("cache")
        self._refresh_cache_view()
    
    def _show_settings(self):
        self._show_page("settings")
    
    def _init_backend(self):
        def init_thread():
            try:
                sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
                
                from engine.translator import TranslationEngine
                from engine.cache import TranslationCache
                from games.game_manager import GameManager
                
                self._translation_engine = TranslationEngine(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json"))
                self._cache = TranslationCache(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cache", "translations.db"))
                self._game_manager = GameManager(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "games", "configs"))
                
                # Sync saved system prompt to ollama/custom translators
                for _key in ("ollama", "custom_endpoint"):
                    _t = self._translation_engine.get_translator(_key)
                    if _t and hasattr(_t, "system_prompt"):
                        _t.system_prompt = self._system_prompt

                self._safe_after(0, lambda: self._set_status("Backend initialized successfully"))
                self._safe_after(100, self._refresh_home_stats)
                self._safe_after(200, self._load_game_images)
                self._safe_after(300, self._refresh_home_games)
                self._safe_after(400, self._refresh_games_list)
            except Exception as e:
                self._safe_after(0, lambda: self._set_status(f"Backend init error: {e}"))
        
        threading.Thread(target=init_thread, daemon=True).start()
    
    def _display_arabic(self, text):
        if not text:
            return text
        
        import re
        if not re.search(r'[\u0600-\u06FF\uFE70-\uFEFF]', text):
            return text
        
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display
            
            has_presentation = any(0xFE70 <= ord(c) <= 0xFEFF for c in text[:20])
            
            if has_presentation:
                normal = self._presentation_to_normal(text)
                reshaped = arabic_reshaper.reshape(normal)
            else:
                reshaped = arabic_reshaper.reshape(text)
            
            return get_display(reshaped)
        except:
            return text
    
    def _presentation_to_normal(self, text):
        MAPPING = {
            0xFE8D: 0x0627, 0xFE8E: 0x0627, 0xFE8F: 0x0628, 0xFE90: 0x0628,
            0xFE91: 0x0628, 0xFE92: 0x0628, 0xFE93: 0x0629, 0xFE94: 0x0629,
            0xFE95: 0x062A, 0xFE96: 0x062A, 0xFE97: 0x062A, 0xFE98: 0x062A,
            0xFE99: 0x062B, 0xFE9A: 0x062B, 0xFE9B: 0x062B, 0xFE9C: 0x062B,
            0xFE9D: 0x062C, 0xFE9E: 0x062C, 0xFE9F: 0x062C, 0xFEA0: 0x062C,
            0xFEA1: 0x062D, 0xFEA2: 0x062D, 0xFEA3: 0x062D, 0xFEA4: 0x062D,
            0xFEA5: 0x062E, 0xFEA6: 0x062E, 0xFEA7: 0x062E, 0xFEA8: 0x062E,
            0xFEA9: 0x062F, 0xFEAA: 0x062F, 0xFEAB: 0x0630, 0xFEAC: 0x0630,
            0xFEAD: 0x0631, 0xFEAE: 0x0631, 0xFEAF: 0x0632, 0xFEB0: 0x0632,
            0xFEB1: 0x0633, 0xFEB2: 0x0633, 0xFEB3: 0x0633, 0xFEB4: 0x0633,
            0xFEB5: 0x0634, 0xFEB6: 0x0634, 0xFEB7: 0x0634, 0xFEB8: 0x0634,
            0xFEB9: 0x0635, 0xFEBA: 0x0635, 0xFEBB: 0x0635, 0xFEBC: 0x0635,
            0xFEBD: 0x0636, 0xFEBE: 0x0636, 0xFEBF: 0x0636, 0xFEC0: 0x0636,
            0xFEC1: 0x0637, 0xFEC2: 0x0637, 0xFEC3: 0x0637, 0xFEC4: 0x0637,
            0xFEC5: 0x0638, 0xFEC6: 0x0638, 0xFEC7: 0x0638, 0xFEC8: 0x0638,
            0xFEC9: 0x0639, 0xFECA: 0x0639, 0xFECB: 0x0639, 0xFECC: 0x0639,
            0xFECD: 0x063A, 0xFECE: 0x063A, 0xFECF: 0x063A, 0xFED0: 0x063A,
            0xFED1: 0x0641, 0xFED2: 0x0641, 0xFED3: 0x0641, 0xFED4: 0x0641,
            0xFED5: 0x0642, 0xFED6: 0x0642, 0xFED7: 0x0642, 0xFED8: 0x0642,
            0xFED9: 0x0643, 0xFEDA: 0x0643, 0xFEDB: 0x0643, 0xFEDC: 0x0643,
            0xFEDD: 0x0644, 0xFEDE: 0x0644, 0xFEDF: 0x0644, 0xFEE0: 0x0644,
            0xFEE1: 0x0645, 0xFEE2: 0x0645, 0xFEE3: 0x0645, 0xFEE4: 0x0645,
            0xFEE5: 0x0646, 0xFEE6: 0x0646, 0xFEE7: 0x0646, 0xFEE8: 0x0646,
            0xFEE9: 0x0647, 0xFEEA: 0x0647, 0xFEEB: 0x0647, 0xFEEC: 0x0647,
            0xFEED: 0x0648, 0xFEEE: 0x0648, 0xFEEF: 0x0649, 0xFEF0: 0x0649,
            0xFEF1: 0x064A, 0xFEF2: 0x064A, 0xFEF3: 0x064A, 0xFEF4: 0x064A,
        }
        result = []
        for c in text:
            code = ord(c)
            if code in MAPPING:
                result.append(chr(MAPPING[code]))
            else:
                result.append(c)
        return ''.join(result)
    
    def _set_status(self, text):
        try:
            self._status_text.configure(text=text)
        except:
            pass
    
    def _safe_after(self, ms, func):
        try:
            self.root.after(ms, func)
        except RuntimeError:
            pass
    
    def _update_model_indicator(self, model_name=None):
        if model_name:
            self._model_indicator.configure(text=f"🟢 {model_name}", fg=AppColors.SUCCESS)
        else:
            self._model_indicator.configure(text="🔴 No model loaded", fg=AppColors.ERROR)
    
    def _refresh_home_stats(self):
        if self._game_manager:
            games = self._game_manager.get_game_list()
            self._home_stats["games_count"].configure(text=str(len(games)))
        
        if self._cache:
            all_games = self._cache.get_all_games()
            total = 0
            for g in all_games:
                stats = self._cache.get_stats(g)
                total += stats.get("total_translations", 0)
            self._home_stats["translations_count"].configure(text=str(total))
            self._home_stats["cache_size"].configure(text=str(len(all_games)))
        
        if self._translation_engine:
            active = self._translation_engine.get_active_model()
            self._home_stats["model_status"].configure(text=active or "None")
    
    def _refresh_games_list(self):
        for widget in self._games_list_frame.inner.winfo_children():
            widget.destroy()

        if not self._game_manager:
            tk.Label(self._games_list_frame.inner, text="Loading...",
                     font=("Segoe UI", 11), bg=AppColors.BG_DARK,
                     fg=AppColors.TEXT_MUTED).pack(pady=20)
            return

        games = self._game_manager.get_game_list()
        if not games:
            empty = tk.Frame(self._games_list_frame.inner, bg=AppColors.BG_CARD, padx=30, pady=40)
            empty.pack(fill="x", pady=10)
            tk.Label(empty, text="No games added yet", font=("Segoe UI", 14),
                     bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED).pack()
            tk.Label(empty, text="Click '+ Add Game' to add your first game",
                     font=("Segoe UI", 11), bg=AppColors.BG_CARD,
                     fg=AppColors.TEXT_MUTED).pack(pady=(5, 0))
            return

        from games.translation_package import TranslationPackage
        pkg = TranslationPackage()

        grid_frame = tk.Frame(self._games_list_frame.inner, bg=AppColors.BG_DARK)
        grid_frame.pack(fill="x", padx=5)

        cols = 4
        for i, game in enumerate(games):
            row, col = divmod(i, cols)
            game_id = game["id"]

            card = tk.Frame(grid_frame, bg=AppColors.BG_CARD, padx=8, pady=8, cursor="hand2")
            card.grid(row=row, column=col, padx=6, pady=6, sticky="ew")
            grid_frame.grid_columnconfigure(col, weight=1)

            img_frame = tk.Frame(card, bg=AppColors.BG_LIGHT, height=100, width=160)
            img_frame.pack(fill="x", pady=(0, 6))
            img_frame.pack_propagate(False)
            if game_id in self._game_images:
                try:
                    tk.Label(img_frame, image=self._game_images[game_id],
                             bg=AppColors.BG_LIGHT).pack(fill="both", expand=True)
                except:
                    tk.Label(img_frame, text="🎮", font=("Segoe UI", 28),
                             bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_MUTED).pack(expand=True)
            else:
                tk.Label(img_frame, text="🎮", font=("Segoe UI", 28),
                         bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_MUTED).pack(expand=True)

            name_lbl = tk.Label(card, text=game["name"], font=("Segoe UI", 10, "bold"),
                                bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY, wraplength=150)
            name_lbl.pack(anchor="w")

            engine_lbl = tk.Label(card, text=game.get("engine", "auto"),
                                  font=("Segoe UI", 8),
                                  bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
            engine_lbl.pack(anchor="w")

            # ready badge
            if pkg.has_files(game_id):
                tk.Label(card, text="📦 جاهز للتعريب", font=("Segoe UI", 7, "bold"),
                         bg=AppColors.BG_CARD, fg=AppColors.SUCCESS).pack(anchor="w")

            img_btn = tk.Label(card, text="📷 Change Image", font=("Segoe UI", 7),
                               bg=AppColors.BG_CARD, fg=AppColors.ACCENT, cursor="hand2")
            img_btn.pack(anchor="e", pady=(3, 0))

            for widget in [card, img_frame, name_lbl, engine_lbl]:
                widget.bind("<Button-1>", lambda e, g=game: self._show_game_detail(g["id"]))
            img_btn.bind("<Button-1>", lambda e, gid=game_id: (self._set_game_image(gid), "break"))

            def _enter(e, c=card): c.configure(bg=AppColors.BG_LIGHT)
            def _leave(e, c=card): c.configure(bg=AppColors.BG_CARD)
            card.bind("<Enter>", _enter)
            card.bind("<Leave>", _leave)
    
    def _add_game_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Add New Game")
        dialog.geometry("450x400")
        dialog.configure(bg=AppColors.BG_DARK)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        
        x = self.root.winfo_x() + (self.root.winfo_width() - 450) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 400) // 2
        dialog.geometry(f"+{x}+{y}")
        
        tk.Label(dialog, text="Add New Game", font=("Segoe UI", 16, "bold"), bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(pady=(20, 15))
        
        form_frame = tk.Frame(dialog, bg=AppColors.BG_DARK, padx=30)
        form_frame.pack(fill="both", expand=True)
        
        fields = {}
        field_defs = [
            ("game_id", "Game ID:", "e.g., MyGame"),
            ("process_name", "Process Name:", "e.g., MyGame.exe"),
            ("game_path", "Game Path:", ""),
            ("engine", "Engine:", "auto / unity / unreal"),
        ]
        
        for key, label, placeholder in field_defs:
            row = tk.Frame(form_frame, bg=AppColors.BG_DARK)
            row.pack(fill="x", pady=5)
            tk.Label(row, text=label, font=("Segoe UI", 10), bg=AppColors.BG_DARK, fg=AppColors.TEXT_SECONDARY, width=14, anchor="w").pack(side="left")
            entry = tk.Entry(row, font=("Segoe UI", 10), bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY, insertbackground=AppColors.TEXT_PRIMARY, relief="flat")
            entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(5, 0))
            entry.insert(0, placeholder)
            fields[key] = entry
        
        def browse_path():
            path = filedialog.askdirectory(title="Select Game Directory")
            if path:
                fields["game_path"].delete(0, tk.END)
                fields["game_path"].insert(0, path)
                
                exe_files = [f for f in os.listdir(path) if f.endswith(".exe")]
                if exe_files and not fields["process_name"].get() or fields["process_name"].get() == "e.g., MyGame.exe":
                    fields["process_name"].delete(0, tk.END)
                    fields["process_name"].insert(0, exe_files[0])
        
        browse_btn = tk.Button(form_frame, text="Browse...", font=("Segoe UI", 9), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=3, command=browse_path)
        browse_btn.pack(anchor="e", pady=(2, 10))
        
        def save_game():
            game_id = fields["game_id"].get().strip()
            if not game_id or game_id == "e.g., MyGame":
                messagebox.showwarning("Warning", "Please enter a Game ID")
                return
            
            config = {
                "process_name": fields["process_name"].get().strip() if fields["process_name"].get().strip() != "e.g., MyGame.exe" else "",
                "game_path": fields["game_path"].get().strip(),
                "engine": fields["engine"].get().strip() if fields["engine"].get().strip() != "auto / unity / unreal" else "auto",
            }
            
            if self._game_manager:
                success = self._game_manager.add_game(game_id, config)
                if success:
                    dialog.destroy()
                    self._refresh_games_list()
                    self._set_status(f"Game '{game_id}' added successfully")
                else:
                    messagebox.showerror("Error", "Failed to save game configuration")
        
        save_btn = tk.Button(form_frame, text="💾 Save Game", font=("Segoe UI", 11, "bold"), bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=20, pady=8, command=save_game)
        save_btn.pack(pady=(10, 0))
    
    def _delete_game(self, game_id):
        if messagebox.askyesno("Confirm", f"Delete game '{game_id}'?"):
            if self._game_manager:
                self._game_manager.delete_game(game_id)
                self._refresh_games_list()
                self._set_status(f"Game '{game_id}' deleted")
    
    def _edit_game_dialog(self, game_id):
        game_config = self._game_manager.get_game(game_id) if self._game_manager else None
        if not game_config:
            return
        
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit: {game_id}")
        dialog.geometry("500x350")
        dialog.configure(bg=AppColors.BG_DARK)
        dialog.transient(self.root)
        dialog.grab_set()
        
        x = self.root.winfo_x() + (self.root.winfo_width() - 500) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 350) // 2
        dialog.geometry(f"+{x}+{y}")
        
        tk.Label(dialog, text=f"Edit: {game_id}", font=self._theme.get_header_font(), bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(pady=(15, 10))
        
        form = tk.Frame(dialog, bg=AppColors.BG_DARK, padx=30)
        form.pack(fill="both", expand=True)
        
        fields = {}
        field_defs = [
            ("process_name", "Process Name:", game_config.get("process_name", "")),
            ("game_path", "Game Path:", game_config.get("game_path", "")),
            ("engine", "Engine:", game_config.get("engine", "auto")),
        ]
        
        for key, label, default in field_defs:
            row = tk.Frame(form, bg=AppColors.BG_DARK)
            row.pack(fill="x", pady=5)
            tk.Label(row, text=label, font=self._theme.get_font(), bg=AppColors.BG_DARK, fg=AppColors.TEXT_SECONDARY, width=14, anchor="w").pack(side="left")
            entry = tk.Entry(row, font=self._theme.get_font(), bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY, insertbackground=AppColors.TEXT_PRIMARY, relief="flat")
            entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(5, 0))
            entry.insert(0, default)
            fields[key] = entry
        
        def save():
            updates = {}
            for key, entry in fields.items():
                val = entry.get().strip()
                if val != game_config.get(key, ""):
                    updates[key] = val
            
            if updates and self._game_manager:
                self._game_manager.update_game(game_id, updates)
                dialog.destroy()
                self._show_game_detail(game_id)
                self._set_status(f"Game '{game_id}' updated")
        
        btn_frame = tk.Frame(form, bg=AppColors.BG_DARK)
        btn_frame.pack(fill="x", pady=(15, 0))
        tk.Button(btn_frame, text="💾 Save", font=self._theme.get_font(), bg=AppColors.SUCCESS, fg="black", relief="flat", padx=15, pady=4, command=save).pack(side="left")
        tk.Button(btn_frame, text="Cancel", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=15, pady=4, command=dialog.destroy).pack(side="left", padx=10)
    
    def _patch_game_fonts(self, game):
        game_id = game.get("id", "")
        game_config = None
        if self._game_manager:
            game_config = self._game_manager.get_game(game_id)
        
        if not game_config:
            messagebox.showwarning("Warning", "Game configuration not found")
            return
        
        game_path = game_config.get("game_path", "")
        if not game_path:
            messagebox.showwarning("Warning", "Game path not configured")
            return
        
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Font Patcher: {game['name']}")
        dialog.geometry("500x350")
        dialog.configure(bg=AppColors.BG_DARK)
        dialog.transient(self.root)
        dialog.grab_set()
        
        x = self.root.winfo_x() + (self.root.winfo_width() - 500) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 350) // 2
        dialog.geometry(f"+{x}+{y}")
        
        tk.Label(dialog, text="🔤 Font Patcher", font=("Segoe UI", 16, "bold"), bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(pady=(15, 5))
        tk.Label(dialog, text="Replaces game fonts with Arabic-compatible fonts", font=("Segoe UI", 10), bg=AppColors.BG_DARK, fg=AppColors.TEXT_SECONDARY).pack(pady=(0, 15))
        
        log_frame = tk.Frame(dialog, bg=AppColors.ENTRY_BG)
        log_frame.pack(fill="both", expand=True, padx=15, pady=5)
        
        font_log = tk.Text(log_frame, height=8, font=("Consolas", 9), bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_SECONDARY, relief="flat", padx=8, pady=5, wrap="word", state="disabled")
        scrollbar = ttk.Scrollbar(log_frame, command=font_log.yview)
        font_log.configure(yscrollcommand=scrollbar.set)
        font_log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        btn_frame = tk.Frame(dialog, bg=AppColors.BG_DARK)
        btn_frame.pack(fill="x", padx=15, pady=(10, 15))
        
        def log_to_dialog(msg):
            if font_log.winfo_exists():
                font_log.configure(state="normal")
                font_log.insert("end", msg + "\n")
                font_log.see("end")
                font_log.configure(state="disabled")
        
        def do_patch():
            from games.ror2.font_patcher import RoR2FontPatcher
            patcher = RoR2FontPatcher(game_path)
            success = patcher.patch_fonts(log_callback=log_to_dialog)
            if success:
                messagebox.showinfo("Success", "Fonts patched! Restart the game to apply.")
                self._set_status("Fonts patched successfully")
            else:
                messagebox.showerror("Error", "Font patching failed. Check the log.")
        
        def do_restore():
            from games.ror2.font_patcher import RoR2FontPatcher
            patcher = RoR2FontPatcher(game_path)
            if patcher.has_backups():
                patcher.restore_backups(log_callback=log_to_dialog)
                messagebox.showinfo("Restored", "Original fonts restored! Restart the game.")
            else:
                messagebox.showinfo("Info", "No backups found to restore.")
        
        patch_btn = tk.Button(btn_frame, text="🔤 Patch Fonts", font=("Segoe UI", 10, "bold"), bg="#e67e22", fg="white", relief="flat", padx=15, pady=5, command=lambda: threading.Thread(target=do_patch, daemon=True).start())
        patch_btn.pack(side="left", padx=5)
        
        restore_btn = tk.Button(btn_frame, text="↩️ Restore Original", font=("Segoe UI", 10), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=15, pady=5, command=lambda: threading.Thread(target=do_restore, daemon=True).start())
        restore_btn.pack(side="left", padx=5)
        
        close_btn = tk.Button(btn_frame, text="Close", font=("Segoe UI", 10), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=15, pady=5, command=dialog.destroy)
        close_btn.pack(side="right")
    
    def _translate_game(self, game):
        game_id = game.get("id", "")
        game_name = game.get("name", game_id)
        game_config = None
        if self._game_manager:
            game_config = self._game_manager.get_game(game_id)
        
        if not game_config:
            messagebox.showwarning("Warning", "Game configuration not found")
            return
        
        game_path = game_config.get("game_path", "")
        if not game_path:
            messagebox.showwarning("Warning", "Game path not configured.\nEdit the game and set the path first.")
            return
        
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Translate: {game_name}")
        dialog.geometry("650x580")
        dialog.configure(bg=AppColors.BG_DARK)
        dialog.transient(self.root)

        x = self.root.winfo_x() + (self.root.winfo_width() - 650) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 580) // 2
        dialog.geometry(f"+{x}+{y}")
        
        tk.Label(dialog, text=f"🌐 Translate: {game_name}", font=("Segoe UI", 16, "bold"), bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(pady=(15, 5))
        
        model_frame = tk.Frame(dialog, bg=AppColors.BG_CARD, padx=15, pady=12)
        model_frame.pack(fill="x", padx=15, pady=(5, 5))
        
        tk.Label(model_frame, text="نموذج الترجمة:", font=("Segoe UI", 10, "bold"), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 6))
        
        model_row = tk.Frame(model_frame, bg=AppColors.BG_CARD)
        model_row.pack(fill="x")
        
        available_models = []
        if self._translation_engine:
            for m in self._translation_engine.get_available_models():
                available_models.append(m["key"])
        
        dialog_model_var = tk.StringVar(value=self._translation_engine.get_active_model() if self._translation_engine else "")
        model_combo = ttk.Combobox(model_row, textvariable=dialog_model_var, values=available_models, state="readonly", width=25, font=("Segoe UI", 10))
        model_combo.pack(side="left")
        
        cached_models = []
        if self._cache:
            cached_models = self._cache.get_models_for_game(game_name)
        
        if cached_models:
            tk.Label(model_row, text="  or use cached from:", font=("Segoe UI", 9), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY).pack(side="left", padx=(15, 5))
            cached_var = tk.StringVar()
            cached_combo = ttk.Combobox(model_row, textvariable=cached_var, values=cached_models, state="readonly", width=20, font=("Segoe UI", 9))
            cached_combo.pack(side="left")
        
        mode_frame = tk.Frame(model_frame, bg=AppColors.BG_CARD)
        mode_frame.pack(fill="x", pady=(10, 0))
        
        mode_var = tk.StringVar(value="fresh")
        
        tk.Radiobutton(mode_frame, text="🆕 ترجمة من الصفر (حذف القديم وإعادة الترجمة)", variable=mode_var, value="fresh", font=("Segoe UI", 9), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, selectcolor=AppColors.ENTRY_BG, activebackground=AppColors.BG_CARD).pack(anchor="w")
        tk.Radiobutton(mode_frame, text="📦 استخدام الكاش فقط (بدون استدعاءات API جديدة)", variable=mode_var, value="cache_only", font=("Segoe UI", 9), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, selectcolor=AppColors.ENTRY_BG, activebackground=AppColors.BG_CARD).pack(anchor="w")
        tk.Radiobutton(mode_frame, text="🔄 استكمال المفقود (الاحتفاظ بالموجود وترجمة الجديد)", variable=mode_var, value="missing", font=("Segoe UI", 9), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, selectcolor=AppColors.ENTRY_BG, activebackground=AppColors.BG_CARD).pack(anchor="w")

        options_frame = tk.Frame(model_frame, bg=AppColors.BG_CARD)
        options_frame.pack(fill="x", pady=(8, 0))

        # Reshaping ON by default for Unity games, OFF for locres-based games (UE4/locres handle Arabic natively)
        _game_id_lower = game_id.lower().replace(" ", "").replace("_", "")
        _default_reshape = not ("myth" in _game_id_lower or "empires" in _game_id_lower or "moe" in _game_id_lower)
        reshape_var = tk.BooleanVar(value=_default_reshape)
        reshape_cb = tk.Checkbutton(
            options_frame,
            text="🔤 قلب النصوص العربية (Arabic Reshaping)",
            variable=reshape_var,
            font=("Segoe UI", 9),
            bg=AppColors.BG_CARD,
            fg=AppColors.TEXT_SECONDARY,
            selectcolor=AppColors.ENTRY_BG,
            activebackground=AppColors.BG_CARD,
            activeforeground=AppColors.TEXT_PRIMARY,
        )
        reshape_cb.pack(anchor="w")
        tk.Label(
            options_frame,
            text="  شغّلها لألعاب Unity/tkinter | أوقفها لألعاب UE4 locres (تتحمل العربية بنفسها)",
            font=("Segoe UI", 8),
            bg=AppColors.BG_CARD,
            fg=AppColors.TEXT_MUTED,
        ).pack(anchor="w")

        progress_frame = tk.Frame(dialog, bg=AppColors.BG_CARD, padx=20, pady=12)
        progress_frame.pack(fill="x", padx=15, pady=5)
        
        dialog_progress_label = tk.Label(progress_frame, text="Ready", font=("Segoe UI", 10), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY)
        dialog_progress_label.pack(anchor="w")
        
        dialog_progress_bar = ttk.Progressbar(progress_frame, length=600, mode='determinate')
        dialog_progress_bar.pack(fill="x", pady=(6, 0))
        
        dialog_stats_label = tk.Label(progress_frame, text="", font=("Segoe UI", 9), bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
        dialog_stats_label.pack(anchor="w", pady=(4, 0))
        
        log_frame = tk.Frame(dialog, bg=AppColors.ENTRY_BG)
        log_frame.pack(fill="both", expand=True, padx=15, pady=(5, 8))
        
        dialog_log = tk.Text(log_frame, height=8, font=("Consolas", 9), bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_SECONDARY, relief="flat", padx=8, pady=5, wrap="word", state="disabled")
        scrollbar = ttk.Scrollbar(log_frame, command=dialog_log.yview)
        dialog_log.configure(yscrollcommand=scrollbar.set)
        dialog_log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        btn_frame = tk.Frame(dialog, bg=AppColors.BG_DARK)
        btn_frame.pack(fill="x", padx=15, pady=(0, 12))
        
        stop_flag = [False]
        
        def log_to_dialog(msg):
            if dialog_log.winfo_exists():
                dialog_log.configure(state="normal")
                dialog_log.insert("end", msg + "\n")
                dialog_log.see("end")
                dialog_log.configure(state="disabled")
        
        def update_progress(current, total, cached, failed):
            if dialog_progress_bar.winfo_exists():
                pct = (current / total * 100) if total > 0 else 0
                dialog_progress_bar["value"] = pct
                dialog_progress_label.configure(text=f"Progress: {current}/{total} ({pct:.0f}%)")
                dialog_stats_label.configure(text=f"New: {current - cached - failed} | Cached: {cached} | Failed: {failed}")
        
        def run_translation():
            selected_model = dialog_model_var.get()
            mode = mode_var.get()
            
            if selected_model and self._translation_engine:
                self._translation_engine.set_active_model(selected_model)
                self._translation_engine.load_model(selected_model)
            
            if mode == "fresh" and self._cache:
                log_to_dialog(f"حذف الترجمات القديمة لـ {game_name}...")
                self._cache.clear_game(game_name)
            
            engine_type = game_config.get("engine", "auto")
            game_id_lower = game_id.lower().replace(" ", "").replace("_", "")
            
            if "ror" in game_id_lower or "rain" in game_id_lower or engine_type == "unity":
                from games.ror2.translator import RoR2Translator
                handler = RoR2Translator(game_path, self._translation_engine, self._cache)
                handler.set_callbacks(progress=update_progress, log=log_to_dialog)
                
                if not handler.is_game_valid():
                    log_to_dialog(f"ERROR: Game not found at: {game_path}")
                    log_to_dialog("Check that the game path is correct in config.")
                    return
                
                log_to_dialog(f"Engine: Unity | Model: {selected_model} | Mode: {mode}")
                log_to_dialog("Starting translation...")
                
                success = handler.translate_all()
                stats = handler.get_stats()
                
                def show_result():
                    if success:
                        log_to_dialog(f"\n{'='*40}")
                        log_to_dialog(f"COMPLETE | Model: {selected_model}")
                        log_to_dialog(f"Total: {stats['total']} | New: {stats['translated']} | Cached: {stats['cached']}")
                        log_to_dialog(f"Saved: {handler.ar_path}")
                        self._set_status(f"{game_name} translated with {selected_model}")
                    else:
                        log_to_dialog("\nSTOPPED or FAILED")
                
                self._safe_after(0, show_result)
            
            elif "myth" in game_id_lower or "empires" in game_id_lower or "moe" in game_id_lower:
                from games.mythofempires.translator import MythOfEmpiresTranslator
                _unrealpak = self._config.get("tools", {}).get("unrealpak_path", "")
                handler = MythOfEmpiresTranslator(game_path, self._translation_engine, self._cache,
                                                  unrealpak_path=_unrealpak, reshape_text=reshape_var.get())
                handler.set_callbacks(progress=update_progress, log=log_to_dialog)

                if not handler.is_game_valid():
                    log_to_dialog(f"ERROR: No .locres files found at: {game_path}")
                    return

                locres_files = handler.find_locres_files()
                log_to_dialog(f"Engine: Unreal Engine (.locres)")
                log_to_dialog(f"Model: {selected_model} | Mode: {mode}")
                log_to_dialog(f"Found {len(locres_files)} locres files:")
                for lf in locres_files:
                    log_to_dialog(f"  - {lf}")

                target_locres = None

                saved_locres = game_config.get("locres_path", "")
                if saved_locres and os.path.exists(saved_locres):
                    target_locres = saved_locres
                    log_to_dialog(f"\nUsing saved locres: {os.path.basename(target_locres)}")
                else:
                    for lf in locres_files:
                        basename = os.path.basename(lf).lower()
                        if "moegame" in basename or "game" in basename:
                            target_locres = lf
                            break
                    if not target_locres and locres_files:
                        target_locres = locres_files[0]

                    if target_locres:
                        if self._game_manager:
                            self._game_manager.update_game(game_id, {"locres_path": target_locres})
                        log_to_dialog(f"\nAuto-selected: {target_locres}")

                if not target_locres:
                    log_to_dialog("ERROR: Could not determine target locres file")
                    log_to_dialog("Use Browse to select a .locres file in the game detail page")
                    return

                handler.set_locres_path(target_locres)
                log_to_dialog(f"\nTarget: {os.path.basename(target_locres)}")

                if not handler.load_locres():
                    log_to_dialog("ERROR: Failed to export/parse locres file")
                    return

                log_to_dialog(f"Entries: {handler.get_entries_count()}")
                log_to_dialog("\nStarting translation...")

                success = handler.translate_all()
                stats = handler.get_stats()

                def show_moe_result():
                    if success:
                        log_to_dialog(f"\n{'='*40}")
                        log_to_dialog(f"COMPLETE | Model: {selected_model}")
                        log_to_dialog(f"Total: {stats['total']} | New: {stats['translated']} | Cached: {stats['cached']}")
                        log_to_dialog(f"Saved: {stats['locres_path']}")
                        self._set_status(f"Myth of Empires translated with {selected_model}")
                    else:
                        log_to_dialog("\nSTOPPED or FAILED")

                self._safe_after(0, show_moe_result)

            elif "manor" in game_id_lower or engine_type == "unreal":
                log_to_dialog(f"Engine: Unreal Engine")
                log_to_dialog(f"Model: {selected_model} | Mode: {mode}")
                log_to_dialog("")
                log_to_dialog("Manor Lords uses Unreal Engine with .pak files.")
                log_to_dialog("Translation is done via Frida runtime hook.")
                log_to_dialog("")
                log_to_dialog("Steps:")
                log_to_dialog("1. Launch Manor Lords")
                log_to_dialog("2. Click 'Attach' to connect Frida")
                log_to_dialog("3. Game text will be translated in real-time")
                log_to_dialog("")
                log_to_dialog("To pre-build cache, use the Translate tab")
                log_to_dialog("to translate common game terms manually.")
                
                if self._cache:
                    stats = self._cache.get_stats(game_name)
                    log_to_dialog(f"\nCached translations: {stats['total_translations']}")
            
            elif "flotsam" in game_id_lower:
                from games.flotsam.translator import FlotsamTranslator
                handler = FlotsamTranslator(game_path, self._translation_engine, self._cache)
                handler.set_callbacks(progress=update_progress, log=log_to_dialog)
                
                if not handler.is_game_valid():
                    log_to_dialog(f"ERROR: I2Languages file not found at: {game_path}")
                    return
                
                log_to_dialog(f"Engine: Unity + I2Languages")
                log_to_dialog(f"Model: {selected_model} | Mode: {mode}")
                log_to_dialog(f"Terms: {handler.get_terms_count()}")
                log_to_dialog("")
                log_to_dialog("Starting translation...")
                
                success = handler.translate_all()
                stats = handler.get_stats()
                
                def show_flotsam_result():
                    if success:
                        log_to_dialog(f"\n{'='*40}")
                        log_to_dialog(f"COMPLETE | Model: {selected_model}")
                        log_to_dialog(f"Total: {stats['total']} | New: {stats['translated']} | Cached: {stats['cached']}")
                        log_to_dialog(f"Saved: {handler.output_path}")
                        log_to_dialog("")
                        log_to_dialog("Start the game and the translation server (port 5001)")
                        self._set_status(f"Flotsam translated with {selected_model}")
                    else:
                        log_to_dialog("\nSTOPPED or FAILED")
                
                self._safe_after(0, show_flotsam_result)
            
            else:
                log_to_dialog(f"Engine: {engine_type}")
                log_to_dialog(f"Model: {selected_model} | Mode: {mode}")
                log_to_dialog("")
                log_to_dialog("This game uses Frida runtime translation.")
                log_to_dialog("Launch the game, then click Attach to start.")
                
                if self._cache:
                    stats = self._cache.get_stats(game_name)
                    log_to_dialog(f"\nCached translations: {stats['total_translations']}")
        
        def start_translation():
            stop_flag[0] = False
            self._translation_running = True
            start_btn.configure(state="disabled")
            stop_btn.configure(state="normal")

            def _run_and_reset():
                try:
                    run_translation()
                finally:
                    self._translation_running = False

            threading.Thread(target=_run_and_reset, daemon=True).start()
        
        start_btn = tk.Button(btn_frame, text="▶ Start Translation", font=("Segoe UI", 10, "bold"), bg=AppColors.SUCCESS, fg="black", relief="flat", padx=15, pady=5, command=start_translation)
        start_btn.pack(side="left", padx=3)
        
        stop_btn = tk.Button(btn_frame, text="⏹ Stop", font=("Segoe UI", 10), bg=AppColors.ERROR, fg="white", relief="flat", padx=15, pady=5, state="disabled")
        stop_btn.pack(side="left", padx=3)
        
        def apply_cached():
            if not cached_models:
                messagebox.showinfo("Info", "No cached translations found")
                return
            
            selected_cached = cached_var.get()
            if not selected_cached:
                messagebox.showwarning("Warning", "Select a cached model first")
                return
            
            translations = self._cache.get_by_model(game_name, selected_cached)
            if not translations:
                log_to_dialog("No translations found for this model")
                return
            
            engine_type = game_config.get("engine", "auto")
            game_id_lower = game_id.lower().replace(" ", "").replace("_", "")
            
            if "ror" in game_id_lower or "rain" in game_id_lower or engine_type == "unity":
                from games.ror2.translator import RoR2Translator
                handler = RoR2Translator(game_path, self._translation_engine, self._cache)
                handler.set_callbacks(log=log_to_dialog)
                
                os.makedirs(handler.ar_path, exist_ok=True)
                
                all_strings = handler.get_all_english_strings()
                applied = 0
                for filename, strings in all_strings.items():
                    translated_strings = {}
                    for key, value in strings.items():
                        if value in translations:
                            translated_strings[key] = translations[value]
                            applied += 1
                        else:
                            translated_strings[key] = value
                    
                    output_path = os.path.join(handler.ar_path, filename)
                    with open(output_path, "w", encoding="utf-8") as f:
                        json.dump({"strings": translated_strings}, f, indent=2, ensure_ascii=False)
                
                log_to_dialog(f"Applied {applied} translations from {selected_cached}")
                self._set_status(f"Applied {applied} cached translations")
            
            else:
                log_to_dialog(f"Loaded {len(translations)} translations from {selected_cached}")
                log_to_dialog("These will be sent to the game when you click Attach")
                log_to_dialog("")
                log_to_dialog("Launch the game and click Attach to apply.")
                self._set_status(f"Loaded {len(translations)} cached translations")
        
        apply_btn = tk.Button(btn_frame, text="📥 Apply Cached", font=("Segoe UI", 10), bg="#9b59b6", fg="white", relief="flat", padx=12, pady=5, command=apply_cached)
        apply_btn.pack(side="left", padx=3)
        
        tk.Button(btn_frame, text="Close", font=("Segoe UI", 10), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=15, pady=5, command=dialog.destroy).pack(side="right")
    
    def _attach_to_game(self, game):
        process_name = game.get("process_name", "")
        if not process_name:
            messagebox.showwarning("Warning", "No process name configured for this game")
            return
        
        self._current_attached_game = game.get("name", game.get("id", "default"))
        self._set_status(f"Looking for process: {process_name}")
        
        def attach_thread():
            try:
                from hooking.frida_manager import FridaManager
                
                if self._frida_manager is None:
                    self._frida_manager = FridaManager()
                    self._frida_manager.set_callbacks(
                        on_text=self._on_game_text,
                        on_log=lambda msg: self._safe_after(0, lambda: self._set_status(msg))
                    )
                
                pid = self._frida_manager.find_process(process_name)
                if pid:
                    success = self._frida_manager.attach_to_process(pid)
                    if success:
                        hooks_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooking", "hooks")
                        self._frida_manager.load_game_hooks(game, hooks_dir)
                        
                        if self._cache:
                            game_id = game.get("id", "")
                            game_name = game.get("name", "")
                            
                            all_translations = self._cache.get_all_for_game(game_id)
                            if game_name and game_name != game_id:
                                name_translations = self._cache.get_all_for_game(game_name)
                                all_translations.update(name_translations)
                            
                            if all_translations:
                                self._frida_manager.send_cache(all_translations)
                                self._safe_after(0, lambda: self._set_status(f"Attached + {len(all_translations)} translations loaded"))
                        
                        self._safe_after(0, lambda: self._set_status(f"Attached to {process_name} (PID: {pid})"))
                        self._safe_after(0, lambda: self._process_indicator.configure(text=f"🟢 {process_name}", fg=AppColors.SUCCESS))
                    else:
                        self._safe_after(0, lambda: self._set_status(f"Failed to attach to {process_name}"))
                else:
                    self._safe_after(0, lambda: messagebox.showinfo("Info", f"Process '{process_name}' not found.\nMake sure the game is running."))
                    self._safe_after(0, lambda: self._set_status(f"Process '{process_name}' not found"))
            except Exception as e:
                self._safe_after(0, lambda: self._set_status(f"Attach error: {e}"))
        
        threading.Thread(target=attach_thread, daemon=True).start()
    
    def _on_game_text(self, text, source="unknown"):
        if not self._translation_engine:
            return None
        
        game_name = self._current_attached_game or "default"
        
        if self._cache:
            cached = self._cache.get(game_name, text)
            if cached:
                try:
                    from engine.arabic_processor import reshape_arabic_keep_tags
                    return reshape_arabic_keep_tags(cached)
                except:
                    return cached
        
        translated = self._translation_engine.translate(text)
        
        if translated:
            if self._cache:
                self._cache.put(game_name, text, translated, self._translation_engine.get_active_model() or "unknown")
            
            try:
                from engine.arabic_processor import reshape_arabic_keep_tags
                reshaped = reshape_arabic_keep_tags(translated)
            except:
                reshaped = translated
            
            self._safe_after(0, lambda: self._log_translation(text, reshaped, source))
            return reshaped
        
        return None
        
        return translated
    
    def _log_translation(self, original, translated, source):
        self._translate_log.configure(state="normal")
        self._translate_log.insert("end", f"[{source}] {original[:60]} -> {translated[:60]}\n")
        self._translate_log.see("end")
        self._translate_log.configure(state="disabled")
    
    def _do_translate(self):
        text = self._translate_input.get("1.0", "end").strip()
        if not text:
            return
        
        self._translate_status.configure(text="Translating...", fg=AppColors.WARNING)
        self._translate_output.configure(state="normal")
        self._translate_output.delete("1.0", "end")
        self._translate_output.configure(state="disabled")
        
        def translate_thread():
            result = None
            if self._translation_engine:
                result = self._translation_engine.translate(text)
            
            if result:
                try:
                    from engine.arabic_processor import reshape_arabic_keep_tags
                    result = reshape_arabic_keep_tags(result)
                except:
                    pass
            
            def update_ui():
                self._translate_output.configure(state="normal")
                self._translate_output.delete("1.0", "end")
                if result:
                    self._translate_output.insert("1.0", result)
                    self._translate_status.configure(text=f"Translated using: {self._translation_engine.get_active_model()}", fg=AppColors.SUCCESS)
                else:
                    self._translate_output.insert("1.0", "Translation failed. Make sure a model is loaded.")
                    self._translate_status.configure(text="Translation failed", fg=AppColors.ERROR)
                self._translate_output.configure(state="disabled")
            
            self._safe_after(0, update_ui)
        
        threading.Thread(target=translate_thread, daemon=True).start()
    
    def _refresh_models_list(self):
        for widget in self._models_container.inner.winfo_children():
            widget.destroy()
        
        if not self._translation_engine:
            tk.Label(self._models_container.inner, text="Engine not initialized", font=("Segoe UI", 11), bg=AppColors.BG_DARK, fg=AppColors.TEXT_MUTED).pack(pady=20)
            return
        
        models = self._translation_engine.get_available_models()
        
        for model in models:
            card = tk.Frame(self._models_container.inner, bg=AppColors.BG_CARD, padx=20, pady=15)
            card.pack(fill="x", pady=3)
            
            info_frame = tk.Frame(card, bg=AppColors.BG_CARD)
            info_frame.pack(side="left", fill="x", expand=True)
            
            status_icon = "🟢" if model["is_loaded"] else "⚪"
            active_badge = "  [ACTIVE]" if model["is_active"] else ""
            
            tk.Label(info_frame, text=f"{status_icon} {model['key']}{active_badge}", font=("Segoe UI", 12, "bold"), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY, anchor="w").pack(anchor="w")
            tk.Label(info_frame, text=model["description"], font=("Segoe UI", 9), bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED, anchor="w").pack(anchor="w")
            
            if model["key"] == "ollama":
                # ── Row 1: base model ──────────────────────────────────────
                ollama_row = tk.Frame(info_frame, bg=AppColors.BG_CARD)
                ollama_row.pack(fill="x", pady=(6, 0))

                tk.Label(ollama_row, text="Model:", font=("Segoe UI", 10),
                    bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, width=8, anchor="w").pack(side="left")

                self._ollama_base_var = tk.StringVar(value="Select...")
                self._ollama_base_combo = ttk.Combobox(ollama_row, textvariable=self._ollama_base_var,
                    state="readonly", width=28, font=("Segoe UI", 10))
                self._ollama_base_combo.pack(side="left", padx=(4, 5))

                tk.Button(ollama_row, text="🔄", font=("Segoe UI", 9),
                    bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY,
                    relief="flat", padx=6, pady=1, cursor="hand2",
                    command=self._fetch_ollama_models).pack(side="left", padx=2)

                # ── Row 2: quantization variant ────────────────────────────
                quant_row = tk.Frame(info_frame, bg=AppColors.BG_CARD)
                quant_row.pack(fill="x", pady=(4, 0))

                tk.Label(quant_row, text="Quant:", font=("Segoe UI", 10),
                    bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, width=8, anchor="w").pack(side="left")

                self._ollama_quant_var = tk.StringVar(value="—")
                self._ollama_quant_combo = ttk.Combobox(quant_row, textvariable=self._ollama_quant_var,
                    state="readonly", width=28, font=("Segoe UI", 10))
                self._ollama_quant_combo.pack(side="left", padx=(4, 5))

                tk.Button(quant_row, text="✅ Apply", font=("Segoe UI", 9, "bold"),
                    bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY,
                    relief="flat", padx=10, pady=1, cursor="hand2",
                    command=self._apply_ollama_model).pack(side="left", padx=2)

                self._ollama_size_label = tk.Label(quant_row, text="", font=("Segoe UI", 9),
                    bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
                self._ollama_size_label.pack(side="left", padx=(12, 0))

                # When base model changes → refresh quant dropdown
                self._ollama_base_combo.bind("<<ComboboxSelected>>",
                    lambda e: self._ollama_base_changed())
                # When quant changes → update info label
                self._ollama_quant_combo.bind("<<ComboboxSelected>>",
                    lambda e: self._ollama_update_info_label())

                self._fetch_ollama_models()
            
            btn_frame = tk.Frame(card, bg=AppColors.BG_CARD)
            btn_frame.pack(side="right")
            
            if model["is_loaded"]:
                unload_btn = tk.Button(btn_frame, text="Unload", font=("Segoe UI", 9), bg=AppColors.ERROR, fg="white", relief="flat", padx=10, pady=3, cursor="hand2", command=lambda k=model["key"]: self._unload_model(k))
                unload_btn.pack(side="left", padx=3)
            else:
                load_btn = tk.Button(btn_frame, text="Load", font=("Segoe UI", 9), bg=AppColors.SUCCESS, fg="black", relief="flat", padx=10, pady=3, cursor="hand2", command=lambda k=model["key"]: self._load_model(k))
                load_btn.pack(side="left", padx=3)
            
            if not model["is_active"]:
                set_btn = tk.Button(btn_frame, text="Set Active", font=("Segoe UI", 9), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=3, cursor="hand2", command=lambda k=model["key"]: self._set_active_model(k))
                set_btn.pack(side="left", padx=3)
    
    @staticmethod
    def _ollama_base_name(full_name: str) -> str:
        """Strip quantization suffix to get base model name.
        e.g. 'gemma3:12b-q4_K_M' → 'gemma3:12b', 'qwen3:14b' → 'qwen3:14b'
        """
        cleaned = re.sub(r'-[qQ]\d+(?:[_\.][A-Za-z0-9]+)*$', '', full_name)
        return cleaned

    def _fetch_ollama_models(self):
        self._set_status("Fetching Ollama models...")

        def fetch_thread():
            models = []
            if self._translation_engine:
                models = self._translation_engine.get_ollama_models()

            # Group by base name: base → [{"full": name, "quant": str, "label": str, "info": str}]
            groups: dict = {}
            for m in models:
                base  = self._ollama_base_name(m["name"])
                quant = m.get("quantization", "") or "default"
                gb    = m.get("size_gb", "?")
                param = m.get("parameter_size", "")
                fam   = m.get("family", "")

                label = f"{quant}  —  {gb} GB"
                info_parts = [p for p in [param, quant, fam, f"{gb} GB"] if p]
                info  = "  |  ".join(info_parts)

                groups.setdefault(base, []).append({
                    "full":  m["name"],
                    "quant": quant,
                    "label": label,
                    "info":  info,
                })

            def update():
                if not (hasattr(self, '_ollama_base_combo') and
                        self._ollama_base_combo.winfo_exists()):
                    return

                # Store groups for use by base-change handler and apply
                self._ollama_groups = groups

                base_names = sorted(groups.keys())
                self._ollama_base_combo["values"] = base_names

                # Pre-select the base that matches the currently loaded model
                current = (self._translation_engine.get_current_ollama_model()
                           if self._translation_engine else "")
                current_base = self._ollama_base_name(current) if current else ""

                if current_base and current_base in base_names:
                    self._ollama_base_var.set(current_base)
                elif base_names:
                    self._ollama_base_var.set(base_names[0])

                # Populate quant dropdown for the selected base
                self._ollama_base_changed(select_full=current)

                if base_names:
                    self._set_status(f"Found {len(models)} Ollama models ({len(base_names)} unique)")
                else:
                    self._set_status("No Ollama models found. Is Ollama running?")

            try:
                self._safe_after(0, update)
            except RuntimeError:
                pass

        threading.Thread(target=fetch_thread, daemon=True).start()

    def _ollama_base_changed(self, select_full: str = ""):
        """Refresh quant dropdown when base model changes."""
        if not hasattr(self, '_ollama_base_combo'):
            return
        groups = getattr(self, '_ollama_groups', {})
        base   = self._ollama_base_var.get()
        variants = groups.get(base, [])

        labels = [v["label"] for v in variants]
        self._ollama_quant_combo["values"] = labels

        # Select the variant that matches select_full (or first)
        matched = next((v["label"] for v in variants if v["full"] == select_full), None)
        if matched:
            self._ollama_quant_var.set(matched)
        elif labels:
            self._ollama_quant_var.set(labels[0])
        else:
            self._ollama_quant_var.set("—")

        self._ollama_update_info_label()

    def _ollama_update_info_label(self):
        """Update the size/info label for the currently selected base+quant."""
        if not hasattr(self, '_ollama_size_label') or not self._ollama_size_label.winfo_exists():
            return
        groups   = getattr(self, '_ollama_groups', {})
        base     = self._ollama_base_var.get()
        quant_lbl = self._ollama_quant_var.get()
        for v in groups.get(base, []):
            if v["label"] == quant_lbl:
                self._ollama_size_label.configure(text=v["info"])
                return
        self._ollama_size_label.configure(text="")

    def _apply_ollama_model(self):
        if not hasattr(self, '_ollama_base_var') or not self._translation_engine:
            return
        groups    = getattr(self, '_ollama_groups', {})
        base      = self._ollama_base_var.get()
        quant_lbl = self._ollama_quant_var.get()
        # Find the full model name that matches
        full_name = next(
            (v["full"] for v in groups.get(base, []) if v["label"] == quant_lbl),
            base  # fallback: use base name directly
        )
        self._translation_engine.set_ollama_model(full_name)
        self._set_status(f"Ollama model set to: {full_name}")
        self._refresh_models_list()
    
    def _load_model(self, model_key):
        self._set_status(f"Loading model: {model_key}...")
        
        def load_thread():
            success = False
            if self._translation_engine:
                success = self._translation_engine.load_model(model_key)
            
            def update():
                if success:
                    self._set_status(f"Model '{model_key}' loaded successfully")
                    self._update_model_indicator(model_key)
                else:
                    self._set_status(f"Failed to load model '{model_key}'")
                self._refresh_models_list()
            
            self._safe_after(0, update)
        
        threading.Thread(target=load_thread, daemon=True).start()
    
    def _unload_model(self, model_key):
        if self._translation_engine:
            self._translation_engine.unload_model(model_key)
            self._set_status(f"Model '{model_key}' unloaded")
            self._update_model_indicator(None)
            self._refresh_models_list()
    
    def _set_active_model(self, model_key):
        if self._translation_engine:
            self._translation_engine.set_active_model(model_key)
            self._set_status(f"Active model set to: {model_key}")
            self._update_model_indicator(model_key)
            self._refresh_models_list()
    
    @staticmethod
    def _default_system_prompt() -> str:
        return (
            "You are an expert Arabic game localization specialist with 15+ years of experience "
            "localizing AAA games into Arabic for the MENA market.\n\n"
            "Your ONLY task: translate the given English game text into natural, high-quality "
            "Modern Standard Arabic (فصحى خفيفة) suitable for games.\n\n"
            "CORE RULES — never break these:\n"
            "1. Output ONLY the Arabic translation. No explanations. No alternatives. No comments. No transliteration.\n"
            "2. Preserve ALL formatting tokens exactly as-is: {0} {1} {playerName} \\n <color=#ff0000> </color> [b] [/b] %s %d — never translate or modify them.\n"
            "3. Preserve punctuation structure that matches the original (ellipsis, exclamation marks, etc.).\n"
            "4. Never add content that is not in the original text.\n"
            "5. If the input is already Arabic or is untranslatable (a proper noun, a code), return it unchanged.\n\n"
            "TRANSLATION QUALITY STANDARDS:\n"
            "- Use terminology consistent with major Arabic game localizations: المهمة، المخزون، المهارة، الصحة، الدرع، الخصم، الحليف، المكافأة، الخريطة، المستوى، النقاط، الذخيرة، التعديلات.\n"
            "- Match tone: dramatic for story/combat, clear for UI/menus, imperative for tutorials (اضغط، حرك، اختر).\n"
            "- Character names, brand names, unique item names: keep in English unless a well-known Arabic equivalent exists.\n"
            "- Short UI labels (buttons, menus): be concise — 1 to 3 words maximum when possible.\n"
            "- Descriptions and lore: use flowing, engaging Arabic that reads naturally, not literally.\n"
            "- Every word must carry meaning — no hollow filler.\n\n"
            "ARABIC LANGUAGE RULES:\n"
            "- Use correct pronoun attachment (كتابته، لاعبها، قدراتك).\n"
            "- Maintain grammatical gender agreement; masculine by default for generic references.\n"
            "- Prefer active voice when the original uses active voice.\n"
            "- Do not add diacritics (تشكيل) unless emphasis is critical."
        )

    def _save_system_prompt(self):
        prompt = self._system_prompt_text.get("1.0", "end").strip()
        if not prompt:
            return
        self._system_prompt = prompt

        # Push to active translators
        if self._translation_engine:
            for key in ("ollama", "custom_endpoint"):
                t = self._translation_engine.get_translator(key)
                if t and hasattr(t, "system_prompt"):
                    t.system_prompt = prompt

        # Persist to config.json
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg["system_prompt"] = prompt
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Prompt] Failed to save to config.json: {e}")

        self._set_status("تم حفظ البرومت")

    def _reset_system_prompt(self):
        default = self._default_system_prompt()
        self._system_prompt = default
        self._system_prompt_text.delete("1.0", "end")
        self._system_prompt_text.insert("1.0", default)

        # Push to active translators
        if self._translation_engine:
            for key in ("ollama", "custom_endpoint"):
                t = self._translation_engine.get_translator(key)
                if t and hasattr(t, "system_prompt"):
                    t.system_prompt = default

        # Remove override from config.json (fall back to default on next load)
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg.pop("system_prompt", None)
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Prompt] Failed to update config.json: {e}")

        self._set_status("تمت إعادة ضبط البرومت للافتراضي")
    
    def _refresh_cache_view(self):
        if not self._cache:
            return
        
        games = self._cache.get_all_games()
        values = ["All Games"] + games
        self._cache_game_combo["values"] = values
        
        if self._cache_selected_game and self._cache_selected_game in values:
            self._cache_game_var.set(self._cache_selected_game)
        elif values:
            self._cache_game_var.set(values[0])
        
        self._cache_current_page = 0
        self._cache_update_models_filter()
        self._cache_load_entries()
    
    def _cache_select_game(self):
        self._cache_selected_game = self._cache_game_var.get()
        self._cache_current_page = 0
        self._cache_update_models_filter()   # resets model to "All Models"
        self._cache_update_delete_model_btn()
        self._cache_load_entries()

    def _cache_do_search(self):
        """Search without resetting the model dropdown."""
        self._cache_current_page = 0
        self._cache_load_entries()

    def _cache_select_model(self):
        """Called only when model dropdown changes — does NOT reset model selection."""
        self._cache_current_page = 0
        self._cache_update_delete_model_btn()
        self._cache_load_entries()
    
    def _cache_clear_search(self):
        self._cache_search_var.set("")
        self._cache_current_page = 0
        self._cache_load_entries()
    
    def _cache_update_models_filter(self):
        if not self._cache:
            return
        
        game = self._cache_game_var.get()
        if game == "All Games":
            all_models = set()
            for g in self._cache.get_all_games():
                all_models.update(self._cache.get_models_for_game(g))
            models = sorted(all_models)
        else:
            models = self._cache.get_models_for_game(game)
        
        values = ["All Models"] + models
        self._cache_model_combo["values"] = values
        self._cache_model_var.set("All Models")
    
    def _cache_change_page(self, delta):
        self._cache_current_page = max(0, self._cache_current_page + delta)
        self._cache_load_entries()
    
    def _cache_load_entries(self):
        self._cache_tree.delete(*self._cache_tree.get_children())
        self._cache_entry_map = {}

        if not self._cache:
            return

        game        = self._cache_game_var.get()
        search      = self._cache_search_var.get().strip()
        model_filter = self._cache_model_var.get()

        if game == "All Games":
            games = self._cache.get_all_games()
            all_entries = []
            for g in games:
                entries = self._cache.get_page(g, 0, 10000, search, model_filter)
                for e in entries:
                    e["game"] = g
                all_entries.extend(entries)
            total = len(all_entries)
            start = self._cache_current_page * self._cache_page_size
            page_entries = all_entries[start:start + self._cache_page_size]
            self._cache_stats_label.configure(text=f"Total: {total} entries")
        else:
            total = self._cache.count_entries(game, search, model_filter)
            offset = self._cache_current_page * self._cache_page_size
            page_entries = self._cache.get_page(game, offset, self._cache_page_size, search, model_filter)
            stats = self._cache.get_stats(game)
            self._cache_stats_label.configure(text=f"Total: {total} | Hits: {stats['cache_hits']}")

        total_pages = max(1, (total + self._cache_page_size - 1) // self._cache_page_size)
        self._cache_page_label.configure(text=f"Page {self._cache_current_page + 1}/{total_pages}")
        self._cache_prev_btn.configure(state="normal" if self._cache_current_page > 0 else "disabled")
        self._cache_next_btn.configure(state="normal" if self._cache_current_page < total_pages - 1 else "disabled")

        locked = self._translation_running
        self._cache_edit_btn.configure(state="disabled" if locked else "normal")
        self._cache_del_btn.configure(state="disabled" if locked else "normal")

        for i, entry in enumerate(page_entries):
            num       = self._cache_current_page * self._cache_page_size + i + 1
            orig      = entry["original"]
            trans     = entry["translated"]
            model     = entry.get("model", "?")
            game_name = entry.get("game", game)
            tag       = "odd" if i % 2 == 0 else "even"

            # Normalize for single-line Treeview display (actual \n and literal \n → ↵)
            orig_disp  = orig.replace("\\n", " ↵ ").replace("\n", " ↵ ")
            trans_disp = trans.replace("\\n", " ↵ ").replace("\n", " ↵ ")

            iid = self._cache_tree.insert("", "end",
                values=(num, orig_disp, trans_disp, model),
                tags=(tag,))

            ec = dict(entry)
            ec["game"] = game_name
            self._cache_entry_map[iid] = ec
    
    def _cache_edit_selected(self):
        sel = self._cache_tree.selection()
        if not sel:
            return
        entry = self._cache_entry_map.get(sel[0])
        if not entry:
            return
        if self._translation_running:
            messagebox.showwarning("Locked", "الترجمة جارية — انتظر حتى تنتهي قبل التعديل")
            return
        self._cache_edit_entry(entry.get("game") or self._cache_game_var.get(), entry)

    def _cache_delete_selected(self):
        sel = self._cache_tree.selection()
        if not sel:
            return
        if self._translation_running:
            messagebox.showwarning("Locked", "الترجمة جارية — انتظر حتى تنتهي قبل الحذف")
            return
        if len(sel) > 1:
            if not messagebox.askyesno("تأكيد الحذف", f"حذف {len(sel)} عنصراً محدداً؟"):
                return
            game_name = self._cache_game_var.get()
            for iid in sel:
                entry = self._cache_entry_map.get(iid)
                if entry and self._cache:
                    self._cache.delete_entry(entry.get("game") or game_name, entry["original"])
            self._cache_load_entries()
            self._set_status(f"تم حذف {len(sel)} عنصراً")
        else:
            entry = self._cache_entry_map.get(sel[0])
            if not entry:
                return
            self._cache_delete_entry(entry.get("game") or self._cache_game_var.get(), entry)

    def _cache_tree_rclick(self, event):
        iid = self._cache_tree.identify_row(event.y)
        if not iid:
            return
        # If right-clicked item is not already in the selection, select only it
        if iid not in self._cache_tree.selection():
            self._cache_tree.selection_set(iid)
        sel_count = len(self._cache_tree.selection())
        menu = tk.Menu(self.root, tearoff=0,
            bg=AppColors.BG_MEDIUM, fg=AppColors.TEXT_PRIMARY,
            activebackground=AppColors.ACCENT, activeforeground="white")
        if sel_count == 1:
            menu.add_command(label="✏️  Edit", command=self._cache_edit_selected)
        menu.add_command(label=f"🔄  إعادة ترجمة ({sel_count})", command=self._cache_retranslate_selected)
        menu.add_command(label=f"🗑  Delete ({sel_count})", command=self._cache_delete_selected)
        menu.post(event.x_root, event.y_root)

    def _cache_retranslate_selected(self):
        sel = self._cache_tree.selection()
        if not sel:
            messagebox.showinfo("لا يوجد تحديد", "حدّد سطراً أو أكثر من القائمة أولاً.\n\nاستخدم Ctrl+Click لتحديد أكثر من سطر.")
            return
        if not self._translation_engine or not self._translation_engine.get_active_model():
            messagebox.showwarning("لا يوجد موديل", "فعّل موديل الترجمة أولاً من صفحة AI Models")
            return
        if self._translation_running:
            messagebox.showwarning("مشغول", "الترجمة جارية — انتظر حتى تنتهي")
            return

        entries_to_retrans = []
        for iid in sel:
            entry = self._cache_entry_map.get(iid)
            if entry and entry.get("original"):
                entries_to_retrans.append(entry)

        if not entries_to_retrans:
            return

        count = len(entries_to_retrans)
        if not messagebox.askyesno(
            "إعادة ترجمة",
            f"إعادة ترجمة {count} {'عنصر' if count == 1 else 'عناصر'} من النص الإنجليزي الأصلي؟\n\n"
            "• الموديل النشط سيُستخدم للترجمة\n"
            "• سيتم حماية التاغات والرموز الخاصة تلقائياً\n"
            "• الترجمة الحالية في الكاش ستُستبدل بالنتيجة الجديدة"
        ):
            return

        def _retrans_thread():
            done = 0
            failed = 0
            model_key = self._translation_engine.get_active_model() or "unknown"
            game_name = self._cache_game_var.get()

            for entry in entries_to_retrans:
                orig = entry["original"]
                game = entry.get("game") or game_name
                try:
                    result = self._translation_engine.translate(orig)
                    if result and result != orig:
                        if self._cache:
                            self._cache.update_translation(game, orig, result)
                        done += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1

            def _finish():
                self._cache_load_entries()
                msg = f"إعادة الترجمة: {done} نجح"
                if failed:
                    msg += f"، {failed} فشل"
                self._set_status(msg)

            self._safe_after(0, _finish)

        threading.Thread(target=_retrans_thread, daemon=True).start()
        self._set_status(f"جاري إعادة ترجمة {count} عنصر...")

    def _cache_edit_entry(self, game_name, entry):
        dialog = tk.Toplevel(self.root)
        dialog.title("تعديل الترجمة")
        dialog.geometry("720x540")
        dialog.configure(bg=AppColors.BG_DARK)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(True, True)

        x = self.root.winfo_x() + (self.root.winfo_width() - 720) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 540) // 2
        dialog.geometry(f"+{x}+{y}")

        tk.Label(dialog, text="✏️ تعديل الترجمة", font=self._theme.get_header_font(),
                 bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(pady=(15, 5))
        tk.Label(dialog, text=f"اللعبة: {game_name}", font=self._theme.get_small_font(),
                 bg=AppColors.BG_DARK, fg=AppColors.TEXT_MUTED).pack(pady=(0, 10))

        # Pack buttons at bottom FIRST so they always stay visible
        btn_frame = tk.Frame(dialog, bg=AppColors.BG_DARK)
        btn_frame.pack(side="bottom", fill="x", padx=20, pady=(5, 15))

        content_frame = tk.Frame(dialog, bg=AppColors.BG_DARK)
        content_frame.pack(fill="both", expand=True, padx=20)
        content_frame.grid_rowconfigure(1, weight=1)
        content_frame.grid_rowconfigure(3, weight=2)
        content_frame.grid_columnconfigure(0, weight=1)

        # English (read-only)
        tk.Label(content_frame, text="النص الأصلي (إنجليزي):", font=self._theme.get_font(),
                 bg=AppColors.BG_DARK, fg=AppColors.TEXT_SECONDARY).grid(row=0, column=0, sticky="w", pady=(0, 3))

        orig_wrap = tk.Frame(content_frame, bg=AppColors.ENTRY_BG)
        orig_wrap.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        orig_wrap.grid_rowconfigure(0, weight=1)
        orig_wrap.grid_columnconfigure(0, weight=1)

        orig_text = tk.Text(orig_wrap, font=self._theme.get_code_font(),
                            bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_SECONDARY,
                            relief="flat", padx=8, pady=6, wrap="word")
        orig_vsb = ttk.Scrollbar(orig_wrap, orient="vertical", command=orig_text.yview)
        orig_text.configure(yscrollcommand=orig_vsb.set)
        orig_text.grid(row=0, column=0, sticky="nsew")
        orig_vsb.grid(row=0, column=1, sticky="ns")

        # Display: replace literal \n with actual newline for readability
        orig_display = entry["original"].replace("\\n", "\n")
        orig_text.insert("1.0", orig_display)
        orig_text.configure(state="disabled")

        # Arabic (editable)
        tk.Label(content_frame, text="الترجمة العربية:", font=self._theme.get_font(),
                 bg=AppColors.BG_DARK, fg=AppColors.TEXT_SECONDARY).grid(row=2, column=0, sticky="w", pady=(0, 3))

        trans_wrap = tk.Frame(content_frame, bg=AppColors.ENTRY_BG)
        trans_wrap.grid(row=3, column=0, sticky="nsew", pady=(0, 8))
        trans_wrap.grid_rowconfigure(0, weight=1)
        trans_wrap.grid_columnconfigure(0, weight=1)

        trans_text = tk.Text(trans_wrap, font=self._theme.get_code_font(),
                             bg=AppColors.ENTRY_BG, fg=AppColors.SUCCESS,
                             relief="flat", padx=8, pady=6, wrap="word")
        trans_vsb = ttk.Scrollbar(trans_wrap, orient="vertical", command=trans_text.yview)
        trans_text.configure(yscrollcommand=trans_vsb.set)
        trans_text.grid(row=0, column=0, sticky="nsew")
        trans_vsb.grid(row=0, column=1, sticky="ns")

        # Display: replace literal \n with actual newline for readability
        trans_display = entry["translated"].replace("\\n", "\n")
        trans_text.insert("1.0", trans_display)

        def save():
            raw = trans_text.get("1.0", "end-1c").strip()
            if not raw or not self._cache:
                return
            # Convert actual newlines back to literal \n to match cache storage format
            new_trans = raw.replace("\n", "\\n")
            self._cache.update_translation(game_name, entry["original"], new_trans)
            dialog.destroy()
            self._cache_load_entries()
            self._set_status("تم تحديث الترجمة")

        tk.Button(btn_frame, text="💾 حفظ", font=self._theme.get_font(style="bold"), bg=AppColors.SUCCESS, fg="black", relief="flat", padx=15, pady=4, command=save).pack(side="left")
        tk.Button(btn_frame, text="إلغاء", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=15, pady=4, command=dialog.destroy).pack(side="left", padx=10)
    
    def _apply_to_subtitle_files(self, game_name, original, translated):
        import arabic_reshaper
        
        translate_dir = self._find_translate_dir_from_name(game_name)
        if not translate_dir:
            return
        
        found = False
        for fname in os.listdir(translate_dir):
            if not fname.endswith('.subtitle.en.txt'):
                continue
            
            en_path = os.path.join(translate_dir, fname)
            en_text = self._read_subtitle_file(en_path)
            
            if en_text and en_text.strip() == original.strip():
                hash_name = fname.replace('.subtitle.en.txt', '')
                ar_path = os.path.join(translate_dir, f"{hash_name}.subtitle.txt")
                
                reshaped = arabic_reshaper.reshape(translated)
                with open(ar_path, 'wb') as f:
                    f.write(b'\xff\xfe')
                    f.write(reshaped.encode('utf-16-le'))
                
                found = True
                self._set_status(f"Updated subtitle: {hash_name}")
                break
        
        if not found:
            self._set_status("Subtitle file not found for this text")
    
    def _find_translate_dir_from_name(self, game_name):
        game_config = self._game_manager.get_game(game_name) if self._game_manager else None
        if not game_config:
            game_id_clean = game_name.replace(" ", "_")
            game_config = self._game_manager.get_game(game_id_clean) if self._game_manager else None
        
        if game_config:
            return self._find_translate_dir(game_config)
        return ""
    
    def _find_translate_dir(self, game_config):
        game_path = game_config.get("game_path", "")
        if not game_path:
            return ""
        
        for sub in ["ManorLords", ""]:
            candidate = os.path.join(game_path, sub, "Binaries", "Win64", "Translate") if sub else os.path.join(game_path, "Binaries", "Win64", "Translate")
            if os.path.exists(candidate):
                return candidate
        
        return ""
    
    def _start_translation_server(self):
        import subprocess
        
        server_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "translation_server.py")
        
        if not os.path.exists(server_script):
            messagebox.showwarning("Warning", "translation_server.py not found")
            return
        
        try:
            subprocess.Popen(
                ["python", server_script],
                creationflags=0x00000008,
                cwd=os.path.dirname(server_script)
            )
            self._set_status("Translation server started on port 5001")
        except Exception as e:
            self._set_status(f"Failed to start server: {e}")
    
    def _sync_from_game(self, game_id, game_name, game_config):
        game_id_lower = game_id.lower().replace(" ", "").replace("_", "")
        
        if "flotsam" in game_id_lower:
            self._sync_flotsam_from_game(game_id, game_name, game_config)
            return
        
        if "myth" in game_id_lower or "empires" in game_id_lower or "moe" in game_id_lower:
            self._sync_moe_from_game(game_id, game_name, game_config)
            return
        
        translate_dir = self._find_translate_dir(game_config)
        if not translate_dir:
            messagebox.showwarning("Warning", "Translate directory not found")
            return
        
        def sync_thread():
            files = os.listdir(translate_dir)
            en_files = [f for f in files if f.endswith('.subtitle.en.txt')]
            
            imported = 0
            for f in en_files:
                hash_name = f.replace('.subtitle.en.txt', '')
                en_path = os.path.join(translate_dir, f)
                ar_path = os.path.join(translate_dir, hash_name + '.subtitle.txt')
                
                if not os.path.exists(ar_path):
                    continue
                
                en_text = self._read_subtitle_file(en_path)
                ar_text = self._read_subtitle_file(ar_path)
                
                if not en_text or not ar_text or len(en_text) < 2:
                    continue
                
                if any(0xFE70 <= ord(c) <= 0xFEFF for c in ar_text[:10]):
                    ar_text = self._presentation_to_normal(ar_text)
                
                existing = self._cache.get(game_name, en_text)
                if existing == ar_text:
                    continue
                
                self._cache.put(game_name, en_text, ar_text, "subtitle_sync")
                imported += 1
            
            self._safe_after(0, lambda: self._set_status(f"Synced {imported} translations from game"))
            self._safe_after(0, lambda: self._show_game_detail(game_id))
        
        self._set_status("Syncing from game...")
        threading.Thread(target=sync_thread, daemon=True).start()
    
    def _sync_to_game(self, game_id, game_name, game_config):
        game_id_lower = game_id.lower().replace(" ", "").replace("_", "")
        
        if "flotsam" in game_id_lower:
            self._sync_flotsam_to_game(game_id, game_name, game_config)
            return
        
        if "myth" in game_id_lower or "empires" in game_id_lower or "moe" in game_id_lower:
            self._sync_moe_to_game(game_id, game_name, game_config)
            return
        
        translate_dir = self._find_translate_dir(game_config)
        if not translate_dir:
            messagebox.showwarning("Warning", "Translate directory not found")
            return
        
        def sync_thread():
            import arabic_reshaper
            
            translations = self._cache.get_all_for_game(game_name)
            if not translations:
                self._safe_after(0, lambda: self._set_status("No translations in cache"))
                return
            
            en_map = {}
            for fname in os.listdir(translate_dir):
                if fname.endswith('.subtitle.en.txt'):
                    en_path = os.path.join(translate_dir, fname)
                    en_text = self._read_subtitle_file(en_path)
                    if en_text:
                        hash_name = fname.replace('.subtitle.en.txt', '')
                        en_map[en_text.strip()] = hash_name
            
            written = 0
            for en_text, ar_text in translations.items():
                en_clean = en_text.strip()
                
                hash_name = en_map.get(en_clean)
                if not hash_name:
                    continue
                
                ar_path = os.path.join(translate_dir, f"{hash_name}.subtitle.txt")
                
                reshaped = arabic_reshaper.reshape(ar_text)
                with open(ar_path, 'wb') as f:
                    f.write(b'\xff\xfe')
                    f.write(reshaped.encode('utf-16-le'))
                
                written += 1
            
            self._safe_after(0, lambda: self._set_status(f"Synced {written} translations to game"))
            self._safe_after(0, lambda: self._show_game_detail(game_id))
        
        self._set_status("Syncing to game...")
        threading.Thread(target=sync_thread, daemon=True).start()
    
    def _sync_flotsam_from_game(self, game_id, game_name, game_config):
        game_path = game_config.get("game_path", "")
        json_path = os.path.join(game_path, "BepInEx", "config", "ArabicGameTranslator", "flotsam_i2_translated_only.json")
        
        if not os.path.exists(json_path):
            messagebox.showwarning("Warning", "Flotsam translation JSON not found")
            return
        
        def sync_thread():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    payload = json.load(f)
                
                i2_path = os.path.join(game_path, "Flotsam_Data", "I2Languages-resources.assets-115691.json")
                key_to_english = {}
                if os.path.exists(i2_path):
                    with open(i2_path, 'r', encoding='utf-8') as f:
                        i2data = json.load(f)
                    for term in i2data.get('mSource', {}).get('mTerms', {}).get('Array', []):
                        name = term.get('Term', '')
                        langs = term.get('Languages', {}).get('Array', [])
                        if name and langs:
                            key_to_english[name] = langs[0]
                
                entries = payload.get('entries', [])
                imported = 0
                for entry in entries:
                    key = entry.get('key', '')
                    arabic = entry.get('Arabic', '')
                    if not key or not arabic:
                        continue
                    
                    english = key_to_english.get(key, key)
                    existing = self._cache.get(game_name, english) if self._cache else None
                    if existing == arabic:
                        continue
                    
                    if self._cache:
                        self._cache.put(game_name, english, arabic, "flotsam_sync")
                    imported += 1
                
                self._safe_after(0, lambda: self._set_status(f"Synced {imported} Flotsam translations from game"))
                self._safe_after(0, lambda: self._show_game_detail(game_id))
            except Exception as e:
                self._safe_after(0, lambda: self._set_status(f"Sync error: {e}"))
        
        self._set_status("Syncing Flotsam translations...")
        threading.Thread(target=sync_thread, daemon=True).start()
    
    def _sync_flotsam_to_game(self, game_id, game_name, game_config):
        game_path = game_config.get("game_path", "")
        json_path = os.path.join(game_path, "BepInEx", "config", "ArabicGameTranslator", "flotsam_i2_translated_only.json")
        
        i2_path = os.path.join(game_path, "Flotsam_Data", "I2Languages-resources.assets-115691.json")
        if not os.path.exists(i2_path):
            messagebox.showwarning("Warning", "I2Languages file not found")
            return
        
        def sync_thread():
            try:
                with open(i2_path, 'r', encoding='utf-8') as f:
                    i2data = json.load(f)
                
                terms = i2data.get('mSource', {}).get('mTerms', {}).get('Array', [])
                
                translations = self._cache.get_all_for_game(game_name) if self._cache else {}
                
                english_to_key = {}
                for term in terms:
                    name = term.get('Term', '')
                    langs = term.get('Languages', {}).get('Array', [])
                    if name and langs:
                        english_to_key[langs[0]] = name
                
                entries = []
                for english, arabic in translations.items():
                    key = english_to_key.get(english, english)
                    entries.append({'key': key, 'Arabic': arabic})
                
                os.makedirs(os.path.dirname(json_path), exist_ok=True)
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump({'entries': entries}, f, ensure_ascii=False)
                
                self._safe_after(0, lambda: self._set_status(f"Synced {len(entries)} translations to Flotsam"))
                self._safe_after(0, lambda: self._show_game_detail(game_id))
            except Exception as e:
                self._safe_after(0, lambda: self._set_status(f"Sync error: {e}"))
        
        self._set_status("Syncing to Flotsam...")
        threading.Thread(target=sync_thread, daemon=True).start()
    
    def _sync_moe_from_game(self, game_id, game_name, game_config):
        game_path = game_config.get("game_path", "")
        saved_locres = game_config.get("locres_path", "")
        
        def sync_thread():
            try:
                from games.mythofempires.translator import MythOfEmpiresTranslator
                handler = MythOfEmpiresTranslator(game_path, None, self._cache)
                
                if not handler.is_game_valid():
                    self._safe_after(0, lambda: self._set_status("ERROR: No .locres files found"))
                    return
                
                target = saved_locres
                if not target or not os.path.exists(target):
                    locres_files = handler.find_locres_files()
                    for lf in locres_files:
                        basename = os.path.basename(lf).lower()
                        if "moegame" in basename or "game" in basename:
                            target = lf
                            break
                    if not target and locres_files:
                        target = locres_files[0]
                
                if not target or not os.path.exists(target):
                    self._safe_after(0, lambda: self._set_status("ERROR: No target locres file"))
                    return
                
                if not handler.load_locres(target):
                    self._safe_after(0, lambda: self._set_status("ERROR: Failed to export/parse locres"))
                    return
                
                entries = handler.get_entries()
                imported = 0
                for key, value in entries.items():
                    if not value or len(value.strip()) < 2:
                        continue
                    existing = self._cache.get(game_name, key) if self._cache else None
                    if existing == value:
                        continue
                    if self._cache:
                        self._cache.put(game_name, key, value, "moe_locres_sync")
                    imported += 1
                
                self._safe_after(0, lambda: self._set_status(f"Synced {imported} Myth of Empires translations from game"))
                self._safe_after(0, lambda: self._show_game_detail(game_id))
            except Exception as e:
                self._safe_after(0, lambda: self._set_status(f"Sync error: {e}"))
        
        self._set_status("Syncing Myth of Empires translations...")
        threading.Thread(target=sync_thread, daemon=True).start()
    
    def _sync_moe_to_game(self, game_id, game_name, game_config):
        game_path = game_config.get("game_path", "")
        saved_locres = game_config.get("locres_path", "")

        if not saved_locres or not os.path.exists(saved_locres):
            messagebox.showwarning("Warning", "No .locres file selected. Use Browse to select one first.")
            return

        def sync_thread():
            try:
                from games.mythofempires.translator import MythOfEmpiresTranslator
                _unrealpak = self._config.get("tools", {}).get("unrealpak_path", "")
                handler = MythOfEmpiresTranslator(game_path, None, self._cache, unrealpak_path=_unrealpak)

                self._safe_after(0, lambda: self._set_status("Exporting locres..."))
                if not handler.load_locres(saved_locres):
                    self._safe_after(0, lambda: self._set_status("ERROR: Failed to export locres"))
                    return

                translations = self._cache.get_all_for_game(game_name) if self._cache else {}
                if not translations:
                    self._safe_after(0, lambda: self._set_status("No translations in cache"))
                    return

                entries = handler.get_entries()
                applied = 0
                for key, value in entries.items():
                    # cache is keyed by english text (the value), not by the hash key
                    if value in translations:
                        entries[key] = translations[value]
                        applied += 1

                handler._entries = entries

                self._safe_after(0, lambda: self._set_status(f"Writing {applied} translations to TXT..."))
                if handler._write_txt():
                    self._safe_after(0, lambda: self._set_status("Importing TXT to locres..."))
                    if handler._import_locres():
                        self._safe_after(0, lambda: self._set_status("Packing to .pak..."))
                        handler._pack_to_pak()
                        self._safe_after(0, lambda: self._set_status(f"Synced {applied} translations to Myth of Empires"))
                        self._safe_after(0, lambda: self._show_game_detail(game_id))
                    else:
                        self._safe_after(0, lambda: self._set_status("ERROR: Failed to import locres"))
                else:
                    self._safe_after(0, lambda: self._set_status("ERROR: Failed to write TXT"))
            except Exception as e:
                self._safe_after(0, lambda: self._set_status(f"Sync error: {e}"))

        self._set_status("Syncing to Myth of Empires...")
        threading.Thread(target=sync_thread, daemon=True).start()
    
    def _read_subtitle_file(self, path):
        try:
            with open(path, 'rb') as f:
                raw = f.read()
            if raw[:2] == b'\xff\xfe':
                return raw[2:].decode('utf-16-le', errors='replace').replace('\x00', '').strip()
            if raw[:2] == b'\xfe\xff':
                return raw[2:].decode('utf-16-be', errors='replace').replace('\x00', '').strip()
            if len(raw) >= 2 and raw[1] == 0:
                return raw.decode('utf-16-le', errors='replace').replace('\x00', '').strip()
            return raw.decode('utf-8', errors='replace').replace('\x00', '').strip()
        except:
            return ""
    
    def _cache_delete_entry(self, game_name, entry):
        if messagebox.askyesno("Confirm", f"Delete this translation?\n\n{entry['original'][:60]}..."):
            if self._cache:
                self._cache.delete_entry(game_name, entry["original"])
                self._cache_load_entries()
                self._set_status("Entry deleted")
    
    def _cache_delete_all(self):
        game = self._cache_game_var.get()
        if game == "All Games":
            msg = "Delete ALL cache databases for ALL games?\n\nThis deletes every .db file in data/cache/."
        else:
            msg = f"Delete the entire cache database for '{game}'?\n\nThis deletes data/cache/{game}.db completely."
        if not messagebox.askyesno("Confirm Delete ALL", msg, icon="warning"):
            return
        if not self._cache:
            return
        if game == "All Games":
            self._cache.delete_all()
        else:
            self._cache.delete_game(game)
        # reset to All Games BEFORE refresh so we don't reconnect to deleted db
        self._cache_game_var.set("All Games")
        self._cache_selected_game = "All Games"
        self._cache_model_var.set("All Models")
        self._cache_update_delete_model_btn()
        self._refresh_cache_view()
        self._set_status(f"Deleted: {game}")
        self._refresh_home_stats()

    def _cache_update_delete_model_btn(self):
        if not hasattr(self, "_cache_delete_model_btn"):
            return
        model = self._cache_model_var.get()
        if model and model != "All Models":
            self._cache_delete_model_btn.configure(
                state="normal", bg="#c0392b", fg="white")
        else:
            self._cache_delete_model_btn.configure(
                state="disabled", bg="#5a1a1a", fg="#555555")

    def _cache_delete_model(self):
        game  = self._cache_game_var.get()
        model = self._cache_model_var.get()
        if not model or model == "All Models":
            return
        if game == "All Games":
            games = self._cache.get_all_games() if self._cache else []
            msg = f"Delete all translations by '{model}' across ALL games?\n({len(games)} databases)"
        else:
            msg = f"Delete all translations by '{model}' for '{game}'?"
        if not messagebox.askyesno("Confirm Delete Model", msg, icon="warning"):
            return
        if not self._cache:
            return
        if game == "All Games":
            for g in self._cache.get_all_games():
                self._cache.delete_by_model(g, model)
        else:
            self._cache.delete_by_model(game, model)
        self._cache_model_var.set("All Models")
        self._cache_update_delete_model_btn()
        self._cache_current_page = 0
        self._cache_update_models_filter()
        self._cache_load_entries()
        self._set_status(f"Deleted model '{model}' from {game}")

    def _cache_clean_bad(self):
        """Delete cache entries where the Arabic translation is suspiciously long
        (more than 6x the English length) — caused by Google adding extra context."""
        if not self._cache:
            return
        game = self._cache_game_var.get()
        games = self._cache.get_all_games() if game == "All Games" else [game]

        total_deleted = 0
        for g in games:
            entries = self._cache.get_all_for_game(g)
            to_delete = []
            for orig, trans in entries.items():
                # Flag if Arabic is 6x+ the English length (Google hallucinated)
                if len(trans) > max(len(orig) * 6, 600):
                    to_delete.append(orig)
                # Flag if translation has \n but original doesn't (Google added paragraphs)
                elif '\n' in trans and '\n' not in orig:
                    to_delete.append(orig)

            if to_delete:
                if not messagebox.askyesno(
                    "Clean Bad Translations",
                    f"Found {len(to_delete)} bad entries in '{g}'\n"
                    f"(Google added extra content or newlines).\n\n"
                    f"Delete them so they can be re-translated correctly?",
                    icon="warning"
                ):
                    continue
                for orig in to_delete:
                    self._cache.delete_entry(g, orig)
                total_deleted += len(to_delete)

        if total_deleted == 0:
            messagebox.showinfo("Clean Bad", "No bad entries found — cache looks clean!")
        else:
            self._cache_current_page = 0
            self._cache_load_entries()
            self._set_status(f"Cleaned {total_deleted} bad entries from cache")

    # ------------------------------------------------------------------
    # IoStore / UAsset Wizard
    # ------------------------------------------------------------------

    def _open_iostore_wizard(self, game_id: str = ""):
        from games.iostore.translator import (IoStoreTranslator, UE_VERSIONS,
                                               ZEN_VERSIONS, EXTRACTION_MODES)

        win = tk.Toplevel(self.root)
        win.title("📦 IoStore / UAsset Translator")
        win.geometry("950x780")
        win.minsize(820, 640)
        win.configure(bg=AppColors.BG_DARK)
        win.transient(self.root)
        x = self.root.winfo_x() + max(0, (self.root.winfo_width() - 950) // 2)
        y = self.root.winfo_y() + max(0, (self.root.winfo_height() - 780) // 2)
        win.geometry(f"+{x}+{y}")

        # ── State ──────────────────────────────────────────────────────
        legacy_folder = [None]           # set after step 1
        json_paths = [[]]                # set after step 2
        all_texts = [[]]                 # set after step 2 extraction
        translations = [{}]              # set after step 3
        _active_translator = [None]      # ref to running translator (for stop)

        # ── Helpers ────────────────────────────────────────────────────
        def _safe(func):
            try:
                win.after(0, func)
            except Exception:
                pass

        def log(msg: str):
            def _append():
                log_text.configure(state="normal")
                log_text.insert("end", msg + "\n")
                log_text.see("end")
                log_text.configure(state="disabled")
            _safe(_append)

        def set_step_status(badge_lbl, color, text):
            def _update():
                badge_lbl.configure(text=text, fg=color)
            _safe(_update)

        def _get_translator() -> IoStoreTranslator:
            retoc = retoc_var.get().strip() or self._config.get("tools", {}).get("retoc_path", "")
            uagui = uassetgui_var.get().strip() or self._config.get("tools", {}).get("uassetgui_path", "")
            t = IoStoreTranslator(
                translator_engine=self._translation_engine,
                cache=self._cache,
                retoc_path=retoc or None,
                uassetgui_path=uagui or None,
            )
            t.set_callbacks(log=log)
            return t

        # ── Scrollable main body ────────────────────────────────────────
        tk.Label(win, text="📦  IoStore / UAsset Translator",
                 font=self._theme.get_title_font(),
                 bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", padx=20, pady=(14, 4))
        tk.Frame(win, bg=AppColors.BORDER, height=1).pack(fill="x", padx=20)

        body_scroll = ScrollableFrame(win, bg_color=AppColors.BG_DARK)
        body_scroll.pack(fill="both", expand=True, padx=0, pady=0)
        body = body_scroll.inner

        def card(parent, title):
            f = tk.Frame(parent, bg=AppColors.BG_CARD, padx=18, pady=14)
            f.pack(fill="x", padx=16, pady=(8, 0))
            tk.Label(f, text=title, font=self._theme.get_header_font(),
                     bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 8))
            return f

        def row_field(parent, label, var, width=38, show=None):
            r = tk.Frame(parent, bg=AppColors.BG_CARD)
            r.pack(fill="x", pady=3)
            tk.Label(r, text=label, font=self._theme.get_font(), bg=AppColors.BG_CARD,
                     fg=AppColors.TEXT_SECONDARY, width=18, anchor="w").pack(side="left")
            kw = {"show": show} if show else {}
            e = tk.Entry(r, textvariable=var, font=self._theme.get_font(),
                         bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY,
                         insertbackground=AppColors.TEXT_PRIMARY, relief="flat",
                         width=width, **kw)
            e.pack(side="left", ipady=4, padx=(6, 0), fill="x", expand=True)
            return r, e

        def browse_btn(parent, var, title="Select file",
                       filetypes=None, folder=False):
            def _browse():
                if folder:
                    p = filedialog.askdirectory(title=title)
                else:
                    p = filedialog.askopenfilename(
                        title=title,
                        filetypes=filetypes or [("All files", "*.*")])
                if p:
                    var.set(p)
            tk.Button(parent, text="📂", font=self._theme.get_small_font(),
                      bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY,
                      relief="flat", padx=8, pady=3, cursor="hand2",
                      command=_browse).pack(side="left", padx=4)

        # ── Config card ────────────────────────────────────────────────
        cfg = card(body, "⚙️  Configuration")

        game_name_var = tk.StringVar(value=game_id or "IoStore")
        row_field(cfg, "Game name (cache):", game_name_var)

        ue_ver_var = tk.StringVar(value=UE_VERSIONS[0])
        r_ue = tk.Frame(cfg, bg=AppColors.BG_CARD)
        r_ue.pack(fill="x", pady=3)
        tk.Label(r_ue, text="UE Version:", font=self._theme.get_font(), bg=AppColors.BG_CARD,
                 fg=AppColors.TEXT_SECONDARY, width=18, anchor="w").pack(side="left")
        ue_combo = ttk.Combobox(r_ue, textvariable=ue_ver_var, values=UE_VERSIONS,
                                width=18, font=self._theme.get_font())
        ue_combo.pack(side="left", padx=6)

        aes_var = tk.StringVar()
        row_field(cfg, "AES Key (optional):", aes_var, show="*")

        extr_mode_var = tk.StringVar(value=EXTRACTION_MODES[0][0])
        r_extr = tk.Frame(cfg, bg=AppColors.BG_CARD)
        r_extr.pack(fill="x", pady=3)
        tk.Label(r_extr, text="Extraction Mode:", font=self._theme.get_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY,
                 width=18, anchor="w").pack(side="left")
        extr_combo = ttk.Combobox(
            r_extr, textvariable=extr_mode_var,
            values=[m[0] for m in EXTRACTION_MODES],
            width=22, font=self._theme.get_font(), state="readonly")
        extr_combo.pack(side="left", padx=6)
        extr_lbl = tk.Label(r_extr, text=EXTRACTION_MODES[0][1],
                            font=self._theme.get_small_font(),
                            bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
        extr_lbl.pack(side="left", padx=6)
        def _on_extr_mode_change(*_):
            val = extr_mode_var.get()
            desc = next((m[1] for m in EXTRACTION_MODES if m[0] == val), "")
            extr_lbl.configure(text=desc)
        extr_mode_var.trace_add("write", _on_extr_mode_change)

        _retoc_default = (self._config.get("tools", {}).get("retoc_path", "")
                          or "D:/GameArabicTranslator/tools/retoc/retoc.exe")
        retoc_var = tk.StringVar(value=_retoc_default)
        r_retoc, _ = row_field(cfg, "retoc.exe:", retoc_var)
        browse_btn(r_retoc, retoc_var, "Select retoc.exe",
                   [("retoc", "retoc.exe"), ("Exe", "*.exe"), ("All", "*.*")])

        _uagui_default = (self._config.get("tools", {}).get("uassetgui_path", "")
                          or "D:/GameArabicTranslator/tools/UAssetGUI.exe")
        uassetgui_var = tk.StringVar(value=_uagui_default)
        r_gui, _ = row_field(cfg, "UAssetGUI.exe:", uassetgui_var)
        browse_btn(r_gui, uassetgui_var, "Select UAssetGUI.exe",
                   [("UAssetGUI", "UAssetGUI.exe"), ("Exe", "*.exe"), ("All", "*.*")])

        mappings_var = tk.StringVar()
        r_map, _ = row_field(cfg, "Mappings (.usmap):", mappings_var)
        tk.Label(r_map, text="optional — name without extension, e.g.  ManorLords",
                 font=self._theme.get_small_font(), bg=AppColors.BG_CARD,
                 fg=AppColors.TEXT_MUTED).pack(side="left", padx=6)

        # ── Step 1 card ────────────────────────────────────────────────
        s1 = card(body, "Step 1 — Extract IoStore → Legacy Files")
        s1_badge = tk.Label(s1, text="⬜ pending", font=self._theme.get_small_font(),
                            bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
        s1_badge.pack(anchor="w", pady=(0, 6))

        tk.Label(s1, text="Select the game's Paks folder (contains .utoc / .ucas / .pak files)",
                 font=self._theme.get_small_font(), bg=AppColors.BG_CARD,
                 fg=AppColors.TEXT_MUTED).pack(anchor="w", pady=(0, 4))

        paks_var = tk.StringVar()
        r_paks, _ = row_field(s1, "Paks folder:", paks_var)
        browse_btn(r_paks, paks_var, "Select Paks folder", folder=True)

        out_dir_var = tk.StringVar()
        r_out, _ = row_field(s1, "Output folder:", out_dir_var)
        browse_btn(r_out, out_dir_var, "Select output folder", folder=True)

        def _autofill_output(*_):
            paks = paks_var.get().strip().rstrip("/\\")
            if paks and not out_dir_var.get().strip():
                parent = os.path.dirname(paks)
                name = os.path.basename(paks)
                out_dir_var.set(os.path.join(parent, name + "_legacy"))
        paks_var.trace_add("write", _autofill_output)

        def _run_step1():
            paks = paks_var.get().strip()
            out = out_dir_var.get().strip()
            if not paks:
                log("ERROR: Please select the Paks folder")
                return
            if not os.path.isdir(paks):
                log(f"ERROR: Paks folder not found: {paks}")
                return
            if not out:
                log("ERROR: Please specify an output folder")
                return
            set_step_status(s1_badge, AppColors.WARNING, "🔄 running…")
            s1_btn.configure(state="disabled")

            def _thread():
                t = _get_translator()
                ok = t.to_legacy(paks, out, aes_var.get().strip())
                if ok:
                    legacy_folder[0] = out
                    set_step_status(s1_badge, AppColors.SUCCESS, "✅ done")
                    log(f"\nOutput legacy folder: {out}\n")
                else:
                    set_step_status(s1_badge, AppColors.ERROR, "❌ failed")
                _safe(lambda: s1_btn.configure(state="normal"))

            threading.Thread(target=_thread, daemon=True).start()

        s1_btn_row = tk.Frame(s1, bg=AppColors.BG_CARD)
        s1_btn_row.pack(anchor="w", pady=(8, 0))

        s1_btn = tk.Button(s1_btn_row, text="▶  Run Step 1",
                           font=self._theme.get_font(style="bold"),
                           bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY,
                           relief="flat", padx=16, pady=5, cursor="hand2",
                           command=_run_step1)
        s1_btn.pack(side="left")

        s1_cache_btn = tk.Button(s1_btn_row, text="📦  Save to for_cache",
                                 font=self._theme.get_font(),
                                 bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_MUTED,
                                 relief="flat", padx=12, pady=5, cursor="hand2",
                                 state="disabled")
        s1_cache_btn.pack(side="left", padx=(8, 0))

        def _save_to_for_cache():
            from games.translation_package import TranslationPackage
            gname = game_name_var.get().strip() or game_name
            legacy = legacy_folder[0] or out_dir_var.get().strip()
            if not legacy or not os.path.isdir(legacy):
                log("ERROR: Run Step 1 first to get a legacy folder")
                return
            p = TranslationPackage()
            ok, lines = p.copy_to_for_cache(gname, legacy)
            for ln in lines:
                log(ln)
            if ok:
                # save wizard config for later re-use
                p.save_wizard_config(gname, {
                    "legacy_name": os.path.basename(legacy),
                    "cache_game_name": gname,
                })
                s1_cache_btn.configure(bg=AppColors.SUCCESS, fg="black",
                                       text="✅ Saved to for_cache")

        s1_cache_btn.configure(command=_save_to_for_cache)

        # unlock Save button after Step 1 succeeds
        _orig_run_step1 = _run_step1
        def _run_step1_with_unlock():
            _orig_run_step1()
            # enable after thread starts (badge turns green)
            def _check():
                if s1_badge.cget("fg") == AppColors.SUCCESS:
                    s1_cache_btn.configure(state="normal",
                                           bg=AppColors.BG_LIGHT,
                                           fg=AppColors.TEXT_PRIMARY)
                else:
                    self.root.after(500, _check)
            self.root.after(500, _check)
        s1_btn.configure(command=_run_step1_with_unlock)

        # ── Step 2 card ────────────────────────────────────────────────
        s2 = card(body, "Step 2 — Convert .uasset → JSON")
        s2_badge = tk.Label(s2, text="⬜ pending", font=self._theme.get_small_font(),
                            bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
        s2_badge.pack(anchor="w", pady=(0, 6))

        mode_var = tk.StringVar(value="all")
        r_mode = tk.Frame(s2, bg=AppColors.BG_CARD)
        r_mode.pack(anchor="w", pady=(0, 4))
        tk.Radiobutton(r_mode, text="All .uasset files in legacy folder",
                       variable=mode_var, value="all",
                       font=self._theme.get_font(), bg=AppColors.BG_CARD,
                       fg=AppColors.TEXT_PRIMARY, selectcolor=AppColors.BG_LIGHT,
                       activebackground=AppColors.BG_CARD).pack(side="left")
        tk.Radiobutton(r_mode, text="Single file",
                       variable=mode_var, value="single",
                       font=self._theme.get_font(), bg=AppColors.BG_CARD,
                       fg=AppColors.TEXT_PRIMARY, selectcolor=AppColors.BG_LIGHT,
                       activebackground=AppColors.BG_CARD).pack(side="left", padx=(12, 0))

        single_var = tk.StringVar()
        r_single, _ = row_field(s2, ".uasset file:", single_var)
        browse_btn(r_single, single_var, "Select .uasset file",
                   [("UAsset", "*.uasset"), ("All", "*.*")])

        s2_info = tk.Label(s2, text="", font=self._theme.get_small_font(),
                           bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
        s2_info.pack(anchor="w", pady=(4, 0))

        def _run_step2():
            ue = ue_ver_var.get().strip()
            if not ue:
                log("ERROR: Select a UE Version first")
                return
            mode = mode_var.get()
            if mode == "all":
                folder = legacy_folder[0] or out_dir_var.get().strip()
                if not folder or not os.path.isdir(folder):
                    log("ERROR: Legacy folder not found — run Step 1 first or set output folder")
                    return
            else:
                if not single_var.get().strip():
                    log("ERROR: Select a .uasset file")
                    return

            set_step_status(s2_badge, AppColors.WARNING, "🔄 running…")
            s2_btn.configure(state="disabled")

            def _thread():
                t = _get_translator()
                _maps = mappings_var.get().strip()
                if mode == "all":
                    folder = legacy_folder[0] or out_dir_var.get().strip()
                    paths = t.uasset_folder_to_json(folder, ue, _maps)
                else:
                    p = t.uasset_to_json(single_var.get().strip(), ue, _maps)
                    paths = [p] if p else []

                if not paths:
                    set_step_status(s2_badge, AppColors.ERROR, "❌ no JSON created")
                    _safe(lambda: s2_btn.configure(state="normal"))
                    return

                json_paths[0] = paths
                # Extract translatable texts
                _mode = extr_mode_var.get()
                all_t = []
                for jp in paths:
                    all_t.extend(t.extract_texts_from_json(jp, _mode))
                seen = set()
                uniq = [x for x in all_t if x not in seen and not seen.add(x)]
                all_texts[0] = uniq

                count_msg = f"{len(paths)} JSON file(s), {len(uniq)} unique string(s) to translate"
                log(f"\n{count_msg}\n")
                set_step_status(s2_badge, AppColors.SUCCESS, "✅ done")
                _safe(lambda: s2_info.configure(text=count_msg, fg=AppColors.SUCCESS))
                _safe(lambda: s2_btn.configure(state="normal"))
                _safe(lambda: s3_strings_lbl.configure(
                    text=f"Strings to translate: {len(uniq)}"))

            threading.Thread(target=_thread, daemon=True).start()

        s2_btn = tk.Button(s2, text="▶  Run Step 2",
                           font=self._theme.get_font(style="bold"),
                           bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY,
                           relief="flat", padx=16, pady=5, cursor="hand2",
                           command=_run_step2)
        s2_btn.pack(anchor="w", pady=(8, 0))

        # ── Step 3 card ────────────────────────────────────────────────
        s3 = card(body, "Step 3 — Translate")
        s3_badge = tk.Label(s3, text="⬜ pending", font=self._theme.get_small_font(),
                            bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
        s3_badge.pack(anchor="w", pady=(0, 4))

        s3_strings_lbl = tk.Label(s3, text="Strings to translate: —",
                                  font=self._theme.get_font(),
                                  bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY)
        s3_strings_lbl.pack(anchor="w", pady=(0, 4))

        # ── Load existing JSON (skip Steps 1 & 2) ─────────────────────
        s3_load_frame = tk.Frame(s3, bg=AppColors.BG_LIGHT, padx=12, pady=8)
        s3_load_frame.pack(fill="x", pady=(0, 8))
        tk.Label(s3_load_frame,
                 text="📂  Load existing .uasset.json  (skip Steps 1 & 2 if file already ready)",
                 font=self._theme.get_small_font(),
                 bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_MUTED).pack(anchor="w", pady=(0, 4))

        load_json_var = tk.StringVar()
        r_load = tk.Frame(s3_load_frame, bg=AppColors.BG_LIGHT)
        r_load.pack(fill="x")
        load_json_entry = tk.Entry(r_load, textvariable=load_json_var,
                                   font=self._theme.get_font(),
                                   bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY,
                                   insertbackground=AppColors.TEXT_PRIMARY,
                                   relief="flat", width=45)
        load_json_entry.pack(side="left", ipady=4, fill="x", expand=True)

        def _browse_json_file():
            p = filedialog.askopenfilename(
                title="Select .uasset.json file",
                filetypes=[("UAsset JSON", "*.json"), ("All files", "*.*")])
            if p:
                load_json_var.set(p)

        def _load_json_into_step3():
            jp = load_json_var.get().strip()
            if not jp:
                log("ERROR: select a .uasset.json file first")
                return
            if not os.path.isfile(jp):
                log(f"ERROR: file not found: {jp}")
                return
            t = _get_translator()
            texts = t.extract_texts_from_json(jp, extr_mode_var.get())
            if not texts:
                log(f"WARNING: no DefaultText strings found in {os.path.basename(jp)}")
                return
            json_paths[0] = [jp]
            all_texts[0] = texts
            log(f"Loaded: {os.path.basename(jp)}  →  {len(texts)} unique strings")
            _safe(lambda: s3_strings_lbl.configure(
                text=f"Strings to translate: {len(texts)}  (from loaded JSON)"))

        tk.Button(r_load, text="📂", font=self._theme.get_small_font(),
                  bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY,
                  relief="flat", padx=8, pady=3, cursor="hand2",
                  command=_browse_json_file).pack(side="left", padx=4)
        tk.Button(r_load, text="Load →", font=self._theme.get_font(-2, "bold"),
                  bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY,
                  relief="flat", padx=10, pady=3, cursor="hand2",
                  command=_load_json_into_step3).pack(side="left", padx=2)

        def _open_translate_popup():
            texts = all_texts[0]
            if not texts:
                log("ERROR: No texts found — run Step 2 first (or load a JSON file above)")
                return
            gname = game_name_var.get().strip() or "IoStore"

            dlg = tk.Toplevel(win)
            dlg.title(f"🌐 Translate: {gname}")
            dlg.geometry("650x560")
            dlg.configure(bg=AppColors.BG_DARK)
            dlg.transient(win)
            x = win.winfo_x() + max(0, (win.winfo_width()  - 650) // 2)
            y = win.winfo_y() + max(0, (win.winfo_height() - 560) // 2)
            dlg.geometry(f"+{x}+{y}")

            tk.Label(dlg, text=f"🌐 Translate: {gname}",
                     font=("Segoe UI", 16, "bold"),
                     bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(pady=(15, 5))

            # ── Model + mode ───────────────────────────────────────────
            mf = tk.Frame(dlg, bg=AppColors.BG_CARD, padx=15, pady=12)
            mf.pack(fill="x", padx=15, pady=(5, 5))

            tk.Label(mf, text="نموذج الترجمة:", font=("Segoe UI", 10, "bold"),
                     bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 6))

            model_row = tk.Frame(mf, bg=AppColors.BG_CARD)
            model_row.pack(fill="x")

            available_models = []
            if self._translation_engine:
                for m in self._translation_engine.get_available_models():
                    available_models.append(m["key"])

            _dlg_model_var = tk.StringVar(
                value=self._translation_engine.get_active_model()
                      if self._translation_engine else "")
            ttk.Combobox(model_row, textvariable=_dlg_model_var,
                         values=available_models, state="readonly",
                         width=25, font=("Segoe UI", 10)).pack(side="left")

            cached_models = self._cache.get_models_for_game(gname) if self._cache else []
            if cached_models:
                tk.Label(model_row, text="  or use cached from:",
                         font=("Segoe UI", 9),
                         bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY).pack(side="left", padx=(15, 5))
                _cached_var = tk.StringVar()
                ttk.Combobox(model_row, textvariable=_cached_var,
                             values=cached_models, state="readonly",
                             width=20, font=("Segoe UI", 9)).pack(side="left")

            mode_frame = tk.Frame(mf, bg=AppColors.BG_CARD)
            mode_frame.pack(fill="x", pady=(10, 0))
            _mode_var = tk.StringVar(value="missing")
            _rb = dict(font=("Segoe UI", 9), bg=AppColors.BG_CARD,
                       fg=AppColors.TEXT_SECONDARY, selectcolor=AppColors.ENTRY_BG,
                       activebackground=AppColors.BG_CARD, variable=_mode_var)
            tk.Radiobutton(mode_frame, text="🆕 ترجمة من الصفر (حذف القديم وإعادة الترجمة)",
                           value="fresh",      **_rb).pack(anchor="w")
            tk.Radiobutton(mode_frame, text="📦 استخدام الكاش فقط (بدون استدعاءات API جديدة)",
                           value="cache_only", **_rb).pack(anchor="w")
            tk.Radiobutton(mode_frame, text="🔄 استكمال المفقود (الاحتفاظ بالموجود وترجمة الجديد)",
                           value="missing",    **_rb).pack(anchor="w")

            opts_frame = tk.Frame(mf, bg=AppColors.BG_CARD)
            opts_frame.pack(fill="x", pady=(8, 0))
            _reshape_var = tk.BooleanVar(value=False)
            tk.Checkbutton(opts_frame,
                           text="🔤 قلب النصوص العربية (Arabic Reshaping)",
                           variable=_reshape_var,
                           font=("Segoe UI", 9), bg=AppColors.BG_CARD,
                           fg=AppColors.TEXT_SECONDARY, selectcolor=AppColors.ENTRY_BG,
                           activebackground=AppColors.BG_CARD).pack(anchor="w")
            tk.Label(opts_frame,
                     text="  شغّلها لألعاب Unity/tkinter | أوقفها لألعاب UE4 locres (تتحمل العربية بنفسها)",
                     font=("Segoe UI", 8), bg=AppColors.BG_CARD,
                     fg=AppColors.TEXT_MUTED).pack(anchor="w")

            # ── Progress ───────────────────────────────────────────────
            pf = tk.Frame(dlg, bg=AppColors.BG_CARD, padx=20, pady=12)
            pf.pack(fill="x", padx=15, pady=5)
            _prog_lbl = tk.Label(pf, text="Ready", font=("Segoe UI", 10),
                                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY)
            _prog_lbl.pack(anchor="w")
            _prog_bar = ttk.Progressbar(pf, length=600, mode="determinate")
            _prog_bar.pack(fill="x", pady=(6, 0))
            _stats_lbl = tk.Label(pf, text="", font=("Segoe UI", 9),
                                  bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
            _stats_lbl.pack(anchor="w", pady=(4, 0))

            # ── Log ────────────────────────────────────────────────────
            lf = tk.Frame(dlg, bg=AppColors.ENTRY_BG)
            lf.pack(fill="both", expand=True, padx=15, pady=(5, 8))
            _log_txt = tk.Text(lf, height=8, font=("Consolas", 9),
                               bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_SECONDARY,
                               relief="flat", padx=8, pady=5,
                               wrap="word", state="disabled")
            _log_sb = ttk.Scrollbar(lf, command=_log_txt.yview)
            _log_txt.configure(yscrollcommand=_log_sb.set)
            _log_txt.pack(side="left", fill="both", expand=True)
            _log_sb.pack(side="right", fill="y")

            def _dlg_log(msg):
                if _log_txt.winfo_exists():
                    _log_txt.configure(state="normal")
                    _log_txt.insert("end", msg + "\n")
                    _log_txt.see("end")
                    _log_txt.configure(state="disabled")

            def _dlg_progress(current, total, cached=0, failed=0):
                if not _prog_bar.winfo_exists():
                    return
                pct = (current / total * 100) if total else 0
                _prog_bar["value"] = pct
                _prog_lbl.configure(text=f"Progress: {current}/{total} ({pct:.0f}%)")
                _stats_lbl.configure(
                    text=f"New: {current - cached - failed} | Cached: {cached} | Failed: {failed}")

            # ── Buttons ────────────────────────────────────────────────
            bf = tk.Frame(dlg, bg=AppColors.BG_DARK)
            bf.pack(fill="x", padx=15, pady=(0, 12))

            _stop_flag = [False]
            _active = [None]
            _paused = [False]

            def _start():
                selected_model = _dlg_model_var.get()
                if selected_model and self._translation_engine:
                    self._translation_engine.set_active_model(selected_model)
                    self._translation_engine.load_model(selected_model)

                mode = _mode_var.get()
                if mode == "fresh":
                    translations[0] = {}
                    _dlg_log("Mode: Fresh — clearing previous translations")

                _paused[0] = False
                self._translation_running = True
                _start_btn.configure(state="disabled")
                _pause_btn.configure(state="normal", text="⏸  Pause")
                _stop_btn.configure(state="normal")
                set_step_status(s3_badge, AppColors.WARNING, "🔄 translating…")

                def _thread():
                    t = _get_translator()
                    _active[0] = t
                    _active_translator[0] = t

                    def _prog_cb(current, total):
                        pct = (current / total * 100) if total else 0
                        if _prog_bar.winfo_exists():
                            _prog_bar["value"] = pct
                            _prog_lbl.configure(
                                text=f"Progress: {current}/{total} ({pct:.0f}%)")

                    t.set_callbacks(log=_dlg_log, progress=_prog_cb)
                    existing = translations[0]


                    if mode == "cache_only":
                        remaining = [tx for tx in texts if tx not in existing]
                        _dlg_log(f"Cache-only: looking up {len(remaining)} texts…")
                        if t.cache:
                            hits = t.cache.get_batch(gname, remaining)
                            existing.update(hits)
                        translations[0] = existing
                        _active[0] = None
                        _active_translator[0] = None
                        _extr = extr_mode_var.get()
                        for jp in json_paths[0]:
                            t.apply_translations_to_json(jp, existing, _extr)
                        count = len(existing)
                        _dlg_log(f"Done: {count}/{len(texts)} from cache")
                        set_step_status(s3_badge,
                            AppColors.SUCCESS if count else AppColors.WARNING,
                            f"✅ {count}/{len(texts)} from cache" if count else "⚠️ 0 cached")
                        _safe(lambda: _start_btn.configure(state="normal"))
                        _safe(lambda: _pause_btn.configure(state="disabled"))
                        _safe(lambda: _stop_btn.configure(state="disabled"))
                        self._translation_running = False
                        return

                    # For "missing" mode: pre-load ALL existing cache entries so we
                    # know exactly which strings still need translation (avoids
                    # starting from 0 and re-scanning 10000 texts redundantly).
                    if mode == "missing" and self._cache:
                        pre_hits = self._cache.get_batch(gname, texts)
                        new_from_cache = {k: v for k, v in pre_hits.items()
                                          if k not in existing}
                        if new_from_cache:
                            existing.update(new_from_cache)
                            translations[0] = existing
                            _dlg_log(f"الكاش: {len(existing)}/{len(texts)} مترجم مسبقاً")

                    remaining = ([tx for tx in texts if tx not in existing]
                                 if mode == "missing" else texts)
                    if mode == "missing":
                        _dlg_log(f"المتبقي للترجمة: {len(remaining)}/{len(texts)}")
                        # Update progress bar to reflect already-done items
                        _already_done = len(existing)
                        _total_all = len(texts)
                        def _prog_cb_resume(current, total):
                            actual = _already_done + current
                            pct = (actual / _total_all * 100) if _total_all else 0
                            if _prog_bar.winfo_exists():
                                _prog_bar["value"] = pct
                                _prog_lbl.configure(
                                    text=f"Progress: {actual}/{_total_all} ({pct:.0f}%)")
                        t.set_callbacks(log=_dlg_log, progress=_prog_cb_resume)
                        _prog_bar["value"] = (_already_done / _total_all * 100) if _total_all else 0
                        _prog_lbl.configure(text=f"Progress: {_already_done}/{_total_all} ({_already_done/_total_all*100:.0f}%)" if _total_all else "")

                    new_results = t.translate_texts(remaining, gname,
                                                    use_cache=False if mode == "missing" else (mode != "fresh"))
                    existing.update(new_results)
                    translations[0] = existing
                    _active[0] = None
                    _active_translator[0] = None

                    _extr = extr_mode_var.get()
                    if existing:
                        for jp in json_paths[0]:
                            t.apply_translations_to_json(jp, existing, _extr)
                        _dlg_log(f"\nDone: {len(existing)}/{len(texts)} translated")
                        set_step_status(s3_badge, AppColors.SUCCESS,
                                        f"✅ {len(existing)}/{len(texts)} translated")
                    else:
                        set_step_status(s3_badge, AppColors.WARNING, "⚠️ 0 translated")

                    self._translation_running = False
                    _safe(lambda: _start_btn.configure(state="normal"))
                    _safe(lambda: _pause_btn.configure(state="disabled"))
                    _safe(lambda: _stop_btn.configure(state="disabled"))

                threading.Thread(target=_thread, daemon=True).start()

            def _toggle_pause():
                t = _active[0]
                if _paused[0]:
                    _paused[0] = False
                    if t:
                        t.resume()
                    _pause_btn.configure(text="⏸  Pause")
                    _dlg_log("Resumed…")
                else:
                    _paused[0] = True
                    if t:
                        t.pause()
                    _pause_btn.configure(text="▶  Resume")
                    _dlg_log("Paused — press Resume to continue")

            def _stop():
                t = _active[0]
                if t:
                    t.resume()
                    t.stop()
                _paused[0] = False
                _dlg_log("Stop requested…")

            def _apply_cached():
                gn = game_name_var.get().strip() or "IoStore"
                if not self._cache:
                    _dlg_log("ERROR: Cache not available")
                    return
                t = _get_translator()
                hits = self._cache.get_batch(gn, texts)
                if hits:
                    translations[0].update(hits)
                    _extr = extr_mode_var.get()
                    for jp in json_paths[0]:
                        t.apply_translations_to_json(jp, translations[0], _extr)
                    _dlg_log(f"Applied {len(hits)} cached translations")
                    set_step_status(s3_badge, AppColors.SUCCESS,
                                    f"✅ {len(hits)}/{len(texts)} from cache")
                else:
                    _dlg_log(f"0 cache hits for game '{gn}'")

            _start_btn = tk.Button(bf, text="▶  Start Translation",
                font=("Segoe UI", 10, "bold"), bg=AppColors.SUCCESS, fg="black",
                relief="flat", padx=15, pady=5, cursor="hand2", command=_start)
            _start_btn.pack(side="left")
            _pause_btn = tk.Button(bf, text="⏸  Pause",
                font=("Segoe UI", 10), bg="#e67e22", fg="white",
                relief="flat", padx=12, pady=5, cursor="hand2",
                state="disabled", command=_toggle_pause)
            _pause_btn.pack(side="left", padx=4)
            _stop_btn = tk.Button(bf, text="⏹  Stop",
                font=("Segoe UI", 10), bg=AppColors.ERROR, fg="white",
                relief="flat", padx=12, pady=5, cursor="hand2",
                state="disabled", command=_stop)
            _stop_btn.pack(side="left", padx=4)
            tk.Button(bf, text="📦  Apply Cached",
                font=("Segoe UI", 10), bg="#8e44ad", fg="white",
                relief="flat", padx=12, pady=5, cursor="hand2",
                command=_apply_cached).pack(side="left", padx=6)
            tk.Button(bf, text="Close",
                font=("Segoe UI", 10), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY,
                relief="flat", padx=15, pady=5, cursor="hand2",
                command=dlg.destroy).pack(side="right")

        tk.Button(s3, text="🌐  Translate",
                  font=self._theme.get_font(style="bold"),
                  bg=AppColors.SUCCESS, fg="black",
                  relief="flat", padx=20, pady=6, cursor="hand2",
                  command=_open_translate_popup).pack(anchor="w", pady=(4, 0))

        # ── Step 3b card (optional) ─────────────────────────────────────
        s3b = card(body, "Step 3b — Font Replacement  (Optional)")
        s3b_badge = tk.Label(s3b, text="⬜ skipped", font=self._theme.get_small_font(),
                             bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
        s3b_badge.pack(anchor="w", pady=(0, 6))

        # Fonts folder
        r_fonts = tk.Frame(s3b, bg=AppColors.BG_CARD)
        r_fonts.pack(fill="x", pady=2)
        tk.Label(r_fonts, text="Fonts folder:", width=16, anchor="w",
                 font=self._theme.get_small_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY).pack(side="left")
        fonts_folder_var = tk.StringVar()
        tk.Entry(r_fonts, textvariable=fonts_folder_var, width=42,
                 bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY,
                 insertbackground=AppColors.TEXT_PRIMARY,
                 relief="flat", font=self._theme.get_small_font()).pack(side="left", padx=4)
        def _browse_fonts_folder():
            d = filedialog.askdirectory(title="Select Fonts folder")
            if d:
                fonts_folder_var.set(d)
        tk.Button(r_fonts, text="Browse", font=self._theme.get_small_font(),
                  bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY,
                  relief="flat", padx=8, pady=3, cursor="hand2",
                  command=_browse_fonts_folder).pack(side="left", padx=4)

        # Arabic font file
        r_arfont = tk.Frame(s3b, bg=AppColors.BG_CARD)
        r_arfont.pack(fill="x", pady=2)
        tk.Label(r_arfont, text="Arabic font:", width=16, anchor="w",
                 font=self._theme.get_small_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY).pack(side="left")
        arabic_font_var = tk.StringVar(
            value=r"D:\GameArabicTranslator\assets\fonts\Aljazeera.ttf")
        tk.Entry(r_arfont, textvariable=arabic_font_var, width=42,
                 bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY,
                 insertbackground=AppColors.TEXT_PRIMARY,
                 relief="flat", font=self._theme.get_small_font()).pack(side="left", padx=4)
        def _browse_arabic_font():
            p = filedialog.askopenfilename(
                title="Select Arabic font",
                filetypes=[("Font files", "*.ttf *.otf"), ("All files", "*.*")])
            if p:
                arabic_font_var.set(p)
        tk.Button(r_arfont, text="Browse", font=self._theme.get_small_font(),
                  bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY,
                  relief="flat", padx=8, pady=3, cursor="hand2",
                  command=_browse_arabic_font).pack(side="left", padx=4)

        # Font name entry + Add button
        r_addname = tk.Frame(s3b, bg=AppColors.BG_CARD)
        r_addname.pack(fill="x", pady=(10, 2))
        tk.Label(r_addname, text="Font name (no ext):", width=16, anchor="w",
                 font=self._theme.get_small_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY).pack(side="left")
        font_name_var = tk.StringVar()
        font_name_entry = tk.Entry(r_addname, textvariable=font_name_var, width=30,
                                   bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY,
                                   insertbackground=AppColors.TEXT_PRIMARY,
                                   relief="flat", font=self._theme.get_small_font())
        font_name_entry.pack(side="left", padx=4)

        # Names listbox
        list_frame = tk.Frame(s3b, bg=AppColors.BG_CARD)
        list_frame.pack(fill="x", pady=(4, 0))
        font_listbox = tk.Listbox(list_frame, height=5,
                                  bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY,
                                  selectbackground=AppColors.ACCENT,
                                  font=self._theme.get_small_font(),
                                  relief="flat", borderwidth=1,
                                  activestyle="none")
        font_listbox.pack(side="left", fill="x", expand=True)
        sb_fl = tk.Scrollbar(list_frame, orient="vertical", command=font_listbox.yview)
        sb_fl.pack(side="left", fill="y")
        font_listbox.configure(yscrollcommand=sb_fl.set)

        def _add_font_name(event=None):
            name = font_name_var.get().strip()
            if not name:
                return
            if name.lower().endswith(".ufont"):
                name = name[:-6]
            if name not in font_listbox.get(0, "end"):
                font_listbox.insert("end", name)
            font_name_var.set("")
            font_name_entry.focus()

        font_name_entry.bind("<Return>", _add_font_name)

        def _remove_font_name():
            for i in reversed(font_listbox.curselection()):
                font_listbox.delete(i)

        def _apply_fonts():
            import shutil
            fonts_dir = fonts_folder_var.get().strip()
            src_font  = arabic_font_var.get().strip()
            names     = list(font_listbox.get(0, "end"))
            if not fonts_dir or not os.path.isdir(fonts_dir):
                log("Font step ERROR: Fonts folder not found")
                set_step_status(s3b_badge, AppColors.ERROR, "❌ no folder")
                return
            if not src_font or not os.path.isfile(src_font):
                log("Font step ERROR: Arabic font file not found")
                set_step_status(s3b_badge, AppColors.ERROR, "❌ font missing")
                return
            if not names:
                log("Font step ERROR: No font names entered")
                set_step_status(s3b_badge, AppColors.ERROR, "❌ no names")
                return
            set_step_status(s3b_badge, AppColors.WARNING, "🔄 copying…")
            ok = 0
            for name in names:
                dest = os.path.join(fonts_dir, name + ".ufont")
                try:
                    shutil.copy2(src_font, dest)
                    log(f"  font → {name}.ufont")
                    ok += 1
                except Exception as e:
                    log(f"  ERROR {name}.ufont: {e}")
            set_step_status(
                s3b_badge,
                AppColors.SUCCESS if ok == len(names) else AppColors.WARNING,
                f"✅ {ok}/{len(names)} fonts copied")

        r_s3b_btns = tk.Frame(s3b, bg=AppColors.BG_CARD)
        r_s3b_btns.pack(fill="x", pady=(4, 0))
        tk.Button(r_addname, text="Add", font=self._theme.get_font(-2, "bold"),
                  bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY,
                  relief="flat", padx=10, pady=3, cursor="hand2",
                  command=_add_font_name).pack(side="left", padx=4)
        tk.Button(r_s3b_btns, text="Remove Selected", font=self._theme.get_small_font(),
                  bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY,
                  relief="flat", padx=8, pady=3, cursor="hand2",
                  command=_remove_font_name).pack(side="left")
        tk.Button(r_s3b_btns, text="▶  Apply Fonts", font=self._theme.get_font(-1, "bold"),
                  bg=AppColors.SUCCESS, fg=AppColors.BG_DARK,
                  relief="flat", padx=14, pady=5, cursor="hand2",
                  command=_apply_fonts).pack(side="right")

        # ── Step 4 card — fromjson ─────────────────────────────────────
        s4 = card(body, "Step 4 — Convert JSON → .uasset")
        s4_badge = tk.Label(s4, text="⬜ pending", font=self._theme.get_small_font(),
                            bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
        s4_badge.pack(anchor="w", pady=(0, 4))
        tk.Label(s4, text="Converts the translated .uasset.json files back to .uasset using UAssetGUI.",
                 font=self._theme.get_small_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED).pack(anchor="w", pady=(0, 4))

        def _run_step4():
            ue = ue_ver_var.get().strip()
            if not ue:
                log("ERROR: Select a UE Version in Configuration")
                return
            if not json_paths[0]:
                log("ERROR: No JSON files — run Step 2 or load a JSON file first")
                return

            set_step_status(s4_badge, AppColors.WARNING, "🔄 running…")
            s4_btn.configure(state="disabled")

            def _thread():
                t = _get_translator()
                _maps = mappings_var.get().strip()
                converted = 0
                for jp in json_paths[0]:
                    if t.json_to_uasset(jp, ue, _maps):
                        converted += 1
                log(f"fromjson: {converted}/{len(json_paths[0])} files converted")
                if converted:
                    set_step_status(s4_badge, AppColors.SUCCESS,
                                    f"✅ {converted}/{len(json_paths[0])} converted")
                else:
                    set_step_status(s4_badge, AppColors.ERROR, "❌ failed")
                _safe(lambda: s4_btn.configure(state="normal"))

            threading.Thread(target=_thread, daemon=True).start()

        s4_btn = tk.Button(s4, text="▶  Run Step 4",
                           font=self._theme.get_font(style="bold"),
                           bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY,
                           relief="flat", padx=16, pady=5, cursor="hand2",
                           command=_run_step4)
        s4_btn.pack(anchor="w", pady=(8, 0))

        # ── Step 5 card — retoc to-zen ────────────────────────────────
        s5 = card(body, "Step 5 — Repack IoStore  (retoc to-zen)")
        s5_badge = tk.Label(s5, text="⬜ pending", font=self._theme.get_small_font(),
                            bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
        s5_badge.pack(anchor="w", pady=(0, 6))

        zen_ver_var = tk.StringVar(value=ZEN_VERSIONS[0])
        r_zen = tk.Frame(s5, bg=AppColors.BG_CARD)
        r_zen.pack(fill="x", pady=3)
        tk.Label(r_zen, text="UE Version (to-zen):", font=self._theme.get_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY,
                 width=18, anchor="w").pack(side="left")
        ttk.Combobox(r_zen, textvariable=zen_ver_var, values=ZEN_VERSIONS,
                     width=14, font=self._theme.get_font()).pack(side="left", padx=6)
        tk.Label(r_zen, text="passed as:  retoc to-zen --version <VALUE>",
                 font=self._theme.get_small_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED).pack(side="left", padx=4)

        # ── Legacy folder field (manual override) ────────────────────
        s5_legacy_var = tk.StringVar()
        r_s5_legacy = tk.Frame(s5, bg=AppColors.BG_CARD)
        r_s5_legacy.pack(fill="x", pady=3)
        tk.Label(r_s5_legacy, text="Legacy folder:", font=self._theme.get_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY,
                 width=18, anchor="w").pack(side="left")
        tk.Entry(r_s5_legacy, textvariable=s5_legacy_var, width=42,
                 bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY,
                 insertbackground=AppColors.TEXT_PRIMARY,
                 relief="flat", font=self._theme.get_font()).pack(side="left", padx=4)
        def _browse_s5_legacy():
            d = filedialog.askdirectory(title="Select Legacy folder (Paks_legacy)")
            if d:
                s5_legacy_var.set(d)
        tk.Button(r_s5_legacy, text="Browse", font=self._theme.get_small_font(),
                  bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY,
                  relief="flat", padx=8, pady=3, cursor="hand2",
                  command=_browse_s5_legacy).pack(side="left", padx=4)
        tk.Label(r_s5_legacy, text="auto-filled by Step 1",
                 font=self._theme.get_small_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED).pack(side="left", padx=4)

        # keep s5_legacy_var in sync with legacy_folder[0] when Step 1 runs
        def _sync_s5_legacy(*_):
            if legacy_folder[0] and not s5_legacy_var.get().strip():
                s5_legacy_var.set(legacy_folder[0])
        out_dir_var.trace_add("write", _sync_s5_legacy)

        output_base_var = tk.StringVar()
        r_base = tk.Frame(s5, bg=AppColors.BG_CARD)
        r_base.pack(fill="x", pady=3)
        tk.Label(r_base, text="Output base path:", font=self._theme.get_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY,
                 width=18, anchor="w").pack(side="left")
        tk.Entry(r_base, textvariable=output_base_var, width=42,
                 bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY,
                 insertbackground=AppColors.TEXT_PRIMARY,
                 relief="flat", font=self._theme.get_font()).pack(side="left", padx=4)
        def _browse_output_base():
            d = filedialog.askdirectory(title="Select output folder for pak files")
            if d:
                paks = paks_var.get().strip().rstrip("/\\")
                name = os.path.basename(paks) if paks else "Paks"
                output_base_var.set(os.path.join(d, name + "_translated"))
        tk.Button(r_base, text="Browse", font=self._theme.get_small_font(),
                  bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY,
                  relief="flat", padx=8, pady=3, cursor="hand2",
                  command=_browse_output_base).pack(side="left", padx=4)
        tk.Label(r_base, text="will produce: <path>_P.utoc + _P.ucas",
                 font=self._theme.get_small_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED).pack(side="left", padx=4)

        def _autofill_output_base(*_):
            paks = paks_var.get().strip().rstrip("/\\")
            if paks and not output_base_var.get().strip():
                parent = os.path.dirname(paks)
                name = os.path.basename(paks)
                output_base_var.set(os.path.join(parent, name + "_translated"))
        paks_var.trace_add("write", _autofill_output_base)

        def _run_step5():
            folder = s5_legacy_var.get().strip() or legacy_folder[0] or out_dir_var.get().strip()
            base   = output_base_var.get().strip()
            if not folder or not os.path.isdir(folder):
                log("ERROR: Legacy folder not found — set it manually or run Step 1 first")
                return
            if not base:
                log("ERROR: Specify output base path")
                return

            set_step_status(s5_badge, AppColors.WARNING, "🔄 running…")
            s5_btn.configure(state="disabled")

            # to_zen strips .utoc suffix then adds _P.utoc — compute actual output
            clean = base[:-5] if base.endswith(".utoc") else base
            actual_base = clean + "_P"   # e.g. D:/Paks/Paks_translated_P

            def _thread():
                t = _get_translator()
                ok = t.to_zen(folder, base, zen_ver_var.get(), aes_var.get().strip())
                if ok:
                    log(f"\nOutput files:")
                    log(f"  {actual_base}.utoc")
                    log(f"  {actual_base}.ucas")
                    set_step_status(s5_badge, AppColors.SUCCESS, "✅ done")
                    _safe(lambda: s5_ready_btn.configure(
                        state="normal",
                        bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY))
                else:
                    set_step_status(s5_badge, AppColors.ERROR, "❌ failed")
                _safe(lambda: s5_btn.configure(state="normal"))

            threading.Thread(target=_thread, daemon=True).start()

        s5_btn_row = tk.Frame(s5, bg=AppColors.BG_CARD)
        s5_btn_row.pack(anchor="w", pady=(8, 0))

        s5_btn = tk.Button(s5_btn_row, text="▶  Run Step 5",
                           font=self._theme.get_font(style="bold"),
                           bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY,
                           relief="flat", padx=16, pady=5, cursor="hand2",
                           command=_run_step5)
        s5_btn.pack(side="left")

        s5_ready_btn = tk.Button(s5_btn_row, text="✅  Save to ready",
                                 font=self._theme.get_font(),
                                 bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_MUTED,
                                 relief="flat", padx=12, pady=5, cursor="hand2",
                                 state="disabled")
        s5_ready_btn.pack(side="left", padx=(8, 0))

        # game target dir (full path to game's Paks folder)
        r_game_tgt = tk.Frame(s5, bg=AppColors.BG_CARD)
        r_game_tgt.pack(fill="x", pady=(6, 0))
        tk.Label(r_game_tgt, text="Game Paks dir (target):", font=self._theme.get_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY,
                 width=22, anchor="w").pack(side="left")
        game_tgt_var = tk.StringVar()
        tk.Entry(r_game_tgt, textvariable=game_tgt_var, width=38,
                 bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY,
                 insertbackground=AppColors.TEXT_PRIMARY,
                 relief="flat", font=self._theme.get_font()).pack(side="left", padx=4)
        def _browse_game_tgt():
            d = filedialog.askdirectory(title="Select game's Paks folder")
            if d:
                game_tgt_var.set(d)
        tk.Button(r_game_tgt, text="Browse", font=self._theme.get_small_font(),
                  bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY,
                  relief="flat", padx=8, pady=3, cursor="hand2",
                  command=_browse_game_tgt).pack(side="left", padx=4)
        tk.Label(r_game_tgt, text="copy here after Step 5",
                 font=self._theme.get_small_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED).pack(side="left", padx=4)

        def _save_to_ready():
            import shutil as _shutil
            from games.translation_package import TranslationPackage
            gname = game_name_var.get().strip() or game_name
            base  = output_base_var.get().strip()
            if not base:
                log("ERROR: Set Output base path in Step 5 first")
                return
            clean = base[:-5] if base.endswith(".utoc") else base
            actual_base = clean + "_P"
            p = TranslationPackage()
            ok, lines = p.save_paks_to_ready(gname, actual_base, game_tgt_var.get().strip())
            for ln in lines:
                log(ln)
            if ok:
                p.save_wizard_config(gname, {
                    "zen_version":    zen_ver_var.get(),
                    "ue_version":     ue_ver_var.get(),
                    "extraction_mode": extr_mode_var.get(),
                    "mappings":       mappings_var.get(),
                    "output_base":    base,
                    "game_target_dir": game_tgt_var.get().strip(),
                })
                # direct install to game Paks folder
                paks_dir = game_tgt_var.get().strip()
                if paks_dir and os.path.isdir(paks_dir):
                    for ext in (".pak", ".ucas", ".utoc"):
                        src = actual_base + ext
                        if os.path.isfile(src):
                            dst = os.path.join(paks_dir, os.path.basename(src))
                            try:
                                _shutil.copy2(src, dst)
                                log(f"✓ Installed: {os.path.basename(src)}  →  {paks_dir}")
                            except Exception as e:
                                log(f"ERROR installing {os.path.basename(src)}: {e}")
                # cleanup output dir
                for ext in (".pak", ".ucas", ".utoc"):
                    f = actual_base + ext
                    if os.path.isfile(f):
                        try:
                            os.remove(f)
                            log(f"🗑 Removed: {os.path.basename(f)}")
                        except Exception as e:
                            log(f"WARNING: could not remove {os.path.basename(f)}: {e}")
                s5_ready_btn.configure(bg=AppColors.SUCCESS, fg="black",
                                       text="✅ Saved to ready")
                self._safe_after(200, self._refresh_home_games)

        s5_ready_btn.configure(command=_save_to_ready)

        # ── Step 6 card — Re-sync from Cache ──────────────────────────
        s6 = card(body, "Step 6 — Re-sync from Cache  →  JSON  →  .uasset")
        s6_badge = tk.Label(s6, text="⬜ pending", font=self._theme.get_small_font(),
                            bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
        s6_badge.pack(anchor="w", pady=(0, 4))
        tk.Label(s6,
                 text="Re-reads every .uasset.json in the folder, fetches current translations\n"
                      "from the cache (including any edits you made), writes them back to JSON,\n"
                      "then converts each JSON → .uasset  (same UE Version & Mappings as above).",
                 font=self._theme.get_small_font(), justify="left",
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED).pack(anchor="w", pady=(0, 8))

        # JSON folder row — auto-filled from Step 2 / Step 3 paths
        r_s6_folder = tk.Frame(s6, bg=AppColors.BG_CARD)
        r_s6_folder.pack(fill="x", pady=2)
        tk.Label(r_s6_folder, text="JSON folder:", width=16, anchor="w",
                 font=self._theme.get_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY).pack(side="left")
        s6_folder_var = tk.StringVar()
        tk.Entry(r_s6_folder, textvariable=s6_folder_var, width=42,
                 bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY,
                 insertbackground=AppColors.TEXT_PRIMARY,
                 relief="flat", font=self._theme.get_font()).pack(side="left", padx=4)
        def _browse_s6_folder():
            # Let user pick a .uasset.json file — derive the folder from it
            p = filedialog.askopenfilename(
                title="Select any .uasset.json file in the target folder",
                filetypes=[("UAsset JSON", "*.json"), ("All files", "*.*")])
            if p:
                s6_folder_var.set(os.path.dirname(p))
        tk.Button(r_s6_folder, text="Browse", font=self._theme.get_small_font(),
                  bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY,
                  relief="flat", padx=8, pady=3, cursor="hand2",
                  command=_browse_s6_folder).pack(side="left", padx=4)
        tk.Label(r_s6_folder, text="(pick any .json file — folder is auto-detected)",
                 font=self._theme.get_small_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED).pack(side="left", padx=4)

        # Also run fromjson checkbox
        s6_run_fromjson_var = tk.BooleanVar(value=True)
        tk.Checkbutton(s6, text="Also run fromjson → .uasset after re-applying",
                       variable=s6_run_fromjson_var,
                       font=self._theme.get_small_font(),
                       bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY,
                       selectcolor=AppColors.ENTRY_BG,
                       activebackground=AppColors.BG_CARD).pack(anchor="w", pady=(6, 0))

        def _autofill_s6_folder(*_):
            """Auto-fill the JSON folder from step 2 json_paths when they're set."""
            if json_paths[0] and not s6_folder_var.get().strip():
                first = json_paths[0][0]
                s6_folder_var.set(os.path.dirname(first))

        def _run_step6():
            folder = s6_folder_var.get().strip()
            if not folder:
                # try to auto-fill from tracked json_paths
                if json_paths[0]:
                    folder = os.path.dirname(json_paths[0][0])
                    s6_folder_var.set(folder)
            if not folder or not os.path.isdir(folder):
                log("ERROR: JSON folder not found — set it or run Step 2 first")
                return

            gname = game_name_var.get().strip() or "IoStore"
            if not self._cache:
                log("ERROR: Cache not available")
                return

            ue    = ue_ver_var.get().strip()
            _maps = mappings_var.get().strip()
            _mode = extr_mode_var.get()
            run_fromjson = s6_run_fromjson_var.get()

            if run_fromjson and not ue:
                log("ERROR: Select a UE Version in Configuration for fromjson")
                return

            set_step_status(s6_badge, AppColors.WARNING, "🔄 running…")
            s6_btn.configure(state="disabled")

            def _thread():
                t = _get_translator()
                # collect all .uasset.json files recursively
                json_files = []
                for _root, _, _fnames in os.walk(folder):
                    for _fn in _fnames:
                        if _fn.endswith(".uasset.json"):
                            json_files.append(os.path.join(_root, _fn))
                if not json_files:
                    log(f"ERROR: No .uasset.json files found in {folder}")
                    set_step_status(s6_badge, AppColors.ERROR, "❌ no JSON files")
                    _safe(lambda: s6_btn.configure(state="normal"))
                    return

                # show config being used so user can diagnose mismatches
                available_games = self._cache.get_all_games()
                log(f"\nRe-sync config:")
                log(f"  Game name (cache): \"{gname}\"")
                log(f"  Extraction mode  : {_mode}")
                log(f"  Available in cache: {available_games}")
                log(f"  Files found: {len(json_files)}")
                applied_total = 0
                converted_total = 0

                for jf in json_files:
                    fname = os.path.basename(jf)
                    # prefer .orig (pre-translation English backup) for cache key lookup
                    orig_jf = jf + ".orig"
                    if os.path.exists(orig_jf):
                        src_jf = orig_jf
                        log(f"  {fname}: ✓ .orig found — using original English backup for cache lookup")
                    else:
                        src_jf = jf
                        log(f"  {fname}: no .orig backup found — reading current file")
                    # 1. extract source texts from this file
                    texts = t.extract_texts_from_json(src_jf, _mode)
                    if not texts:
                        log(f"  {fname}: no extractable texts (mode={_mode}) — skipped")
                        continue
                    log(f"  {fname}: {len(texts)} texts extracted")
                    # 2. fetch current translations from cache for these texts
                    cached = self._cache.get_batch(gname, texts)
                    if not cached:
                        log(f"  {fname}: 0 cache hits for game \"{gname}\"")
                        # show sample extracted texts vs cache contents
                        log(f"    Sample extracted texts (first 3):")
                        for s in texts[:3]:
                            short = s[:80].replace("\n", "\\n")
                            log(f"      • \"{short}\"")
                        cache_samples = self._cache.get_sample_originals(gname, 3)
                        if cache_samples:
                            log(f"    Sample texts in cache \"{gname}\" (first 3):")
                            for s in cache_samples:
                                short = s[:80].replace("\n", "\\n")
                                log(f"      • \"{short}\"")
                        else:
                            log(f"    Cache \"{gname}\" is empty")
                        # search all available caches for the best match
                        best_game, best_count = "", 0
                        for cg in available_games:
                            if cg == gname:
                                continue
                            hits = self._cache.get_batch(cg, texts[:200])
                            if len(hits) > best_count:
                                best_count, best_game = len(hits), cg
                        if best_game:
                            log(f"    → Best match: cache \"{best_game}\" has {best_count} hits")
                            log(f"    → Change \"Game name (cache)\" to \"{best_game}\" and retry")
                        else:
                            log(f"    → No matching cache found — texts not translated yet")
                            log(f"    → Run Steps 1-3 first to translate and cache these texts")
                        continue
                    # 3. apply to JSON file (read from orig backup if available)
                    src_arg = orig_jf if os.path.exists(orig_jf) else None
                    t.apply_translations_to_json(jf, cached, _mode, source_path=src_arg)
                    log(f"  {fname}: {len(cached)}/{len(texts)} applied")
                    applied_total += len(cached)
                    # 4. fromjson if requested
                    if run_fromjson:
                        ok = t.json_to_uasset(jf, ue, _maps)
                        if ok:
                            converted_total += 1

                summary = f"✅ {len(json_files)} file(s) — {applied_total} texts updated"
                if run_fromjson:
                    summary += f", {converted_total} .uasset converted"
                set_step_status(s6_badge, AppColors.SUCCESS, summary)
                log(f"\nRe-sync complete: {summary}")
                _safe(lambda: s6_btn.configure(state="normal"))

            threading.Thread(target=_thread, daemon=True).start()

        s6_btn = tk.Button(s6, text="▶  Run Step 6 — Re-sync",
                           font=self._theme.get_font(style="bold"),
                           bg=AppColors.SUCCESS, fg=AppColors.BG_DARK,
                           relief="flat", padx=16, pady=5, cursor="hand2",
                           command=_run_step6)
        s6_btn.pack(anchor="w", pady=(10, 0))

        def _save_s6_to_for_cache():
            # Use the Step 1 legacy root folder (full Paks_legacy tree), not Step 6's JSON subfolder
            root = legacy_folder[0] or out_dir_var.get().strip()
            if not root or not os.path.isdir(root):
                log("ERROR: Legacy folder not found — run Step 1 first to set the output folder")
                return
            gname = game_name_var.get().strip() or "IoStore"
            from games.translation_package import TranslationPackage as _TP
            _p = _TP()
            ok, lines = _p.copy_to_for_cache(gname, root)
            for ln in lines:
                log(ln)
            if ok:
                log(f"✅ for_cache updated ({os.path.basename(root)}) — '🔄 تحديث من الكاش' will use this state next time")

        tk.Button(s6, text="📦  حفظ الحالة في for_cache",
                  font=self._theme.get_font(),
                  bg="#8e44ad", fg="white",
                  relief="flat", padx=12, pady=5, cursor="hand2",
                  command=_save_s6_to_for_cache).pack(anchor="w", pady=(6, 0))

        # wire auto-fill: whenever json_paths changes, try to fill s6_folder
        # (checked lazily when Run Step 6 is clicked — see _run_step6 above)

        # ── Log area ────────────────────────────────────────────────────
        log_card = tk.Frame(body, bg=AppColors.BG_CARD, padx=16, pady=12)
        log_card.pack(fill="x", padx=16, pady=(8, 12))
        tk.Label(log_card, text="📋 Log", font=self._theme.get_header_font(),
                 bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 6))

        log_container = tk.Frame(log_card, bg=AppColors.ENTRY_BG)
        log_container.pack(fill="x")
        log_text = tk.Text(log_container, height=10, font=("Consolas", 9),
                           bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_SECONDARY,
                           insertbackground=AppColors.TEXT_PRIMARY,
                           relief="flat", padx=8, pady=6, wrap="word", state="disabled")
        log_sb = ttk.Scrollbar(log_container, command=log_text.yview)
        log_text.configure(yscrollcommand=log_sb.set)
        log_text.pack(side="left", fill="both", expand=True)
        log_sb.pack(side="right", fill="y")

        clear_btn = tk.Button(log_card, text="🗑 Clear Log",
                              font=self._theme.get_small_font(),
                              bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY,
                              relief="flat", padx=10, pady=2, cursor="hand2",
                              command=lambda: (
                                  log_text.configure(state="normal"),
                                  log_text.delete("1.0", "end"),
                                  log_text.configure(state="disabled")
                              ))
        clear_btn.pack(anchor="w", pady=(6, 0))

    def run(self):
        self._show_home()
        self.root.mainloop()
    
    def cleanup(self):
        if self._frida_manager:
            self._frida_manager.detach()
        if self._translation_engine:
            self._translation_engine.unload_all()
        if self._cache:
            self._cache.close()
