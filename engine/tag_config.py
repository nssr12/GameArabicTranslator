"""
engine/tag_config.py — إدارة قائمة التاقات المحمية لـ Tiered/Bulletproof.

يُخزّن في data/tag_config.json:
  inline_tags:      تاقات تبقى inline (مزدوجة بدون سمات) → b, i, u …
  selfclosing_tags: تاقات تُحمى بـ ⟦sN⟧                  → sprite, br, hr …

الـ paired tags المعقدة (مع سمات مثل <color=red>) تُحمى تلقائياً بـ ⟦N⟧/⟦/N⟧
ولا تحتاج إضافة هنا.
"""
from __future__ import annotations
import json
import os
from typing import TypedDict


CONFIG_PATH = "data/tag_config.json"

DEFAULT_INLINE_TAGS: list[str] = [
    "b", "i", "u", "em", "strong", "s", "mark", "noparse",
]

DEFAULT_SELFCLOSE_TAGS: list[str] = [
    "sprite", "br", "hr", "img", "page", "nobr",
]


class TagConfig(TypedDict):
    inline_tags: list[str]
    selfclosing_tags: list[str]


def _normalize_tag(name: str) -> str:
    """ينظّف اسم التاق: lowercase + بدون < > /"""
    name = name.strip().lower()
    for ch in "<>/":
        name = name.replace(ch, "")
    return name.strip()


def load_config(path: str = CONFIG_PATH) -> TagConfig:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    inline = data.get("inline_tags") or list(DEFAULT_INLINE_TAGS)
    selfclose = data.get("selfclosing_tags") or list(DEFAULT_SELFCLOSE_TAGS)
    return {
        "inline_tags": _dedup_clean(inline),
        "selfclosing_tags": _dedup_clean(selfclose),
    }


def save_config(cfg: TagConfig, path: str = CONFIG_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    clean: TagConfig = {
        "inline_tags": _dedup_clean(cfg.get("inline_tags") or []),
        "selfclosing_tags": _dedup_clean(cfg.get("selfclosing_tags") or []),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)


def reset_to_defaults(path: str = CONFIG_PATH) -> TagConfig:
    cfg: TagConfig = {
        "inline_tags": list(DEFAULT_INLINE_TAGS),
        "selfclosing_tags": list(DEFAULT_SELFCLOSE_TAGS),
    }
    save_config(cfg, path)
    return cfg


def _dedup_clean(tags: list[str]) -> list[str]:
    """ينظّف القائمة من التكرار والمحارف غير المرغوبة."""
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        n = _normalize_tag(str(t))
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


__all__ = [
    "TagConfig",
    "load_config",
    "save_config",
    "reset_to_defaults",
    "DEFAULT_INLINE_TAGS",
    "DEFAULT_SELFCLOSE_TAGS",
    "CONFIG_PATH",
]
