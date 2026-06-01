"""
engine/tag_health.py — يكشف الترجمات المعطوبة (تاقات مكسورة).

يُستخدَم عند:
  • تصدير translations.txt (BepInEx) أو مجلد Translate (Unreal Hook)
  • فحص الكاش يدوياً (tools/clean_broken_tag_translations.py)

نمط الـ bug:
  - الأصل فيه <name attrs/> (selfclosing مع attrs)
  - الترجمة فيها تاق مكسور: عدد ناقص أو attrs تطفو بلا wrapper
"""
from __future__ import annotations
import re

# نمط selfclosing مع attrs: <name ... attrs/>
_RX_SELFCLOSE_FULL = re.compile(
    r'<([a-zA-Z][a-zA-Z0-9_]*)\s+([^<>]*?)/\s*>'
)


def is_broken_translation(original: str, translated: str) -> bool:
    """True لو الأصل فيه selfclosing tag والترجمة لا تحفظه بشكل كامل.

    نتجاهل:
      - تاقات بدون attrs (مثل <br>, <hr>) — لا تُكسَر عادة
      - paired tags بلا selfclosing — المودل قد يحذفها عمداً (مثل <noparse>)
    """
    if not original or not translated:
        return False
    orig_tags = _RX_SELFCLOSE_FULL.findall(original)
    if not orig_tags:
        return False

    for name, attrs in orig_tags:
        # 1) نفس عدد التاقات في الترجمة بنفس الـ name
        rx = re.compile(r'<' + re.escape(name) + r'\s+[^<>]*?/\s*>')
        orig_count = len(re.findall(rx, original))
        trans_count = len(rx.findall(translated))
        if trans_count != orig_count:
            return True

        # 2) لو attrs فيها "|VALUE|" (مثل id=|SoldierBee|)، تحقّق إنها مُغلَّفة
        if attrs and "|" in attrs:
            m = re.search(r'\|([^|<>]+)\|', attrs)
            if m:
                fingerprint = m.group(0)   # |SoldierBee|
                if fingerprint in translated:
                    pos = translated.find(fingerprint)
                    prefix = translated[max(0, pos - 60):pos]
                    if f"<{name}" not in prefix:
                        return True
    return False


__all__ = ["is_broken_translation"]
