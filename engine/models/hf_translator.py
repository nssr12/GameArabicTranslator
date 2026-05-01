from typing import Optional
from engine.models.base import BaseTranslator


class HuggingFaceTranslator(BaseTranslator):
    
    def __init__(self, name: str, description: str, model_name: str):
        super().__init__(name, description)
        self.model_name = model_name
        self._pipeline = None
        self._tokenizer = None
        self._model = None
    
    def load(self) -> bool:
        try:
            from transformers import MarianMTModel, MarianTokenizer
            import torch
            
            print(f"[HF] Loading model: {self.model_name}")
            self._tokenizer = MarianTokenizer.from_pretrained(self.model_name)
            self._model = MarianMTModel.from_pretrained(self.model_name)
            
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = self._model.to(device)
            self._device = device
            
            self._is_loaded = True
            print(f"[HF] Model loaded on {device}")
            return True
        except Exception as e:
            print(f"[HF] Failed to load model: {e}")
            self._is_loaded = False
            return False
    
    def translate(self, text: str, source_lang: str = "en", target_lang: str = "ar") -> Optional[str]:
        if not self._is_loaded:
            return None
        
        try:
            text = self._preprocess(text)
            if not text:
                return None
            
            inputs = self._tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
            
            import torch
            with torch.no_grad():
                outputs = self._model.generate(**inputs, max_length=512, num_beams=4)
            
            result = self._tokenizer.decode(outputs[0], skip_special_tokens=True)
            return self._postprocess(result)
        except Exception as e:
            print(f"[HF] Translation error: {e}")
            return None
    
    def unload(self):
        self._model = None
        self._tokenizer = None
        self._device = None
        self._is_loaded = False
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except:
            pass


class MBartTranslator(BaseTranslator):
    
    def __init__(self, name: str, description: str, model_name: str):
        super().__init__(name, description)
        self.model_name = model_name
        self._tokenizer = None
        self._model = None
    
    def load(self) -> bool:
        try:
            from transformers import MBartForConditionalGeneration, MBart50TokenizerFast
            import torch
            
            print(f"[mBART] Loading model: {self.model_name}")
            self._tokenizer = MBart50TokenizerFast.from_pretrained(self.model_name)
            self._model = MBartForConditionalGeneration.from_pretrained(self.model_name)
            
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = self._model.to(device)
            self._device = device
            
            self._is_loaded = True
            print(f"[mBART] Model loaded on {device}")
            return True
        except Exception as e:
            print(f"[mBART] Failed to load model: {e}")
            self._is_loaded = False
            return False
    
    def translate(self, text: str, source_lang: str = "en", target_lang: str = "ar") -> Optional[str]:
        if not self._is_loaded:
            return None
        
        try:
            text = self._preprocess(text)
            if not text:
                return None
            
            self._tokenizer.src_lang = "en_XX"
            
            inputs = self._tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
            
            import torch
            with torch.no_grad():
                outputs = self._model.generate(
                    **inputs,
                    max_length=512,
                    num_beams=4,
                    forced_bos_token_id=self._tokenizer.lang_code_to_id["ar_AR"]
                )
            
            result = self._tokenizer.decode(outputs[0], skip_special_tokens=True)
            return self._postprocess(result)
        except Exception as e:
            print(f"[mBART] Translation error: {e}")
            return None
    
    def unload(self):
        self._model = None
        self._tokenizer = None
        self._device = None
        self._is_loaded = False
        import gc
        gc.collect()


class NLLBTranslator(BaseTranslator):
    
    def __init__(self, name: str, description: str, model_name: str):
        super().__init__(name, description)
        self.model_name = model_name
        self._tokenizer = None
        self._model = None
    
    def load(self) -> bool:
        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            import torch
            
            print(f"[NLLB] Loading model: {self.model_name}")
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
            
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = self._model.to(device)
            self._device = device
            
            self._is_loaded = True
            print(f"[NLLB] Model loaded on {device}")
            return True
        except Exception as e:
            print(f"[NLLB] Failed to load model: {e}")
            self._is_loaded = False
            return False
    
    def translate(self, text: str, source_lang: str = "eng_Latn", target_lang: str = "arb_Arab") -> Optional[str]:
        if not self._is_loaded:
            return None
        
        try:
            text = self._preprocess(text)
            if not text:
                return None
            
            self._tokenizer.src_lang = source_lang
            
            inputs = self._tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
            
            import torch
            with torch.no_grad():
                outputs = self._model.generate(
                    **inputs,
                    max_length=512,
                    num_beams=4,
                    forced_bos_token_id=self._tokenizer.convert_tokens_to_ids(target_lang)
                )
            
            result = self._tokenizer.decode(outputs[0], skip_special_tokens=True)
            return self._postprocess(result)
        except Exception as e:
            print(f"[NLLB] Translation error: {e}")
            return None
    
    def unload(self):
        self._model = None
        self._tokenizer = None
        self._device = None
        self._is_loaded = False
        import gc
        gc.collect()
