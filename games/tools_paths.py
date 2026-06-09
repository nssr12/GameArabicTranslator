"""
games/tools_paths.py — مُحلِّل مسارات الأدوات الخارجية (واعٍ بالنسخة المُغلَّفة).

ترتيب البحث لكل أداة:
  1. config.json["tools"][key]  (إن ضُبط يدوياً في لوحة الأدمن)
  2. مواقع النسخة المُغلَّفة (next to exe، _internal، _MEIPASS)
  3. مجلّد المشروع (tools/) في وضع التطوير

الهدف: أن يجد التطبيق الأدوات سواء كان نسخة مطوّر أو حزمة PyInstaller، فيتمكّن
المستخدم النهائي من البناء/التحديث محلياً (لا يعتمد على pak جاهز فقط).
"""
from __future__ import annotations
import os
import sys
import json
from functools import lru_cache

# مفاتيح الأدوات: key → (config_key, [مسارات نسبية مرشّحة])
_TOOLS = {
    "repak":     ("repak_path",     ["tools/repak/repak.exe"]),
    "uassetgui": ("uassetgui_path", ["tools/UAssetGUI/UAssetGUI.exe", "tools/UAssetGUI.exe"]),
    "retoc":     ("retoc_path",     ["tools/retoc/retoc.exe"]),
    "unrealpak": ("unrealpak_path", ["tools/UnrealPak/UnrealPak.exe"]),
    "ue4loc":    ("ue4loc_tool",    ["tools/UE4localizationsTool/UE4localizationsTool.exe"]),
}


def _project_root() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _search_bases() -> list[str]:
    bases: list[str] = []
    if getattr(sys, "frozen", False):
        exedir = os.path.dirname(sys.executable)
        bases += [exedir, os.path.join(exedir, "_internal")]
        mei = getattr(sys, "_MEIPASS", "")
        if mei:
            bases.append(mei)
    bases.append(_project_root())
    # أزل التكرار مع الحفاظ على الترتيب
    seen, out = set(), []
    for b in bases:
        if b and b not in seen:
            seen.add(b)
            out.append(b)
    return out


def _config_tools() -> dict:
    try:
        with open(os.path.join(_project_root(), "config.json"), encoding="utf-8") as f:
            return (json.load(f).get("tools", {}) or {})
    except Exception:
        return {}


def find_tool(key: str) -> str:
    """يُرجع المسار الكامل لأداة موجودة فعلاً، أو '' إن لم تُوجد."""
    cfg_key, rels = _TOOLS.get(key, ("", []))
    # 1) config يدوي
    cfg = _config_tools()
    p = (cfg.get(cfg_key, "") or "").strip()
    if p and os.path.isfile(p):
        return p
    # 2/3) مواقع الحزمة ثم المشروع
    for base in _search_bases():
        for rel in rels:
            cand = os.path.join(base, *rel.split("/"))
            if os.path.isfile(cand):
                return cand
    return ""


# اختصارات
def repak() -> str:     return find_tool("repak")
def uassetgui() -> str: return find_tool("uassetgui")
def retoc() -> str:     return find_tool("retoc")
def unrealpak() -> str: return find_tool("unrealpak")
def ue4loc() -> str:    return find_tool("ue4loc")


__all__ = ["find_tool", "repak", "uassetgui", "retoc", "unrealpak", "ue4loc"]
