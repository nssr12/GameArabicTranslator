# تعريب Foundation — ✅ مكتمل ويعمل

> آخر تحديث: 2026-06-03 — **المشروع مكتمل**. المحرّك: Hurricane (خاص، خطوط Noto مشفّرة في game.package).
> تشغيل Steam عادي → عربية كاملة صحيحة (RTL + تشكيل + أنماط + أسطر متعدّدة).

## الخلاصة — كل شيء يعمل ✅
- **الترجمة**: 7,248 نص مترجم (Foundation.db) + مكتوب في ar/*.json بتخطيط RTL.
- **الخط**: proxy `CrashRpt1403.dll` يُحمَّل تلقائياً عند الإطلاق العادي → hook على
  `FT_New_Memory_Face @ 0x141e06eb0` يستبدل خطوط الواجهة (Regular→arabic_regular،
  Bold/BoldItalic→arabic_bold) بخط عربي. يتجاوز تشفير الحزمة (المحرّك يفكّ قبل FT).
- **RTL متعدّد الأسطر**: `engine/rtl_layout.py` (تطبيع `\n` + لفّ ذاتي + تشكيل/عكس لكل سطر).

## آلية النشر (للإطلاق العادي عبر Steam)
في مجلّد اللعبة:
- `CrashRpt1403.dll` ← الـ proxy (محلّنا)؛ `CrashRpt1403_orig.dll` ← الأصلية.
- `arabic_regular.ttf` (arial) + `arabic_bold.ttf` (arialbd) — خطوط الاستبدال.
- `localization/ar/*.json` — الترجمة المُشكّلة؛ `locales.txt` فيه `ar:` (اسم مُشكّل).
- اضبط اللغة=ar في usersetting.config، احذف charset.txt مرّة (يُعاد توليده).
- ⚠ تحديث Steam يستعيد CrashRpt1403.dll → أعد النشر (انظر "بناء/نشر").

## بناء/نشر الـ proxy
```bash
ZIG=tools/zig/zig-x86_64-windows-0.16.0/zig.exe
$ZIG cc -shared -target x86_64-windows-gnu -O2 -I tools/foundation/tools_minhook/include \
  tools/foundation/dll/arabicfont.c tools/foundation/dll/CrashRpt1403.def \
  tools/foundation/tools_minhook/src/*.c tools/foundation/tools_minhook/src/hde/hde64.c \
  -o tools/foundation/dll/CrashRpt1403.dll -lkernel32 -luser32
# انسخ CrashRpt1403.dll + arabic_regular.ttf + arabic_bold.ttf لمجلّد اللعبة
```

## RTL متعدّد الأسطر — الحلّ الجذري (قابل لإعادة الاستخدام)
`engine/rtl_layout.py::layout_rtl(text, max_line_len)`:
1. `\n` حرفي → سطر فعلي.
2. لفّ الكلمات إلى أسطر ≤ max_line_len (للصناديق التي تطبّق auto-wrap).
3. تشكيل + عكس BiDi لكل سطر مستقلاً (الترتيب الرأسي محفوظ).
القاعدة: max_line_len ≤ أضيق صندوق → لا auto-wrap → ترتيب صحيح دائماً. (Foundation: 45)

## لمسات اختيارية متبقية
- الخط: arial حالياً → للتوزيع ادمج Noto Sans + خط عربي مفتوح الرخصة (مطابقة مظهر + ترخيص).
- ضبط `--wrap` حسب أضيق صندوق نص في اللعبة.
- توحيد مصطلحات (Seneschal) بمسرد.
- placeholders ({1}/{IMG1}) داخل RTL: ضبط موضع في جمل نادرة.

---
## أرشيف الاكتشافات (مرجع)

---

## 1) الترجمة — تعمل ومحفوظة ✅

| العنصر | القيمة |
|------|------|
| الأداة | `tools/foundation/translate_foundation.py` |
| الكاش | `data/cache/Foundation.db` (يُحفظ كل سطر فوراً — قابل للاستئناف) |
| التقدّم | ~6006 / 7248 نص فريد |
| المخرجات | `D:/SteamLibrary/.../Foundation/localization/ar/*.json` |

**للاستئناف/الإكمال:**
```bash
C:/Python314/python tools/foundation/translate_foundation.py          # يكمل من الكاش
C:/Python314/python tools/foundation/translate_foundation.py --analyze  # إحصاء
C:/Python314/python tools/foundation/translate_foundation.py --write-only  # يعيد كتابة ar/ من الكاش
C:/Python314/python tools/foundation/translate_foundation.py --shape   # + تشكيل عند الكتابة
```
- التشكيل (presentation forms + عكس) **اختياري** عبر `--shape` — نقرّره بعد ما نعرف هل المحرّك يشكّل (فيه ICU).
- مصطلح "Seneschal" تُرجم بصيغ مختلفة — يُوحَّد لاحقاً بمسرد.

---

## 2) حقن الخط (مسار DLL) — جاهز، ينتظر اختبار الحقن

**الاكتشافات (Ghidra):**
- مشروع Ghidra محفوظ: `tools/foundation/ghidra_proj/` (لا يحتاج إعادة تحليل — استخدم `-process foundation.exe -noanalysis`).
- دالة بناء الخط: `GenCFreeTypeFont::build` @ `0x1403d4220` (تطابق `GuiCSkinAtlasBuilder::addFont`).
- **`FT_New_Memory_Face` = `FUN_141e06eb0` @ `0x141e06eb0`** ← نقطة الحقن (image base `0x140000000`).
  التوقيع: `(library, file_base, file_size, face_index, aface)`.

**المكوّنات الجاهزة:**
| الملف | الدور |
|------|------|
| `tools/foundation/dll/arabicfont.c` | DLL يعترض FT_New_Memory_Face، يستبدل خط الواجهة (يُعرَف بالحجم 455188/455164/471004) بـ `arabic_ui.ttf`. تسجيل Win32 خالص. |
| `tools/foundation/work/arabic_ui.ttf` | الخط البديل (arial: لاتيني+سيريلي+عربي+presentation forms). |
| `tools/foundation/steam_wrap.py` | غلاف Steam Launch Options (يُطلق+يحقن — handshake حقيقي). |
| `tools/foundation/inject_foundation.py` | حاقن مباشر (يفشل بسبب Steam handshake — استخدم الغلاف). |
| `tools/zig/` | مترجم Zig لبناء الـ DLL. |
| `tools/foundation/tools_minhook/` | MinHook (detour). |

**بناء الـ DLL:**
```bash
ZIG=tools/zig/zig-x86_64-windows-0.16.0/zig.exe
$ZIG cc -shared -target x86_64-windows-gnu -O2 -I tools/foundation/tools_minhook/include \
  tools/foundation/dll/arabicfont.c \
  tools/foundation/tools_minhook/src/buffer.c tools/foundation/tools_minhook/src/hook.c \
  tools/foundation/tools_minhook/src/trampoline.c tools/foundation/tools_minhook/src/hde/hde64.c \
  -o tools/foundation/dll/arabicfont.dll -lkernel32 -luser32
```

**الاختبار (الخطوة التالية):**
1. Steam → Foundation → Properties → Launch Options:
   `"C:\Python314\python.exe" "D:\GameArabicTranslator\tools\foundation\steam_wrap.py" %command%`
2. تأكّد: اللغة=ar، charset محذوف، `arabicfont.dll`+`arabic_ui.ttf` بجوار foundation.exe.
3. شغّل عبر Steam → افحص القائمة الرئيسية + `arabicfont_dll.log`.

**سجلّ التشخيص المتوقّع** (`arabicfont_dll.log` بجوار foundation.exe):
`DllMain ATTACH` → `font loaded bytes` → `HOOK INSTALLED OK` → `substitute size 0x...` (لكل خط واجهة).

---

## 3) العوائق المحلولة في الطريق
- المود لا يدعم حقن الخطوط (لا نوع أصل خط في API + الـ atlas يُبنى قبل المودات). → مسدود.
- game.package **مشفّر** (مفتاح لكل أصل) → لا تعديل مباشر. → تجاوزناه بحقن FreeType (المحرّك يفكّ التشفير قبل FT).
- التشغيل المباشر يخرج عند Steam handshake. → الحل: غلاف Steam Launch Options.

## أدوات مساعدة
- `tools/foundation/pkg.py` — محلّل/مستخرج حزمة Foundation.
- `tools/foundation/find_ft.py` / `find_xref.py` / `disasm.py` — أدوات RE.
- `tools/foundation/ghidra_scripts/FindFreeType.java` — سكربت كشف تدفّق الخط.
