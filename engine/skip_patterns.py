"""
engine/skip_patterns.py — قائمة الأنماط الممنوعة من الإرسال للمحرّك.

النصوص المطابقة لأي نمط هنا:
  • لا تُرسل لـ Ollama (توفير موارد)
  • تُعاد كما هي (يصنّفها البروكسي "بدون تغيير")
  • لا تُحسب فشلاً

أنماط wildcard بسيطة (fnmatch): * يطابق أي شيء، ? يطابق حرفاً واحداً.
الأنماط حساسة لحالة الأحرف لتجنّب مطابقات مفاجئة.

يُخزَّن في data/skip_patterns.json:
{
  "patterns": ["Nexa *", "* SDF", ...]
}
"""
from __future__ import annotations

import json
import os
import threading
from fnmatch import fnmatchcase
from typing import Iterable

CONFIG_PATH = "data/skip_patterns.json"

# أنماط افتراضية تستهدف أسماء الخطوط في Unity/TMP التي لا تُترجَم
DEFAULT_PATTERNS: list[str] = [
    "Nexa *",
    "Nexa-*",
    "Nexa*",
    "* SDF",
    "*SDF",
    "* Bold",
    "* Italic",
    "* Regular",
    "* Heavy",
    "* Black",
    "* Light",
    "* Medium",
]

_lock = threading.RLock()
_cache: list[str] | None = None


def _normalize(p: str) -> str:
    return (p or "").strip()


def _dedup_clean(patterns: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in patterns:
        n = _normalize(str(p))
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def load_patterns(path: str = CONFIG_PATH) -> list[str]:
    """يقرأ القائمة من القرص. لا يستخدم الكاش."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("patterns")
        if raw is None:
            return list(DEFAULT_PATTERNS)
        return _dedup_clean(raw)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return list(DEFAULT_PATTERNS)


def save_patterns(patterns: Iterable[str], path: str = CONFIG_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    clean = _dedup_clean(patterns)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"patterns": clean}, f, ensure_ascii=False, indent=2)
    reload()


def reset_to_defaults(path: str = CONFIG_PATH) -> list[str]:
    save_patterns(DEFAULT_PATTERNS, path)
    return list(DEFAULT_PATTERNS)


def get_patterns() -> list[str]:
    """يُرجع نسخة من القائمة المحمّلة في الذاكرة (تحميل كسول)."""
    global _cache
    with _lock:
        if _cache is None:
            _cache = load_patterns()
        return list(_cache)


def reload() -> list[str]:
    """يعيد القراءة من القرص ويحدّث الكاش."""
    global _cache
    with _lock:
        _cache = load_patterns()
        return list(_cache)


def add_pattern(pattern: str) -> bool:
    """يضيف نمطاً جديداً. يُرجع True إذا أُضيف فعلاً."""
    p = _normalize(pattern)
    if not p:
        return False
    with _lock:
        current = get_patterns()
        if p in current:
            return False
        current.append(p)
        save_patterns(current)
        return True


def remove_pattern(pattern: str) -> bool:
    """يزيل نمطاً. يُرجع True إذا أُزيل فعلاً."""
    p = _normalize(pattern)
    if not p:
        return False
    with _lock:
        current = get_patterns()
        if p not in current:
            return False
        current = [x for x in current if x != p]
        save_patterns(current)
        return True


def matches(text: str, patterns: list[str] | None = None) -> str | None:
    """
    يفحص إن كان النص يطابق أي نمط من قائمة المنع.
    يُرجع النمط المُطابق (للتسجيل) أو None.
    """
    if not text:
        return None
    pats = patterns if patterns is not None else get_patterns()
    if not pats:
        return None
    for p in pats:
        try:
            if fnmatchcase(text, p):
                return p
        except Exception:
            continue
    return None


def count_matching(texts: Iterable[str], patterns: list[str] | None = None) -> int:
    """يحسب كم نص من القائمة المعطاة سيُمنع بهذه الأنماط."""
    pats = patterns if patterns is not None else get_patterns()
    if not pats:
        return 0
    return sum(1 for t in texts if matches(t, pats) is not None)


__all__ = [
    "CONFIG_PATH",
    "DEFAULT_PATTERNS",
    "load_patterns",
    "save_patterns",
    "reset_to_defaults",
    "get_patterns",
    "reload",
    "add_pattern",
    "remove_pattern",
    "matches",
    "count_matching",
]
