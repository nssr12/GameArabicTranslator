"""
steam_inject_wrap.py - Steam Launch Options wrapper for UE5 game injection.

Lets you launch the game directly from Steam (or its shortcut) while still
getting the translation hooks injected automatically.

══════ التثبيت في Steam ══════

1. Right-click اللعبة في Steam → Properties → Launch Options
2. ضع هذا السطر (عدّل المسار حسب نظامك):

   "C:\\Python314\\python.exe" "D:\\GameArabicTranslator\\tools\\steam_inject_wrap.py" %command%

3. اضغط OK وشغّل اللعبة عادياً من Steam ← الترجمة ستعمل تلقائياً.

══════ كيف يعمل ══════

عند تشغيل Steam للعبة:
1. Steam يستبدل %command% بأمر تشغيل اللعبة (مع كل args)
2. السكربت يستلم أمر التشغيل كاملاً عبر argv
3. يكتشف أي لعبة من مسار الـ exe → يحمّل config المطابق
4. يطلق اللعبة SUSPENDED → يحقن DLLs → يستأنف
5. Steam يتتبّع الـ process (لـ overlay، playtime، إلخ)

══════ ملاحظات مهمة ══════

• الـ proxy + watcher لازم تكون شغّالة لو في نصوص جديدة (DLC، شاشات جديدة).
• اللعب الجماعي قد لا يعمل بسبب EAS auth — استخدم --no-inject أو
  عطّل المود مؤقتاً عبر التطبيق قبل لعب الأونلاين.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
from ctypes import wintypes
from pathlib import Path

# Reuse logic from launch_unreal_game
sys.path.insert(0, str(Path(__file__).resolve().parent))
from inject_unreal_hook import inject_dll, INJECTION_ORDER
from launch_unreal_game import (
    STARTUPINFOW, PROCESS_INFORMATION, kernel32, CREATE_SUSPENDED,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def find_matching_config(game_exe: Path) -> tuple[str, dict] | None:
    """يبحث عن config مطابق لمسار الـ exe من Steam.

    يقارن:
      - cfg["game_exe_inject"]
      - cfg["unreal_hook"]["game_exe_inject"]
    """
    configs_dir = PROJECT_ROOT / "games" / "configs"
    target = game_exe.resolve()
    target_name = game_exe.name.lower()
    for cfg_file in sorted(configs_dir.glob("*.json")):
        try:
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        # 1) مطابقة كاملة بالمسار
        for key_path in (
            cfg.get("game_exe_inject"),
            cfg.get("unreal_hook", {}).get("game_exe_inject"),
        ):
            if key_path:
                try:
                    if Path(key_path).resolve() == target:
                        return cfg_file.stem, cfg
                except Exception:
                    pass
        # 2) مطابقة باسم process_name (fallback)
        proc = (cfg.get("process_name") or "").lower()
        if proc and proc == target_name:
            return cfg_file.stem, cfg
    return None


def launch_with_injection(game_exe: Path, dll_dir: Path,
                          extra_args: list[str]) -> int:
    """يطلق اللعبة SUSPENDED → يحقن DLLs → يستأنف."""
    print(f"[*] Game exe: {game_exe}")
    print(f"[*] DLL dir : {dll_dir}")

    missing = [dll for dll in INJECTION_ORDER if not (dll_dir / dll).exists()]
    if missing:
        print(f"[!] Missing hook DLLs: {missing}")
        print("    Install via app GUI → Game page → Unreal Hook → Install")
        print("    Launching game WITHOUT injection (no translation).")
        # شغّل عادياً (بدون حقن) كي اللعبة تعمل على الأقل
        import subprocess
        subprocess.run([str(game_exe)] + extra_args)
        return 0

    # ابنِ سطر الأوامر (exe + أي args من Steam)
    parts = [f'"{game_exe}"'] + [
        f'"{a}"' if " " in a else a for a in extra_args
    ]
    cmdline = " ".join(parts)

    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    cmd_buf = ctypes.create_unicode_buffer(cmdline)

    ok = kernel32.CreateProcessW(
        str(game_exe),
        cmd_buf,
        None, None,
        False,
        CREATE_SUSPENDED,
        None,
        str(game_exe.parent),
        ctypes.byref(si),
        ctypes.byref(pi),
    )
    if not ok:
        err = ctypes.get_last_error()
        print(f"[X] CreateProcess failed: {err} = {ctypes.FormatError(err)}")
        return 3

    pid = pi.dwProcessId
    print(f"[OK] Game launched SUSPENDED  PID={pid}")

    # احقن
    print("[*] Injecting hook DLLs...")
    for dll in INJECTION_ORDER:
        full_path = str(dll_dir / dll)
        try:
            ok_inj, msg = inject_dll(pid, full_path)
            tag = "[OK]" if ok_inj else "[X] "
            print(f"  {tag} {dll}  {msg}")
        except Exception as e:
            print(f"  [X]  {dll}  exception: {e}")

    # استأنف
    prev = kernel32.ResumeThread(pi.hThread)
    if prev == 0xFFFFFFFF:
        print(f"[X] ResumeThread failed: {ctypes.get_last_error()}")
        return 4

    print("[OK] Game resumed with hooks active.")
    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)
    return 0


def launch_passthrough(game_exe: Path, extra_args: list[str]) -> int:
    """شغّل اللعبة عادياً (بدون حقن) — للأونلاين أو إذا --no-inject."""
    print(f"[*] Launching without injection (online-safe mode)")
    print(f"[*] Game exe: {game_exe}")
    import subprocess
    try:
        subprocess.run([str(game_exe)] + extra_args)
        return 0
    except Exception as e:
        print(f"[X] Launch failed: {e}")
        return 1


def main():
    # نحلّل الأرقام: الـ flags الخاصة بنا فقط (--no-inject)، والباقي يُمرَّر للعبة
    ap = argparse.ArgumentParser(
        description="Steam wrapper for UE5 hook injection",
        add_help=False,
    )
    ap.add_argument("--no-inject", action="store_true",
                    help="شغّل اللعبة بدون حقن (للأونلاين)")
    ap.add_argument("--help-wrap", action="store_true",
                    help="عرض هذه المساعدة")
    # كل ما تبقّى = أمر اللعبة الذي مرّره Steam (%command%)
    known, rest = ap.parse_known_args()

    if known.help_wrap:
        print(__doc__)
        return 0

    if not rest:
        print(__doc__)
        print()
        print("[X] No game command received. هل ضبطت Launch Options في Steam؟")
        return 1

    print("=" * 70)
    print("  Steam Inject Wrapper")
    print("=" * 70)

    # rest[0] هو الـ exe، rest[1:] الـ args
    game_exe = Path(rest[0])
    extra_args = rest[1:]

    if not game_exe.exists():
        print(f"[X] Game exe not found: {game_exe}")
        return 1

    # ابحث عن config مطابق
    match = find_matching_config(game_exe)
    if not match:
        print(f"[!] No game config matches: {game_exe.name}")
        print("    شغّل اللعبة عادياً بدون ترجمة...")
        return launch_passthrough(game_exe, extra_args)

    game_name, cfg = match
    print(f"[OK] Matched config: {game_name}")

    if known.no_inject:
        return launch_passthrough(game_exe, extra_args)

    # ابحث عن DLL dir من الـ config
    hook_cfg = cfg.get("unreal_hook", {})
    dll_dir_str = hook_cfg.get("win64_dir") or str(game_exe.parent)
    dll_dir = Path(dll_dir_str)
    if not dll_dir.exists():
        print(f"[!] DLL dir not found: {dll_dir} — passthrough")
        return launch_passthrough(game_exe, extra_args)

    return launch_with_injection(game_exe, dll_dir, extra_args)


if __name__ == "__main__":
    sys.exit(main())
