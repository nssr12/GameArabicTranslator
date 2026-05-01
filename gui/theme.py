import json
import os

DEFAULT_THEMES = {
    "dark": {
        "name": "Dark",
        "BG_DARK": "#1a1a2e", "BG_MEDIUM": "#16213e", "BG_LIGHT": "#0f3460",
        "BG_CARD": "#1e2a4a", "ACCENT": "#e94560", "ACCENT_HOVER": "#ff6b81",
        "TEXT_PRIMARY": "#ffffff", "TEXT_SECONDARY": "#a8b2d1", "TEXT_MUTED": "#6b7394",
        "SUCCESS": "#00d2ff", "WARNING": "#ffd700", "ERROR": "#ff4757",
        "BORDER": "#2a3a5c", "ENTRY_BG": "#0d1b2a", "SIDEBAR_BG": "#0a0f1e", "SIDEBAR_ACTIVE": "#1a2744"
    },
    "light": {
        "name": "Light",
        "BG_DARK": "#f0f0f5", "BG_MEDIUM": "#e0e0ea", "BG_LIGHT": "#d0d0dd",
        "BG_CARD": "#ffffff", "ACCENT": "#e94560", "ACCENT_HOVER": "#ff6b81",
        "TEXT_PRIMARY": "#1a1a2e", "TEXT_SECONDARY": "#555577", "TEXT_MUTED": "#888899",
        "SUCCESS": "#00aaff", "WARNING": "#cc9900", "ERROR": "#dd3344",
        "BORDER": "#ccccdd", "ENTRY_BG": "#f8f8ff", "SIDEBAR_BG": "#e8e8f0", "SIDEBAR_ACTIVE": "#d0d0e0"
    },
    "sunset": {
        "name": "Sunset",
        "BG_DARK": "#1a0a1e", "BG_MEDIUM": "#2d1b3e", "BG_LIGHT": "#4a2060",
        "BG_CARD": "#2a1540", "ACCENT": "#ff6b35", "ACCENT_HOVER": "#ff8855",
        "TEXT_PRIMARY": "#ffffff", "TEXT_SECONDARY": "#c8a8d8", "TEXT_MUTED": "#8866aa",
        "SUCCESS": "#44ddaa", "WARNING": "#ffcc00", "ERROR": "#ff4466",
        "BORDER": "#4a2a5c", "ENTRY_BG": "#120820", "SIDEBAR_BG": "#0f0518", "SIDEBAR_ACTIVE": "#2a1040"
    },
    "ocean": {
        "name": "Ocean",
        "BG_DARK": "#0a1628", "BG_MEDIUM": "#0f2240", "BG_LIGHT": "#1a3a5c",
        "BG_CARD": "#122a48", "ACCENT": "#00bbff", "ACCENT_HOVER": "#44ccff",
        "TEXT_PRIMARY": "#ffffff", "TEXT_SECONDARY": "#88bbdd", "TEXT_MUTED": "#557799",
        "SUCCESS": "#00ff88", "WARNING": "#ffaa00", "ERROR": "#ff4455",
        "BORDER": "#1a3a5c", "ENTRY_BG": "#081020", "SIDEBAR_BG": "#060e1a", "SIDEBAR_ACTIVE": "#102040"
    },
    "forest": {
        "name": "Forest",
        "BG_DARK": "#0a1a0e", "BG_MEDIUM": "#142818", "BG_LIGHT": "#1e3a22",
        "BG_CARD": "#162a1a", "ACCENT": "#44cc66", "ACCENT_HOVER": "#66dd88",
        "TEXT_PRIMARY": "#ffffff", "TEXT_SECONDARY": "#a8ccaa", "TEXT_MUTED": "#668866",
        "SUCCESS": "#88ff44", "WARNING": "#ffcc00", "ERROR": "#ff4444",
        "BORDER": "#2a4a2c", "ENTRY_BG": "#081208", "SIDEBAR_BG": "#060e08", "SIDEBAR_ACTIVE": "#102010"
    },
    "purple": {
        "name": "Purple",
        "BG_DARK": "#12082a", "BG_MEDIUM": "#1e1040", "BG_LIGHT": "#2e1860",
        "BG_CARD": "#1a1040", "ACCENT": "#bb44ff", "ACCENT_HOVER": "#cc66ff",
        "TEXT_PRIMARY": "#ffffff", "TEXT_SECONDARY": "#bba8dd", "TEXT_MUTED": "#7755aa",
        "SUCCESS": "#44ffaa", "WARNING": "#ffdd00", "ERROR": "#ff4477",
        "BORDER": "#3a2060", "ENTRY_BG": "#0a0418", "SIDEBAR_BG": "#08031a", "SIDEBAR_ACTIVE": "#1a0a30"
    }
}

DEFAULT_FONT_FAMILY = "Segoe UI"
DEFAULT_FONT_SIZE = 11


class ThemeManager:
    
    def __init__(self, config_dir: str = "data"):
        self.config_dir = config_dir
        self.config_path = os.path.join(config_dir, "ui_settings.json")
        self.themes = dict(DEFAULT_THEMES)
        self.current_theme = "dark"
        self.font_family = DEFAULT_FONT_FAMILY
        self.font_size = DEFAULT_FONT_SIZE
        self._load()
    
    def _load(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.current_theme = data.get("theme", "dark")
                self.font_family = data.get("font_family", DEFAULT_FONT_FAMILY)
                self.font_size = data.get("font_size", DEFAULT_FONT_SIZE)
                if "custom_themes" in data:
                    self.themes.update(data["custom_themes"])
        except:
            pass
    
    def save(self):
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            data = {
                "theme": self.current_theme,
                "font_family": self.font_family,
                "font_size": self.font_size,
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except:
            pass
    
    def get_colors(self) -> dict:
        return dict(self.themes.get(self.current_theme, self.themes["dark"]))
    
    def get_theme_names(self) -> list:
        return list(self.themes.keys())
    
    def set_theme(self, theme_name: str):
        if theme_name in self.themes:
            self.current_theme = theme_name
            self.save()
    
    def set_font(self, family: str, size: int):
        self.font_family = family
        self.font_size = size
        self.save()
    
    def get_font(self, size_offset: int = 0, style: str = "") -> tuple:
        size = max(8, self.font_size + size_offset)
        if style == "bold":
            return (self.font_family, size, "bold")
        elif style == "italic":
            return (self.font_family, size, "italic")
        return (self.font_family, size)
    
    def get_title_font(self) -> tuple:
        return self.get_font(6, "bold")
    
    def get_header_font(self) -> tuple:
        return self.get_font(3, "bold")
    
    def get_small_font(self) -> tuple:
        return self.get_font(-2)
    
    def get_code_font(self) -> tuple:
        return ("Consolas", max(8, self.font_size - 1))
