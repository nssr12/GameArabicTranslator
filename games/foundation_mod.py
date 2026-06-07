"""
games/foundation_mod.py — تثبيت/إلغاء تعريب Foundation (محرّك Hurricane خاص).

الآلية (انظر CLAUDE.md "تعريب Foundation"):
  • proxy `CrashRpt1403.dll` (من mods/Foundation/) يُحمَّل تلقائياً عند الإطلاق العادي
    عبر Steam → MinHook على FT_New_Memory_Face → يستبدل خطوط الواجهة بخط عربي.
  • خطوط الاستبدال: arabic_regular.ttf (arial) + arabic_bold.ttf (arialbd) — تُنسخ من Windows.
  • الترجمة: تُطبَّق من الكاش (Foundation.db) إلى localization/ar/*.json بتخطيط RTL
    (engine.rtl_layout.layout_rtl: تطبيع \n + لفّ ذاتي + تشكيل/عكس لكل سطر).
  • يسجّل ar في locales.txt (اسم مُشكّل)، يضبط اللغة=ar، يحذف charset (يُعاد توليده).

التثبيت/الإلغاء عكسيّان بالكامل (uninstall يستعيد الأصل).
⚠ تحديث Steam يستعيد CrashRpt1403.dll الأصلية → أعد التثبيت.
"""
from __future__ import annotations
import json
import os
import re
import shutil
from typing import List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROXY_SRC_DIR = os.path.join(ROOT, "mods", "Foundation")
PROXY_NAME = "CrashRpt1403.dll"
ORIG_NAME = "CrashRpt1403_orig.dll"

# خطوط Windows (Regular + Bold فقط فيها عربي؛ المائل بلا عربي والعربية بلا مائل)
WIN_FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
FONT_MAP = {"arabic_regular.ttf": "arial.ttf", "arabic_bold.ttf": "arialbd.ttf"}

_LETTER = re.compile(r"[A-Za-z]")
_TOKEN_RE = re.compile(r"<[^>]*>|\{[^{}]*\}|%[0-9]*[A-Za-z]")


def _usersetting_path() -> str:
    base = os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))
    return os.path.join(base, "Polymorph Games", "Foundation", "usersetting.config")


def _is_translatable(text: str) -> bool:
    return bool(text and text.strip() and _LETTER.search(_TOKEN_RE.sub(" ", text)))


def _walk(obj, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, path + (i,))
    elif isinstance(obj, str):
        yield path, obj


def _set_at(obj, path, value):
    for k in path[:-1]:
        obj = obj[k]
    obj[path[-1]] = value


