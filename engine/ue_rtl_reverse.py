"""
engine/ue_rtl_reverse.py — عكس ترتيب الكلمات لودجات UE التي لا تطبّق BiDi.

بعض ودجات Manor Lords (صفحة المساعدة/الموسوعة) **تُشكّل العربي لكن لا تعكسه** (لا BiDi)
فتظهر الكلمات بترتيب منطقي LTR = معكوسة بصرياً. الحل: نعكس ترتيب الكلمات (الوحدات)
مع إبقاء حروف كل كلمة منطقية (اللعبة تشكّلها) وإبقاء تاقات <h> سليمة.

⚠ لا نُشكّل (presentation forms) — اللعبة تشكّل بنفسها.
⚠ ضروري فقط للودجات بلا BiDi (المساعدة). الودجات السليمة (تلميحات/إعدادات) لا تحتاجه
   (يكسرها double-reverse) — لذا يُطبَّق **انتقائياً لكل نص** عبر engine/rtl_overrides.py.

التفاصيل:
- نقسّم على فواصل الفقرات {br} ونحافظ على ترتيب الفقرات (رأسياً)، نعكس داخل كل فقرة فقط.
- التاقات الزوجية <h>..</> تبقى ملتفّة حول محتواها (مع عكس كلماته داخلياً).
- التاقات الذاتية <img/> تُحذف افتراضياً (تنكسر/تظهر حرفية في السياق المعكوس؛ وهي زخرفية).
  {br} يبقى كفاصل فقرات.
"""
from __future__ import annotations
import re

_SENT = "\x00"
# مجموعة زوجية كاملة: <tag>محتوى</> (مع تاقات ذاتية متقدّمة اختيارية)
_GROUP = re.compile(r'<[A-Za-z][^<>]*(?<!/)>[^<>]*?</>|<[^<>]+>', re.S)
_PAIR_CONTENT = re.compile(r'(<[A-Za-z][^<>]*(?<!/)>)([^<>]*?)(</>)', re.S)
_IMG = re.compile(r'<img[^<>]*/>')
_BR = re.compile(r'(\{br\})')


def _reverse_segment(seg: str) -> str:
    """يعكس كلمات فقرة واحدة (بلا {br})، مبقياً تاقات <h> ملتفّة."""
    def protect(m: re.Match) -> str:
        s = m.group(0)
        def rev_content(mm):
            o, c, cl = mm.groups()
            if " " in c:
                c = " ".join(reversed(c.split(" ")))
            return o + c + cl
        s = _PAIR_CONTENT.sub(rev_content, s)
        return s.replace(" ", _SENT)
    protected = _GROUP.sub(protect, seg)
    tokens = [t for t in protected.split(" ") if t != ""]
    return " ".join(reversed(tokens)).replace(_SENT, " ")


def reverse_for_display(text: str, strip_img: bool = True) -> str:
    if not text or not text.strip():
        return text
    if strip_img:
        text = _IMG.sub(" ", text)          # مسافة بدل فراغ (تمنع التصاق الكلمات)
        text = re.sub(r' {2,}', " ", text)
    # افصل الفقرات على {br} وحافظ على ترتيبها؛ اعكس داخل كل فقرة
    parts = _BR.split(text)
    out = []
    for p in parts:
        if p == "{br}":
            out.append(p)
        else:
            out.append(_reverse_segment(p))
    return "".join(out)


__all__ = ["reverse_for_display"]
