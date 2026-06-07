"""
Embedded HTTP proxy server — bridges XUnity.AutoTranslator to the translation engine.
XUnity sends GET /?text=<english>  →  expects plain-text Arabic back.
"""
import http.server
import queue
import re as _re
import time
import urllib.parse
import threading
from collections import deque

from .tag_filter import TieredTagFilter, BulletproofTagFilter
from .tag_validator import validate_bulletproof_markers, summarize_issues
from . import skip_patterns
from . import static_translations
from . import number_template
from .models.base import enforce_trailing_punctuation


# إشارة "عطل مؤقت بالمحرّك" — تُميّز الاتصال المنقطع/المهلة عن الفشل الدائم.
# عند رؤيتها، do_GET يردّ بجسم فارغ كي يُعيد العميل (XUnity/DLL) المحاولة لاحقاً
# بدل تخزين النص الإنجليزي كـ "لا ترجمة" (تسميم الكاش).
_TRANSIENT = "\x00__TRANSIENT__\x00"

# إشارة "قيد المعالجة بالخلفية" — النص الطويل جُدوِل للترجمة async.
# do_GET يردّ بجسم فارغ (لا إنجليزي) كي لا يُخزّنه الـ DLL كـ "لا ترجمة" دائمة.
# العميل يُعيد الطلب في العرض التالي حتى تجهز الترجمة في الكاش → تُعرض عربية.
_PENDING = "\x00__PENDING__\x00"


