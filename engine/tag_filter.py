"""
engine/tag_filter.py — Tiered tag stripping for translation context preservation.

الاستراتيجية المتدرّجة:
  1. تاقات بسيطة (b, i, u) → تبقى inline (المودل يفهمها كـ Markdown).
  2. تاقات معقدة بصرية (color, size, font) → تُستبدل بـ [t0]...[/t0]
  3. تاقات مستقلة (sprite, br) → تُستبدل بـ [s0]

السبب:
  - التاقات المعقدة كـ <color=#FF0000> ترفضها النماذج الصغيرة أو تترجم سماتها
  - PUA chars (U+E000) قد تحذفها بعض النماذج
  - Bracket markers [tN] أحرف ASCII عادية يصعب على المودل تحريفها
  - السياق محفوظ: النص داخل التاقات يبقى قابلاً للترجمة
"""
from __future__ import annotations
import re
from typing import Optional


# ── أنماط التعرّف على التاقات ─────────────────────────────────────────────
# تاقات مزدوجة <tag>...</tag> مع سمات اختيارية.
# ملاحظة: TMP يستخدم صيغة "<color=red>" بدون مسافة، فالسمات قد تبدأ بـ "=" مباشرة
_PAIRED_TAG_RE = re.compile(
    r'<(?P<name>[a-zA-Z][a-zA-Z0-9_-]*)'      # اسم التاق
    r'(?P<attrs>[^>]*)'                          # سمات (أي شيء حتى >)
    r'>'                                         # إغلاق التاق المفتوح
    r'(?P<inner>.*?)'                            # محتوى داخلي (non-greedy)
    r'</(?P=name)\s*>',                          # إغلاق
    re.DOTALL
)

# تاقات مستقلة self-closing: <br>, <br/>, <sprite ...>, <hr>
_SELFCLOSE_RE = re.compile(
    r'<(?P<name>sprite|br|hr|img|page|nobr)'
    r'(?P<attrs>[^>/]*?)'
    r'\s*/?>',
    re.IGNORECASE
)

# تاقات بسيطة تبقى inline (لا تحتاج سمات معقدة)
_INLINE_TAGS = frozenset({'b', 'i', 'u', 'em', 'strong', 's', 'mark', 'noparse'})


class TieredTagFilter:
    """
    يجرّد التاقات المعقدة فقط من النص قبل الترجمة، ويُعيدها بعدها.

    الاستخدام:
        flt = TieredTagFilter()
        cleaned, tokens = flt.strip(text)
        translated = engine.translate(cleaned)
        result = flt.restore(translated, tokens)
        if result is None:
            # علامات التاقات تلفت في رد المودل — أعد المحاولة بدون تجريد
            ...
    """

    def __init__(self, inline_tags: frozenset = _INLINE_TAGS):
        self.inline_tags = inline_tags

    # ── Public API ────────────────────────────────────────────────────────

    def strip(self, text: str) -> tuple[str, list]:
        """يُرجع (نص_نظيف، قائمة_التاقات). الترتيب مهم للاستعادة."""
        if not text or '<' not in text:
            return text, []

        tokens: list = []
        result = text

        # المرحلة 1: التاقات المزدوجة — كل تمريرة تعالج جميع التاقات غير المتداخلة
        # نُكرّر للتعامل مع المتشعّب: <a><b>X</b></a> يحتاج تمريرتين
        for _ in range(12):  # حد أمان ضد الحلقات اللانهائية
            new_result = _PAIRED_TAG_RE.sub(
                lambda m: self._handle_paired(m, tokens),
                result,
            )
            if new_result == result:
                break
            result = new_result

        # المرحلة 2: التاقات المستقلة (لا تتداخل بطبيعتها)
        result = _SELFCLOSE_RE.sub(
            lambda m: self._handle_selfclose(m, tokens),
            result,
        )

        return result, tokens

    def restore(self, translated: str, tokens: list) -> Optional[str]:
        """يُعيد التاقات الأصلية. يُرجع None إذا فُقد marker أساسي."""
        if not tokens:
            return translated
        if translated is None:
            return None

        # تحقّق من سلامة كل markers قبل الاستعادة
        for idx, (kind, name, attrs, _inner) in enumerate(tokens):
            if kind == "paired":
                if f"[t{idx}]" not in translated or f"[/t{idx}]" not in translated:
                    return None  # تاق مفقود → نُعيد None كإشارة فشل
            elif kind == "self":
                if f"[s{idx}]" not in translated:
                    return None

        # استعد بالترتيب — نبدأ بالأعلى رقماً لتجنّب prefix collisions
        # (مثلاً: [t1] قد يُطابق داخل [t10] لو بدأنا من الأصغر)
        for idx in range(len(tokens) - 1, -1, -1):
            kind, name, attrs, _inner = tokens[idx]
            if kind == "paired":
                opener = f"<{name}{attrs}>"
                closer = f"</{name}>"
                translated = translated.replace(f"[t{idx}]", opener)
                translated = translated.replace(f"[/t{idx}]", closer)
            elif kind == "self":
                # نخرج التاق بدون / لأن TMP يقبل الصيغتين والأشيع هو بدون /
                fulltag = f"<{name}{attrs}>"
                translated = translated.replace(f"[s{idx}]", fulltag)

        return translated

    # ── Internal ──────────────────────────────────────────────────────────

    def _handle_paired(self, m: re.Match, tokens: list) -> str:
        name = m.group("name").lower()
        attrs = m.group("attrs") or ""
        inner = m.group("inner") or ""

        # تاق بسيط بلا سمات → اتركه inline
        if name in self.inline_tags and not attrs.strip():
            return m.group(0)

        idx = len(tokens)
        tokens.append(("paired", m.group("name"), attrs, None))
        return f"[t{idx}]{inner}[/t{idx}]"

    def _handle_selfclose(self, m: re.Match, tokens: list) -> str:
        idx = len(tokens)
        tokens.append(("self", m.group("name"), m.group("attrs") or "", None))
        return f"[s{idx}]"


