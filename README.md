# 🎮 Game Arabic Translator

> أداة متكاملة لترجمة الألعاب إلى اللغة العربية باستخدام نماذج ذكاء اصطناعي متعددة

**الإصدار:** 1.0.0 | **الترخيص:** MIT | **المستودع:** [GitHub](https://github.com/nssr12/GameArabicTranslator.git)

---

## 📋 فهرس المحتويات

1. [نظرة عامة على المشروع](#1-نظرة-عامة-على-المشروع)
2. [بنية المشروع](#2-بنية-المشروع)
3. [الألعاب المدعومة](#3-الألعاب-المدعومة)
4. [محركات الترجمة](#4-محركات-الترجمة)
5. [نظام الكاش](#5-نظام-الكاش)
6. [معالجة النص العربي](#6-معالجة-النص-العربي)
7. [ملاحظات مهمة عن كل لعبة](#7-ملاحظات-مهمة-عن-كل-لعبة)
8. [واجهة المستخدم](#8-واجهة-المستخدم)
9. [المشاكل المعروفة والحلول](#9-المشاكل-المعروفة-والحلول)
10. [خطوات التطوير المستقبلية](#10-خطوات-التطوير-المستقبلية)
11. [الأوامر المفيدة](#11-الأوامر-المفيدة)

---

## 1. نظرة عامة على المشروع

**Game Arabic Translator** هي أداة سطح مكتب مبنية بـ Python لترجمة نصوص الألعاب الإنجليزية إلى اللغة العربية. تدعم الألعاب المبنية على محركي **Unity** و **Unreal Engine**، وتستخدم عدة نماذج ترجمة بالذكاء الاصطناعي.

### المميزات الرئيسية:
- 🌐 دعم **7 محركات ترجمة** مختلفة (HuggingFace MarianMT, mBART, NLLB-200, Google Free, Ollama, DeepL, Custom Endpoint)
- 🎮 دعم ألعاب متعددة مع ملفات إعداد لكل لعبة
- 💾 نظام **SQLite Cache** لتخزين الترجمات وإعادة استخدامها
- 🔤 معالجة متقدمة للنص العربي تشمل **Arabic Reshaping** و **BIDI Algorithm**
- 🪝 دعم **Frida Hook** للترجمة في الوقت الفعلي أثناء اللعب
- 🖥️ واجهة مستخدم رسومية بـ **tkinter** مع 6 ثيمات مختلفة
- 🔌 **Translation Server** محلي على البورت `5001` للألعاب التي تتطلب HTTP endpoint
- 🛡️ نظام **Token Protection** لحماية علامات التنسيق أثناء الترجمة

---

## 2. بنية المشروع

```
D:\GameArabicTranslator\
├── main.py                          # نقطة البداية - تشغيل الواجهة الرسومية
├── config.json                      # إعدادات التطبيق الرئيسية والمحركات
├── translation_server.py            # خادم ترجمة HTTP محلي (port 5001)
├── start.bat                        # سكريبت تشغيل سريع
├── requirements.txt                 # متطلبات Python
│
├── engine/                          # محرك الترجمة الأساسي
│   ├── translator.py                # TranslationEngine - إدارة المحركات والنماذج
│   ├── cache.py                     # TranslationCache - نظام SQLite Cache
│   ├── arabic_processor.py          # معالجة النص العربي (reshaping + BIDI)
│   ├── text_validator.py            # التحقق من صحة النصوص
│   └── models/                      # نماذج الترجمة
│       ├── base.py                  # BaseTranslator - الفئة الأساسية المجردة
│       ├── api_translator.py        # GoogleFreeTranslator, OllamaTranslator, CustomEndpointTranslator
│       ├── hf_translator.py         # HuggingFaceTranslator, MBartTranslator, NLLBTranslator
│       └── deepl_translator.py      # DeepLTranslator
│
├── games/                           # مترجمات الألعاب
│   ├── game_manager.py              # GameManager - إدارة إعدادات الألعاب
│   ├── configs/                     # ملفات JSON لإعدادات كل لعبة
│   │   ├── _template.json           # قالب لإضافة لعبة جديدة
│   │   ├── Risk_of_Rain_2.json
│   │   ├── Flotsam.json
│   │   ├── Manor Lords.json
│   │   └── Myth of Empires.json
│   ├── ror2/                        # مترجم Risk of Rain 2
│   │   └── translator.py            # RoR2Translator
│   ├── flotsam/                     # مترجم Flotsam
│   │   └── translator.py            # FlotsamTranslator
│   ├── manorlords/                  # مترجم Manor Lords
│   └── mythofempires/               # مترجم Myth of Empires
│       └── translator.py            # MythOfEmpiresTranslator
│
├── gui/                             # الواجهة الرسومية
│   ├── main_window.py               # MainWindow - الواجهة الرئيسية (2560 سطر)
│   └── theme.py                     # ThemeManager - إدارة الثيمات والألوان
│
├── hooking/                         # نظام الحقن (Frida)
│   ├── frida_manager.py             # FridaManager - إدارة Frida sessions
│   └── hooks/                       # سكريبتات Frida JavaScript
│
├── mods/                            # تعديلات الألعاب (BepInEx Plugins)
│   └── FlotsamArabicRuntime/        # BepInEx plugin لـ Flotsam
│       └── FlotsamArabicRuntime.cs  # C# plugin (1742 سطر)
│
├── UE4localizationsTool/            # أداة تعديل ملفات Unreal Engine
│   ├── UE4localizationsTool.exe     # أداة export/import ملفات .locres
│   └── Csv.dll                      # مكتبة CSV المساعدة
│
├── data/                            # بيانات التطبيق
│   ├── cache/                       # قاعدة بيانات SQLite
│   ├── translations/                # ملفات ترجمة محفوظة
│   ├── game_images/                 # صور الألعاب للواجهة
│   ├── manorlords_extracted/        # ملفات Manor Lords المستخرجة
│   └── ui_settings.json             # إعدادات الواجهة المحفوظة
│
└── assets/                          # موارد التطبيق (خطوط، صور)
```

---

## 3. الألعاب المدعومة

### 🌧️ Risk of Rain 2

| Property | Value |
|----------|-------|
| **المحرك** | Unity |
| **طريقة الترجمة** | File-based (JSON language files) |
| **الحقن** | Frida Hook (اختياري) |
| **صيغة الملفات** | `.json` في `StreamingAssets/Language/en/` |
| **الملفات المترجمة** | 37 ملف JSON (Achievements, Items, Main, etc.) |

**كيفية الاستخدام:**
1. حدد مسار اللعبة في الإعدادات (مثل `C:\Program Files (x86)\Steam\steamapps\common\Risk of Rain 2`)
2. اختر محرك الترجمة والنموذج من الواجهة
3. اضغط "Translate" - ستُقرأ ملفات `en/*.json` وتُترجم وتُحفظ في `ar/*.json`
4. اللعبة ستكتشف تلقائياً وجود مجلد `ar/` وتعرض اللغة العربية

**ملاحظة:** يتم حماية علامات التنسيق مثل `<style=...>`, `<color=...>`, `{0}` أثناء الترجمة عبر نظام Token Protection.

---

### 🚢 Flotsam

| Property | Value |
|----------|-------|
| **المحرك** | Unity + I2Languages |
| **طريقة الترجمة** | BepInEx Plugin (FlotsamArabicRuntime.dll) |
| **صيغة الملفات** | I2Languages JSON (`I2Languages-resources.assets-115691.json`) |
| **الإخراج** | `BepInEx/config/ArabicGameTranslator/flotsam_i2_translated_only.json` |

**كيفية الاستخدام:**
1. ثبت **BepInEx** في مجلد اللعبة
2. انسخ `FlotsamArabicRuntime.dll` إلى `BepInEx/plugins/`
3. استخدم الواجهة لترجمة ملفات I2Languages
4. شغّل اللعبة - سيقرأ الـ Plugin ملف الترجمة تلقائياً

**أنواع الـ Tokens المدعومة:**
- `{[TOKEN]}` - أقواس مربعة داخل أقواس
- `%TOKEN%` - نسبة مئوية
- `{[RWRD:...]}` - rewards مع معاملات
- HTML tags مثل `<b>`, `<i>`, `<color>`

**آلية حماية الـ Tokens في BepInEx Plugin:**
- `ApplyRTLfixPrefix` يستبدل الـ Tokens بـ Unicode control characters قبل معالجة RTLFixer
- `ApplyRTLfixPostfix` يستعيدها بعد المعالجة
- `SanitizeVisibleText` يصلح الـ Tokens المفسدة فقط عندما تكون اللغة العربية نشطة

---

### 🏰 Manor Lords

| Property | Value |
|----------|-------|
| **المحرك** | Unreal Engine |
| **طريقة الترجمة** | FLTAH's dxgi.dll + ZXSOSZXSubtitle.exe |
| **صيغة الملفات** | Custom hash-based subtitle files |
| **الخادم** | Translation Server على port 5001 |

**كيفية الاستخدام:**
1. استخدم أداة FLTAH لاستخراج ملفات الترجمة
2. ملفات الترجمة تستخدم **Presentation Forms** (U+FE70-U+FEFF) للحروف العربية
3. شغّل `translation_server.py` على port 5001
4. الأداة ترسل نصوص إنجليزية عبر HTTP GET إلى الخادم ويستلم النص العربي مع reshaping

**ملاحظة:** ملفات Subtitles تحتوي على أحرف عربية بصيغة **Presentation Forms** وليس Unicode عادي، مما يعني أن الحروف تُحفظ بالشكل الذي ستظهر به على الشاشة.

---

### ⚔️ Myth of Empires

| Property | Value |
|----------|-------|
| **المحرك** | Unreal Engine 4 |
| **طريقة الترجمة** | File-based (.locres) |
| **أداة التحويل** | UE4localizationsTool.exe |
| **صيغة الملفات** | `.locres` (custom UE4 binary) → `.txt` (Namespace::Key=Value) |

**كيفية الاستخدام:**
1. حدد مسار ملف `.locres` عبر File Browser في الواجهة (أو يُكتشف تلقائياً)
2. الأداة تستدعي `UE4localizationsTool.exe export` لتحويل `.locres` إلى `.txt`
3. يتم تحليل ملف `.txt` بصيغة `Namespace::Key=Value`
4. بعد الترجمة، يُكتب ملف `.txt` ويُستورد بـ `UE4localizationsTool.exe -import`
5. يُنشأ ملف `_NEW.locres` يُنسخ فوق الأصلي (مع نسخة احتياطية `.bak`)

**مسارات البحث عن ملفات locres:**
```
<game_path>/MOE/Content/  (البحث التلقائي)
<game_path>/               (بحث شامل)
```

---

## 4. محركات الترجمة

يوجد 7 محركات ترجمة مدعومة، تُدار من خلال `config.json` في قسم `models`:

### 4.1 Google Translate (Free)
```json
"google_free": {
    "type": "google_free",
    "description": "Google Translate (Free - no API key needed)",
    "enabled": true
}
```
- **النوع:** API مجاني بدون مفتاح
- **الاستخدام:** `https://translate.googleapis.com/translate_a/single`
- **المميزات:** سريع، لا يحتاج تسجيل
- **العيوب:** قد يُحظر عند الاستخدام المكثف

### 4.2 MarianMT (Helsinki-NLP)
```json
"marianmt": {
    "type": "huggingface",
    "name": "Helsinki-NLP/opus-mt-en-ar",
    "enabled": true
}
```
- **النوع:** HuggingFace Transformers محلي
- **الحجم:** ~300MB
- **المميزات:** سريع، خفيف، يعمل بدون إنترنت
- **الإعدادات:** `num_beams=4`, `max_length=512`
- **GPU:** يدعم CUDA تلقائياً إذا كان متاحاً

### 4.3 mBART-50
```json
"mbart": {
    "type": "huggingface",
    "name": "facebook/mbart-large-50-many-to-many-mmt",
    "enabled": false
}
```
- **النوع:** HuggingFace Transformers محلي
- **الحجم:** ~2.4GB
- **المميزات:** جودة عالية جداً، يدعم 50 لغة
- **ملاحظة:** أبطأ من MarianMT لكن دقيق أكثر

### 4.4 NLLB-200 (Meta)
```json
"nllb": {
    "type": "huggingface",
    "name": "facebook/nllb-200-distilled-600M",
    "enabled": false
}
```
- **النوع:** HuggingFace Transformers محلي
- **الحجم:** ~1.2GB (600M parameters)
- **المميزات:** نموذج Meta متعدد اللغات (200 لغة)
- **رموز اللغات:** `eng_Latn` → `arb_Arab`

### 4.5 Ollama (Local LLM)
```json
"ollama": {
    "type": "ollama",
    "model": "llama3",
    "url": "http://localhost:11434",
    "enabled": false
}
```
- **النوع:** Local LLM عبر Ollama API
- **المميزات:** خصوصية كاملة، يعمل بدون إنترنت
- **الإعدادات:** يمكن تغيير النموذج من الواجهة (llama3, mistral, etc.)
- **System Prompt:** `"You are a professional game text translator. Translate the following English text to Arabic. Reply ONLY with the Arabic translation, nothing else."`
- **Temperature:** 0.3 | **num_predict:** 200

### 4.6 DeepL
```json
"deepl": {
    "type": "deepl",
    "api_key": "YOUR_API_KEY",
    "tier": "free",
    "enabled": false
}
```
- **النوع:** DeepL API
- **الإصدار المجاني:** 500,000 شهرياً
- **URL:** Free: `https://api-free.deepl.com` | Pro: `https://api.deepl.com`
- **المميزات:** `tag_handling=html`, `preserve_formatting=1`

### 4.7 Custom Endpoint
```json
"custom_endpoint": {
    "type": "custom",
    "url": "http://localhost:5001/translate",
    "enabled": false
}
```
- **النوع:** HTTP POST endpoint مخصص
- **الطلب:** `{"text": "...", "source": "en", "target": "ar"}`
- **الاستجابة:** `{"translated": "..."}` أو `{"translation": "..."}` أو `{"text": "..."}`
- **الاستخدام:** يُستخدم مع `translation_server.py`

---

## 5. نظام الكاش

### البنية
يستخدم النظام قاعدة بيانات **SQLite** مخزنة في `data/cache/translations.db`.

### الجداول

#### `translations`
```sql
CREATE TABLE translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_name TEXT NOT NULL,          -- اسم اللعبة
    original_text TEXT NOT NULL,       -- النص الأصلي (إنجليزي)
    translated_text TEXT NOT NULL,     -- النص المترجم (عربي)
    model_used TEXT DEFAULT 'unknown', -- النموذج المستخدم
    created_at TIMESTAMP,              -- وقت الإنشاء
    updated_at TIMESTAMP,              -- آخر تحديث
    hit_count INTEGER DEFAULT 0,       -- عدد مرات الاستخدام
    UNIQUE(game_name, original_text)   -- فهرس فريد
);
```

#### `failed_translations`
```sql
CREATE TABLE failed_translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_name TEXT NOT NULL,
    original_text TEXT NOT NULL,
    reason TEXT DEFAULT '',
    created_at TIMESTAMP,
    UNIQUE(game_name, original_text)
);
```

### المميزات
- **Fuzzy Search:** البحث يدعم case-insensitive مع upper/lower
- **Pagination:** تصفح النتائج بصفحات (50 عنصر/صفحة)
- **Model Filter:** تصفية حسب النموذج المستخدم
- **Edit/Delete:** تعديل وحذف إدخالات محددة
- **Batch Operations:** حذف حسب اللعبة أو النموذج
- **Export/Import:** تصدير واستيراد ترجمات اللعبة
- **Sync from Game:** مزامنة الترجمات من Cache إلى ملفات اللعبة
- **Hit Count:** تتبع عدد مرات استخدام كل ترجمة
- **WAL Mode:** `PRAGMA journal_mode=WAL` لأداء أفضل
- **Thread-safe:** كل thread يستخدم connection خاص

### تطبيع النص العربي في Cache
```python
def _normalize_arabic(text):
    text = unicodedata.normalize('NFKC', text)
    text = text.replace('\u0640', '')     # إزالة الـ tatweel
    text = text.replace('\u0622', '\u0627') # آ → ا
    text = text.replace('\u0623', '\u0627') # أ → ا
    text = text.replace('\u0625', '\u0627') # إ → ا
    text = text.replace('\u0649', '\u064A') # ى → ي
```

---

## 6. معالجة النص العربي

### 6.1 Arabic Reshaping
المكتبات المستخدمة:
- **`arabic_reshaper`** - تحويل الحروف العربية إلى **Presentation Forms** (U+FE70-U+FEFF)
- **`python-bidi`** - معالجة **Bidirectional Text Algorithm** لعرض النص من اليمين لليسار

### 6.2 الدوال الرئيسية

#### `reshape_arabic(text)`
```python
def reshape_arabic(text):
    reshaped = arabic_reshaper.reshape(text)  # تحويل أشكال الحروف
    display = get_display(reshaped)            # تطبيق BIDI algorithm
    return display
```

#### `reshape_arabic_keep_tags(text)`
```python
def reshape_arabic_keep_tags(text):
    # 1. استبدال العلامات <...> و {...} بـ placeholders
    # 2. تطبيق reshaping على النص فقط
    # 3. استعادة العلامات
```

### 6.3 Token Protection أثناء الترجمة
كل مترجم يستخدم نظام حماية لمنع النماذج من ترجمة الـ Tokens:

| اللعبة | Regex Pattern | Placeholder |
|--------|--------------|-------------|
| Risk of Rain 2 | `<style=...>`, `<color=...>`, `{0}`, `{1:...}` | `__TAG_N__` |
| Flotsam | `%TOKEN%`, `{[TOKEN]}`, `{TOKEN}` | `__AGT_N__` |
| Myth of Empires | `{0}`, `{KEY}`, `%VAR%`, `<tag>` | `__AGT_N__` |

### 6.4 RTL Handling في المحركات المختلفة
- **Google Free:** لا يحتاج معالجة خاصة
- **HuggingFace models:** يُطبق reshaping بعد الترجمة
- **Ollama:** الـ system prompt يطلب الحفاظ على التنسيق
- **DeepL:** `tag_handling=html` يحافظ على HTML tags
- **Custom Endpoint:** يُطبق reshaping في `translation_server.py` عبر `apply_rtl_visual()`

---

## 7. ملاحظات مهمة عن كل لعبة

### 🌧️ Risk of Rain 2 (Unity)

#### هيكل الملفات
```
Risk of Rain 2_Data/
└── StreamingAssets/
    └── Language/
        ├── en/                    # ملفات اللغة الإنجليزية
        │   ├── language.json
        │   ├── Main.json          # {"strings": {"key": "value"}}
        │   ├── Items.json
        │   └── ... (37 ملف)
        └── ar/                    # ملفات اللغة العربية (تُنشأ تلقائياً)
            ├── language.json      # {"language": {"selfname": "العربية"}}
            ├── Main.json
            └── ...
```

#### نمط علامات التنسيق
```regex
<style=[^>]*>.*?</style>     # علامات style
<color=[^>]*>.*?</color>     # علامات color
<size=[^>]*>.*?</size>       # علامات size
\n, \r                       # أسطر جديدة
{0}, {1:format}              # format placeholders
```

#### Font Patching
- يمكن استبدال الخط الافتراضي بخط عربي (مثل `Aljazeera.ttf`)
- يُحدد عبر `font_path` في config.json

---

### 🚢 Flotsam (Unity + I2Languages)

#### نظام I2Languages
اللعبة تستخدم نظام **I2 Localization** لإدارة اللغات. ملفات الترجمة مخزنة في:
```
Flotsam_Data/
└── I2Languages-resources.assets-115691.json
```

الهيكل:
```json
{
    "mSource": {
        "mTerms": {
            "Array": [
                {
                    "Term": "term_name",
                    "Languages": {
                        "Array": ["English text", "French text", ...]
                    }
                }
            ]
        }
    }
}
```

#### BepInEx Plugin Architecture
الملف `FlotsamArabicRuntime.cs` (1742 سطر) يحتوي على:

1. **Token Protection عبر HarmonyX:**
   ```csharp
   // Hook ApplyRTLfix method في I2.Loc.LocalizationManager
   _harmony.Patch(applyRTLfixMethod,
       prefix: new HarmonyMethod(typeof(FlotsamArabicRuntime), "ApplyRTLfixPrefix"),
       postfix: new HarmonyMethod(typeof(FlotsamArabicRuntime), "ApplyRTLfixPostfix"));
   ```

2. **Arabic Font Fallback:**
   ```csharp
   // إنشاء TMP_FontAsset dinamically من خطوط النظام
   _osArabicFont = Font.CreateDynamicFontFromOSFont(
       new[] { "Tahoma", "Arial", "Segoe UI" }, 36);
   _arabicTmpFallback = CreateDynamicTmpFontAsset(_osArabicFont);
   ```

3. **Text Sanitization:**
   ```csharp
   // SanitizeVisibleText يصلح الـ Tokens المفسدة
   if (IsArabicLanguageActive()) {
       return FixCorruptedTokens(value);  // فقط إصلاح، لا يحذف HTML tags
   }
   // إذا لم تكن العربية نشطة: يحذف HTML tags و Tokens المفسدة
   ```

#### ⚠️ مشاكل معروفة في Flotsam

**مشكلة 1: `ref` parameter في HarmonyX**
```
الـ `ref line` parameter في HarmonyX prefix لا ينقل التعديلات إلى الدالة الأصلية.
الحل: استخدام prefix لتخزين الحالة في static field، واستخدام postfix لتعديل __result.
```

**مشكلة 2: ApplyRTLfix يفسد `{[TOKEN]}`
```
دالة RTLFixer.Fix() في I2Languages تعكس أحرف الـ Tokens:
{[RWRD:Gold]} ← يصبح → }]dlO[:DWRW{[
الحل: ApplyRTLfixPrefix يستبدل Tokens بـ control chars قبل المعالجة.
```

**مشكلة 3: SanitizeVisibleText يجب ألا يحذف HTML tags مع العربية**
```
عندما تكون اللغة العربية نشطة، يجب عدم حذف HTML tags لأن النص يحتاجها.
الحل: IsArabicLanguageActive() check في بداية الدالة.
```

**مشكلة 4: isRightToLeftText وحده لا يكفي**
```
isRightToLeftText() في I2Languages لا يُطبق Presentation Forms.
ApplyRTLfix هو من يُطبق arabic_reshaper على النص.
لذلك يجب hook ApplyRTLfix وليس isRightToLeftText.
```

---

### 🏰 Manor Lords (Unreal Engine)

#### طريقة العمل
1. يستخدم أداة **FLTAH** مع `dxgi.dll` و `ZXSOSZXSubtitle.exe`
2. ملفات الترجمة تستخدم **Custom Hash System** لتحديد النصوص
3. النص العربي يُخزن بصيغة **Presentation Forms** (U+FE70-U+FEFF)

#### Translation Server
```python
# translation_server.py - يعمل على port 5001
# يتلقى طلبات GET: /health و /?text=...
# يترجم النص ويُطبق arabic_reshaper
# يُعيد النص مع <align="right"> prefix
```

---

### ⚔️ Myth of Empires (Unreal Engine 4)

#### صيغة .locres
ملف `.locres` هو صيغة **Unreal Engine 4** المخصصة للترجمة:
```
# صيغة ملف .txt بعد التصدير:
Namespace::Key=Value
MoeGame::UI_OK=OK
MoeGame::UI_CANCEL=Cancel
MoeGame::ItemName_Sword=Sword
```

#### UE4localizationsTool
```
# تصدير:
UE4localizationsTool.exe export <file.locres>
# يُنشئ: <file.locres.txt>

# استيراد:
UE4localizationsTool.exe -import <file.locres.txt>
# يُنشئ: <file_NEW.locres>
```

#### File Browser
- يمكن تحديد ملف `.locres` يدوياً عبر File Browser
- يُحفظ المسار في config.json كـ `locres_path`
- البحث التلقائي يبحث في `<game_path>/MOE/Content/`

---

## 8. واجهة المستخدم

### التقنيات
- **Framework:** tkinter (Python built-in)
- **الحجم:** 1200x750 (minimum: 900x600)
- **الخطوط:** Segoe UI (default), مع دعم 8 خطوط

### الثيمات المتوفرة
| الثيم | الألوان الرئيسية |
|-------|-----------------|
| **Dark** | `#1a1a2e` BG, `#e94560` Accent |
| **Light** | `#f0f0f5` BG, `#e94560` Accent |
| **Sunset** | `#1a0a1e` BG, `#ff6b35` Accent |
| **Ocean** | `#0a1628` BG, `#00bbff` Accent |
| **Forest** | `#0a1a0e` BG, `#44cc66` Accent |
| **Purple** | `#12082a` BG, `#bb44ff` Accent |

### صفحات التنقل (Sidebar)
1. **🏠 Home** - الصفحة الرئيسية مع إحصائيات سريعة
2. **🎮 Games** - قائمة الألعاب المدعومة مع إعداداتها
3. **🌐 Translate** - صفحة الترجمة مع اختيار النموذج والمود
4. **💾 Cache** - عرض وإدارة Cache مع البحث والتصفية
5. **⚙️ Settings** - إعدادات التطبيق والثيمات

### صفحة الترجمة
- اختيار النموذج من Combobox
- 3 أوضاع ترجمة:
  - **Fresh:** حذف القديم + ترجمة جديدة
  - **Cache Only:** استخدام Cache فقط بدون API calls
  - **Missing:** ترجمة النصوص الجديدة فقط
- Progress bar مع إحصائيات (New/Cached/Failed)
- Log viewer مع سجل العمليات

### صفحة Cache
- **Combobox:** تصفية حسب اللعبة و النموذج
- **Search:** بحث في النصوص الأصلية والمترجمة
- **Pagination:** أزرار Prev/Next للتنقل بين الصفحات
- **Reshape Toggle:** خيار "Show Raw Arabic" لعرض النص بدون reshaping
- **Actions:** Edit/Delete لكل إدخال
- **Delete ALL:** حذف جميع الترجمات

### مميزات إضافية
- **Copy/Paste:** Ctrl+C, Ctrl+V, Ctrl+X, Ctrl+A
- **Mouse Wheel:** تدعم التمرير بالماوس
- **Status Bar:** شريط حالة في الأسفل

---

## 9. المشاكل المعروفة والحلول

### ❌ مشكلة: HarmonyX `ref` parameter لا ينقل التعديلات
**الوصف:** عند استخدام HarmonyX prefix مع `ref` parameter، التعديلات على المتغير لا تصل إلى الدالة الأصلية.

**الحل:** استخدام نمط Prefix + Postfix:
```csharp
// Prefix: تخزين الحالة في static field
static bool ApplyRTLfixPrefix(ref string line) {
    _rtlProtectedTokens = ExtractTokens(line);
    line = ReplaceTokensWithPlaceholders(line);
    return true; // استمرار الدالة الأصلية
}

// Postfix: تعديل النتيجة
static void ApplyRTLfixPostfix(ref string __result) {
    __result = RestoreTokens(__result, _rtlProtectedTokens);
}
```

### ❌ مشكلة: RTLFixer يفسد أنماط `{[TOKEN]}`
**الوصف:** دالة `RTLFixer.Fix()` في I2Languages تعكس أحرف Tokens مثل `{[RWRD:Gold]}` إلى `}dlO[:DWRW{[`.

**الحل:** استبدال Tokens بـ Unicode control characters (`\u0003`) قبل RTLFixer واستعادتها بعده.

### ❌ مشكلة: عرض النص العربي RTL
**الوصف:** بعض محركات العرض لا تدعم RTL بشكل صحيح.

**الحلول:**
- استخدام `arabic_reshaper` + `python-bidi` لتحويل النص إلى Presentation Forms
- إضافة `<align="right">` prefix (في translation_server.py)
- استخدام BepInEx plugin مع Arabic Font Fallback

### ❌ مشكلة: Presentation Forms vs Normal Arabic
**الوصف:** بعض الألعاب (مثل Manor Lords) تتوقع Presentation Forms (U+FE70-U+FEFF) بينما أخرى تتوقع Unicode عادي.

**الحل:** تحديد نوع المعالجة حسب اللعبة:
- **Manor Lords:** `arabic_reshaper.reshape()` فقط (بدون BIDI)
- **Flotsam:** `FixCorruptedTokens()` لإصلاح Tokens المفسدة
- **Risk of Rain 2:** `reshape_arabic_keep_tags()` مع حماية العلامات

### ❌ مشكلة: Cache يعرض Arabic Reshaped بدل Raw Arabic
**الوصف:** النصوص المخزنة في Cache قد تكون بصيغة reshaped (presentation forms).

**الحل:** خيار "Show Raw Arabic" toggle في صفحة Cache يتحكم في العرض.

---

## 10. خطوات التطوير المستقبلية

- [ ] إضافة دعم ألعاب Unreal Engine 5 (UE5)
- [ ] تحسين ملف `.locres` parser بدون الحاجة لأداة خارجية
- [ ] إضافة Frida hooks للألعاب الأكثر شيوعاً
- [ ] دعم ترجمة ملفات `.pak` مباشرة
- [ ] إضافة Batch translation مع threading متعدد
- [ ] تحسين Arabic text shaping مع دعم HarfBuzz
- [ ] إضافة Translation Memory مشتركة بين الألعاب
- [ ] دعم تصدير الترجمات إلى صيغ `.po` و `.xliff`
- [ ] إضافة اختبارات تلقائية (Unit Tests)
- [ ] دعم RTL preview مباشر في الواجهة
- [ ] إضافة Dark Web mode للترجمة عبر Tor

---

## 11. الأوامر المفيدة

### تشغيل التطبيق
```bash
# الطريقة 1: عبر start.bat
start.bat

# الطريقة 2: عبر Python مباشرة
python main.py

# الطريقة 3: مع مسار محدد
cd D:\GameArabicTranslator
python main.py
```

### تثبيت المتطلبات
```bash
pip install -r requirements.txt
```

### تشغيل Translation Server (لـ Manor Lords)
```bash
python translation_server.py
# يعمل على http://127.0.0.1:5001
# Health check: http://127.0.0.1:5001/health
# Translation: http://127.0.0.1:5001/?text=Hello
```

### بناء FlotsamArabicRuntime.dll
```bash
# المتطلبات:
# - .NET SDK 6.0+
# - BepInEx 5.x (Unity Mono)
# - Unity 2019.4+ assemblies (UnityEngine.dll, etc.)
# - HarmonyX
# - Newtonsoft.Json
# - TextMeshPro

# بناء عبر dotnet CLI:
cd mods/FlotsamArabicRuntime
dotnet build -c Release

# أو عبر Visual Studio:
# افتح FlotsamArabicRuntime.csproj → Build → Release
```

### استخدام UE4localizationsTool
```bash
# تصدير ملف .locres إلى .txt
UE4localizationsTool.exe export "path/to/file.locres"

# استيراد ملف .txt إلى .locres
UE4localizationsTool.exe -import "path/to/file.locres.txt"
# يُنشئ: file_NEW.locres
```

### إضافة لعبة جديدة
1. أنشئ ملف JSON في `games/configs/` باستخدام `_template.json` كقالب
2. أنشئ مجلد في `games/<game_name>/` مع `translator.py`
3. أضف handler في `gui/main_window.py` في دالة `run_translation()`
4. حدّث `config.json` إذا لزم الأمر

---

## المتطلبات

| المكتبة | الإصدار | الاستخدام |
|---------|---------|-----------|
| `transformers` | ≥4.35.0 | HuggingFace models |
| `torch` | ≥2.0.0 | GPU inference |
| `sentencepiece` | ≥0.1.99 | Tokenization |
| `sacremoses` | ≥0.1.1 | Preprocessing |
| `frida-tools` | ≥12.0.0 | Runtime hooking |
| `frida` | ≥16.0.0 | Runtime hooking |
| `psutil` | ≥5.9.0 | Process management |
| `requests` | ≥2.31.0 | HTTP API calls |
| `chardet` | ≥5.0.0 | Encoding detection |
| `arabic-reshaper` | ≥3.0.0 | Arabic text shaping |
| `python-bidi` | ≥0.4.2 | BIDI algorithm |
| `UnityPy` | ≥1.20.0 | Unity asset parsing |
| `Pillow` | ≥10.0.0 | Image processing |

---

<div dir="rtl">

**تم التطوير بواسطة:** [nssr12](https://github.com/nssr12) | **آخر تحديث:** مايو 2026

</div>
