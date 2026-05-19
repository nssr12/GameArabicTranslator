"""
Embedded HTTP proxy server — bridges XUnity.AutoTranslator to the translation engine.
XUnity sends GET /?text=<english>  →  expects plain-text Arabic back.
"""
import http.server
import re as _re
import time
import urllib.parse
import threading
from collections import deque

from .tag_filter import TieredTagFilter, BulletproofTagFilter
from .tag_validator import validate_bulletproof_markers, summarize_issues


def _needs_translation(text: str) -> bool:
    """يعيد False للأرقام والرموز والنصوص غير القابلة للترجمة."""
    t = text.strip()
    if len(t) < 3:
        return False
    # نطلب على الأقل تتابع حرفين لاتينيين أو عربيين — يستبعد "3x4", "+40x40"
    if not _re.search(r'[a-zA-Z؀-ۿ]{2,}', t):
        return False
    # يحتوي خطوطاً غير إنجليزية (صيني/ياباني/روسي/كوري)
    if _re.search(r'[　-鿿Ѐ-ӿ぀-ヿ가-힯]', t):
        return False
    return True


def _pre_wrap(text: str, char_limit: int) -> str:
    """يقسّم النص عند حدود الكلمات قبل أن يصل TMP لتجنّب مشكلة ترتيب الأسطر."""
    if char_limit <= 0 or len(text) <= char_limit:
        return text
    words = text.split(' ')
    lines, current = [], ''
    for word in words:
        candidate = (current + ' ' + word) if current else word
        if current and len(candidate) > char_limit:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return '\n'.join(lines) if len(lines) > 1 else text


def _apply_rtl(text: str, apply_bidi: bool = True, char_limit: int = 0) -> str:
    """يشكّل الحروف العربية للعرض الصحيح في TMP.
    apply_bidi=True  → reshape + get_display  (ألعاب LTR بدون دعم RTL مدمج)
    apply_bidi=False → reshape فقط            (ألعاب BepInEx/RTL-mod تعالج الاتجاه بنفسها)
    char_limit>0     → pre-wrap قبل bidi لمنع TMP من تقسيم الأسطر بترتيب خاطئ
    """
    try:
        import arabic_reshaper

        def _process(seg: str) -> str:
            if not seg.strip():
                return seg
            import re
            if '<' not in seg:
                shaped = arabic_reshaper.reshape(seg)
                if apply_bidi:
                    from bidi.algorithm import get_display
                    return get_display(shaped)
                return shaped
            TAG_RE = re.compile(r'<[^>]+>')
            phs: dict = {}
            ctr = [0]
            def rep(m):
                ph = chr(0xE000 + ctr[0]); phs[ph] = m.group(0); ctr[0] += 1; return ph
            protected = TAG_RE.sub(rep, seg)
            shaped = arabic_reshaper.reshape(protected)
            if apply_bidi:
                from bidi.algorithm import get_display
                visual = get_display(shaped)
            else:
                visual = shaped
            for ph, tag in phs.items():
                visual = visual.replace(ph, tag)
            return visual

        # pre-wrap عند حد الأحرف (مستقل عن apply_bidi)
        if char_limit > 0:
            if '\\n' in text:
                text = '\\n'.join(_pre_wrap(p, char_limit) for p in text.split('\\n'))
            elif '\n' in text:
                text = '\n'.join(_pre_wrap(line, char_limit) for line in text.split('\n'))
            else:
                text = _pre_wrap(text, char_limit)

        if '\\n' in text:
            lines = [_process(p) for p in text.split('\\n') if p.strip()]
            return '\n'.join(lines)

        if '\n' in text:
            lines = [_process(line) for line in text.split('\n') if line.strip()]
            return '\n'.join(lines)

        return _process(text)

    except Exception:
        return text


