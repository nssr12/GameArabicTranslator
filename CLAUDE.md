# CLAUDE.md

> ملف سياق المشروع لـ Claude / AI assistants.
> للمستخدمين النهائيين، انظر [README.md](README.md).
> آخر تحديث: 2026-06-01 (v2.3 — استقرار Ollama + جودة الترجمة + تقليل تكرار الكاش)

## TL;DR

Game Arabic Translator v2.3 — تطبيق Python/**PySide6** لترجمة ألعاب Unity/UE5 إلى العربية. يستخدم:

> ⚠ **ملاحظة framework**: الكود يستورد فعلياً من `PySide6` (لا PyQt6). استخدم `Signal`/`Slot`/`@Property` (لا `pyqtSignal`/`pyqtSlot`/`pyqtProperty`) في أي كود Qt جديد.

- **بروكسي HTTP محلي** (port 5001) — يستقبل من XUnity Auto-Translator (Unity) أو من unreal_hook_watcher (UE5)
- **محرّكات متعدّدة** (Ollama, Google, DeepL, HuggingFace MarianMT/mBART/NLLB)
- **SQLite cache** لكل لعبة (schema v2): `UNIQUE(original_text, model_used)` + جدول `failed_translations`
- **BepInEx mods C#** لمعالجة العرض RTL + sprite assets داخل اللعبة (Unity)
- **Unreal Hook DLL injection** (cppfs + dxgi hijack) لـ UE5 — Manor Lords, Palworld
- **فلتر تاقات عام** (config.json::tag_mode) موحَّد عبر البروكسي، الكاش، والترجمة الفورية

## أوامر سريعة

```bash
# التشغيل
"d:\GameArabicTranslator\start - main_qt.py.bat"   # GUI الرئيسية

# بناء الـ mods C# (تحتاج .NET SDK)
cd mods/ArabicFontFixer && dotnet build -c Release \
  -p:GAME_MANAGED="C:\Program Files (x86)\Steam\steamapps\common\Flotsam\Flotsam_Data\Managed" \
  -p:BEPINEX_CORE="D:\GameArabicTranslator\mods\_bepinex_base\BepInEx\core"

cd mods/FlotsamArabicRuntime && dotnet build -c Release

# فحص syntax بايثون
C:/Python314/python -c "import ast; ast.parse(open('PATH.py', encoding='utf-8').read())"
```

## بنية المشروع

```
d:\GameArabicTranslator\
├── main_qt.py                     ← نقطة الدخول لـ PySide6
├── config.json                    ← models + ollama_options + system_prompt + tag_mode (عام)
├── engine/
│   ├── proxy_server.py            ← البروكسي HTTP (port 5001) — قلب التطبيق
│   ├── cache.py                   ← TranslationCache (SQLite per-game, schema v2)
│   ├── translator.py              ← TranslationEngine (يدير المترجمات)
│   ├── tag_filter.py              ← Tiered + Bulletproof tag protection
│   ├── tag_validator.py           ← التحقّق من علامات ⟦N⟧
│   ├── tag_config.py              ← تحرير قائمة التاقات (data/tag_config.json) + add_tags()
│   ├── tag_discovery.py           ← ⭐ جديد — استخراج XML tags من نصوص
│   ├── tag_health.py              ← ⭐ جديد — is_broken_translation() كاشف الترجمات المعطوبة
│   ├── filtered_translator.py     ← ⭐ جديد — FilteredTranslator + global tag_mode helpers
│   ├── i2_translator.py           ← ⭐ I2BatchTranslator — ترجمة دفعية لملفات I2Languages JSON (UABEA)
│   ├── number_template.py         ← ⭐ v2.3 — تقويلب الأرقام ({0}{1}) لتقليل تكرار الكاش
│   ├── arabic_shaper.py           ← تشكيل عربي + عكس بصري RTL لـ TMP (يحفظ tags/placeholders)
│   ├── arabic_processor.py        ← reshape_arabic() — تشكيل مع حماية tokens (tags/{0}/%s/|icon|)
│   ├── skip_patterns.py           ← قائمة المنع (data/skip_patterns.json)
│   ├── static_translations.py     ← قارئ translations.txt اليدوي (الأولوية القصوى)
│   └── models/
│       └── api_translator.py      ← OllamaTranslator + GoogleFree + Custom
├── games/
│   ├── game_manager.py
│   ├── bepinex_mod.py             ← Unity: تثبيت/إلغاء + export translations.txt
│   ├── unreal_hook_mod.py         ← UE5 (DLL injection): تثبيت DLLs + export <hash>.subtitle.txt
│   ├── ue4ss_mod.py               ← UE4SS Arabic Translator mod (dict/translations.txt + mods.txt) — مسار UE بديل
│   ├── configs/<GameName>.json    ← إعداد كل لعبة (path, hook_mode, …) — tag_mode أُزيل (عام الآن)
│   └── iostore/                   ← UE5 IoStore (Grounded2)
├── gui/qt/
│   ├── app.py
│   ├── pages/
│   │   ├── games.py               ← صفحة الألعاب + GameDetail + LogPanel (3000+ سطر)
│   │   ├── cache.py               ← صفحة الكاش + EditDialog + اكتشاف التاقات + exact-match
│   │   ├── settings.py            ← شريط تبويبات (عام + Ollama)
│   │   ├── ollama_settings.py     ← تبويب Ollama + مراقبة موارد CPU/GPU/VRAM
│   │   ├── models.py              ← AI Models + SystemPromptEditor + tag_mode combo (عام)
│   │   ├── translate.py           ← الترجمة الفورية — يقرأ tag_mode من config العام
│   │   ├── i2_translate.py        ← صفحة ترجمة I2Languages JSON (تحليل + دفعي + حفظ Arabic-only)
│   │   └── unrealpak.py           ← صفحة فك/حزم ملفات .pak (UnrealPak.exe)
│   └── dialogs/
│       ├── admin_panel.py            ← لوحة إدارة محمية بـ PIN (إخفاء/إظهار أقسام الواجهة)
│       ├── tag_config_dialog.py
│       ├── tag_discovery_dialog.py   ← ⭐ جديد — اكتشاف XML tags من نصوص الكاش
│       ├── tag_mode_confirm_dialog.py ← ⚠ مهجور — لم يعد يُستدعى (الفلتر عام الآن)
│       ├── skip_list_dialog.py
│       ├── locres_wizard.py
│       ├── iostore_wizard.py
│       └── font_wizard.py
├── tools/
│   ├── launch_unreal_game.py      ← suspended-launch + inject (تشغيل من التطبيق)
│   ├── steam_inject_wrap.py       ← ⭐ جديد — Steam Launch Options wrapper
│   ├── toggle_unreal_hook.py      ← ⭐ جديد — تعطيل/تفعيل DLLs (للأونلاين)
│   ├── unreal_hook_watcher.py     ← يراقب Translate/ ويترجم النصوص الجديدة عبر البروكسي
│   ├── inject_unreal_hook.py      ← CreateRemoteThread + LoadLibrary injector
│   └── clean_broken_tag_translations.py ← ⭐ جديد — حذف ترجمات معطوبة من الكاش
└── mods/
    ├── _bepinex_base/             ← BepInEx + XUnity + ArabicFontFixer (مشترك بين الألعاب)
    ├── ArabicFontFixer/           ← C# عام (تثبيت ترجمات translations.txt + queue للـ proxy)
    ├── FlotsamArabicRuntime/      ← C# خاص بـ Flotsam (RTL + sprite handling + I2)
    ├── Flotsam/                   ← FlotsamArabicRuntime.dll للتوزيع
    ├── Grounded2/                 ← package.json (IoStore mod)
    └── Windrose/                  ← package.json (UE5 mod)
```

## السلوكيات الأساسية (Critical)

### 1. ترتيب البحث عن الترجمة في `engine/proxy_server.py::_translate()`

```
1. translations.txt        ← مصدر يدوي (Highest priority — يتجاوزه "بدون كاش" فقط)
2. skip_patterns           ← قائمة المنع (Nexa*, *SDF, ...)
3. is_failed (SQLite)      ← لا تُعِد محاولة نص سبق وفشل (يتجاوزه "بدون كاش")
4. SQLite cache            ← ترجمات AI سابقة (يتجاوزه "بدون كاش")
5. AI (Ollama/Google/...)  ← دائماً (آخر مرحلة)
```

**`cache_model_filter`**:
- `""` → كل النماذج (افتراضي)
- `"<model_name>"` → فقط ترجمات هذا النموذج تُسترجَع من cache
- `"none"` → **يتجاوز كل شيء** (translations.txt + skip + is_failed + cache) → AI مباشرة

### 2. Timeout ديناميكي حسب طول النص

في `_effective_timeout_for(text)` ([engine/proxy_server.py](engine/proxy_server.py)):

| طول النص | المضاعف | مع base=60ث |
|------|------|------|
| ≤ 500 | 1.0 | 60 |
| ≤ 1500 | 1.5 | 90 |
| ≤ 3000 | 2.5 | 150 |
| > 3000 | 4.0 | 240 |

يُطبَّق على `self._engine._timeout` قبل كل استدعاء AI، يُستعاد في `finally`.

### 3. Cascade fallback في Bulletproof mode

داخل `_translate_with_bulletproof()` → `_do_bulletproof_cascade()`:
1. جرّب `bulletproof` (⟦N⟧/⟦/N⟧/⟦sN⟧) — الأقوى
2. عند الفشل: جرّب `tiered` ([tN]/[sN]) — أقل صرامة
3. عند الفشل: جرّب `strip` (PUA U+E000+) — آخر محاولة
4. عند الفشل النهائي → `None` → يُسجَّل في `failed_translations`

كل محاولة تأخذ `original_timeout / 3` كحد أدنى 25ث.

### 4. مفتاح النموذج ≠ اسم النموذج

`engine.get_active_model()` يُرجع **المفتاح** (مثل `"ollama"`).
الاسم الفعلي (`"qwen2.5:14b"`) موجود في `translator.model`.

الـ helper `_resolve_model_name()` في proxy_server يفصل بينهما:
```python
key = self._engine.get_active_model()       # "ollama"
tr  = self._engine.get_translator(key)
actual = getattr(tr, "model", None)         # "qwen2.5:14b"
return actual or key
```

استخدم دائماً `actual` عند الحفظ في `cache.put(...)` أو `cache.mark_failed(...)`.

### 5. `_last_error` على المترجم النشط لا على الـ wrapper

`TranslationEngine` (wrapper) ليس عنده `_last_error`. الـ attribute موجود على `OllamaTranslator`.

```python
# خطأ:
err = self._engine._last_error

# صحيح:
key = self._engine.get_active_model()
tr  = self._engine.get_translator(key)
err = getattr(tr, "_last_error", "") if tr else ""
```

## الأنماط المتّبعة (Conventions)

### اللغة في كل الردود

المستخدم عربي — كل ردود AI **بالعربية**. الكود الإنجليزي، التعليقات بالعربي في الكود السورس.

### المسارات (Windows)

- استخدم `os.path.join()` لتجنب مشاكل forward/back slash
- المسار الرئيسي: `d:\GameArabicTranslator\`
- مسار اللعبة في config: `"game_path": "C:/Program Files (x86)/Steam/..."`

### QDialog Flags

```python
# ✅ صحيح — يحافظ على X وأزرار النافذة الافتراضية
self.setWindowFlags(
    self.windowFlags()
    | Qt.Window
    | Qt.WindowMinMaxButtonsHint
    | Qt.WindowCloseButtonHint
)

# ❌ خطأ — يلغي زر X
self.setWindowFlags(Qt.Window | Qt.WindowMinMaxButtonsHint)
```

### Stretch في Layouts

أضِف `stretch=1` للحاويات التي تجب أن تتمدّد مع النافذة:
```python
root.addWidget(preview_section, 3)   # الأكبر
root.addWidget(list_section, 1)      # متوسط
text_edit.setMinimumHeight(110)      # حدّ أدنى مريح بلا setMaximumHeight
```

### Tag protection levels

| الوضع | علامات | البقاء مع المودل | الاستخدام |
|------|------|------|------|
| `inline` | لا يحمي شيئاً | الكل | للمودلات الذكية |
| `strip` | يستبدل بـ PUA (U+E000+) | لا شيء | للمودلات الصغيرة |
| `tiered` | `[tN]/[sN]` ASCII | لا شيء | متوسط |
| `bulletproof` | `⟦N⟧/⟦/N⟧/⟦sN⟧` Unicode | لا شيء | **افتراضي** — الأقوى مع cascade |

## ⭐ ترجمة Unity الفورية — المعمارية الكاملة

هذا القسم يوثّق التدفّق الكامل من اللعبة → الترجمة → العرض، مع كل التعديلات النهائية.

### المكوّنات والمسؤوليات

| المكوّن | اللغة | الموقع | الدور |
|------|------|------|------|
| **BepInEx 5.x** | C# | `<game>/BepInEx/core/` | Runtime mod loader + Doorstop hook |
| **XUnity AutoTranslator** | C# | `<game>/BepInEx/plugins/XUnity.*` | يعترض TMP setter → يرسل لـ proxy |
| **XUnity ResourceRedirector** | C# | `<game>/BepInEx/plugins/XUnity.ResourceRedirector` | يساعد في hook الموارد |
| **ArabicFontFixer.dll** | C# | `<game>/BepInEx/plugins/` | translations.txt + Arabic font fallback + queue للـ proxy |
| **FlotsamArabicRuntime.dll** | C# | `<game>/BepInEx/plugins/` (Flotsam فقط) | RTL + sprite handling + I2 hooks |
| **Python proxy** | Python | `engine/proxy_server.py` | HTTP server على port 5001 |
| **Ollama** | Native | `localhost:11434` | LLM للترجمة الفعلية |

### التدفّق الزمني الكامل

```
1. اللعبة (Unity TMP_Text):
   setter.text = "Long English help text..."
                   │
                   ▼
2. ArabicFontFixer prefix hook:
   ├─ هل النص في _staticTr (محمَّل من translations.txt)؟
   │   ├─ ✅ نعم → استبدل بالعربي → ضعه في setter → END
   │   └─ ❌ لا → ضعه في _pendingSet → ابدأ worker thread
   └─ مرّر النص كما هو للـ hooks التالية
                   │
                   ▼
3. FlotsamArabicRuntime prefix (Flotsam فقط):
   ├─ إذا اللغة عربية: FixCorruptedTokens (إصلاح {[X]} مكسورة)
   └─ مرّر للـ setter النهائي
                   │
                   ▼
4. XUnity AutoTranslator prefix:
   └─ يرسل GET /?text=... للـ proxy (HttpWebRequest, Timeout=5000ms)
                   │
                   ▼
5. Python proxy._translate(text):
   ├─ Level 1: في translations.txt → عربي فوراً (50ms)
   ├─ Level 2: في skip_patterns → الإنجليزي + unchanged
   ├─ Level 3: في failed_translations → الإنجليزي + unchanged
   ├─ Level 4: في SQLite cache → عربي فوراً (50ms)
   │
   ├─ نص قصير (< 200 حرف): AI sync مع timeout 60-90 ث
   │   └─ نتيجة → cache.put() + ردّ بالعربي
   │
   └─ نص طويل (≥ 200 حرف): ASYNC ⭐
       ├─ _bg_queue.put(text) (50ms)
       ├─ ردّ بالنص الإنجليزي + unchanged=True
       └─ _bg_worker_loop يأخذ من queue ويترجم بالخلفية
           └─ نتيجة → cache.put() (للطلب التالي)
                   │
                   ▼
6. ArabicFontFixer's worker thread (parallel):
   ├─ تابع: HttpWebRequest يستلم الردّ
   ├─ لو الردّ != الأصل → خزّن في _staticTr
   └─ ApplyLoop يطبّق على كل TMP_Text فيها هذا النص
                   │
                   ▼
7. TMP يعرض النص النهائي مع:
   ├─ Arabic font fallback (لو مطلوب)
   ├─ isRightToLeftText = true (لو عربي)
   └─ ApplyArabicLayout (يقلب TextAlignment)
```

### ⭐ Async Background Translation — السبب والحل

**المشكلة الجذرية**:
- XUnity / ArabicFontFixer يستخدمان `HttpWebRequest.Timeout = 5000ms`
- Ollama على نص 500+ حرف يحتاج 30-240 ثانية
- العميل يفترض الخادم ميت → يدخل حالة معطّلة
- اللعبة تتطلّب **إعادة تشغيل** (لا يكفي إيقاف/تشغيل البروكسي)

**الحل**: في [engine/proxy_server.py:744-822](engine/proxy_server.py#L744-L822):

```
طلب نص طويل (≥ 200 حرف)
   │
   ├─ proxy يضيفه لـ _bg_queue
   ├─ proxy يردّ بالنص الإنجليزي فوراً (< 50ms)
   ├─ العميل سعيد، اللعبة تواصل بدون تعليق
   │
   └─ في الخلفية:
       _bg_worker thread يأخذ نصاً من queue
       ├─ يستدعي AI (90-240 ث، لا أحد ينتظر)
       ├─ يحفظ في cache
       └─ الطلب التالي لنفس النص → cache hit
```

**النتيجة**:
- اللعبة لا تتجمّد أبداً مهما طال نص AI
- إيقاف/تشغيل البروكسي يعمل بلا حاجة لإعادة اللعبة
- شاشات المساعدة الطويلة تظهر بالإنجليزي أول مرة، عربي عند إعادة فتح الشاشة
- النصوص القصيرة (أزرار، tooltips) ما زالت sync (تجربة فورية)

### مفاتيح الإعداد

| الإعداد | القيمة | الموقع |
|------|------|------|
| `_async_threshold_chars` | 200 حرف | `ProxyServer.__init__` |
| `_bg_max_queue_size` | 500 | `ProxyServer.__init__` |
| `idle_timeout` (worker exit) | 30 ث | `_bg_worker_loop` |
| HttpWebRequest.Timeout | 5000ms | ArabicFontFixer (لا يحتاج زيادة بعد async) |
| Ollama keep_alive | "30m" | `config.json["ollama_options"]` |
| Cascade per-attempt | 25/45/75/120 ث | حسب طول النص |

### XUnity AutoTranslatorConfig.ini المطلوب

```ini
[Service]
Endpoint=CustomTranslate

[General]
Language=ar
FromLanguage=en
EnableIMGUI=False
EnableUGUI=True
EnableNGUI=True
EnableTextMesh=True
EnableTextMeshPro=True
MaxCharactersPerTranslation=5000      # ← مهم! الافتراضي 150 يتخطّى النصوص الطويلة
IgnoreWhitespaceInTranslations=True

[CustomTranslate]
Url=http://127.0.0.1:5001/
```

### قاعدة sprite assets الحرجة

عند استبدال `text.font = _arabicTmpFallback`:
- ✅ شغّال: نص عربي + `<b>` + `<color>` (تعليمات تنسيق نقية)
- ❌ ينكسر: `<sprite="GameSpecificAsset" name="X">` — الخط الجديد لا يعرف هذا الـ asset → TMP يعرض التاق كنص حرفي → BiDi يقلبه بصرياً

**الإصلاح** في FlotsamArabicRuntime: `HasCustomSpriteAsset(text)` يكتشف هذه التاقات ويُبقي الخط الأصلي للعبة. الـ Arabic fallback يكون عبر `fallbackFontAssetTable` (مُضاف للخط الأصلي عند بدء المود).

### Hooks الـ C# المركّبة لنفس TMP setter

ثلاثة mods تضع prefix على `TMP_Text.text`:

```
text setter في Unity
   ├─ Harmony prefix #1: ArabicFontFixer.TMP_SetText_Prefix
   │   └─ value = Translate(value)   # static lookup + queue
   ├─ Harmony prefix #2: FlotsamArabicRuntime.SanitizeTextSetterPrefix
   │   └─ يصلح tokens مكسورة
   ├─ Harmony prefix #3: XUnity AutoTranslator (داخلي)
   │   └─ يرسل للـ proxy
   └─ setter الأصلي ينفّذ
```

**ترتيب الـ prefixes غير مضمون** بين mods منفصلة. لذا كل واحد يجب أن يكون **idempotent** (تطبيقه مرتين لا يضرّ).

### نقاط timeout الحرجة

| المكوّن | timeout | الملاحظة |
|------|------|------|
| `HttpWebRequest.Timeout` | 5000ms | ✅ مع async، لا يهمّ بعد الآن |
| `HttpWebRequest.ReadWriteTimeout` | default 300000ms | كافٍ |
| Python proxy `_timeout` | 60 ث base | ديناميكي حسب الطول |
| Ollama `keep_alive` | "30m" | يمنع تفريغ المودل بين الطلبات |
| `_bg_worker idle_timeout` | 30 ث | يخرج لو لا عمل، يُحيا عند طلب |

### تشخيص سريع عند مشاكل الترجمة

| العَرَض | السبب الأرجح | الفحص |
|------|------|------|
| لا تظهر ترجمات | XUnity غير محمَّل | `BepInEx/LogOutput.log` يحوي `Loading [XUnity Auto Translator]` |
| نصوص قصيرة تظهر عربي، طويلة إنجليزي | Async يعمل + cache لا يحوي الطويلة بعد | انتظر دقيقة + أعد فتح الشاشة |
| اللعبة تعلّق على نص طويل | (قبل async) — يجب أن لا يحدث الآن | تحقّق من `_async_threshold_chars=200` |
| نص الـ sprite تاق يظهر بدل الصورة | الخط استُبدِل وفقد sprite asset | تحقّق من `HasCustomSpriteAsset` في FlotsamArabicRuntime |
| الإيقاف/التشغيل في GUI لا يُصلح | (قبل non-blocking stop) — يجب يعمل الآن | `stop()` يجب يأخذ < 1ms |
| الخادم يطلب إعادة تشغيل اللعبة | (قبل async + session reset) — يجب لا يحدث | تأكّد من v25 changes في proxy_server.py |

## ⭐ نظام I2 الدفعي (Batch I2Languages Translation)

مسار **منفصل عن الترجمة الفورية** لترجمة ملفات `I2Languages` كاملةً قبل تشغيل اللعبة (بدل الاعتماد على البروكسي وقت اللعب). مفيد لألعاب Unity التي تخزّن كل نصوصها في asset واحد عبر I2.Localization.

### المكوّنات الثلاثة

| المكوّن | اللغة | الدور |
|------|------|------|
| **engine/i2_translator.py** (`I2BatchTranslator`) | Python | يقرأ JSON المستخرج من UABEA → يترجم دفعياً عبر `FilteredTranslator` (نفس cascade) مع reuse للكاش per-game → يحقن في فتحة عربية (موجودة أو جديدة) → يصدّر `arabic_only.json` للمود |
| **gui/qt/pages/i2_translate.py** | Python | الواجهة: اختيار لعبة + ملف JSON، تحليل، خيارات تشغيل (cache/skip/translations.txt/حد طول/tag_mode override)، progress + ETA + pause/resume، حفظ الناتج |
| **mods/I2LanguageInjector/ (DLL)** | C# | يحقن الترجمات العربية في I2.Loc وقت التشغيل |

### التدفّق

```
UABEA يستخرج I2Languages-*.assets → *.json
   → I2BatchTranslator.analyze() (إحصاءات: اللغات، فتحة العربي)
   → .run() دفعي عبر FilteredTranslator + cache (per-game)
   → .save_modified() (الملف كامل) + .export_arabic_only() (للمود)
   → I2LanguageInjector.dll يحقنها في اللعبة
```

### تكامل الكاش — suffix `:i2`

ترجمات I2 الدفعية تُخزَّن في نفس DB اللعبة لكن بـ suffix `:i2` على اسم المودل (مثل `translategemma:12b:i2`). نصوصها قد تكون بصيغة template (`{0} Days`) لا تطابق نصوص اللعبة الـ live (post-substitution). لذا التصدير لـ translations.txt يُفضّل الـ live عبر `cache.get_best(text, deprioritize_suffix=":i2")` — انظر v2.2 §5.

## مساري UE — متى أيّهما

| المسار | الملف | الآلية | الاستخدام |
|------|------|------|------|
| **DLL injection** | `games/unreal_hook_mod.py` | حقن `cppfs/dxgi/ZXSOSZX*.dll` + ملفات `Translate/*.subtitle.txt` | الافتراضي لـ UE5 (Palworld) |
| **UE4SS mod** | `games/ue4ss_mod.py` | UE4SS + Lua mod يقرأ `dict/translations.txt` | مسار بديل لألعاب تدعم UE4SS |
| **DataTable .pak mod** | `games/manorlords_mod.py` | تعديل `DT_Translation_*` (عمود en_US) → repak V11 | **Manor Lords** (أنظف وأقوى من البروكسي) |

## ⭐ تعريب Manor Lords — مود DataTable (.pak) ساكن

> Manor Lords (UE5.5) يخزّن **كل** نصوصه في DataTables. النهج الساكن (تعديل الأصول مسبقاً)
> **أنظف بكثير** من البروكسي الحيّ: لا التقاط نص وقت اللعب، لا تجمّد، تغطية كاملة فورية.
> الأدوات في `tools/manorlords/` و `games/manorlords_mod.py`. مفتاح AES + usmap محفوظان لدى المستخدم.

### المعطيات المُكتشَفة (حاسمة)

| المعطى | القيمة |
|------|------|
| تخزين النصوص | DataTables `DT_Translation_*` في `Content/Translation/HoodedHorse/` (39 جدول) + `CombinedDataTables/CDT_*` |
| بنية الصف | **عمود لكل لغة** (`en_US`, `de_DE`, …) من نوع `StrPropertyData` — **لا يوجد عمود عربي** |
| الحلّ | نكتب العربي **مكان عمود `en_US`** (تبقى اللعبة إنجليزية، تظهر عربي) |
| تغليف اللعبة | **`.pak` خالص** (لا IoStore/`.utoc` — لذا UnrealPak لا retoc) |
| **إصدار pak** | **11** ← ⚠ UnrealPak من UE5.7 ينتج **12 → كراش** `Invalid pak file version (12)`. الحلّ: **repak `--version V11`** |
| mount point | `../../../` والمسار الكامل `ManorLords/Content/Translation/HoodedHorse/DT_*.uasset` |
| الخط/RTL | **UE5 يشكّل ويعكس BiDi أصلاً + خط اللعبة فيه عربي** → **بلا تعديل خط ولا rtl_layout** (عكس Foundation/Unity) |
| usmap | `…/UAssetGUI/Mappings/ManorLords.usmap` (UAssetGUI يبحث فيه تلقائياً) |
| موضع المود | مباشرة في `Content/Paks/` (لا `~mods`) باسم `zzz_…_P.pak` (يرتّب أخيراً = أولوية + لاحقة `_P`) |

### الأدوات (`tools/`)

| الأداة | الدور |
|------|------|
| `tools/repak/repak.exe` | ⭐ حزم pak **V11** (الأهم — حلّ الكراش). UAssetGUI/UnrealPak **لا** يصلحان للحزم هنا |
| `tools/UAssetGUI/UAssetGUI.exe` | `uasset ⇄ JSON` مع usmap (`tojson`/`fromjson`، `VER_UE5_5`). round-trip **متطابق بايت** |
| `tools/manorlords/translate_dt.py` | ترجمة جدول واحد (كاش + Ollama + حماية تاقات) |
| `tools/manorlords/build_all.py` | ترجمة **كل** الجداول دفعةً ثم حزم مود واحد (يحمّل المحرّك مرّة) |
| `tools/manorlords/pack_mod.py` | حزم ملفات uasset في `.pak` (repak V11) + تثبيت |

### التدفّق

```
uasset --(UAssetGUI tojson + usmap)--> JSON
   → ترجمة عمود en_US (FilteredTranslator + cache per-game + tag filter)
   → كتابة العربي مكان en_US في JSON
JSON --(UAssetGUI fromjson)--> uasset مترجم
   → repak pack --version V11 --mount-point ../../../  →  zzz_..._P.pak
   → نسخ إلى <game>/ManorLords/Content/Paks/
```

### تكامل التطبيق (`games/manorlords_mod.py` + بطاقة في `games.py`)

- **`ManorLordsMod`** — واجهة مثل FoundationMod: `get_install_status` / `build` / `install` /
  `update_translations` / `uninstall` / `status_counts`. **`build()` من الكاش فقط** (بلا Ollama —
  سريع): لكل جدول `tojson` من `.orig` الإنجليزي → يطبّق `cache.get_best` على `en_US` → `fromjson`
  → يجمع في staging → `repak V11`. idempotent (يبدأ دائماً من الأصل الإنجليزي).
- **البطاقة** في `gui/qt/pages/games.py::_render_manorlords_card` (تظهر عند `cfg["mod_mode"]=="datatable_pak"`):
  أزرار **تثبيت/تحديث/إلغاء**. الإشارات `manorlords_*_requested` → معالِجات `_on_manorlords_*`.
- **`ManorLordsBuildWorker(QThread)`** — البناء (~78 استدعاء UAssetGUI ≈ 2-4 د) في خيط مع
  `QProgressDialog` (لا يجمّد الواجهة). الإلغاء سريع (حذف الـ pak فقط، بلا خيط).
- **config**: `games/configs/Manor Lords.json::mod_mode = "datatable_pak"` يفعّل البطاقة.

### ⚠️ مشكلة RTL في ودجات معيّنة (صفحة المساعدة/الموسوعة) — عكس انتقائي لكل نص

**الاكتشاف**: بعض ودجات Manor Lords (صفحة «مساعدة في المواضيع»/الموسوعة) **تُشكّل العربي
لكن لا تطبّق BiDi** → تعرض الكلمات بترتيب منطقي LTR = معكوسة بصرياً. ودجات أخرى
(تلميحات/قوائم/إعدادات) تطبّق BiDi صح. **نفس الجدول يغذّي الاثنين** → لا يمكن إصلاح
واحدة دون كسر الأخرى بتعديل المحتوى.

**التشخيص (سلسلة اختبارات pak تشخيصية)**: إنجليزي+تاق=صح (الودجة تحلّل التاقات)، عربي
قصير=صح، عربي طويل (بتاقات أو بدونها أو بأرقام)=معكوس. الخلاصة: الودجة لا تعكس BiDi.
`rtl_layout` (presentation forms) **يفشل** هنا (اللعبة تُشكّل بنفسها → تعارض → حروف منفصلة).
الحل الصحيح: **عكس ترتيب الكلمات فقط** (الحروف منطقية → اللعبة تشكّلها).

**الحل — عكس انتقائي لكل نص (مثل wrap_overrides)**:
- `engine/ue_rtl_reverse.py::reverse_for_display(text)` — يعكس ترتيب الكلمات؛ يُبقي `<h>..</>`
  ملتفّة (مع عكس كلمات محتواها)؛ يقسّم على `{br}` (يحافظ على ترتيب الفقرات)؛ **يحذف `<img/>`**
  (تنكسر/تظهر حرفية في السياق المعكوس، وهي زخرفية). لا تشكيل (اللعبة تشكّل).
- `engine/rtl_overrides.py` — مجموعة نصوص مُعلَّمة لكل لعبة في `data/cache/<game>.rtlrev.json`.
- **زر «🔁 عكس RTL»** في صفحة الكاش (`gui/qt/pages/cache.py`) — يُعلّم/يُزيل تعليم النصوص
  المحدَّدة (مثل «منع»/«اكتشف التاقات»). المستخدم يُعلّم **نصوص صفحة المساعدة فقط**.
- `ManorLordsMod.build` يقرأ `rtl_overrides.load(GAME)` ويطبّق `reverse_for_display` على
  النصوص المُعلَّمة فقط عند البناء/التحديث → **التلميحات السليمة لا تتأثّر، صفر تعارض**.
- **مزلق**: تاق الفتح الزوجي في `_PAIR_CONTENT` يجب أن يستثني الذاتي `/>` (`(?<!/)>`) وإلا
  يطابق `<img.../>` كتاق فتح فيكسر المجموعة.

### ملاحظات/مزالق

1. **الترجمة الدفعية (الكاش) منفصلة عن البناء**: `build_all.py` يملأ الكاش (Ollama)؛ أزرار التطبيق
   تطبّق الكاش فقط (سريع). لتعريب جديد كامل: شغّل `build_all.py` مرّة ثم استخدم الأزرار.
2. **`.orig` = الأصل الإنجليزي**: `build_all.py` يحفظه أوّل مرّة. `ManorLordsMod.build` يبني منه دائماً
   (لذا التحديث بعد تعديل الكاش يُعيد التطبيق نظيفاً، لا تراكم).
3. **تلوّث الكاش CJK**: ترجمات qwen قديمة سرّبت صينية (reasoning). نُظّفت بفحص نطاقات CJK.
   عند ظهور حروف صينية في الترجمة → افحص الكاش واحذف الصفوف الملوّثة.
4. **جداول CDT المدموجة**: اللعبة تقرأ `DT_*` المفصّلة (مُثبَت). لو بقيت شاشات إنجليزية → أضف
   `--include-combined`/`include_combined=True` لضمّ `CDT_*`.
5. **تطابق الإصدار حرج**: أي لعبة UE أخرى بنفس النهج — افحص إصدار pak اللعبة الأصلي (footer magic
   `0x5A6F12E1` ثم uint32) وطابقه بـ repak `--version`. v11=UE5.4/5.5، اختلاف الإصدار = كراش.
6. **⚠️ المصدر دائماً من `.orig` الإنجليزي — لا الـ uasset/json المترجَم** (مزلق خطير سبّب تلف
   128 صف): بعد `fromjson`، الـ uasset يصبح **عربياً**. لو أعدت `tojson` منه (أو من `.json` قديم
   صار عربياً) تقرأ العربي كـ `en_US` وتترجمه ثانيةً → `put(عربي, عربي_مُعاد)` يُنشئ صفوف كاش
   `original_text` عربي (تالفة). الحماية الثلاثية المطبّقة:
   - `build_all.py` + `ManorLordsMod.build`: `tojson` **دائماً من `.orig`** (وفي build يكتب JSON
     لملف مؤقت في staging، لا يعيد استخدام `for_cache/*.json`).
   - حارس في `build_all.py`/`translate_dt.py`: **تخطّى أي مصدر `en` فيه حرف عربي**.
   - حارس في `cache.py::RetranslateWorker`: لا يُترجم نصّاً مصدره عربي (يمنع المستخدم من إفساد الكاش
     بزر «إعادة الترجمة» على صف تالف).
   - تنظيف: احذف الصفوف التي `original_text GLOB '*[؀-ۿ]*'` (عربي في المصدر).
7. **تلوّث CJK من qwen القديم**: ترجمات سرّبت صينية (reasoning). نظّفها بفحص نطاقات CJK
   (`[一-鿿…]`) في `translated_text`.
8. **⚠️ حماية تاقات UE RichText — `engine/ue_richtext.py`** (الفلتر العام لا يصلح):
   tag_filter العام مبني على إغلاق **مُسمّى** (`<h>…</h>`) ويصنّف `<i>`/`<u>` كـ inline
   (بلا حماية). لكن UE يستخدم إغلاقاً **عاماً** `</>` (بلا اسم) و`<i>` و`{br}`. فالفلتر
   يفوّتها → المودل يضيف `</i>`/`</h>` (يظهر **حرفياً** في اللعبة لأن UE يفهم `</>` فقط).
   - **الحل**: `ue_richtext.protect()` يستبدل **كل** `<…>`/`</>`/`{…}` (وتتابعاتها المتلاصقة
     كتوكن واحد) بـ`⟦N⟧` معتم → المودل لا يرى التاقات → لا يضيف/يحذف/يبدّل صيغتها. يتحقّق
     أن كل توكن موجود مرّة واحدة قبل القبول (`is_valid`)، وإلا None (لا يحفظ مكسوراً).
   - **تحجيم ديناميكي**: يرفع `num_predict`/`num_ctx` للنصوص الطويلة (truncation يقصّ التوكنات
     الأخيرة)، و**تنويع حرارة** على المحاولات المتكرّرة (`temp=0` يجعل الـ retry حتمياً).
   - **مستخدَم في**: `build_all.py`/`translate_dt.py` (الترجمة الدفعية) + `cache.py::RetranslateWorker`
     (زر «إعادة الترجمة») — استبدلا `FilteredTranslator`.
   - **إصلاح القائم**: `tools/manorlords/fix_tags.py` يعيد ترجمة الصفوف التي
     `tags_of(orig) != tags_of(trans)`. + إصلاح حتمي: حذف أي `</name>` مُسمّى من الترجمات
     (0 أصل يستخدمه → آمن دائماً). الباقي العصيّ (تاق محذوف) يفقد تنسيقاً فقط بلا ظهور حرفي.

## ⭐ تعريب Foundation — محرّك Hurricane خاص (بلا Unity/UE)

> لعبة Foundation (Polymorph) على محرّك **Hurricane** خاص. لا BepInEx ولا UE hooks تنفع.
> الحلّ المُثبَت: **proxy DLL يعترض FreeType** + ترجمة JSON دفعية + تخطيط RTL برمجي.
> أدوات اللعبة في `tools/foundation/` و `mods/Foundation/`. التفاصيل الكاملة في
> [tools/foundation/PROGRESS.md](tools/foundation/PROGRESS.md).

### المعمارية (3 طبقات)

| الطبقة | الآلية | الملف |
|------|------|------|
| **الترجمة** | يقرأ `localization/en/*.json` (27 ملف، nested، BOM، tabs) → يترجم عبر FilteredTranslator + كاش (`Foundation.db`) → يكتب `localization/ar/*.json` بتخطيط RTL | `tools/foundation/translate_foundation.py` |
| **رسم الخط** | proxy `CrashRpt1403.dll` (يُحمَّل تلقائياً عند الإطلاق العادي — CrashRpt مستوردة static) → MinHook على `FT_New_Memory_Face @ 0x141e06eb0` → يستبدل خطوط الواجهة بخط عربي حسب النمط | `tools/foundation/dll/arabicfont.c` |
| **RTL** | `engine/rtl_layout.py` (تطبيع `\n` + لفّ ذاتي + تشكيل/عكس BiDi لكل سطر) | مشترك |

### لماذا proxy DLL (لا حقن ولا مود)

- **المود مسدود**: لا نوع أصل خط في API، والـ atlas يُبنى عند الإقلاع قبل تحميل المودات.
- **`game.package` مشفّر** (مفتاح لكل أصل) → لا تعديل مباشر للخطوط.
- **الحقن المباشر/الغلاف يكسران Steam handshake** → اللعبة تخرج/تتعطّل.
- **الحلّ**: المحرّك يفكّ تشفير الخط ثم يمرّره لـ `FT_New_Memory_Face`. نعترض هذا (المحرّك
  فكّ التشفير قبله) ونستبدل البافر. الـ proxy لـ DLL مستوردة static (`CrashRpt1403.dll`)
  يُحمَّل أثناء الإطلاق العادي عبر Steam → **بلا حقن، بلا غلاف، بلا كسر تشفير**.

### استبدال الخط حسب النمط (في الـ hook)

يُعرَف نوع الخط من **حجم الملف** (من جدول الحزمة):
- المدى 400KB–700KB = خطوط الواجهة اللاتينية (Sans/Serif/Mono). Thai(~47KB)/CJK(~16MB) خارجه.
- أحجام Bold/BoldItalic (455164/471004/570708/608488) → `arabic_bold.ttf`. الباقي → `arabic_regular.ttf`.
- خط vector واحد يكفي كل الأحجام النقطية (FreeType يقيس). العربية بلا مائل → Bold للعريض والمائل.

### ⭐ `engine/rtl_layout.py` — الحلّ الجذري لـ RTL (قابل لإعادة الاستخدام في كل الألعاب)

المشكلة المتكرّرة في كل محرّك بلا BiDi (Unity TMP، Hurricane، …):
1. **فاصل السطر**: `\n` حرفي vs سطر فعلي — `layout_rtl` يطبّعه (`\\n` → `\n`).
2. **انقلاب ترتيب الأسطر**: المحرّك يلفّ النص المعكوس مسبقاً من اليسار (auto-wrap) فينقلب
   ترتيب الأسطر رأسياً. الحل: **نلفّ الكلمات بأنفسنا** (قبل التشكيل) لأسطر ≤ عرض أضيق صندوق
   → المحرّك لا يحتاج auto-wrap → ترتيب صحيح دائماً.
3. **التشكيل + العكس لكل سطر مستقلاً** (الترتيب الرأسي محفوظ).

```python
from engine.rtl_layout import layout_rtl
out = layout_rtl(text, max_line_len=45)   # 0 = فواصل صريحة فقط؛ ≤ أضيق صندوق
```
**القاعدة**: `max_line_len ≤ أضيق صندوق نص` → لا auto-wrap في أي مكان (Foundation: 45).

### النشر (للإطلاق العادي عبر Steam)

عبر `games/foundation_mod.py` (تثبيت/إلغاء — مثل bepinex_mod). يضع في مجلّد اللعبة:
- `CrashRpt1403.dll` (proxy محلّنا) + `CrashRpt1403_orig.dll` (الأصلية مُعاد تسميتها).
- `arabic_regular.ttf` + `arabic_bold.ttf` (خطوط الاستبدال).
- يطبّق RTL على `localization/ar/*.json` + يسجّل `ar:` في locales.txt (اسم مُشكّل) +
  يضبط اللغة=ar في usersetting.config + يحذف charset.txt (يُعاد توليده).
- ⚠ **تحديث Steam يستعيد `CrashRpt1403.dll`** → أعد التثبيت من الزر.

### بناء الـ proxy (يحتاج Zig — `tools/zig/`)

```bash
ZIG=tools/zig/zig-x86_64-windows-0.16.0/zig.exe
$ZIG cc -shared -target x86_64-windows-gnu -O2 -I tools/foundation/tools_minhook/include \
  tools/foundation/dll/arabicfont.c tools/foundation/dll/CrashRpt1403.def \
  tools/foundation/tools_minhook/src/{buffer,hook,trampoline}.c tools/foundation/tools_minhook/src/hde/hde64.c \
  -o tools/foundation/dll/CrashRpt1403.dll -lkernel32 -luser32
```
الـ `.def` يوجّه كل صادرات CrashRpt الأصلية لـ `CrashRpt1403_orig` (لئلا تنكسر اللعبة).

### الهندسة العكسية (مرجع)

- مشروع Ghidra محفوظ: `tools/foundation/ghidra_proj/` (أعد التشغيل بـ `-process foundation.exe -noanalysis`).
- دالة بناء الخط: `GenCFreeTypeFont::build` @ `0x1403d4220`. `FT_New_Memory_Face` = `FUN_141e06eb0`.
- أدوات: `pkg.py` (محلّل الحزمة)، `find_ft.py`/`find_xref.py`/`disasm.py` (RE)، `ghidra_scripts/FindFreeType.java`.

### تكامل التطبيق (صفحة اللعبة + الكاش)

- **`games/foundation_mod.py`** (`FoundationMod`) — تثبيت/تحديث/إلغاء (واجهة مثل BepInExMod):
  `install/uninstall/update_translations/get_install_status/apply_translations`. التثبيت ينشر
  الـ proxy + الخطوط + يطبّق RTL على ar/ + يضبط اللغة + يحذف charset. الإلغاء عكسي بالكامل.
- **بطاقة Foundation** في `gui/qt/pages/games.py::_render_foundation_card` (engine=="hurricane"):
  أزرار تثبيت/تحديث الترجمة/إلغاء + **اختيار الخط** + **منزلق لفّ الأسطر** + عرض الخط الحالي.
  الإشارات `foundation_*_requested` → معالِجات `_on_foundation_*`.
- **اختيار الخط** (`set_font`/`font_coverage`): منتقي ملف يفحص تغطية العربي + **presentation forms**
  (لازمة لأننا نغذّي نصاً مُشكّلاً). خطوط GSUB فقط (Cairo/Tajawal/Noto Sans Arabic) بلا PF → `؟`.
  خطوط فيها PF: Tahoma/Segoe/Arial/Amiri/**Noto Kufi Arabic**. الخط بأي حجم (الـ hook يطابق خط اللعبة بالحجم).
- **لفّ مخصّص لكل نص** (`engine/wrap_overrides.py` → `data/cache/<game>.wrap.json`): في EditDialog
  (صفحة الكاش) منزلق "لفّ RTL مخصّص" يطغى على العام لنص محدّد (للصناديق الضيّقة). يُطبَّق عند "تحديث الترجمة".

### تعديل ترجمة جملة + ملاحظات RTL

1. صفحة **الكاش** → اختر اللعبة (Foundation) → ابحث عن الجملة → **زر "✏ تعديل"** → صحّح → حفظ (في `Foundation.db`).
2. **أعد التطبيق**: زر "🔄 تحديث الترجمة" في صفحة اللعبة → يُعيد كتابة `ar/*.json` بالتخطيط → أعد تشغيل اللعبة.
- ⚠ **المسافات المتعمَّدة محفوظة**: `EditDialog._save` لا يحذف المسافات (مهمّة لتباعد أجزاء RTL).
- ⚠ **القوالب المتداخلة** (اللعبة تملأ `{1}` بجملة منسّقة أخرى) = أصعب حالة RTL؛ ترتيب الأجزاء
  الداخلية تتحكّم به اللعبة → لا يُعكس آلياً. القوالب المفردة (`{1} ل {2}`) تُعالَج صحيحاً (BiDi يُبقي الأرقام LTR).

## الـ C# Mods

### ArabicFontFixer (عام)

[mods/ArabicFontFixer/ArabicFontFixer.cs](mods/ArabicFontFixer/ArabicFontFixer.cs)

- يقرأ `BepInEx/config/ArabicGameTranslator/translations.txt` عند البدء
- يـ hook `I2.Loc.LocalizationManager.GetTranslation` (postfix) و `TMP_Text.text` setter (prefix)
- لو النص في `translations.txt` → يُطبَّقه فوراً
- إن لم يكن → يضعه في queue ويرسله لـ `http://127.0.0.1:5001/` على thread خلفي
- **حد طول النص = 4000** (كان 500 سابقاً — انظر إصلاحات أدناه)
- ينشئ Arabic font fallback من خطوط نظام Windows (Tahoma/Arial/Segoe UI)

### FlotsamArabicRuntime (خاص بـ Flotsam)

[mods/FlotsamArabicRuntime/FlotsamArabicRuntime.cs](mods/FlotsamArabicRuntime/FlotsamArabicRuntime.cs)

- يـ hook طبقات متعدّدة: `TMP_Text.text`, `TMP_Text.SetText`, `Text.text`, `LocalizedText.UpdateText`, `TextField.SetText`, `RecipeItemDisplay.Initialize`, `LocalizationManager.ApplyRTLfix`
- يُحمّل ترجمات Flotsam I2 من `flotsam_i2_translated_only.json`
- `EnsureRtlState()` يضبط `isRightToLeftText` ديناميكياً حسب محتوى النص
- `PreReverseLtrRunsForRtl()` يعكس LTR runs مسبقاً (لـ TMP يعيدها للوضع الصحيح)
- `SwapBracketsForRtl()` يقلب `( ↔ )` و `[ ↔ ]` للعرض RTL
- `HasCustomSpriteAsset()` يكتشف `<sprite="X" name="Y">` ويُبقي الخط الأصلي للعبة لذلك النص

> راجع قسم "قاعدة sprite assets الحرجة" أعلاه في "ترجمة Unity الفورية" للتفاصيل.

## ⭐ تطويرات v2.1 (2026-05-26) — أنظمة جديدة

### 1. الفلتر العام (Global tag_mode)

قبل: الفلتر كان يُختار في **3 أماكن منفصلة** (per-game config، TagModeConfirmDialog عند تشغيل البروكسي، combo في صفحة الترجمة الفورية). نتج عنه:
- زر "إعادة الترجمة" في الكاش يستخدم engine مباشرة **بدون أي filter** ← التاقات تتكسر
- التضارب بين القيم في الأماكن المختلفة

الآن: **مكان واحد فقط** — `config.json["tag_mode"]` يُختار من صفحة AI Models (combo في topbar):

```python
from engine.filtered_translator import get_global_tag_mode, set_global_tag_mode
mode = get_global_tag_mode()   # → "bulletproof" | "tiered" | "strip" | "inline"
set_global_tag_mode("tiered")  # يحفظ في config.json فوراً
```

**المستخدمون**:
- البروكسي (`proxy.start()` يقرأها من `cfg["tag_mode"]` الذي يُمرَّر من `games.py`)
- `RetranslateWorker` في صفحة الكاش (عبر `FilteredTranslator`)
- صفحة الترجمة الفورية (مجرّد label عرض، يقرأ من config)

**أُزيل**:
- `TagModeConfirmDialog` (لم يعد يُستدعى — الملف باقي لكن مهجور)
- `tag_mode` من `games/configs/*.json` (تم حذفه من Flotsam.json)
- combo الـ tag_mode من `gui/qt/pages/translate.py`

### 2. FilteredTranslator — wrapper مشترك مع cascade

في [engine/filtered_translator.py](engine/filtered_translator.py):

```python
ft = FilteredTranslator(engine, tag_mode=None)   # tag_mode=None → يقرأ من config
result, mode = ft.translate_with_info(text)
# bulletproof mode → cascade تلقائي: bulletproof → tiered → strip → None
```

نفس منطق `_do_bulletproof_cascade` في البروكسي — الآن مفصول كي يستخدمه:
- `gui/qt/pages/cache.py::RetranslateWorker` (إعادة الترجمة من الكاش)
- البروكسي يحتفظ بنسخته داخل `_translate()` (لم يُغيَّر للحفاظ على دمج timeout الديناميكي + lock)

### 3. ⚠ Bug جذري في tag_filter.py — تم الإصلاح

[engine/tag_filter.py](engine/tag_filter.py) — `_handle_selfclose()` في كل من `TieredTagFilter` و `BulletproofTagFilter`:

**قبل**:
```python
tokens.append(("self", name, attrs, None))   # attrs = " id=|X|" (بدون /)
# عند restore: f"<{name}{attrs}>" → "<itemName id=|X|>"   ← /> مفقودة!
```

**بعد**:
```python
attrs = m.group("attrs") or ""
if m.group(0).rstrip().endswith("/>"):
    attrs = attrs + "/"   # احفظ / لو الأصل كان self-closed
tokens.append(("self", name, attrs, None))
# عند restore: f"<{name}{attrs}>" → "<itemName id=|X|/>"  ← /> محفوظة ✓
```

**التأثير**: Palworld + Manor Lords + أي UE5 يستخدم `<tag attrs/>` — التاقات تظل سليمة في الترجمة. Unity TMP `<sprite=0>` (بدون /) يظل يعمل أيضاً (الصيغة الأصلية محفوظة).

### 4. tag_health.py — كاشف الترجمات المعطوبة

[engine/tag_health.py](engine/tag_health.py)::`is_broken_translation(orig, trans)` يكتشف نمط:
- الأصل فيه `<name attrs/>` (selfclosing)
- الترجمة لا تحفظ نفس عدد الـ tags، أو فيها `|VALUE|` تطفو بلا wrapper

يُستخدَم في:
- **`games/unreal_hook_mod.py::export_translate_folder`** — يتخطّى المعطوبة + **يحذف `.subtitle.txt` القديم** كي يُعيد الـ watcher ترجمتها عند الإطلاق التالي
- **`games/bepinex_mod.py::export_static_translations_txt`** — نفس الشيء لـ translations.txt
- **`tools/clean_broken_tag_translations.py`** — أداة فحص/حذف يدوية

### 5. ⚠ Bug في export_translate_folder — تطبيع المفتاح

البروكسي يُطبّق على النص الوارد:
```python
text_key = " ".join(text.replace("\\n", " ").replace("\n", " ").split())
```
ثم يخزّنه في الكاش بهذا الشكل. لكن `.subtitle.en.txt` على القرص يحوي `\r\n` خام.

**النتيجة قبل الإصلاح**: لكل نص متعدّد الأسطر، البحث في الكاش يفشل ← آلاف الملفات تظهر "بدون ترجمة" رغم وجودها في الكاش.

**الإصلاح**: في `export_translate_folder`، نُطبّق نفس التطبيع على المفتاح قبل البحث:
```python
def _normalize_key(s): return " ".join(s.replace("\\n", " ").replace("\n", " ").split())
normalized = {_normalize_key(en): ar for en, ar in translations.items()}
ar_text = translations.get(src_text) or normalized.get(_normalize_key(src_text))
```

**النتيجة على Palworld**: 4,678 → 6,973 ملف محدَّث (+2,295 ترجمة استُرجعت).

### 6. RetranslateWorker — صف لكل مودل (لا استبدال)

`gui/qt/pages/cache.py::RetranslateWorker`:

**قبل**: يستدعي `cache.update_translation(game, orig, result)` ← `UPDATE WHERE original_text = ?` يستبدل أي صف (يفقد ترجمات مودلات أخرى).

**بعد**: يحدّد المودل النشط الفعلي ويستدعي `cache.put(game, orig, result, model=active_model, mode_used=mode)` ← `ON CONFLICT(original_text, model_used)` يُنشئ صفاً جديداً لمودل لم يترجم النص بعد، أو يُحدّث صف المودل الحالي فقط. **ترجمات المودلات الأخرى تبقى سليمة**.

### 7. اكتشاف التاقات من الكاش

نظام جديد لاستخراج XML/HTML tags من النصوص:
- [engine/tag_discovery.py](engine/tag_discovery.py) — `discover_tags(texts)` يُرجع قائمة `TagInfo` مع: name, kind (selfclosing|paired), count, example, suggested_kind, sources
- [gui/qt/dialogs/tag_discovery_dialog.py](gui/qt/dialogs/tag_discovery_dialog.py) — حوار checkbox لكل تاق مكتشف + combo (inline|selfclosing) + إحصاء جديد/موجود
- [engine/tag_config.py::add_tags()](engine/tag_config.py) — يضيف للقائمة بدون تكرار
- زر **"🏷  اكتشف التاقات"** في صفحة الكاش جنب زر "🚫 منع" (يظهر مع التحديد)

### 8. صفحة الكاش — بحث بمطابقة تامة

زر `≈` / `=` toggle بجانب صندوق البحث:
- **جزئي** (افتراضي، رمز ≈): `LIKE '%text%'`
- **تام** (رمز =، مفعّل): `= ? COLLATE NOCASE` — يطابق النص كاملاً، case-insensitive

التعديل في `engine/cache.py`: `count_entries` / `get_page` / `count_failed` / `get_failed_page` يقبلون `exact_match: bool = False`.

### 9. Unreal Hook — أدوات إضافية

- [tools/steam_inject_wrap.py](tools/steam_inject_wrap.py) — Steam Launch Options wrapper:
  ```
  "C:\Python314\python.exe" "D:\GameArabicTranslator\tools\steam_inject_wrap.py" %command%
  ```
  Steam يستبدل `%command%` بأمر اللعبة، السكربت يكتشف الـ config من الـ exe ويعمل suspended-launch + inject. Steam overlay و playtime يعملان طبيعياً.

- [tools/toggle_unreal_hook.py](tools/toggle_unreal_hook.py) — تعطيل/تفعيل DLLs (للأونلاين):
  ```bash
  python tools/toggle_unreal_hook.py --game Palworld --disable   # قبل الجماعي
  python tools/toggle_unreal_hook.py --game Palworld --enable    # رجوع للأوفلاين
  python tools/toggle_unreal_hook.py --game Palworld --status
  ```
  السبب: مود الترجمة يحقن `cppfs.dll/dxgi.dll/ZXSOSZX*.dll` → Epic Online Services يكشف الحقن ويرفض `ConnectLoginNoEAS(0)`. الـ toggle يُعيد تسمية الـ DLLs لـ `.disabled` كي اللعبة تتجاهلها.

### 10. صفحة Palworld — UX دمج هرمي (نفس Flotsam)

في `gui/qt/pages/games.py::_render_unreal_hook_card`:
```
🏆  دمج هرمي (6,802 ترجمة من كل المودلات)
🤖 translategemma:12b  (3,150 ترجمة)
🤖 qwen2.5:14b  (2,200 ترجمة)
```
نفس صيغة Flotsam في `game_detail_dialog._do_bepinex_update`.

## ⭐ تطويرات v2.2 (2026-05-31) — إصلاحات Farthest Frontier + تحسينات الـ live

### السياق

دمج لعبة Farthest Frontier (Unity 2022.3.62 Mono) كشف سلسلة buggs خفيّة في الـ pipeline بين الـ proxy و ArabicFontFixer. الأعراض التي رصدها المستخدم:
1. النصوص تظهر إنجليزية أوّل مرة عند تمرير الماوس على tooltip، ثم عربية في المرّة الثانية
2. السيرفر يتعطّل بعد فترة طويلة من اللعب (الإحصاءات تتجمّد، زر السيرفر أخضر)
3. سلسلة `IDENTITY response: '+17%'` / `'-10%'` في اللوق
4. بعد إعادة تشغيل اللعبة، يجب المرور على كل عنصر hover من جديد

كل هذه الأعراض كان لها سبب جذري واحد، اكتُشِف عبر diagnostic logging مفصّل.

### 1. ⚠️ الـ Bug الجذري — `\=` escape في parser الـ DLL

[mods/ArabicFontFixer/ArabicFontFixer.cs](mods/ArabicFontFixer/ArabicFontFixer.cs)::`LoadStaticTranslations` كان يستخدم `line.IndexOf('=')` لإيجاد فاصل key=value.

**النتيجة الكارثية**: 346 سطر في `translations.txt` تحتوي `<color\=#xxxxxx>...` (الـ `\=` escape لمنع تفسير الـ `=` كفاصل). الـ DLL يقسم عند **أوّل `=`** (داخل `\=`) → key يصبح `"<color\"` بدل النص الكامل.

كل 346 سطر ينتهي بمفتاح مشوّه مكرّر → `Dictionary<string, string>` يستبدل القيمة في كل مرة → **229 ترجمة فُقدت** من `_staticTr`.

**كشف الـ bug**: الـ DLL يطبع `Loaded 2378 static translations (total entries incl. normalized: 2149)`. الفرق 229 بين عدد السطور والإدخالات الفعلية لفت الانتباه. تأكيد عبر Python script: `2378 - 346 = 2032` (سطور سليمة) + بعض المُطبَّعة المختلفة ≈ 2149.

**الإصلاح**: `FindKeyValueSeparator(line)` يبحث عن أوّل `=` **غير مسبوق بـ `\`** (مطابق لمنطق Python parser في `engine/static_translations.py::_parse_lines`). تم تطبيقه على `LoadStaticTranslations` و`ProcessReloadRequest`.

```csharp
private static int FindKeyValueSeparator(string line)
{
    for (int i = 0; i < line.Length; i++)
    {
        if (line[i] == '=' && (i == 0 || line[i - 1] != '\\'))
            return i;
    }
    return -1;
}
```

**كل النصوص الملوّنة `<color\=...>` كانت تفشل بسبب هذا** — وهذا فسّر "إنجليزي أول مرة عربي ثاني مرة" لمعظم tooltips.

### 2. تطبيع المفاتيح بين Python و C#

البروكسي يطبّع النص قبل التخزين في SQLite:
```python
text_key = " ".join(text.replace("\\n", " ").replace("\n", " ").split())
```
ثم `export_static_translations_txt` يكتب الـ key المُطبَّع في translations.txt. اللعبة ترسل النص بـ newlines الأصلية → عدم تطابق.

**الإصلاح في DLL**: `NormalizeKey(text)` يطابق Python بدقّة (يستبدل `\\n` literal + كل `char.IsWhiteSpace` → space ويضغطها). يُستخدم في:
- `StoreWithNormalizedKey`: يخزّن مفتاحين (أصلي + مُطبَّع) في `_staticTr`
- `Translate`: يجرّب المفتاح الأصلي أولاً، ثم المُطبَّع كـ fallback (ويكاش النتيجة بالمفتاح الأصلي للسرعة)

### 3. النصوص "غير القابلة للترجمة" تعمل re-queue بلا انقطاع

نصوص مثل `Pioneer`, `Ctrl+Alt`, `v1.1.2` تذهب لـ AI، AI يرّدها كما هي (IDENTITY) → تُسجَّل في `failed_translations`. عند المرّة التالية:
- البروكسي يفحص `is_failed("Pioneer")` → True → يردّ `"Pioneer"` + `unchanged=True`
- ArabicFontFixer يستلم النص. الكود القديم فحص `result != text` → false → **لم يخزّن** → كل hover ترجع نفس الدورة

**الإصلاح**: عند `result == text`، الـ DLL يخزّن **self-key marker** (`_staticTr[text] = text`). `Translate` يكتشف self-key marker (`ar == text`) ويُرجع النص فوراً بدون queue. هذا أوقف 55+ طلب HTTP متكرّر لكل جلسة.

### 4. حفظ markers بين الجلسات

بدون تصدير، الـ markers تضيع عند إغلاق اللعبة. الجلسة التالية تعيد الدورة لكل نص.

**الإصلاح في [games/bepinex_mod.py](games/bepinex_mod.py)::`export_static_translations_txt`**: يصدّر `failed_translations` بصيغة `text=__SKIP__` بعد الترجمات العادية:

```python
if not model_filter:
    rows = conn.execute("SELECT original_text FROM failed_translations").fetchall()
    for (en,) in rows:
        if en in exported_keys:
            continue
        f.write(f"{safe_key}=__SKIP__\n")
```

في الـ DLL، `StoreWithNormalizedKey` يكتشف `val == SKIP_MARKER ("__SKIP__")` ويحوّلها إلى self-key (`_staticTr[key] = key`). الـ `Translate` يعرف فوراً "لا ترجمة" بدون استدعاء البروكسي.

### 5. ترجمات `:i2` (template) تتعارض مع الترجمات الـ live

I2 batch translator يخزّن ترجمات بصيغة template (`{0} Days`, `Population: {0:N0}/{1:N0}`). اللعبة تستبدل placeholders قبل إرسال للـ TMP، فالنص الذي يصل = `"42 Days"` (post-substitution).

ترجمات `:i2` كانت تحت suffix `translategemma:12b:i2`. لو نص له ترجمتان (واحدة من `translategemma:12b` بصيغة post-substitution، والأخرى من `:i2` بصيغة template أو contextual)، `get_best` كان يختار أحياناً `:i2` → الـ DLL يفشل في المطابقة.

**الإصلاح المزدوج**:
- [engine/cache.py](engine/cache.py)::`get_best(text, deprioritize_suffix=":i2")`: يفلتر المودلات بـ suffix معيّن عند توفّر بديل. `iter_best_translations` يمرّر نفس الـ parameter
- [games/bepinex_mod.py](games/bepinex_mod.py)::`export_static_translations_txt`: يستبعد النصوص التي تحوي `{N}` templates (576 نص في Farthest Frontier) + يمرّر `deprioritize_suffix=":i2"`

النتيجة: 6,461 → 5,896 ترجمة (تخطّى 576 template + ~11 ترجمة `:i2` كان لها بديل أنسب). الترجمات في translations.txt تطابق ما تستلمه اللعبة فعلياً.

### 6. تحسينات أخرى

**[engine/proxy_server.py](engine/proxy_server.py)**:
- `_needs_translation`: شُدِّد ليتطلّب 3 أحرف لاتينية متتالية بدل 2 → يستبعد `+10%`, `-20%`, `1x`, `2K` قبل ما تصل لـ AI (كانت تسبّب IDENTITY responses)
- `_translate`: عند فشل AI، يُرجع `(text, False, True)` بدل `(None, ...)` → `do_GET` يطبع `⏭` ويحدّث counter كـ "بلا تغيير" بدل "ترجمات جديدة"
- `start()`: أُلغي التصدير التلقائي للكاش → translations.txt (المستخدم يفضّل التحكّم اليدوي عبر زر "تحديث الترجمات")

### تتبع تطوّر ArabicFontFixer

| الإصدار | التغيير |
|------|------|
| v3.1.8 → 3.1.9 | + `NormalizeKey` + `StoreWithNormalizedKey` |
| v3.2.0 | تحسين `NormalizeKey` لمطابقة Python بدقّة (`char.IsWhiteSpace` + `\\n` literal) |
| v3.2.1 | + self-key markers (يخزّن `_staticTr[text]=text` عند `result==text`) |
| v3.2.2 | + قراءة `__SKIP__` markers من translations.txt |
| v3.2.3 | diag logging مفصّل للـ LONG-MISS (يكشف الـ key الفعلي + المُطبَّع) |
| **v3.2.4** | **`FindKeyValueSeparator` يحترم `\=` escape — الإصلاح الجذري** |

### درس مستفاد لأي وكيل لاحق

عند ظهور أعراض مثل "نص ثابت يفشل في lookup":
1. **لا تفترض** أن المشكلة في التطبيع أو المسار. ربما **الـ key لم يُحمَّل أصلاً**.
2. **قارن العدد**: `Loaded X (total entries Y)` لو `Y < X` بشكل غريب، فيه parsing bug.
3. **استخدم diag logging** يطبع الـ key بتفصيل (`EscapeForDiag` يحوّل `\n`/`\r`/`\t` لـ literals مرئية).
4. **اقرأ سطر translations.txt بـ Python** وقارن byte-by-byte مع ما يصل الـ DLL.
5. **تذكّر**: format escape sequences (`\=`, `\n`) في translations.txt يجب يحترمها parser الـ DLL بنفس قواعد parser الـ Python.

## ⭐ تطويرات v2.3 (2026-06-01) — استقرار Ollama + جودة الترجمة + تقليل تكرار الكاش

### السياق

جلسة عمل على Farthest Frontier كشفت 4 مشاكل في الـ pipeline الحيّ، حُلّت كلها في طبقة Python (بلا بناء DLL) عدا إصلاح عكس الأسطر (DLL).

### 1. ⚠️ انقطاع Ollama الصامت — socket بائت + موت أبدي

**العَرَض**: بعد فترة لعب، Ollama "يفصل" — الخادم يبدو يعمل (أخضر) لكن لا يترجم. حتى إيقاف/تشغيل الخادم لا يُصلح، يجب إعادة تشغيل اللعبة.

**السبب الجذري** (سلسلة):
- `OllamaTranslator` يستخدم `requests.Session` دائمة بـ HTTP keep-alive. عند الخمول، الـ socket المُخزَّن يصبح بائتاً (النظام/Ollama يُغلق الاتصالات الخاملة).
- الطلب التالي على socket ميت → `ConnectionError` → `_raw_translate` يضع `_is_loaded=False`.
- الـ wrapper `TranslationEngine.translate` يحاول `load()`؛ لو فشل مرّة (Ollama مشغول) → `_load_failed_session=True` → **لا يُعيد المحاولة أبداً** لبقية الجلسة (كان يُصفَّر فقط في `proxy.start()`).

**الإصلاحات**:
- [api_translator.py](engine/models/api_translator.py)::`_raw_translate` → عند `ConnectionError` **يُعيد إنشاء الجلسة ويحاول مرّة ثانية** قبل الاستسلام (يعالج الـ socket البائت فوراً). فُصِل تنفيذ الطلب في `_post_and_parse`.
- [translator.py](engine/translator.py)::`translate` → `_load_failed_session` يتعافى بعد **cooldown 30 ث** (عبر `_load_failed_at`) بدل الموت الأبدي.

### 2. ⚠️ تسميم الكاش أثناء عطل المحرّك (transient vs permanent)

**المشكلة**: عند فشل Ollama (اتصال/مهلة)، كان البروكسي يُعامله كفشل **دائم**: `mark_failed` في DB + يردّ بالنص الإنجليزي. الـ DLL يخزّن الإنجليزي كـ`_staticTr[text]=text` ("لا ترجمة دائمة"). فحتى بعد تعافي Ollama، الـ DB والـ DLL "مسمَّمان" → يتطلّب إعادة تشغيل اللعبة. **هذا السبب الفعلي لـ"لازم أعيد تشغيل اللعبة".**

**الإصلاح** في [proxy_server.py](engine/proxy_server.py):
- `_is_transient_failure()` يميّز العطل المؤقت (الاتصال منقطع `_is_loaded=False`، أو رسالة خطأ فيها "اتصال/مهلة/connection/timeout").
- عند عطل مؤقت: **لا** `mark_failed`، ويُرجع الإشارة `_TRANSIENT` → `do_GET` يردّ بجسم **فارغ** → الـ DLL/XUnity لا يُسمَّمان ويُعيدان المحاولة عند التعافي.

### 3. ⚠️ النصوص الطويلة (async) تُترجَم وتُحفظ بالكاش لكن لا تُعرض

**المشكلة**: النص ≥ 200 حرف يذهب async، فالبروكسي كان يردّ **بالإنجليزي** فوراً. الـ DLL يخزّنه كـ self-marker ("لا ترجمة"). العامل الخلفي يترجمه ويحفظه في SQLite (لذا يظهر في الكاش!)، **لكن الـ DLL لا يسأل عنه ثانية** → يبقى إنجليزياً للجلسة.

**الإصلاح**: المسار غير المتزامن يُرجع الإشارة `_PENDING` → `do_GET` يردّ **فارغاً** بدل الإنجليزي. الـ DLL لا يُسمّم، يُعيد الطلب في العرض التالي حتى تجهز الترجمة في الكاش → تُعرض عربية. ("الإنجليزي أولاً" يبقى عبر الـ prefix hook في الـ DLL).

> **الإشارتان** `_TRANSIENT` و`_PENDING` (محارف sentinel في proxy_server.py) كلاهما → ردّ فارغ في `do_GET`. الفرق في الإحصاء فقط: transient=فشل، pending=بانتظار. السلوك الصحيح: **لا تردّ بالإنجليزي إلا عند فشل دائم حقيقي** (is_failed/identity) — حينها الـ DLL يُسمّم بحقّ (بلا spam).

### 4. تقويلب الأرقام — تقليل تكرار الكاش

اللعبة تستبدل القوالب بالأرقام قبل العرض: `"Current Tier: 2"`, `"Fertility: 100% from 0 to 100"`, `"417 Peas have been lost..."`. كل قيمة = مدخل كاش جديد + ترجمة AI جديدة (تكرار ضخم + spam في diag).

**الحل** [engine/number_template.py](engine/number_template.py) + غلاف في `proxy_server.py::_translate`:
- يستبدل الأرقام بـ`{0}{1}` (علامة **محميّة أصلاً** في برومت النظام وفي `translate_preserving_tokens`) → المفتاح يصبح قالباً واحداً.
- `_translate` (الغلاف) ينادي `_translate_impl` بالقالب، ثم يُعيد الأرقام في النتيجة.
- لا يتدخّل لو النص فيه `{..}` أصلاً (تجنّب تضارب).
- يُعطَّل عبر `config.json["number_templating"]` (افتراضي مُفعَّل).
- **ملاحظة نطاق**: يعمل بالكامل على المسار **الحيّ**. لمطابقة المسار الثابت (translations.txt) يحتاج نفس التقويلب في الـ DLL (خطوة مستقبلية).
- **المحتوى الديناميكي غير الرقمي (أسماء القرويين Kasar/Iarra/…)** لا يُقولَب (صعب عمومياً) — يبقى مدخلاً لكل اسم، لكن يُعرض صحيحاً (ترجمة لكل اسم مرّة ثم cache).

### 5. فرض تماثل علامة النهاية — منع نقاط المودل الزائدة

**المشكلة**: translategemma:12b يضيف نقطة في نهاية الترجمة حتى لو الأصل بلا نقطة (رغم برومت المنع). النقطة بعد `</color>` تتداخل مع عكس RTL في الـ DLL → نقطة حمراء منفصلة + اللون يُطبَّق على الكلمة الخطأ.

**الحل (حتمي، لا يعتمد على طاعة المودل)** [base.py](engine/models/base.py)::`enforce_trailing_punctuation(src, translated)`:
- لو الأصل لا ينتهي بعلامة نهاية جملة، يحذف العلامة التي أضافها المودل (سواء في النهاية أو قبل/بعد تاقات الإغلاق).
- يُطبَّق في `proxy_server.py::_translate_impl` (الحيّ) و`filtered_translator.py::translate_with_info` (إعادة الترجمة + I2).
- **تنظيف الموجود**: [tools/fix_added_periods.py](tools/fix_added_periods.py) — يُصحّح الكاش القائم في مكانه (لا يحذف). على الكاش الحالي: **~11,945 ترجمة** فيها نقطة زائدة (22-58% حسب اللعبة!).
  ```bash
  python tools/fix_added_periods.py                 # فحص (dry-run)
  python tools/fix_added_periods.py --apply --yes   # تصحيح كل الألعاب
  ```

### 6. عكس ترتيب الأسطر RTL (DLL) — لافّ كلمات بعرض محدّد

**المشكلة**: الـ DLL يعرض RTL بعكس كل سطر يدوياً + `isRightToLeftText=false`. السطر الطويل بلا `\n` → TMP يطبّق auto-wrap على النص المعكوس → ينقلب ترتيب الأسطر رأسياً (الأول تحت).

**الإصلاح** [ArabicFontFixer.cs](mods/ArabicFontFixer/ArabicFontFixer.cs)::`InsertLineBreaksAtSentenceEnds` (أُعيدت كتابتها): لافّ كلمات كامل (`MaxVisualLineLen=30`) يعالج كل سطر مستقلاً ويلفّ أي مقطع طويل عند حدود الكلمات → لا مقطع يكفي لتشغيل auto-wrap → لا عكس. **القيمة 30 مضبوطة لصناديق tooltips الضيّقة في Farthest Frontier (~33 حرف)** — تُصغَّر للصناديق الأضيق، تُكبَّر للأوسع. الحلّ الجذري البديل: RTL أصلي عبر `isRightToLeftText=true` (يدع TMP يلفّ تلقائياً).

### درس مستفاد

- **عند "تُحفظ بالكاش لكن لا تُعرض"**: المشكلة غالباً ليست في الترجمة، بل في **تسميم عميل الـ DLL** (`_staticTr` self-marker) أثناء async/عطل. البروكسي يجب يردّ **فارغاً** (لا إنجليزي) إلا عند فشل دائم حقيقي.
- **المحتوى الديناميكي (أرقام/أسماء)** = أكبر مصدر تضخّم كاش وأعراض "إنجليزي ثم عربي". قولِب ما يمكن (الأرقام)، واقبل الباقي مع ضمان العرض الصحيح.
- **تعديل كود Python يتطلّب إعادة تشغيل التطبيق** — زر الخادم لا يكفي (Python يحمّل الوحدات مرّة واحدة).

## الإصلاحات الجوهرية من هذه الجلسة (2026-05-22)

تاريخ الـ commits السابقة:
```
dcd1c57 Fix proxy reading _last_error from wrong layer
b719e42 Fix duplicate [tried: ...] in recent-failures display
6db9a33 Detailed failure logging + recent-failures viewer
4d2cce5 Ollama settings tab + live resource monitoring
4dd76dc Add keep_alive to Ollama API calls
```

### إصلاحات غير-مرتبطة بعد (لم تُحفَظ كـ commit)

1. **منع إعادة محاولة نصوص فاشلة عند "بدون كاش"** — كان `is_failed()` داخل شرط `cache_model_filter != "none"` فيُتخطّى → نصوص فاشلة تُرسَل لـ Ollama مراراً.
2. **`_get_engine_last_error()` يقرأ من المترجم النشط** بدل الـ wrapper (TranslationEngine لا يحفظ `_last_error`).
3. **Skip patterns module** (`engine/skip_patterns.py`) — قائمة منع مخصّصة مع fnmatch.
4. **Static translations module** (`engine/static_translations.py`) — قارئ translations.txt مع auto-reload عند تغيّر mtime.
5. **Dynamic timeout** للنصوص الطويلة (>500 حرف) — يمنع timeout على شاشات المساعدة الكبيرة.
6. **Manual fix dialog** في عرض الفاشلة — يحفظ التصحيح تحت نفس المودل الذي فشل.
7. **زر تشغيل/إغلاق اللعبة** عبر `steam://run/<appid>` (يكتشف appid من `appmanifest_*.acf`).
8. **Proxy restart** بدون إعادة تشغيل التطبيق — أضفنا `server_close()` + `allow_reuse_address=True`.
9. **System prompt يُحمَّل من config.json عند init** المترجم (كان يُتجاهَل إلا بعد حفظ يدوي).
10. **ArabicFontFixer حد 4000 حرف** (كان 500) — نصوص شاشة المساعدة الطويلة تمرّ الآن.
11. **FlotsamArabicRuntime يحتفظ بالخط الأصلي** عند وجود `<sprite="...">` — يعرض الأيقونات بدل نص حرفي.
12. **Installer ينسخ DLLs إضافية من `mods/<GameName>/`** تلقائياً (FlotsamArabicRuntime.dll الآن يُثبّت تلقائياً).
13. **حوارات قابلة للتوسيع** مع size grip + min/max buttons لـ 4 حوارات.
14. **System prompt v4** — قاعدة symmetry لمنع المودل من إضافة علامات ليست في الأصل.
15. **Schema v2 للكاش** — `UNIQUE(original_text, model_used)` يسمح بترجمات متعدّدة لنفس النص (واحدة لكل مودل). Migration تلقائي يحفظ كل البيانات القديمة. أعمدة جديدة: `is_preferred`. جدول جديد: `model_priority(model_used, priority, updated_at)`.
16. **خوارزمية الدمج الهرمي** في `cache.get_best(text)`:
    1. `is_preferred=1` (اختيار يدوي عبر `set_preferred`)
    2. `mode_used='manual'` (تصحيح يدوي من EditDialog، الأحدث)
    3. إجماع 2+ مودلات (نفس الترجمة)
    4. أعلى `priority` من `model_priority`
    5. الأحدث `updated_at` (fallback)
17. **`iter_best_translations(game, model_filter)`** — مولّد للتصدير لـ translations.txt. `model_filter=""` يطبّق الدمج، اسم مودل محدّد يصدّر ترجماته فقط.
18. **حوار "🎯 أولوية المودلات"** ([gui/qt/dialogs/model_priority_dialog.py](gui/qt/dialogs/model_priority_dialog.py)) — drag-drop لترتيب المودلات. يظهر في صف أزرار BepInEx في كلا الـ:
    - `gui/qt/pages/games.py::GameDetail` (صفحة الألعاب)
    - `gui/qt/dialogs/game_detail_dialog.py::GameDetailDialog` (الحوار المنبثق)
    عند الحفظ: يُحوّل ترتيب القائمة إلى `priority` (الأعلى = N، الأدنى = 1) عبر `cache.set_model_priority`.
19. **export يقرأ فقط — Game.db لا يتغيّر**: ضغط "تحديث الترجمات" يطبّق الدمج عبر `iter_best_translations` ويكتب `translations.txt` فقط. الـ DB لا يُعدَّل أبداً.
20. **Restart fix #2**: `proxy.start()` يُعيد تعيين `_load_failed_session = False` على كل المترجمات. السبب: عند ConnectionError مع Ollama يُوضَع `_is_loaded = False`، ثم في محاولة إعادة التحميل التالية لو فشلت يُوضَع `_load_failed_session = True` ولا يُعاد المحاولة. كان يضطرّ المستخدم لإعادة تشغيل التطبيق. الإصلاح يضمن restart نظيف.
21. **Cascade timeout per-attempt محسّن للنصوص الطويلة**: بدل `max(25, total/3)` ثابت، الآن min حسب طول النص:
    - ≤ 500 حرف: 25 ث
    - ≤ 1500: 45 ث
    - ≤ 3000: 75 ث
    - > 3000: 120 ث
    يمنع timeout مبكر على شاشات المساعدة الكبيرة في وضع Bulletproof cascade.
22. **Non-blocking stop()** ([engine/proxy_server.py:375-413](engine/proxy_server.py#L375-L413)) — كان `stop()` يستدعي `server.shutdown()` الذي يبلوك حتى تنتهي كل threads الطلبات الجارية. لو فيه طلب AI طويل (240 ث) → الواجهة تتجمّد. الإصلاح: `stop()` يصفّر المراجع فوراً ويُطلق `shutdown()` في thread خلفي. زمن stop الآن < 1ms بدل 240,000ms.
23. **Engine_lock تجديد على start()** — طلبات AI القديمة من تشغيل سابق قد لا تزال تحاصر القفل القديم. عند start جديد نُنشئ `threading.Lock()` جديد. الطلبات الجديدة لا تنتظر threads قديمة لتحرّر القفل. الـ threads القديمة تُحرّر قفلها (لكن لا أحد ينتظر).
24. **HTTP session reset on start()** — في `proxy.start()` نُغلق `_session` لكل translator + نضع `_is_loaded=False`. السبب: العميل HTTP قد يحمل اتصالاً مكسوراً (broken pipe) بعد ConnectionError. الجلسة الجديدة تُفتح عند الطلب التالي تلقائياً.
25. **🌟 Async background translation للنصوص الطويلة** ([engine/proxy_server.py:744-822](engine/proxy_server.py#L744-L822)) — **الإصلاح الأهم**. النصوص ≥ 200 حرف لا تُترجَم متزامناً (تحاصر العميل لـ 90-240 ث) بل تُضاف لـ background queue، البروكسي يردّ بالنص الإنجليزي فوراً (50ms)، AI يكمل في الخلفية ويحفظ في cache. الطلب التالي لنفس النص → cache hit → عربي. مكوّنات:
    - `self._bg_queue: queue.Queue[str]` — طابور النصوص المعلّقة
    - `self._bg_in_progress: set[str]` — منع تكرار (نفس النص لا يُجدوَل مرتين)
    - `self._bg_worker: threading.Thread` — daemon worker thread (idle timeout 30s)
    - `self._bg_stop_event: threading.Event` — لإيقاف الـ worker عند stop()
    - `self._async_threshold_chars = 200` — الحد. أقل = sync، أكثر = async
    - `self._bg_max_queue_size = 500` — backpressure
    - `_should_translate_async(text)` — قرار sync/async (يحترم "بدون كاش" → كل sync)
    - `_translate(text, force_sync=True)` — bg worker يستدعي بـ force_sync لتجنّب re-scheduling
    - السبب الجذري: ArabicFontFixer/XUnity يستخدمان `HttpWebRequest.Timeout=5000ms` للاتصال. لو AI يأخذ > 5 ث، العميل يفترض الخادم ميت → يدخل حالة معطّلة → اللعبة تتطلب إعادة تشغيل. الـ async يمنع هذا تماماً (الردّ خلال 50ms دائماً).
    - **النتيجة**: لا تجميد للعميل أبداً مهما طال نص AI. مستخدم يرى الإنجليزي أول مرة، عند إعادة فتح الشاشة → عربي.

## واجهات الـ DB الجديدة (cache.py)

```python
# قراءة
cache.get_best(game, text) → str | None              # دمج هرمي
cache.iter_best_translations(game, model_filter="")  # مولّد للتصدير
cache.count_by_model(game)            → dict          # خريطة {model: count}
cache.count_by_model(game, "qwen")    → int           # عدد لمودل واحد
cache.get_model_priorities(game)      → dict          # {model: priority}

# كتابة
cache.put(game, text, ar, model, mode_used)           # صف لكل (text, model)
cache.set_preferred(game, text, model, True/False)    # علم الاختيار اليدوي
cache.set_model_priority(game, model, priority)        # رفع/خفض الأولوية
```

## المزالق المعروفة (Gotchas)

### Python / proxy

1. **TIME_WAIT على المنفذ**: لازم `server_close()` بعد `shutdown()` + `allow_reuse_address=True` كي يعمل restart فوراً.
2. **`_translate()` يجب أن يحترم `cache_model_filter == "none"`**: في كل فحص (translations.txt، is_failed، cache). كل واحد منهم محاط بـ `if not no_cache_mode:`.
3. **Thread safety في cache**: كل thread يفتح connection خاصاً (SQLite default).
4. **`_engine_lock` يسلسل استدعاءات Ollama**: لا تُجرِ AI calls متوازية (Ollama instance واحد).
5. **`is_running` يفحص الـ thread**: لو الـ thread مات، `is_running == False` لكن `_server` قد يبقى مع socket مرتبط — نظّفه في بداية `start()`.
6. **`_is_loaded = False` بعد ConnectionError**: في [api_translator.py:290](engine/models/api_translator.py#L290)، عند انقطاع Ollama يُوضَع `_is_loaded = False`. الـ engine wrapper يُعيد التحميل، لكن لو فشل reload أوّل مرة (Ollama بطيء) يُوضَع `_load_failed_session = True` ولا يُعاد المحاولة أبداً. الإصلاح: `proxy.start()` يُعيد تعيين هذا العلم على كل المترجمات في بداية كل تشغيل.
7. **schema migration v2 happens once**: إعادة بناء الجدول مع `UNIQUE(original_text, model_used)`. يُمحَى الـ unique index القديم، يُنشَأ index مركّب جديد. كل البيانات (1335 صف) محفوظة. لا تعدّل cache.py:`_migrate_to_composite_unique` بعد ذلك بدون فهم آلية إعادة البناء.
8. **تطبيع نص الكاش = تطبيع نص .en.txt**: البروكسي يستبدل `\r\n` و `\\n` بمسافة قبل التخزين (`engine/proxy_server.py:136`). أي كود يبحث في الكاش بمفتاح من ملف نصي **لازم** يطبّق نفس التطبيع — انظر `games/unreal_hook_mod.py::export_translate_folder` (`_normalize_key`). نسيان هذا = البحث يفشل لكل نص متعدّد الأسطر.
9. **تاقات selfclosing — احفظ صيغة الإغلاق الأصلية**: `engine/tag_filter.py::_handle_selfclose` يضيف `/` إلى `attrs` لو الأصل كان `<tag/>`. لا تُزله من المنطق — Palworld و UE5 يفرّقون بين `<tag/>` و `<tag>` ويكسران بدونها.
10. **cache.put() لإعادة الترجمة، لا update_translation**: عند إعادة الترجمة بمودل ثاني، استخدم `put()` (ينشئ صف جديد لمودل جديد، أو يحدّث صف نفس المودل) — لا `update_translation` الذي يضرب أي صف بنفس النص.
11. **لا تردّ بالإنجليزي إلا عند فشل دائم** (v2.3): عند عطل مؤقت (اتصال/مهلة) أو نص قيد المعالجة async، ردّ **فارغاً** (`_TRANSIENT`/`_PENDING`) لا الإنجليزي. الإنجليزي == النص يجعل الـ DLL يخزّنه كـ self-marker ("لا ترجمة دائمة للجلسة") → الترجمة تصل الكاش لكن لا تُعرض حتى إعادة تشغيل اللعبة. الإنجليزي مسموح فقط عند `is_failed`/identity (فشل حقيقي).
12. **تعديل كود Python يتطلّب إعادة تشغيل التطبيق** (v2.3): زر إيقاف/تشغيل الخادم يُعيد `proxy.start()` فقط (إعدادات + حالة)، لا يُعيد استيراد `.py`. انظر قسم "Workflow اختبار سريع".

### C# / BepInEx

1. **Harmony prefix `ref` parameter**: التعديلات قد لا تنتقل. استخدم prefix + postfix مع static field للحالة (انظر `ApplyRTLfixPrefix/Postfix`).
2. **`isRightToLeftText` لا يكفي**: TMP يقلب LTR runs بصرياً في وضع RTL. استخدم `PreReverseLtrRunsForRtl()` لعكسها مسبقاً (للوضع غير-العربي).
3. **استبدال `text.font` يُلغي sprite assets**: الخط الجديد لا يعرف الـ assets المخصّصة للعبة. استخدم `fallbackFontAssetTable` بدلاً من ذلك.
4. **`TMP_FontAsset.CreateFontAsset` overloads متعدّدة**: جرّب modern (family name) ثم legacy (UnityEngine.Font) — انظر `TryCreateFont` في ArabicFontFixer.
5. **Harmony hook order**: غير مضمون. الـ mods الثلاثة (XUnity, ArabicFontFixer, FlotsamArabicRuntime) لا يجب أن يتعارضوا على نفس النص (نتأكّد بأن كل واحد idempotent).

### واجهة المستخدم

1. **Qt RTL display ≠ النص المحفوظ**: حقول RTL تعكس `<` و `>` بصرياً. ليست مشكلة في البيانات.
2. **QDialog flags استبدال**: استخدم `windowFlags() | NEW_FLAG` للحفاظ على X.
3. **QTextEdit بلا stretch**: لا يتمدّد عمودياً مع النافذة. أضِف `stretch=1` في `addWidget`.

### parser sync بين Python و C# (مهم — انظر v2.2 §1)

4. **`\=` escape في translations.txt**: لو الـ key يحوي `=` حرفي (مثل `<color=#FF0000>...`)، الـ Python writer يكتبه كـ `\=` (escape). الـ DLL parser **يجب** يحترم هذا (يبحث عن أوّل `=` غير مسبوق بـ `\`). لا تستخدم `string.IndexOf('=')` في الـ DLL لأنه يقسم في المكان الخطأ ويفقد الـ key.
5. **تطبيع النص بين البروكسي وDLL**: البروكسي يطبّع `\n` → space + يضغط whitespace قبل التخزين في SQLite. الـ DLL يجب يطبّق نفس المنطق في `NormalizeKey` (يدعم Python's `.split()` بتعامل كل whitespace + الـ `\\n` literal من XUnity).
6. **self-key markers في `_staticTr`**: لو نص لا يحتاج ترجمة (AI يردّه كما هو)، نخزّن `_staticTr[text] = text` (نفس النص). الـ `Translate` يكتشفها بـ `string.Equals(ar, text)` ويُرجع فوراً بدون `PrepareForRtlDisplay`.

### ترجمات `:i2` (template) vs live (post-substitution)

7. **مودلات بـ suffix `:i2`** (مثل `translategemma:12b:i2`): تأتي من I2 batch translator، نصوصها بصيغة template (`{0} Days`, `Population: {0:N0}/{1:N0}`). هذه **لا تطابق** نصوص اللعبة الـ live (اللعبة تستبدل قبل الإرسال). استخدم `get_best(text, deprioritize_suffix=":i2")` لتفضيل المودلات الـ live في التصدير.
8. **`{N}` templates في الـ export**: `export_static_translations_txt` يستبعد أي نص يحوي `{N}` placeholders (regex `\{\d+[^}]*\}`) — وجودها في translations.txt مهدر فقط لأنها لن تطابق أبداً.

## أين تجد ماذا

| ما تريده | الملف |
|------|------|
| تعديل البرومت الافتراضي | `config.json["system_prompt"]` (أو `_default_ollama_system_prompt()` في `engine/models/api_translator.py:9`) |
| إعدادات Ollama (num_ctx, num_predict, ...) | `config.json["ollama_options"]` |
| **الفلتر العام (tag_mode)** | `config.json["tag_mode"]` ← UI في `gui/qt/pages/models.py` (topbar combo) |
| تعديل ترتيب البحث | `engine/proxy_server.py::_translate()` |
| إعدادات اللعبة | `games/configs/<GameName>.json` |
| تثبيت/إلغاء mod (Unity) | `games/bepinex_mod.py::install()` و `uninstall()` |
| تثبيت/إلغاء hook (UE5) | `games/unreal_hook_mod.py::install()` و `uninstall()` |
| ترجمة ملفات اللعبة | `games/<game>/translator.py` (مثل `games/flotsam/translator.py`) |
| سجل البروكسي والإحصاءات | `gui/qt/pages/games.py::LogPanel` |
| تحرير قائمة المنع | `gui/qt/dialogs/skip_list_dialog.py` |
| تصحيح ترجمة فاشلة يدوياً | `gui/qt/pages/cache.py::EditDialog` (failed view) |
| **اكتشاف XML tags من نصوص** | زر "🏷 اكتشف التاقات" في `gui/qt/pages/cache.py` |
| **كشف ترجمات معطوبة** | `engine/tag_health.py::is_broken_translation(orig, trans)` |
| **ترجمة محمية برمجياً (cascade)** | `engine/filtered_translator.py::FilteredTranslator` |
| **Steam Launch wrapper** | `tools/steam_inject_wrap.py` |
| **تعطيل/تفعيل DLLs للأونلاين** | `tools/toggle_unreal_hook.py --game X --disable\|--enable\|--status` |
| **حذف ترجمات معطوبة من الكاش** | `tools/clean_broken_tag_translations.py --delete` |
| **بحث بمطابقة تامة في الكاش** | زر `≈/=` toggle بجانب صندوق البحث في صفحة الكاش |
| **parser لـ translations.txt في DLL** | `mods/ArabicFontFixer/ArabicFontFixer.cs::FindKeyValueSeparator` (يحترم `\=`) |
| **تطبيع المفاتيح في DLL** | `mods/ArabicFontFixer/ArabicFontFixer.cs::NormalizeKey` (يطابق Python `text_key`) |
| **تفضيل المودلات الـ live في التصدير** | `cache.get_best(text, deprioritize_suffix=":i2")` |
| **استبعاد templates في التصدير** | فلتر `_template_pat` في `games/bepinex_mod.py::export_static_translations_txt` |
| **diag log للـ DLL** | `<game>/BepInEx/arabicfontfixer_diag.log` (Heartbeat كل 5 دقائق + LONG-MISS lookups) |
| **إعادة محاولة Ollama على socket بائت** | `engine/models/api_translator.py::_raw_translate` (retry على جلسة جديدة) |
| **تعافي المحرّك بعد فشل تحميل** | `engine/translator.py::translate` (cooldown 30 ث عبر `_load_failed_at`) |
| **تمييز عطل مؤقت/قيد معالجة** | `engine/proxy_server.py` sentinels `_TRANSIENT` / `_PENDING` (ردّ فارغ، لا تسميم) |
| **تقويلب الأرقام (تقليل تكرار الكاش)** | `engine/number_template.py` + غلاف `proxy_server.py::_translate` (تعطيل: `config.json["number_templating"]`) |
| **منع نقاط المودل الزائدة** | `engine/models/base.py::enforce_trailing_punctuation` (حتمي) |
| **تنظيف النقاط الزائدة من الكاش** | `tools/fix_added_periods.py --apply` |
| **منع عكس ترتيب الأسطر RTL** | `ArabicFontFixer.cs::InsertLineBreaksAtSentenceEnds` (`MaxVisualLineLen=30`) |

## Workflow اختبار سريع

> ⚠ **تمييز حاسم: تعديل الكود ≠ تغيير الإعدادات.**
> زر "إيقاف/تشغيل الخادم" يُعيد استدعاء `proxy.start()` فقط (يقرأ الإعدادات + يصفّر الحالة).
> **لا يُعيد استيراد ملفات `.py` المعدّلة** — Python يحمّل الوحدات في الذاكرة مرّة واحدة.
> لذلك أي تعديل على **كود** المحرّك (proxy_server.py، api_translator.py، …) يتطلّب
> **إغلاق التطبيق وإعادة فتحه** بالكامل، وليس مجرّد زر الخادم.

1. **بعد تغيير إعدادات التشغيل فقط** (تبديل اللعبة، tag_mode، cache_model_filter، إعادة تشغيل خادم HTTP بعد تعطّل): يكفي زر "إيقاف الخادم" ثم "تشغيل الخادم".
2. **بعد تعديل كود Python** (أي ملف في `engine/` أو `gui/`): **أعد تشغيل التطبيق كاملاً** — زر الخادم لا يكفي.
3. **بعد تعديل system_prompt**: أعد تشغيل التطبيق (يُحمَّل في `TranslationEngine._init_translators`).
4. **بعد تعديل C# mod**: أغلق اللعبة (الـ DLL مقفول أثناء التشغيل) → `dotnet build` → انسخ DLL إلى `<game>/BepInEx/plugins/` → أعد تشغيل اللعبة.
5. **بعد تعديل translations.txt يدوياً**: auto-reload — البروكسي يقرأ التغييرات في الطلب التالي.

## التعامل مع تعارض المودات

السيناريو الحالي (Flotsam):
- **3 hooks على `TMP_Text.text`**: ArabicFontFixer (prefix) + FlotsamArabicRuntime (prefix + postfix) + XUnity AutoTranslator
- **يعملون بالتسلسل**: prefix → prefix → set_text → postfix
- **الترتيب يعتمد** على Harmony — لا تضمن ترتيباً، اجعل كل hook idempotent
- **خطّان عربيان** يُسجَّلان كـ fallback (`ArabicFontFixer_Fallback` + `ArabicRuntimeFallback`) — هدر ذاكرة لكن لا يكسر

## ملفات يجب عدم تعديلها/حذفها

- `data/cache/*.db` — قواعد بيانات SQLite للترجمات (احفظها قبل أي تعديل خطير، خصوصاً قبل migration)
- `data/cache/Flotsam.db.translategemma_backup` — backup يدوي من المستخدم قبل migration v2 (لا تحذفه)
- `mods/_bepinex_base/` — BepInEx + XUnity المشترك (يُنسَخ منه للعبة)
- `config.json` — يحوي إعدادات Ollama المضبوطة + system_prompt المخصّص

## نقاط الاتصال (Integration Points)

| المكوّن | يَطلب من | عبر |
|------|------|------|
| ArabicFontFixer.dll (C#, Unity) | بروكسي Python | `GET http://127.0.0.1:5001/?text=...` (queue داخلي + thread خلفي) |
| XUnity AutoTranslator (Unity) | بروكسي Python | `GET http://127.0.0.1:5001/?text=...` (Endpoint=CustomTranslate في AutoTranslatorConfig.ini) |
| ZXSOSZX*Mod.dll + dxgi hijack (UE5) | `Translate/*.subtitle.en.txt` files | اللعبة تكتب `.en.txt` وتقرأ `.subtitle.txt` — لا اتصال HTTP مباشر |
| `tools/unreal_hook_watcher.py` | بروكسي Python | يراقب `Translate/` ويرسل أي `.en.txt` جديد لـ proxy → يكتب `.subtitle.txt` |
| البروكسي | translations.txt | يقرأ من `<game_path>/BepInEx/config/ArabicGameTranslator/translations.txt` (أولوية مطلقة) |
| البروكسي | SQLite cache | يقرأ ويكتب في `data/cache/<GameName>.db` |
| البروكسي | Ollama | `POST http://localhost:11434/api/chat` (مع keep_alive=30m) |
| GUI export (BepInEx) | translations.txt | يكتب فقط (دمج هرمي عبر `cache.iter_best_translations` + يتخطّى المعطوبة عبر `tag_health`) |
| GUI export (UnrealHook) | `Translate/*.subtitle.txt` | يكتب فقط + يحذف الملفات المعطوبة (نمط tag بمكسر) |
| GUI priority dialog | model_priority table | يقرأ/يكتب أولوية المودلات (per-game) |
| Models page | `config.json["tag_mode"]` | يقرأ ويكتب الفلتر العام عبر `engine/filtered_translator.py` |
| Steam (Launch Options) | `tools/steam_inject_wrap.py` | Steam يستبدل `%command%` بأمر اللعبة → السكربت يطلق suspended + يحقن |

## خطّة مستقبلية: دمج هرمي لترجمات متعدّدة المودلات

عند تنفيذ هذه الخطة، نسمح لكل نص إنجليزي بأن يحتفظ بترجمات منفصلة من مودلات مختلفة (qwen + translategemma + google_free)، ثم نختار الأفضل عند التصدير لـ `translations.txt`.

### تغييرات schema

```sql
-- يُعدَّل: UNIQUE(original_text) → UNIQUE(original_text, model_used)
-- يضاف: عمود "is_preferred" (BOOLEAN) لتحديد الاختيار اليدوي
ALTER TABLE translations ADD COLUMN is_preferred BOOLEAN DEFAULT 0;
-- يضاف: جدول أولوية المودلات لكل لعبة
CREATE TABLE model_priority (
    game_name TEXT NOT NULL,
    model_used TEXT NOT NULL,
    priority INTEGER NOT NULL,
    PRIMARY KEY (game_name, model_used)
);
```

### خوارزمية الاختيار (Hierarchical Fallback)

عند الحاجة لاختيار ترجمة واحدة من بين ترجمات متعدّدة لنفس النص:

```
1. لو نص له is_preferred=1 (اختيار يدوي صريح من المستخدم)
   → استخدمه فوراً، لا تتجاوزه

2. وإلا، لو نص له mode_used="manual" (تصحيح يدوي عبر EditDialog)
   → استخدمه (ثقة عالية بالمستخدم)

3. وإلا، لو 2+ مودلات أنتجت ترجمة متطابقة (إجماع)
   → استخدم ترجمة الإجماع

4. وإلا، طبّق الأولوية من جدول model_priority
   → أعلى رقم priority للمودل المتوفّر

5. وإلا، الأحدث (MAX updated_at)
   → fallback نهائي
```

### تغييرات على proxy_server.py

في `_translate()` عند الحفظ بـ `cache.put()`:
- الآن: يُحدّث الصف الموجود (`ON CONFLICT(original_text) UPDATE`)
- بعد: يُدخل صفاً جديداً لكل (نص × مودل) (`ON CONFLICT(original_text, model_used) UPDATE`)

في `_translate()` عند البحث:
- الآن: `cache.get(text)` يُرجع الترجمة الوحيدة
- بعد: `cache.get(text)` يطبّق الخوارزمية الهرمية ويُرجع الأفضل

### واجهة المستخدم (إضافات)

1. **صفحة Settings → "أولوية المودلات للعبة"**:
   ```
   اللعبة: Flotsam
   ┌────────────────────────────────────┐
   │ ⬆ qwen2.5:14b-instruct      (15)  │  ← السحب لإعادة الترتيب
   │   translategemma:12b          (10) │
   │   google_free                  (5) │
   │ ⬇                                  │
   └────────────────────────────────────┘
   ```

2. **صفحة الكاش → عمود "Conflicts"**:
   - شارة 🔀 بجانب النصوص التي لها 2+ ترجمات
   - النقر يفتح حوار "حلّ التعارض" مع خيارات:
     - عرض كل الترجمات بمودلاتها
     - زر "هذه الأفضل" يضع `is_preferred=1`
     - زر "احذف الباقي" يبقي الترجمة المختارة فقط

3. **حوار تصدير translations.txt**:
   ```
   ☑ تطبيق الدمج الهرمي تلقائياً
   ☐ مراجعة التعارضات يدوياً قبل التصدير
       (يفتح حواراً لـ N تعارضاً تحتاج قراراً)
   ```

### خطوات التنفيذ (لما نحتاج هذه الميزة)

1. **migration schema**: قراءة كل الكاش، إعادة كتابته بـ schema الجديد (سكريبت `tools/migrate_cache_v2.py`)
2. **تحديث `cache.put()`** لقبول صفوف متعدّدة
3. **إضافة `cache.get_best(text, game)`** يطبّق الخوارزمية الهرمية
4. **GUI لإدارة أولوية المودلات** في صفحة الإعدادات
5. **GUI لحلّ التعارضات** في صفحة الكاش
6. **تحديث `export_static_translations_txt`** ليستخدم `get_best()` بدل `get()`
7. **اختبار شامل** على كاش به ترجمات من 3+ مودلات

### لماذا الآن غير مطلوب

- الكاش الحالي: 1,334 نص × ترجمة واحدة لكل نص = لا تعارض ممكن
- المجموع 93 + 1 + 1,240 = 1,334 (لا تداخل بين المودلات حالياً)
- لو شغّلت نفس اللعبة مرة أخرى بـ "بدون كاش" وبمودل مختلف، سيبدأ التعارض الحقيقي

عند الوصول لـ 2+ ترجمة لنفس النص، يأتي وقت تنفيذ هذه الخطة.
