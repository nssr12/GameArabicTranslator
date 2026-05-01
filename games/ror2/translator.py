import json
import os
import re
import shutil
import threading
import time
from typing import Optional, Dict, List, Callable
from engine.arabic_processor import reshape_arabic_keep_tags


class RoR2Translator:
    
    STYLE_TAG_PATTERN = re.compile(r'(<style=[^>]*>.*?</style>|</?style=[^>]*>|<color=[^>]*>.*?</color>|</?color=[^>]*>|<size=[^>]*>.*?</size>|</?size=[^>]*>|\\n|\\r|\{[0-9]*(:[^}]*)?\})')
    
    LANGUAGE_FILES = [
        "Achievements.json", "Artifacts.json", "CharacterBodies.json",
        "CharacterSelect.json", "Controls.json", "credits_roles.json",
        "credits.json", "Cutscene.json", "Dialogue.json", "Difficulty.json",
        "Discord.json", "DLC1.json", "DLC2.json", "DLC3.json",
        "EarlyAccess.json", "Eclipse.json", "EOS.json", "Equipment.json",
        "GameBrowser.json", "GameModes.json", "HostGamePanel.json",
        "InfiniteTower.json", "Interactors.json", "Items.json",
        "Keywords.json", "Lobby.json", "Logbook.json", "Main.json",
        "Maps.json", "Messages.json", "Objectives.json", "Rules.json",
        "Settings.json", "Stats.json", "Steam.json", "Tooltips.json",
        "Unlockables.json",
    ]
    
    def __init__(self, game_path: str, translator_engine=None, cache=None):
        self.game_path = game_path
        self.engine = translator_engine
        self.cache = cache
        self.game_name = "Risk of Rain 2"
        self.language_path = os.path.join(game_path, "Risk of Rain 2_Data", "StreamingAssets", "Language")
        self.en_path = os.path.join(self.language_path, "en")
        self.ar_path = os.path.join(self.language_path, "ar")
        self._stop_flag = False
        self._progress_callback: Optional[Callable] = None
        self._log_callback: Optional[Callable] = None
        self._total_strings = 0
        self._translated_strings = 0
        self._cached_strings = 0
        self._failed_strings = 0
    
    def set_callbacks(self, progress: Callable = None, log: Callable = None):
        self._progress_callback = progress
        self._log_callback = log
    
    def _log(self, msg: str):
        if self._log_callback:
            self._log_callback(msg)
        print(f"[RoR2] {msg}")
    
    def _update_progress(self, current: int, total: int, cached: int, failed: int):
        if self._progress_callback:
            self._progress_callback(current, total, cached, failed)
    
    def is_game_valid(self) -> bool:
        return os.path.exists(self.en_path)
    
    def get_all_english_strings(self) -> Dict[str, Dict[str, str]]:
        all_strings = {}
        
        for filename in self.LANGUAGE_FILES:
            filepath = os.path.join(self.en_path, filename)
            if not os.path.exists(filepath):
                continue
            
            try:
                with open(filepath, "r", encoding="utf-8-sig") as f:
                    raw = f.read()
                
                raw = re.sub(r',\s*}', '}', raw)
                raw = re.sub(r',\s*]', ']', raw)
                
                data = json.loads(raw)
                
                strings = data.get("strings", {})
                file_strings = {}
                for key, value in strings.items():
                    if isinstance(value, str) and len(value) > 1:
                        file_strings[key] = value
                
                if file_strings:
                    all_strings[filename] = file_strings
                    self._log(f"Read {len(file_strings)} strings from {filename}")
            
            except Exception as e:
                self._log(f"Error reading {filename}: {e}")
        
        return all_strings
    
    def count_total_strings(self) -> int:
        all_strings = self.get_all_english_strings()
        return sum(len(v) for v in all_strings.values())
    
    def _protect_style_tags(self, text: str) -> tuple:
        replacements = {}
        counter = [0]
        
        def replace_tag(match):
            placeholder = f"__TAG_{counter[0]}__"
            replacements[placeholder] = match.group(0)
            counter[0] += 1
            return placeholder
        
        protected = self.STYLE_TAG_PATTERN.sub(replace_tag, text)
        return protected, replacements
    
    def _restore_style_tags(self, text: str, replacements: dict) -> str:
        for placeholder, original in replacements.items():
            text = text.replace(placeholder, original)
        return text
    
    def _translate_single_string(self, text: str) -> Optional[str]:
        if not text or len(text.strip()) < 2:
            return None
        
        protected, replacements = self._protect_style_tags(text)
        
        if self.cache:
            cached = self.cache.get(self.game_name, text)
            if cached:
                return cached
        
        if self.engine:
            result = self.engine.translate(protected)
            if result:
                final = self._restore_style_tags(result, replacements)
                if self.cache:
                    self.cache.put(self.game_name, text, final, self.engine.get_active_model() or "unknown")
                return final
        
        return None
    
    def translate_all(self, progress_callback: Callable = None, log_callback: Callable = None) -> bool:
        if progress_callback:
            self._progress_callback = progress_callback
        if log_callback:
            self._log_callback = log_callback
        
        self._stop_flag = False
        self._translated_strings = 0
        self._cached_strings = 0
        self._failed_strings = 0
        
        if not self.is_game_valid():
            self._log(f"Game not found at: {self.en_path}")
            return False
        
        all_strings = self.get_all_english_strings()
        self._total_strings = sum(len(v) for v in all_strings.values())
        
        self._log(f"Total strings to translate: {self._total_strings}")
        
        os.makedirs(self.ar_path, exist_ok=True)
        
        language_json = os.path.join(self.ar_path, "language.json")
        with open(language_json, "w", encoding="utf-8") as f:
            json.dump({"language": {"selfname": "العربية"}}, f, indent=2, ensure_ascii=False)
        
        for filename, strings in all_strings.items():
            if self._stop_flag:
                self._log("Translation stopped by user")
                return False
            
            self._log(f"Translating {filename} ({len(strings)} strings)...")
            
            translated_strings = {}
            for key, value in strings.items():
                if self._stop_flag:
                    return False
                
                cached = None
                if self.cache:
                    cached = self.cache.get(self.game_name, value)
                
                if cached:
                    translated_strings[key] = cached
                    self._cached_strings += 1
                else:
                    result = self._translate_single_string(value)
                    if result:
                        translated_strings[key] = result
                        self._translated_strings += 1
                    else:
                        translated_strings[key] = value
                        self._failed_strings += 1
                
                done = self._translated_strings + self._cached_strings + self._failed_strings
                self._update_progress(done, self._total_strings, self._cached_strings, self._failed_strings)
            
            reshaped_strings = {}
            for key, value in translated_strings.items():
                reshaped_strings[key] = reshape_arabic_keep_tags(value)
            
            output_data = {"strings": reshaped_strings}
            output_path = os.path.join(self.ar_path, filename)
            
            try:
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(output_data, f, indent=2, ensure_ascii=False)
                self._log(f"Saved {filename}")
            except Exception as e:
                self._log(f"Error saving {filename}: {e}")
        
        self._log(f"Translation complete! Total: {self._total_strings}, Translated: {self._translated_strings}, Cached: {self._cached_strings}, Failed: {self._failed_strings}")
        return True
    
    def stop(self):
        self._stop_flag = True
    
    def get_stats(self) -> dict:
        return {
            "total": self._total_strings,
            "translated": self._translated_strings,
            "cached": self._cached_strings,
            "failed": self._failed_strings,
            "ar_path_exists": os.path.exists(self.ar_path),
            "ar_files": len(os.listdir(self.ar_path)) if os.path.exists(self.ar_path) else 0,
        }
    
    def delete_arabic(self):
        if os.path.exists(self.ar_path):
            shutil.rmtree(self.ar_path)
            self._log("Arabic translation deleted")
