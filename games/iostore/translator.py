import os
import re
import json
import subprocess
import time
from typing import Optional, Dict, List, Callable, Any, Tuple

from engine.models.base import translate_preserving_tokens


_TOOLS_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
_RETOC_DEFAULT    = os.path.join(_TOOLS_DIR, "retoc", "retoc.exe")
_UASSETGUI_DEFAULT = os.path.join(_TOOLS_DIR, "UAssetGUI.exe")

# UAssetGUI version format (VER_ prefix)
UE_VERSIONS = [
    "VER_UE5_6", "VER_UE5_5", "VER_UE5_4", "VER_UE5_3",
    "VER_UE5_2", "VER_UE5_1", "VER_UE5_0",
    "VER_UE4_27", "VER_UE4_26", "VER_UE4_25", "VER_UE4_24",
    "VER_UE4_23", "VER_UE4_22", "VER_UE4_21", "VER_UE4_20",
]

# retoc to-zen version format (no VER_ prefix) — same order as UE_VERSIONS
ZEN_VERSIONS = [v.replace("VER_", "") for v in UE_VERSIONS]

# (value, display_label) pairs for the wizard Extraction Mode dropdown
EXTRACTION_MODES = [
    ("default_text",       "DefaultText  (Grounded2, general UE assets)"),
    ("datatable_english",  "DataTable — english_* column  (Manor Lords)"),
]


