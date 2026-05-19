import requests
import json
import re
import time
from typing import Optional
from engine.models.base import BaseTranslator, translate_preserving_tokens


def _default_ollama_system_prompt() -> str:
    return (
        "You are an expert Arabic game localization specialist with 15+ years of experience "
        "localizing AAA games into Arabic for the MENA market.\n\n"
        "Your ONLY task: translate the given English game text into natural, high-quality "
        "Modern Standard Arabic (فصحى خفيفة) suitable for games.\n\n"
        "CORE RULES — never break these:\n"
        "1. Output ONLY the Arabic translation. No explanations. No alternatives. No comments. No transliteration.\n"
        "2. Preserve ALL formatting tokens and special characters exactly as-is: {0} {1} {playerName} \\n <color=#ff0000> </color> [b] [/b] %s %d — never translate, remove, or modify them. The bracket markers [t0] [/t0] [t1] [/t1] [s0] [s1] AND the mathematical brackets ⟦0⟧ ⟦/0⟧ ⟦1⟧ ⟦/1⟧ ⟦s0⟧ ⟦s1⟧ (any numbered [tN]/[/tN]/[sN]/⟦N⟧/⟦/N⟧/⟦sN⟧) are PROTECTED STRUCTURAL MARKERS. They wrap content you SHOULD translate, but the markers themselves must appear UNCHANGED in your output — same characters, same digits, same count. If you cannot guarantee preservation, output the markers as-is rather than guessing. This includes any unusual Unicode characters or symbols in the input.\n"
        "3. Preserve punctuation EXACTLY as in the original. Do NOT add a period (.) at the end unless the original text itself ends with a period. Do NOT add or remove any punctuation mark.\n"
        "4. Never add content that is not in the original text.\n"
        "5. If the input is already Arabic, is a non-English language name (日本語, Русский, Türkçe …), or contains non-Latin script: return it UNCHANGED — no comment, no explanation.\n"
        "6. NEVER refuse. NEVER apologize. NEVER ask for more input. NEVER explain what you're doing. Output ONLY the translation.\n\n"
        "TRANSLATION QUALITY STANDARDS:\n"
        "- Use terminology consistent with major Arabic game localizations: المهمة، المخزون، المهارة، الصحة، الدرع، الخصم، الحليف، المكافأة، الخريطة، المستوى، النقاط، الذخيرة، التعديلات.\n"
        "- Match tone: dramatic for story/combat, clear for UI/menus, imperative for tutorials (اضغط، حرك، اختر).\n"
        "- Character names, brand names, unique item names: keep in English unless a well-known Arabic equivalent exists.\n"
        "- Short UI labels (buttons, menus): be concise — 1 to 3 words maximum when possible.\n"
        "- Descriptions and lore: use flowing, engaging Arabic that reads naturally, not literally.\n"
        "- Every word must carry meaning — no hollow filler.\n\n"
        "ARABIC LANGUAGE RULES:\n"
        "- Use correct pronoun attachment (كتابته، لاعبها، قدراتك).\n"
        "- Maintain grammatical gender agreement; masculine by default for generic references.\n"
        "- Prefer active voice when the original uses active voice.\n"
        "- Do not add diacritics (تشكيل) unless emphasis is critical."
    )


