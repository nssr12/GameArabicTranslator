import re
from abc import ABC, abstractmethod
from typing import Optional, List

# ── Token pattern — matches ALL protected tokens including HTML tags ──────────
TOKEN_RE = re.compile(
    r'('
    r'</?\{[^{}]{0,60}\}[^<>]{0,60}>'    # <{prefix}>  </{var}>  <{tag} attrs>
    r'|\{[^{}]{0,60}\}'                   # {0}  {playerName}  {damage:.2f}
    r'|</?[a-zA-Z][^<>]{0,120}>'          # <color=#ff0000>  </b>  <GlobalColor>
    r'|</>'                               # </> — Unity/UE short closing tag
    r'|\[[a-zA-Z/#][^\[\]]{0,60}\]'      # [b]  [/color=red]  [sprite icon]
    r'|\\[nrtbf\\]'                       # \n \r \t \b \f \\ (literal escape seqs)
    r'|%[A-Za-z_][A-Za-z0-9_]*%'         # %DAY%  %HOTKEY%  %FILESIZE%
    r'|%(?:[0-9]+\$)?[-+0 #]*[0-9]*(?:\.[0-9]+)?[sdifgeoxXu%]'  # %s %d %1$s %.2f
    r'|\|[A-Za-z0-9_]+\|'               # |icon_name|
    r'|&(?:[a-zA-Z]+|#[0-9]+);'          # &amp;  &lt;  &#39;
    r')')

# ── Hard separators — tokens that break sentence flow (excludes HTML tags) ────
# HTML tags are NOT hard separators: the model receives the full sentence with
# tags intact so it can translate in full context. The actual newline char is
# included because _preprocess() converts \n → real newline before we get here.
_HARD_SEP_RE = re.compile(
    r'('
    r'</?\{[^{}]{0,60}\}[^<>]{0,60}>'    # <{prefix}>  </{var}>
    r'|\{[^{}]{0,60}\}'                   # {0}  {playerName}
    r'|</>'                               # </>
    r'|\[[a-zA-Z/#][^\[\]]{0,60}\]'      # [b]  [/color=red]
    r'|\\[nrtbf\\]'                       # literal \n \r \t (before _preprocess)
    '|\n'                                  # actual newline (after _preprocess \n→\n)
    r'|%[A-Za-z_][A-Za-z0-9_]*%'         # %DAY%
    r'|%(?:[0-9]+\$)?[-+0 #]*[0-9]*(?:\.[0-9]+)?[sdifgeoxXu%]'  # %s %d
    r'|\|[A-Za-z0-9_]+\|'               # |icon_name|
    r'|&(?:[a-zA-Z]+|#[0-9]+);'          # &amp;
    r')')

# ── Inline HTML tag detection ─────────────────────────────────────────────────
_HTML_TAG_RE = re.compile(r'</?[a-zA-Z][^<>]{0,120}>')
_HAS_TEXT_RE = re.compile(r'[A-Za-z؀-ۿ\d]')


# ── فرض تماثل علامة نهاية الجملة ──────────────────────────────────────────────
# المودلات الصغيرة (12b) تميل لإضافة نقطة في نهاية الترجمة حتى لو الأصل بلا نقطة،
# رغم تعليمات البرومت. هذا حتمي (لا يعتمد على طاعة المودل): لو الأصل لا ينتهي
# بعلامة نهاية جملة، نحذف العلامة التي أضافها المودل.
_END_PUNCT = ".!?؟。！．؛"
# تاقات (فتح/إغلاق) + مسافات في نهاية النص — نتجاهلها عند فحص آخر حرف "حقيقي"
_TRAILING_TAGS_WS = re.compile(r'(?:\s|</?[a-zA-Z][^<>]{0,120}>)+$')


def _ends_with_sentence_punct(s: str) -> bool:
    core = _TRAILING_TAGS_WS.sub('', (s or '').rstrip())
    return bool(core) and core[-1] in _END_PUNCT


def enforce_trailing_punctuation(src: str, translated: str) -> str:
    """يفرض تماثل علامة النهاية: لو الأصل لا ينتهي بعلامة نهاية جملة، يحذف
    علامة أضافها المودل في الترجمة — سواء كانت في النهاية أو قبل تاقات إغلاق.
       "Cavalry</color>"  +  "الفرسان</color>."  →  "الفرسان</color>"
    لا يلمس الترجمة إذا كان الأصل ينتهي بعلامة (التماثل محفوظ)."""
    if not translated or not src:
        return translated
    if _ends_with_sentence_punct(src):
        return translated   # الأصل ينتهي بعلامة → لا تغيير
    # افصل التاقات/المسافات النهائية لنصل لجسم النص ثم افحص آخر حرف
    m = _TRAILING_TAGS_WS.search(translated)
    if m and m.start() > 0:
        body, tail = translated[:m.start()], translated[m.start():]
    else:
        body, tail = translated, ''
    body_r = body.rstrip()
    if body_r and body_r[-1] in _END_PUNCT:
        return body_r[:-1].rstrip() + tail
    return translated


def _strip_hallucinated_tokens(translated: str) -> str:
    """Remove tokens (e.g. {0}, <tag>) the AI hallucinated in a plain-text segment."""
    cleaned = TOKEN_RE.sub('', translated)
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
    cleaned = re.sub(r'\s+([.,;:!؟?])', r'\1', cleaned)
    return cleaned.strip()


def _strip_nontag_tokens(translated: str) -> str:
    """Remove only hard-separator tokens (not HTML) the AI hallucinated."""
    cleaned = _HARD_SEP_RE.sub('', translated)
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
    cleaned = re.sub(r'\s+([.,;:!؟?])', r'\1', cleaned)
    return cleaned.strip()


def translate_preserving_tokens(text: str, raw_translate_fn) -> Optional[str]:
    """
    Split text at hard-separator boundaries ({0}, newline, %s …), translate each
    segment with its inline HTML tags INTACT so the model sees full sentence
    context. HTML tags are never used as split points.

    raw_translate_fn(segment: str) -> Optional[str]
    """
    parts = _HARD_SEP_RE.split(text)

    def _translate_seg(seg: str) -> Optional[str]:
        if not seg.strip():
            return seg
        leading  = seg[: len(seg) - len(seg.lstrip())]
        trailing = seg[len(seg.rstrip()):]
        seg_stripped = seg.strip()

        # Skip segments that contain only HTML tags — nothing to translate.
        content_only = _HTML_TAG_RE.sub('', seg_stripped).strip()
        if not _HAS_TEXT_RE.search(content_only):
            return seg

        has_html = bool(_HTML_TAG_RE.search(seg_stripped))

        translated = raw_translate_fn(seg_stripped)
        if not translated:
            return None

        # If the original had no newline but translation added one, flatten it.
        if '\n' not in seg and '\n' in translated:
            translated = translated.replace('\n', ' ').strip()

        if has_html:
            # Segment had HTML — preserve tags the model kept, only strip
            # hard-separator tokens ({0}, %s …) that may have been hallucinated.
            translated = _strip_nontag_tokens(translated)
        else:
            translated = _strip_hallucinated_tokens(translated)

        return (leading + translated + trailing) if translated else None

    if len(parts) == 1:
        return _translate_seg(text)

    result: List[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            result.append(part)   # hard-separator token — keep as-is
        else:
            seg_result = _translate_seg(part)
            result.append(seg_result if seg_result is not None else part)

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
