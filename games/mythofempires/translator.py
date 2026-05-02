import os
import re
import json
import shutil
import subprocess
import time
from typing import Optional, Dict, List, Callable, Tuple
from engine.arabic_processor import reshape_arabic_keep_tags


TOOL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "UE4localizationsTool", "UE4localizationsTool.exe")


class MythOfEmpiresTranslator:

    def __init__(self, game_path: str, translator_engine=None, cache=None):
        self.game_path = game_path
        self.engine = translator_engine
        self.cache = cache
        self.game_name = "Myth of Empires"
        self._stop_flag = False
        self._progress_callback: Optional[Callable] = None
        self._log_callback: Optional[Callable] = None
        self._total_strings = 0
        self._translated_strings = 0
        self._cached_strings = 0
        self._failed_strings = 0
        self._locres_path: Optional[str] = None
        self._txt_path: Optional[str] = None
        self._entries: Dict[str, str] = {}

    def set_callbacks(self, progress: Callable = None, log: Callable = None):
        self._progress_callback = progress
        self._log_callback = log

    def _log(self, msg: str):
        if self._log_callback:
            self._log_callback(msg)
        print(f"[MythOfEmpires] {msg}")

    def _update_progress(self, current: int, total: int, cached: int, failed: int):
        if self._progress_callback:
            self._progress_callback(current, total, cached, failed)

    def is_game_valid(self) -> bool:
        if not os.path.exists(self.game_path):
            return False
        return len(self.find_locres_files()) > 0

    def find_locres_files(self) -> List[str]:
        results = []
        search_dirs = [
            os.path.join(self.game_path, "MOE", "Content"),
            self.game_path,
        ]
        for search_dir in search_dirs:
            if not os.path.exists(search_dir):
                continue
            for root, dirs, files in os.walk(search_dir):
                for f in files:
                    if f.lower().endswith(".locres") and not f.endswith(".bak"):
                        results.append(os.path.join(root, f))
        return results

    def set_locres_path(self, path: str):
        self._locres_path = path
        self._txt_path = path + ".txt"
        self._log(f"Selected locres: {os.path.basename(path)}")

    def export_locres(self, locres_path: str = None) -> bool:
        if locres_path:
            self.set_locres_path(locres_path)

        if not self._locres_path or not os.path.exists(self._locres_path):
            self._log(f"ERROR: locres file not found: {self._locres_path}")
            return False

        if not os.path.exists(TOOL_PATH):
            self._log(f"ERROR: UE4localizationsTool not found at: {TOOL_PATH}")
            return False

        try:
            self._log(f"Exporting {os.path.basename(self._locres_path)}...")
            result = subprocess.run(
                [TOOL_PATH, "export", self._locres_path],
                capture_output=True, text=True, timeout=60
            )

            if result.returncode != 0:
                self._log(f"ERROR: Export failed: {result.stderr}")
                return False

            self._txt_path = self._locres_path + ".txt"
            if not os.path.exists(self._txt_path):
                self._log(f"ERROR: TXT file not created")
                return False

            return self._parse_txt()

        except subprocess.TimeoutExpired:
            self._log("ERROR: Export timed out")
            return False
        except Exception as e:
            self._log(f"ERROR: Export exception: {e}")
            return False

    def _parse_txt(self) -> bool:
        if not self._txt_path or not os.path.exists(self._txt_path):
            return False

        try:
            self._entries = {}
            with open(self._txt_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or "=" not in line:
                        continue
                    eq_pos = line.index("=")
                    key = line[:eq_pos]
                    value = line[eq_pos + 1:]
                    if key and value:
                        self._entries[key] = value

            self._total_strings = len(self._entries)
            self._log(f"Parsed {self._total_strings} entries from TXT")
            return True

        except Exception as e:
            self._log(f"ERROR: Parse TXT failed: {e}")
            return False

    def load_locres(self, path: str = None) -> bool:
        if path:
            self.set_locres_path(path)
        return self.export_locres()

    def get_entries(self) -> Dict[str, str]:
        return dict(self._entries)

    def get_entries_count(self) -> int:
        return len(self._entries)

    def translate_all(self, progress_callback: Callable = None, log_callback: Callable = None) -> bool:
        if progress_callback:
            self._progress_callback = progress_callback
        if log_callback:
            self._log_callback = log_callback

        self._stop_flag = False
        self._translated_strings = 0
        self._cached_strings = 0
        self._failed_strings = 0

        if not self._entries:
            if not self.export_locres():
                return False

        entries = self._entries
        self._total_strings = len(entries)

        self._log(f"Starting translation of {self._total_strings} entries...")

        for key, value in entries.items():
            if self._stop_flag:
                self._log("Translation stopped by user")
                return False

            if not value or len(value.strip()) < 2:
                continue

            cached = None
            if self.cache:
                cached = self.cache.get(self.game_name, value)

            if cached:
                self._entries[key] = cached
                self._cached_strings += 1
            else:
                result = self._translate_single(value)
                if result:
                    self._entries[key] = result
                    self._translated_strings += 1
                else:
                    self._failed_strings += 1

            done = self._translated_strings + self._cached_strings + self._failed_strings
            self._update_progress(done, self._total_strings, self._cached_strings, self._failed_strings)

        self._log(f"Translation complete! Total: {self._total_strings}, New: {self._translated_strings}, Cached: {self._cached_strings}, Failed: {self._failed_strings}")

        if self._write_txt():
            return self._import_locres()
        return False

    def _translate_single(self, text: str) -> Optional[str]:
        if not text or len(text.strip()) < 2:
            return None

        protected, replacements = self._protect_tokens(text)

        if self.engine:
            result = self.engine.translate(protected)
            if result:
                final = self._restore_tokens(result, replacements)
                reshaped = reshape_arabic_keep_tags(final)
                if self.cache:
                    self.cache.put(self.game_name, text, reshaped, self.engine.get_active_model() or "unknown")
                return reshaped

        return None

    TOKEN_PATTERN = re.compile(
        r'(\{[0-9]+\}|\{[A-Z_]+\}|%[A-Z_]+%|<[a-zA-Z/][^>]*>|\[[\w\s]+\])'
    )

    def _protect_tokens(self, text: str) -> Tuple[str, dict]:
        replacements = {}
        counter = [0]

        def replace_token(match):
            placeholder = f"__AGT_{counter[0]}__"
            replacements[placeholder] = match.group(0)
            counter[0] += 1
            return placeholder

        protected = self.TOKEN_PATTERN.sub(replace_token, text)
        return protected, replacements

    def _restore_tokens(self, text: str, replacements: dict) -> str:
        for placeholder, original in replacements.items():
            text = text.replace(placeholder, original)
        return text

    def _write_txt(self) -> bool:
        if not self._txt_path:
            return False

        try:
            backup = self._txt_path + ".bak"
            if not os.path.exists(backup) and os.path.exists(self._txt_path):
                shutil.copy2(self._txt_path, backup)

            with open(self._txt_path, "w", encoding="utf-8") as f:
                for key, value in self._entries.items():
                    f.write(f"{key}={value}\n")

            self._log(f"Wrote translated TXT: {os.path.basename(self._txt_path)}")
            return True

        except Exception as e:
            self._log(f"ERROR: Write TXT failed: {e}")
            return False

    def _import_locres(self) -> bool:
        if not self._txt_path or not os.path.exists(self._txt_path):
            self._log("ERROR: TXT file not found for import")
            return False

        try:
            self._log("Importing TXT back to locres...")
            result = subprocess.run(
                [TOOL_PATH, "-import", self._txt_path],
                capture_output=True, text=True, timeout=60
            )

            if result.returncode != 0:
                self._log(f"ERROR: Import failed: {result.stderr}")
                return False

            new_locres = self._locres_path.replace(".locres", "_NEW.locres")
            if os.path.exists(new_locres):
                backup = self._locres_path + ".bak"
                if not os.path.exists(backup):
                    shutil.copy2(self._locres_path, backup)

                shutil.copy2(new_locres, self._locres_path)
                os.remove(new_locres)
                self._log(f"Saved translated locres: {os.path.basename(self._locres_path)}")
                return True
            else:
                self._log(f"ERROR: _NEW.locres not created")
                return False

        except subprocess.TimeoutExpired:
            self._log("ERROR: Import timed out")
            return False
        except Exception as e:
            self._log(f"ERROR: Import exception: {e}")
            return False

    def stop(self):
        self._stop_flag = True

    def get_stats(self) -> dict:
        return {
            "total": self._total_strings,
            "translated": self._translated_strings,
            "cached": self._cached_strings,
            "failed": self._failed_strings,
            "locres_path": self._locres_path or "",
            "entries_count": self.get_entries_count(),
        }

    def sync_from_cache(self) -> int:
        if not self._entries:
            if not self.export_locres():
                return 0

        if not self.cache:
            return 0

        synced = 0
        for key, value in self._entries.items():
            if not value or len(value.strip()) < 2:
                continue
            cached = self.cache.get(self.game_name, value)
            if cached:
                self._entries[key] = cached
                synced += 1

        if synced > 0:
            if self._write_txt():
                self._import_locres()
            self._log(f"Synced {synced} entries from cache")

        return synced

    def export_to_json(self, output_path: str) -> bool:
        if not self._entries:
            if not self.export_locres():
                return False

        try:
            data = {
                "game": self.game_name,
                "source": os.path.basename(self._locres_path or ""),
                "entries": self._entries
            }
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._log(f"Exported {len(self._entries)} entries to {output_path}")
            return True
        except Exception as e:
            self._log(f"Export error: {e}")
            return False