class IoStoreTranslator:

    def __init__(self, translator_engine=None, cache=None,
                 retoc_path: str = None, uassetgui_path: str = None):
        self.engine = translator_engine
        self.cache = cache
        self.retoc_path = retoc_path or _RETOC_DEFAULT
        self.uassetgui_path = uassetgui_path or _UASSETGUI_DEFAULT
        self._stop_flag = False
        self._pause_flag = False
        self._log_callback: Optional[Callable] = None
        self._progress_callback: Optional[Callable] = None

    def set_callbacks(self, log: Callable = None, progress: Callable = None):
        self._log_callback = log
        self._progress_callback = progress

    def _log(self, msg: str):
        if self._log_callback:
            self._log_callback(msg)
        else:
            print(f"[IoStore] {msg}")

    def _progress(self, current: int, total: int):
        if self._progress_callback:
            self._progress_callback(current, total)

    def stop(self):
        self._stop_flag = True

    def pause(self):
        self._pause_flag = True

    def resume(self):
        self._pause_flag = False

    def _cmd_str(self, cmd: list) -> str:
        """Format a command list as a CLI string with quotes around arguments that contain spaces."""
        parts = []
        for arg in cmd:
            parts.append(f'"{arg}"' if " " in str(arg) else str(arg))
        return " ".join(parts)

    def _run(self, cmd: list, timeout: int = 300) -> tuple[bool, str]:
        """Run subprocess, return (success, combined_output)."""
        self._log(f"$ {self._cmd_str(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            out = (result.stdout or "").strip()
            err = (result.stderr or "").strip()
            combined = "\n".join(filter(None, [out, err]))
            return result.returncode == 0, combined
        except subprocess.TimeoutExpired:
            return False, f"Timed out after {timeout}s"
        except FileNotFoundError:
            return False, f"File not found: {cmd[0]}"
        except Exception as e:
            return False, str(e)

    # ── Step 1: IoStore paks folder → Legacy folder ───────────────────

    def to_legacy(self, paks_input: str, output_dir: str, aes_key: str = "") -> bool:
        """
        paks_input: path to the game's Paks folder (contains .utoc/.ucas/.pak files)
                    OR a single .utoc file path.
        output_dir: destination folder for the extracted legacy assets.
        """
        if not os.path.exists(self.retoc_path):
            self._log(f"ERROR: retoc.exe not found at: {self.retoc_path}")
            return False
        if not os.path.exists(paks_input):
            self._log(f"ERROR: path not found: {paks_input}")
            return False

        cmd = [self.retoc_path, "to-legacy", paks_input, output_dir]
        if aes_key.strip():
            cmd += ["--aes-key", aes_key.strip()]

        ok, out = self._run(cmd, timeout=300)
        for line in out.splitlines():
            self._log(f"  {line}")
        if not ok:
            self._log("ERROR: to-legacy failed")
            return False
        if not os.path.isdir(output_dir):
            self._log(f"WARNING: output folder not found after extraction: {output_dir}")
        self._log("✓ Step 1 complete")
        return True

    # ── Step 2: .uasset → JSON ────────────────────────────────────────

    def uasset_to_json(self, uasset_path: str, ue_version: str,
                       mappings: str = "") -> Optional[str]:
        if not os.path.exists(self.uassetgui_path):
            self._log(f"ERROR: UAssetGUI.exe not found at: {self.uassetgui_path}")
            return None
        if not os.path.isfile(uasset_path):
            self._log(f"ERROR: .uasset not found: {uasset_path}")
            return None

        json_path = uasset_path + ".json"
        cmd = [self.uassetgui_path, "tojson", uasset_path, json_path, ue_version]
        if mappings.strip():
            cmd.append(mappings.strip())
        ok, out = self._run(cmd, timeout=60)
        for line in out.splitlines():
            self._log(f"  {line}")
        if not ok or not os.path.isfile(json_path):
            self._log(f"ERROR: tojson failed for {os.path.basename(uasset_path)}")
            return None
        return json_path

    def uasset_folder_to_json(self, folder: str, ue_version: str,
                               mappings: str = "") -> List[str]:
        """Convert every .uasset in folder tree to JSON. Returns list of JSON paths."""
        results = []
        for root, _, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(".uasset"):
                    path = os.path.join(root, f)
                    j = self.uasset_to_json(path, ue_version, mappings)
                    if j:
                        results.append(j)
        return results

    # ── Step 3: Extract translatable texts ────────────────────────────

    def extract_texts_from_json(self, json_path: str,
                                mode: str = "default_text") -> List[str]:
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw: List[str] = []
            if mode == "datatable_english":
                self._collect_datatable_english(data, raw)
            else:
                self._collect_default_texts(data, raw)
            seen: set = set()
            unique: List[str] = []
            for t in raw:
                if t and t.strip() and t not in seen:
                    seen.add(t)
                    unique.append(t)
            return unique
        except Exception as e:
            self._log(f"ERROR extracting {os.path.basename(json_path)}: {e}")
            return []

    def extract_texts_from_folder(self, folder: str,
                                   mode: str = "default_text") -> Dict[str, List[str]]:
        """Returns {json_path: [texts]} for all .uasset.json files in folder tree."""
        results: Dict[str, List[str]] = {}
        for root, _, files in os.walk(folder):
            for f in files:
                if f.endswith(".uasset.json"):
                    path = os.path.join(root, f)
                    texts = self.extract_texts_from_json(path, mode)
                    if texts:
                        results[path] = texts
        return results

    def _collect_default_texts(self, obj: Any, out: list):
        if isinstance(obj, dict):
            if (obj.get("Name") == "DefaultText"
                    and isinstance(obj.get("Value"), str)
                    and obj["Value"].strip()):
                out.append(obj["Value"])
            for v in obj.values():
                self._collect_default_texts(v, out)
        elif isinstance(obj, list):
            for item in obj:
                self._collect_default_texts(item, out)

    def _collect_datatable_english(self, obj: Any, out: list):
        """Extract english_* StrPropertyData values from UAssetAPI DataTable JSON."""
        if isinstance(obj, dict):
            name = obj.get("Name", "")
            if (isinstance(name, str)
                    and name.lower().startswith("english_")
                    and "StrPropertyData" in obj.get("$type", "")
                    and isinstance(obj.get("Value"), str)
                    and obj["Value"].strip()):
                out.append(obj["Value"])
            else:
                for v in obj.values():
                    self._collect_datatable_english(v, out)
        elif isinstance(obj, list):
            for item in obj:
                self._collect_datatable_english(item, out)

    # ── Step 3: Translate ─────────────────────────────────────────────

    def translate_texts(self, texts: List[str],
                        game_name: str = "IoStore",
                        use_cache: bool = True) -> Dict[str, str]:
        self._stop_flag = False
        translations: Dict[str, str] = {}
        total = len(texts)

        if use_cache and self.cache and texts:
            cached = self.cache.get_batch(game_name, texts)
            translations.update(cached)
            self._log(f"Cache: {len(cached)}/{total} found")
            self._progress(len(translations), total)

        remaining = [t for t in texts if t not in translations]
        for text in remaining:
            if self._stop_flag:
                self._log("Translation stopped by user")
                break
            while self._pause_flag and not self._stop_flag:
                time.sleep(0.3)
            if not text or len(text.strip()) < 2:
                self._progress(len(translations), total)
                continue
            try:
                if self.engine:
                    result = translate_preserving_tokens(text, self.engine.translate)
                    if result and result != text:
                        translations[text] = result
                        if self.cache:
                            try:
                                model = self.engine.get_active_model() or "unknown"
                            except Exception:
                                model = "unknown"
                            self.cache.put(game_name, text, result, model)
            except Exception as e:
                self._log(f"  Translate error: {e}")
            self._progress(len(translations), total)

        self._log(f"Translation done: {len(translations)}/{total}")
        return translations

    # ── Step 3b: Apply translations back to JSON ──────────────────────

    def apply_translations_to_json(self, json_path: str,
                                   translations: Dict[str, str],
                                   mode: str = "default_text",
                                   source_path: str = None) -> bool:
        """
        source_path: read source data from this file (e.g. .orig backup) but write to json_path.
                     If omitted, reads and writes json_path.
        """
        read_path = source_path or json_path
        try:
            with open(read_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # save original (pre-translation) backup once — used by Step 6 re-sync
            if source_path is None:
                orig_path = json_path + ".orig"
                if not os.path.exists(orig_path):
                    import shutil
                    shutil.copy2(json_path, orig_path)
                    self._log(f"Saved original backup: {os.path.basename(orig_path)}")
            if mode == "datatable_english":
                self._replace_datatable_english(data, translations)
            else:
                self._replace_default_texts(data, translations)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._log(f"Applied translations: {os.path.basename(json_path)}")
            return True
        except Exception as e:
            self._log(f"ERROR applying to {os.path.basename(json_path)}: {e}")
            return False

    def _replace_default_texts(self, obj: Any, translations: Dict[str, str]):
        if isinstance(obj, dict):
            if (obj.get("Name") == "DefaultText"
                    and isinstance(obj.get("Value"), str)
                    and obj["Value"] in translations):
                obj["Value"] = translations[obj["Value"]]
            for v in obj.values():
                self._replace_default_texts(v, translations)
        elif isinstance(obj, list):
            for item in obj:
                self._replace_default_texts(item, translations)

    def _replace_datatable_english(self, obj: Any, translations: Dict[str, str]):
        """Replace english_* StrPropertyData values in UAssetAPI DataTable JSON."""
        if isinstance(obj, dict):
            name = obj.get("Name", "")
            if (isinstance(name, str)
                    and name.lower().startswith("english_")
                    and "StrPropertyData" in obj.get("$type", "")
                    and isinstance(obj.get("Value"), str)
                    and obj["Value"] in translations):
                obj["Value"] = translations[obj["Value"]]
            else:
                for v in obj.values():
                    self._replace_datatable_english(v, translations)
        elif isinstance(obj, list):
            for item in obj:
                self._replace_datatable_english(item, translations)

    # ── Step 4a: JSON → .uasset ───────────────────────────────────────

    def json_to_uasset(self, json_path: str, ue_version: str,
                       mappings: str = "") -> bool:
        if not os.path.exists(self.uassetgui_path):
            self._log("ERROR: UAssetGUI.exe not found")
            return False
        if not os.path.isfile(json_path):
            self._log(f"ERROR: JSON not found: {json_path}")
            return False

        if json_path.endswith(".uasset.json"):
            uasset_path = json_path[:-5]  # strip ".json"
        else:
            uasset_path = json_path.rsplit(".json", 1)[0]

        cmd = [self.uassetgui_path, "fromjson", json_path, uasset_path]
        if mappings.strip():
            cmd.append(mappings.strip())
        ok, out = self._run(cmd, timeout=60)
        for line in out.splitlines():
            self._log(f"  {line}")
        if not ok:
            self._log(f"ERROR: fromjson failed for {os.path.basename(json_path)}")
            return False
        return True

    def json_folder_to_uasset(self, folder: str, ue_version: str,
                               mappings: str = "") -> int:
        """Convert all .uasset.json files in folder tree back to .uasset. Returns count."""
        count = 0
        for root, _, files in os.walk(folder):
            for f in files:
                if f.endswith(".uasset.json"):
                    if self.json_to_uasset(os.path.join(root, f), ue_version, mappings):
                        count += 1
        return count

    # ── Step 4b: Legacy folder → IoStore (.utoc/.ucas) ────────────────

    def to_zen(self, legacy_folder: str, output_base: str,
               zen_version: str = "UE5_6", aes_key: str = "") -> bool:
        """
        zen_version: UE version string without VER_ prefix, e.g. 'UE5_6', 'UE5_5'.
                     Passed as: retoc to-zen --version <zen_version> <INPUT> <OUTPUT>
        """
        if not os.path.exists(self.retoc_path):
            self._log("ERROR: retoc.exe not found")
            return False
        if not os.path.isdir(legacy_folder):
            self._log(f"ERROR: folder not found: {legacy_folder}")
            return False
        if not zen_version:
            self._log("ERROR: zen_version is required (e.g. UE5_6)")
            return False

        # retoc treats the output path literally as the .utoc filename, then derives .ucas from it
        base = output_base[:-5] if output_base.endswith(".utoc") else output_base
        utoc_out = base + "_P.utoc"
        cmd = [self.retoc_path, "to-zen", "--version", zen_version,
               legacy_folder, utoc_out]
        if aes_key.strip():
            cmd += ["--aes-key", aes_key.strip()]

        ok, out = self._run(cmd, timeout=300)
        for line in out.splitlines():
            self._log(f"  {line}")
        if not ok:
            self._log("ERROR: to-zen failed")
            return False
        self._log(f"✓ Step 5 complete → {utoc_out}")
        # retoc only produces .utoc/.ucas — create .pak stub so the engine recognises the mod
        pak_out = utoc_out[:-5] + ".pak"
        if not os.path.exists(pak_out):
            self._create_pak_stub(pak_out)
        return True

    def _create_pak_stub(self, path: str):
        """Create a minimal valid UE pak file (IoStore container stub)."""
        import struct, hashlib
        stub = (
            struct.pack('<I', 0x5A6F12E1) +   # magic
            struct.pack('<i', 8) +             # version 8 (accepted by UE4/5)
            struct.pack('<q', 0) +             # index offset
            struct.pack('<q', 0) +             # index size
            hashlib.sha1(b'').digest() +       # SHA1 of empty index (20 bytes)
            struct.pack('<B', 0) +             # bEncryptedIndex = false
            bytes(16) +                        # EncryptionKeyGuid = null
            struct.pack('<i', 0)               # CompressionMethodsCount = 0
        )
        try:
            with open(path, 'wb') as f:
                f.write(stub)
            self._log(f"Created .pak stub: {os.path.basename(path)}")
        except Exception as e:
            self._log(f"WARNING: could not create .pak stub: {e}")
