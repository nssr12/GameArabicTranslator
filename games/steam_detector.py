"""
games/steam_detector.py — Steam library and game path detector (Windows)
"""
from __future__ import annotations
import os
import re
from typing import Optional, List

# game_id → {folder in steamapps/common, optional paks sub-path}
_KNOWN = {
    "Grounded2": {
        "folder":   "Grounded",
        "subpath":  "Augusta/Content/Paks",
    },
}


def _steam_root() -> Optional[str]:
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for sub in (
                r"SOFTWARE\Valve\Steam",
                r"SOFTWARE\WOW6432Node\Valve\Steam",
            ):
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        path, _ = winreg.QueryValueEx(k, "InstallPath")
                        if path and os.path.isdir(path):
                            return path
                except OSError:
                    pass
    except Exception:
        pass
    return None


def _steam_libraries(steam_root: str) -> List[str]:
    libs = [os.path.join(steam_root, "steamapps")]
    vdf = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
    if os.path.isfile(vdf):
        try:
            txt = open(vdf, encoding="utf-8").read()
            for m in re.finditer(r'"path"\s+"([^"]+)"', txt):
                p = m.group(1).replace("\\\\", "\\")
                candidate = os.path.join(p, "steamapps")
                if os.path.isdir(candidate) and candidate not in libs:
                    libs.append(candidate)
        except Exception:
            pass
    return libs


def find_game_path(game_id: str) -> Optional[str]:
    """
    Return the full paks/install path for a known game, or None if not found.
    Uses Steam registry + libraryfolders.vdf on Windows.
    """
    info = _KNOWN.get(game_id)
    if not info:
        return None

    root = _steam_root()
    if not root:
        return None

    folder  = info["folder"]
    subpath = info.get("subpath", "")

    for lib in _steam_libraries(root):
        game_dir = os.path.join(lib, "common", folder)
        if not os.path.isdir(game_dir):
            continue
        if subpath:
            full = os.path.join(game_dir, subpath)
            return full if os.path.isdir(full) else game_dir
        return game_dir

    return None


def is_known(game_id: str) -> bool:
    return game_id in _KNOWN
