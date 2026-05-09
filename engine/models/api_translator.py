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
        "2. Preserve ALL formatting tokens exactly as-is: {0} {1} {playerName} \\n <color=#ff0000> </color> [b] [/b] %s %d — never translate or modify them.\n"
        "3. Preserve punctuation structure that matches the original (ellipsis, exclamation marks, etc.).\n"
        "4. Never add content that is not in the original text.\n"
        "5. If the input is already Arabic or is untranslatable (a proper noun, a code), return it unchanged.\n\n"
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

    def __init__(self, name: str, description: str, model: str = "llama3", url: str = "http://localhost:11434",
                 config_path: str = "config.json"):
        super().__init__(name, description)
        self.model = model
        self.url = url.rstrip("/")
        self.config_path = config_path
        self._session = None
        self._available_models = []
        self.system_prompt = _default_ollama_system_prompt()
    
    def list_models(self) -> list:
        try:
            if not self._session:
                self._session = requests.Session()
            resp = self._session.get(f"{self.url}/api/tags", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                self._available_models = [
                    {
                        "name": m.get("name", ""),
                        "size": m.get("size", 0),
                        "size_gb": round(m.get("size", 0) / (1024**3), 1),
                        "family": m.get("details", {}).get("family", ""),
                        "parameter_size": m.get("details", {}).get("parameter_size", ""),
                        "quantization": m.get("details", {}).get("quantization_level", ""),
                        "modified": m.get("modified_at", "")[:10],
                    }
                    for m in models
                ]
                return self._available_models
            return []
        except Exception as e:
            print(f"[Ollama] Failed to list models: {e}")
            return []
    
    def set_model(self, model_name: str):
        self.model = model_name
        print(f"[Ollama] Model set to: {model_name}")
    
    def load(self) -> bool:
        try:
            self._session = requests.Session()
            resp = self._session.get(f"{self.url}/api/tags", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                self._available_models = [
                    {"name": m.get("name", ""), "size": m.get("size", 0)}
                    for m in models
                ]
                self._is_loaded = True
                opts = _load_ollama_options(self.config_path)
                print(f"[Ollama] Connected → {self.url}  model: {self.model}")
                print(f"[Ollama] Options → gpu={opts.get('num_gpu')}  ctx={opts.get('num_ctx')}  "
                      f"batch={opts.get('num_batch')}  predict={opts.get('num_predict')}  "
                      f"temp={opts.get('temperature')}  timeout={opts.get('timeout', 60)}s")
                return True
            else:
                print(f"[Ollama] Server responded with status {resp.status_code}")
                return False
        except Exception as e:
            print(f"[Ollama] Failed to connect: {e}")
            return False
    
    def _raw_translate(self, text: str) -> Optional[str]:
        opts = _load_ollama_options(self.config_path)
        timeout = opts.pop("timeout", 60)
        payload = {
            "model": self.model,
            "prompt": f'English: "{text}"\nArabic:',
            "system": self.system_prompt,
            "stream": False,
            "options": opts,
        }
        response = self._session.post(f"{self.url}/api/generate", json=payload, timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            raw = data.get("response", "").strip().strip('"').strip("'").strip()
            if raw and raw != text:
                return raw
        return None

    def translate(self, text: str, source_lang: str = "en", target_lang: str = "ar") -> Optional[str]:
        if not self._is_loaded or not self._session:
            return None
        try:
            text = self._preprocess(text)
            if not text or len(text) < 2:
                return None
            result = translate_preserving_tokens(text, self._raw_translate)
            return self._postprocess(result) if result else None
        except Exception as e:
            print(f"[Ollama] Translation error: {e}")
            return None

    def cancel_current_request(self):
        """Close session to interrupt any in-flight request, then recreate it."""
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = requests.Session()

    def unload(self):
        if self._session:
            self._session.close()
        self._session = None
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