__all__ = ["TieredTagFilter", "BulletproofTagFilter"]


# ═════════════════════════════════════════════════════════════════════════════
# BulletproofTagFilter — علامات Unicode رياضية ⟦1⟧/⟦/1⟧ مع التحقق الصارم
# ═════════════════════════════════════════════════════════════════════════════

# U+27E6 ⟦ MATHEMATICAL LEFT WHITE SQUARE BRACKET
# U+27E7 ⟧ MATHEMATICAL RIGHT WHITE SQUARE BRACKET
# هذه الأقواس:
#   - نادرة جداً في النص العادي (لا تتداخل مع محتوى المستخدم)
#   - مرئية (تشخيص أسهل عند الفشل)
#   - ليست HTML/XML → النموذج لن يحاول إصلاحها
#   - شائعة في تدريب LLM (LaTeX, math notation)
_BP_OPEN  = "⟦"   # ⟦
_BP_CLOSE = "⟧"   # ⟧


class BulletproofTagFilter:
    """
    نسخة محسّنة من TieredTagFilter باستخدام علامات Unicode رياضية.

    الميزات الإضافية:
      - علامات ⟦N⟧ بدل [tN] (أعلى احتمال للحفاظ من النموذج)
      - تمييز بين paired (⟦N⟧...⟦/N⟧) و self-closing (⟦*N⟧)
      - متوافق مع TagValidator للفحص الصارم
    """

    def __init__(self, inline_tags: frozenset = _INLINE_TAGS):
        self.inline_tags = inline_tags

    def strip(self, text: str) -> tuple[str, list]:
        if not text or '<' not in text:
            return text, []

        tokens: list = []
        result = text

        # paired tags (تكرار للمتشعّب)
        for _ in range(12):
            new_result = _PAIRED_TAG_RE.sub(
                lambda m: self._handle_paired(m, tokens),
                result,
            )
            if new_result == result:
                break
            result = new_result

        # self-closing
        result = _SELFCLOSE_RE.sub(
            lambda m: self._handle_selfclose(m, tokens),
            result,
        )

        return result, tokens

    def restore(self, translated: str, tokens: list) -> Optional[str]:
        """يستعيد التاقات. يُرجع None إذا فُقد marker (التحقق أصرم)."""
        if not tokens:
            return translated
        if translated is None:
            return None

        # تحقق دقيق: كل marker موجود مرة واحدة بالضبط
        for idx, (kind, name, attrs, _inner) in enumerate(tokens):
            if kind == "paired":
                op = f"{_BP_OPEN}{idx}{_BP_CLOSE}"
                cl = f"{_BP_OPEN}/{idx}{_BP_CLOSE}"
                if translated.count(op) != 1 or translated.count(cl) != 1:
                    return None
            elif kind == "self":
                mk = f"{_BP_OPEN}s{idx}{_BP_CLOSE}"
                if translated.count(mk) != 1:
                    return None

        # تحقق ترتيب: ⟦/N⟧ يأتي بعد ⟦N⟧ لكل paired
        for idx, (kind, _name, _attrs, _inner) in enumerate(tokens):
            if kind == "paired":
                op = f"{_BP_OPEN}{idx}{_BP_CLOSE}"
                cl = f"{_BP_OPEN}/{idx}{_BP_CLOSE}"
                if translated.index(op) >= translated.index(cl):
                    return None

        # استعد بترتيب عكسي لتجنّب prefix collisions
        for idx in range(len(tokens) - 1, -1, -1):
            kind, name, attrs, _inner = tokens[idx]
            if kind == "paired":
                opener = f"<{name}{attrs}>"
                closer = f"</{name}>"
                translated = translated.replace(f"{_BP_OPEN}{idx}{_BP_CLOSE}", opener)
                translated = translated.replace(f"{_BP_OPEN}/{idx}{_BP_CLOSE}", closer)
            elif kind == "self":
                fulltag = f"<{name}{attrs}>"
                translated = translated.replace(f"{_BP_OPEN}s{idx}{_BP_CLOSE}", fulltag)

        return translated

    def _handle_paired(self, m: re.Match, tokens: list) -> str:
        name = m.group("name").lower()
        attrs = m.group("attrs") or ""
        inner = m.group("inner") or ""
        if name in self.inline_tags and not attrs.strip():
            return m.group(0)
        idx = len(tokens)
        tokens.append(("paired", m.group("name"), attrs, None))
        return f"{_BP_OPEN}{idx}{_BP_CLOSE}{inner}{_BP_OPEN}/{idx}{_BP_CLOSE}"

    def _handle_selfclose(self, m: re.Match, tokens: list) -> str:
        # نستخدم ⟦sN⟧ بدل ⟦*N⟧ — الـ * كان يُفسَّر كـ markdown emphasis ويُحذف
        idx = len(tokens)
        tokens.append(("self", m.group("name"), m.group("attrs") or "", None))
        return f"{_BP_OPEN}s{idx}{_BP_CLOSE}"
