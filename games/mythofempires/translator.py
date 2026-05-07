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

    def __init__(self, game_path: str, translator_engine=None, cache=None,
                 unrealpak_path: str = None, reshape_text: bool = False):
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
        self._unrealpak_path: Optional[str] = unrealpak_path
        self._reshape_text: bool = reshape_text

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
                    line = line.rstrip('\r\n')  # preserve trailing spaces in values
                    if not line or "=" not in line:
                        continue
                    eq_pos = line.index("=")
                    key = line[:eq_pos]
                    value = line[eq_pos + 1:]
                    if key:
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

            # Skip entries that are already in Arabic (from a previous translation run)
            if any('؀' <= c <= 'ۿ' for c in value):
                self._cached_strings += 1
                done = self._translated_strings + self._cached_strings + self._failed_strings
                self._update_progress(done, self._total_strings, self._cached_strings, self._failed_strings)
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
            if self._import_locres():
                self._pack_to_pak()
                return True
        return False

    def _translate_single(self, text: str) -> Optional[str]:
        if not text or len(text.strip()) < 2:
            return None

        protected, replacements = self._protect_tokens(text)

        if self.engine:
            result = self.engine.translate(protected)
            if result:
                final = self._restore_tokens(result, replacements)
                output = reshape_arabic_keep_tags(final) if self._reshape_text else final
                if self.cache:
                    self.cache.put(self.game_name, text, output, self.engine.get_active_model() or "unknown")
                return output

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

            with open(self._txt_path, "w", encoding="utf-8", newline='') as f:
                for key, value in self._entries.items():
                    f.write(f"{key}={value}\r\n")

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
                [TOOL_PATH, "import", self._txt_path],
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

    def _find_pak_folder(self) -> Optional[tuple]:
        """Find the pakchunk folder from locres_path. Returns (pak_folder, output_pak_path) or None."""
        if not self._locres_path:
            return None
        norm = self._locres_path.replace('\\', '/')
        parts = norm.split('/')
        for i, part in enumerate(parts):
            if 'pakchunk' in part.lower() and part.lower().endswith('_p'):
                pak_folder = os.path.normpath('/'.join(parts[:i + 1]))
                pak_dir = os.path.normpath('/'.join(parts[:i]))
                output_pak = os.path.join(pak_dir, part + '.pak')
                return pak_folder, output_pak
        return None

    def _find_unrealpak(self) -> Optional[str]:
        """Find UnrealPak.exe from config path or common UE installation directories."""
        if self._unrealpak_path and os.path.isfile(self._unrealpak_path):
            return self._unrealpak_path
        candidates = [
            os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'UnrealPak.exe')),
        ]
        for drive in ['C', 'D', 'E', 'F']:
            base = f'{drive}:\\Program Files\\Epic Games'
            if os.path.isdir(base):
                try:
                    for entry in os.listdir(base):
                        candidates.append(os.path.join(base, entry, 'Engine', 'Binaries', 'Win64', 'UnrealPak.exe'))
                except OSError:
                    pass
        for c in candidates:
            if os.path.isfile(c):
                return os.path.normpath(c)
        return None

    def _pack_to_pak(self) -> bool:
        """Pack the pakchunk folder into a .pak file using UnrealPak.exe."""
        result = self._find_pak_folder()
        if not result:
            self._log('Pack: Could not find pakchunk folder in locres path')
            return False

        pak_folder, output_pak = result

        if not os.path.isdir(pak_folder):
            self._log(f'Pack: Folder not found: {pak_folder}')
            return False

        tool = self._find_unrealpak()
        if not tool:
            self._log('Pack: UnrealPak.exe not found.')
            self._log('  Options: (1) Go to Settings -> UE4 Tools and browse for UnrealPak.exe')
            self._log('  (2) Copy UnrealPak.exe to: tools\\UnrealPak.exe inside the app folder')
            self._log(f'  Translated locres is ready at: {self._locres_path}')
            return False

        self._log(f'Packing {os.path.basename(pak_folder)} -> {os.path.basename(output_pak)}...')

        # Extensions to exclude from the pak (temp files created during translation)
        _EXCLUDE_EXT = {'.txt', '.bak'}

        try:
            import tempfile

            # Build per-file filelist excluding temp files
            entries_added = 0
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as rf:
                response_path = rf.name
                for root, _, files in os.walk(pak_folder):
                    for fname in files:
                        ext = os.path.splitext(fname)[1].lower()
                        if ext in _EXCLUDE_EXT:
                            continue
                        src = os.path.join(root, fname)
                        rel = os.path.relpath(src, pak_folder).replace('\\', '/')
                        rf.write(f'"{src}" "../../../{rel}"\n')
                        entries_added += 1

            self._log(f'Pack: {entries_added} files queued')

            if os.path.exists(output_pak):
                bak = output_pak + '.bak'
                if not os.path.exists(bak):
                    shutil.copy2(output_pak, bak)
                    self._log(f'Backed up existing: {os.path.basename(bak)}')

            proc = subprocess.run(
                [tool, output_pak, f'-create={response_path}'],
                capture_output=True, text=True, timeout=120
            )
            try:
                os.remove(response_path)
            except OSError:
                pass

            if proc.returncode != 0:
                self._log(f'Pack ERROR (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}')
                return False

            if os.path.exists(output_pak):
                size_mb = os.path.getsize(output_pak) / (1024 * 1024)
                self._log(f'Pack complete: {os.path.basename(output_pak)} ({size_mb:.1f} MB)')
                self._log(f'Location: {output_pak}')
                return True
            else:
                self._log('Pack ERROR: Output .pak file was not created')
                return False

        except subprocess.TimeoutExpired:
            self._log('Pack ERROR: UnrealPak timed out after 120s')
            return False
        except Exception as e:
            self._log(f'Pack ERROR: {e}')
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
                if self._import_locres():
                    self._pack_to_pak()
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