def _needs_translation(text: str) -> bool:
    """يعيد False للأرقام والرموز والنصوص غير القابلة للترجمة."""
    t = text.strip()
    if len(t) < 3:
        return False
    # نطلب على الأقل تتابع 3 أحرف لاتينية أو عربية — يستبعد:
    #   "3x4", "+40x40"             (لا حروف)
    #   "+10%", "-20%", "1x", "2K"  (حرفان أو أقل)
    #   "OK", "No"                  (كلمة قصيرة جداً — تكلفة الترجمة > الفائدة)
    if not _re.search(r'[a-zA-Z؀-ۿ]{3,}', t):
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
            # عطل مؤقت بالمحرّك (transient) أو نص قيد المعالجة بالخلفية (pending)
            # → ردّ فارغ (لا نُسمّم عميل XUnity/DLL بنص إنجليزي يُخزَّن كـ "لا ترجمة").
            # العميل يُعيد المحاولة في العرض التالي حتى تجهز الترجمة.
            if arabic == _TRANSIENT or arabic == _PENDING:
                if srv:
                    # transient = فشل (للتنبيه)، pending = بانتظار (بلا تغيير)
                    srv._stat_request_finished(False, failed=(arabic == _TRANSIENT),
                                               unchanged=(arabic == _PENDING))
                try:
                    self._respond(200, b"", "text/plain; charset=utf-8")
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    pass
                return
            if not arabic:
                arabic = text
            arabic = _apply_rtl(arabic,
                                apply_bidi=srv._apply_bidi if srv else True,
                                char_limit=srv._char_limit if srv else 0)
            tag = "📦" if from_cache else ("⏭" if was_unchanged else "🔄")
            print(f"[Proxy] {tag} {text[:40]:40s} => {arabic[:40]}")
            # نطبع 🔄 فقط للترجمات الجديدة (AI). الـ cache hits (📦/📖) طُبعت
            # بالفعل من داخل _translate. النصوص بلا تغيير ما نلوّثها بالـ log.
            if srv and srv.log_callback and not was_unchanged and not from_cache:
                try:
                    srv.log_callback(f"🔄 {text[:45]}  ⟶  {arabic[:45]}")
                except Exception:
                    pass
            if srv:
                srv._stat_request_finished(from_cache, unchanged=was_unchanged)
            try:
                self._respond(200, arabic.encode("utf-8"), "text/plain; charset=utf-8")
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                # XUnity أنهى الاتصال قبل أن نُجيب (تأخّر AI أو إغلاق اللعبة)
                pass
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # تجاهل صامت — العميل اختفى
            if srv:
                srv._stat_request_finished(False, failed=True)
        except Exception as e:
            print(f"[Proxy] Error: {e}")
            if srv:
                srv._stat_request_finished(False, failed=True)
            try:
                self._respond(200, text.encode("utf-8"), "text/plain; charset=utf-8")
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass

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
        # فلتر مصدر الكاش — يحدّد أي ترجمات سابقة تُسترجَع:
        #   ""       → كل النماذج (افتراضي)
        #   "none"   → تجاهل الكاش (ترجمة من الصفر)
        #   "اسم"   → فقط ترجمات هذا النموذج
        self._cache_model_filter = ""
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None       = None
        self._engine_lock  = threading.Lock()   # يسلسل استدعاءات المحرّك (Ollama single-instance)
        self.log_callback  = None   # callable(str) | None — thread-safe via Qt Signal
        # إحصاءات الترجمة (Thread-safe عبر Lock)
        self._stats_lock     = threading.Lock()
        self._pending_count  = 0          # عدد الطلبات قيد المعالجة الآن
        self._translated_engine_count = 0 # ترجمات فعلية (نتيجة ≠ الأصل)
        self._translated_cache_count  = 0 # ضربات الكاش
        self._unchanged_count         = 0 # نصوص أرجعها الـ AI بدون تغيير (أسماء، أرقام)
        self._failed_count            = 0 # فشل المحرّك بشكل نهائي
        self._recent_translations: deque = deque(maxlen=120)  # طوابع زمنية للترجمات الأخيرة (لحساب المعدل)
        # تتبّع آخر 20 فشل مع تفاصيل (للتشخيص)
        self._recent_failures: deque = deque(maxlen=20)
        # متتالية الإخفاقات الحالية (لاكتشاف انهيار المحرّك)
        self._consecutive_failures = 0
        self.stats_callback  = None   # callable(dict) | None — تُستدعى بعد كل تحديث إحصاءات

        # ── Async background translation infrastructure ───────────────────────
        # النصوص الطويلة تُجدوَل للخلفية بدل ما تجمّد البروكسي.
        # الطلب الأولي يستلم النص الإنجليزي فوراً (لا timeout عند العميل)،
        # ثم AI يكمل في الخلفية ويحفظ في cache. الطلب التالي لنفس النص → cache hit.
        self._bg_queue: queue.Queue[str] = queue.Queue()
        self._bg_in_progress: set[str] = set()
        self._bg_lock = threading.Lock()
        self._bg_worker: threading.Thread | None = None
        self._bg_stop_event = threading.Event()
        # الحد الأقصى لطول النص الذي يُعالَج متزامناً (sync). فوق هذا → async.
        # 200 حرف = ~30 ث AI كحد أعلى = أقل من XUnity timeout الافتراضي (5 ث... للاتصال).
        # يمكن تعديله من config.json["proxy"]["async_threshold_chars"]
        self._async_threshold_chars = 200
        # الحد الأقصى لحجم الـ queue — يمنع تراكم لانهائي عند الحاجة
        self._bg_max_queue_size = 500

        # تقويلب الأرقام: استبدال الأرقام بـ {0}{1}.. لتقليل تكرار الكاش
        # ("Current Tier: 2/3/5" → قالب واحد). يُقرأ من config، افتراضي مُفعَّل.
        self._number_templating = True

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

    def set_cache_model_filter(self, model: str):
        """يحدّد مصدر الكاش:
          ""     → كل النماذج
          "none" → تجاهل الكاش
          غيره   → ترجمات هذا النموذج فقط"""
        self._cache_model_filter = model or ""

    def get_cache_model_filter(self) -> str:
        return self._cache_model_filter

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
        game_path = (_cfg.get("game_path") or "").strip()

        # ملاحظة: لا تصدير تلقائي للكاش → translations.txt هنا.
        # المستخدم يفضّل التحكّم اليدوي عبر زر "تحديث الترجمات" في صفحة اللعبة.

        # حمّل translations.txt اليدوي إن وُجد — مصدر الأولوية على الكاش
        try:
            data, path = static_translations.load(game_path)
            if data:
                msg = f"📖  حُمّل translations.txt: {len(data):,} ترجمة"
                if self.log_callback:
                    self.log_callback(msg)
                print(f"[Proxy] {msg}")
            else:
                # لا تحذير — الملف اختياري
                static_translations.clear()
        except Exception as e:
            print(f"[Proxy] static_translations load error: {e}")
            static_translations.clear()
        # tag_mode: المفضّل. strip_tags_before_translate: قديم — للتوافق
        tag_mode_cfg = _cfg.get("tag_mode")
        if tag_mode_cfg in ("inline", "strip", "tiered", "bulletproof"):
            self.set_tag_mode(tag_mode_cfg)
        else:
            self.set_strip_tags(bool(_cfg.get("strip_tags_before_translate", False)))
        # فلتر مصدر الكاش — للتجربة بمودل واحد أو ترجمة من الصفر
        self.set_cache_model_filter(str(_cfg.get("cache_model_filter", "")))
        # تقويلب الأرقام (افتراضي مُفعَّل) — يمكن تعطيله من config.json["number_templating"]
        self._number_templating = bool(_cfg.get("number_templating", True))
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

        # تجديد engine_lock — طلبات الـ AI القديمة (إن وُجدت من تشغيل سابق) لا تزال
        # محاصرة على القفل القديم لكن لن يحاصرها أحد. الـ threads الجديدة تستخدم القفل الجديد.
        # هذا حاسم لإعادة التشغيل بعد timeout طويل: لا ننتظر threads قديمة لتُحرّر القفل.
        self._engine_lock = threading.Lock()

        # أعد تعيين أعلام فشل تحميل المترجمات — قد تكون مُفعَّلة من جلسة سابقة
        # (مثلاً Ollama انقطع → _is_loaded=False → _load_failed_session=True بعد محاولة فاشلة).
        # هذا الإصلاح يضمن أن restart يعمل بعد ConnectionError دون الحاجة لإعادة تشغيل التطبيق.
        try:
            if self._engine is not None and hasattr(self._engine, "_translators"):
                for tr in self._engine._translators.values():
                    if hasattr(tr, "_load_failed_session"):
                        tr._load_failed_session = False
                    # أغلق الـ HTTP session القديم (إن وُجد) — يُجبر OllamaTranslator
                    # على فتح session جديد عند الطلب التالي، فيتجنّب pipe broken
                    if hasattr(tr, "_session") and tr._session is not None:
                        try:
                            tr._session.close()
                        except Exception:
                            pass
                        tr._session = None
                        # نُعلِم translator أنه يحتاج إعادة تحميل
                        if hasattr(tr, "_is_loaded"):
                            tr._is_loaded = False
        except Exception:
            pass

        # تنظيف أي بقايا من تشغيل سابق — حماية من إعادة التشغيل بعد crash
        # حيث قد يكون _server موجوداً مع socket مرتبط لكن _thread ميت
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
            try:
                self._server.server_close()
            except Exception:
                pass
            self._server = None
        self._thread = None

        try:
            # ThreadingHTTPServer: كل طلب في خيط مستقل
            # → cache hits سريعة، لا تنتظر AI calls الطويلة في خيوط أخرى
            # allow_reuse_address: يسمح بإعادة استخدام المنفذ فوراً بعد توقف
            # (يحلّ مشكلة "Address already in use" على Windows في TIME_WAIT)
            class _ReusableServer(http.server.ThreadingHTTPServer):
                allow_reuse_address = True
                daemon_threads = True

            self._server = _ReusableServer(("127.0.0.1", self.PORT), _Handler)
        except OSError as e:
            self._server = None
            return False, f"تعذّر فتح المنفذ {self.PORT}: {e}"

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="TranslationProxy",
        )
        self._thread.start()
        return True, f"✅  خادم الترجمة يعمل على http://127.0.0.1:{self.PORT}/"

    def stop(self) -> str:
        """Stop the server. Safe to call even when already stopped or crashed.

        ⚠ shutdown() البلوكنغ قد يجمّد إذا كان فيه طلب AI طويل جارٍ (90-240 ث).
        لذا نُطلق shutdown() في thread منفصل وندعه يكمل بالخلفية،
        ونُغلق socket فوراً ليفرّر المنفذ لإعادة الاستخدام.
        """
        was_running = self.is_running
        old_server = self._server
        old_thread = self._thread

        # نصفّر المراجع فوراً — لا ننتظر shutdown البطيء
        self._server    = None
        self._thread    = None
        self._game_name = ""

        # أوقِف bg worker وامسح الـ queue — الـ thread daemon سيموت من تلقاء نفسه
        # بعد idle_timeout أو عند رؤية stop_event.
        self._bg_stop_event.set()
        try:
            while not self._bg_queue.empty():
                self._bg_queue.get_nowait()
                self._bg_queue.task_done()
        except (queue.Empty, ValueError):
            pass
        with self._bg_lock:
            self._bg_in_progress.clear()

        # امسح translations.txt المُحمّل (في حال اللعبة التالية مختلفة)
        try:
            static_translations.clear()
        except Exception:
            pass

        if old_server is not None:
            # shutdown + close معاً في thread خلفي — لا نُجمّد الواجهة.
            # نضمن الترتيب الصحيح (shutdown أولاً → serve_forever loop يستيقظ وينهي
            # ثم close يحرّر الـ socket) لتجنّب OSError في selector.select().
            # الـ threads الجارية daemon — ستُنهى تلقائياً مع إغلاق التطبيق.
            def _bg_shutdown(srv=old_server):
                try:
                    srv.shutdown()
                except Exception:
                    pass
                try:
                    srv.server_close()
                except Exception:
                    pass
            t = threading.Thread(target=_bg_shutdown, daemon=True, name="ProxyShutdown")
            t.start()

            # تحرير المنفذ فوراً لإعادة الاستخدام — _ReusableServer.allow_reuse_address=True
            # يسمح لـ start جديد بربط نفس المنفذ حتى مع socket قديم مفتوح.
            # هذا أكثر أماناً من server_close فوراً (الذي يسبب OSError مع selector).
        return "⛔  توقّف خادم الترجمة الفورية" if was_running else "الخادم لم يكن يعمل"

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
            recent = [t for t in self._recent_translations if now - t <= 1.0]
            rate_per_sec = len(recent)
            return {
                "pending": self._pending_count,
                "engine_count": self._translated_engine_count,
                "cache_count": self._translated_cache_count,
                "unchanged_count": self._unchanged_count,
                "failed_count": self._failed_count,
                "consecutive_failures": self._consecutive_failures,
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
            self._failed_count = 0
            self._recent_translations.clear()
            self._recent_failures.clear()
            self._consecutive_failures = 0
        self._emit_stats()

    def record_failure(self, text: str, reason: str, modes_tried: str = ""):
        """يُسجّل فشل ترجمة مع التفاصيل لاحقاً تشخيصها."""
        now = time.monotonic()
        with self._stats_lock:
            self._failed_count += 1
            self._consecutive_failures += 1
            self._recent_failures.append({
                "ts": now,
                "text": text[:200],
                "reason": reason[:200],
                "modes_tried": modes_tried,
            })
        # تحذير إن تتابع الفشل (انهيار محتمل للمحرّك)
        if self._consecutive_failures == 5:
            if self.log_callback:
                try:
                    self.log_callback(
                        f"⚠⚠  5 فشل متتالية — المحرّك قد يكون عالقاً أو المودل مُحمَّل بشكل غير سليم"
                    )
                except Exception:
                    pass
        elif self._consecutive_failures == 15:
            if self.log_callback:
                try:
                    self.log_callback(
                        f"🚨  15 فشل متتالية — يُنصح بإيقاف الخادم وفحص Ollama"
                    )
                except Exception:
                    pass

    def record_success(self):
        """يُصفّر متتالية الفشل عند أي نجاح."""
        with self._stats_lock:
            self._consecutive_failures = 0

    def get_recent_failures(self) -> list[dict]:
        with self._stats_lock:
            return list(self._recent_failures)

    # ── Internal ──────────────────────────────────────────────────────────────

    _HTML_TAG_RE_PROXY = _re.compile(r"</?[a-zA-Z][^<>]{0,120}>")

    def _get_cached_by_model(self, text: str, model: str):
        """يجلب من الكاش فقط إذا كان النموذج المحدد له ترجمة لهذا النص."""
        try:
            if hasattr(self._cache, "get_if_model_matches"):
                return self._cache.get_if_model_matches(self._game_name, text, model)
        except Exception:
            pass
        # fallback: get_by_model يُرجع dict، نفحص العنصر
        try:
            rows = self._cache.get_by_model(self._game_name, model)
            return rows.get(text)
        except Exception:
            return None

    def _get_engine_last_error(self) -> str:
        """يجلب آخر سبب فشل من المترجم النشط (لا من الـ wrapper).
        Wrapper TranslationEngine لا يحفظ _last_error — يُحفظ في الـ translator فقط."""
        if not self._engine:
            return ""
        try:
            key = self._engine.get_active_model() or ""
            tr = self._engine.get_translator(key) if key else None
            return getattr(tr, "_last_error", "") if tr else ""
        except Exception:
            return ""

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

    def _effective_timeout_for(self, text: str) -> float:
        """يحسب timeout مناسب بناءً على طول النص.
        نصوص طويلة (شاشات مساعدة، dialog كاملة) تحتاج وقت أطول للترجمة
        — Ollama يولّد العربية ببطء وقد تتجاوز 60 ثانية على النصوص الكبيرة.

        السلّم:
          ≤ 500   حرف → الـ base (افتراضي 60ث)
          ≤ 1500       → base × 1.5
          ≤ 3000       → base × 2.5
          > 3000       → base × 4
        """
        base = self._timeout if self._timeout > 0 else 60.0
        length = len(text or "")
        if length <= 500:
            return base
        if length <= 1500:
            return base * 1.5
        if length <= 3000:
            return base * 2.5
        return base * 4.0

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
        # في cascade نُقسّم الوقت على 3 محاولات حتى لا يتجاوز مهلة XUnity.
        # للنصوص الطويلة نسمح لكل محاولة بوقت أطول (Ollama يحتاج وقتاً أكثر للنصوص الكبيرة).
        original_timeout = getattr(self._engine, "_timeout", 60.0)
        text_len = len(text) if text else 0
        if text_len <= 500:
            min_per_attempt = 25.0   # نصوص UI قصيرة
        elif text_len <= 1500:
            min_per_attempt = 45.0   # جمل متوسطة
        elif text_len <= 3000:
            min_per_attempt = 75.0   # فقرات
        else:
            min_per_attempt = 120.0  # شاشات مساعدة كاملة
        cascade_per_attempt = max(min_per_attempt, original_timeout / 3)
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

    # ── Async background translation ──────────────────────────────────────────

    def _schedule_background_translation(self, text: str) -> bool:
        """يُجدوِل نصاً للترجمة في الخلفية.
        يُرجع True لو جُدوِل (أو موجود مسبقاً)، False لو الـ queue مليان.
        """
        if not text or not self._engine or not self._game_name:
            return False
        with self._bg_lock:
            if text in self._bg_in_progress:
                return True   # موجود سلفاً (لا تكرار)
            if self._bg_queue.qsize() >= self._bg_max_queue_size:
                return False   # backpressure — رفض
            self._bg_in_progress.add(text)
        try:
            self._bg_queue.put_nowait(text)
        except queue.Full:
            with self._bg_lock:
                self._bg_in_progress.discard(text)
            return False
        self._ensure_bg_worker_running()
        return True

    def _ensure_bg_worker_running(self):
        """ينشئ thread الـ worker لو لم يكن يعمل."""
        with self._bg_lock:
            if self._bg_worker is not None and self._bg_worker.is_alive():
                return
            self._bg_stop_event.clear()
            self._bg_worker = threading.Thread(
                target=self._bg_worker_loop,
                daemon=True,
                name="ProxyBgTranslator",
            )
            self._bg_worker.start()

    def _bg_worker_loop(self):
        """الحلقة الخلفية: تأخذ نصاً، تترجم متزامناً، تحفظ في cache."""
        idle_timeout = 30.0   # ينام Worker لو مافي عمل لـ 30 ث ثم يخرج (يُحيا عند الطلب)
        while not self._bg_stop_event.is_set():
            try:
                text = self._bg_queue.get(timeout=idle_timeout)
            except queue.Empty:
                # خامل لفترة → اخرج، سيُحيا عند طلب جديد
                return
            if self._bg_stop_event.is_set():
                return
            try:
                # نستدعي _translate بـ force_sync=True ليتجاوز إعادة الجدولة
                # الـ AI سيُستدعى مع الـ timeout الديناميكي + cascade fallback،
                # ويُحفَظ النتيجة تلقائياً في cache أو failed_translations.
                if self._engine and self._game_name:
                    self._translate(text, force_sync=True)
                if self.log_callback:
                    try:
                        self.log_callback(
                            f"✅  ترجم خلفية ({len(text)} حرف): {text[:50]}"
                        )
                    except Exception:
                        pass
            except Exception as e:
                print(f"[BgWorker] error: {e}")
            finally:
                with self._bg_lock:
                    self._bg_in_progress.discard(text)
                try:
                    self._bg_queue.task_done()
                except ValueError:
                    pass

    def _should_translate_async(self, text: str) -> bool:
        """يقرّر هل النص يُترجَم متزامناً أم في الخلفية.
        النصوص الطويلة → async (لا تجميد للعميل).
        النصوص القصيرة → sync (تجربة فورية).
        وضع "بدون كاش" → دائماً sync (المستخدم يجرب يدوياً).
        """
        if self._cache_model_filter == "none":
            return False   # المستخدم يجرب — لا async
        if not text:
            return False
        return len(text) >= self._async_threshold_chars

    def _is_transient_failure(self) -> bool:
        """هل آخر فشل في المحرّك مؤقت (اتصال منقطع/مهلة) لا دائم؟
        نُميّز كي لا نُسجّل الفشل في DB ولا نُسمّم عميل الـ DLL."""
        if not self._engine:
            return False
        try:
            key = self._engine.get_active_model() or ""
            tr = self._engine.get_translator(key) if key else None
            if tr is None:
                return False
            # اتصال سقط → _is_loaded=False
            if getattr(tr, "_is_loaded", True) is False:
                return True
            err = getattr(tr, "_last_error", "") or ""
            keywords = ("اتصال", "مهلة", "connection", "Connection", "timeout", "Timeout")
            return any(k in err for k in keywords)
        except Exception:
            return False

    def _translate(self, text: str, force_sync: bool = False) -> tuple[str | None, bool, bool]:
        """غلاف تقويلب الأرقام حول _translate_impl.
        يستبدل الأرقام بـ {0}{1}.. فيصبح المفتاح قالباً واحداً (يقلّل تكرار الكاش)،
        ثم يُعيد الأرقام الأصلية في النتيجة. لو لا أرقام (أو الميزة معطّلة) → تمرير مباشر.
        """
        if self._number_templating and number_template.should_templatize(text):
            tmpl, nums = number_template.extract(text)
            if nums:
                result, from_cache, was_unchanged = self._translate_impl(tmpl, force_sync)
                if result and result not in (_TRANSIENT, _PENDING):
                    result = number_template.restore(result, nums)
                return result, from_cache, was_unchanged
        return self._translate_impl(text, force_sync)

    def _translate_impl(self, text: str, force_sync: bool = False) -> tuple[str | None, bool, bool]:
        """Translation lookup order:
          1) translations.txt (المرجع اليدوي عالي الجودة — أولوية مطلقة)
          2) قائمة المنع (skip_patterns)
          3) جدول الفشل (is_failed)
          4) الكاش (SQLite)
          5) الـ AI (Ollama)

        ملاحظة: عند "بدون كاش" (cache_model_filter == "none") يُتجاوز كل من
        translations.txt و SQLite cache — كل النصوص تذهب مباشرة لـ AI.

        Returns (result, from_cache, was_unchanged).
        - from_cache=True   → ترجمة فعلية مسترجَعة (translations.txt أو SQLite)
        - was_unchanged=True → النص لا يحتاج ترجمة (أُعيد كما هو)
        """
        no_cache_mode = (self._cache_model_filter == "none")

        # 1) translations.txt — المصدر اليدوي اليدوي. لو وُجد، يُعتمد فوراً بلا
        #    استدعاء AI ولا فحص كاش. يُعدّ "from_cache=True" لأن الترجمة جاهزة.
        #    لكن في وضع "بدون كاش" نتخطّاه أيضاً (ترجمة من الصفر بالكامل).
        if not no_cache_mode:
            try:
                static_ar = static_translations.lookup(text)
            except Exception:
                static_ar = None
            if static_ar:
                if self.log_callback:
                    self.log_callback(f"📖  يدوي: {text[:40]}  ⟶  {static_ar[:40]}")
                return static_ar, True, False

        # 2) قائمة المنع (skip_patterns): نصوص مطابقة لا تُرسل للمحرّك أصلاً
        # — توفير موارد + تصنيف "بدون تغيير" بدل فشل (مثل أسماء الخطوط Nexa, *SDF)
        try:
            matched_pat = skip_patterns.matches(text)
        except Exception:
            matched_pat = None
        if matched_pat:
            if self.log_callback:
                self.log_callback(f"🚫  مُمنَع [{matched_pat}]: {text[:50]}")
            return text, False, True

        # فحص جدول الفشل — يُتخطّى في وضع "بدون كاش" لإعادة محاولة كل شيء
        if self._cache and self._game_name and not no_cache_mode:
            try:
                if self._cache.is_failed(self._game_name, text):
                    if self.log_callback:
                        self.log_callback(f"⏭  معروف فاشل، تخطّي: {text[:50]}")
                    return text, False, True
            except Exception:
                pass

        # تطبيق فلتر مصدر الكاش (للترجمات الناجحة فقط):
        #   "none" → لا تستخدم الكاش، اذهب مباشرة للـ AI
        #   "اسم"  → فقط ترجمات هذا النموذج تُسترجَع
        #   ""    → كل النماذج (افتراضي)
        if self._cache and self._game_name and self._cache_model_filter != "none":
            if self._cache_model_filter:
                # فلتر بمودل واحد
                cached = self._get_cached_by_model(text, self._cache_model_filter)
            else:
                cached = self._cache.get(self._game_name, text)
            if cached:
                # طبع 📦 من هنا حتى الفلتر يصنّف الـ SQLite cache hits ك "كاش"
                # (الـ HTTP handler يتخطّى السطر لـ from_cache=True)
                if self.log_callback:
                    try:
                        self.log_callback(f"📦 {text[:45]}  ⟶  {cached[:45]}")
                    except Exception:
                        pass
                return cached, True, False

        # ── Async dispatch للنصوص الطويلة ──────────────────────────────
        # النصوص الطويلة (>= 200 حرف عادة) تذهب لـ background queue بدل ما
        # تحاصر العميل في انتظار AI لـ 90-240 ثانية. نُعيد النص الإنجليزي فوراً،
        # AI يكمل في الخلفية ويحفظ في cache، الطلب التالي لنفس النص → cache hit.
        # force_sync=True عند استدعاء من bg worker لتجنب re-scheduling.
        if not force_sync and self._should_translate_async(text):
            scheduled = self._schedule_background_translation(text)
            if self.log_callback:
                try:
                    if scheduled:
                        self.log_callback(
                            f"⏳  جدولة خلفية ({len(text)} حرف): {text[:50]}"
                        )
                    else:
                        self.log_callback(
                            f"⚠  queue مليان — تخطّي ({len(text)} حرف)"
                        )
                except Exception:
                    pass
            # ردّ فارغ (إشارة "قيد المعالجة") بدل الإنجليزي — العميل لا ينتظر AI،
            # ولا يُخزّن الإنجليزي كـ "لا ترجمة" دائمة. يُعيد الطلب حتى تجهز الترجمة.
            return _PENDING, False, True

        result = None
        succeeded_mode = self._tag_mode  # سنُحدّثها لو bulletproof fallback نشط
        modes_attempted = ""             # للـ failed_translations لو فشل كل شيء
        if self._engine:
            # Lock يمنع استدعاءين متوازيين للمحرّك (Ollama instance واحد)
            # cache lookup فوقه تَمَّ بدون lock → cache hits تظل سريعة
            with self._engine_lock:
                # تحقق من الفشل مرة أخرى داخل الـ lock — قد يكون thread آخر
                # سجّل النص نفسه كفاشل بينما كنا ننتظر (يُتخطّى في وضع بدون كاش)
                if self._cache and self._game_name and not no_cache_mode:
                    try:
                        if self._cache.is_failed(self._game_name, text):
                            return text, False, True
                    except Exception:
                        pass
                # تحقق من الكاش مرة أخرى داخل الـ lock — قد يكون thread آخر
                # ترجم نفس النص بينما كنا ننتظر (يحترم cache_model_filter)
                if self._cache and self._game_name and self._cache_model_filter != "none":
                    if self._cache_model_filter:
                        cached2 = self._get_cached_by_model(text, self._cache_model_filter)
                    else:
                        cached2 = self._cache.get(self._game_name, text)
                    if cached2:
                        return cached2, True, False
                # طبّق timeout ديناميكي بناءً على طول النص — يحفظه ويستعيده
                _saved_timeout = getattr(self._engine, "_timeout", 60.0)
                _eff = self._effective_timeout_for(text)
                if _eff != _saved_timeout:
                    try:
                        self._engine._timeout = _eff
                        if self.log_callback and len(text) > 500:
                            self.log_callback(
                                f"⏱  نص طويل ({len(text)} حرف) — timeout = {int(_eff)}ث"
                            )
                    except Exception:
                        pass
                try:
                    if self._tag_mode == "bulletproof":
                        result, info = self._translate_with_bulletproof(text)
                        if result:
                            succeeded_mode = info  # bulletproof | tiered | strip
                        else:
                            modes_attempted = info
                    elif self._tag_mode == "tiered":
                        result = self._translate_with_tiered_tags(text)
                    elif self._tag_mode == "strip" or self._strip_tags:
                        result = self._translate_with_tag_stripping(text)
                    else:
                        result = self._engine.translate(text)
                finally:
                    # استعد timeout الأصلي حتى لا يؤثّر على النص التالي
                    try:
                        self._engine._timeout = _saved_timeout
                    except Exception:
                        pass

        # فرض تماثل علامة النهاية: أزل نقطة أضافها المودل لو الأصل بلا نقطة.
        # (حتمي — يُصلح أيضاً تداخل النقطة مع تاقات اللون في عرض RTL.)
        if result and result != text:
            result = enforce_trailing_punctuation(text, result)

        if result and self._cache and self._game_name:
            if result == text:
                # الـ AI أرجع نفس النص → نُسجّله كـ "بلا تغيير"
                try:
                    self._cache.mark_failed(
                        self._game_name, text, "unchanged_by_ai",
                        model_used=self._resolve_model_name(),
                    )
                except Exception:
                    pass
                self.record_success()  # نُصفّر متتالية الفشل
                return result, False, True
            model = self._resolve_model_name()
            self._cache.put(self._game_name, text, result, model, mode_used=succeeded_mode)
            # Learning cache: سجّل نجاح هذا الـ mode
            try:
                self._cache.record_mode_success(self._game_name, succeeded_mode)
            except Exception:
                pass
            self.record_success()
        elif result is None and self._cache and self._game_name and self._engine:
            # عطل مؤقت (اتصال منقطع/مهلة) ≠ فشل دائم. لا نُسجّله في DB ولا نُرجع
            # النص الإنجليزي (الذي يُسمّم الـ DLL كـ "لا ترجمة"). نُرجع إشارة مؤقتة
            # → do_GET يردّ فارغاً → العميل يُعيد المحاولة عند تعافي المحرّك.
            if self._is_transient_failure():
                try:
                    self.record_failure(
                        text, self._get_engine_last_error() or "transient_engine_error", ""
                    )
                    if self.log_callback:
                        self.log_callback(f"⏳  عطل مؤقت بالمحرّك — سيُعاد لاحقاً: {text[:40]}")
                except Exception:
                    pass
                return _TRANSIENT, False, False
            # الـ AI فشل دائماً (None) → نُسجّل سبب الفشل ونمنع إعادة المحاولة كل مرة
            # وإلا نظل نستدعي AI لنفس النص الفاشل بلا انقطاع
            try:
                # نفصل السبب الأساسي عن قائمة الأوضاع المُجرَّبة لتجنّب التكرار في العرض
                # _last_error يوجد على المترجم النشط (OllamaTranslator)، ليس على الـ wrapper
                reason_base = self._get_engine_last_error() or "engine_failed"
                reason_full = reason_base
                if modes_attempted:
                    reason_full = f"{reason_base} [tried: {modes_attempted}]"
                self._cache.mark_failed(
                    self._game_name, text, reason_full[:200],
                    model_used=self._resolve_model_name(),
                )
                # سجّل فشل كل وضع جرَّبناه في Learning cache
                for mode in (modes_attempted.split(",") if modes_attempted else [self._tag_mode]):
                    if mode:
                        self._cache.record_mode_failure(self._game_name, mode.strip())
                if self.log_callback:
                    self.log_callback(f"⚠  فشل: {text[:40]}  →  {reason_full[:80]}")
                # سجّل في تتبّع الفشل (السبب الأساسي بدون [tried:]) لأن العرض يضيفها
                self.record_failure(text, reason_base, modes_attempted)
            except Exception:
                pass
            # نُرجع unchanged=True كي do_GET يُسجّل ⏭ بدل 🔄
            # ويُحدّث counter كـ unchanged بدل translated. هذا يمنع تضخّم عداد
            # الترجمات الجديدة بنصوص لم تُترجَم فعلاً.
            return text, False, True

        return result, False, False
