"""
engine/tag_discovery.py — اكتشاف XML/HTML tags من النصوص.

يستخرج أسماء التاقات من نصوص اللعبة لإضافتها إلى tag_config.json (Tag Protection).

يميّز بين:
  - selfclosing: <name .../>  أو  <name>  بدون nesting صحيح
  - paired:     <name>...</name>  مع محتوى داخلي

الاستخدام:
    from engine.tag_discovery import discover_tags
    results = discover_tags(["<itemName id=|PalEgg|/>", "<b>bold</b>"])
    # → [TagInfo(name="itemName", kind="selfclosing", count=1, example=...), ...]
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Iterable


# تاقات تنسيق Unity/TMP المعروفة لتُقترح كـ inline افتراضياً
_KNOWN_INLINE = {
    "b", "i", "u", "em", "strong", "s", "mark", "noparse",
    "sub", "sup", "smallcaps", "uppercase", "lowercase",
}

# تاقات Unity/TMP المعروفة لتُقترح كـ selfclosing افتراضياً
_KNOWN_SELFCLOSE = {
    "br", "hr", "img", "page", "nobr", "sprite",
}

# نمط self-closing صريح: <name ... />
_RX_SELFCLOSE = re.compile(
    r'<\s*([a-zA-Z][a-zA-Z0-9_:-]*)\b([^<>]*?)/\s*>'
)

# نمط paired كامل: <name ...>...</name>
_RX_PAIRED = re.compile(
    r'<\s*([a-zA-Z][a-zA-Z0-9_:-]*)\b([^<>]*?)>(.*?)</\s*\1\s*>',
    re.DOTALL,
)

# نمط open tag عام (لاكتشاف التاقات التي لا تظهر كزوج)
_RX_OPEN = re.compile(
    r'<\s*([a-zA-Z][a-zA-Z0-9_:-]*)\b([^<>]*?)>'
)

# نمط close tag
_RX_CLOSE = re.compile(
    r'</\s*([a-zA-Z][a-zA-Z0-9_:-]*)\s*>'
)


@dataclass
class TagInfo:
    name: str                            # اسم التاق (lowercase)
    kind: str                            # "selfclosing" | "paired"
    count: int = 0                       # عدد المرات التي ظهر فيها
    example: str = ""                    # أوّل مثال من النصوص الأصلية
    suggested_kind: str = ""             # افتراض ذكي: "selfclosing" | "inline"
    sources: list[str] = field(default_factory=list)   # أوّل 3 نصوص فيها التاق

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "count": self.count,
            "example": self.example,
            "suggested_kind": self.suggested_kind,
            "sources": list(self.sources),
        }


def _norm(name: str) -> str:
    return name.strip().lower()


def _suggest_kind(name: str, found_kinds: set[str]) -> str:
    """
    يقترح أين تضيف التاق:
      - "inline"      → inline_tags  (مزدوج بسيط بدون سمات: <b>...</b>)
      - "selfclosing" → selfclosing_tags  (self-closing أو محمي بـ ⟦sN⟧)
    """
    n = _norm(name)
    if n in _KNOWN_INLINE:
        return "inline"
    if n in _KNOWN_SELFCLOSE:
        return "selfclosing"
    # paired فقط بدون selfclosing → غالباً inline (لكن مع سمات يبقى محمي تلقائياً)
    if "paired" in found_kinds and "selfclosing" not in found_kinds:
        return "inline"
    # selfclosing أو مختلط → selfclosing
    return "selfclosing"


def discover_tags(texts: Iterable[str]) -> list[TagInfo]:
    """
    يستخرج كل التاقات الفريدة من قائمة نصوص.

    Args:
        texts: نصوص إنجليزية أصلية (قبل الترجمة).

    Returns:
        قائمة TagInfo مرتّبة حسب count (تنازلياً).
    """
    info: dict[str, TagInfo] = {}            # name → TagInfo
    found_kinds: dict[str, set[str]] = {}    # name → {kinds seen}

    for text in texts:
        if not text or "<" not in text:
            continue
        # نتتبّع التاقات التي وُجدت في هذا النص لإضافة مصدر واحد فقط لكل (تاق, نص)
        per_text_names: set[str] = set()

        # 1) self-closing صريح
        for m in _RX_SELFCLOSE.finditer(text):
            name = _norm(m.group(1))
            if not name:
                continue
            kinds = found_kinds.setdefault(name, set())
            kinds.add("selfclosing")
            ti = info.setdefault(name, TagInfo(
                name=name, kind="selfclosing",
                example=m.group(0),
            ))
            ti.count += 1
            if name not in per_text_names:
                per_text_names.add(name)
                if len(ti.sources) < 3 and text not in ti.sources:
                    ti.sources.append(text)

        # 2) paired كامل
        for m in _RX_PAIRED.finditer(text):
            name = _norm(m.group(1))
            if not name:
                continue
            kinds = found_kinds.setdefault(name, set())
            kinds.add("paired")
            ti = info.setdefault(name, TagInfo(
                name=name, kind="paired",
                example=m.group(0)[:80],
            ))
            ti.count += 1
            if name not in per_text_names:
                per_text_names.add(name)
                if len(ti.sources) < 3 and text not in ti.sources:
                    ti.sources.append(text)

        # 3) open tag بدون close مطابق ولا "/>" → نعتبره selfclosing-ضمني
        # (مثل <br> أو <sprite=X> في بعض الصيغ)
        # نبحث عن أي open غير مغلق بعدُ في هذا النص
        opens = [(m.group(1).lower(), m.start(), m.group(0))
                 for m in _RX_OPEN.finditer(text)
                 if not m.group(0).rstrip().endswith("/>")]
        closes = {m.group(1).lower() for m in _RX_CLOSE.finditer(text)}
        for name, _pos, raw in opens:
            n = _norm(name)
            if not n or n in closes:
                continue   # paired يُغطّى أعلاه
            # تاق مفتوح بلا إغلاق ولا "/" → selfclosing-ضمني
            kinds = found_kinds.setdefault(n, set())
            kinds.add("selfclosing")
            ti = info.setdefault(n, TagInfo(
                name=n, kind="selfclosing",
                example=raw,
            ))
            ti.count += 1
            if n not in per_text_names:
                per_text_names.add(n)
                if len(ti.sources) < 3 and text not in ti.sources:
                    ti.sources.append(text)

    # حدّد suggested_kind بناءً على كل ما رأيناه
    for name, ti in info.items():
        ti.suggested_kind = _suggest_kind(name, found_kinds.get(name, set()))

    # ترتيب: count تنازلياً، ثم الاسم
    return sorted(info.values(), key=lambda t: (-t.count, t.name))


__all__ = ["TagInfo", "discover_tags"]
