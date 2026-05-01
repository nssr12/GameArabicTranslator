import os
import sys
import shutil
import json
from typing import Optional


class RoR2FontPatcher:
    
    def __init__(self, game_path: str):
        self.game_path = game_path
        self.data_path = os.path.join(game_path, "Risk of Rain 2_Data")
        self.bundles_path = os.path.join(self.data_path, "StreamingAssets", "aa", "StandaloneWindows64")
        self.backup_dir = os.path.join(game_path, "_font_backup")
        
        self.ARABIC_FONT_PATH = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "assets", "fonts", "Aljazeera.ttf"
        )
        
        self.FONT_BUNDLES = [
            "ror2-base-common-fonts-bombardier_assets_all",
            "ror2-base-common-fonts-noto_assets_all",
            "textmeshpro-formerresources-fonts&materials_assets_all",
        ]
    
    def _find_bundle(self, prefix: str) -> Optional[str]:
        if not os.path.exists(self.bundles_path):
            return None
        
        for f in os.listdir(self.bundles_path):
            if f.startswith(prefix) and f.endswith(".bundle"):
                return os.path.join(self.bundles_path, f)
        return None
    
    def _backup_file(self, filepath: str):
        os.makedirs(self.backup_dir, exist_ok=True)
        backup_path = os.path.join(self.backup_dir, os.path.basename(filepath))
        if not os.path.exists(backup_path):
            shutil.copy2(filepath, backup_path)
    
    def patch_fonts(self, log_callback=None) -> bool:
        def log(msg):
            if log_callback:
                log_callback(msg)
            print(f"[FontPatcher] {msg}")
        
        if not os.path.exists(self.ARABIC_FONT_PATH):
            log(f"Arabic font not found: {self.ARABIC_FONT_PATH}")
            return False
        
        try:
            import UnityPy
            from UnityPy.enums import ClassIDType
        except ImportError:
            log("UnityPy not installed. Run: pip install UnityPy")
            return False
        
        try:
            with open(self.ARABIC_FONT_PATH, "rb") as f:
                arabic_font_data = f.read()
            log(f"Loaded Arabic font: {len(arabic_font_data)} bytes")
        except Exception as e:
            log(f"Failed to read Arabic font: {e}")
            return False
        
        patched_count = 0
        
        for bundle_prefix in self.FONT_BUNDLES:
            bundle_path = self._find_bundle(bundle_prefix)
            if not bundle_path:
                log(f"Bundle not found: {bundle_prefix}")
                continue
            
            log(f"Patching: {os.path.basename(bundle_path)}")
            
            try:
                self._backup_file(bundle_path)
                
                env = UnityPy.load(bundle_path)
                
                font_count = 0
                for obj in env.objects:
                    if obj.type == ClassIDType.Font:
                        try:
                            data = obj.read()
                            font_name = data.m_Name if hasattr(data, 'm_Name') else 'unknown'
                            
                            data.m_FontData = bytearray(arabic_font_data)
                            data.save()
                            
                            font_count += 1
                            log(f"  Patched font: {font_name}")
                        except Exception as e:
                            log(f"  Font patch error: {e}")
                    
                    elif obj.type == ClassIDType.MonoBehaviour:
                        try:
                            data = obj.read()
                            if hasattr(data, 'atlas') and hasattr(data, 'faceInfo'):
                                if hasattr(data, 'm_FontData'):
                                    data.m_FontData = bytearray(arabic_font_data)
                                    data.save()
                                    font_count += 1
                                    log(f"  Patched TMP font asset")
                        except:
                            pass
                
                if font_count > 0:
                    with open(bundle_path, 'wb') as f:
                        f.write(env.file.save())
                    patched_count += font_count
                    log(f"  Saved {font_count} fonts in bundle")
                
            except Exception as e:
                log(f"Bundle error: {e}")
        
        log(f"Total fonts patched: {patched_count}")
        return patched_count > 0
    
    def restore_backups(self, log_callback=None) -> bool:
        def log(msg):
            if log_callback:
                log_callback(msg)
            print(f"[FontPatcher] {msg}")
        
        if not os.path.exists(self.backup_dir):
            log("No backups found")
            return False
        
        restored = 0
        for filename in os.listdir(self.backup_dir):
            src = os.path.join(self.backup_dir, filename)
            dst = os.path.join(self.bundles_path, filename)
            try:
                shutil.copy2(src, dst)
                restored += 1
                log(f"Restored: {filename}")
            except Exception as e:
                log(f"Restore error {filename}: {e}")
        
        log(f"Restored {restored} files")
        return restored > 0
    
    def has_backups(self) -> bool:
        return os.path.exists(self.backup_dir) and len(os.listdir(self.backup_dir)) > 0
