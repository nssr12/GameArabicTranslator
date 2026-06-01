"""
engine/filtered_translator.py — يُغلّف TranslationEngine بـ tag filter + cascade.

استخدامه:
    ft = FilteredTranslator(engine, tag_mode="bulletproof")
    result = ft.translate(text)              # str | None
    result, mode = ft.translate_with_info(text)  # ("...عربي...", "bulletproof")

يستخدمه:
  - engine/proxy_server.py: عند الترجمة الفورية للعبة
  - gui/qt/pages/cache.py:  زر "إعادة ترجمة" — حتى يُطبَّق نفس cascade
  - أي مكان آخر يريد ترجمة محمية من كسر التاقات

الإعدادات تُقرأ من config.json (الـ top-level field "tag_mode").
"""
from __future__ import annotations
import json
import os
import re
from typing import Optional

from .tag_filter import TieredTagFilter, BulletproofTagFilter
from .tag_validator import validate_bulletproof_markers, summarize_issues


CONFIG_PATH = "config.json"
VALID_MODES = ("inline", "strip", "tiered", "bulletproof")
DEFAULT_MODE = "bulletproof"

_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^<>]{0,120}>")


# ── إعداد عام (config.json) ─────────────────────────────────────────────────

def get_global_tag_mode(default: str = DEFAULT_MODE) -> str:
    """يقرأ tag_mode من config.json. الافتراضي 'bulletproof'."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            mode = json.load(f).get("tag_mode")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default
    return mode if mode in VALID_MODES else default


def set_global_tag_mode(mode: str) -> None:
    """يحفظ tag_mode في config.json. يحتفظ بكل الحقول الأخرى."""
    if mode not in VALID_MODES:
        raise ValueError(f"invalid tag_mode {mode!r} (expected one of {VALID_MODES})")
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        cfg = {}
    cfg["tag_mode"] = mode
    os.makedirs(os.path.dirname(CONFIG_PATH) or ".", exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ── الـ Wrapper الرئيسي ─────────────────────────────────────────────────────

class FilteredTranslator:
    """ترجمة محمية بـ tag filter + cascade fallback (نفس منطق البروكسي)."""

    def __init__(
        self,
        engine,
        tag_mode: Optional[str] = None,
        log_callback=None,
    ):
        self._engine = engine
        self._tag_mode = (tag_mode or get_global_tag_mode())
        if self._tag_mode not in VALID_MODES:
            self._tag_mode = DEFAULT_MODE
        self.log = log_callback
        self._bulletproof = BulletproofTagFilter()
        self._tiered = TieredTagFilter()

    # ── API ──────────────────────────────────────────────────────────────

    @property
    def tag_mode(self) -> str:
        return self._tag_mode

    def set_tag_mode(self, mode: str) -> None:
        if mode in VALID_MODES:
            self._tag_mode = mode

    def reload_filters(self) -> None:
        """يُعيد بناء الـ filters بعد تغيير tag_config.json."""
        self._bulletproof = BulletproofTagFilter()
        self._tiered = TieredTagFilter()

    def translate(self, text: str) -> Optional[str]:
        """يُرجع الترجمة أو None لو فشلت كل المحاولات."""
        result, _info = self.translate_with_info(text)
        return result

    def translate_with_info(self, text: str) -> tuple[Optional[str], str]:
        """يُرجع (translated, succeeded_mode) أو (None, modes_tried_csv)."""
        if not text:
            return text, "empty"
        if self._tag_mode == "bulletproof":
            return self._cascade(text)
        if self._tag_mode == "tiered":
            r = self._tiered_only(text)
            return r, "tiered" if r else "tiered"
        if self._tag_mode == "strip":
            r = self._strip_only(text)
            return r, "strip" if r else "strip"
        # inline → ترجمة مباشرة بدون filter
        r = self._engine.translate(text)
        return r, "inline" if r else "inline"

    # ── Cascade (لـ bulletproof mode) ────────────────────────────────────

    def _cascade(self, text: str) -> tuple[Optional[str], str]:
        modes_tried: list = []

        # محاولة 1: bulletproof (⟦N⟧)
        cleaned, tokens = self._bulletproof.strip(text)
        if tokens:
            modes_tried.append("bulletproof")
            response = self._engine.translate(cleaned)
            if response:
                val = validate_bulletproof_markers(response, tokens)
                if val.valid:
                    restored = self._bulletproof.restore(response, tokens)
                    if restored is not None:
                        return restored, "bulletproof"
                if self.log:
                    try:
                        self.log(f"⚠ bulletproof فشل: {summarize_issues(val)}")
                    except Exception:
                        pass
        else:
            # لا تاقات معقدة → ترجمة عادية
            response = self._engine.translate(text)
            if response:
                return response, "bulletproof"

        # محاولة 2: tiered ([tN] / [sN])
        modes_tried.append("tiered")
        cleaned2, tokens2 = self._tiered.strip(text)
        if tokens2:
            response = self._engine.translate(cleaned2)
            if response:
                restored = self._tiered.restore(response, tokens2)
                if restored is not None:
                    return restored, "tiered"

        # محاولة 3: strip (PUA chars)
        modes_tried.append("strip")
        response = self._strip_only(text)
        if response:
            return response, "strip"

        return None, ",".join(modes_tried)

    # ── tiered منفرد ─────────────────────────────────────────────────────

    def _tiered_only(self, text: str) -> Optional[str]:
        cleaned, tokens = self._tiered.strip(text)
        if not tokens:
            return self._engine.translate(text)
        response = self._engine.translate(cleaned)
        if not response:
            return None
        return self._tiered.restore(response, tokens)

    # ── strip منفرد (PUA chars) ──────────────────────────────────────────

    def _strip_only(self, text: str) -> Optional[str]:
        tags: list = []

        def replace(m):
            ph = chr(0xE000 + len(tags))
            tags.append(m.group(0))
            return ph

        cleaned = _HTML_TAG_RE.sub(replace, text)
        if not tags:
            return self._engine.translate(text)
        translated = self._engine.translate(cleaned)
        if not translated:
            return None
        for idx, tag in enumerate(tags):
            translated = translated.replace(chr(0xE000 + idx), tag)
        return translated


__all__ = [
    "FilteredTranslator",
    "get_global_tag_mode",
    "set_global_tag_mode",
    "VALID_MODES",
    "DEFAULT_MODE",
]
