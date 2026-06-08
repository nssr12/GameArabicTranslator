"""
engine/rtl_overrides.py — تحديد النصوص التي تحتاج عكس RTL يدوياً (لكل لعبة).

بعض ودجات اللعبة لا تطبّق BiDi (تعكس العربي) بينما غيرها يطبّقه صح. لتجنّب كسر
الودجات السليمة، المستخدم يُعلّم **النصوص التي تظهر في الودجات المعكوسة فقط** (مثل
صفحة المساعدة) من صفحة الكاش، ونطبّق عليها engine.ue_rtl_reverse عند البناء/التحديث.

التخزين: data/cache/<game>.rtlrev.json = ["english source text", ...]
المفتاح = النص الإنجليزي الأصلي (يطابق مفتاح الكاش).
"""
from __future__ import annotations
import json
import os

_DIR = os.path.join("data", "cache")


def _path(game: str) -> str:
    safe = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in game).strip()
    return os.path.join(_DIR, f"{safe}.rtlrev.json")


def load(game: str) -> set:
    try:
        with open(_path(game), "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return set()


def is_marked(game: str, text: str) -> bool:
    return text in load(game)


def _save(game: str, s: set) -> None:
    os.makedirs(_DIR, exist_ok=True)
    with open(_path(game), "w", encoding="utf-8") as f:
        json.dump(sorted(s), f, ensure_ascii=False, indent="\t")


def set_marked(game: str, text: str, marked: bool) -> None:
    s = load(game)
    if marked:
        s.add(text)
    else:
        s.discard(text)
    _save(game, s)


def toggle(game: str, texts: list) -> bool:
    """يبدّل مجموعة نصوص دفعةً: لو أي منها غير مُعلَّم → علّم الكل، وإلا أزل الكل.
    يُرجع الحالة الجديدة (مُعلَّم/غير)."""
    s = load(game)
    mark = any(t not in s for t in texts)
    for t in texts:
        if mark:
            s.add(t)
        else:
            s.discard(t)
    _save(game, s)
    return mark


def count(game: str) -> int:
    return len(load(game))


# ── عكس على مستوى الجدول (لجداول كاملة مثل DT_Translation_Wiki = الموسوعة) ──
# يعكس النص **فقط عند ظهوره في هذه الجداول** (لا في الجداول الأخرى) → يتجنّب
# تداخل النصوص المشتركة مع جداول الواجهة/التلميحات.

def _tables_path(game: str) -> str:
    safe = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in game).strip()
    return os.path.join(_DIR, f"{safe}.rtltables.json")


def load_tables(game: str) -> set:
    try:
        with open(_tables_path(game), "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return set()


def set_table(game: str, table: str, marked: bool) -> None:
    s = load_tables(game)
    if marked:
        s.add(table)
    else:
        s.discard(table)
    os.makedirs(_DIR, exist_ok=True)
    with open(_tables_path(game), "w", encoding="utf-8") as f:
        json.dump(sorted(s), f, ensure_ascii=False, indent="\t")


__all__ = ["load", "is_marked", "set_marked", "toggle", "count",
           "load_tables", "set_table"]
