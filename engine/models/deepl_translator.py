import requests
import json
from typing import Optional
from engine.models.base import BaseTranslator


class DeepLTranslator(BaseTranslator):
    
    def __init__(self, name: str, description: str, api_key: str = "", tier: str = "free"):
        super().__init__(name, description)
        self.api_key = api_key
        self.tier = tier
        self._session = None
        self._base_url = "https://api-free.deepl.com" if tier == "free" else "https://api.deepl.com"
    
    def load(self) -> bool:
        try:
            self._session = requests.Session()
            if self.api_key:
                self._is_loaded = True
                print(f"[DeepL] Ready (tier: {self.tier})")
                return True
            else:
                print("[DeepL] No API key provided")
                return False
        except Exception as e:
            print(f"[DeepL] Failed: {e}")
            return False
    
    def translate(self, text: str, source_lang: str = "EN", target_lang: str = "AR") -> Optional[str]:
        if not self._is_loaded or not self._session:
            return None
        
        try:
            text = self._preprocess(text)
            if not text or len(text) < 2:
                return None
            
            response = self._session.post(
                f"{self._base_url}/v2/translate",
                data={
                    "auth_key": self.api_key,
                    "text": text,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "preserve_formatting": "1",
                    "tag_handling": "html",
                },
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                translations = data.get("translations", [])
                if translations:
                    result = translations[0].get("text", "")
                    if result:
                        return self._postprocess(result)
            
            return None
        except Exception as e:
            print(f"[DeepL] Error: {e}")
            return None
    
    def unload(self):
        if self._session:
            self._session.close()
        self._session = None
        self._is_loaded = False
    
    def set_api_key(self, key: str):
        self.api_key = key
        if key:
            self._is_loaded = True
