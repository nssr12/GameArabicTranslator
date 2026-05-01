import re

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    ARABIC_LIBS_AVAILABLE = True
except ImportError:
    ARABIC_LIBS_AVAILABLE = False


def reshape_arabic(text: str) -> str:
    if not text or not ARABIC_LIBS_AVAILABLE:
        return text
    
    if not re.search(r'[\u0600-\u06FF]', text):
        return text
    
    try:
        reshaped = arabic_reshaper.reshape(text)
        display = get_display(reshaped)
        return display
    except Exception:
        return text


def reshape_arabic_keep_tags(text: str) -> str:
    if not text or not ARABIC_LIBS_AVAILABLE:
        return text
    
    if not re.search(r'[\u0600-\u06FF]', text):
        return text
    
    try:
        tag_pattern = re.compile(r'(<[^>]+>|{[^}]*})')
        tags = []
        def replace_tag(match):
            tags.append(match.group(0))
            return f"__TAG{len(tags)-1}__"
        
        protected = tag_pattern.sub(replace_tag, text)
        reshaped = arabic_reshaper.reshape(protected)
        display = get_display(reshaped)
        
        for i, tag in enumerate(tags):
            display = display.replace(f"__TAG{i}__", tag)
        
        return display
    except Exception:
        return text
