"""
engine/ue_rtl_reverse.py — عكس ترتيب الكلمات لودجات UE التي لا تطبّق BiDi.

بعض ودجات Manor Lords (صفحة المساعدة/الموسوعة) **تُشكّل العربي لكن لا تعكسه** (لا BiDi)
فتظهر الكلمات بترتيب منطقي LTR = معكوسة بصرياً. الحل: نعكس ترتيب الكلمات (الوحدات)
مع إبقاء حروف كل كلمة منطقية (اللعبة تشكّلها) وإبقاء التاقات والأيقونات سليمة.

⚠ لا نُشكّل (presentation forms) — اللعبة تشكّل بنفسها.
⚠ ضروري فقط للودجات بلا BiDi (المساعدة). الودجات السليمة (تلميحات) لا تحتاجه
   (يكسرها double-reverse) — لذا يُطبَّق **انتقائياً لكل نص** عبر engine/rtl_overrides.py.

التفاصيل:
- نقسّم على فواصل الفقرات {br} ونحافظ على ترتيب الفقرات (رأسياً)، نعكس داخل كل فقرة.
- **لفّ ذاتي للأسطر** (max_line_len): نلفّ كل فقرة لأسطر ≤ عرض الصندوق ونعكس كلمات كل
  سطر مع الإبقاء على ترتيب الأسطر؛ نفصلها بـ {br} صريح → اللعبة لا تلفّ تلقائياً → لا
  ينقلب ترتيب الأسطر رأسياً (نفس حلّ Foundation rtl_layout، لكن بلا تشكيل).
- التاقات الزوجية <h>..</> تبقى ملتفّة حول محتواها (مع عكس كلماته داخلياً).
- الأيقونات <img/> تبقى ملتصقة بكلمتها (مفردة). تُحذف فقط لو strip_img=True.
"""
from __future__ import annotations
import re

_SENT = "\x00"
_GROUP = re.compile(r'<[A-Za-z][^<>]*(?<!/)>[^<>]*?</>|<[^<>]+>', re.S)
_PAIR_CONTENT = re.compile(r'(<[A-Za-z][^<>]*(?<!/)>)([^<>]*?)(</>)', re.S)
_TAGS = re.compile(r'<[^<>]+>|\{[^{}]*\}')
_IMG = re.compile(r'<img[^<>]*/>')
_BR = re.compile(r'(\{br\})')


def _protect(m: re.Match) -> str:
    """يعكس كلمات محتوى التاق الزوجي + يحمي مسافاته بسنتينل (يصبح رمزاً واحداً)."""
    s = m.group(0)
    def rev_content(mm):
        o, c, cl = mm.groups()
        if " " in c:
            c = " ".join(reversed(c.split(" ")))
        return o + c + cl
    s = _PAIR_CONTENT.sub(rev_content, s)
    return s.replace(" ", _SENT)


def _visible_len(unit: str) -> int:
    """الطول المرئي للوحدة (بلا تاقات، مع استعادة المسافات المحميّة)."""
    s = unit.replace(_SENT, " ")
    s = _TAGS.sub("", s)
    return len(s)


def reverse_for_display(text: str, max_line_len: int = 110, strip_img: bool = False) -> str:
    if not text or not text.strip():
        return text
    if strip_img:
        text = _IMG.sub(" ", text)
        text = re.sub(r' {2,}', " ", text)

    out = []
    for para in _BR.split(text):
        if para == "{br}":
            out.append(para)
            continue
        protected = _GROUP.sub(_protect, para)
        units = [u for u in protected.split(" ") if u != ""]
        if not units:
            continue

        if max_line_len and max_line_len > 0:
            # لفّ لأسطر ≤ max_line_len (عرض مرئي)، اعكس كلمات كل سطر، رتّب الأسطر صحيحاً
            lines, cur, cur_len = [], [], 0
            for u in units:
                ul = _visible_len(u)
                if cur and cur_len + 1 + ul > max_line_len:
                    lines.append(cur)
                    cur, cur_len = [], 0
                cur.append(u)
                cur_len += (1 if cur_len else 0) + ul
            if cur:
                lines.append(cur)
            seg = "{br}".join(" ".join(reversed(ln)) for ln in lines)
        else:
            seg = " ".join(reversed(units))
        seg = seg.replace(_SENT, " ")
        # مسافة بعد إغلاق </> لو لاصقته كلمة (ترجمة وضعت كلمة بعد التاق بلا مسافة)
        seg = re.sub(r'(</>)(?=[^\s<])', r'\1 ', seg)
        out.append(seg)
    return "".join(out)


__all__ = ["reverse_for_display"]
