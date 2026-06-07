"""
engine/wrap_overrides.py — لفّ أسطر مخصّص لكل نص (يطغى على القيمة العامة).

بعض النصوص في صناديق ضيّقة تحتاج عدد أحرف أقل من العام. هنا نخزّن override لكل
نص إنجليزي (المفتاح) → عدد أحرف اللفّ. عند تطبيق الترجمة (foundation_mod /
أي مسار RTL دفعي)، لو للنص override نستخدمه بدل القيمة العامة.

التخزين: data/cache/<game>.wrap.json  =  { "english text": wrap_int, ... }
القيمة 0 (أو الحذف) تعني: استخدم العام.
"""
from __future__ import annotations
import json
import os

_DIR = os.path.join("data", "cache")


def _path(game: str) -> str:
    safe = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in game).strip()
    return os.path.join(_DIR, f"{safe}.wrap.json")


def load(game: str) -> dict:
    try:
        with open(_path(game), "r", encoding="utf-8") as f:
            d = json.load(f)
        return {k: int(v) for k, v in d.items() if int(v) > 0}
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {}


def get(game: str, text: str, default: int = 0) -> int:
    return int(load(game).get(text, default))


def set_override(game: str, text: str, wrap: int) -> None:
    """wrap>0 → يحفظ override؛ wrap≤0 → يحذفه (استخدام العام)."""
    d = load(game)
    if wrap and int(wrap) > 0:
        d[text] = int(wrap)
    else:
        d.pop(text, None)
    os.makedirs(_DIR, exist_ok=True)
    with open(_path(game), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent="\t")


def count(game: str) -> int:
    return len(load(game))


__all__ = ["load", "get", "set_override", "count"]
