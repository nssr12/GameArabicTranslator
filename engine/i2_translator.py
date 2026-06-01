"""
engine/i2_translator.py — معالج الترجمة الدفعية لملف I2Languages

يعالج ملفات I2.Loc المستخرجة من UABEA. يدعم:
  - تحليل البنية واستخراج النصوص الإنجليزية
  - الترجمة الدفعية مع reuse للكاش (per-game)
  - cascade fallback عبر FilteredTranslator
  - حقن الترجمات في فتحة عربية (موجودة أو جديدة)
  - حفظ الملف المعدّل + إنتاج Arabic-only JSON للمود

استخدام برمجي:
    bt = I2BatchTranslator(
        json_path="...I2Languages-resources.assets-34311.json",
        game_name="Farthest Frontier",
        engine=engine,
        cache=cache,
    )
    bt.analyze()              # يملأ stats
    bt.run(on_progress=...)   # دفعي
    bt.save_modified("...modified.json")
    bt.export_arabic_only("...arabic_only.json")
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from engine.filtered_translator import FilteredTranslator, get_global_tag_mode


# ───── Helpers — IO ─────────────────────────────────────────────────────────────

def load_i2_json(path: str) -> dict:
    """يقرأ ملف I2Languages JSON. يدعم UTF-8 و BOM."""
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_i2_json(data: dict, path: str, pretty: bool = True) -> None:
    """يحفظ ملف I2Languages JSON. UTF-8 بدون BOM، نفس بنية UABEA."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if pretty:
            json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


# ───── Helpers — Analysis ──────────────────────────────────────────────────────

def get_languages(data: dict) -> list[dict]:
    """يُرجع قائمة [{Name, Code, Flags}, ...]."""
    return data.get("mSource", {}).get("mLanguages", {}).get("Array", []) or []


def get_terms(data: dict) -> list[dict]:
    """يُرجع قائمة الترمز (كل عنصر فيه Term + Languages.Array)."""
    return data.get("mSource", {}).get("mTerms", {}).get("Array", []) or []


def find_language_index(data: dict, code_or_name: str) -> int:
    """يبحث عن فهرس لغة بالاسم أو الكود (case-insensitive). يُرجع -1 إن لم توجد."""
    needle = (code_or_name or "").lower()
    for i, lang in enumerate(get_languages(data)):
        if str(lang.get("Code", "")).lower() == needle:
            return i
        if str(lang.get("Name", "")).lower() == needle:
            return i
    return -1


def english_index(data: dict) -> int:
    """يُرجع فهرس الإنجليزية (افتراضياً 0). يحاول en/English أولاً، ثم 0."""
    idx = find_language_index(data, "en")
    if idx >= 0:
        return idx
    idx = find_language_index(data, "English")
    if idx >= 0:
        return idx
    return 0


# نصوص قصيرة جداً أو نصوص-كود لا تستحق الترجمة
_SKIP_REGEX = re.compile(
    r"^\s*$"                       # فارغ
    r"|^[\W_]+$"                   # رموز فقط
    r"|^\d+(\.\d+)?$"              # أرقام
    r"|^[A-Z]{1,4}\d+$"            # كود مثل ACH001
)


def should_translate_english(text: str) -> bool:
    """يقرّر هل النص الإنجليزي يستحق ترجمة (يتجاوز الرموز/الأكواد القصيرة)."""
    if not text or not isinstance(text, str):
        return False
    if _SKIP_REGEX.match(text):
        return False
    # لا حروف إنجليزية أبداً (نص رموز/أرقام)
    if not re.search(r"[A-Za-z]", text):
        return False
    return True


# ───── Stats ───────────────────────────────────────────────────────────────────

@dataclass
class I2Stats:
    total_terms: int = 0
    translatable_terms: int = 0     # تستحق ترجمة
    skip_pattern_hits: int = 0      # match لـ skip_patterns عامة
    has_arabic_slot: bool = False
    arabic_index: int = -1
    language_count: int = 0
    languages: list = field(default_factory=list)  # [{Name, Code}]


# ───── Runtime counters ────────────────────────────────────────────────────────

