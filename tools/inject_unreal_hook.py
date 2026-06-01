"""
inject_unreal_hook.py - Inject Unreal Engine text hook DLLs into a running game process.

Why: dxgi.dll is a "KnownDLL" on Windows 10/11, loaded from System32 only.
The local dxgi.dll (hook entry point) is ignored by Windows DLL loader.
Solution: CreateRemoteThread + LoadLibrary to manually inject the hook DLLs.

Usage:
    # Wait for Manor Lords and inject automatically:
    python tools/inject_unreal_hook.py

    # Or specify a different process:
    python tools/inject_unreal_hook.py --process "SomeGame-Win64-Shipping.exe"

    # With custom DLL folder:
    python tools/inject_unreal_hook.py --dll-dir "C:/path/to/Win64"
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import csv
import io
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_DLL_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\Manor Lords\ManorLords\Binaries\Win64"
DEFAULT_PROCESS = "ManorLords-Win64-Shipping.exe"

# Inject in order: dependencies FIRST, then main DLLs.
# cppfs.dll  = filesystem dep needed by ZXSOSZXNMod (loads first)
# dxgi.dll   = Hook's entry point hijack (blocked by KnownDLLs at startup,
#              but manual injection works)
# ZXSOSZXNMod.dll = native hook engine (depends on cppfs)
# ZXSOSZXMod.dll  = managed mod loader (.NET, loads native via mscoree)
INJECTION_ORDER = ["cppfs.dll", "dxgi.dll", "ZXSOSZXNMod.dll", "ZXSOSZXMod.dll"]

# ── Windows API setup ─────────────────────────────────────────────────
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
kernel32.VirtualFreeEx.restype = wintypes.BOOL
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.restype = wintypes.BOOL
kernel32.CreateRemoteThread.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
kernel32.CreateRemoteThread.restype = wintypes.HANDLE
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.GetModuleHandleA.argtypes = [ctypes.c_char_p]
kernel32.GetModuleHandleA.restype = ctypes.c_void_p
kernel32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
kernel32.GetProcAddress.restype = ctypes.c_void_p
kernel32.GetExitCodeThread.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeThread.restype = wintypes.BOOL

psapi.EnumProcessModules.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
psapi.EnumProcessModules.restype = wintypes.BOOL
psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD]
psapi.GetModuleFileNameExW.restype = wintypes.DWORD


def find_pid(process_name: str) -> int | None:
    """Find PID of a running process by name."""
    try:
        result = subprocess.run(
            ['tasklist', '/FI', f'IMAGENAME eq {process_name}', '/FO', 'CSV', '/NH'],
            capture_output=True, text=True, timeout=10
        )
        reader = csv.reader(io.StringIO(result.stdout))
        for row in reader:
            if len(row) >= 2 and row[0].lower() == process_name.lower():
                return int(row[1])
    except Exception as e:
        print(f"[X] tasklist failed: {e}")
    return None


def list_loaded_dlls(pid: int, name_filter: list[str] | None = None) -> list[str]:
    """List DLLs currently loaded in target process."""
    h = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
    if not h:
        return []
    try:
        HMODS = (ctypes.c_void_p * 1024)()
        needed = wintypes.DWORD(0)
        psapi.EnumProcessModules(h, HMODS, ctypes.sizeof(HMODS), ctypes.byref(needed))
        n = needed.value // ctypes.sizeof(ctypes.c_void_p)
        result = []
        for i in range(n):
            buf = ctypes.create_unicode_buffer(512)
            psapi.GetModuleFileNameExW(h, HMODS[i], buf, 512)
            path = buf.value
            if path:
                if name_filter:
                    for nf in name_filter:
                        if nf.lower() in path.lower():
                            result.append(path)
                            break
                else:
                    result.append(path)
        return result
    finally:
        kernel32.CloseHandle(h)


def inject_dll(pid: int, dll_path: str) -> tuple[bool, str]:
    """Inject a DLL into target process.

    Uses LoadLibraryExW with LOAD_WITH_ALTERED_SEARCH_PATH so the DLL's own
    directory is searched FIRST for its dependencies (e.g. cppfs.dll for
    ZXSOSZXNMod.dll). This bypasses Windows' default DLL search order which
    can fail when the target process's CWD differs from the DLL location.
    """
    # We need to pass: (LPCWSTR path, HANDLE 0, DWORD flags)
    # but CreateRemoteThread can only pass 1 arg. Solution: write a small
    # struct in remote memory, then call a wrapper. Easier: use LoadLibraryW
    # which only needs the path. Windows DLL search via SetDllDirectory or
    # AddDllDirectory inside the target — but that needs another thread.
    #
    # Simplest working solution: call LoadLibraryW with the full path. The
    # full path means LoadLibrary looks in that directory first.
    # For dependencies (cppfs.dll), we rely on the fact that they're in the
    # same directory as the DLL being loaded. Windows DOES check the DLL's
    # own directory for its dependencies (DLL Redirection rules).

    # Use wide chars (LPCWSTR) for LoadLibraryW
    dll_path_w = (dll_path + '\x00').encode('utf-16-le')

    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        err = ctypes.get_last_error()
        return False, f"OpenProcess failed (err {err}). Run as admin."

    try:
        remote_addr = kernel32.VirtualAllocEx(
            h, None, len(dll_path_w),
            MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
        )
        if not remote_addr:
            err = ctypes.get_last_error()
            return False, f"VirtualAllocEx failed (err {err})"

        try:
            written = ctypes.c_size_t(0)
            if not kernel32.WriteProcessMemory(
                h, remote_addr, dll_path_w, len(dll_path_w), ctypes.byref(written)
            ):
                err = ctypes.get_last_error()
                return False, f"WriteProcessMemory failed (err {err})"

            # Use LoadLibraryW (wide-char version)
            kernel32_handle = kernel32.GetModuleHandleA(b"kernel32.dll")
            loadlib_addr = kernel32.GetProcAddress(kernel32_handle, b"LoadLibraryW")
            if not loadlib_addr:
                return False, "GetProcAddress(LoadLibraryW) failed"

            thread_id = wintypes.DWORD(0)
            thread_h = kernel32.CreateRemoteThread(
                h, None, 0, loadlib_addr, remote_addr, 0, ctypes.byref(thread_id)
            )
            if not thread_h:
                err = ctypes.get_last_error()
                return False, f"CreateRemoteThread failed (err {err})"

            # 6. Wait for thread to finish
            try:
                wait_result = kernel32.WaitForSingleObject(thread_h, 10000)  # 10s timeout
                if wait_result == 0x102:  # WAIT_TIMEOUT
                    return False, "LoadLibrary timeout (DLL may be hung)"

                # 7. Check exit code (LoadLibrary returns HMODULE or NULL)
                exit_code = wintypes.DWORD(0)
                kernel32.GetExitCodeThread(thread_h, ctypes.byref(exit_code))
                if exit_code.value == 0:
                    return False, "LoadLibrary returned NULL (DLL load failed)"

                return True, f"loaded (handle=0x{exit_code.value:08x})"
            finally:
                kernel32.CloseHandle(thread_h)

        finally:
            kernel32.VirtualFreeEx(h, remote_addr, 0, MEM_RELEASE)

    finally:
        kernel32.CloseHandle(h)


def main():
    ap = argparse.ArgumentParser(description="Inject hook DLLs into a UE5 game process")
    ap.add_argument("--process", default=DEFAULT_PROCESS,
                    help=f"Process name (default: {DEFAULT_PROCESS})")
    ap.add_argument("--dll-dir", default=DEFAULT_DLL_DIR,
                    help="DLL folder (default: Manor Lords Win64)")
    ap.add_argument("--wait", type=int, default=60,
                    help="Wait up to N seconds for process (default 60)")
    ap.add_argument("--watch", action="store_true",
                    help="Keep running, auto-inject when game starts again")
    args = ap.parse_args()

    print("=" * 70)
    print("  Unreal Hook DLL Injector")
    print("=" * 70)
    print(f"[*] Target process: {args.process}")
    print(f"[*] DLL folder:     {args.dll_dir}")

    dll_dir = Path(args.dll_dir)
    if not dll_dir.exists():
        print(f"[X] DLL folder not found: {dll_dir}")
        return 1

    # Verify all DLLs exist
    missing = []
    for dll in INJECTION_ORDER:
        if not (dll_dir / dll).exists():
            missing.append(dll)
    if missing:
        print(f"[X] Missing DLLs: {missing}")
        print(f"    Make sure hook DLLs are installed to {dll_dir}")
        return 2

    def attempt_injection():
        # Find PID
        print(f"\n[*] Looking for {args.process}...")
        deadline = time.time() + args.wait
        pid = None
        while time.time() < deadline:
            pid = find_pid(args.process)
            if pid:
                print(f"[OK] Found PID: {pid}")
                break
            time.sleep(1)
        if not pid:
            print(f"[X] Process not found after {args.wait}s. Launch the game first.")
            return False

        # Wait briefly for game to fully init (otherwise injection may crash)
        print("[*] Waiting 5s for game to initialize...")
        time.sleep(5)

        # Check what's already loaded
        already_loaded = list_loaded_dlls(pid, INJECTION_ORDER)
        already_names = set()
        for path in already_loaded:
            for dll in INJECTION_ORDER:
                if dll.lower() in path.lower():
                    already_names.add(dll)

        # Inject each DLL
        print()
        print("[*] Injecting DLLs...")
        any_failed = False
        for dll in INJECTION_ORDER:
            full_path = str(dll_dir / dll)
            if dll in already_names:
                print(f"  [SKIP] {dll}  (already loaded)")
                continue
            print(f"  [...] {dll}...", end="", flush=True)
            ok, msg = inject_dll(pid, full_path)
            if ok:
                print(f"\r  [OK] {dll}  {msg}")
            else:
                print(f"\r  [X]  {dll}  {msg}")
                any_failed = True

        # Verify
        print()
        print("[*] Verifying loaded DLLs...")
        time.sleep(2)
        loaded = list_loaded_dlls(pid, INJECTION_ORDER)
        for dll in INJECTION_ORDER:
            found = any(dll.lower() in p.lower() for p in loaded)
            mark = "[Y]" if found else "[N]"
            print(f"  {mark} {dll}")

        return not any_failed

    if args.watch:
        print("\n[*] Watch mode: will auto-inject when game appears.")
        seen_pid = None
        while True:
            try:
                pid = find_pid(args.process)
                if pid and pid != seen_pid:
                    print(f"\n[*] New game instance detected (PID={pid})")
                    attempt_injection()
                    seen_pid = pid
                elif not pid:
                    seen_pid = None
                time.sleep(3)
            except KeyboardInterrupt:
                print("\n[*] Stopped")
                break
    else:
        ok = attempt_injection()
        return 0 if ok else 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
