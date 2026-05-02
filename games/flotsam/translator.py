import json
import os
import sys
import re
from typing import Optional, Dict, Callable

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

TOKEN_ONLY_RE = re.compile(
    r"(%[A-Z0-9_]+%|\[\{[A-Z0-9_:,]+\}\]|\{[A-Z0-9_:,]+\}|\{\[[A-Z0-9_:,]+\]\})"
)


def mask_tokens(text):
    tokens = []
    def repl(match):
        tokens.append(match.group(0))
        return f"__AGT_{len(tokens)-1}__"
    return TOKEN_ONLY_RE.sub(repl, text), tokens


def restore_tokens(text, tokens):
    result = text
    for i, token in enumerate(tokens):
        marker = f"__AGT_{i}__"
        result = result.replace(marker, token)
    return result


class FlotsamTranslator:
    
    LANGUAGES = [
        "English", "French", "Italian", "German", "Spanish", "Dutch",
        "Japanese", "Korean", "Portuguese", "Russian",
        "Chinese_Simplified", "Chinese_Traditional", "Ukrainian", "Turkish", "Danish"
    ]
    
    def __init__(self, game_path: str, translator_engine=None, cache=None):
        self.game_path = game_path
        self.engine = translator_engine
        self.cache = cache
        self.game_name = "Flotsam"
        self.i2_json_path = os.path.join(game_path, "Flotsam_Data", "I2Languages-resources.assets-115691.json")
        self.output_path = os.path.join(game_path, "BepInEx", "config", "ArabicGameTranslator", "flotsam_i2_translated_only.json")
        self._log_callback: Optional[Callable] = None
        self._progress_callback: Optional[Callable] = None
        self._stop = False
        self._total = 0
        self._translated = 0
        self._cached = 0
        self._failed = 0
    
    def set_callbacks(self, progress: Callable = None, log: Callable = None):
        self._progress_callback = progress
        self._log_callback = log
    
    def _log(self, msg):
        if self._log_callback:
            self._log_callback(msg)
        print(f"[Flotsam] {msg}")
    
    def is_game_valid(self) -> bool:
        return os.path.exists(self.i2_json_path)
    
    def get_terms_count(self) -> int:
        try:
            with open(self.i2_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            terms = data.get("mSource", {}).get("mTerms", {}).get("Array", [])
            return len(terms)
        except:
            return 0
    
    def extract_english_terms(self) -> Dict[str, str]:
        with open(self.i2_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        terms = data.get("mSource", {}).get("mTerms", {}).get("Array", [])
        result = {}
        
        for term in terms:
            term_name = term.get("Term", "")
            languages = term.get("Languages", {}).get("Array", [])
            
            if not term_name or not languages:
                continue
            
            english = languages[0] if len(languages) > 0 else ""
            
            if english and isinstance(english, str) and len(english.strip()) >= 2:
                result[term_name] = english.strip()
        
        return result
    
    def _translate_with_token_protection(self, text):
        cached = self.cache.get(self.game_name, text) if self.cache else None
        if cached:
            return cached
        
        masked, tokens = mask_tokens(text)
        
        result = self.engine.translate(masked) if self.engine else None
        if not result or not result.strip() or result == masked:
            return None
        
        final = restore_tokens(result, tokens)
        
        if self.cache:
            self.cache.put(self.game_name, text, final, self.engine.get_active_model() or "unknown")
        
        return final
    
    def translate_all(self) -> bool:
        self._stop = False
        self._translated = 0
        self._cached = 0
        self._failed = 0
        
        if not self.is_game_valid():
            self._log(f"I2Languages file not found: {self.i2_json_path}")
            return False
        
        self._log("Extracting English terms...")
        terms = self.extract_english_terms()
        self._total = len(terms)
        self._log(f"Found {self._total} terms to translate")
        
        entries = []
        
        for term_name, english_text in terms.items():
            if self._stop:
                self._log("Translation stopped")
                break
            
            cached = self.cache.get(self.game_name, english_text) if self.cache else None
            if cached:
                entries.append({"key": term_name, "Arabic": cached})
                self._cached += 1
            else:
                result = self._translate_with_token_protection(english_text)
                if result:
                    entries.append({"key": term_name, "Arabic": result})
                    self._translated += 1
                else:
                    self._failed += 1
            
            done = self._translated + self._cached + self._failed
            if self._progress_callback:
                self._progress_callback(done, self._total, self._cached, self._failed)
            
            if done % 50 == 0:
                self._log(f"Progress: {done}/{self._total}")
        
        self._log(f"Writing {len(entries)} entries to JSON...")
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        
        payload = {"entries": entries}
        with open(self.output_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        
        self._log(f"Saved: {self.output_path}")
        self._log(f"Total: {self._total} | Translated: {self._translated} | Cached: {self._cached} | Failed: {self._failed}")
        return True
    
    def stop(self):
        self._stop = True
    
    def get_stats(self) -> dict:
        return {
            "total": self._total,
            "translated": self._translated,
            "cached": self._cached,
            "failed": self._failed,
        }
