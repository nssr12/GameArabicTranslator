"""
launch_unreal_game.py - Generic suspended-launch + inject launcher for UE games.

Works for any UE5 game that has hook DLLs installed in its Win64 folder.
Reads game config from games/configs/<name>.json to find exe path + DLL dir.

This solves the late-injection problem: launching the game suspended, injecting
DLLs, then resuming guarantees hooks are installed BEFORE any text rendering.

Usage:
    python tools/launch_unreal_game.py --game "Manor Lords"
    python tools/launch_unreal_game.py --game "Palworld"

    # Or pass paths directly:
    python tools/launch_unreal_game.py \\
        --game-exe "C:/.../Game-Win64-Shipping.exe" \\
        --dll-dir  "C:/.../Binaries/Win64"
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

# Reuse injector functions
sys.path.insert(0, str(Path(__file__).resolve().parent))
from inject_unreal_hook import inject_dll, INJECTION_ORDER, list_loaded_dlls

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Windows API ───────────────────────────────────────────────────────
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
CREATE_SUSPENDED = 0x00000004


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


kernel32.CreateProcessW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPWSTR,
    ctypes.c_void_p, ctypes.c_void_p,
    wintypes.BOOL, wintypes.DWORD,
    ctypes.c_void_p, wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW),
    ctypes.POINTER(PROCESS_INFORMATION),
]
kernel32.CreateProcessW.restype = wintypes.BOOL
kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
kernel32.ResumeThread.restype = wintypes.DWORD


def load_game_config(game_name: str) -> dict | None:
    """Load games/configs/<game_name>.json."""
    cfg_path = PROJECT_ROOT / "games" / "configs" / f"{game_name}.json"
    if not cfg_path.exists():
        return None
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[X] Failed to parse {cfg_path}: {e}")
        return None


def main():
    ap = argparse.ArgumentParser(description="Suspended-launch + DLL inject for any UE5 game")
    ap.add_argument("--game", help="Game name (loads games/configs/<name>.json)")
    ap.add_argument("--game-exe", help="Full path to game exe (overrides config)")
    ap.add_argument("--dll-dir", help="Full path to Win64 folder (overrides config)")
    args = ap.parse_args()

    print("=" * 70)
    print("  Unreal Game Launcher (suspended-injection)")
    print("=" * 70)

    game_exe = None
    dll_dir = None

    # Load from config if --game given
    if args.game:
        cfg = load_game_config(args.game)
        if not cfg:
            print(f"[X] Config not found for game: {args.game}")
            print(f"    Expected: games/configs/{args.game}.json")
            return 1
        # Try unreal_hook section first, fall back to top-level keys
        hook_cfg = cfg.get("unreal_hook", {})
        game_exe = (
            cfg.get("game_exe_inject")
            or hook_cfg.get("game_exe_inject")
        )
        dll_dir = hook_cfg.get("win64_dir")

    # CLI overrides
    if args.game_exe:
        game_exe = args.game_exe
    if args.dll_dir:
        dll_dir = args.dll_dir

    if not game_exe:
        print("[X] Game exe path not specified. Use --game-exe or set in config.")
        return 1
    if not dll_dir:
        # Default to same folder as exe
        dll_dir = str(Path(game_exe).parent)

    game_exe_path = Path(game_exe)
    dll_dir_path = Path(dll_dir)

    if not game_exe_path.exists():
        print(f"[X] Game exe not found: {game_exe_path}")
        return 1
    if not dll_dir_path.exists():
        print(f"[X] DLL folder not found: {dll_dir_path}")
        return 1

    print(f"[*] Game:    {args.game or '(custom)'}")
    print(f"[*] Exe:     {game_exe_path}")
    print(f"[*] DLL dir: {dll_dir_path}")

    # Verify hook DLLs present
    print()
    print("[*] Verifying hook DLLs...")
    missing = [dll for dll in INJECTION_ORDER if not (dll_dir_path / dll).exists()]
    if missing:
        print(f"[X] Missing hook DLLs: {missing}")
        print("    Install via GUI: Game page → Unreal Hook card → Install button")
        return 2
    print("[OK] All hook DLLs present")

    # CreateProcess SUSPENDED
    print()
    print("[*] Launching game SUSPENDED...")
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    cmd = ctypes.create_unicode_buffer(f'"{game_exe_path}"')

    ok = kernel32.CreateProcessW(
        str(game_exe_path),
        cmd,
        None, None,
        False,
        CREATE_SUSPENDED,
        None,
        str(game_exe_path.parent),
        ctypes.byref(si),
        ctypes.byref(pi),
    )

    if not ok:
        err = ctypes.get_last_error()
        print(f"[X] CreateProcess failed: error {err} = {ctypes.FormatError(err)}")
        print()
        print("Possible causes:")
        print("  - Steam not running (game requires Steam DRM)")
        print("  - Game already running (close it first)")
        print("  - Permissions issue (try Run as Admin)")
        return 3

    pid = pi.dwProcessId
    print(f"[OK] Process created SUSPENDED: PID={pid}")

    # Inject DLLs while suspended
    print()
    print("[*] Injecting hook DLLs (game paused — clean install)...")
    any_failed = False
    for dll in INJECTION_ORDER:
        full_path = str(dll_dir_path / dll)
        print(f"  [...] {dll}", end="", flush=True)
        try:
            ok_inj, msg = inject_dll(pid, full_path)
            if ok_inj:
                print(f"\r  [OK] {dll}  {msg}".ljust(70))
            else:
                print(f"\r  [X]  {dll}  {msg}".ljust(70))
                any_failed = True
        except Exception as e:
            print(f"\r  [X]  {dll}  exception: {e}")
            any_failed = True

    if any_failed:
        print()
        print("[!] Some DLLs failed. Resuming anyway (hook may be partial).")

    # Resume
    print()
    print("[*] Resuming game thread...")
    prev_count = kernel32.ResumeThread(pi.hThread)
    if prev_count == 0xFFFFFFFF:
        err = ctypes.get_last_error()
        print(f"[X] ResumeThread failed: error {err}")
        return 4

    print(f"[OK] Game running with hooks active!")
    print()
    print("=" * 70)
    print("  Game starting with translation hooks injected.")
    print("  Make sure proxy + watcher are running in other windows.")
    print("=" * 70)

    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)

    # Verify after a moment
    print()
    print("[*] Verifying loaded DLLs after 5s...")
    time.sleep(5)
    loaded = list_loaded_dlls(pid, INJECTION_ORDER)
    for dll in INJECTION_ORDER:
        found = any(dll.lower() in p.lower() for p in loaded)
        mark = "[Y]" if found else "[N]"
        print(f"  {mark} {dll}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
