# UE4 Arabic Translator

> مود UE4SS عام (Lua) لترجمة ألعاب Unreal Engine للعربية بدون lag.
> يدعم: UE 4.x, UE 5.x. مختبر على: ManorLords (UE5).

## الفكرة الأساسية

```
1. القاموس (dict/translations.txt) يُحمَّل مرة واحدة في الذاكرة
2. main.lua يهوك UFunctions النصوص (TextBlock:SetText إلخ.)
3. عند كل عرض نصّ:
   - في القاموس؟ → استبدل بالعربي فوراً (O(1) lookup)
   - غير موجود؟ → سجّله في missing.txt للترجمة لاحقاً
4. صفر قرص I/O أثناء اللعب → صفر lag
```

## بنية المجلد

```
UE4ArabicTranslator/
├── Scripts/
│   ├── main.lua         ← المنطق الأساسي + hooks
│   └── explore.lua      ← (اختياري) لاستكشاف UFunctions اللعبة
├── dict/
│   ├── translations.txt ← القاموس (key=value، يُولَّد من Python)
│   └── missing.txt      ← نصوص جديدة وجدتها اللعبة (لـ Python لترجمتها)
├── enabled.txt          ← (موجود = مُفعَّل)
└── README.md            ← هذا الملف
```

## التثبيت

### الخطوة 1: ثبّت UE4SS في اللعبة

```
انسخ من: d:\GameArabicTranslator\tools\UE4SS\zDEV-UE4SS_v3.0.1\
       إلى: <Game>\<GameName>\Binaries\Win64\
       (الملفات: UE4SS.dll, dwmapi.dll, UE4SS-settings.ini, ...)
```

### الخطوة 2: انسخ هذا الـ mod

```
انسخ مجلد UE4ArabicTranslator كاملاً إلى:
   <Game>\<GameName>\Binaries\Win64\Mods\UE4ArabicTranslator\
```

### الخطوة 3: فعّل الـ mod في mods.txt

افتح: `<Game>\<GameName>\Binaries\Win64\Mods\mods.txt`
أضف سطراً:
```
UE4ArabicTranslator : 1
```

### الخطوة 4: ولّد القاموس من Python

اذهب لـ Game Arabic Translator → صفحة اللعبة → **🔄 تحديث الترجمات**
سيُولَّد dict/translations.txt تلقائياً من Cache.

### الخطوة 5: شغّل اللعبة

عند تشغيل اللعبة، تلقائياً ترى في الـ console:
```
[ArabicTr] UE4 Arabic Translator starting...
[ArabicTr] dict تحميل: 1234 ترجمة
[ArabicTr] hooks مُركَّبة: 6/6
[ArabicTr] جاهز ✓
```

## وضع الاستكشاف (لإضافة لعبة جديدة)

لو ManorLords أو لعبة UE أخرى تستخدم UFunctions غير قياسية:

1. افتح `Scripts/main.lua`، غيّر `CONFIG.enable_explore = true`
2. شغّل اللعبة، تنقّل بين كل الشاشات (قائمة، إعدادات، dialogue، إلخ)
3. أغلق اللعبة
4. افحص `<Game>\Binaries\Win64\ue4ss_arabic_logs\explore_log.txt`
5. أضف الـ UFunctions الجديدة لـ `HOOK_TARGETS` في `main.lua`
6. أعد ضبط `enable_explore = false`

## كيف يعمل بدون lag

| المشكلة في FLTAH | حلّنا |
|------|------|
| 158 ملف قرص لكل لعبة | ملف واحد محمَّل في الذاكرة |
| Disk read لكل نصّ | Hash lookup O(1) في الـ RAM |
| DLL hijacking (dxgi.dll) | UE4SS الرسمي (proper hooks) |
| Hash collisions | لا hash — مفتاح = النص الإنجليزي مباشرة |
| Per-game addresses في .ini | UE4SS يستخدم AOB signatures عامة |

## التكامل مع Game Arabic Translator

```
Python (engine/proxy_server.py)
   ↓ يجمع ترجمات في cache (Game.db)
Python (games/ue4ss_mod.py)
   ↓ يُصدِّر إلى translations.txt
UE4ArabicTranslator (Lua mod)
   ↓ يطبّقها في اللعبة بـ صفر lag
الترجمات الجديدة:
   missing.txt ← يُكتب بواسطة الـ mod
Python (يقرأه)
   ↓ يترجم النصوص الجديدة عبر Ollama
   ↓ يضيفها للـ cache
الدورة تتكرر — كل ما تلعب أكثر، الترجمة تتحسّن
```

## الاختبار

بعد التثبيت:
- شغّل اللعبة
- تنقّل بين قائمة، خيارات، dialogue
- افحص الـ console لو يطبع stats كل 5 ثوانٍ
- افحص `dict/missing.txt` لرؤية النصوص التي تحتاج ترجمة

## التشخيص

| العَرَض | السبب الأرجح |
|------|------|
| لا يطبع شيئاً عند التشغيل | UE4SS غير محمَّل — تأكّد من dwmapi.dll في Win64 |
| `dict/translations.txt غير موجود` | شغّل "تحديث الترجمات" في Python أولاً |
| `hooks مُركَّبة: 0/6` | اللعبة تستخدم UFunctions مختلفة — شغّل explore.lua |
| نصوص لا تظهر بالعربية | الـ UFunction غير مهوَّك — أضِفه لـ HOOK_TARGETS |
| لاج محسوس | غيّر `log_replacements = false` لو كان true |
