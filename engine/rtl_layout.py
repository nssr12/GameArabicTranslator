"""
engine/rtl_layout.py — تخطيط RTL جذري للمحرّكات بلا دعم RTL.

المشكلة المتكرّرة في كل لعبة لا تدعم BiDi:
  1. فاصل الأسطر: قد يكون سطراً فعلياً (0x0a) أو `\\n` حرفياً — نطبّعه.
  2. عكس ترتيب الأسطر: المحرّك يلفّ النص المعكوس مسبقاً من اليسار (LTR) فينقلب
     ترتيب الأسطر رأسياً. الحل: نلفّ الكلمات بأنفسنا (قبل التشكيل) لأسطر قصيرة
     لا تتجاوز عرض الصندوق، فالمحرّك لا يحتاج auto-wrap → لا انقلاب.
  3. لكل سطر: تشكيل (presentation forms) + عكس بصري (BiDi) مستقلّ — فالأسطر
     تبقى بترتيبها الصحيح من فوق لتحت، وكل سطر صحيح يميناً-يساراً.

الناتج: نص بأسطر فعلية (0x0a)، جاهز للعرض في محرّك LTR.

الاستخدام:
    from engine.rtl_layout import layout_rtl
    out = layout_rtl(text, max_line_len=50)   # 0 = بلا لفّ (فواصل صريحة فقط)
"""
from __future__ import annotations
import re
from .arabic_shaper import shape_for_tmp_protected, has_arabic, libs_available

# tokens لا تُكسَر عبر الأسطر (placeholders/tags) — تُعامَل ككلمة واحدة
_TOKEN = re.compile(
    r"<[^>]*>"
    r"|\{[^{}]*\}"
    r"|%[0-9]*[A-Za-z]"
)


def _split_words(text: str):
    """يقسّم على المسافات مع إبقاء الـ tokens ككلمات كاملة."""
    return text.split(" ")


def _wrap_words(text: str, width: int):
    """لفّ كلمات إلى أسطر لا يتجاوز أيّها width حرفاً (تقريب بصري)."""
    words = _split_words(text)
    lines, cur = [], ""
    for w in words:
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            # كلمة أطول من العرض → ضعها وحدها (لا نكسر داخل الكلمة)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def layout_rtl(text: str, max_line_len: int = 0) -> str:
    """يحوّل نصاً منطقياً إلى نص بصري RTL جاهز لمحرّك LTR.

    max_line_len: 0 = احترم الفواصل الصريحة فقط (بلا لفّ). >0 = لفّ الكلمات أيضاً
                  (موصى به للصناديق التي تطبّق auto-wrap).
    """
    if not text or not libs_available():
        return text
    # 1) طبّع فاصل السطر: `\n` حرفي → سطر فعلي
    text = text.replace("\\n", "\n")

    out_lines = []
    for para in text.split("\n"):
        if not para.strip():
            out_lines.append("")          # احفظ السطر الفارغ (فاصل فقرات)
            continue
        if max_line_len and has_arabic(para) and len(para) > max_line_len:
            pieces = _wrap_words(para, max_line_len)
        else:
            pieces = [para]
        # 2) شكّل + اعكس كل سطر مستقلاً (الترتيب الرأسي يُحفظ)
        for piece in pieces:
            out_lines.append(shape_for_tmp_protected(piece))

    # 3) أعد التجميع بأسطر فعلية
    return "\n".join(out_lines)


__all__ = ["layout_rtl"]