class GoogleFreeTranslator(BaseTranslator):
    
    BASE_URL = "https://translate.googleapis.com/translate_a/single"
    
    def __init__(self, name: str, description: str):
        super().__init__(name, description)
        self._session = None
    
    def load(self) -> bool:
        try:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            self._is_loaded = True
            print("[Google] Free translator ready")
            return True
        except Exception as e:
            print(f"[Google] Failed to initialize: {e}")
            return False
    
    def _raw_translate(self, text: str, source_lang: str = "en", target_lang: str = "ar") -> Optional[str]:
        params = {
            "client": "gtx",
            "sl": source_lang,
            "tl": target_lang,
            "dt": "t",
            "q": text
        }
        response = self._session.get(self.BASE_URL, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0 and data[0]:
                raw = "".join(p[0] for p in data[0] if p and p[0])
                if raw and raw != text:
                    # Google sometimes injects extra paragraphs when original has none.
                    # If original had no newlines but result does, strip extra paragraphs.
                    if '\n' not in text and '\n' in raw:
                        raw = raw.replace('\n', ' ').strip()
                    # Reject if translation is suspiciously long (Google added context).
                    # Arabic is naturally ~1.5x English, so 6x means Google hallucinated.
                    if len(raw) > max(len(text) * 6, 600):
                        print(f"[Google] Rejected overlong translation ({len(raw)} chars for {len(text)} char input)")
                        return None
                    return raw
        return None

    def translate(self, text: str, source_lang: str = "en", target_lang: str = "ar") -> Optional[str]:
        if not self._is_loaded or not self._session:
            return None
        try:
            text = self._preprocess(text)
            if not text or len(text) < 2:
                return None

            def _raw(segment: str) -> Optional[str]:
                return self._raw_translate(segment, source_lang, target_lang)

            result = translate_preserving_tokens(text, _raw)
            return self._postprocess(result) if result else None
        except Exception as e:
            print(f"[Google] Translation error: {e}")
            return None
    
    def unload(self):
        if self._session:
            self._session.close()
        self._session = None
        self._is_loaded = False


_DEFAULT_OLLAMA_OPTIONS = {
    "num_gpu":        999,
    "num_thread":     8,
    "num_ctx":        512,
    "num_batch":      512,
    "num_predict":    80,
    "temperature":    0.1,
    "top_k":          20,
    "top_p":          0.9,
    "repeat_penalty": 1.1,
    "seed":           -1,
}


def _load_ollama_options(config_path: str = "config.json") -> dict:
    """Read ollama_options from config.json, skip keys starting with '_'."""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        raw = cfg.get("ollama_options", {})
        opts = {k: v for k, v in raw.items() if not k.startswith("_")}
        merged = dict(_DEFAULT_OLLAMA_OPTIONS)
        merged.update(opts)
        return merged
    except Exception:
        return dict(_DEFAULT_OLLAMA_OPTIONS)


class OllamaTranslator(BaseTranslator):

    def __init__(self, name: str, description: str, model: str = "llama3",
                 url: str = "http://localhost:11434", config_path: str = "config.json"):
        super().__init__(name, description)
        self.model       = model
        self.url         = url.rstrip("/")
        self.config_path = config_path
        self._session: requests.Session | None = None
        self._available_models: list = []
        self._opts:    dict  = {}
        self._timeout: float = 60.0
        self._last_error: str = ""
        self.system_prompt = _default_ollama_system_prompt()

    # ── Model discovery ───────────────────────────────────────────────────────

    def list_models(self) -> list:
        """جلب النماذج المثبتة من الخادم — لا يحتاج load()."""
        try:
            sess = self._session or requests.Session()
            resp = sess.get(f"{self.url}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                self._available_models = [
                    {
                        "name":           m.get("name", ""),
                        "size_gb":        round(m.get("size", 0) / (1024 ** 3), 1),
                        "parameter_size": m.get("details", {}).get("parameter_size", ""),
                        "quantization":   m.get("details", {}).get("quantization_level", ""),
                        "family":         m.get("details", {}).get("family", ""),
                    }
                    for m in models
                ]
                return self._available_models
        except Exception as e:
            print(f"[Ollama] list_models: {e}")
        return []

    def set_model(self, model_name: str):
        self.model = model_name
        print(f"[Ollama] model → {model_name}")

    # ── Load / connect ────────────────────────────────────────────────────────

    def load(self) -> bool:
        self._last_error = ""
        try:
            self._session = requests.Session()

            # Check server is reachable
            resp = self._session.get(f"{self.url}/api/tags", timeout=5)
            if resp.status_code != 200:
                self._last_error = f"الخادم أعاد {resp.status_code}"
                print(f"[Ollama] server status {resp.status_code}")
                return False

            raw_models = resp.json().get("models", [])
            available  = [m.get("name", "") for m in raw_models]

            # Verify the selected model is installed
            if self.model and self.model not in available:
                self._last_error = (
                    f"النموذج '{self.model}' غير مثبت.\n"
                    f"المتاح: {', '.join(available) or 'لا يوجد'}"
                )
                print(f"[Ollama] model '{self.model}' not found. available: {available}")
                return False

            # Cache options (done once, not per-translation)
            opts = _load_ollama_options(self.config_path)
            self._timeout = float(opts.pop("timeout", 120))
            self._opts    = opts
            self._available_models = [
                {"name": m.get("name", ""), "size_gb": round(m.get("size", 0) / (1024 ** 3), 1)}
                for m in raw_models
            ]

            self._is_loaded = True
            print(f"[Ollama] connected → {self.url}  model: {self.model}  "
                  f"ctx={self._opts.get('num_ctx')}  predict={self._opts.get('num_predict')}  "
                  f"temp={self._opts.get('temperature')}  timeout={self._timeout}s")
            return True

        except requests.exceptions.ConnectionError:
            self._last_error = "تعذّر الاتصال بـ Ollama — تأكد أن الخادم يعمل"
            print(f"[Ollama] connection refused: {self.url}")
            return False
        except requests.exceptions.Timeout:
            self._last_error = "انتهت مهلة الاتصال — الخادم بطيء أو غير موجود"
            print(f"[Ollama] tags request timed out: {self.url}")
            return False
        except Exception as e:
            self._last_error = str(e)
            print(f"[Ollama] load failed: {e}")
            return False

    # ── Translation ───────────────────────────────────────────────────────────

    def _raw_translate(self, text: str) -> Optional[str]:
        """Translate via /api/chat."""
        self._last_error = ""
        try:
            payload = {
                "model":   self.model,
                "stream":  False,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user",   "content": text},
                ],
                "options": self._opts,
            }
            resp = self._session.post(
                f"{self.url}/api/chat", json=payload, timeout=self._timeout
            )
            if resp.status_code == 200:
                raw = resp.json().get("message", {}).get("content", "").strip().strip('"\'').strip()
                if raw and raw != text:
                    if self._is_valid_translation(text, raw):
                        return raw
                    self._last_error = "رد غير صالح (رفض أو هلوسة)"
                    print(f"[Ollama] rejected response for {text[:30]!r}: {raw[:60]!r}")
                elif not raw:
                    self._last_error = "استجابة فارغة من النموذج"
                    print(f"[Ollama] empty response for: {text[:40]!r}")
                else:
                    self._last_error = "النموذج أعاد النص دون ترجمة"
                    print(f"[Ollama] identity response: {raw[:40]!r}")
            else:
                try:
                    err_body = resp.json().get("error", resp.text)
                except Exception:
                    err_body = resp.text
                self._last_error = f"خطأ {resp.status_code}: {str(err_body)[:150]}"
                print(f"[Ollama] HTTP {resp.status_code}: {err_body}")

        except requests.exceptions.Timeout:
            self._last_error = f"انتهت مهلة الانتظار ({int(self._timeout)}ث)"
            print(f"[Ollama] timeout ({self._timeout}s) for: {text[:40]!r}")

        except requests.exceptions.ConnectionError as e:
            self._last_error = "انقطع الاتصال بـ Ollama"
            self._is_loaded = False
            print(f"[Ollama] connection error: {e}")

        except Exception as e:
            self._last_error = str(e)
            print(f"[Ollama] _raw_translate: {type(e).__name__}: {e}")

        return None

    # ── Response validators ───────────────────────────────────────────────────

    _REFUSAL_PATTERNS = (
        'أعتذر', 'أنا آسف', 'لا يمكنني', 'يرجى تزويدي', 'يرجى تقديم',
        'أعتقد أنك تقصد', 'يرجى توفير', 'I cannot', "I'm sorry", 'I apologize',
        'Please provide', 'Sure, here is',
    )

    @staticmethod
    def _is_valid_translation(original: str, result: str) -> bool:
        """يتحقق أن الرد ترجمة حقيقية وليس رفضاً أو هلوسة."""
        import re
        # يجب أن يحتوي على عربي
        if not re.search(r'[؀-ۿ]', result):
            return False
        # أنماط رفض معروفة
        for pat in OllamaTranslator._REFUSAL_PATTERNS:
            if pat in result:
                return False
        # هلوسة طولية: نص قصير أعطى ردّاً أطول بكثير
        if len(original.strip()) <= 30 and len(result) > max(len(original) * 5, 120):
            return False
        # هلوسة بالتوكنات: الرد يحوي {} لكن الأصل لا يحويها
        if '{' in result and '{' not in original:
            return False
        return True

    def translate(self, text: str, source_lang: str = "en", target_lang: str = "ar") -> Optional[str]:
        if not self._is_loaded or not self._session:
            self._last_error = "النموذج غير محمّل أو الجلسة منتهية"
            return None
        self._last_error = ""
        try:
            text = self._preprocess(text)
            if not text or len(text) < 2:
                return None
            result = translate_preserving_tokens(text, self._raw_translate)
            return self._postprocess(result) if result else None
        except Exception as e:
            self._last_error = str(e)
            print(f"[Ollama] translate error: {e}")
            return None

    def cancel_current_request(self):
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = requests.Session()

    def unload(self):
        if self._session:
            self._session.close()
        self._session  = None
        self._is_loaded = False


class CustomEndpointTranslator(BaseTranslator):
    
    def __init__(self, name: str, description: str, url: str = "http://localhost:5001/translate"):
        super().__init__(name, description)
        self.url = url.rstrip("/")
        self._session = None
    
    def load(self) -> bool:
        try:
            self._session = requests.Session()
            self._is_loaded = True
            print(f"[Custom] Endpoint ready: {self.url}")
            return True
        except Exception as e:
            print(f"[Custom] Failed: {e}")
            return False
    
    def translate(self, text: str, source_lang: str = "en", target_lang: str = "ar") -> Optional[str]:
        if not self._is_loaded or not self._session:
            return None
        
        try:
            text = self._preprocess(text)
            if not text or len(text) < 2:
                return None
            
            payload = {
                "text": text,
                "source": source_lang,
                "target": target_lang
            }
            
            response = self._session.post(
                self.url,
                json=payload,
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                result = data.get("translated", data.get("translation", data.get("text", "")))
                if result:
                    return self._postprocess(result)
            
            return None
        except Exception as e:
            print(f"[Custom] Translation error: {e}")
            return None
    
    def unload(self):
        if self._session:
            self._session.close()
        self._session = None
        self._is_loaded = False