class FoundationMod:
    """تثبيت/إلغاء تعريب Foundation. واجهة مماثلة لـ BepInExMod."""

    # ── دعم/حالة ─────────────────────────────────────────────────────────
    @staticmethod
    def is_supported(game_cfg: dict) -> bool:
        return (game_cfg.get("engine") == "hurricane"
                or game_cfg.get("hook_mode") == "foundation_proxy"
                or "foundation" in game_cfg)

    @staticmethod
    def proxy_src_exists() -> bool:
        return os.path.exists(os.path.join(PROXY_SRC_DIR, PROXY_NAME))

    def get_install_status(self, game_cfg: dict, game_path: str) -> Optional[bool]:
        """True=مثبَّت، False=غير مثبَّت، None=المسار غير مضبوط."""
        if not game_path or not os.path.isdir(game_path):
            return None
        # مثبَّت لو الأصلية أُعيد تسميتها (الـ proxy منشور)
        return os.path.exists(os.path.join(game_path, ORIG_NAME))

    # ── تطبيق الترجمة من الكاش → ar/*.json بتخطيط RTL ────────────────────
    def apply_translations(self, game_cfg: dict, game_path: str, cache,
                           wrap: int = 45) -> Tuple[int, int]:
        """يقرأ en/*.json + الكاش → يكتب ar/*.json (مُشكّل + ملفوف). يُرجع (ملفات, نصوص)."""
        from engine.rtl_layout import layout_rtl
        from engine import wrap_overrides
        game_name = game_cfg.get("name", "Foundation")
        overrides = wrap_overrides.load(game_name)   # {english: wrap} يطغى على العام
        en_dir = os.path.join(game_path, "localization", "en")
        ar_dir = os.path.join(game_path, "localization", "ar")
        os.makedirs(ar_dir, exist_ok=True)
        nfiles = nstr = 0
        for fn in sorted(os.listdir(en_dir)):
            if not fn.endswith(".json"):
                continue
            with open(os.path.join(en_dir, fn), "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            for path, en_text in _walk(data):
                if not _is_translatable(en_text):
                    continue
                ar = cache.get_best(game_name, en_text)
                if ar:
                    w = overrides.get(en_text, wrap)   # override للنص إن وُجد
                    _set_at(data, path, layout_rtl(ar, max_line_len=w))
                    nstr += 1
            with open(os.path.join(ar_dir, fn), "w", encoding="utf-8-sig") as f:
                json.dump(data, f, ensure_ascii=False, indent="\t")
            nfiles += 1
        return nfiles, nstr

    # ── locales.txt + اللغة + charset ────────────────────────────────────
    def _register_locale(self, game_path: str, log: List[str]):
        from engine.arabic_shaper import shape_for_tmp
        p = os.path.join(game_path, "localization", "locales.txt")
        if not os.path.exists(p):
            return
        lines = [l for l in open(p, encoding="utf-8-sig").read().splitlines() if l.strip()]
        lines = [l for l in lines if not l.startswith("ar:")]
        lines.append("ar:" + shape_for_tmp("العربية"))
        open(p, "w", encoding="utf-8-sig").write("\n".join(lines) + "\n")
        log.append("✓ سُجّلت ar في locales.txt")

    def _set_language(self, code: str, log: List[str]):
        p = _usersetting_path()
        if not os.path.exists(p):
            log.append(f"⚠ usersetting.config غير موجود (شغّل اللعبة مرّة): {p}")
            return
        t = open(p, encoding="utf-8-sig").read()
        t2 = re.sub(r'<Language value="[^"]*"/>', f'<Language value="{code}"/>', t)
        open(p, "w", encoding="utf-8-sig").write(t2)
        log.append(f"✓ اللغة → {code}")

    def _delete_charset(self, game_path: str, log: List[str]):
        loc = os.path.join(game_path, "localization")
        for fn in ("charset.txt", "charset-spaceless.txt"):
            fp = os.path.join(loc, fn)
            if os.path.exists(fp):
                os.remove(fp)
        log.append("✓ حُذف charset (يُعاد توليده عند التشغيل)")

    # ── التثبيت ──────────────────────────────────────────────────────────
    def install(self, game_cfg: dict, game_path: str, cache,
                wrap: Optional[int] = None) -> Tuple[bool, List[str]]:
        log: List[str] = []
        if not game_path or not os.path.isdir(game_path):
            return False, ["❌ مسار اللعبة غير صحيح"]
        if not self.proxy_src_exists():
            return False, [f"❌ الـ proxy غير موجود في {PROXY_SRC_DIR}"]
        wrap = wrap if wrap is not None else game_cfg.get("foundation", {}).get("wrap", 45)

        try:
            # 1) نسخ احتياطي للأصلية ثم وضع الـ proxy
            dst = os.path.join(game_path, PROXY_NAME)
            orig = os.path.join(game_path, ORIG_NAME)
            if not os.path.exists(orig):
                if os.path.exists(dst):
                    shutil.move(dst, orig)
                    log.append(f"✓ احتياطي: {PROXY_NAME} → {ORIG_NAME}")
                else:
                    return False, [f"❌ {PROXY_NAME} الأصلية غير موجودة في مجلّد اللعبة"]
            shutil.copy2(os.path.join(PROXY_SRC_DIR, PROXY_NAME), dst)
            log.append("✓ نُشر الـ proxy")

            # 2) خطوط الاستبدال (من Windows)
            for out_name, win_name in FONT_MAP.items():
                src = os.path.join(WIN_FONTS, win_name)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(game_path, out_name))
                else:
                    log.append(f"⚠ خط Windows غير موجود: {win_name}")
            log.append("✓ نُسخت خطوط الاستبدال (Regular + Bold)")

            # 3) الترجمة → ar/*.json بتخطيط RTL
            nf, ns = self.apply_translations(game_cfg, game_path, cache, wrap=wrap)
            log.append(f"✓ طُبّقت الترجمة: {ns} نص في {nf} ملف (wrap={wrap})")

            # 4) locales + اللغة + charset
            self._register_locale(game_path, log)
            self._set_language(game_cfg.get("foundation", {}).get("lang_code", "ar"), log)
            self._delete_charset(game_path, log)

            log.append("🎉 التثبيت اكتمل — شغّل اللعبة عبر Steam عادي.")
            return True, log
        except Exception as e:
            log.append(f"❌ خطأ: {e}")
            return False, log

    # ── تحديث الترجمة فقط (بعد تعديل في الكاش) ────────────────────────────
    def update_translations(self, game_cfg: dict, game_path: str, cache,
                            wrap: Optional[int] = None) -> Tuple[bool, List[str]]:
        log: List[str] = []
        if self.get_install_status(game_cfg, game_path) is not True:
            return False, ["❌ غير مثبَّت — ثبّت أولاً"]
        wrap = wrap if wrap is not None else game_cfg.get("foundation", {}).get("wrap", 45)
        try:
            nf, ns = self.apply_translations(game_cfg, game_path, cache, wrap=wrap)
            self._delete_charset(game_path, log)
            log.append(f"✓ حُدّثت الترجمة: {ns} نص في {nf} ملف (wrap={wrap}) — أعد تشغيل اللعبة")
            return True, log
        except Exception as e:
            return False, [f"❌ خطأ: {e}"]

    # ── تغيير خط الاستبدال (للتجربة) ──────────────────────────────────────
    @staticmethod
    def font_coverage(font_path: str) -> dict:
        """يُرجع تغطية الخط للعربي + presentation forms (لازمة للنص المُشكّل)."""
        try:
            from fontTools.ttLib import TTFont
            cmap = TTFont(font_path, fontNumber=0).getBestCmap()
        except Exception as e:
            return {"error": str(e), "arabic": 0, "pf_a": 0, "pf_b": 0}
        return {
            "arabic": sum(1 for c in cmap if 0x600 <= c <= 0x6FF),
            "pf_a":   sum(1 for c in cmap if 0xFB50 <= c <= 0xFDFF),
            "pf_b":   sum(1 for c in cmap if 0xFE70 <= c <= 0xFEFF),
        }

    @staticmethod
    def current_font_name(game_path: str, slot: str = "regular") -> Optional[str]:
        """اسم الخط المُطبَّق حالياً (من name table) أو None لو غير موجود."""
        fp = os.path.join(game_path, "arabic_bold.ttf" if slot == "bold" else "arabic_regular.ttf")
        if not os.path.exists(fp):
            return None
        try:
            from fontTools.ttLib import TTFont
            nm = TTFont(fp, fontNumber=0)["name"]
            for nid in (4, 1, 6):   # full name، family، postscript
                v = nm.getDebugName(nid)
                if v:
                    return v
        except Exception:
            pass
        return "خط مخصّص"

    SLOT_FILES = {
        "regular": ["arabic_regular.ttf"],
        "bold":    ["arabic_bold.ttf"],
        "both":    ["arabic_regular.ttf", "arabic_bold.ttf"],
    }

    def set_font(self, game_path: str, font_path: str, slot: str = "both") -> Tuple[bool, List[str]]:
        """ينسخ خطاً للفتحة (regular/bold/both) + يحذف charset. أعد تشغيل اللعبة لرؤيته.
        الخط يمكن أن يكون بأي حجم — الـ hook يطابق خط اللعبة بالحجم ويضع هذا مكانه."""
        log: List[str] = []
        if not os.path.isfile(font_path):
            return False, ["❌ ملف الخط غير موجود"]
        targets = self.SLOT_FILES.get(slot)
        if not targets:
            return False, [f"❌ فتحة غير صحيحة: {slot}"]
        try:
            for t in targets:
                shutil.copy2(font_path, os.path.join(game_path, t))
                log.append(f"✓ {os.path.basename(font_path)} → {t}")
            self._delete_charset(game_path, log)
            log.append("أعد تشغيل اللعبة لرؤية الخط الجديد.")
            return True, log
        except Exception as e:
            return False, [f"❌ خطأ: {e}"]

    # ── الإلغاء (عكسي بالكامل) ────────────────────────────────────────────
    def uninstall(self, game_cfg: dict, game_path: str) -> Tuple[bool, List[str]]:
        log: List[str] = []
        if not game_path or not os.path.isdir(game_path):
            return False, ["❌ مسار اللعبة غير صحيح"]
        try:
            dst = os.path.join(game_path, PROXY_NAME)
            orig = os.path.join(game_path, ORIG_NAME)
            if os.path.exists(orig):
                if os.path.exists(dst):
                    os.remove(dst)
                shutil.move(orig, dst)
                log.append("✓ استُعيدت CrashRpt1403.dll الأصلية")
            # احذف خطوط الاستبدال
            for out_name in FONT_MAP:
                fp = os.path.join(game_path, out_name)
                if os.path.exists(fp):
                    os.remove(fp)
            log.append("✓ حُذفت خطوط الاستبدال")
            # أرجع اللغة لإنجليزي + احذف charset (يُعاد توليده لاتيني)
            self._set_language("en", log)
            self._delete_charset(game_path, log)
            log.append("✓ أُلغي التعريب — اللعبة رجعت إنجليزية.")
            return True, log
        except Exception as e:
            return False, [f"❌ خطأ: {e}"]
