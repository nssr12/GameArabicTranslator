"""
engine/static_translations.py — قارئ ملف translations.txt (المرجع اليدوي).

الفلسفة:
  • translations.txt = مصدر يدوي عالي الجودة (يحرّره المستخدم)
  • الكاش (SQLite) = ترجمات AI تلقائية
  • الأولوية: translations.txt → الكاش → AI

الصيغة: سطر واحد لكل ترجمة بصيغة  key=value
  - يبدأ السطر بـ # → تعليق يُتجاهَل
  - \\n في السطر → سطر جديد فعلي بعد التحميل
  - \\=  في الـ key → علامة = حرفية (لا تُعتبر فاصلاً)

المسار: <game_path>/BepInEx/config/ArabicGameTranslator/translations.txt
"""
from __future__ import annotations

import os
import threading

# كاش في الذاكرة + بصمة آخر تحميل (mtime + path) لإعادة التحميل التلقائية
_lock = threading.RLock()
_cache: dict[str, str] = {}
_cache_path: str = ""
_cache_mtime: float = 0.0


def get_translations_path(game_path: str) -> str:
    """يُرجع المسار المتوقّع لملف translations.txt للعبة معيّنة."""
    if not game_path:
        return ""
    return os.path.join(
        game_path, "BepInEx", "config", "ArabicGameTranslator", "translations.txt"
    )


def _parse_lines(lines: list[str]) -> dict[str, str]:
    """يحلّل أسطر الملف ويُرجع dict مع تطبيع \\n."""
    out: dict[str, str] = {}
    for line in lines:
        if not line:
            continue
        # تجاهل التعليقات
        if line.lstrip().startswith("#"):
            continue
        # ابحث عن أول = غير مسبوق بـ \
        idx = -1
        i = 0
        while i < len(line):
            if line[i] == "=" and (i == 0 or line[i - 1] != "\\"):
                idx = i
                break
            i += 1
        if idx <= 0:
            continue
        key = line[:idx].replace("\\=", "=").replace("\\n", "\n")
        val = line[idx + 1:].replace("\\n", "\n").rstrip("\r\n")
        if key and val:
            out[key] = val
    return out


def load(game_path: str) -> tuple[dict[str, str], str]:
    """يحمّل translations.txt للعبة. يُرجع (dict, path).
    لو الملف غير موجود → ({}, path) — نرجع المسار للتسجيل.
    """
    global _cache, _cache_path, _cache_mtime
    path = get_translations_path(game_path)
    if not path or not os.path.isfile(path):
        with _lock:
            _cache = {}
            _cache_path = path
            _cache_mtime = 0.0
        return {}, path
    try:
        mtime = os.path.getmtime(path)
        with open(path, "r", encoding="utf-8") as f:
            data = _parse_lines(f.read().splitlines())
        with _lock:
            _cache = data
            _cache_path = path
            _cache_mtime = mtime
        return data, path
    except Exception:
        with _lock:
            _cache = {}
            _cache_path = path
            _cache_mtime = 0.0
        return {}, path


def _maybe_reload() -> None:
    """يُعيد التحميل تلقائياً إذا تغيّر mtime للملف (المستخدم عدّله يدوياً)."""
    global _cache, _cache_mtime
    path = _cache_path
    if not path or not os.path.isfile(path):
        return
    try:
        m = os.path.getmtime(path)
    except OSError:
        return
    if m == _cache_mtime:
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = _parse_lines(f.read().splitlines())
        with _lock:
            _cache = data
            _cache_mtime = m
    except Exception:
        pass


def lookup(text: str) -> str | None:
    """يبحث عن النص في translations.txt المُحمَّل. None إذا غير موجود."""
    if not text:
        return None
    with _lock:
        # تحقّق سريع من تغيّر الملف (المستخدم قد يكون حدّثه)
        pass
    _maybe_reload()
    with _lock:
        return _cache.get(text)


def count() -> int:
    """عدد الإدخالات المحمَّلة حالياً."""
    with _lock:
        return len(_cache)


def current_path() -> str:
    """مسار الملف المُحمَّل حالياً (أو "" إذا لا يوجد)."""
    with _lock:
        return _cache_path


def clear() -> None:
    """يمسح الكاش — يُستدعى عند توقّف البروكسي أو تبديل اللعبة."""
    global _cache, _cache_path, _cache_mtime
    with _lock:
        _cache = {}
        _cache_path = ""
        _cache_mtime = 0.0


__all__ = [
    "get_translations_path",
    "load",
    "lookup",
    "count",
    "current_path",
    "clear",
]
