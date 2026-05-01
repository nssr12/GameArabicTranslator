import requests
import json
from typing import Optional
from engine.models.base import BaseTranslator
import time
import re


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
    
    def translate(self, text: str, source_lang: str = "en", target_lang: str = "ar") -> Optional[str]:
        if not self._is_loaded or not self._session:
            return None
        
        try:
            text = self._preprocess(text)
            if not text or len(text) < 2:
                return None
            
            params = {
                "client": "gtx",
                "sl": source_lang,
                "tl": target_lang,
                "dt": "t",
                "q": text
            }
            
            response = self._session.get(
                self.BASE_URL,
                params=params,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0 and data[0]:
                    translated_parts = []
                    for part in data[0]:
                        if part and part[0]:
                            translated_parts.append(part[0])
                    result = "".join(translated_parts)
                    if result and result != text:
                        return self._postprocess(result)
            
            return None
        except Exception as e:
            print(f"[Google] Translation error: {e}")
            return None
    
    def unload(self):
        if self._session:
            self._session.close()
        self._session = None
        self._is_loaded = False


class OllamaTranslator(BaseTranslator):
    
    def __init__(self, name: str, description: str, model: str = "llama3", url: str = "http://localhost:11434"):
        super().__init__(name, description)
        self.model = model
        self.url = url.rstrip("/")
        self._session = None
        self._available_models = []
        self.system_prompt = "You are a professional game text translator. Translate the following English text to Arabic. Reply ONLY with the Arabic translation, nothing else."
    
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
                print(f"[Ollama] Connected to {self.url}, model: {self.model}")
                return True
            else:
                print(f"[Ollama] Server responded with status {resp.status_code}")
                return False
        except Exception as e:
            print(f"[Ollama] Failed to connect: {e}")
            return False
    
    def translate(self, text: str, source_lang: str = "en", target_lang: str = "ar") -> Optional[str]:
        if not self._is_loaded or not self._session:
            return None
        
        try:
            text = self._preprocess(text)
            if not text or len(text) < 2:
                return None
            
            payload = {
                "model": self.model,
                "prompt": f'English: "{text}"\nArabic:',
                "system": self.system_prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 200
                }
            }
            
            response = self._session.post(
                f"{self.url}/api/generate",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                result = data.get("response", "").strip()
                result = result.strip('"').strip("'").strip()
                if result:
                    return self._postprocess(result)
            
            return None
        except Exception as e:
            print(f"[Ollama] Translation error: {e}")
            return None
    
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
