"""
games/steam_detector.py — كشف مسار تثبيت ألعاب Steam تلقائياً (Windows).

الكشف عبر **appid** (الأدق): يقرأ `appmanifest_<appid>.acf` في كل مكتبات Steam
→ `installdir` → `steamapps/common/<installdir>`. ثم يُضاف `steam_subpath` من
config اللعبة (المسار الفرعي داخل مجلّد اللعبة، مثل Windrose = R5/Content/Paks).

الغرض: المستخدم على جهاز آخر يثبّت Steam في مكان مختلف → التطبيق يصحّح
`game_path` تلقائياً بدل الاعتماد على مسار المطوّر الثابت.
"""
from __future__ import annotations
import os
import re
from typing import Optional, List

# game_id → Steam appid (احتياطي إن لم يُضبط steam_appid في config)
_APPIDS = {
    "Grounded2":         "2661300",
    "Windrose":          "3041230",
    "Palworld":          "1623730",
    "Manor Lords":       "1363080",
    "Farthest Frontier": "1044720",
    "Myth of Empires":   "1371580",
    "Risk of Rain 2":    "632360",
    "Foundation":        "690830",
    "Flotsam":           "821250",
}


def _steam_root() -> Optional[str]:
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for sub in (r"SOFTWARE\Valve\Steam", r"SOFTWARE\WOW6432Node\Valve\Steam"):
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        path, _ = winreg.QueryValueEx(k, "InstallPath")
                        if path and os.path.isdir(path):
                            return path
                except OSError:
                    pass
    except Exception:
        pass
    # احتياطي: مسارات شائعة
    for p in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        if os.path.isdir(p):
            return p
    return None


def _steam_libraries(steam_root: str) -> List[str]:
    libs = [os.path.join(steam_root, "steamapps")]
    vdf = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
    if os.path.isfile(vdf):
        try:
            txt = open(vdf, encoding="utf-8", errors="replace").read()
            for m in re.finditer(r'"path"\s+"([^"]+)"', txt):
                p = m.group(1).replace("\\\\", "\\")
                candidate = os.path.join(p, "steamapps")
                if os.path.isdir(candidate) and candidate not in libs:
                    libs.append(candidate)
        except Exception:
            pass
    return libs


def find_install_dir(appid: str) -> Optional[str]:
    """يُرجع مجلّد تثبيت اللعبة (steamapps/common/<installdir>) عبر appid، أو None."""
    if not appid:
        return None
    root = _steam_root()
    if not root:
        return None
    for lib in _steam_libraries(root):
        acf = os.path.join(lib, f"appmanifest_{appid}.acf")
        if not os.path.isfile(acf):
            continue
        try:
            txt = open(acf, encoding="utf-8", errors="replace").read()
            m = re.search(r'"installdir"\s+"([^"]+)"', txt)
            if m:
                p = os.path.join(lib, "common", m.group(1))
                if os.path.isdir(p):
                    return p
        except Exception:
            pass
    return None


def appid_for(game_id: str, cfg: dict | None = None) -> str:
    if cfg and cfg.get("steam_appid"):
        return str(cfg["steam_appid"])
    return _APPIDS.get(game_id, "")


def resolve_game_path(game_id: str, cfg: dict) -> Optional[str]:
    """يُرجع مسار لعبة صالحاً:
      - المسار المضبوط في config إن كان موجوداً فعلاً.
      - وإلا يكتشفه تلقائياً عبر appid + steam_subpath.
    يُرجع None إن تعذّر."""
    cfg = cfg or {}
    cur = (cfg.get("game_path", "") or "").strip()
    if cur and os.path.isdir(cur):
        return cur
    appid = appid_for(game_id, cfg)
    base = find_install_dir(appid)
    if not base:
        return None
    sub = (cfg.get("steam_subpath", "") or "").strip().strip("/\\")
    if sub:
        full = os.path.join(base, *sub.split("/"))
        if os.path.isdir(full):
            return full
    return base if os.path.isdir(base) else None


# توافق رجعي مع الاستدعاء القديم في add_game.py
def find_game_path(game_id: str) -> Optional[str]:
    return resolve_game_path(game_id, {"steam_appid": _APPIDS.get(game_id, "")})


def is_known(game_id: str) -> bool:
    return game_id in _APPIDS


__all__ = ["find_install_dir", "resolve_game_path", "find_game_path",
           "appid_for", "is_known"]
