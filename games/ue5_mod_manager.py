import os
import sys
import json
import shutil
import sqlite3
import zipfile
import io
from typing import Optional, Dict, Callable


UE5_MOD_FILES = {
    "dxgi.dll": None,
    "ZXSOSZXMod.dll": None,
    "ZXSOSZXNMod.dll": None,
    "ZXSOSZXSubtitle.exe": None,
    "ZXSOSZXFont.ttf": None,
    "ZXSOSZXFormat.ini": None,
    "ZXSOSZXHandle.ini": None,
    "ZXSOSZXLog.ini": None,
    "ZXSOSZXSubtitle.exe.config": None,
    "ZXSOSZXSubtitleReadUni.ini": None,
    "ZXSOSZXSubtitleUseUni.ini": None,
    "GameID.ini": None,
    "GameName.ini": None,
    "mod_addr1.ini": None,
    "mod_addr50.ini": None,
    "mod_addr51.ini": None,
    "mod_addr99.ini": None,
}


class UE5ModManager:
    
    MOD_SOURCE = r"D:\FLTAH_Translator_by_zxsoszx\Game"
    
    def __init__(self, cache=None):
        self.cache = cache
        self._log_callback: Optional[Callable] = None
    
    def set_callbacks(self, log: Callable = None):
        self._log_callback = log
    
    def _log(self, msg: str):
        if self._log_callback:
            self._log_callback(msg)
        print(f"[UE5Mod] {msg}")
    
    def get_supported_games(self) -> list:
        games = []
        if os.path.exists(self.MOD_SOURCE):
            for item in os.listdir(self.MOD_SOURCE):
                zip_path = os.path.join(self.MOD_SOURCE, item, f"{item}.zip")
                if os.path.exists(zip_path):
                    games.append(item)
                
                alt_path = os.path.join(self.MOD_SOURCE, item)
                if os.path.isdir(alt_path):
                    for f in os.listdir(alt_path):
                        if f.endswith('.zip'):
                            games.append(item)
                            break
        
        return sorted(games)
    
    def install_mod(self, game_name: str, game_path: str, translate_dir_name: str = "Translate") -> bool:
        zip_path = os.path.join(self.MOD_SOURCE, game_name, f"{game_name}.zip")
        
        if not os.path.exists(zip_path):
            alt_path = os.path.join(self.MOD_SOURCE, game_name)
            if os.path.isdir(alt_path):
                for f in os.listdir(alt_path):
                    if f.endswith('.zip'):
                        zip_path = os.path.join(alt_path, f)
                        break
        
        if not os.path.exists(zip_path):
            self._log(f"Mod zip not found: {zip_path}")
            return False
        
        try:
            self._log(f"Installing mod from: {zip_path}")
            
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(game_path)
            
            self._log(f"Mod installed to: {game_path}")
            return True
        except Exception as e:
            self._log(f"Install error: {e}")
            return False
    
    def generate_subtitles(self, game_name: str, translate_dir: str, translations: Dict[str, str]) -> int:
        import arabic_reshaper
        from bidi.algorithm import get_display
        
        os.makedirs(translate_dir, exist_ok=True)
        
        count = 0
        for en_text, ar_text in translations.items():
            if not en_text or not ar_text or en_text == ar_text:
                continue
            
            reshaped = arabic_reshaper.reshape(ar_text)
            display = get_display(reshaped)
            
            import zlib
            hash_val = zlib.crc32(en_text.encode('utf-8')) & 0xFFFFFFFF
            
            en_path = os.path.join(translate_dir, f"{hash_val}.subtitle.en.txt")
            ar_path = os.path.join(translate_dir, f"{hash_val}.subtitle.txt")
            
            try:
                with open(en_path, 'w', encoding='utf-8') as f:
                    f.write(en_text)
                
                with open(ar_path, 'w', encoding='utf-8') as f:
                    f.write(display)
                
                count += 1
            except Exception as e:
                pass
        
        self._log(f"Generated {count} subtitle files in {translate_dir}")
        return count
    
    def export_cache_to_subtitles(self, game_name: str, translate_dir: str) -> int:
        if not self.cache:
            self._log("No cache available")
            return 0
        
        translations = self.cache.get_all_for_game(game_name)
        if not translations:
            self._log(f"No cached translations for {game_name}")
            return 0
        
        self._log(f"Exporting {len(translations)} translations to subtitles...")
        return self.generate_subtitles(game_name, translate_dir, translations)
    
    def create_mod_package(self, game_name: str, output_path: str) -> bool:
        try:
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr(f"{game_name}/Binaries/Win64/GameName.ini", game_name)
                z.writestr(f"{game_name}/Binaries/Win64/GameID.ini", "UnReal511Mod")
            
            self._log(f"Mod package created: {output_path}")
            return True
        except Exception as e:
            self._log(f"Package error: {e}")
            return False
    
    def list_installed_mods(self, game_path: str) -> dict:
        result = {
            "has_dxgi": False,
            "has_mod_dll": False,
            "has_translate": False,
            "subtitle_count": 0,
            "translate_dir": "",
        }
        
        win64_path = os.path.join(game_path, "ManorLords", "Binaries", "Win64")
        if not os.path.exists(win64_path):
            win64_path = os.path.join(game_path, "Binaries", "Win64")
        
        result["has_dxgi"] = os.path.exists(os.path.join(win64_path, "dxgi.dll"))
        result["has_mod_dll"] = os.path.exists(os.path.join(win64_path, "ZXSOSZXMod.dll"))
        
        translate_dir = os.path.join(win64_path, "Translate")
        if os.path.exists(translate_dir):
            result["has_translate"] = True
            result["translate_dir"] = translate_dir
            result["subtitle_count"] = len([f for f in os.listdir(translate_dir) if f.endswith('.subtitle.txt')])
        
        return result
