import struct
import os
import re
import json
import shutil
from typing import Optional, Dict, List, Callable, Tuple
from engine.arabic_processor import reshape_arabic_keep_tags


class LocresFile:
    """Parser for Unreal Engine .locres files (supports both standard and custom formats)."""

    MAGIC_STANDARD = 0xE78A21B5
    MAGIC_CUSTOM = 0x0E147475

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.entries: Dict[str, str] = {}
        self._raw_header = b""
        self._raw_body = b""
        self._magic = 0
        self._version = 0
        self._header_size = 0

    def read(self) -> bool:
        if not os.path.exists(self.filepath):
            return False

        with open(self.filepath, "rb") as f:
            data = f.read()

        if len(data) < 4:
            return False

        magic = struct.unpack_from("<I", data, 0)[0]

        if magic == self.MAGIC_STANDARD:
            return self._read_standard(data)
        elif magic == self.MAGIC_CUSTOM:
            return self._read_custom(data)
        else:
            return self._read_custom(data)

    def _read_standard(self, data: bytes) -> bool:
        try:
            offset = 4
            self._version = struct.unpack_from("<B", data, offset)[0]
            offset += 1

            if self._version >= 2:
                str_len = struct.unpack_from("<I", data, offset)[0]
                offset += 4
                offset += str_len

            if self._version >= 3:
                offset += 8

            entry_count = struct.unpack_from("<I", data, offset)[0]
            offset += 4

            self._magic = self.MAGIC_STANDARD
            self.entries = {}

            for _ in range(entry_count):
                ns_len = struct.unpack_from("<I", data, offset)[0]
                offset += 4
                namespace = data[offset:offset + ns_len].decode("utf-8", errors="replace").rstrip("\x00")
                offset += ns_len

                key_len = struct.unpack_from("<I", data, offset)[0]
                offset += 4
                key = data[offset:offset + key_len].decode("utf-8", errors="replace").rstrip("\x00")
                offset += key_len

                source_hash = data[offset:offset + 16]
                offset += 16

                val_len = struct.unpack_from("<i", data, offset)[0]
                offset += 4

                if val_len > 0:
                    value = data[offset:offset + val_len * 2].decode("utf-16-le", errors="replace").rstrip("\x00")
                    offset += val_len * 2
                elif val_len < 0:
                    val_bytes = abs(val_len)
                    value = data[offset:offset + val_bytes].decode("utf-8", errors="replace").rstrip("\x00")
                    offset += val_bytes
                else:
                    value = ""

                full_key = f"{namespace}:{key}" if namespace else key
                self.entries[full_key] = value

            self._header_size = 0
            self._raw_body = data
            return True

        except Exception as e:
            print(f"[LocresFile] Standard parse error: {e}")
            return False

    def _read_custom(self, data: bytes) -> bool:
        try:
            self._magic = struct.unpack_from("<I", data, 0)[0]
            self._raw_header = data[:37]
            self._header_size = 37

            strings = []
            pos = 37

            while pos < len(data) - 4:
                str_len = struct.unpack_from("<I", data, pos)[0]
                pos += 4

                if str_len == 0 or str_len > 10000:
                    pos += 4
                    continue

                raw_str = data[pos:pos + str_len]
                pos += str_len

                try:
                    s = raw_str.decode("utf-8", errors="replace").rstrip("\x00")
                    if len(s) > 1:
                        strings.append(s)
                except:
                    pass

            keys = []
            values = []

            for s in strings:
                if self._is_key(s):
                    keys.append(s)
                else:
                    values.append(s)

            self.entries = {}
            for i, key in enumerate(keys):
                if i < len(values):
                    self.entries[key] = values[i]
                else:
                    self.entries[key] = ""

            self._raw_body = data
            return len(self.entries) > 0

        except Exception as e:
            print(f"[LocresFile] Custom parse error: {e}")
            return False

    def _is_key(self, s: str) -> bool:
        if not s:
            return False
        if re.match(r'^[A-F0-9]{32}$', s):
            return False
        if any(c in s for c in ['_', 'DataTable', 'Key ', 'ToolTips', 'Command']):
            return True
        if s[0].isupper() and '_' in s:
            return True
        return False

    def write(self, output_path: str = None) -> bool:
        if output_path is None:
            output_path = self.filepath

        if self._magic == self.MAGIC_STANDARD:
            return self._write_standard(output_path)
        else:
            return self._write_custom(output_path)

    def _write_standard(self, output_path: str) -> bool:
        try:
            with open(output_path, "wb") as f:
                f.write(struct.pack("<I", self.MAGIC_STANDARD))
                f.write(struct.pack("<B", self._version))

                if self._version >= 2:
                    f.write(struct.pack("<I", 0))

                if self._version >= 3:
                    f.write(struct.pack("<Q", 0))

                f.write(struct.pack("<I", len(self.entries)))

                for full_key, value in self.entries.items():
                    if ":" in full_key:
                        namespace, key = full_key.split(":", 1)
                    else:
                        namespace, key = "", full_key

                    ns_bytes = namespace.encode("utf-8") + b"\x00"
                    f.write(struct.pack("<I", len(ns_bytes)))
                    f.write(ns_bytes)

                    key_bytes = key.encode("utf-8") + b"\x00"
                    f.write(struct.pack("<I", len(key_bytes)))
                    f.write(key_bytes)

                    f.write(b"\x00" * 16)

                    if value:
                        val_bytes = value.encode("utf-16-le") + b"\x00\x00"
                        f.write(struct.pack("<i", len(value) + 1))
                        f.write(val_bytes)
                    else:
                        f.write(struct.pack("<i", 0))

            return True
        except Exception as e:
            print(f"[LocresFile] Standard write error: {e}")
            return False

    def _write_custom(self, output_path: str) -> bool:
        try:
            with open(self.filepath, "rb") as f:
                original = f.read()

            key_section_end = self._find_key_section_end(original)
            if key_section_end is None:
                return self._write_standard(output_path)

            key_section = original[:key_section_end]
            value_section_start = self._find_value_section_start(original)

            if value_section_start is None:
                value_section_start = key_section_end

            new_values = b""
            for key, value in self.entries.items():
                if value:
                    encoded = value.encode("utf-16-le") + b"\x00\x00"
                    new_values += struct.pack("<I", len(encoded)) + encoded

            with open(output_path, "wb") as f:
                f.write(key_section)
                f.write(original[key_section_end:value_section_start])
                f.write(new_values)

            return True

        except Exception as e:
            print(f"[LocresFile] Custom write error: {e}")
            return False

    def _find_key_section_end(self, data: bytes) -> None:
        return None

    def _find_value_section_start(self, data: bytes) -> None:
        return None


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
        self._locres: Optional[LocresFile] = None

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

        locres_paths = self.find_locres_files()
        return len(locres_paths) > 0

    def find_locres_files(self) -> List[str]:
        results = []
        search_dirs = [
            os.path.join(self.game_path, "MOE", "Content"),
            os.path.join(self.game_path),
        ]

        for search_dir in search_dirs:
            if not os.path.exists(search_dir):
                continue
            for root, dirs, files in os.walk(search_dir):
                for f in files:
                    if f.lower().endswith(".locres"):
                        results.append(os.path.join(root, f))

        return results

    def set_locres_path(self, path: str):
        self._locres_path = path
        self._log(f"Selected locres: {os.path.basename(path)}")

    def load_locres(self, path: str = None) -> bool:
        if path:
            self._locres_path = path

        if not self._locres_path:
            self._log("ERROR: No locres file selected")
            return False

        self._locres = LocresFile(self._locres_path)
        if self._locres.read():
            self._total_strings = len(self._locres.entries)
            self._log(f"Loaded {self._total_strings} entries from {os.path.basename(self._locres_path)}")
            return True
        else:
            self._log(f"ERROR: Failed to parse {self._locres_path}")
            return False

    def get_entries(self) -> Dict[str, str]:
        if self._locres:
            return dict(self._locres.entries)
        return {}

    def get_entries_count(self) -> int:
        if self._locres:
            return len(self._locres.entries)
        return 0

    def translate_all(self, progress_callback: Callable = None, log_callback: Callable = None) -> bool:
        if progress_callback:
            self._progress_callback = progress_callback
        if log_callback:
            self._log_callback = log_callback

        self._stop_flag = False
        self._translated_strings = 0
        self._cached_strings = 0
        self._failed_strings = 0

        if not self._locres:
            if not self.load_locres():
                return False

        entries = self._locres.entries
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
                self._locres.entries[key] = cached
                self._cached_strings += 1
            else:
                result = self._translate_single(value)
                if result:
                    self._locres.entries[key] = result
                    self._translated_strings += 1
                else:
                    self._failed_strings += 1

            done = self._translated_strings + self._cached_strings + self._failed_strings
            self._update_progress(done, self._total_strings, self._cached_strings, self._failed_strings)

        self._log(f"Translation complete! Total: {self._total_strings}, New: {self._translated_strings}, Cached: {self._cached_strings}, Failed: {self._failed_strings}")

        if self._locres_path:
            backup_path = self._locres_path + ".bak"
            if not os.path.exists(backup_path):
                shutil.copy2(self._locres_path, backup_path)
                self._log(f"Backup saved: {os.path.basename(backup_path)}")

            if self._locres.write(self._locres_path):
                self._log(f"Saved translated locres: {os.path.basename(self._locres_path)}")
                return True
            else:
                self._log("ERROR: Failed to write locres file")
                return False

        return True

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
        if not self._locres:
            if not self.load_locres():
                return 0

        if not self.cache:
            return 0

        synced = 0
        for key, value in self._locres.entries.items():
            if not value or len(value.strip()) < 2:
                continue

            cached = self.cache.get(self.game_name, value)
            if cached:
                self._locres.entries[key] = cached
                synced += 1

        if synced > 0 and self._locres_path:
            backup_path = self._locres_path + ".bak"
            if not os.path.exists(backup_path):
                shutil.copy2(self._locres_path, backup_path)

            self._locres.write(self._locres_path)
            self._log(f"Synced {synced} entries from cache")

        return synced

    def export_to_json(self, output_path: str) -> bool:
        if not self._locres:
            if not self.load_locres():
                return False

        try:
            data = {
                "game": self.game_name,
                "source": os.path.basename(self._locres_path or ""),
                "entries": self._locres.entries
            }
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._log(f"Exported {len(self._locres.entries)} entries to {output_path}")
            return True
        except Exception as e:
            self._log(f"Export error: {e}")
            return False

    def import_from_json(self, json_path: str) -> int:
        if not self._locres:
            if not self.load_locres():
                return 0

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            entries = data.get("entries", {})
            imported = 0
            for key, value in entries.items():
                if key in self._locres.entries:
                    self._locres.entries[key] = value
                    imported += 1

            if imported > 0 and self._locres_path:
                self._locres.write(self._locres_path)

            self._log(f"Imported {imported} entries from {json_path}")
            return imported
        except Exception as e:
            self._log(f"Import error: {e}")
            return 0
