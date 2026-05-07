import re
from abc import ABC, abstractmethod
from typing import Optional, List

# ── Token pattern — matches special game/engine symbols ───────────────────────
# These tokens must NEVER be sent to the translation API.
# Strategy: split the text at token boundaries, translate only the text segments,
# then reassemble — tokens are never touched.
TOKEN_RE = re.compile(
    r'('
    r'\{[^{}]{0,60}\}'                    # {0}  {playerName}  {damage:.2f}
    r'|</?[a-zA-Z][^<>]{0,120}>'          # <color=#ff0000>  </b>  <GlobalColor.Attention>
    r'|</>'                               # </> — Unity/UE short closing tag (Grounded2 etc.)
    r'|\[[a-zA-Z/#][^\[\]]{0,60}\]'       # [b]  [/color=red]  [sprite icon]
    r'|\\[nrtbf\\]'                        # \n  \t  \r  \b  \f  \\
    r'|%(?:[0-9]+\$)?[-+0 #]*[0-9]*(?:\.[0-9]+)?[sdifgeoxXu%]'  # %s %d %1$s %.2f
    r'|\|[A-Za-z0-9_]+\|'                 # |icon_name|
    r'|&(?:[a-zA-Z]+|#[0-9]+);'           # &amp;  &lt;  &#39;
    r')'
)


def translate_preserving_tokens(text: str, raw_translate_fn) -> Optional[str]:
    """
    Split text at protected token boundaries, translate non-token segments
    individually, then reassemble.  Tokens are NEVER sent to the API.

    raw_translate_fn(segment: str) -> Optional[str]
        Called for each non-token text segment.
    """
    parts = TOKEN_RE.split(text)   # capturing group → [text, token, text, token, …]

    if len(parts) == 1:
        # No tokens found — translate the whole text at once
        translated = raw_translate_fn(text)
        if translated and '\n' not in text and '\n' in translated:
            translated = translated.replace('\n', ' ').strip()
        return translated

    result: List[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            # Odd indices = captured token groups → keep unchanged
            result.append(part)
        else:
            # Even indices = text segments between tokens → translate
            if part.strip():
                translated = raw_translate_fn(part)
                if translated:
                    # Don't allow the API to inject newlines that weren't in the original
                    if '\n' not in part and '\n' in translated:
                        translated = translated.replace('\n', ' ').strip()
                    result.append(translated)
                else:
                    result.append(part)
            else:
                result.append(part)   # preserve whitespace / empty strings

    joined = ''.join(result)
    return joined if joined else None


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
