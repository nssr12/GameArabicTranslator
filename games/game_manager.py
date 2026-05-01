import json
import os
from typing import Optional, Dict, List


DEFAULT_GAME_CONFIG = {
    "name": "",
    "process_name": "",
    "game_path": "",
    "engine": "auto",
    "hook_mode": "frida",
    "source_lang": "en",
    "target_lang": "ar",
    "replace_font": False,
    "font_path": "",
    "notes": "",
    "hooks": [],
    "enabled": True
}


class GameManager:
    
    def __init__(self, configs_dir: str = "games/configs"):
        self.configs_dir = configs_dir
        self._games: Dict[str, dict] = {}
        self._load_all_configs()
    
    def _ensure_dir(self):
        os.makedirs(self.configs_dir, exist_ok=True)
    
    def _load_all_configs(self):
        self._ensure_dir()
        if not os.path.exists(self.configs_dir):
            return
        
        for filename in os.listdir(self.configs_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(self.configs_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        config = json.load(f)
                        game_id = config.get("name", filename.replace(".json", ""))
                        self._games[game_id] = config
                except Exception as e:
                    print(f"[GameManager] Error loading {filename}: {e}")
    
    def get_game(self, game_id: str) -> Optional[dict]:
        return self._games.get(game_id)
    
    def get_all_games(self) -> Dict[str, dict]:
        return dict(self._games)
    
    def get_game_list(self) -> List[dict]:
        return [
            {
                "id": gid,
                "name": g.get("name", gid),
                "process_name": g.get("process_name", ""),
                "engine": g.get("engine", "auto"),
                "enabled": g.get("enabled", True)
            }
            for gid, g in self._games.items()
        ]
    
    def add_game(self, game_id: str, config: dict) -> bool:
        full_config = dict(DEFAULT_GAME_CONFIG)
        full_config.update(config)
        full_config["name"] = game_id
        
        self._games[game_id] = full_config
        return self._save_config(game_id, full_config)
    
    def update_game(self, game_id: str, updates: dict) -> bool:
        if game_id not in self._games:
            return False
        
        self._games[game_id].update(updates)
        return self._save_config(game_id, self._games[game_id])
    
    def delete_game(self, game_id: str) -> bool:
        if game_id not in self._games:
            return False
        
        del self._games[game_id]
        filepath = os.path.join(self.configs_dir, f"{game_id}.json")
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
            return True
        except:
            return False
    
    def _save_config(self, game_id: str, config: dict) -> bool:
        self._ensure_dir()
        filepath = os.path.join(self.configs_dir, f"{game_id}.json")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[GameManager] Error saving {game_id}: {e}")
            return False
    
    def detect_game_engine(self, game_path: str) -> str:
        if not os.path.exists(game_path):
            return "unknown"
        
        contents = os.listdir(game_path)
        contents_lower = [c.lower() for c in contents]
        
        for item in contents:
            item_lower = item.lower()
            if item_lower.endswith("_data") and os.path.isdir(os.path.join(game_path, item)):
                data_path = os.path.join(game_path, item)
                if os.path.exists(os.path.join(data_path, "globalgamemanagers")):
                    return "unity"
                if os.path.exists(os.path.join(data_path, "content")):
                    return "unreal"
        
        for item in contents_lower:
            if "unreal" in item or "ue4" in item or "ue5" in item:
                return "unreal"
        
        for item in contents:
            if item.lower().endswith(".uasset") or item.lower().endswith(".pak"):
                return "unreal"
        
        for item in contents:
            if item.lower().endswith(".assets") or item.lower().endswith(".bundle"):
                return "unity"
        
        return "unknown"
