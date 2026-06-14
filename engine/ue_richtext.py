"""
engine/ue_richtext.py — حماية تاقات UE RichText أثناء الترجمة (أقوى من tag_filter العام).

المشكلة: tag_filter العام مبني على تاقات بإغلاق مُسمّى (`<h>…</h>`) ويصنّف `<i>`/`<u>`
كـ inline (بلا حماية). لكن UE RichText يستخدم:
  - إغلاق عام `</>` (بلا اسم)             ← لا يلتقطه الفلتر العام
  - `<i>` `<h>` `<img id="X"/>`            ← `<i>` غير محمي (inline)
  - `{br}` `{0}` `{PlayerName}`            ← قوالب
فيمرّر النص خاماً للمودل الذي يضيف `</i>` أو يعيد ترتيب التاقات → عرض مكسور.

الحل هنا: نحمي **كل** `{…}` و `</>` و `<…>` كتوكن معتم ⟦N⟧، نترجم، ثم نستعيد.
المودل لا يرى التاقات إطلاقاً → لا يقدر يضيف/يحذف/يبدّل صيغتها. الاستعادة بالرقم
تتحمّل إعادة الترتيب (RTL). نتحقّق أن كل توكن موجود مرّة واحدة قبل القبول.
"""
from __future__ import annotations
import re
from typing import List, Optional, Tuple

# يلتقط **تتابعات** التاقات/القوالب المتلاصقة كتوكن واحد (`+`) — يقلّل عدد التوكنات
# بشدّة (UE يجمّع `<img/><h>` و`{br}{br}`) فيسهل على المودل الحفاظ عليها.
# ترتيب البدائل: {…} ثم </> ثم أي <…> (بفراغات اختيارية بينها داخل التتابع).
_RICH_RE = re.compile(r'(?:\{[^{}]*\}|</>|<[^<>]+>)(?:\s*(?:\{[^{}]*\}|</>|<[^<>]+>))*')
_TOK_FIND = re.compile(r'⟦(\d+)⟧')

# تقطيع UE RichText: إغلاق عام </> ، أو تاق <…> ، أو نص
_RT_TOKEN = re.compile(r'</>|<[^<>]+>|[^<]+', re.S)


def sanitize_richtext(text: str) -> str:
    """منظّف حتمي لعرض UE RichText — يصلح مخرجات المودل المعطوبة بلا إعادة ترجمة:

    1. **يحذف `</>` اليتيمة** (إغلاق بلا فتح مطابق) — المودل أحياناً يُسقط وسم الفتح
       `<r>`/`<h>` ويُبقي إغلاقه `</>` فيظهر حرفياً في اللعبة.
    2. **يغلق الوسوم المفتوحة المتبقّية** في النهاية (تجنّب تنسيق يتسرّب لبقية النص).
    3. **يضيف مسافة** بعد `</>` أو `<…/>` (img) إن لصقتها كلمة (المودل يلصق بلا مسافة).

    آمن: `<img id="X"/>` ذاتي الإغلاق لا يغيّر العمق. النص بلا `<` يُعاد كما هو."""
    if not text or "<" not in text:
        return text
    res: List[str] = []
    depth = 0
    for m in _RT_TOKEN.finditer(text):
        t = m.group(0)
        if t == "</>":
            if depth > 0:
                depth -= 1
                res.append(t)
            # وإلا: إغلاق يتيم → احذفه
        elif t.startswith("<"):
            if t.endswith("/>"):
                res.append(t)            # ذاتي الإغلاق (img) — العمق لا يتغيّر
            else:
                depth += 1
                res.append(t)            # فتح
        else:
            res.append(t)                # نص
    if depth > 0:                        # أغلق ما تبقّى مفتوحاً
        res.append("</>" * depth)
    s = "".join(res)
    # مسافة بعد </> أو /> إن لصقتها كلمة — لكن ليس قبل علامة ترقيم أو وسم
    s = re.sub(r'(</>|/>)(?=[^\s<.,!?:;)\]}،؛؟])', r'\1 ', s)
    return s


