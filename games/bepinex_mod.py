"""
games/bepinex_mod.py  —  إدارة مودات BepInEx+I2 لألعاب Unity

مصادر BepInEx (بالأولوية):
  1. mods/<GameName>/bepinex/   ← مجلد محفوظ مسبقاً
  2. tools/BepInEx*.zip         ← أرشيف جاهز في مجلد tools
  3. أي mods/<Other>/bepinex/   ← من لعبة أخرى

يُثبَّت على اللعبة:
    <game_path>/winhttp.dll
    <game_path>/BepInEx/core/...
    <game_path>/BepInEx/plugins/<dll_name>
    <game_path>/BepInEx/config/ArabicGameTranslator/<translations_json>
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import sys
import zipfile
from typing import List, Optional, Tuple

if getattr(sys, "frozen", False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

_MODS_DIR    = os.path.join(_BASE, "mods")
_TOOLS_DIR   = os.path.join(_BASE, "tools")
_SHARED_BASE = os.path.join(_MODS_DIR, "_bepinex_base")   # BepInEx+XUnity مشترك لكل الألعاب

# الملفات/المجلدات التي تُشكّل BepInEx base
_BEPINEX_BASE_ITEMS = [
    "winhttp.dll",
    "doorstop_config.ini",
    os.path.join("BepInEx", "core"),
]


class BepInExMod:
    """إدارة تثبيت/إلغاء/تحديث مودات BepInEx+I2 لألعاب Unity."""

    # ── مسارات ───────────────────────────────────────────────────────────────

    def get_dll_src(self, game_name: str, dll_name: str) -> str:
        """مسار DLL داخل مجلد mods/."""
        return os.path.join(_MODS_DIR, game_name, dll_name)

    def _bepinex_base_dir(self, game_name: str) -> str:
        """مجلد ملفات BepInEx الأساسية: mods/<GameName>/bepinex/"""
        return os.path.join(_MODS_DIR, game_name, "bepinex")

    def _find_any_bepinex_base(self, skip_game: str = "") -> str:
        """يبحث عن أي mods/<OtherGame>/bepinex/ جاهز ويعيد مساره، أو "" إن لم يجد."""
        if not os.path.isdir(_MODS_DIR):
            return ""
        for entry in os.listdir(_MODS_DIR):
            if entry == skip_game:
                continue
            candidate = os.path.join(_MODS_DIR, entry, "bepinex")
            if os.path.isdir(candidate) and (
                os.path.exists(os.path.join(candidate, "winhttp.dll"))
                or os.path.isdir(os.path.join(candidate, "BepInEx", "core"))
            ):
                return candidate
        return ""

    def find_bepinex_zip(self) -> str:
        """يبحث عن BepInEx*.zip في مجلد tools/ ويعيد مساره، أو "" إن لم يجد."""
        pattern = os.path.join(_TOOLS_DIR, "BepInEx*.zip")
        matches = sorted(glob.glob(pattern), reverse=True)  # أحدث إصدار أولاً
        return matches[0] if matches else ""

    def install_bepinex_from_zip(self, zip_path: str, game_path: str) -> Tuple[bool, str, int]:
        """
        يستخرج BepInEx zip مباشرة إلى game_path.
        يعيد (success, message, files_count).
        """
        try:
            count = 0
            with zipfile.ZipFile(zip_path, "r") as zf:
                skip = {"changelog.txt"}
                for member in zf.infolist():
                    if member.filename in skip or member.filename.endswith("/"):
                        continue
                    dest = os.path.join(game_path, member.filename)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(member) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    count += 1
            return True, os.path.basename(zip_path), count
        except Exception as e:
            return False, str(e), 0

    def _plugins_dir(self, game_path: str) -> str:
        return os.path.join(game_path, "BepInEx", "plugins")

    def _config_dir(self, game_path: str) -> str:
        return os.path.join(game_path, "BepInEx", "config", "ArabicGameTranslator")

    # ── مساعد نسخ شجرة مجلد ─────────────────────────────────────────────────

    def _copy_tree(self, src_dir: str, dest_dir: str) -> int:
        """ينسخ شجرة مجلد كاملة فوق dest_dir، يعيد عدد الملفات المنسوخة."""
        count = 0
        for root, _dirs, files in os.walk(src_dir):
            rel = os.path.relpath(root, src_dir)
            d   = os.path.join(dest_dir, rel) if rel != "." else dest_dir
            os.makedirs(d, exist_ok=True)
            for f in files:
                shutil.copy2(os.path.join(root, f), os.path.join(d, f))
                count += 1
        return count

    # ── فحص الدعم والحالة ────────────────────────────────────────────────────

    def is_supported(self, game_cfg: dict) -> bool:
        """True إذا كانت اللعبة تحتوي على قسم bepinex_mod (حتى بدون dll خاص)."""
        return "bepinex_mod" in game_cfg

    def dll_src_exists(self, game_cfg: dict) -> bool:
        """True إذا كان ملف DLL موجوداً في مجلد mods/."""
        bm        = game_cfg.get("bepinex_mod", {})
        dll_name  = bm.get("dll_name", "")
        game_name = game_cfg.get("name", "")
        if not dll_name or not game_name:
            return False
        return os.path.exists(self.get_dll_src(game_name, dll_name))

    def bepinex_base_exists(self, game_cfg: dict) -> bool:
        """True إذا كانت ملفات BepInEx الأساسية موجودة في mods/<GameName>/bepinex/"""
        base = self._bepinex_base_dir(game_cfg.get("name", ""))
        if not os.path.isdir(base):
            return False
        return (
            os.path.exists(os.path.join(base, "winhttp.dll"))
            or os.path.isdir(os.path.join(base, "BepInEx", "core"))
        )

    def has_bepinex_source(self, game_cfg: dict) -> bool:
        """True إذا كان مصدر BepInEx متاحاً (shared base أو مجلد أو zip أو لعبة أخرى)."""
        return bool(self._resolve_bepinex_source(game_cfg))

    def _resolve_bepinex_source(self, game_cfg: dict) -> str:
        """
        يعيد مسار مصدر BepInEx المتاح بالأولوية:
        1. _bepinex_base (مشترك)
        2. mods/<GameName>/bepinex/ (خاص باللعبة)
        3. أي lعبة أخرى لديها bepinex/
        4. "" إذا لم يجد شيئاً
        """
        if os.path.isdir(_SHARED_BASE) and (
            os.path.exists(os.path.join(_SHARED_BASE, "winhttp.dll"))
            or os.path.isdir(os.path.join(_SHARED_BASE, "BepInEx", "core"))
        ):
            return _SHARED_BASE
        game_base = self._bepinex_base_dir(game_cfg.get("name", ""))
        if self.bepinex_base_exists(game_cfg):
            return game_base
        other = self._find_any_bepinex_base(game_cfg.get("name", ""))
        if other:
            return other
        return ""

    def is_bepinex_installed(self, game_path: str) -> bool:
        """True إذا كان BepInEx مثبتاً فعلاً في مجلد اللعبة."""
        if not game_path:
            return False
        for probe in (
            "winhttp.dll",
            "doorstop_config.ini",
            os.path.join("BepInEx", "core", "BepInEx.dll"),
        ):
            if os.path.exists(os.path.join(game_path, probe)):
                return True
        return False

    def get_install_status(self, game_cfg: dict, game_path: str) -> Optional[bool]:
        """
        True  = مُثبَّت (DLL plugin إذا كان محدداً، وإلا BepInEx نفسه)
        False = غير مُثبَّت
        None  = مسار اللعبة غير محدد
        """
        if not game_path:
            return None
        bm       = game_cfg.get("bepinex_mod", {})
        dll_name = bm.get("dll_name", "")
        if dll_name:
            dest = os.path.join(self._plugins_dir(game_path), dll_name)
            return os.path.exists(dest)
        # XUnity mode (no custom DLL) — installed = BepInEx present in game
        return self.is_bepinex_installed(game_path)

    def is_xunity_installed(self, game_path: str) -> bool:
        """True إذا كان XUnity.AutoTranslator مثبَّتاً في مجلد اللعبة."""
        if not game_path:
            return False
        return os.path.exists(os.path.join(
            self._plugins_dir(game_path), "XUnity.AutoTranslator.Plugin.BepInEx.dll"
        ))

    def is_font_fixer_installed(self, game_path: str) -> bool:
        """True إذا كان ArabicFontFixer.dll مثبَّتاً في مجلد اللعبة."""
        if not game_path:
            return False
        return os.path.exists(os.path.join(
            self._plugins_dir(game_path), "ArabicFontFixer.dll"
        ))

    def get_cache_count(self, game_cfg: dict, cache) -> int:
        """عدد الترجمات المخزنة في الكاش لهذه اللعبة."""
        try:
            return cache.count_entries(game_cfg.get("name", "")) if cache else 0
        except Exception:
            return 0

    def get_json_status(self, game_cfg: dict, game_path: str) -> Optional[bool]:
        """True = ملف JSON الترجمات موجود في مجلد config اللعبة."""
        if not game_path:
            return None
        bm        = game_cfg.get("bepinex_mod", {})
        json_name = bm.get("translations_json", "")
        if not json_name:
            return None
        dest = os.path.join(self._config_dir(game_path), json_name)
        return os.path.exists(dest)

    # ── بناء قائمة الترجمات ──────────────────────────────────────────────────

    def build_entries(
        self, game_cfg: dict, game_path: str, cache
    ) -> Tuple[List[dict], str]:
        """
        يبني قائمة {"key": term_key, "Arabic": translated} من الكاش.
        الأولوية: I2 source file → كل الكاش كـ fallback.
        يعيد (entries, warning_message).
        """
        bm        = game_cfg.get("bepinex_mod", {})
        i2_rel    = bm.get("i2_source_file", "")
        game_name = game_cfg.get("name", "")
        entries: List[dict] = []
        warning = ""

        if i2_rel and game_path:
            i2_path = os.path.join(game_path, i2_rel)
            if os.path.exists(i2_path):
                try:
                    with open(i2_path, encoding="utf-8") as f:
                        data = json.load(f)
                    terms = data.get("mSource", {}).get("mTerms", {}).get("Array", [])
                    term_keys: List[str] = []
                    en_texts:  List[str] = []
                    for t in terms:
                        key   = t.get("Term", "")
                        langs = t.get("Languages", {}).get("Array", [])
                        en    = langs[0] if langs and isinstance(langs[0], str) else ""
                        if key and en and len(en.strip()) >= 2:
                            term_keys.append(key)
                            en_texts.append(en.strip())

                    if cache and term_keys:
                        cached = cache.get_batch(game_name, en_texts)
                        for key, en in zip(term_keys, en_texts):
                            ar = cached.get(en)
                            if ar:
                                entries.append({"key": key, "Arabic": ar})
                    return entries, ""
                except Exception as e:
                    warning = f"تعذّر قراءة I2 source: {e}"
            else:
                warning = "ملف I2Languages غير موجود في مسار اللعبة"

        if not entries and cache and game_name:
            try:
                all_t   = cache.get_all_for_game(game_name)
                entries = [{"key": k, "Arabic": v} for k, v in all_t.items()]
                suffix  = " — صُدِّر الكاش الكامل بدلاً من ذلك" if warning else ""
                warning = (warning + suffix) if warning else "صُدِّر الكاش كاملاً (ملف I2 غير متاح)"
            except Exception:
                pass

        return entries, warning

    # ── تصدير ملف الترجمات ───────────────────────────────────────────────────

    def export_translations(
        self, game_cfg: dict, game_path: str, cache
    ) -> Tuple[bool, str, int]:
        """
        يكتب ملف JSON الترجمات إلى BepInEx/config/ArabicGameTranslator/.
        يعيد (success, message, count).
        """
        bm        = game_cfg.get("bepinex_mod", {})
        json_name = bm.get("translations_json", "")
        if not json_name or not game_path:
            return False, "إعدادات ناقصة أو مسار اللعبة غير محدد", 0

        dest_dir  = self._config_dir(game_path)
        dest_path = os.path.join(dest_dir, json_name)

        entries, warn = self.build_entries(game_cfg, game_path, cache)
        if not entries:
            # لا تحذف JSON موجود عند الكاش الفارغ
            if os.path.exists(dest_path):
                try:
                    with open(dest_path, encoding="utf-8") as f:
                        existing = json.load(f)
                    existing_count = len(existing.get("entries", []))
                    if existing_count > 0:
                        return True, f"الكاش فارغ — محافظ على الـ JSON الحالي ({existing_count:,} ترجمة)", existing_count
                except Exception:
                    pass
            return False, warn or "لا توجد ترجمات في الكاش لهذه اللعبة", 0
        try:
            os.makedirs(dest_dir, exist_ok=True)
            with open(dest_path, "w", encoding="utf-8") as f:
                json.dump({"entries": entries}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return False, f"خطأ في الكتابة: {e}", 0

        msg = f"صُدِّرت {len(entries):,} ترجمة → BepInEx/config/ArabicGameTranslator/{json_name}"
        if warn:
            msg += f"\n⚠ {warn}"
        return True, msg, len(entries)

    # ── تصدير translations.txt (للـ ArabicFontFixer static hook) ────────────

    @staticmethod
    def _shape_arabic(text: str) -> str:
        """
        يشكّل الحروف العربية (Presentation Forms) ويُبقيها بالترتيب المنطقي.

        ⚠ ضروري لأن:
          • الخط Arabic fallback (Tahoma من النظام) عند تحويله إلى TMP_FontAsset
            عبر CreateDynamicFontFromOSFont يفقد جداول OpenType للـ Arabic shaping.
          • TMP بدون presentation forms مسبقة يعرض الأحرف في صيغة isolated فقط
            (لا توصيل بين الحروف) → النص يظهر مفكّكاً ("متابعة" تبدو "م ت ا ب ع ة").
          • بتطبيق reshape هنا، الأحرف تصل لـ TMP بصيغة presentation forms جاهزة،
            ثم isRightToLeftText=true يعكس الترتيب البصري للقراءة من اليمين.

        التاقات (<color=...> إلخ) محمية بـ PUA placeholders.
        """
        try:
            import re
            import arabic_reshaper

            def _process(seg: str) -> str:
                if not seg.strip():
                    return seg
                if '<' not in seg:
                    return arabic_reshaper.reshape(seg)
                TAG_RE = re.compile(r'<[^>]+>')
                phs: dict = {}
                ctr = [0]
                def rep(m):
                    ph = chr(0xE000 + ctr[0]); phs[ph] = m.group(0); ctr[0] += 1; return ph
                protected = TAG_RE.sub(rep, seg)
                shaped = arabic_reshaper.reshape(protected)
                for ph, tag in phs.items():
                    shaped = shaped.replace(ph, tag)
                return shaped

            # نُسطّح النص لجملة واحدة — TMP في وضع RTL سيُقسّمها بنفسه
            flat = " ".join(text.replace("\\n", " ").replace("\n", " ").split())
            return _process(flat) if flat else text

        except ImportError:
            return text
        except Exception:
            return text

    def export_static_translations_txt(
        self, game_cfg: dict, game_path: str, cache, model_filter: str = ""
    ) -> Tuple[bool, str, int]:
        """
        يكتب ملف translations.txt بصيغة  key=value  إلى
        BepInEx/config/ArabicGameTranslator/translations.txt

        model_filter:
          - "" (افتراضي): يصدّر كل ترجمات اللعبة مع تطبيق **الدمج الهرمي**:
              1) is_preferred=1
              2) mode_used='manual'
              3) إجماع 2+ مودلات
              4) أعلى model_priority
              5) الأحدث (fallback)
            النص الذي له ترجمات متعدّدة يُصدَّر بترجمة واحدة فقط (الأفضل).
          - "ollama" / "llama3:8b" / ...: يصدّر فقط ترجمات هذا النموذج (بدون دمج).

        ⚠ الكاش (Game.db) لا يُعدَّل — هذه الدالة قراءة فقط.
        الملف الناتج فقط يُحدَّث عند تكرار العملية.
        """
        if not game_path or not cache:
            return False, "مسار اللعبة غير محدد أو الكاش غير متاح", 0

        game_name = game_cfg.get("name", "")
        if not game_name:
            return False, "اسم اللعبة غير محدد", 0

        dest_dir  = self._config_dir(game_path)
        dest_path = os.path.join(dest_dir, "translations.txt")
        # كاشف الترجمات المعطوبة — نتخطّاها حتى لا تظهر في اللعبة
        from engine.tag_health import is_broken_translation
        import re as _re
        # نمط placeholders: {0}, {0:N0}, {playerName} — هذه نصوص template
        # اللعبة تستبدلها قبل إرسال للـ TMP، لذا لن تطابق أبداً في الـ live.
        # وجودها في translations.txt مهدر فقط.
        _template_pat = _re.compile(r"\{\d+[^}]*\}")

        try:
            os.makedirs(dest_dir, exist_ok=True)
            count = 0
            broken = 0
            templates = 0
            skip_count = 0
            with open(dest_path, "w", encoding="utf-8") as f:
                # iter_best_translations يطبّق الدمج الهرمي عندما model_filter=""
                # ويُرجع ترجمة المودل المحدّد عندما يكون غير فارغ.
                # deprioritize_suffix=":i2" يفضّل المودلات الـ live (post-substitution)
                # على ترجمات :i2 (التي تأتي من I2 batch مع context/templates مختلفة).
                exported_keys = set()
                for en, ar in cache.iter_best_translations(
                    game_name, model_filter, deprioritize_suffix=":i2"
                ):
                    if not en or not ar:
                        continue
                    # تخطّى نصوص بصيغة template ({0}, {0:N0}) — لا تطابق نصوص اللعبة
                    if _template_pat.search(en):
                        templates += 1
                        continue
                    # تخطّى الترجمات ذات التاقات المكسورة
                    if is_broken_translation(en, ar):
                        broken += 1
                        continue
                    safe_key  = en.replace("=", "\\=").replace("\n", "\\n")
                    visual_ar = self._shape_arabic(ar).replace("\n", "\\n")
                    f.write(f"{safe_key}={visual_ar}\n")
                    exported_keys.add(en)
                    count += 1

                # تصدير failed_translations كـ markers (=__SKIP__) — يُتجاهَل تلقائياً
                # في الـ DLL، يمنع re-queue كل hover للنصوص غير القابلة للترجمة
                # (أسماء، أرقام نسخ، اختصارات لوحة المفاتيح، ...).
                # ⚠ لا نضيف marker لنص له ترجمة فعلية (حالة الكاش الحالية).
                # نقتصر على الفلتر العام (بلا model_filter) لأن الـ markers مستقلّة عن المودل.
                if not model_filter:
                    try:
                        conn = cache._get_conn(game_name)
                        rows = conn.execute(
                            "SELECT original_text FROM failed_translations"
                        ).fetchall()
                        for (en,) in rows:
                            if not en or en in exported_keys:
                                continue
                            safe_key = en.replace("=", "\\=").replace("\n", "\\n")
                            f.write(f"{safe_key}=__SKIP__\n")
                            skip_count += 1
                    except Exception as e:
                        print(f"[bepinex_mod] failed markers export error: {e}")
        except Exception as e:
            return False, f"خطأ في كتابة translations.txt: {e}", 0

        if count == 0:
            label = f" للنموذج «{model_filter}»" if model_filter else ""
            return False, f"لا توجد ترجمات في الكاش{label}", 0

        if model_filter:
            suffix = f" (نموذج: {model_filter})"
        else:
            suffix = " (دمج هرمي عبر كل المودلات)"
        msg = f"صُدِّرت {count:,} ترجمة{suffix} → translations.txt"
        if skip_count:
            msg += f"  •  {skip_count:,} marker (نصوص بلا ترجمة)"
        if templates:
            msg += f"  •  تخطّى {templates:,} template ({{N}})"
        if broken:
            msg += f"  •  تخطّى {broken:,} معطوبة (تاقات مكسورة)"
        return True, msg, count

    # ── تثبيت كامل ───────────────────────────────────────────────────────────

    def install(
        self, game_cfg: dict, game_path: str, cache
    ) -> Tuple[bool, List[str]]:
        """
        تثبيت كامل:
          1. ملفات BepInEx الأساسية (من mods/<GameName>/bepinex/ إذا وجدت)
          2. DLL الـ plugin
          3. ملف JSON الترجمات
        يعيد (success, log_lines).
        """
        bm        = game_cfg.get("bepinex_mod", {})
        dll_name  = bm.get("dll_name", "")
        game_name = game_cfg.get("name", "")
        log: List[str] = []

        if not game_path:
            return False, ["مسار اللعبة غير محدد — حدده من «تعديل الإعدادات»"]

        # 1. ملفات BepInEx الأساسية
        src_base = self._resolve_bepinex_source(game_cfg)
        needs_install = not self.is_bepinex_installed(game_path)
        # upgrade مطلوب إذا كانت اللعبة عندها ملفات 6.x مختلطة مع 5.x
        needs_upgrade = (
            src_base == _SHARED_BASE and
            self.is_bepinex_installed(game_path) and
            os.path.exists(os.path.join(game_path, "BepInEx", "core", "BepInEx.Core.dll"))
        )
        # لألعاب XUnity (بدون dll خاص): نحدّث plugins دائماً لضمان ArabicFontFixer محدَّث
        is_xunity_mode = not dll_name
        needs_plugins_update = (
            is_xunity_mode and
            src_base == _SHARED_BASE and
            self.is_bepinex_installed(game_path) and
            not needs_upgrade
        )

        if needs_install or needs_upgrade:
            if src_base:
                try:
                    if needs_upgrade:
                        # احذف BepInEx القديم أولاً لضمان عدم بقاء ملفات 6.x
                        for fname in ("winhttp.dll", "doorstop_config.ini", ".doorstop_version"):
                            fp = os.path.join(game_path, fname)
                            if os.path.exists(fp):
                                os.remove(fp)
                        bepinex_dir = os.path.join(game_path, "BepInEx")
                        if os.path.isdir(bepinex_dir):
                            shutil.rmtree(bepinex_dir)
                    count = self._copy_tree(src_base, game_path)
                    label = os.path.basename(src_base)
                    action = "تحديث" if needs_upgrade else "تثبيت"
                    log.append(f"✓ {action} BepInEx ({count} ملف) من {label}")
                except Exception as e:
                    return False, log + [f"خطأ في نسخ ملفات BepInEx: {e}"]
            else:
                return False, [
                    "لم يُعثر على ملفات BepInEx",
                    "المتوقع: mods/_bepinex_base/ أو tools/BepInEx*.zip",
                ]
        elif needs_plugins_update:
            # تحديث plugins فقط (ArabicFontFixer + XUnity)
            plugins_src = os.path.join(src_base, "BepInEx", "plugins")
            if os.path.isdir(plugins_src):
                try:
                    count = self._copy_tree(plugins_src, self._plugins_dir(game_path))
                    log.append(f"✓ تحديث plugins ({count} ملف)")
                except Exception as e:
                    log.append(f"⚠ فشل تحديث plugins: {e}")
        elif self.is_bepinex_installed(game_path):
            log.append("✓ BepInEx مثبَّت")

        # 2. DLL الـ plugin (اختياري — ألعاب XUnity فقط لا تحتاجه)
        if dll_name:
            src_dll = self.get_dll_src(game_name, dll_name)
            if not os.path.exists(src_dll):
                return False, log + [f"ملف DLL غير موجود:\n{src_dll}"]
            plugins_dir = self._plugins_dir(game_path)
            dest_dll    = os.path.join(plugins_dir, dll_name)
            try:
                os.makedirs(plugins_dir, exist_ok=True)
                shutil.copy2(src_dll, dest_dll)
                log.append(f"✓ نُسخ {dll_name} → BepInEx/plugins/")
            except Exception as e:
                return False, log + [f"خطأ في نسخ DLL: {e}"]

        # 2.5 نسخ أي DLLs إضافية من mods/<GameName>/ (plugins خاصة باللعبة)
        # مثلاً FlotsamArabicRuntime.dll — يُكمّل عمل ArabicFontFixer للعبة معيّنة.
        # يُهمل أي DLL مطابق لـ dll_name (نُسخ سلفاً) أو في مجلد bepinex/ الفرعي.
        game_mod_dir = os.path.join(_MODS_DIR, game_name)
        if os.path.isdir(game_mod_dir):
            plugins_dir = self._plugins_dir(game_path)
            os.makedirs(plugins_dir, exist_ok=True)
            extra_copied = []
            try:
                for fname in os.listdir(game_mod_dir):
                    if not fname.lower().endswith(".dll"):
                        continue
                    if dll_name and fname == dll_name:
                        continue   # سبق نسخه أعلاه
                    src = os.path.join(game_mod_dir, fname)
                    if not os.path.isfile(src):
                        continue
                    dest = os.path.join(plugins_dir, fname)
                    shutil.copy2(src, dest)
                    extra_copied.append(fname)
            except Exception as e:
                log.append(f"⚠ خطأ في نسخ plugins إضافية: {e}")
            if extra_copied:
                log.append(
                    f"✓ نُسخ {len(extra_copied)} plugin إضافي للعبة: "
                    f"{', '.join(extra_copied)}"
                )

        # 3. ملف الترجمات
        if is_xunity_mode:
            # وضع XUnity: صدِّر translations.txt للـ ArabicFontFixer static hook
            ok, msg, count = self.export_static_translations_txt(game_cfg, game_path, cache)
            if ok:
                log.append(f"✓ {count:,} ترجمة → BepInEx/config/ArabicGameTranslator/translations.txt")
            else:
                log.append(f"⚠ الترجمات: {msg}")
        else:
            # وضع Method 1: صدِّر JSON للـ plugin المخصص
            ok, msg, count = self.export_translations(game_cfg, game_path, cache)
            if ok:
                log.append(f"✓ {count:,} ترجمة → BepInEx/config/ArabicGameTranslator/")
            else:
                log.append(f"⚠ الترجمات: {msg}")

        return True, log

    # ── إلغاء التثبيت ────────────────────────────────────────────────────────

    def uninstall(
        self, game_cfg: dict, game_path: str
    ) -> Tuple[bool, List[str]]:
        """
        Method 1 (dll_name موجود): يحذف DLL + JSON فقط، يُبقي BepInEx الأساسي.
        Method 2 (XUnity، بدون dll_name): يحذف BepInEx كاملاً من مجلد اللعبة.
        """
        bm        = game_cfg.get("bepinex_mod", {})
        dll_name  = bm.get("dll_name", "")
        json_name = bm.get("translations_json", "")
        log: List[str] = []
        ok = True

        if not game_path:
            return False, ["مسار اللعبة غير محدد"]

        is_xunity_mode = not dll_name

        if is_xunity_mode:
            # ── Method 2: احذف BepInEx كاملاً ────────────────────────────────
            removed = 0
            for fname in ("winhttp.dll", "doorstop_config.ini", ".doorstop_version"):
                fp = os.path.join(game_path, fname)
                if os.path.exists(fp):
                    try:
                        os.remove(fp)
                        removed += 1
                    except Exception as e:
                        log.append(f"خطأ في حذف {fname}: {e}")
                        ok = False

            bepinex_dir = os.path.join(game_path, "BepInEx")
            if os.path.isdir(bepinex_dir):
                try:
                    shutil.rmtree(bepinex_dir)
                    removed += 1
                    log.append("🗑 حُذف مجلد BepInEx/ بالكامل")
                except Exception as e:
                    log.append(f"خطأ في حذف BepInEx/: {e}")
                    ok = False
            else:
                log.append("تخطي: مجلد BepInEx/ غير موجود")

            if removed > 0 and ok:
                log.append("✓ تم إلغاء تثبيت BepInEx+XUnity بالكامل")
            elif not log:
                log.append("تخطي: لا يوجد BepInEx مثبَّت في مسار اللعبة")
        else:
            # ── Method 1: احذف DLL + JSON فقط ────────────────────────────────
            dest_dll = os.path.join(self._plugins_dir(game_path), dll_name)
            if os.path.exists(dest_dll):
                try:
                    os.remove(dest_dll)
                    log.append(f"🗑 حُذف {dll_name} من BepInEx/plugins/")
                except Exception as e:
                    log.append(f"خطأ في حذف DLL: {e}")
                    ok = False
            else:
                log.append(f"تخطي: {dll_name} غير موجود في plugins/")

            if json_name:
                dest_json = os.path.join(self._config_dir(game_path), json_name)
                if os.path.exists(dest_json):
                    try:
                        os.remove(dest_json)
                        log.append(f"🗑 حُذف {json_name} من config/ArabicGameTranslator/")
                    except Exception as e:
                        log.append(f"خطأ في حذف JSON: {e}")
                        ok = False

        return ok, log

    # ── تحديث الترجمات فقط ───────────────────────────────────────────────────

    def update_translations(
        self, game_cfg: dict, game_path: str, cache, model_filter: str = ""
    ) -> Tuple[bool, List[str]]:
        """يعيد تصدير الترجمات دون المساس بالـ DLL أو BepInEx.

        model_filter:
          - "" = كل الترجمات
          - اسم نموذج = فقط ترجمات هذا النموذج
        """
        bm       = game_cfg.get("bepinex_mod", {})
        dll_name = bm.get("dll_name", "")
        if not dll_name:
            # وضع XUnity/ArabicFontFixer — صدِّر translations.txt
            ok, msg, count = self.export_static_translations_txt(
                game_cfg, game_path, cache, model_filter=model_filter,
            )
            if ok:
                return True, [f"✓ {msg}"]
            return False, [f"✗ {msg}"]
        # وضع Method 1 — صدِّر JSON
        ok, msg, count = self.export_translations(game_cfg, game_path, cache)
        if ok:
            return True, [f"✓ تم تحديث {count:,} ترجمة في BepInEx/config/ArabicGameTranslator/"]
        return False, [f"✗ {msg}"]

    # ── استيراد الترجمات من ملف اللعبة إلى الكاش ───────────────────────────

    def import_translations_from_game(
        self, game_cfg: dict, game_path: str, cache,
        source_path: str = ""
    ) -> Tuple[bool, str, int]:
        """
        يقرأ ملف الترجمات من source_path (أو game_path) ويستورد {English: Arabic} إلى الكاش.
        source_path: مسار بديل (مثلاً نسخة MODED)، يُستخدم game_path افتراضياً.
        """
        bm        = game_cfg.get("bepinex_mod", {})
        json_name = bm.get("translations_json", "")
        i2_rel    = bm.get("i2_source_file", "")
        game_name = game_cfg.get("name", "")
        read_path = source_path or game_path   # مسار قراءة الترجمات

        if not json_name or not read_path or not cache:
            return False, "إعدادات ناقصة أو مسار المصدر غير محدد", 0

        json_path = os.path.join(self._config_dir(read_path), json_name)
        if not os.path.exists(json_path):
            return False, f"ملف الترجمات غير موجود في:\n{json_path}", 0
        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            key_to_ar = {
                e["key"]: e["Arabic"]
                for e in data.get("entries", [])
                if e.get("key") and e.get("Arabic")
            }
        except Exception as e:
            return False, f"خطأ في قراءة ملف الترجمات: {e}", 0

        if not key_to_ar:
            return False, "ملف الترجمات فارغ (لا توجد مدخلات)", 0

        # ── محاولة تحميل I2Languages (اختياري) ───────────────────────────────────
        key_to_en: dict = {}
        if i2_rel:
            i2_path = os.path.join(read_path, i2_rel)
            if not os.path.exists(i2_path) and source_path:
                i2_path = os.path.join(game_path, i2_rel)
            if os.path.exists(i2_path):
                try:
                    with open(i2_path, encoding="utf-8") as f:
                        i2_data = json.load(f)
                    terms = i2_data.get("mSource", {}).get("mTerms", {}).get("Array", [])
                    for t in terms:
                        term_key = t.get("Term", "")
                        langs    = t.get("Languages", {}).get("Array", [])
                        en       = langs[0] if langs and isinstance(langs[0], str) else ""
                        if term_key and en:
                            key_to_en[term_key] = en.strip()
                except Exception as e:
                    pass  # I2Languages اختياري — نكمل بدونه

        count = 0
        for key, ar in key_to_ar.items():
            if not ar:
                continue
            # إذا وُجد I2Languages: key = term_name → نرجع النص الإنجليزي
            # إذا لم يوجد أو key غير موجود فيه: نفترض key = نص إنجليزي مباشرة
            en = key_to_en.get(key, key)
            try:
                cache.put(game_name, en, ar)
                count += 1
            except Exception:
                pass

        if count == 0:
            return False, "لم تُستورد أي ترجمة — تحقق من تنسيق ملف الترجمات", 0
        return True, f"استُورد {count:,} ترجمة إلى الكاش", count

    # ── جمع ملفات BepInEx من اللعبة → mods/ ─────────────────────────────────

    def collect_bepinex_from_game(
        self, game_cfg: dict, game_path: str, source_path: str = ""
    ) -> Tuple[bool, str]:
        """
        يجمع إعداد BepInEx الكامل (core + plugins + configs) من مجلد لعبة مثبّتة.
        source_path: مسار بديل للمصدر (مثلاً نسخة Moded)، يُستخدم game_path افتراضياً.
        يُستثنى من الجمع: plugin اللعبة الخاص + ملفات الترجمة + cache + logs.
        """
        game_name = game_cfg.get("name", "")
        src       = source_path or game_path
        if not src or not game_name:
            return False, "إعدادات ناقصة أو مسار المصدر غير محدد"
        if not self.is_bepinex_installed(src):
            return False, f"لم يُعثر على BepInEx في:\n{src}"

        bm       = game_cfg.get("bepinex_mod", {})
        dll_name = bm.get("dll_name", "")

        # الملفات/المجلدات المستثناة (خاصة باللعبة أو runtime)
        exclude_paths = {
            os.path.join("BepInEx", "cache"),
            os.path.join("BepInEx", "LogOutput.log"),
            os.path.join("BepInEx", "config", "ArabicGameTranslator"),
        }
        if dll_name:
            exclude_paths.add(os.path.join("BepInEx", "plugins", dll_name))

        dest_base = self._bepinex_base_dir(game_name)
        if os.path.exists(dest_base):
            shutil.rmtree(dest_base)
        os.makedirs(dest_base, exist_ok=True)

        total_files = 0
        errors: List[str] = []

        # نسخ ملفات جذر اللعبة (winhttp.dll, doorstop_config.ini, .doorstop_version)
        for f in os.listdir(src):
            full = os.path.join(src, f)
            if not os.path.isfile(full):
                continue
            if f.lower() in ("winhttp.dll", "doorstop_config.ini", ".doorstop_version",
                             "changelog.txt"):
                try:
                    shutil.copy2(full, os.path.join(dest_base, f))
                    total_files += 1
                except Exception as e:
                    errors.append(f"{f}: {e}")

        # نسخ مجلد BepInEx/ كاملاً مع استثناء ما يجب استثناؤه
        bepinex_src = os.path.join(src, "BepInEx")
        if os.path.isdir(bepinex_src):
            for root, dirs, files in os.walk(bepinex_src):
                rel_to_src = os.path.relpath(root, src)

                # تحقق من الاستثناءات
                skip = False
                for excl in exclude_paths:
                    if rel_to_src == excl or rel_to_src.startswith(excl + os.sep):
                        skip = True
                        break
                if skip:
                    dirs.clear()
                    continue

                dest_dir = os.path.join(dest_base, rel_to_src)
                os.makedirs(dest_dir, exist_ok=True)

                for f in files:
                    src_f  = os.path.join(root, f)
                    rel_f  = os.path.join(rel_to_src, f)
                    # استثناء plugin اللعبة بالاسم
                    if any(rel_f == excl or rel_f.startswith(excl + os.sep)
                           for excl in exclude_paths):
                        continue
                    try:
                        shutil.copy2(src_f, os.path.join(dest_dir, f))
                        total_files += 1
                    except Exception as e:
                        errors.append(f"{rel_f}: {e}")

        if total_files == 0:
            return False, "لم تُنسخ أي ملفات\n" + "\n".join(errors)

        src_label = os.path.basename(src.rstrip("/\\"))
        msg = f"تم جمع {total_files} ملف من «{src_label}» → mods/{game_name}/bepinex/"
        if errors:
            msg += f"\n⚠ أخطاء ({len(errors)}):\n" + "\n".join(f"  • {e}" for e in errors[:5])
        return True, msg

    # ── نسخ DLL من اللعبة → mods/ ────────────────────────────────────────────

    def copy_dll_from_game(
        self, game_cfg: dict, game_path: str
    ) -> Tuple[bool, str]:
        """ينسخ DLL المثبَّت في BepInEx/plugins/ إلى mods/<GameName>/"""
        bm        = game_cfg.get("bepinex_mod", {})
        dll_name  = bm.get("dll_name", "")
        game_name = game_cfg.get("name", "")

        if not dll_name or not game_path:
            return False, "إعدادات ناقصة أو مسار اللعبة غير محدد"

        src = os.path.join(self._plugins_dir(game_path), dll_name)
        if not os.path.exists(src):
            return False, f"لم يُعثر على {dll_name} في BepInEx/plugins/"

        dest     = self.get_dll_src(game_name, dll_name)
        dest_dir = os.path.dirname(dest)
        try:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(src, dest)
            return True, f"نُسخ {dll_name} → mods/{game_name}/"
        except Exception as e:
            return False, f"خطأ في النسخ: {e}"
