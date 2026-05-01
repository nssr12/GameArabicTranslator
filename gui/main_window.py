import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import json
import os
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
        
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
    
    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class MainWindow:
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Game Arabic Translator v1.0")
        self.root.geometry("1200x750")
        self.root.minsize(900, 600)
        
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
        self._system_prompt = "You are a professional game text translator. Translate the following English text to Arabic. Reply ONLY with the Arabic translation, nothing else. Keep any style tags, format placeholders like {0}, and special characters intact."
        
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
        tk.Label(logo_frame, text="v1.0", font=("Segoe UI", 9), bg=AppColors.SIDEBAR_BG, fg=AppColors.TEXT_MUTED).pack()
        
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
        
        tk.Label(page, text="Game Arabic Translator", font=("Segoe UI", 20, "bold"), bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 5))
        tk.Label(page, text="Translate any game to Arabic using AI models", font=("Segoe UI", 12), bg=AppColors.BG_DARK, fg=AppColors.TEXT_SECONDARY).pack(anchor="w", pady=(0, 20))
        
        stats_frame = tk.Frame(page, bg=AppColors.BG_DARK)
        stats_frame.pack(fill="x", pady=(0, 15))
        
        self._home_stats = {}
        stat_items = [
            ("games_count", "Games", "0", AppColors.ACCENT),
            ("translations_count", "Translations", "0", AppColors.SUCCESS),
            ("model_status", "Active Model", "None", AppColors.WARNING),
            ("cache_size", "Cache Entries", "0", "#9b59b6"),
        ]
        
        for i, (key, label, value, color) in enumerate(stat_items):
            card = tk.Frame(stats_frame, bg=AppColors.BG_CARD, padx=20, pady=12)
            card.grid(row=0, column=i, padx=4, sticky="ew")
            stats_frame.grid_columnconfigure(i, weight=1)
            tk.Label(card, text=value, font=("Segoe UI", 20, "bold"), bg=AppColors.BG_CARD, fg=color).pack(anchor="w")
            tk.Label(card, text=label, font=("Segoe UI", 9), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY).pack(anchor="w")
            self._home_stats[key] = card.winfo_children()[0]
        
        tk.Label(page, text="My Games", font=("Segoe UI", 14, "bold"), bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(10, 8))
        
        self._home_games_container = ScrollableFrame(page)
        self._home_games_container.pack(fill="both", expand=True)
    
    def _refresh_home_games(self):
        for widget in self._home_games_container.inner.winfo_children():
            widget.destroy()
        
        if not self._game_manager:
            return
        
        games = self._game_manager.get_game_list()
        if not games:
            tk.Label(self._home_games_container.inner, text="No games added yet. Go to Games tab to add one.", font=("Segoe UI", 11), bg=AppColors.BG_DARK, fg=AppColors.TEXT_MUTED).pack(pady=30)
            return
        
        grid_frame = tk.Frame(self._home_games_container.inner, bg=AppColors.BG_DARK)
        grid_frame.pack(fill="x", padx=5)
        
        cols = 4
        for i, game in enumerate(games):
            row, col = divmod(i, cols)
            
            card = tk.Frame(grid_frame, bg=AppColors.BG_CARD, padx=8, pady=8, cursor="hand2")
            card.grid(row=row, column=col, padx=6, pady=6, sticky="ew")
            grid_frame.grid_columnconfigure(col, weight=1)
            
            img_frame = tk.Frame(card, bg=AppColors.BG_LIGHT, height=100, width=160)
            img_frame.pack(fill="x", pady=(0, 6))
            img_frame.pack_propagate(False)
            
            game_id = game["id"]
            if game_id in self._game_images:
                try:
                    img_label = tk.Label(img_frame, image=self._game_images[game_id], bg=AppColors.BG_LIGHT)
                    img_label.pack(fill="both", expand=True)
                except:
                    tk.Label(img_frame, text="🎮", font=("Segoe UI", 28), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_MUTED).pack(expand=True)
            else:
                tk.Label(img_frame, text="🎮", font=("Segoe UI", 28), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_MUTED).pack(expand=True)
            
            name_lbl = tk.Label(card, text=game["name"], font=("Segoe UI", 10, "bold"), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY, wraplength=150)
            name_lbl.pack(anchor="w")
            
            engine_lbl = tk.Label(card, text=game.get("engine", "auto"), font=("Segoe UI", 8), bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
            engine_lbl.pack(anchor="w")
            
            img_btn = tk.Label(card, text="📷 Change Image", font=("Segoe UI", 7), bg=AppColors.BG_CARD, fg=AppColors.ACCENT, cursor="hand2")
            img_btn.pack(anchor="e", pady=(3, 0))
            
            for widget in [card, img_frame, name_lbl, engine_lbl]:
                widget.bind("<Button-1>", lambda e, g=game: self._show_game_detail(g["id"]))
            
            img_btn.bind("<Button-1>", lambda e, gid=game_id: (self._set_game_image(gid), "break"))
            
            def on_enter(e, c=card):
                c.configure(bg=AppColors.BG_LIGHT)
            def on_leave(e, c=card):
                c.configure(bg=AppColors.BG_CARD)
            card.bind("<Enter>", on_enter)
            card.bind("<Leave>", on_leave)
    
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
        
        page = tk.Frame(self._content_frame, bg=AppColors.BG_DARK)
        self._pages["game_detail"] = page
        
        self._show_page("game_detail")
        
        header = tk.Frame(page, bg=AppColors.BG_DARK)
        header.pack(fill="x", pady=(0, 15))
        
        back_btn = tk.Button(header, text="← Back", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=12, pady=4, cursor="hand2", command=lambda: self._navigate("home", self._show_home))
        back_btn.pack(side="left")
        
        tk.Label(header, text=f"  {game_name}", font=self._theme.get_title_font(), bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(side="left")
        
        top_frame = tk.Frame(page, bg=AppColors.BG_DARK)
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
        
        cache_frame = tk.Frame(page, bg=AppColors.BG_CARD, padx=20, pady=15)
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
        
        mod_frame = tk.Frame(page, bg=AppColors.BG_CARD, padx=20, pady=15)
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
        
        trans_frame = tk.Frame(page, bg=AppColors.BG_CARD, padx=20, pady=15)
        trans_frame.pack(fill="x", pady=(0, 10))
        
        tk.Label(trans_frame, text="🌐 Quick Actions", font=self._theme.get_header_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 10))
        
        action_btn_frame = tk.Frame(trans_frame, bg=AppColors.BG_CARD)
        action_btn_frame.pack(fill="x")
        
        tk.Button(action_btn_frame, text="🌐 Translate Game", font=self._theme.get_font(), bg="#9b59b6", fg="white", relief="flat", padx=15, pady=5, cursor="hand2", command=lambda: self._translate_game({"id": game_id, "name": game_name})).pack(side="left", padx=3)
        tk.Button(action_btn_frame, text="🔗 Attach to Game", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=15, pady=5, cursor="hand2", command=lambda: self._attach_to_game({"id": game_id, "name": game_name, "process_name": game_config.get("process_name", "")})).pack(side="left", padx=3)
        
        if game_config.get("hook_mode") == "bepinex" or "flotsam" in game_id.lower():
            tk.Button(action_btn_frame, text="🖥️ Start Server", font=self._theme.get_font(), bg=AppColors.SUCCESS, fg="black", relief="flat", padx=15, pady=5, cursor="hand2", command=lambda: self._start_translation_server()).pack(side="left", padx=3)
        
        tk.Button(action_btn_frame, text="📥 Sync from Game", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=15, pady=5, cursor="hand2", command=lambda: self._sync_from_game(game_id, game_name, game_config)).pack(side="left", padx=3)
        tk.Button(action_btn_frame, text="📤 Sync to Game", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=15, pady=5, cursor="hand2", command=lambda: self._sync_to_game(game_id, game_name, game_config)).pack(side="left", padx=3)
        tk.Button(action_btn_frame, text="✏️ Edit Config", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=15, pady=5, cursor="hand2", command=lambda: self._edit_game_dialog(game_id)).pack(side="left", padx=3)
    
    def _build_games_page(self):
        page = tk.Frame(self._content_frame, bg=AppColors.BG_DARK)
        self._pages["games"] = page
        
        header_frame = tk.Frame(page, bg=AppColors.BG_DARK)
        header_frame.pack(fill="x", pady=(0, 15))
        
        tk.Label(header_frame, text="Game Management", font=("Segoe UI", 18, "bold"), bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(side="left")
        
        btn_frame = tk.Frame(header_frame, bg=AppColors.BG_DARK)
        btn_frame.pack(side="right")
        
        add_btn = tk.Button(btn_frame, text="+ Add Game", font=("Segoe UI", 10, "bold"), bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=15, pady=6, cursor="hand2", command=self._add_game_dialog)
        add_btn.pack(side="left", padx=5)
        add_btn.bind("<Enter>", lambda e: add_btn.configure(bg=AppColors.ACCENT_HOVER))
        add_btn.bind("<Leave>", lambda e: add_btn.configure(bg=AppColors.ACCENT))
        
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
        
        self._cache_delete_all_btn = tk.Button(header, text="🗑 Delete ALL", font=("Segoe UI", 9), bg=AppColors.ERROR, fg="white", relief="flat", padx=12, pady=4, cursor="hand2", command=self._cache_delete_all)
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
        self._cache_model_combo.bind("<<ComboboxSelected>>", lambda e: self._cache_select_game())
        
        row2 = tk.Frame(selector_frame, bg=AppColors.BG_CARD)
        row2.pack(fill="x")
        
        tk.Label(row2, text="Search:", font=self._theme.get_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY).pack(side="left")
        
        self._cache_search_var = tk.StringVar()
        search_entry = tk.Entry(row2, textvariable=self._cache_search_var, font=self._theme.get_font(), bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY, insertbackground=AppColors.TEXT_PRIMARY, relief="flat", width=30)
        search_entry.pack(side="left", padx=8, ipady=3)
        search_entry.bind("<Return>", lambda e: self._cache_select_game())
        
        search_btn = tk.Button(row2, text="🔍 Search", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=2, cursor="hand2", command=self._cache_select_game)
        search_btn.pack(side="left", padx=3)
        
        clear_btn = tk.Button(row2, text="✕ Clear", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=8, pady=2, cursor="hand2", command=self._cache_clear_search)
        clear_btn.pack(side="left", padx=3)
        
        self._cache_stats_label = tk.Label(row2, text="", font=self._theme.get_small_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
        self._cache_stats_label.pack(side="right")
        
        self._cache_nav_frame = tk.Frame(page, bg=AppColors.BG_DARK)
        self._cache_nav_frame.pack(fill="x", pady=(5, 5))
        
        self._cache_page_label = tk.Label(self._cache_nav_frame, text="", font=self._theme.get_small_font(), bg=AppColors.BG_DARK, fg=AppColors.TEXT_MUTED)
        self._cache_page_label.pack(side="left")
        
        self._cache_next_btn = tk.Button(self._cache_nav_frame, text="Next →", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=2, command=lambda: self._cache_change_page(1))
        self._cache_next_btn.pack(side="right", padx=3)
        
        self._cache_prev_btn = tk.Button(self._cache_nav_frame, text="← Prev", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=10, pady=2, command=lambda: self._cache_change_page(-1))
        self._cache_prev_btn.pack(side="right", padx=3)
        
        col_header = tk.Frame(page, bg=AppColors.BG_CARD, padx=10, pady=6)
        col_header.pack(fill="x")
        
        tk.Label(col_header, text="#", font=self._theme.get_small_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED, width=4).pack(side="left")
        tk.Label(col_header, text="English", font=self._theme.get_small_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, width=32, anchor="w").pack(side="left", padx=3)
        tk.Label(col_header, text="Arabic", font=self._theme.get_small_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, width=32, anchor="w").pack(side="left", padx=3)
        tk.Label(col_header, text="Model", font=self._theme.get_small_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED, width=12, anchor="w").pack(side="left", padx=3)
        tk.Label(col_header, text="Actions", font=self._theme.get_small_font(), bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED, width=12).pack(side="left", padx=3)
        
        self._cache_entries_frame = ScrollableFrame(page)
        self._cache_entries_frame.pack(fill="both", expand=True)
        
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
                
                self._safe_after(0, lambda: self._set_status("Backend initialized successfully"))
                self._safe_after(100, self._refresh_home_stats)
                self._safe_after(200, self._load_game_images)
                self._safe_after(300, self._refresh_home_games)
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
            tk.Label(self._games_list_frame.inner, text="Loading...", font=("Segoe UI", 11), bg=AppColors.BG_DARK, fg=AppColors.TEXT_MUTED).pack(pady=20)
            return
        
        games = self._game_manager.get_game_list()
        
        if not games:
            empty_frame = tk.Frame(self._games_list_frame.inner, bg=AppColors.BG_CARD, padx=30, pady=40)
            empty_frame.pack(fill="x", pady=10)
            tk.Label(empty_frame, text="No games added yet", font=("Segoe UI", 14), bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED).pack()
            tk.Label(empty_frame, text="Click '+ Add Game' to add your first game", font=("Segoe UI", 11), bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED).pack(pady=(5, 0))
            return
        
        for game in games:
            card = tk.Frame(self._games_list_frame.inner, bg=AppColors.BG_CARD, padx=20, pady=12)
            card.pack(fill="x", pady=3)
            
            info_frame = tk.Frame(card, bg=AppColors.BG_CARD)
            info_frame.pack(side="left", fill="x", expand=True)
            
            name_lbl = tk.Label(info_frame, text=game["name"], font=("Segoe UI", 12, "bold"), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY, anchor="w")
            name_lbl.pack(anchor="w")
            
            detail = f"Process: {game['process_name'] or 'Not set'}  |  Engine: {game['engine']}  |  {'Enabled' if game['enabled'] else 'Disabled'}"
            tk.Label(info_frame, text=detail, font=("Segoe UI", 9), bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED, anchor="w").pack(anchor="w")
            
            btn_frame = tk.Frame(card, bg=AppColors.BG_CARD)
            btn_frame.pack(side="right")
            
            fonts_btn = tk.Button(btn_frame, text="🔤 Fonts", font=("Segoe UI", 9), bg="#e67e22", fg="white", relief="flat", padx=10, pady=3, cursor="hand2", command=lambda g=game: self._patch_game_fonts(g))
            fonts_btn.pack(side="left", padx=3)
            
            translate_btn = tk.Button(btn_frame, text="🌐 Translate", font=("Segoe UI", 9), bg="#9b59b6", fg="white", relief="flat", padx=10, pady=3, cursor="hand2", command=lambda g=game: self._translate_game(g))
            translate_btn.pack(side="left", padx=3)
            
            attach_btn = tk.Button(btn_frame, text="Attach", font=("Segoe UI", 9), bg=AppColors.SUCCESS, fg="black", relief="flat", padx=10, pady=3, cursor="hand2", command=lambda g=game: self._attach_to_game(g))
            attach_btn.pack(side="left", padx=3)
            
            del_btn = tk.Button(btn_frame, text="Delete", font=("Segoe UI", 9), bg=AppColors.ERROR, fg="white", relief="flat", padx=10, pady=3, cursor="hand2", command=lambda gid=game["id"]: self._delete_game(gid))
            del_btn.pack(side="left", padx=3)
    
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
        dialog.grab_set()
        
        x = self.root.winfo_x() + (self.root.winfo_width() - 650) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 580) // 2
        dialog.geometry(f"+{x}+{y}")
        
        tk.Label(dialog, text=f"🌐 Translate: {game_name}", font=("Segoe UI", 16, "bold"), bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(pady=(15, 5))
        
        model_frame = tk.Frame(dialog, bg=AppColors.BG_CARD, padx=15, pady=12)
        model_frame.pack(fill="x", padx=15, pady=(5, 5))
        
        tk.Label(model_frame, text="Translation Model:", font=("Segoe UI", 10, "bold"), bg=AppColors.BG_CARD, fg=AppColors.TEXT_PRIMARY).pack(anchor="w", pady=(0, 6))
        
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
        
        tk.Radiobutton(mode_frame, text="🆕 Translate fresh (delete old + retranslate)", variable=mode_var, value="fresh", font=("Segoe UI", 9), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, selectcolor=AppColors.ENTRY_BG, activebackground=AppColors.BG_CARD).pack(anchor="w")
        tk.Radiobutton(mode_frame, text="📦 Use existing cache only (no new API calls)", variable=mode_var, value="cache_only", font=("Segoe UI", 9), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, selectcolor=AppColors.ENTRY_BG, activebackground=AppColors.BG_CARD).pack(anchor="w")
        tk.Radiobutton(mode_frame, text="🔄 Translate only missing (keep existing + translate new)", variable=mode_var, value="missing", font=("Segoe UI", 9), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY, selectcolor=AppColors.ENTRY_BG, activebackground=AppColors.BG_CARD).pack(anchor="w")
        
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
                log_to_dialog(f"Deleting old translations for {game_name}...")
                self._cache.delete_game(game_name)
            
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
            start_btn.configure(state="disabled")
            stop_btn.configure(state="normal")
            threading.Thread(target=run_translation, daemon=True).start()
        
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
                ollama_row = tk.Frame(info_frame, bg=AppColors.BG_CARD)
                ollama_row.pack(fill="x", pady=(6, 0))
                
                tk.Label(ollama_row, text="Model:", font=("Segoe UI", 10), bg=AppColors.BG_CARD, fg=AppColors.TEXT_SECONDARY).pack(side="left")
                
                current_model = self._translation_engine.get_current_ollama_model()
                self._ollama_var = tk.StringVar(value=current_model or "Select...")
                
                self._ollama_combo = ttk.Combobox(ollama_row, textvariable=self._ollama_var, state="readonly", width=30, font=("Segoe UI", 10))
                self._ollama_combo.pack(side="left", padx=(8, 5))
                
                refresh_btn = tk.Button(ollama_row, text="🔄", font=("Segoe UI", 9), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=6, pady=1, cursor="hand2", command=self._fetch_ollama_models)
                refresh_btn.pack(side="left", padx=3)
                
                apply_btn = tk.Button(ollama_row, text="Apply", font=("Segoe UI", 9), bg=AppColors.ACCENT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=8, pady=1, cursor="hand2", command=self._apply_ollama_model)
                apply_btn.pack(side="left", padx=3)
                
                self._ollama_size_label = tk.Label(ollama_row, text="", font=("Segoe UI", 9), bg=AppColors.BG_CARD, fg=AppColors.TEXT_MUTED)
                self._ollama_size_label.pack(side="left", padx=(10, 0))
                
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
    
    def _fetch_ollama_models(self):
        self._set_status("Fetching Ollama models...")
        
        def fetch_thread():
            models = []
            if self._translation_engine:
                models = self._translation_engine.get_ollama_models()
            
            def update():
                if hasattr(self, '_ollama_combo') and self._ollama_combo.winfo_exists():
                    names = [m["name"] for m in models]
                    self._ollama_combo["values"] = names
                    
                    current = self._translation_engine.get_current_ollama_model() if self._translation_engine else ""
                    if current and current in names:
                        self._ollama_var.set(current)
                    elif names:
                        self._ollama_var.set(names[0])
                    
                    if models and hasattr(self, '_ollama_size_label') and self._ollama_size_label.winfo_exists():
                        selected = self._ollama_var.get()
                        for m in models:
                            if m["name"] == selected:
                                info = f"{m.get('parameter_size', '')} | {m.get('family', '')} | {m.get('size_gb', '?')}GB"
                                self._ollama_size_label.configure(text=info)
                                break
                    
                    if names:
                        self._set_status(f"Found {len(names)} Ollama models")
                    else:
                        self._set_status("No Ollama models found. Is Ollama running?")
            
            try:
                self._safe_after(0, update)
            except RuntimeError:
                pass
        
        threading.Thread(target=fetch_thread, daemon=True).start()
    
    def _apply_ollama_model(self):
        if not hasattr(self, '_ollama_var') or not self._translation_engine:
            return
        
        selected = self._ollama_var.get()
        if not selected or selected == "Select...":
            return
        
        self._translation_engine.set_ollama_model(selected)
        self._set_status(f"Ollama model set to: {selected}")
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
    
    def _save_system_prompt(self):
        prompt = self._system_prompt_text.get("1.0", "end").strip()
        if prompt:
            self._system_prompt = prompt
            self._set_status("System prompt saved")
            
            if self._translation_engine:
                ollama = self._translation_engine.get_translator("ollama")
                if ollama and hasattr(ollama, "system_prompt"):
                    ollama.system_prompt = prompt
                
                custom = self._translation_engine.get_translator("custom_endpoint")
                if custom and hasattr(custom, "system_prompt"):
                    custom.system_prompt = prompt
    
    def _reset_system_prompt(self):
        default = "You are a professional game text translator. Translate the following English text to Arabic. Reply ONLY with the Arabic translation, nothing else. Keep any style tags, format placeholders like {0}, and special characters intact."
        self._system_prompt = default
        self._system_prompt_text.delete("1.0", "end")
        self._system_prompt_text.insert("1.0", default)
        self._set_status("System prompt reset to default")
    
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
        self._cache_update_models_filter()
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
        for widget in self._cache_entries_frame.inner.winfo_children():
            widget.destroy()
        
        if not self._cache:
            return
        
        game = self._cache_game_var.get()
        search = self._cache_search_var.get().strip()
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
            end = start + self._cache_page_size
            page_entries = all_entries[start:end]
            
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
        
        if not page_entries:
            tk.Label(self._cache_entries_frame.inner, text="No entries found", font=self._theme.get_font(), bg=AppColors.BG_DARK, fg=AppColors.TEXT_MUTED).pack(pady=30)
            return
        
        for i, entry in enumerate(page_entries):
            row_bg = AppColors.BG_CARD if i % 2 == 0 else AppColors.BG_MEDIUM
            row = tk.Frame(self._cache_entries_frame.inner, bg=row_bg, padx=10, pady=5)
            row.pack(fill="x", pady=1)
            
            num = self._cache_current_page * self._cache_page_size + i + 1
            tk.Label(row, text=str(num), font=self._theme.get_small_font(), bg=row_bg, fg=AppColors.TEXT_MUTED, width=4).pack(side="left")
            
            orig = entry["original"][:70] + ("..." if len(entry["original"]) > 70 else "")
            tk.Label(row, text=orig, font=self._theme.get_code_font(), bg=row_bg, fg=AppColors.TEXT_SECONDARY, width=32, anchor="w").pack(side="left", padx=3)
            
            trans = self._display_arabic(entry["translated"][:70])
            tk.Label(row, text=trans, font=self._theme.get_code_font(), bg=row_bg, fg=AppColors.SUCCESS, width=32, anchor="e").pack(side="left", padx=3)
            
            model = entry.get("model", "?")[:12]
            tk.Label(row, text=model, font=self._theme.get_small_font(), bg=row_bg, fg=AppColors.WARNING, width=12, anchor="w").pack(side="left", padx=3)
            
            btn_frame = tk.Frame(row, bg=row_bg)
            btn_frame.pack(side="left", padx=3)
            
            game_name = entry.get("game", game)
            
            edit_btn = tk.Button(btn_frame, text="✏️", font=self._theme.get_small_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=4, pady=1, cursor="hand2", command=lambda e=entry, g=game_name: self._cache_edit_entry(g, e))
            edit_btn.pack(side="left", padx=2)
            
            del_btn = tk.Button(btn_frame, text="🗑", font=self._theme.get_small_font(), bg=AppColors.ERROR, fg="white", relief="flat", padx=4, pady=1, cursor="hand2", command=lambda e=entry, g=game_name: self._cache_delete_entry(g, e))
            del_btn.pack(side="left", padx=2)
    
    def _cache_edit_entry(self, game_name, entry):
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Translation")
        dialog.geometry("650x350")
        dialog.configure(bg=AppColors.BG_DARK)
        dialog.transient(self.root)
        dialog.grab_set()
        
        x = self.root.winfo_x() + (self.root.winfo_width() - 650) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 350) // 2
        dialog.geometry(f"+{x}+{y}")
        
        tk.Label(dialog, text="Edit Translation", font=self._theme.get_header_font(), bg=AppColors.BG_DARK, fg=AppColors.TEXT_PRIMARY).pack(pady=(15, 10))
        
        tk.Label(dialog, text="English (Original):", font=self._theme.get_font(), bg=AppColors.BG_DARK, fg=AppColors.TEXT_SECONDARY).pack(anchor="w", padx=20)
        orig_text = tk.Text(dialog, height=2, font=self._theme.get_code_font(), bg=AppColors.ENTRY_BG, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=8, pady=4, wrap="word")
        orig_text.pack(fill="x", padx=20, pady=(2, 10))
        orig_text.insert("1.0", entry["original"])
        orig_text.configure(state="disabled")
        
        tk.Label(dialog, text="Arabic (Translated):", font=self._theme.get_font(), bg=AppColors.BG_DARK, fg=AppColors.TEXT_SECONDARY).pack(anchor="w", padx=20)
        trans_text = tk.Text(dialog, height=3, font=self._theme.get_code_font(), bg=AppColors.ENTRY_BG, fg=AppColors.SUCCESS, relief="flat", padx=8, pady=4, wrap="word")
        trans_text.pack(fill="x", padx=20, pady=(2, 10))
        trans_text.insert("1.0", entry["translated"])
        
        apply_to_subtitle = tk.BooleanVar(value=True)
        tk.Checkbutton(dialog, text="Apply to subtitle files", font=self._theme.get_font(), bg=AppColors.BG_DARK, fg=AppColors.TEXT_SECONDARY, selectcolor=AppColors.ENTRY_BG, activebackground=AppColors.BG_DARK, variable=apply_to_subtitle).pack(anchor="w", padx=20)
        
        def save():
            new_trans = trans_text.get("1.0", "end").strip()
            if new_trans and self._cache:
                self._cache.update_translation(game_name, entry["original"], new_trans)
                
                if apply_to_subtitle.get():
                    self._apply_to_subtitle_files(game_name, entry["original"], new_trans)
                
                dialog.destroy()
                self._cache_load_entries()
                self._set_status("Translation updated")
        
        btn_frame = tk.Frame(dialog, bg=AppColors.BG_DARK)
        btn_frame.pack(fill="x", padx=20, pady=(10, 15))
        
        tk.Button(btn_frame, text="💾 Save", font=self._theme.get_font(style="bold"), bg=AppColors.SUCCESS, fg="black", relief="flat", padx=15, pady=4, command=save).pack(side="left")
        tk.Button(btn_frame, text="Cancel", font=self._theme.get_font(), bg=AppColors.BG_LIGHT, fg=AppColors.TEXT_PRIMARY, relief="flat", padx=15, pady=4, command=dialog.destroy).pack(side="left", padx=10)
    
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
            msg = "Delete ALL cached translations for ALL games?"
        else:
            msg = f"Delete ALL cached translations for '{game}'?"
        
        if messagebox.askyesno("Confirm", msg):
            if self._cache:
                if game == "All Games":
                    self._cache.delete_all()
                else:
                    self._cache.delete_game(game)
                self._cache_load_entries()
                self._set_status(f"Cache deleted: {game}")
                self._refresh_home_stats()
    
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