class _Handler(http.server.BaseHTTPRequestHandler):
    proxy: "ProxyServer | None" = None   # shared with all handler instances

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        text   = params.get("text", [""])[0].strip()

        if parsed.path == "/health":
            self._respond(200, b'{"status":"running"}', "application/json")
            return

        if not text:
            self._respond(200, b"", "text/plain")
            return

        # تجاهل الأرقام والرموز والنصوص القصيرة التي لا تحتاج ترجمة
        if not _needs_translation(text):
            self._respond(200, text.encode("utf-8"), "text/plain; charset=utf-8")
            return

        srv = self.__class__.proxy
        if srv:
            srv._stat_request_started()
        try:
            # XUnity قد يرسل النص بعد أن يُقسّمه TMP بناءً على عرض الصندوق الإنجليزي
            # → نحذف هذه الأسطر ونُرجع جملة واحدة متصلة ليُعيد TMP تقسيمها بالعربية
            text_key = " ".join(text.replace("\\n", " ").replace("\n", " ").split())
            if not text_key.strip():
                text_key = text
            result = srv._translate(text_key) if srv else (None, False, False)
            arabic, from_cache, was_unchanged = result
            if not arabic:
                arabic = text
            arabic = _apply_rtl(arabic,
                                apply_bidi=srv._apply_bidi if srv else True,
                                char_limit=srv._char_limit if srv else 0)
            tag = "📦" if from_cache else ("⏭" if was_unchanged else "🔄")
            print(f"[Proxy] {tag} {text[:40]:40s} => {arabic[:40]}")
            if srv and srv.log_callback and not was_unchanged:
                # لا نسجّل النصوص بلا تغيير في الـ log حتى لا تُغرقه
                try:
                    srv.log_callback(f"{text[:45]}  ⟶  {arabic[:45]}")
                except Exception:
                    pass
            if srv:
                srv._stat_request_finished(from_cache, unchanged=was_unchanged)
            self._respond(200, arabic.encode("utf-8"), "text/plain; charset=utf-8")
        except Exception as e:
            print(f"[Proxy] Error: {e}")
            if srv:
                srv._stat_request_finished(False, failed=True)
            self._respond(200, text.encode("utf-8"), "text/plain; charset=utf-8")

    def _respond(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class ProxyServer:
    """
    Embeddable translation proxy.
    Start/stop from the main (Qt) thread; HTTP server runs in a daemon thread.
    """

    PORT = 5001

    def __init__(self, engine=None, cache=None):
        self._engine       = engine
        self._cache        = cache
        self._game_name    = ""
        self._apply_bidi   = True   # False for games with built-in RTL mod (BepInEx)
        self._char_limit   = 0      # >0 → pre-wrap at this char count before bidi
        self._strip_tags   = False  # ⚠ deprecated — يُحوَّل لـ tag_mode='strip' لو True
        self._tag_mode     = "inline"  # "inline" | "strip" | "tiered" | "bulletproof"
        self._tiered_filter      = TieredTagFilter()
        self._bulletproof_filter = BulletproofTagFilter()
        self._timeout      = 0      # >0 → سيُطبَّق على المحرّك عند start()
        self._server: http.server.HTTPServer | None = None
        self._thread: threading.Thread | None       = None
        self.log_callback  = None   # callable(str) | None — thread-safe via Qt Signal
        # إحصاءات الترجمة (Thread-safe عبر Lock)
        self._stats_lock     = threading.Lock()
        self._pending_count  = 0          # عدد الطلبات قيد المعالجة الآن
        self._translated_engine_count = 0 # ترجمات فعلية (نتيجة ≠ الأصل)
        self._translated_cache_count  = 0 # ضربات الكاش
        self._unchanged_count         = 0 # نصوص أرجعها الـ AI بدون تغيير (أسماء، أرقام)
        self._recent_translations: deque = deque(maxlen=120)  # طوابع زمنية للترجمات الأخيرة (لحساب المعدل)
        self.stats_callback  = None   # callable(dict) | None — تُستدعى بعد كل تحديث إحصاءات

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def game_name(self) -> str:
        return self._game_name

    def set_backend(self, engine, cache):
        self._engine = engine
        self._cache  = cache

    def set_strip_tags(self, value: bool):
        """⚠ Deprecated: استخدم set_tag_mode بدلاً منها.
        يُحافظ على التوافق: True → 'strip'، False → 'inline'."""
        self._strip_tags = bool(value)
        self._tag_mode = "strip" if value else "inline"

    def set_tag_mode(self, mode: str):
        """تبديل وضع معالجة التاقات.
        القيم: 'inline' | 'strip' | 'tiered' | 'bulletproof'"""
        if mode not in ("inline", "strip", "tiered", "bulletproof"):
            mode = "inline"
        self._tag_mode = mode
        self._strip_tags = (mode == "strip")  # توافق رجعي

    def get_tag_mode(self) -> str:
        return self._tag_mode

    def set_timeout(self, seconds: float):
        """تغيير مهلة المحرّك أثناء التشغيل."""
        self._timeout = max(0.0, float(seconds))
        if self._engine is not None and self._timeout > 0:
            try:
                self._engine._timeout = self._timeout
            except Exception:
                pass

    def get_timeout(self) -> float:
        if self._timeout > 0:
            return self._timeout
        if self._engine is not None:
            try:
                return float(getattr(self._engine, "_timeout", 60))
            except Exception:
                return 60.0
        return 60.0

    def start(self, game_name: str, cfg: dict | None = None) -> tuple[bool, str]:
        """Start server for *game_name*. If already running, just swap the game name."""
        _cfg = cfg or {}
        self._apply_bidi  = _cfg.get("apply_bidi", True)
        self._char_limit  = int(_cfg.get("text_reorder_char_limit", 0))
        # tag_mode: المفضّل. strip_tags_before_translate: قديم — للتوافق
        tag_mode_cfg = _cfg.get("tag_mode")
        if tag_mode_cfg in ("inline", "strip", "tiered"):
            self.set_tag_mode(tag_mode_cfg)
        else:
            self.set_strip_tags(bool(_cfg.get("strip_tags_before_translate", False)))
        self._timeout     = float(_cfg.get("translate_timeout", 0) or 0)
        # طبّق المهلة على المحرّك إن أمكن
        if self._timeout > 0 and self._engine is not None:
            try:
                self._engine._timeout = self._timeout
            except Exception:
                pass
        if self.is_running:
            self._game_name = game_name
            return True, f"تم تحويل الخادم إلى «{game_name}»"

        self._game_name = game_name
        _Handler.proxy  = self

        try:
            self._server = http.server.HTTPServer(("127.0.0.1", self.PORT), _Handler)
        except OSError as e:
            return False, f"تعذّر فتح المنفذ {self.PORT}: {e}"

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="TranslationProxy",
        )
        self._thread.start()
        return True, f"✅  خادم الترجمة يعمل على http://127.0.0.1:{self.PORT}/"

    def stop(self) -> str:
        """Stop the server. Safe to call even when already stopped."""
        if not self.is_running:
            return "الخادم لم يكن يعمل"
        try:
            self._server.shutdown()
        except Exception:
            pass
        self._server    = None
        self._thread    = None
        self._game_name = ""
        return "⛔  توقّف خادم الترجمة الفورية"

    # ── Stats ─────────────────────────────────────────────────────────────────

    def _stat_request_started(self):
        with self._stats_lock:
            self._pending_count += 1
        self._emit_stats()

    def _stat_request_finished(self, from_cache: bool, failed: bool = False,
                               unchanged: bool = False):
        now = time.monotonic()
        with self._stats_lock:
            self._pending_count = max(0, self._pending_count - 1)
            if not failed:
                if from_cache:
                    self._translated_cache_count += 1
                elif unchanged:
                    self._unchanged_count += 1
                else:
                    self._translated_engine_count += 1
                self._recent_translations.append(now)
        self._emit_stats()

    def get_stats(self) -> dict:
        """يعيد إحصاءات الترجمة الحالية. آمنة من أي خيط."""
        now = time.monotonic()
        with self._stats_lock:
            # حساب المعدل: ترجمات في آخر ثانية واحدة
            recent = [t for t in self._recent_translations if now - t <= 1.0]
            rate_per_sec = len(recent)
            return {
                "pending": self._pending_count,
                "engine_count": self._translated_engine_count,
                "cache_count": self._translated_cache_count,
                "unchanged_count": self._unchanged_count,
                "total_count": (self._translated_engine_count +
                                self._translated_cache_count +
                                self._unchanged_count),
                "rate_per_sec": rate_per_sec,
            }

    def _emit_stats(self):
        if not self.stats_callback:
            return
        try:
            self.stats_callback(self.get_stats())
        except Exception:
            pass

    def reset_stats(self):
        with self._stats_lock:
            self._pending_count = 0
            self._translated_engine_count = 0
            self._translated_cache_count = 0
            self._unchanged_count = 0
            self._recent_translations.clear()
        self._emit_stats()

    # ── Internal ──────────────────────────────────────────────────────────────

    _HTML_TAG_RE_PROXY = _re.compile(r"</?[a-zA-Z][^<>]{0,120}>")

    def _resolve_model_name(self) -> str:
        """يُرجع اسم المودل الفعلي (مثل llama3:8b) بدل المفتاح (ollama).
        OllamaTranslator يحفظ الاسم الحقيقي في self.model."""
        if not self._engine:
            return "unknown"
        try:
            key = self._engine.get_active_model() or "unknown"
            tr = self._engine.get_translator(key) if hasattr(self._engine, "get_translator") else None
            actual = getattr(tr, "model", None) if tr else None
            return actual or key
        except Exception:
            return "unknown"

    def _translate_with_tag_stripping(self, text: str):
        """ينزع تاقات HTML قبل إرسال النص للمحرّك ثم يُعيدها لموضعها.
        نستخدم محارف PUA كعلامات لأن المودل عادةً لا يلمسها."""
        tags: list = []
        def replace(m):
            ph = chr(0xE000 + len(tags))
            tags.append(m.group(0))
            return ph
        cleaned = self._HTML_TAG_RE_PROXY.sub(replace, text)
        if not tags:
            return self._engine.translate(text)
        translated = self._engine.translate(cleaned)
        if not translated:
            return None
        for idx, tag in enumerate(tags):
            translated = translated.replace(chr(0xE000 + idx), tag)
        return translated

    def _translate_with_bulletproof(self, text: str):
        """ترجمة بنظام Bulletproof: علامات ⟦N⟧ + تحقق صارم + cascade fallback.

        السلسلة:
          1. جرّب bulletproof (⟦N⟧)         ← الأقوى
          2. عند الفشل: جرّب tiered ([tN])  ← أقل صرامة
          3. عند الفشل: جرّب strip (PUA)   ← آخر محاولة
          4. عند الفشل النهائي: أعد النص الأصلي (لإعادة محاولة لاحقة)
                                            ← الضمان 100% للتاقات

        يُرجع (translated, mode_succeeded) أو (None, modes_tried_csv)
        """
        # في cascade نُقسّم الوقت على 3 محاولات حتى لا يتجاوز مهلة XUnity
        # نحفظ التايم آوت الأصلي ونستعيده في finally
        original_timeout = getattr(self._engine, "_timeout", 60.0)
        cascade_per_attempt = max(25.0, original_timeout / 3)
        try:
            try:
                self._engine._timeout = cascade_per_attempt
            except Exception:
                pass
            return self._do_bulletproof_cascade(text)
        finally:
            try:
                self._engine._timeout = original_timeout
            except Exception:
                pass

    def _do_bulletproof_cascade(self, text: str):
        """التنفيذ الفعلي لـ cascade — مفصول لتمكين try/finally على timeout."""
        # محاولة 1: bulletproof
        cleaned, tokens = self._bulletproof_filter.strip(text)
        modes_tried: list = []
        if tokens:
            modes_tried.append("bulletproof")
            response = self._engine.translate(cleaned)
            if response:
                val = validate_bulletproof_markers(response, tokens)
                if val.valid:
                    restored = self._bulletproof_filter.restore(response, tokens)
                    if restored is not None:
                        return restored, "bulletproof"
                # سجّل سبب الفشل للـ log
                if self.log_callback:
                    try:
                        self.log_callback(f"⚠ bulletproof فشل: {summarize_issues(val)}")
                    except Exception:
                        pass
        else:
            # لا تاقات معقدة → ترجمة عادية مع تاقات inline
            response = self._engine.translate(text)
            if response:
                return response, "bulletproof"

        # محاولة 2: tiered ([tN])
        modes_tried.append("tiered")
        cleaned2, tokens2 = self._tiered_filter.strip(text)
        if tokens2:
            response = self._engine.translate(cleaned2)
            if response:
                restored = self._tiered_filter.restore(response, tokens2)
                if restored is not None:
                    return restored, "tiered"

        # محاولة 3: strip (PUA)
        modes_tried.append("strip")
        response = self._translate_with_tag_stripping(text)
        if response:
            return response, "strip"

        # كل المحاولات فشلت → نُسجّل ونُرجع المحاولات للـ caller
        return None, ",".join(modes_tried)

    def _translate_with_tiered_tags(self, text: str):
        """ترجمة بنظام Tiered: تاقات بسيطة inline، معقدة بـ [tN]، مستقلة بـ [sN].
        يُعيد None إذا تلف أحد markers في رد المودل (نُسجّل فشلاً للمحاولة لاحقاً)."""
        cleaned, tokens = self._tiered_filter.strip(text)
        if not tokens:
            # لا توجد تاقات معقدة → ترجمة عادية
            return self._engine.translate(text)
        translated = self._engine.translate(cleaned)
        if not translated:
            return None
        restored = self._tiered_filter.restore(translated, tokens)
        if restored is None:
            # المودل أتلف markers — نُسجّل سبب فشل واضح
            try:
                self._engine._last_error = (
                    "تلف markers Tiered Tag في رد المودل — جرّب وضع inline أو strip"
                )
            except Exception:
                pass
            return None
        return restored

    def _translate(self, text: str) -> tuple[str | None, bool, bool]:
        """Cache-first translation. Returns (result, from_cache, was_unchanged).
        - from_cache=True   → ترجمة فعلية مسترجَعة من الكاش
        - was_unchanged=True → النص لا يحتاج ترجمة (أُعيد كما هو)، إمّا الآن أو معروف مسبقاً
        """
        if self._cache and self._game_name:
            cached = self._cache.get(self._game_name, text)
            if cached:
                return cached, True, False
            # نص معروف مسبقاً أنه لا يحتاج ترجمة أو فشل سابقاً → لا نستدعي الـ AI
            try:
                if self._cache.is_failed(self._game_name, text):
                    return text, False, True
            except Exception:
                pass

        result = None
        succeeded_mode = self._tag_mode  # سنُحدّثها لو bulletproof fallback نشط
        modes_attempted = ""             # للـ failed_translations لو فشل كل شيء
        if self._engine:
            if self._tag_mode == "bulletproof":
                result, info = self._translate_with_bulletproof(text)
                if result:
                    succeeded_mode = info  # bulletproof | tiered | strip
                else:
                    modes_attempted = info  # CSV من الأوضاع المُجرَّبة
            elif self._tag_mode == "tiered":
                result = self._translate_with_tiered_tags(text)
            elif self._tag_mode == "strip" or self._strip_tags:
                result = self._translate_with_tag_stripping(text)
            else:
                result = self._engine.translate(text)

        if result and self._cache and self._game_name:
            if result == text:
                # الـ AI أرجع نفس النص → نُسجّله كـ "بلا تغيير"
                try:
                    self._cache.mark_failed(self._game_name, text, "unchanged_by_ai")
                except Exception:
                    pass
                return result, False, True
            model = self._resolve_model_name()
            self._cache.put(self._game_name, text, result, model, mode_used=succeeded_mode)
            # Learning cache: سجّل نجاح هذا الـ mode
            try:
                self._cache.record_mode_success(self._game_name, succeeded_mode)
            except Exception:
                pass
        elif result is None and self._cache and self._game_name and self._engine:
            # الـ AI فشل (None) → نُسجّل سبب الفشل ونمنع إعادة المحاولة كل مرة
            # وإلا نظل نستدعي AI لنفس النص الفاشل بلا انقطاع
            try:
                reason = getattr(self._engine, "_last_error", "") or "engine_failed"
                # في وضع bulletproof نُلحق الأوضاع المُجرَّبة بالسبب
                if modes_attempted:
                    reason = f"{reason} [tried: {modes_attempted}]"
                self._cache.mark_failed(self._game_name, text, reason[:200])
                # سجّل فشل كل وضع جرَّبناه في Learning cache
                for mode in (modes_attempted.split(",") if modes_attempted else [self._tag_mode]):
                    if mode:
                        self._cache.record_mode_failure(self._game_name, mode.strip())
                if self.log_callback:
                    self.log_callback(f"⚠  فشلت ترجمة: {text[:40]}  →  {reason[:60]}")
            except Exception:
                pass

        return result, False, False