@dataclass
class I2Progress:
    total: int = 0
    done: int = 0
    cache_hits: int = 0
    new_translations: int = 0
    skipped: int = 0
    failed: int = 0
    current_term: str = ""
    current_text: str = ""
    elapsed_sec: float = 0.0

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.done)

    @property
    def percent(self) -> int:
        if self.total <= 0:
            return 0
        return min(100, int(self.done * 100 / self.total))

    def eta_sec(self) -> float:
        if self.done <= 0 or self.total <= 0:
            return 0.0
        rate = self.done / max(0.001, self.elapsed_sec)
        return self.remaining / max(0.001, rate)


# ───── Core batch translator ───────────────────────────────────────────────────

class I2BatchTranslator:
    """يدير الترجمة الدفعية لملف I2.

    خصائص التحكم (يُمكن تغييرها بين stop/resume):
      use_cache_read    : ابحث في الكاش أولاً
      use_cache_write   : احفظ النتائج في الكاش
      use_skip_patterns : تجاوز نصوص skip_patterns
      use_static_txt    : ابحث في translations.txt قبل الـ AI
      max_text_len      : تجاوز النصوص الأطول من هذا (0 = بدون حد)
      tag_mode_override : قيمة tag_mode محددة، None = من config
      delay_ms          : تأخير بين الترجمات (للضغط على الـ AI)
      model_suffix      : لاحقة تُضاف لاسم المودل عند الكتابة في الكاش
                          (مثلاً ":i2" → "qwen2.5:14b:i2") لتمييز ترجمات I2
                          عن ترجمات البروكسي عند التصدير. None/"" = بدون لاحقة.
    """

    def __init__(
        self,
        json_path: str,
        game_name: str,
        engine,
        cache,
        *,
        use_cache_read: bool = True,
        use_cache_write: bool = True,
        use_skip_patterns: bool = True,
        use_static_txt: bool = False,
        max_text_len: int = 0,
        tag_mode_override: Optional[str] = None,
        delay_ms: int = 0,
        model_suffix: str = ":i2",
    ):
        self.json_path = json_path
        self.game_name = game_name
        self.engine = engine
        self.cache = cache

        self.use_cache_read = use_cache_read
        self.use_cache_write = use_cache_write
        self.use_skip_patterns = use_skip_patterns
        self.use_static_txt = use_static_txt
        self.max_text_len = max_text_len
        self.tag_mode_override = tag_mode_override
        self.delay_ms = delay_ms
        self.model_suffix = model_suffix or ""

        # الحالة المحلية
        self._data: Optional[dict] = None
        self._stats = I2Stats()
        self._progress = I2Progress()

        # خريطة الترجمات: term_id → arabic_text
        # نملأ هذه على مدار الـ run، نحقنها في النهاية عبر inject_arabic
        self._translations: dict[str, str] = {}
        # الترمز اللي تم تخطّيها (للسجل)
        self._skipped_terms: list[tuple[str, str]] = []  # (term, reason)
        # الترمز اللي فشلت
        self._failed_terms: list[tuple[str, str]] = []   # (term, en_text)

        # تحكم الـ thread
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # set = running, clear = paused
        self._skip_current = threading.Event()

        # static translations cache
        self._static_tr: dict[str, str] = {}

    # ── API: properties ─────────────────────────────────────────────────────

    @property
    def data(self) -> Optional[dict]:
        return self._data

    @property
    def stats(self) -> I2Stats:
        return self._stats

    @property
    def progress(self) -> I2Progress:
        return self._progress

    @property
    def translations(self) -> dict[str, str]:
        """{term_id: arabic_text}"""
        return self._translations

    @property
    def skipped_terms(self) -> list[tuple[str, str]]:
        return list(self._skipped_terms)

    @property
    def failed_terms(self) -> list[tuple[str, str]]:
        return list(self._failed_terms)

    # ── API: تحليل ──────────────────────────────────────────────────────────

    def analyze(self) -> I2Stats:
        """يقرأ الملف ويملأ stats. يجب استدعاؤه قبل run()."""
        self._data = load_i2_json(self.json_path)
        langs = get_languages(self._data)
        terms = get_terms(self._data)

        s = I2Stats()
        s.total_terms = len(terms)
        s.language_count = len(langs)
        s.languages = [
            {"Name": l.get("Name", ""), "Code": l.get("Code", "")} for l in langs
        ]
        s.arabic_index = find_language_index(self._data, "ar")
        if s.arabic_index < 0:
            s.arabic_index = find_language_index(self._data, "Arabic")
        s.has_arabic_slot = s.arabic_index >= 0

        # نُحمّل skip_patterns مرة واحدة
        skip_pats = self._load_skip_patterns() if self.use_skip_patterns else []

        en_idx = english_index(self._data)
        for term_obj in terms:
            languages_arr = term_obj.get("Languages", {}).get("Array", [])
            if en_idx >= len(languages_arr):
                continue
            en_text = languages_arr[en_idx]
            if not should_translate_english(en_text):
                continue
            if self._matches_skip_patterns(en_text, skip_pats):
                s.skip_pattern_hits += 1
                continue
            s.translatable_terms += 1

        self._stats = s
        return s

    # ── API: التشغيل ────────────────────────────────────────────────────────

    def run(
        self,
        *,
        on_progress: Optional[Callable[[I2Progress], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        on_term_done: Optional[Callable[[str, str, str, str], None]] = None,
        # (term_id, en_text, ar_text, source)  source = "cache" | "static" | "ai" | "failed" | "skipped"
    ) -> None:
        """يبدأ الترجمة الدفعية (blocking — استخدم QThread). يحترم stop/pause.

        لا يحفظ الملف؛ يبني self._translations فقط.
        استخدم save_modified() أو export_arabic_only() لإنتاج الملف بعد ذلك.
        """
        if self._data is None:
            self.analyze()

        if self.use_static_txt:
            self._static_tr = self._load_static_translations()

        terms = get_terms(self._data)
        en_idx = english_index(self._data)
        skip_pats = self._load_skip_patterns() if self.use_skip_patterns else []

        # filtered translator مع cascade
        ft = FilteredTranslator(
            self.engine,
            tag_mode=self.tag_mode_override or get_global_tag_mode(),
        )

        self._progress = I2Progress(total=self._stats.translatable_terms or self._stats.total_terms)
        self._stop_event.clear()
        self._pause_event.set()
        start_time = time.time()

        def _emit_progress():
            self._progress.elapsed_sec = time.time() - start_time
            if on_progress:
                try:
                    on_progress(self._progress)
                except Exception:
                    pass

        def _emit_log(msg: str):
            if on_log:
                try:
                    on_log(msg)
                except Exception:
                    pass

        if on_log:
            _emit_log(f"▶ بدأت ترجمة {self._progress.total} ترم — اللعبة: {self.game_name}")
            suffix_note = f"|suffix={self.model_suffix!r}" if self.model_suffix else "|بلا suffix"
            _emit_log(f"  tag_mode={ft.tag_mode} | cache_read={self.use_cache_read} | cache_write={self.use_cache_write} {suffix_note}")

        for term_obj in terms:
            if self._stop_event.is_set():
                _emit_log("⏹ تم الإيقاف بواسطة المستخدم")
                break

            # pause check (loop until resume)
            while not self._pause_event.is_set() and not self._stop_event.is_set():
                time.sleep(0.1)
            if self._stop_event.is_set():
                break

            term_id = term_obj.get("Term", "")
            languages_arr = term_obj.get("Languages", {}).get("Array", [])
            if en_idx >= len(languages_arr):
                continue
            en_text = languages_arr[en_idx] or ""

            # تخطّى تلقائياً
            if not should_translate_english(en_text):
                self._progress.skipped += 1
                self._skipped_terms.append((term_id, "non-translatable"))
                continue

            if self._matches_skip_patterns(en_text, skip_pats):
                self._progress.skipped += 1
                self._skipped_terms.append((term_id, "skip_pattern"))
                if on_term_done:
                    try:
                        on_term_done(term_id, en_text, "", "skipped")
                    except Exception:
                        pass
                continue

            if self.max_text_len > 0 and len(en_text) > self.max_text_len:
                self._progress.skipped += 1
                self._skipped_terms.append((term_id, f"too_long({len(en_text)})"))
                if on_term_done:
                    try:
                        on_term_done(term_id, en_text, "", "skipped")
                    except Exception:
                        pass
                continue

            self._progress.current_term = term_id
            self._progress.current_text = en_text
            _emit_progress()

            # محاولة 1: translations.txt
            ar_text: Optional[str] = None
            source = ""
            if self.use_static_txt:
                ar_text = self._static_tr.get(en_text)
                if ar_text:
                    source = "static"

            # محاولة 2: cache
            if not ar_text and self.use_cache_read:
                try:
                    ar_text = self.cache.get_best(self.game_name, en_text)
                except Exception as e:
                    _emit_log(f"⚠ خطأ في قراءة الكاش: {e}")
                if ar_text:
                    source = "cache"
                    self._progress.cache_hits += 1

            # محاولة 3: AI مع cascade
            if not ar_text:
                if self._skip_current.is_set():
                    self._skip_current.clear()
                    self._progress.skipped += 1
                    self._skipped_terms.append((term_id, "manual_skip"))
                    if on_term_done:
                        try:
                            on_term_done(term_id, en_text, "", "skipped")
                        except Exception:
                            pass
                    self._progress.done += 1
                    _emit_progress()
                    continue

                try:
                    result, mode = ft.translate_with_info(en_text)
                except Exception as e:
                    _emit_log(f"❌ {term_id}: استثناء: {e}")
                    result, mode = None, "exception"

                if result:
                    ar_text = result
                    source = "ai"
                    self._progress.new_translations += 1
                    if self.use_cache_write:
                        try:
                            active_model = self._resolve_active_model_name()
                            tagged_model = active_model + self.model_suffix
                            self.cache.put(
                                self.game_name, en_text, ar_text,
                                model=tagged_model, mode_used=mode or "",
                            )
                        except Exception as e:
                            _emit_log(f"⚠ فشل حفظ الكاش: {e}")
                else:
                    self._progress.failed += 1
                    self._failed_terms.append((term_id, en_text))
                    if on_term_done:
                        try:
                            on_term_done(term_id, en_text, "", "failed")
                        except Exception:
                            pass

            if ar_text:
                self._translations[term_id] = ar_text
                if on_term_done:
                    try:
                        on_term_done(term_id, en_text, ar_text, source)
                    except Exception:
                        pass

            self._progress.done += 1
            _emit_progress()

            if self.delay_ms > 0:
                time.sleep(self.delay_ms / 1000.0)

        if on_log:
            self._progress.elapsed_sec = time.time() - start_time
            _emit_log(
                f"✔ انتهت الترجمة | تم: {self._progress.done} "
                f"| كاش: {self._progress.cache_hits} "
                f"| AI: {self._progress.new_translations} "
                f"| تخطّى: {self._progress.skipped} "
                f"| فشل: {self._progress.failed} "
                f"| الوقت: {self._progress.elapsed_sec:.1f}s"
            )

    # ── API: التحكم ─────────────────────────────────────────────────────────

    def stop(self):
        self._stop_event.set()
        self._pause_event.set()  # حرّك من الـ pause

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def skip_current(self):
        """تخطّى الترم الحالي (يُلغى إذا لم يكن قيد الترجمة AI)."""
        self._skip_current.set()

    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    def is_stopped(self) -> bool:
        return self._stop_event.is_set()

    # ── API: الحقن ──────────────────────────────────────────────────────────

    def inject_arabic(self, *, language_name: str = "Arabic", language_code: str = "ar") -> int:
        """يحقن self._translations في self._data، في فتحة عربية موجودة أو جديدة.
        يُرجع فهرس اللغة العربية بعد الحقن."""
        if self._data is None:
            raise RuntimeError("analyze() must run first")

        arabic_idx = find_language_index(self._data, language_code)
        if arabic_idx < 0:
            arabic_idx = find_language_index(self._data, language_name)

        if arabic_idx < 0:
            # نضيف لغة جديدة
            langs_arr = self._data["mSource"]["mLanguages"]["Array"]
            langs_arr.append({
                "Name": language_name,
                "Code": language_code,
                "Flags": 0,
            })
            arabic_idx = len(langs_arr) - 1
            # نضيف عنصراً فارغاً في نهاية Languages array لكل ترم
            terms = get_terms(self._data)
            for t in terms:
                arr = t.get("Languages", {}).get("Array")
                if arr is not None:
                    arr.append("")
                flags = t.get("Flags", {}).get("Array")
                if flags is not None:
                    flags.append(0)

        # نملأ الترجمات
        en_idx = english_index(self._data)
        terms = get_terms(self._data)
        for term_obj in terms:
            term_id = term_obj.get("Term", "")
            arr = term_obj.get("Languages", {}).get("Array")
            if arr is None or arabic_idx >= len(arr):
                continue
            if term_id in self._translations:
                arr[arabic_idx] = self._translations[term_id]
            elif not arr[arabic_idx]:
                # لو الفتحة فارغة، اتركها فارغة (I2 fallback يعرض الإنجليزي)
                # أو إذا فضّل المستخدم: انسخ الإنجليزي
                if en_idx < len(arr):
                    arr[arabic_idx] = arr[en_idx]

        return arabic_idx

    def save_modified(self, output_path: str, *, pretty: bool = True) -> None:
        """يحفظ الملف المعدّل (بعد inject_arabic) بنفس بنية I2 الأصلية."""
        if self._data is None:
            raise RuntimeError("no data to save")
        save_i2_json(self._data, output_path, pretty=pretty)

    def export_arabic_only(
        self,
        output_path: str,
        *,
        pre_shape: bool = True,
    ) -> int:
        """يكتب ملف JSON مبسّط: {term_id: arabic_text} — للمود C#.

        pre_shape=True (افتراضي): يطبّق Arabic presentation forms + BiDi reversal
        قبل الحفظ. النتيجة: نص جاهز لـ Unity TMP بدون حاجة لـ ArabicFontFixer.
        التاقات (<b>, <color>) و placeholders ({0}, {name}) محمية من العكس.

        pre_shape=False: يحفظ النص العربي المنطقي كما هو — مفيد لو تستخدم
        ArabicFontFixer في اللعبة (يطبّق التشكيل runtime).

        يُرجع عدد الترمز المكتوبة.
        """
        out_dict = self._translations
        if pre_shape:
            try:
                from engine.arabic_shaper import shape_dict_for_tmp, libs_available
                if libs_available():
                    out_dict = shape_dict_for_tmp(out_dict, protect_tags=True)
            except Exception:
                pass

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(out_dict, f, ensure_ascii=False, indent=2)
        return len(out_dict)

    def load_arabic_only(self, input_path: str) -> int:
        """يحمّل {term_id: arabic_text} من ملف JSON موجود (للاستئناف).
        يدمج مع self._translations الموجودة. يُرجع عدد المضاف."""
        if not os.path.isfile(input_path):
            return 0
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        added = 0
        for k, v in data.items():
            if k not in self._translations and v:
                self._translations[k] = v
                added += 1
        return added

    # ── Internal ────────────────────────────────────────────────────────────

    def _resolve_active_model_name(self) -> str:
        """يُرجع الاسم الفعلي للمودل النشط (مثل qwen2.5:14b بدل ollama)."""
        try:
            key = self.engine.get_active_model() or "unknown"
            tr = self.engine.get_translator(key)
            actual = getattr(tr, "model", None)
            return actual or key
        except Exception:
            return "unknown"

    def _load_skip_patterns(self) -> list[str]:
        try:
            from engine import skip_patterns
            return skip_patterns.get_patterns()
        except Exception:
            return []

    def _matches_skip_patterns(self, text: str, patterns: list[str]) -> bool:
        if not patterns:
            return False
        try:
            from engine import skip_patterns
            return skip_patterns.matches(text, patterns=patterns) is not None
        except Exception:
            from fnmatch import fnmatchcase
            for pat in patterns:
                if fnmatchcase(text, pat):
                    return True
            return False

    def _load_static_translations(self) -> dict[str, str]:
        """يحمّل ترجمات يدوية من translations.txt للعبة (إن وُجد).
        نحتاج مسار اللعبة من game_manager — نُمرّر None لو غير متاح."""
        try:
            from engine import static_translations
            # نبحث في كل ملفات configs لـ game_path
            import json as _json, os as _os
            cfg_dir = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "games", "configs")
            for fname in _os.listdir(cfg_dir):
                if not fname.endswith(".json"):
                    continue
                base = fname[:-5]
                if base.lower() == self.game_name.lower():
                    with open(_os.path.join(cfg_dir, fname), "r", encoding="utf-8") as f:
                        cfg = _json.load(f)
                    game_path = cfg.get("game_path") or cfg.get("path") or ""
                    if game_path:
                        data, _ = static_translations.load(game_path)
                        return data or {}
        except Exception:
            pass
        return {}


__all__ = [
    "I2BatchTranslator", "I2Stats", "I2Progress",
    "load_i2_json", "save_i2_json",
    "get_languages", "get_terms", "find_language_index", "english_index",
    "should_translate_english",
]
