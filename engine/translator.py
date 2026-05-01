import json
import os
from typing import Optional, Dict, List
from engine.models.base import BaseTranslator


class TranslationEngine:
    
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self._config = {}
        self._translators: Dict[str, BaseTranslator] = {}
        self._active_model: Optional[str] = None
        self._load_config()
        self._init_translators()
    
    def _load_config(self):
        try:
            config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), self.config_path)
            if not os.path.exists(config_file):
                config_file = self.config_path
            with open(config_file, "r", encoding="utf-8") as f:
                self._config = json.load(f)
        except Exception as e:
            print(f"[Engine] Config error: {e}")
            self._config = {"models": {}, "default_model": "google_free"}
    
    def _init_translators(self):
        from engine.models.hf_translator import HuggingFaceTranslator, MBartTranslator, NLLBTranslator
        from engine.models.api_translator import GoogleFreeTranslator, OllamaTranslator, CustomEndpointTranslator
        from engine.models.deepl_translator import DeepLTranslator
        
        models_cfg = self._config.get("models", {})
        
        for key, cfg in models_cfg.items():
            try:
                model_type = cfg.get("type", "")
                name = cfg.get("name", key)
                desc = cfg.get("description", "")
                enabled = cfg.get("enabled", False)
                
                translator = None
                
                if model_type == "huggingface":
                    model_name = cfg.get("name", "")
                    if "opus-mt" in model_name:
                        translator = HuggingFaceTranslator(key, desc, model_name)
                    elif "mbart" in model_name:
                        translator = MBartTranslator(key, desc, model_name)
                    elif "nllb" in model_name:
                        translator = NLLBTranslator(key, desc, model_name)
                    else:
                        translator = HuggingFaceTranslator(key, desc, model_name)
                
                elif model_type == "google_free":
                    translator = GoogleFreeTranslator(key, desc)
                
                elif model_type == "ollama":
                    model = cfg.get("model", "llama3")
                    url = cfg.get("url", "http://localhost:11434")
                    translator = OllamaTranslator(key, desc, model, url)
                
                elif model_type == "custom":
                    url = cfg.get("url", "http://localhost:5001/translate")
                    translator = CustomEndpointTranslator(key, desc, url)
                
                elif model_type == "deepl":
                    api_key = cfg.get("api_key", "")
                    tier = cfg.get("tier", "free")
                    translator = DeepLTranslator(key, desc, api_key, tier)
                
                if translator:
                    self._translators[key] = translator
                    
            except Exception as e:
                print(f"[Engine] Error initializing translator '{key}': {e}")
        
        default = self._config.get("default_model", "google_free")
        if default in self._translators:
            self._active_model = default
    
    def get_available_models(self) -> List[dict]:
        models = []
        for key, translator in self._translators.items():
            models.append({
                "key": key,
                "name": translator.name,
                "description": translator.description,
                "is_loaded": translator.is_loaded,
                "is_active": key == self._active_model
            })
        return models
    
    def get_active_model(self) -> Optional[str]:
        return self._active_model
    
    def set_active_model(self, model_key: str) -> bool:
        if model_key in self._translators:
            self._active_model = model_key
            return True
        return False
    
    def load_model(self, model_key: str) -> bool:
        if model_key not in self._translators:
            print(f"[Engine] Model '{model_key}' not found")
            return False
        
        translator = self._translators[model_key]
        if translator.is_loaded:
            return True
        
        print(f"[Engine] Loading model: {model_key}")
        return translator.load()
    
    def unload_model(self, model_key: str):
        if model_key in self._translators:
            self._translators[model_key].unload()
    
    def load_active_model(self) -> bool:
        if self._active_model:
            return self.load_model(self._active_model)
        return False
    
    def translate(self, text: str, model_key: str = None) -> Optional[str]:
        key = model_key or self._active_model
        if not key or key not in self._translators:
            return None
        
        translator = self._translators[key]
        
        if not translator.is_loaded:
            success = translator.load()
            if not success:
                return None
        
        return translator.translate(text)
    
    def translate_batch(self, texts: List[str], model_key: str = None) -> List[Optional[str]]:
        results = []
        for text in texts:
            results.append(self.translate(text, model_key))
        return results
    
    def get_ollama_models(self) -> list:
        if "ollama" in self._translators:
            translator = self._translators["ollama"]
            if hasattr(translator, "list_models"):
                return translator.list_models()
        return []
    
    def set_ollama_model(self, model_name: str) -> bool:
        if "ollama" in self._translators:
            translator = self._translators["ollama"]
            if hasattr(translator, "set_model"):
                translator.set_model(model_name)
                if translator.is_loaded:
                    translator.unload()
                return True
        return False
    
    def get_current_ollama_model(self) -> str:
        if "ollama" in self._translators:
            translator = self._translators["ollama"]
            if hasattr(translator, "model"):
                return translator.model
        return ""
    
    def get_translator(self, model_key: str):
        return self._translators.get(model_key)
    
    def unload_all(self):
        for translator in self._translators.values():
            translator.unload()
    
    def get_status(self) -> dict:
        return {
            "active_model": self._active_model,
            "models": {
                key: {
                    "loaded": t.is_loaded,
                    "description": t.description
                }
                for key, t in self._translators.items()
            }
        }
