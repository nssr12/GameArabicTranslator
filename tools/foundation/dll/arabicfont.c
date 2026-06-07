/* arabicfont.c — DLL يُحقن في foundation.exe لحقن دعم العربية في خطوط الواجهة.
 *
 * المحرّك يقرأ خطوط Noto (مفكوكة التشفير) عبر FT_New_Memory_Face لبناء atlas.
 * نعترض الاستدعاء ونستبدل خط الواجهة بخط عربي مطابق للنمط (Regular/Bold).
 *
 * الخطوط (بجوار foundation.exe):
 *   arabic_regular.ttf  → للخطوط العادية (NotoSans-Regular, NotoSansMono)
 *   arabic_bold.ttf     → للخطوط العريضة/المائلة (Bold + BoldItalic — العربية بلا مائل)
 *
 * FreeType يقيس الخط (vector) لأي حجم نقطي، فخط واحد لكل نمط يكفي كل الأحجام.
 * التسجيل بـ Win32 خالص. يُحمَّل تلقائياً كـ proxy لـ CrashRpt1403.dll.
 */
#include <windows.h>
#include "MinHook.h"

#define FT_NEW_MEMORY_FACE_VA  0x141e06eb0ULL
#define IMAGE_BASE_DEFAULT     0x140000000ULL

/* مدى أحجام خطوط الواجهة اللاتينية (Sans/Serif/Mono). Thai(~47KB) و CJK(~16MB) خارجه. */
#define FONT_MIN_BYTES 400000LL
#define FONT_MAX_BYTES 700000LL

/* أحجام الخطوط العريضة/المائلة (من جدول الحزمة) → تُستبدل بالعربي العريض */
static const long long kBoldSizes[] = {
    455164,  /* NotoSans-Bold */
    471004,  /* NotoSans-BoldItalic */
    570708,  /* NotoSerif-Bold */
    608488,  /* NotoSerif-BoldItalic */
};
static const int kNumBold = 4;

typedef int (__cdecl *FT_NewMemFace_t)(void *library, const unsigned char *file_base,
                                       long long file_size, long long face_index, void **aface);
static FT_NewMemFace_t g_orig = NULL;

static unsigned char *g_reg = NULL;  static long long g_regLen = 0;
static unsigned char *g_bold = NULL; static long long g_boldLen = 0;
static char g_logPath[MAX_PATH];

static void W(const char *s) {
    HANDLE h = CreateFileA(g_logPath, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return;
    SetFilePointer(h, 0, NULL, FILE_END);
    DWORD n = 0, len = 0; while (s[len]) len++;
    WriteFile(h, s, len, &n, NULL); WriteFile(h, "\r\n", 2, &n, NULL); CloseHandle(h);
}
static void Wnum(const char *label, unsigned long long v) {
    char buf[80]; int i = 0; while (label[i] && i < 50) { buf[i] = label[i]; i++; }
    buf[i++] = ' '; buf[i++] = '0'; buf[i++] = 'x';
    char tmp[20]; int t = 0; if (!v) tmp[t++] = '0';
    while (v) { int d = v & 0xF; tmp[t++] = d < 10 ? '0' + d : 'a' + d - 10; v >>= 4; }
    while (t) buf[i++] = tmp[--t];
    buf[i] = 0; W(buf);
}

/* اقرأ ملف خط بجوار foundation.exe → بافر */
static unsigned char *LoadFile(const char *fname, long long *outLen) {
    char path[MAX_PATH]; GetModuleFileNameA(NULL, path, MAX_PATH);
    char *sl = NULL; for (char *p = path; *p; p++) if (*p == '\\') sl = p;
    if (sl) { sl[1] = 0; lstrcatA(path, fname); }
    HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                           FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) { W("[ArFont] missing font:"); W(fname); return NULL; }
    DWORD sz = GetFileSize(h, NULL);
    unsigned char *buf = (unsigned char *)VirtualAlloc(NULL, sz, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    DWORD got = 0; ReadFile(h, buf, sz, &got, NULL); CloseHandle(h);
    *outLen = got; return buf;
}

/* اختر الخط العربي المناسب لحجم الخط الأصلي */
static const unsigned char *Pick(long long size, long long *outLen) {
    if (size <= FONT_MIN_BYTES || size >= FONT_MAX_BYTES) return NULL;
    for (int k = 0; k < kNumBold; k++)
        if (size == kBoldSizes[k]) { *outLen = g_boldLen; return g_bold; }
    *outLen = g_regLen; return g_reg;   /* الباقي في المدى → Regular */
}

static int __cdecl Hook_FT(void *library, const unsigned char *file_base,
                           long long file_size, long long face_index, void **aface) {
    long long len = 0;
    const unsigned char *sub = Pick(file_size, &len);
    if (sub && len > 0) {
        Wnum("[ArFont] sub size", (unsigned long long)file_size);
        return g_orig(library, sub, len, face_index, aface);
    }
    return g_orig(library, file_base, file_size, face_index, aface);
}

static DWORD WINAPI InitThread(LPVOID p) {
    W("[ArFont] InitThread start");
    g_reg = LoadFile("arabic_regular.ttf", &g_regLen);
    g_bold = LoadFile("arabic_bold.ttf", &g_boldLen);
    if (!g_reg) { W("[ArFont] regular font FAILED"); return 1; }
    if (!g_bold) { g_bold = g_reg; g_boldLen = g_regLen; W("[ArFont] bold missing → using regular"); }
    Wnum("[ArFont] regular bytes", g_regLen);
    Wnum("[ArFont] bold bytes", g_boldLen);

    unsigned long long base = (unsigned long long)GetModuleHandleA(NULL);
    unsigned long long ft = base + (FT_NEW_MEMORY_FACE_VA - IMAGE_BASE_DEFAULT);
    if (MH_Initialize() != MH_OK) { W("[ArFont] MH_Initialize FAILED"); return 1; }
    if (MH_CreateHook((LPVOID)ft, &Hook_FT, (LPVOID *)&g_orig) != MH_OK) { W("[ArFont] MH_CreateHook FAILED"); return 1; }
    if (MH_EnableHook((LPVOID)ft) != MH_OK) { W("[ArFont] MH_EnableHook FAILED"); return 1; }
    W("[ArFont] HOOK INSTALLED OK");
    return 0;
}

BOOL APIENTRY DllMain(HMODULE h, DWORD reason, LPVOID r) {
    if (reason == DLL_PROCESS_ATTACH) {
        GetModuleFileNameA(NULL, g_logPath, MAX_PATH);
        char *sl = NULL; for (char *p = g_logPath; *p; p++) if (*p == '\\') sl = p;
        if (sl) { sl[1] = 0; lstrcatA(g_logPath, "arabicfont_dll.log"); }
        W("[ArFont] DllMain ATTACH");
        DisableThreadLibraryCalls(h);
        CreateThread(NULL, 0, InitThread, NULL, 0, NULL);
    }
    return TRUE;
}
