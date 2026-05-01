import os
import json
import threading
from typing import Optional, Callable


class ManorLordsHandler:
    
    def __init__(self, game_path: str, translator_engine=None, cache=None):
        self.game_path = game_path
        self.engine = translator_engine
        self.cache = cache
        self.game_name = "Manor Lords"
        self.process_name = "ManorLords-Win64-Shipping.exe"
        self._log_callback: Optional[Callable] = None
    
    def set_callbacks(self, log: Callable = None):
        self._log_callback = log
    
    def _log(self, msg: str):
        if self._log_callback:
            self._log_callback(msg)
        print(f"[ManorLords] {msg}")
    
    def is_game_valid(self) -> bool:
        exe_path = os.path.join(self.game_path, "ManorLords", "Binaries", "Win64", self.process_name)
        return os.path.exists(exe_path)
    
    def get_info(self) -> dict:
        info = {
            "name": self.game_name,
            "process": self.process_name,
            "engine": "Unreal Engine",
            "valid": self.is_game_valid(),
            "pak_files": [],
        }
        
        paks_dir = os.path.join(self.game_path, "ManorLords", "Content", "Paks")
        if os.path.exists(paks_dir):
            info["pak_files"] = [f for f in os.listdir(paks_dir) if f.endswith('.pak')]
        
        return info
    
    def get_cache_stats(self) -> dict:
        if self.cache:
            return self.cache.get_stats(self.game_name)
        return {"total_translations": 0, "cache_hits": 0, "failed_count": 0}
