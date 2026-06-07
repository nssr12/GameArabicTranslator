"""
inject_foundation.py — يشغّل Foundation معلّقاً، يحقن arabicfont.dll، ثم يستأنف.
الحقن المبكّر ضروري كي يُركَّب hook الخاص بـ FT_New_Memory_Face قبل بناء atlas الخطوط.

الاستخدام:
    python tools/foundation/inject_foundation.py

ملاحظات:
  • ينشئ steam_appid.txt (690830) كي يعمل foundation.exe مباشرةً دون إعادة إطلاق عبر Steam.
  • يجب أن يكون Steam مفتوحاً.
  • arabicfont.dll و arabic_ui.ttf يجب أن يكونا بجوار foundation.exe.
"""
import ctypes, os, sys, time
from ctypes import wintypes

GAME_DIR = r"D:/SteamLibrary/steamapps/common/Foundation"
EXE = os.path.join(GAME_DIR, "foundation.exe")
DLL = os.path.join(GAME_DIR, "arabicfont.dll")
APPID = "690830"

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

CREATE_SUSPENDED = 0x4
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04
INFINITE = 0xFFFFFFFF


class STARTUPINFO(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
                ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
                ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


def main():
    if not os.path.exists(DLL):
        print(f"❌ لا يوجد {DLL} — انسخ arabicfont.dll للعبة أولاً."); return 1
    if not os.path.exists(os.path.join(GAME_DIR, "arabic_ui.ttf")):
        print("❌ لا يوجد arabic_ui.ttf بجوار اللعبة."); return 1

    # steam_appid.txt + متغيّرات بيئة Steam → اللعبة تعتبر نفسها مُطلقة عبر Steam
    # (تمنع SteamAPI_RestartAppIfNecessary من إعادة الإطلاق/الخروج).
    with open(os.path.join(GAME_DIR, "steam_appid.txt"), "w") as f:
        f.write(APPID)
    os.environ["SteamAppId"] = APPID
    os.environ["SteamGameId"] = APPID
    os.environ["SteamOverlayGameId"] = APPID
    os.environ["SteamClientLaunch"] = "1"
    os.environ["SteamEnv"] = "1"

    si = STARTUPINFO(); si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    k32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p,
                                   ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.LPCWSTR,
                                   ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESS_INFORMATION)]
    ok = k32.CreateProcessW(EXE, None, None, None, False, CREATE_SUSPENDED,
                            None, GAME_DIR, ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        print(f"❌ CreateProcess فشل: {ctypes.get_last_error()}"); return 1
    print(f"✓ أُطلقت Foundation معلّقة (PID={pi.dwProcessId})")

    # حقن LoadLibraryW(DLL)
    dll_w = DLL.replace("/", "\\")
    buf = (dll_w + "\x00").encode("utf-16-le")
    k32.VirtualAllocEx.restype = ctypes.c_void_p
    k32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
    addr = k32.VirtualAllocEx(pi.hProcess, None, len(buf), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
    written = ctypes.c_size_t(0)
    k32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.WriteProcessMemory(pi.hProcess, addr, buf, len(buf), ctypes.byref(written))

    h_k32 = k32.GetModuleHandleW("kernel32.dll")
    k32.GetProcAddress.restype = ctypes.c_void_p
    k32.GetProcAddress.argtypes = [wintypes.HANDLE, ctypes.c_char_p]
    load_lib = k32.GetProcAddress(h_k32, b"LoadLibraryW")

    k32.CreateRemoteThread.restype = wintypes.HANDLE
    k32.CreateRemoteThread.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    # ⚠ استأنف العملية أولاً كي يُهيَّأ الـ loader، ثم احقن (الحقن في عملية معلّقة
    #    قبل تهيئة الـ loader يُفسدها). نافذة ما قبل بناء الـ atlas واسعة (ثوانٍ).
    k32.ResumeThread(pi.hThread)
    time.sleep(0.30)   # تهيئة الـ loader + بدء العملية

    th = k32.CreateRemoteThread(pi.hProcess, None, 0, ctypes.c_void_p(load_lib),
                                ctypes.c_void_p(addr), 0, None)
    if not th:
        print(f"❌ CreateRemoteThread فشل: {ctypes.get_last_error()}"); return 1
    k32.WaitForSingleObject(th, 10000)   # انتظر LoadLibrary (DllMain → InitThread)
    print("✓ حُقن arabicfont.dll بعد تهيئة الـ loader — قبل بناء atlas الخطوط.")
    print("  راقب arabicfont_dll.log بجوار اللعبة + شاشة العربية.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
