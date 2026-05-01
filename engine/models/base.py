from abc import ABC, abstractmethod
from typing import Optional


class BaseTranslator(ABC):
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._is_loaded = False
    
    @abstractmethod
    def load(self) -> bool:
        pass
    
    @abstractmethod
    def translate(self, text: str, source_lang: str = "en", target_lang: str = "ar") -> Optional[str]:
        pass
    
    @abstractmethod
    def unload(self):
        pass
    
    @property
    def is_loaded(self) -> bool:
        return self._is_loaded
    
    def _preprocess(self, text: str) -> str:
        text = text.strip()
        text = text.replace("\\n", "\n")
        return text
    
    def _postprocess(self, text: str) -> str:
        text = text.strip()
        text = text.replace("\n", "\\n")
        return text
    
    def __repr__(self):
        status = "loaded" if self._is_loaded else "not loaded"
        return f"<{self.__class__.__name__} '{self.name}' [{status}]>"
