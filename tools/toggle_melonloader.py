"""
toggle_melonloader.py - فعّل/عطّل MelonLoader في لعبة Unity Mono.

عندما يكون MelonLoader مُثبَّتاً (version.dll) في مجلد اللعبة، فإنه يتعارض مع
BepInEx (winhttp.dll). أحياناً يعمل البرنامجان معاً، لكن الأفضل تعطيل أحدهما.

الاستخدام:
    python tools/toggle_melonloader.py --game "Farthest Frontier" --disable
    python tools/toggle_melonloader.py --game "Farthest Frontier" --enable
    python tools/toggle_melonloader.py --game "Farthest Frontier" --status
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# الـ DLLs والمجلدات اللي MelonLoader يستخدمها
ML_FILES = ["version.dll"]
ML_DIRS  = ["MelonLoader"]


def load_game_path(game_name: str) -> Path | None:
    cfg_path = PROJECT_ROOT / "games" / "configs" / f"{game_name}.json"
    if not cfg_path.exists():
        print(f"[X] Config not found: {cfg_path}")
        return None
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[X] Failed to parse config: {e}")
        return None
    gp = cfg.get("game_path", "")
    if not gp:
        print(f"[X] game_path غير محدّد في {cfg_path.name}")
        return None
    p = Path(gp)
    if not p.exists():
        print(f"[X] Game path not found: {p}")
        return None
    return p


def get_status(game_dir: Path) -> dict[str, str]:
    """يُرجع حالة كل ملف/مجلد."""
    state = {}
    for f in ML_FILES:
        en = game_dir / f
        dis = game_dir / (f + ".disabled")
        if en.exists():
            state[f] = "enabled"
        elif dis.exists():
            state[f] = "disabled"
        else:
            state[f] = "missing"
    for d in ML_DIRS:
        en = game_dir / d
        dis = game_dir / (d + ".disabled")
        if en.is_dir():
            state[d] = "enabled"
        elif dis.is_dir():
            state[d] = "disabled"
        else:
            state[d] = "missing"
    return state


def set_state(game_dir: Path, target: str) -> tuple[bool, list[str]]:
    """target: 'enabled' or 'disabled'."""
    log: list[str] = []
    ok = True
    items = [(f, False) for f in ML_FILES] + [(d, True) for d in ML_DIRS]
    for name, is_dir in items:
        en = game_dir / name
        dis = game_dir / (name + ".disabled")
        kind = "مجلد" if is_dir else "ملف"
        try:
            if target == "disabled":
                if (en.is_dir() if is_dir else en.is_file()):
                    en.rename(dis)
                    log.append(f"  [OK] {kind} {name}  → .disabled")
                elif (dis.is_dir() if is_dir else dis.is_file()):
                    log.append(f"  [  ] {kind} {name}  معطّل مسبقاً")
                else:
                    log.append(f"  [!]  {kind} {name}  مفقود — تجاوز")
            elif target == "enabled":
                if (dis.is_dir() if is_dir else dis.is_file()):
                    dis.rename(en)
                    log.append(f"  [OK] {kind} {name}  → enabled")
                elif (en.is_dir() if is_dir else en.is_file()):
                    log.append(f"  [  ] {kind} {name}  مفعّل مسبقاً")
                else:
                    log.append(f"  [!]  {kind} {name}  مفقود — تجاوز")
        except Exception as e:
            log.append(f"  [X]  {kind} {name}  فشل: {e}")
            ok = False
    return ok, log


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", required=True, help="Game name (مثل: 'Farthest Frontier')")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--enable",  action="store_true", help="فعّل MelonLoader")
    g.add_argument("--disable", action="store_true", help="عطّل MelonLoader (قبل تثبيت BepInEx)")
    g.add_argument("--status",  action="store_true", help="عرض حالة الملفات")
    args = ap.parse_args()

    game_dir = load_game_path(args.game)
    if not game_dir:
        return 1

    print(f"[*] Game:      {args.game}")
    print(f"[*] Game dir:  {game_dir}")
    print()

    if args.status:
        state = get_status(game_dir)
        print("MelonLoader status:")
        for name, s in state.items():
            icon = {"enabled": "✓", "disabled": "○", "missing": "✗"}[s]
            print(f"  {icon}  {name:25s}  {s}")
        if all(v == "enabled" for v in state.values()):
            print("\n[OK] MelonLoader مفعّل بالكامل.")
        elif all(v == "disabled" for v in state.values()):
            print("\n[OK] MelonLoader معطّل — جاهز لتثبيت BepInEx.")
        elif all(v == "missing" for v in state.values()):
            print("\n[i] لا يوجد MelonLoader في هذه اللعبة.")
        else:
            print("\n[!] حالة مختلطة — استخدم --enable أو --disable لتوحيدها.")
        return 0

    target = "enabled" if args.enable else "disabled"
    ok, log = set_state(game_dir, target)
    for line in log:
        print(line)
    print()
    if target == "disabled":
        print("[OK] MelonLoader معطّل. يمكنك الآن تثبيت BepInEx من التطبيق.")
    else:
        print("[OK] MelonLoader مفعّل.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
