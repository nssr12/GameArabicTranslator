"""
toggle_unreal_hook.py - فعّل/عطّل مود الترجمة بإعادة تسمية الـ DLLs.

عند تشغيل اللعبة الجماعي، Epic Online Services (EAS) قد يكشف الحقن أو يفشل في
الحصول على auth token بسبب الـ DLL hooks. الحل المؤقت: إعادة تسمية الـ DLLs
(<dll>.disabled) كي اللعبة تتجاهلها.

الاستخدام:
    python tools/toggle_unreal_hook.py --game Palworld --disable   # للأونلاين
    python tools/toggle_unreal_hook.py --game Palworld --enable    # للأوفلاين مع ترجمة
    python tools/toggle_unreal_hook.py --game Palworld --status    # عرض الحالة
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# نفس قائمة inject_unreal_hook.py
HOOK_DLLS = ["cppfs.dll", "dxgi.dll", "ZXSOSZXNMod.dll", "ZXSOSZXMod.dll"]


def load_game_dir(game_name: str) -> Path | None:
    cfg_path = PROJECT_ROOT / "games" / "configs" / f"{game_name}.json"
    if not cfg_path.exists():
        print(f"[X] Config not found: {cfg_path}")
        return None
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[X] Failed to parse config: {e}")
        return None
    win64 = cfg.get("unreal_hook", {}).get("win64_dir")
    if not win64:
        print(f"[X] unreal_hook.win64_dir غير محدّد في {cfg_path.name}")
        return None
    p = Path(win64)
    if not p.exists():
        print(f"[X] Win64 dir not found: {p}")
        return None
    return p


def get_status(win64: Path) -> dict[str, str]:
    """Returns {dll_name: 'enabled' | 'disabled' | 'missing'}."""
    state = {}
    for dll in HOOK_DLLS:
        enabled = win64 / dll
        disabled = win64 / (dll + ".disabled")
        if enabled.exists():
            state[dll] = "enabled"
        elif disabled.exists():
            state[dll] = "disabled"
        else:
            state[dll] = "missing"
    return state


def set_state(win64: Path, target: str) -> tuple[bool, list[str]]:
    """target: 'enabled' or 'disabled'."""
    log: list[str] = []
    ok = True
    for dll in HOOK_DLLS:
        enabled = win64 / dll
        disabled = win64 / (dll + ".disabled")
        try:
            if target == "disabled":
                if enabled.exists():
                    enabled.rename(disabled)
                    log.append(f"  [OK] {dll}  → .disabled")
                elif disabled.exists():
                    log.append(f"  [  ] {dll}  معطّل مسبقاً")
                else:
                    log.append(f"  [!]  {dll}  مفقود — تجاوز")
            elif target == "enabled":
                if disabled.exists():
                    disabled.rename(enabled)
                    log.append(f"  [OK] {dll}  → enabled")
                elif enabled.exists():
                    log.append(f"  [  ] {dll}  مفعّل مسبقاً")
                else:
                    log.append(f"  [!]  {dll}  مفقود — تجاوز")
        except Exception as e:
            log.append(f"  [X]  {dll}  فشل: {e}")
            ok = False
    return ok, log


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", required=True, help="Game name (e.g., Palworld)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--enable",  action="store_true", help="فعّل المود (للأوفلاين مع ترجمة)")
    g.add_argument("--disable", action="store_true", help="عطّل المود (للأونلاين)")
    g.add_argument("--status",  action="store_true", help="عرض حالة كل DLL")
    args = ap.parse_args()

    win64 = load_game_dir(args.game)
    if not win64:
        return 1

    print(f"[*] Game:  {args.game}")
    print(f"[*] Win64: {win64}")
    print()

    if args.status:
        state = get_status(win64)
        print("DLL Status:")
        for dll, s in state.items():
            icon = {"enabled": "✓", "disabled": "○", "missing": "✗"}[s]
            print(f"  {icon}  {dll:25s}  {s}")
        # خلاصة
        if all(v == "enabled" for v in state.values()):
            print("\n[OK] المود مفعّل بالكامل — جاهز للأوفلاين مع ترجمة.")
        elif all(v == "disabled" for v in state.values()):
            print("\n[OK] المود معطّل بالكامل — جاهز للأونلاين.")
        elif any(v == "missing" for v in state.values()):
            print("\n[!] بعض الـ DLLs مفقودة — ثبّت المود من التطبيق.")
        else:
            print("\n[!] الحالة مختلطة — استخدم --enable أو --disable لتوحيدها.")
        return 0

    target = "enabled" if args.enable else "disabled"
    ok, log = set_state(win64, target)
    for line in log:
        print(line)
    print()
    if target == "disabled":
        print("[OK] المود معطّل. شغّل اللعبة من Steam مباشرة — Online سيعمل.")
    else:
        print("[OK] المود مفعّل. استخدم الـ steam_inject_wrap أو launch_unreal_game.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
