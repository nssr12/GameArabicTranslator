"""
steam_wrap.py — غلاف Steam Launch Options لحقن arabicfont.dll في Foundation.

اضبط في Steam: Foundation → Properties → Launch Options:
    "C:\\Python314\\python.exe" "D:\\GameArabicTranslator\\tools\\foundation\\steam_wrap.py" %command%

Steam يستبدل %command% بأمر تشغيل اللعبة الكامل (exe + args)، فيرث الغلاف بيئة
Steam الحقيقية (IPC + SteamAppId) ويمرّرها للعبة → SteamAPI_Init ينجح → لا خروج.
ثم نحقن الـ DLL مبكراً (قبل بناء atlas الخطوط).
"""
import ctypes, os, sys, time, subprocess
from ctypes import wintypes

DLL = r"D:/SteamLibrary/steamapps/common/Foundation/arabicfont.dll"
k32 = ctypes.WinDLL("kernel32", use_last_error=True)

CREATE_SUSPENDED = 0x4
MEM_COMMIT = 0x1000; MEM_RESERVE = 0x2000; PAGE_READWRITE = 0x04


class STARTUPINFO(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
                ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD), ("dwXSize", wintypes.DWORD),
                ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD),
                ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
                ("hStdError", wintypes.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


def inject(hProcess, dll):
    buf = (dll.replace("/", "\\") + "\x00").encode("utf-16-le")
    k32.VirtualAllocEx.restype = ctypes.c_void_p
    k32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
    addr = k32.VirtualAllocEx(hProcess, None, len(buf), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
    written = ctypes.c_size_t(0)
    k32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.WriteProcessMemory(hProcess, addr, buf, len(buf), ctypes.byref(written))
    h_k32 = k32.GetModuleHandleW("kernel32.dll")
    k32.GetProcAddress.restype = ctypes.c_void_p
    k32.GetProcAddress.argtypes = [wintypes.HANDLE, ctypes.c_char_p]
    load = k32.GetProcAddress(h_k32, b"LoadLibraryW")
    k32.CreateRemoteThread.restype = wintypes.HANDLE
    k32.CreateRemoteThread.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    th = k32.CreateRemoteThread(hProcess, None, 0, ctypes.c_void_p(load), ctypes.c_void_p(addr), 0, None)
    if not th:
        return False
    k32.WaitForSingleObject(th, 10000)
    code = wintypes.DWORD(0)
    k32.GetExitCodeThread(th, ctypes.byref(code))   # = HMODULE (نجاح) أو 0 (فشل)
    return code.value != 0


def main():
    # sys.argv[1:] = أمر اللعبة من %command%
    if len(sys.argv) < 2:
        print("لا أمر — مرّر %command%"); return 1
    cmdline = subprocess.list2cmdline(sys.argv[1:])
    game_dir = os.path.dirname(sys.argv[1])

    si = STARTUPINFO(); si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    k32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                   wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                                   ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESS_INFORMATION)]
    # نطلق معلّقاً (للحقن المبكّر) لكن نرث بيئة Steam (lpEnvironment=NULL)
    ok = k32.CreateProcessW(None, ctypes.create_unicode_buffer(cmdline), None, None, True,
                            CREATE_SUSPENDED, None, game_dir or None,
                            ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        print(f"CreateProcess فشل: {ctypes.get_last_error()}"); return 1

    # استأنف ليُهيَّأ الـ loader + يكتمل Steam handshake، ثم احقن قبل بناء الـ atlas
    k32.ResumeThread(pi.hThread)
    time.sleep(0.5)
    okj = inject(pi.hProcess, DLL)
    print("حقن:", "نجح" if okj else "فشل")
    # ابقَ حياً حتى تنتهي اللعبة (Steam يتتبّع هذه العملية كـ "اللعبة")
    k32.WaitForSingleObject(pi.hProcess, 0xFFFFFFFF)
    return 0


if __name__ == "__main__":
    sys.exit(main())