def protect(text: str) -> Tuple[str, List[str]]:
    """يستبدل كل تاق/قالب بتوكن ⟦N⟧ ويُرجع (النص_المحمي، قائمة_التاقات)."""
    toks: List[str] = []

    def repl(m: re.Match) -> str:
        toks.append(m.group(0))
        return f"⟦{len(toks) - 1}⟧"

    return _RICH_RE.sub(repl, text), toks


def restore(text: str, toks: List[str]) -> str:
    def repl(m: re.Match) -> str:
        i = int(m.group(1))
        return toks[i] if 0 <= i < len(toks) else m.group(0)

    return _TOK_FIND.sub(repl, text)


def tags_of(text: str) -> List[str]:
    """قائمة التاقات/القوالب في النص (للمقارنة)."""
    return _RICH_RE.findall(text or "")


def is_valid(out: str, toks: List[str]) -> bool:
    """كل توكن ⟦i⟧ موجود مرّة واحدة بالضبط (لا حذف/تكرار)."""
    found = [int(x) for x in _TOK_FIND.findall(out or "")]
    return sorted(found) == list(range(len(toks)))


def tags_match(original: str, translated: str) -> bool:
    """نفس مجموعة التاقات (بصرف النظر عن الترتيب — RTL يعيد الترتيب)."""
    return sorted(tags_of(original)) == sorted(tags_of(translated))


def _active_ollama(engine):
    """يُرجع OllamaTranslator النشط (لتحجيم num_predict ديناميكياً) أو None."""
    try:
        key = engine.get_active_model()
        tr = engine.get_translator(key)
        return tr if hasattr(tr, "_opts") else None
    except Exception:
        return None


def translate(text: str, engine, enforce_punct=True, retries: int = 2) -> Optional[str]:
    """يترجم نصّاً مع حماية تاقات UE الكاملة. يُرجع الترجمة أو None لو فشلت الحماية.
    يُعيد المحاولة حتى `retries` مرّات لو أفسد المودل التوكنات (truncation عابر).
    يرفع num_predict/num_ctx ديناميكياً للنصوص الطويلة (تمنع قصّ التوكنات الأخيرة)."""
    cleaned, toks = protect(text)
    if not toks:
        result = engine.translate(text)
    else:
        # نحفظ خيارات Ollama لاستعادتها (نعدّل num_predict/num_ctx/temperature)
        tr = _active_ollama(engine)
        saved = dict(tr._opts) if tr is not None else None
        if tr is not None and (len(text) > 220 or len(toks) > 8):
            need_pred = min(2048, max(256, int(len(cleaned) * 1.3) + len(toks) * 6))
            need_ctx = min(8192, max(int(tr._opts.get("num_ctx", 512)),
                                     int(len(cleaned) * 1.2) + need_pred + 256))
            tr._opts["num_predict"] = need_pred
            tr._opts["num_ctx"] = need_ctx
        try:
            result = None
            # المحاولة الأولى temp=config؛ المحاولات التالية بحرارة متصاعدة كي
            # تختلف المخرجات (temp=0 يجعل الـ retry حتمياً = بلا فائدة).
            base_temp = None
            if tr is not None:
                base_temp = tr._opts.get("temperature", 0.0)
            temps = [base_temp if base_temp else 0.0, 0.4, 0.8]
            for attempt in range(max(1, retries + 1)):
                if tr is not None and attempt < len(temps):
                    tr._opts["temperature"] = temps[attempt]
                out = engine.translate(cleaned)
                if out and is_valid(out, toks):
                    result = restore(out, toks)
                    break
        finally:
            if saved is not None:
                tr._opts.clear(); tr._opts.update(saved)
        if result is None:
            return None   # المودل أفسد التوكنات في كل المحاولات → لا تحفظ مكسوراً
    if result and enforce_punct:
        try:
            from engine.models.base import enforce_trailing_punctuation
            result = enforce_trailing_punctuation(text, result)
        except Exception:
            pass
    return result


__all__ = ["protect", "restore", "tags_of", "is_valid", "tags_match", "translate"]
