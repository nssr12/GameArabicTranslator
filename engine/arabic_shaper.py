"""
engine/arabic_shaper.py — تحويل النص العربي المنطقي إلى presentation forms
                          مع عكس بصري (RTL) ليُعرض صحيحاً في Unity TMP.

يُستخدم عندما لا تقدر اللعبة على تطبيق Arabic shaping/BiDi تلقائياً —
شائع في خطوط TMP افتراضية. النتيجة: نص جاهز للعرض كما هو (LTR rendering).

أمثلة:
    "متابعة"  →  "ﺔﻌﺑﺎﺘﻣ" (شكل بصري + معكوس)
    "Press X to continue" → "Press X to continue" (لا تغيير، ليس عربي)

يحافظ على:
  - HTML/TMP tags كما هي (<b>, <color>, etc.)
  - placeholders ({0}, {playerName})
  - newlines (\n) و LTR runs (إنجليزي، أرقام، رموز)
"""
from __future__ import annotations

import re
from typing import Optional

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    _LIBS_OK = True
except ImportError:
    _LIBS_OK = False


# ── إعداد reshaper ──────────────────────────────────────────────────────────

_configuration = {
    "delete_harakat": False,        # احفظ التشكيل لو موجود
    "support_ligatures": True,      # Lam-Alef ligatures
    "support_zwj": True,            # Zero-Width Joiner
    "language": "Arabic",
}

_reshaper_instance = None


def _get_reshaper():
    global _reshaper_instance
    if _reshaper_instance is None and _LIBS_OK:
        _reshaper_instance = arabic_reshaper.ArabicReshaper(
            configuration=_configuration
        )
    return _reshaper_instance


def has_arabic(text: str) -> bool:
    """فحص سريع: هل النص يحوي حروف عربية أساسية (U+0600-U+06FF)؟"""
    if not text:
        return False
    return any("؀" <= c <= "ۿ" for c in text)


def shape_for_tmp(text: str) -> str:
    """يحوّل نصاً عربياً منطقياً إلى presentation forms مع عكس بصري.

    لو الـ libs غير مثبتة → يرجع النص كما هو (no-op آمن).
    لو النص لا يحوي عربي → يرجعه كما هو.
    """
    if not text or not _LIBS_OK or not has_arabic(text):
        return text
    try:
        reshaper = _get_reshaper()
        reshaped = reshaper.reshape(text)
        # get_display يطبّق Unicode BiDi Algorithm → النتيجة جاهزة للعرض LTR
        return get_display(reshaped)
    except Exception:
        return text


# ── شكل متقدّم: shaping مع حماية tags و placeholders ──────────────────────────

# نمط يلتقط ما يجب ألا يُعالَج (تاقات، placeholders، newlines literal)
_PROTECT_RE = re.compile(
    r"<[^>]*>"                          # <b>, <color=#fff>, </color>
    r"|\{[A-Za-z_][\w.]*\}"             # {playerName}, {item.name}
    r"|\{[0-9]+(:[^}]*)?\}"             # {0}, {1:N2}
    r"|%[0-9]*[A-Za-z]"                 # %d, %s, %1$s
    r"|\\n"                             # \n حرفي
)


def shape_for_tmp_protected(text: str) -> str:
    """نفس shape_for_tmp لكن مع حماية تاقات/placeholders من العكس.

    الخوارزمية:
      1. استخرج كل المقاطع المحمية وعوّضها بـ placeholders فريدة
      2. شكّل + اعكس النص (presentation forms + BiDi)
      3. أرجِع الـ placeholders إلى أماكنها

    ⚠ بعد العكس، ترتيب placeholders قد ينعكس في النص بصرياً —
       هذا مقبول لأن TMP يعرض النص الناتج LTR، فالتاقات تظهر بترتيب صحيح
       بصرياً مع النص العربي (المعكوس).
    """
    if not text or not _LIBS_OK or not has_arabic(text):
        return text

    protected: list[str] = []

    def _save(m: re.Match) -> str:
        # نستخدم Private Use Area chars كـ placeholders — لا تتأثر بـ BiDi
        ph = f"{len(protected):03d}"
        protected.append(m.group(0))
        return ph

    cleaned = _PROTECT_RE.sub(_save, text)
    shaped = shape_for_tmp(cleaned)

    # رجوع الـ placeholders (نلاحظ أن BiDi قد يكون عكس ترتيبهم بصرياً)
    for i, original in enumerate(protected):
        ph = f"{i:03d}"
        shaped = shaped.replace(ph, original)

    return shaped


# ── معالجة دفعة قاموس كاملة ────────────────────────────────────────────────

def shape_dict_for_tmp(d: dict, *, protect_tags: bool = True) -> dict:
    """يطبّق shape على كل قيم القاموس. يستخدم النسخة المحمية افتراضياً."""
    fn = shape_for_tmp_protected if protect_tags else shape_for_tmp
    return {k: fn(v) if isinstance(v, str) else v for k, v in d.items()}


def libs_available() -> bool:
    """هل arabic_reshaper و python-bidi مثبتتان؟"""
    return _LIBS_OK


__all__ = [
    "has_arabic",
    "shape_for_tmp",
    "shape_for_tmp_protected",
    "shape_dict_for_tmp",
    "libs_available",
]
