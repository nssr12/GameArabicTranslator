import os
import json
import shutil
from typing import List, Tuple, Optional

_MODS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mods")
)


class TranslationPackage:
    """
    Manages per-game translation packages stored in mods/<game_name>/.

    Folder layout:
        mods/<game>/
            package.json          — file registry + wizard config
            ready/                — final .pak/.ucas/.utoc ready for install
            for_cache/
                Paks_legacy/      — extracted .uasset files (for cache re-sync)
    """

    # ── Paths ─────────────────────────────────────────────────────────

    def get_mod_dir(self, game_name: str) -> str:
        return os.path.join(_MODS_DIR, game_name)

    def get_ready_dir(self, game_name: str) -> str:
        return os.path.join(self.get_mod_dir(game_name), "ready")

    def get_for_cache_dir(self, game_name: str) -> str:
        return os.path.join(self.get_mod_dir(game_name), "for_cache")

    def ensure_dirs(self, game_name: str):
        os.makedirs(self.get_ready_dir(game_name), exist_ok=True)
        os.makedirs(self.get_for_cache_dir(game_name), exist_ok=True)

    def _config_path(self, game_name: str) -> str:
        return os.path.join(self.get_mod_dir(game_name), "package.json")

    # ── Config ────────────────────────────────────────────────────────

    def get_config(self, game_name: str) -> dict:
        path = self._config_path(game_name)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"files": [], "wizard": {}}

    def _save_config(self, game_name: str, config: dict):
        mod_dir = self.get_mod_dir(game_name)
        os.makedirs(mod_dir, exist_ok=True)
        with open(self._config_path(game_name), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def save_wizard_config(self, game_name: str, wizard: dict):
        """Persist IoStore wizard settings (versions, paths, etc.)."""
        cfg = self.get_config(game_name)
        cfg.setdefault("wizard", {}).update(wizard)
        self._save_config(game_name, cfg)

    def get_wizard_config(self, game_name: str) -> dict:
        return self.get_config(game_name).get("wizard", {})

    # ── File management ───────────────────────────────────────────────

    def _file_dir(self, game_name: str) -> str:
        """Files are stored in ready/ subfolder."""
        return self.get_ready_dir(game_name)

    def add_file(self, game_name: str,
                 mod_src: str,
                 orig_src: str,
                 game_target: str) -> Tuple[bool, str]:
        """
        Copy translated file (and optional .orig) into ready/, then register.
        game_target: relative path inside the game's installation directory.
        """
        file_dir = self._file_dir(game_name)
        os.makedirs(file_dir, exist_ok=True)

        fname = os.path.basename(mod_src)
        dest_mod = os.path.join(file_dir, fname)

        if not os.path.exists(mod_src):
            return False, f"Translated file not found: {mod_src}"

        shutil.copy2(mod_src, dest_mod)

        has_orig = False
        if orig_src and os.path.exists(orig_src):
            dest_orig = os.path.join(file_dir, fname + ".orig")
            shutil.copy2(orig_src, dest_orig)
            has_orig = True

        cfg = self.get_config(game_name)
        cfg["files"] = [e for e in cfg["files"] if e.get("game_target") != game_target]
        cfg["files"].append({
            "name": fname,
            "game_target": game_target,
            "has_orig": has_orig,
        })
        self._save_config(game_name, cfg)
        note = " + .orig" if has_orig else " (no .orig)"
        return True, f"Added {fname}{note}"

    def remove_file(self, game_name: str, game_target: str):
        cfg = self.get_config(game_name)
        cfg["files"] = [e for e in cfg["files"] if e.get("game_target") != game_target]
        self._save_config(game_name, cfg)

    # ── for_cache workflow ────────────────────────────────────────────

    def copy_to_for_cache(self, game_name: str,
                          legacy_folder: str) -> Tuple[bool, List[str]]:
        """
        Copy Paks_legacy folder into for_cache/.
        Existing destination is removed first.
        """
        dst = os.path.join(self.get_for_cache_dir(game_name),
                           os.path.basename(legacy_folder))
        log: List[str] = []
        try:
            os.makedirs(self.get_for_cache_dir(game_name), exist_ok=True)
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(legacy_folder, dst)
            log.append(f"✓ Copied {os.path.basename(legacy_folder)} → for_cache/")
            log.append(f"  Path: {dst}")
            return True, log
        except Exception as e:
            log.append(f"ERROR: {e}")
            return False, log

    def save_paks_to_ready(self, game_name: str,
                           pak_base: str,
                           game_target_dir: str = "") -> Tuple[bool, List[str]]:
        """
        Copy _P.pak / _P.ucas / _P.utoc from pak_base location into ready/.
        Registers each file in package.json using game_target_dir as prefix.
        pak_base: full path without extension (e.g. D:/Paks/Paks_translated)
        game_target_dir: relative dir inside game root (e.g. "Grounded2/Content/Paks")
        """
        ready_dir = self.get_ready_dir(game_name)
        os.makedirs(ready_dir, exist_ok=True)
        log: List[str] = []
        ok = True
        copied = 0
        base = pak_base

        for ext in (".pak", ".ucas", ".utoc"):
            src = base + ext
            if not os.path.exists(src):
                log.append(f"  (skip — not found: {os.path.basename(src)})")
                continue
            fname = os.path.basename(src)
            dst = os.path.join(ready_dir, fname)
            try:
                shutil.copy2(src, dst)
                log.append(f"✓ {fname} → ready/")
                copied += 1
                # register in package.json
                if game_target_dir:
                    gt = game_target_dir.rstrip("/\\") + "/" + fname
                    cfg = self.get_config(game_name)
                    cfg["files"] = [e for e in cfg["files"] if e.get("name") != fname]
                    cfg["files"].append({
                        "name": fname,
                        "game_target": gt,
                        "has_orig": False,
                    })
                    self._save_config(game_name, cfg)
            except Exception as e:
                log.append(f"ERROR copying {fname}: {e}")
                ok = False

        if copied == 0:
            log.append("ERROR: no files found to copy — run Step 5 first")
            ok = False

        return ok, log

    def get_legacy_in_cache(self, game_name: str) -> Optional[str]:
        """Return path to the content folder inside for_cache, if it exists."""
        fc = self.get_for_cache_dir(game_name)
        if not os.path.isdir(fc):
            return None
        # prefer a folder with "legacy" in the name, fall back to any subfolder
        fallback = None
        for name in sorted(os.listdir(fc)):
            candidate = os.path.join(fc, name)
            if not os.path.isdir(candidate):
                continue
            if "legacy" in name.lower():
                return candidate
            if fallback is None:
                fallback = candidate
        return fallback

    # ── Install / Uninstall ───────────────────────────────────────────

    def install(self, game_name: str, game_path: str) -> Tuple[bool, List[str]]:
        cfg = self.get_config(game_name)
        file_dir = self._file_dir(game_name)
        log: List[str] = []
        ok = True

        for entry in cfg["files"]:
            src = os.path.join(file_dir, entry["name"])
            # backward compat: also check root mod_dir
            if not os.path.exists(src):
                src = os.path.join(self.get_mod_dir(game_name), entry["name"])
            dst = os.path.join(game_path, entry["game_target"])

            if not os.path.exists(src):
                log.append(f"ERROR: missing — {entry['name']}")
                ok = False
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                log.append(f"✓ {entry['name']}  →  {entry['game_target']}")
            except Exception as e:
                log.append(f"ERROR: {e}")
                ok = False

        return ok, log

    def uninstall(self, game_name: str, game_path: str) -> Tuple[bool, List[str]]:
        """Remove mod files from the game directory (delete, not restore)."""
        cfg = self.get_config(game_name)
        log: List[str] = []
        ok = True

        for entry in cfg["files"]:
            dst = os.path.join(game_path, entry["game_target"])
            if not os.path.exists(dst):
                log.append(f"SKIP: not in game dir — {entry['name']}")
                continue
            try:
                os.remove(dst)
                log.append(f"🗑 Removed: {entry['name']}")
            except Exception as e:
                log.append(f"ERROR removing {entry['name']}: {e}")
                ok = False

        return ok, log

    # ── Status ────────────────────────────────────────────────────────

    def get_status(self, game_name: str, game_path: str) -> Optional[bool]:
        """True = installed, False = not installed, None = unknown."""
        if not game_path:
            return None
        cfg = self.get_config(game_name)
        if not cfg["files"]:
            return None
        file_dir = self._file_dir(game_name)

        installed = 0
        missing   = 0
        for entry in cfg["files"]:
            dst = os.path.join(game_path, entry["game_target"])
            mod_f = os.path.join(file_dir, entry["name"])
            if not os.path.exists(mod_f):
                mod_f = os.path.join(self.get_mod_dir(game_name), entry["name"])
            if os.path.exists(dst) and os.path.exists(mod_f):
                if os.path.getsize(dst) == os.path.getsize(mod_f):
                    installed += 1
                else:
                    missing += 1
            else:
                missing += 1

        if installed > 0 and missing == 0:
            return True
        if installed == 0 and missing > 0:
            return False
        return None

    def has_files(self, game_name: str) -> bool:
        return bool(self.get_config(game_name)["files"])

    def list_games(self) -> List[str]:
        if not os.path.exists(_MODS_DIR):
            return []
        return [
            d for d in sorted(os.listdir(_MODS_DIR))
            if os.path.exists(os.path.join(_MODS_DIR, d, "package.json"))
        ]
