import re
from typing import Optional


class TextValidator:
    
    MIN_LENGTH = 2
    MAX_LENGTH = 500
    
    SKIP_PATTERNS = [
        r'^[0-9a-fA-F]{8,}$',
        r'^0x[0-9a-fA-F]+$',
        r'^[\x00-\x1F\x7F-\x9F]+$',
        r'^[\d\s\.\,\-\+\=\%\$\#\@\!\&\*\(\)\[\]]+$',
        r'\.(dll|exe|txt|json|xml|xpy|pak|uasset|png|jpg|dds|tga|bmp)$',
        r'^(null|undefined|true|false|none|nan)$',
        r'^[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]+',
    ]
    
    SKIP_KEYWORDS = [
        'debug', 'error', 'warning', 'exception', 'stacktrace',
        'shader', 'texture', 'mesh', 'bone', 'skeleton',
        'animation', 'anim_', 'material', 'particle',
        '.dll', '.exe', '.so', '.dylib',
        'http://', 'https://', 'ftp://',
        'c:\\', 'd:\\', '/usr/', '/var/',
    ]
    
    @classmethod
    def is_valid_text(cls, text: str) -> bool:
        if not text or not isinstance(text, str):
            return False
        
        text = text.strip()
        
        if len(text) < cls.MIN_LENGTH or len(text) > cls.MAX_LENGTH:
            return False
        
        if cls._contains_arabic(text):
            return False
        
        for pattern in cls.SKIP_PATTERNS:
            if re.match(pattern, text, re.IGNORECASE):
                return False
        
        text_lower = text.lower()
        for keyword in cls.SKIP_KEYWORDS:
            if keyword in text_lower:
                return False
        
        if cls._non_printable_ratio(text) > 0.1:
            return False
        
        if not re.search(r'[a-zA-Z]', text):
            return False
        
        letter_count = len(re.findall(r'[a-zA-Z]', text))
        if letter_count < 2:
            return False
        
        return True
    
    @classmethod
    def _contains_arabic(cls, text: str) -> bool:
        return bool(re.search(r'[\u0600-\u06FF]', text))
    
    @classmethod
    def _non_printable_ratio(cls, text: str) -> float:
        if not text:
            return 0.0
        non_printable = sum(
            1 for c in text
            if not (32 <= ord(c) <= 126 or 0x0600 <= ord(c) <= 0x06FF or 160 <= ord(c) <= 255)
        )
        return non_printable / len(text)
    
    @classmethod
    def normalize(cls, text: str) -> str:
        text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    @classmethod
    def clean_for_cache(cls, text: str) -> str:
        return cls.normalize(text)
