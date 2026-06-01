"""
games/unreal_hook_mod.py - Unreal Engine Hook mod manager.

UnrealHook = generic injection-based UE5 text translation mod.
Uses dxgi.dll hijack + LoadLibrary CreateRemoteThread injection.
Works with any UE5 game that has compatible text-hook binaries installed.
Used for games like Manor Lords that can't be hooked via standard methods.

Architecture:
    Manor Lords (game) → injected hook DLLs (via suspended-launch + LoadLibrary)
        → writes Translate/<hash>.subtitle.en.txt
    unreal_hook_watcher.py → reads .en.txt → sends to our proxy → writes .subtitle.txt
    Hook DLL reads .subtitle.txt → displays Arabic in-game

This module manages:
    - Install/uninstall hook DLLs to game's Win64 folder
    - Check installation status
    - Provide info for GUI rendering
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List

# Files required for the hook to work (binary names are fixed in the DLLs)
UNREAL_HOOK_REQUIRED_FILES = [
    "cppfs.dll",
    "dxgi.dll",
    "ManagedWinapi.dll",
    "ZXSOSZXFont.ttf",
    "ZXSOSZXFormat.ini",
    "ZXSOSZXHandle.ini",
    "ZXSOSZXLog.ini",
    "ZXSOSZXMod.dll",
    "ZXSOSZXNMod.dll",
    "ZXSOSZXSubtitle.exe",
    "ZXSOSZXSubtitle.exe.config",
    "ZXSOSZXSubtitleReadUni.ini",
    "ZXSOSZXSubtitleUseUni.ini",
    "GameID.ini",
    "GameName.ini",
]

# Source folder containing hook DLL template
PROJECT_ROOT = Path(__file__).resolve().parent.parent
UNREAL_HOOK_TEMPLATE_DIR = PROJECT_ROOT / "tmp" / "fltah_manorlords" / "ManorLords" / "Binaries" / "Win64"


class UnrealHookMod:
    """Manages Unreal Engine text-hook installation for a game."""

    def get_win64_dir(self, cfg: dict) -> Path | None:
        """Returns the game's Win64 folder where hook DLLs go."""
        hook_cfg = cfg.get("unreal_hook", {})
        w64 = hook_cfg.get("win64_dir")
        if w64:
            return Path(w64)
        # Fallback: try common patterns
        game_path = cfg.get("game_path", "")
        if game_path:
            game_name = cfg.get("name", "")
            # Try <game_path>/<game_name>/Binaries/Win64
            candidates = [
                Path(game_path) / game_name / "Binaries" / "Win64",
                Path(game_path) / game_name.replace(" ", "") / "Binaries" / "Win64",
                Path(game_path) / "Binaries" / "Win64",
            ]
            for c in candidates:
                if c.exists():
                    return c
        return None

    def get_translate_dir(self, cfg: dict) -> Path | None:
        """Returns the Translate/ folder path."""
        hook_cfg = cfg.get("unreal_hook", {})
        td = hook_cfg.get("translate_dir")
        if td:
            return Path(td)
        w64 = self.get_win64_dir(cfg)
        if w64:
            return w64 / "Translate"
        return None

    def is_installed(self, cfg: dict) -> bool:
        """Check if all required hook files are present."""
        w64 = self.get_win64_dir(cfg)
        if not w64 or not w64.exists():
            return False
        for f in UNREAL_HOOK_REQUIRED_FILES:
            if not (w64 / f).exists():
                return False
        return True

    def get_status(self, cfg: dict) -> Dict:
        """Detailed status for GUI."""
        w64 = self.get_win64_dir(cfg)
        translate_dir = self.get_translate_dir(cfg)
        status = {
            "installed": False,
            "win64_dir": str(w64) if w64 else "",
            "win64_exists": w64.exists() if w64 else False,
            "translate_dir": str(translate_dir) if translate_dir else "",
            "translate_dir_exists": translate_dir.exists() if translate_dir else False,
            "missing_files": [],
            "captured_count": 0,
            "translated_count": 0,
            "template_available": UNREAL_HOOK_TEMPLATE_DIR.exists(),
        }
        if w64 and w64.exists():
            for f in UNREAL_HOOK_REQUIRED_FILES:
                if not (w64 / f).exists():
                    status["missing_files"].append(f)
            status["installed"] = len(status["missing_files"]) == 0
        if translate_dir and translate_dir.exists():
            try:
                en_files = list(translate_dir.glob("*.subtitle.en.txt"))
                ar_files = list(translate_dir.glob("*.subtitle.txt"))
                # exclude .en.txt from ar_files count
                ar_only = [f for f in ar_files if not f.name.endswith(".en.txt")]
                status["captured_count"] = len(en_files)
                status["translated_count"] = len(ar_only)
            except Exception:
                pass
        return status

    def install(self, cfg: dict) -> tuple[bool, str]:
        """Copy hook DLLs from template to game folder."""
        if not UNREAL_HOOK_TEMPLATE_DIR.exists():
            return False, f"Hook template not found at: {UNREAL_HOOK_TEMPLATE_DIR}"

        w64 = self.get_win64_dir(cfg)
        if not w64:
            return False, "Could not determine game's Win64 folder. Check 'unreal_hook.win64_dir' in config."
        if not w64.exists():
            return False, f"Game's Win64 folder doesn't exist: {w64}"

        # Copy each required file
        copied = []
        errors = []
        for fname in UNREAL_HOOK_REQUIRED_FILES:
            src = UNREAL_HOOK_TEMPLATE_DIR / fname
            if not src.exists():
                errors.append(f"missing in template: {fname}")
                continue
            dst = w64 / fname
            try:
                shutil.copy2(src, dst)
                copied.append(fname)
            except Exception as e:
                errors.append(f"{fname}: {e}")

        # Create Translate/ folder
        translate_dir = w64 / "Translate"
        translate_dir.mkdir(exist_ok=True)

        if errors:
            return False, f"Installed {len(copied)} files but had errors: {'; '.join(errors)}"
        return True, f"Hook installed successfully ({len(copied)} files)"

    def uninstall(self, cfg: dict) -> tuple[bool, str]:
        """Remove hook DLLs from game folder. Keeps Translate/ folder."""
        w64 = self.get_win64_dir(cfg)
        if not w64 or not w64.exists():
            return False, "Game folder not found"

        removed = []
        for fname in UNREAL_HOOK_REQUIRED_FILES:
            f = w64 / fname
            if f.exists():
                try:
                    f.unlink()
                    removed.append(fname)
                except Exception:
                    pass
        return True, f"Hook uninstalled ({len(removed)} files removed). Translate/ folder kept."

    def clear_translations(self, cfg: dict) -> tuple[bool, str]:
        """Delete all .subtitle.txt files (translations). Keeps .en.txt (captured originals)."""
        translate_dir = self.get_translate_dir(cfg)
        if not translate_dir or not translate_dir.exists():
            return False, "Translate folder doesn't exist"
        removed = 0
        for f in translate_dir.glob("*.subtitle.txt"):
            # Don't delete .en.txt files
            if f.name.endswith(".en.txt"):
                continue
            try:
                f.unlink()
                removed += 1
            except Exception:
                pass
        return True, f"Removed {removed} translation files"

    def clear_captured(self, cfg: dict) -> tuple[bool, str]:
        """Delete all .en.txt files (captured texts). Forces hook to re-capture."""
        translate_dir = self.get_translate_dir(cfg)
        if not translate_dir or not translate_dir.exists():
            return False, "Translate folder doesn't exist"
        removed = 0
        for f in translate_dir.glob("*.subtitle.en.txt"):
            try:
                f.unlink()
                removed += 1
            except Exception:
                pass
        return True, f"Removed {removed} captured files"

    def export_translate_folder(
        self,
        cfg: dict,
        cache,
        game_name: str,
        model_filter: str = "",
        apply_reshape: bool = True,
    ) -> tuple[bool, str, dict]:
        """Regenerate all .subtitle.txt files from cache.

        For each .subtitle.en.txt file, look up its translation in cache and
        write the corresponding .subtitle.txt with the chosen translation.

        Args:
            cfg: game config
            cache: TranslationCache instance
            game_name: game name (cache key)
            model_filter:
                "" (empty)         → use hierarchical merge (best of all models)
                "<model_name>"     → only use translations from this model
            apply_reshape: apply arabic_reshaper for proper Arabic shaping

        Returns:
            (ok, message, stats_dict)
        """
        translate_dir = self.get_translate_dir(cfg)
        if not translate_dir or not translate_dir.exists():
            return False, "Translate folder not found", {}

        # arabic reshaper (optional)
        reshape_fn = lambda t: t
        if apply_reshape:
            try:
                import arabic_reshaper
                reshape_fn = arabic_reshaper.reshape
            except ImportError:
                pass

        # Build lookup: text → translation (using filter)
        try:
            translations: dict[str, str] = {}
            for en_text, ar_text in cache.iter_best_translations(game_name, model_filter):
                if en_text and ar_text:
                    translations[en_text] = ar_text
        except Exception as e:
            return False, f"Failed to read cache: {e}", {}

        if not translations:
            return False, "No translations found in cache for this game", {}

        # كاشف الترجمات المعطوبة (تاقات مكسورة) — نتخطّاها ونحذف .subtitle.txt القديم
        # حتى يُعيد الـ watcher ترجمتها عند الإطلاق التالي للعبة
        from engine.tag_health import is_broken_translation

        # نُعيد بناء فهرس الترجمات بمفتاح مُطبَّع (نفس normalize الذي يفعله البروكسي)
        # حتى يتطابق مع كيفية تخزينه في الكاش.
        # البروكسي يفعل: " ".join(text.replace("\\n", " ").replace("\n", " ").split())
        def _normalize_key(s: str) -> str:
            if not s:
                return s
            return " ".join(s.replace("\\n", " ").replace("\n", " ").split())

        normalized: dict[str, str] = {}
        for en_text, ar_text in translations.items():
            normalized[_normalize_key(en_text)] = ar_text

        # Iterate all .en.txt files and write matching .subtitle.txt
        stats = {
            "total_en": 0, "written": 0, "missing": 0, "errors": 0,
            "broken_skipped": 0,
        }
        for en_file in translate_dir.glob("*.subtitle.en.txt"):
            stats["total_en"] += 1
            try:
                # Read source text
                raw = en_file.read_bytes()
                if raw.startswith(b"\xff\xfe"):
                    raw = raw[2:]
                src_text = raw.decode("utf-16-le", errors="replace")
                src_text = src_text.rstrip("\x00").rstrip("\n").rstrip("\r")

                base = en_file.name.replace(".subtitle.en.txt", "")
                out_file = translate_dir / f"{base}.subtitle.txt"

                # Look up translation (بمفتاح مُطبَّع — يطابق ما يخزّنه البروكسي)
                lookup_key = _normalize_key(src_text)
                ar_text = translations.get(src_text) or normalized.get(lookup_key)
                if ar_text is None:
                    stats["missing"] += 1
                    continue

                # تحقّق من سلامة التاقات — لو الترجمة معطوبة تخطّاها
                # وامسح .subtitle.txt القديم حتى يُعيد الـ watcher الترجمة
                if is_broken_translation(src_text, ar_text):
                    stats["broken_skipped"] += 1
                    if out_file.exists():
                        try:
                            out_file.unlink()
                        except Exception:
                            pass
                    continue

                # Apply reshape
                if apply_reshape:
                    try:
                        ar_text = reshape_fn(ar_text)
                    except Exception:
                        pass

                # Write .subtitle.txt (UTF-16 LE + BOM)
                data = b"\xff\xfe" + ar_text.encode("utf-16-le")
                out_file.write_bytes(data)
                stats["written"] += 1
            except Exception:
                stats["errors"] += 1

        # Build human-readable message
        filter_desc = f"مودل: {model_filter}" if model_filter else "دمج هرمي (best of all)"
        msg_lines = [
            f"تم تحديث مجلد Translate ({filter_desc})",
            "",
            f"  • نصوص ملتقطة:       {stats['total_en']:,}",
            f"  • تم تحديثها:         {stats['written']:,}",
            f"  • بدون ترجمة:        {stats['missing']:,}",
        ]
        if stats["broken_skipped"]:
            msg_lines.append(
                f"  • معطوبة (تخطّى):    {stats['broken_skipped']:,}  ← ستُعاد ترجمتها"
            )
        if stats["errors"]:
            msg_lines.append(f"  • أخطاء:              {stats['errors']:,}")
        if stats["broken_skipped"]:
            msg_lines.append("")
            msg_lines.append(
                "ℹ النصوص المعطوبة في الكاش لم تُكتب — حُذف ملف .subtitle.txt الخاص بها "
                "حتى يُعيد الـ watcher ترجمتها عند إطلاق اللعبة التالي."
            )
        return True, "\n".join(msg_lines), stats
