"""
games/iostore_mod.py — مود تعريب ألعاب IoStore (UE5 zen) عبر حزمة ready جاهزة.

النهج (مثل ManorLordsMod لكن لـ IoStore/.utoc بدل .pak خالص):
  for_cache/<Paks_legacy>/**.uasset.json  ← المصدر المستخرَج (UAssetGUI tojson)
     → تطبيق ترجمات الكاش على نصوص DefaultText (من نسخة .orig الإنجليزية)
     → fromjson لكل JSON (UAssetGUI)
     → retoc to-zen (الإصدار من package.json::wizard) → ready/<base>_P.{utoc,ucas,pak}
  التثبيت/الإلغاء عبر TranslationPackage (package.json::files → مجلد اللعبة).

البناء **من الكاش فقط** (بلا استدعاء AI — سريع). idempotent: المصدر دائماً النسخة
الإنجليزية (.orig) فإعادة البناء بعد تعديل الكاش تطبّق نظيفاً بلا تراكم.

الإعدادات تُقرأ من mods/<game>/package.json::wizard:
  ue_version (VER_UE5_6) / zen_version (UE5_6) / extraction_mode (default_text)
  / mappings (اسم usmap بلا امتداد) / game_target_dir (مجلد Paks داخل اللعبة).
مفتاح AES (للحزم المشفّرة) يُقرأ من config اللعبة (aes_key).
"""
from __future__ import annotations
import os
import shutil
from typing import Callable, List, Optional, Tuple

from games.translation_package import TranslationPackage
from games.iostore.translator import IoStoreTranslator


class IoStoreMod:
    """تعريب لعبة IoStore عبر مود ready (.pak/.ucas/.utoc) مبنيّ من الكاش."""

    def __init__(self):
        self._pkg = TranslationPackage()

    # ── دعم/أدوات ──────────────────────────────────────────────────────────
    @staticmethod
    def is_supported(cfg: dict) -> bool:
        """يُظهَر للألعاب التي فُعِّل لها قسم IoStore (UE4/UE5)."""
        cfg = cfg or {}
        eng = (cfg.get("engine", "") or "").lower()
        shown = cfg.get("shown_features") or []
        is_ue = any(k in eng for k in ("ue4", "ue5", "unreal"))
        return ("iostore_section" in shown) and is_ue

    def tools_exist(self, game_id: str = "") -> Tuple[bool, str]:
        """يفحص الأدوات المطلوبة حسب نوع بناء اللعبة:
        zen → retoc + UAssetGUI ، locres_pak → repak + UE4LocalizationsTool."""
        bt = "zen"
        if game_id:
            legacy = self._pkg.get_legacy_in_cache(game_id)
            wiz = self._pkg.get_wizard_config(game_id)
            if legacy:
                bt = self._detect_build_type(wiz, legacy)
        miss = []
        if bt == "locres_pak":
            from games.tools_paths import repak as _repak_fn
            _REPAK = _repak_fn()
            if not os.path.exists(_REPAK):
                miss.append("repak.exe")
            if not (self._ue4loc_tool() and os.path.isfile(self._ue4loc_tool())):
                miss.append("UE4LocalizationsTool.exe")
        else:
            t = IoStoreTranslator()
            if not os.path.exists(t.retoc_path):
                miss.append("retoc.exe")
            if not os.path.exists(t.uassetgui_path):
                miss.append("UAssetGUI.exe")
        if miss:
            return False, ("أدوات مفقودة: " + "، ".join(miss)
                           + " — اضبط مساراتها في لوحة الأدمن ⚙️ → الأدوات.")
        return True, ""

    # ── نوع البناء ──────────────────────────────────────────────────────────
    @staticmethod
    def _detect_build_type(wiz: dict, legacy: str) -> str:
        """zen (uasset.json → retoc to-zen) أو locres_pak (locres → repak)."""
        bt = (wiz.get("build_type", "") or "").strip()
        if bt:
            return bt
        has_json = has_locres = False
        for _root, _dirs, files in os.walk(legacy):
            for f in files:
                fl = f.lower()
                if fl.endswith(".uasset.json"):
                    has_json = True
                elif fl.endswith(".locres") and not fl.endswith(".locres.txt"):
                    has_locres = True
        if has_json:
            return "zen"
        if has_locres:
            return "locres_pak"
        return "zen"

    # ── حالة ──────────────────────────────────────────────────────────────
    def has_source(self, game_id: str) -> bool:
        """هل يوجد مصدر for_cache (.uasset.json أو .locres) للبناء منه؟"""
        legacy = self._pkg.get_legacy_in_cache(game_id)
        if not legacy or not os.path.isdir(legacy):
            return False
        for _root, _dirs, files in os.walk(legacy):
            for f in files:
                fl = f.lower()
                if fl.endswith(".uasset.json"):
                    return True
                if fl.endswith(".locres") and not fl.endswith(".locres.txt"):
                    return True
        return False

    def has_ready(self, game_id: str) -> bool:
        return self._pkg.has_files(game_id)

    def get_install_status(self, game_id: str, game_path: str) -> Optional[bool]:
        return self._pkg.get_status(game_id, game_path)

    # ── البناء من الكاش ────────────────────────────────────────────────────
    @staticmethod
    def _make_lookup(cache, game_name: str, model_filter: str = ""):
        """يُرجع دالة بحث عن ترجمة. لو حُدِّد model_filter (مودل/مصدر مستورَد)،
        نُفضّل ترجمته ثم نقع على get_best للنصوص الناقصة (لضمان التغطية)."""
        model_map = {}
        if model_filter:
            try:
                model_map = cache.get_by_model(game_name, model_filter) or {}
            except Exception:
                model_map = {}

        def _lookup(en: str):
            if model_filter and en in model_map:
                v = model_map[en]
                if v and v != en:
                    return v
            return cache.get_best(game_name, en)
        return _lookup, len(model_map)

    def build(self, game_id: str, cfg: dict, cache,
              log: Optional[List[str]] = None,
              progress_cb: Optional[Callable[[int, int, str], None]] = None,
              model_filter: str = ""
              ) -> Tuple[bool, List[str]]:
        """يعيد بناء ملفات ready/ من ترجمات الكاش. لا يثبّت.
        model_filter: مودل/مصدر مستورَد محدّد للبناء منه (فارغ = أفضل دمج get_best)."""
        log = log if log is not None else []

        def _log(m: str):
            log.append(m)

        wiz = self._pkg.get_wizard_config(game_id)
        ue_ver   = wiz.get("ue_version", "VER_UE5_6")
        zen_ver  = wiz.get("zen_version", "") or ue_ver.replace("VER_", "")
        mode     = wiz.get("extraction_mode", "default_text")
        mappings = (wiz.get("mappings", "") or "").strip()
        aes      = (cfg.get("aes_key", "") or "").strip()
        game_name = cfg.get("name", game_id) or game_id

        legacy = self._pkg.get_legacy_in_cache(game_id)
        if not legacy or not os.path.isdir(legacy):
            _log("✗ لا يوجد مصدر for_cache — استخرج اللعبة عبر معالج IoStore أولاً.")
            return False, log

        # لقطة للنسخة الحالية قبل الكتابة فوقها (تتيح «↩ تراجع»)
        if self._pkg.snapshot_ready(game_id):
            _log("📸 حُفظت لقطة النسخة السابقة (للتراجع).")

        lookup, mf_count = self._make_lookup(cache, game_name, model_filter)
        if model_filter:
            _log(f"🎯 البناء من المصدر: {model_filter} ({mf_count} نص) + get_best للناقص.")

        # نوع البناء: zen (uasset → retoc) أو locres_pak (locres → repak)
        if self._detect_build_type(wiz, legacy) == "locres_pak":
            return self._build_locres_pak(game_id, cfg, cache, legacy, wiz, log,
                                          progress_cb, lookup)

        tr = IoStoreTranslator()
        tr.set_callbacks(log=_log)

        # 1) اجمع كل ملفات JSON
        json_files: List[str] = []
        for root, _dirs, files in os.walk(legacy):
            for f in files:
                if f.endswith(".uasset.json"):
                    json_files.append(os.path.join(root, f))
        total = len(json_files)
        if total == 0:
            _log("✗ لا توجد ملفات .uasset.json في for_cache.")
            return False, log

        applied = 0
        hit_total = 0
        for i, jp in enumerate(json_files):
            if progress_cb:
                progress_cb(i, total, os.path.basename(jp))
            orig = jp + ".orig"
            # المصدر دائماً النسخة الإنجليزية: .orig إن وُجدت، وإلا الملف الحالي (إنجليزي أوّل مرّة)
            src = orig if os.path.exists(orig) else jp
            try:
                texts = tr.extract_texts_from_json(src, mode)
            except Exception as e:
                _log(f"  تخطّي {os.path.basename(jp)}: {e}")
                continue
            if not texts:
                continue
            translations = {}
            for en in texts:
                ar = lookup(en)
                if ar and ar != en:
                    translations[en] = ar
            if not translations:
                continue
            # احفظ النسخة الإنجليزية المرجعية مرّة واحدة قبل الكتابة
            if not os.path.exists(orig):
                try:
                    shutil.copy2(jp, orig)
                except Exception:
                    pass
            tr.apply_translations_to_json(jp, translations, mode, source_path=src)
            applied += 1
            hit_total += len(translations)

        _log(f"✓ طُبّقت ترجمات الكاش على {applied}/{total} ملف ({hit_total} نص).")
        if applied == 0:
            _log("⚠ لا توجد ترجمات في الكاش لهذه اللعبة — لن يتغيّر المود.")

        # 2) JSON → uasset
        if progress_cb:
            progress_cb(total, total, "JSON → uasset")
        cnt = tr.json_folder_to_uasset(legacy, ue_ver, mappings)
        _log(f"✓ fromjson: {cnt} ملف.")

        # 3) to-zen → ready/
        ready_dir = self._pkg.get_ready_dir(game_id)
        os.makedirs(ready_dir, exist_ok=True)
        base_name = os.path.basename(legacy.rstrip("/\\")) or "Paks"
        out_base = os.path.join(ready_dir, base_name)   # ready/Paks_legacy
        if progress_cb:
            progress_cb(total, total, "retoc to-zen (حزم)…")
        if not tr.to_zen(legacy, out_base, zen_ver, aes):
            _log("✗ فشل retoc to-zen.")
            return False, log

        # 4) سجّل ملفات ready في package.json إن لم تكن مسجَّلة (للألعاب الجديدة)
        if not self._pkg.has_files(game_id):
            gtd = (wiz.get("game_target_dir", "") or "").strip()
            for ext in (".pak", ".ucas", ".utoc"):
                fname = base_name + "_P" + ext
                if os.path.exists(os.path.join(ready_dir, fname)):
                    target = (gtd.rstrip("/\\") + "/" + fname) if gtd else fname
                    self._pkg.register_file(game_id, fname, target)

        _log("✓ اكتمل بناء المود في ready/.")
        return True, log

    @staticmethod
    def _tool_import(tool: str, txt_path: str, log_cb) -> bool:
        """UE4LocalizationsTool -import <Game.locres.txt> → يحدّث <Game.locres> الموجود.
        (نفس استدعاء معالج .locres المُثبت: العَلَم "-import" + cwd=مجلد الملف)."""
        import subprocess
        out_path = txt_path[:-4] if txt_path.lower().endswith(".txt") else txt_path
        if not os.path.isfile(out_path):
            log_cb(f"  ✗ الملف الهدف غير موجود: {os.path.basename(out_path)}")
            return False
        workdir = os.path.dirname(txt_path) or "."
        cmd = [tool, "-import", txt_path]
        log_cb("  CMD: " + " ".join(cmd))
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=180, cwd=workdir)
        except Exception as e:
            log_cb(f"  ✗ استثناء الأداة: {e}")
            return False
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if out:
            for line in out.splitlines()[:4]:
                log_cb("    " + line)
        if r.returncode != 0:
            return False
        # تأكّد أن الأداة حدّثت الملف فعلاً (mtime حديث)
        return os.path.isfile(out_path)

    @staticmethod
    def _ue4loc_tool() -> str:
        """مسار UE4LocalizationsTool (config → حزمة مُغلَّفة → tools/ المشروع)."""
        try:
            from games import tools_paths
            return tools_paths.ue4loc()
        except Exception:
            return ""

    # ── بناء locres_pak (Windrose: ترجمة .locres.txt من الكاش + compile + repak) ──
    # ملاحظة: الـ reader الثنائي لا يقرأ صيغة locres الخاصة بـ Windrose → نستخدم مسار
    # النصّ (.locres.txt) + UE4LocalizationsTool import (نفس آلية معالج locres المُثبت).
    def _build_locres_pak(self, game_id, cfg, cache, legacy, wiz,
                          log, progress_cb, lookup=None) -> Tuple[bool, List[str]]:
        import subprocess
        from games.locres_patcher import LocresTxtFile
        if lookup is None:
            _gn = cfg.get("name", game_id) or game_id
            lookup = lambda en: cache.get_best(_gn, en)

        def _log(m: str):
            log.append(m)

        game_name   = cfg.get("name", game_id) or game_id
        pak_version = (wiz.get("pak_version", "") or "V3").strip()
        mount       = (wiz.get("mount_point", "") or "../../../").strip()
        pack_subdir = (wiz.get("pack_subdir", "") or "").strip()
        out_name    = (wiz.get("output_pak_name", "") or "").strip()

        tool = self._ue4loc_tool()
        if not tool or not os.path.isfile(tool):
            _log("✗ UE4LocalizationsTool غير مضبوط — حدّد مساره في لوحة الأدمن ⚙️ → الأدوات.")
            return False, log

        # 1) لكل .locres ثنائي له .txt مجاور: ترجم الـ txt من الكاش ثم compile
        targets = []
        for root, _dirs, files in os.walk(legacy):
            for f in files:
                fl = f.lower()
                if fl.endswith(".locres") and not fl.endswith(".locres.txt"):
                    lp = os.path.join(root, f)
                    if os.path.exists(lp + ".txt"):
                        targets.append(lp)
        targets.sort()
        if not targets:
            _log("✗ لا توجد ملفات .locres.txt في for_cache — استخرجها عبر معالج .locres أولاً.")
            return False, log

        total = len(targets)
        applied = hit_total = 0
        for i, lp in enumerate(targets):
            if progress_cb:
                progress_cb(i, total, os.path.basename(lp))
            txt = lp + ".txt"
            bak = txt + ".bak"
            # المصدر الإنجليزي: .txt.bak إن وُجد، وإلا الـ .txt الحالي (إنجليزي أوّل مرّة)
            en_src = bak if os.path.exists(bak) else txt
            try:
                entries = LocresTxtFile.read(en_src)
            except Exception as e:
                _log(f"  تخطّي {os.path.basename(lp)}: {e}")
                continue
            english = []
            seen = set()
            for e in entries:
                v = (e.value or "").strip()
                if v and v not in seen:
                    seen.add(v)
                    english.append(v)
            if not english:
                continue
            translations = {}
            for en in english:
                ar = lookup(en)
                if ar and ar != en:
                    translations[en] = ar
            if not translations:
                continue
            # تأكّد من نسخة .txt.bak الإنجليزية قبل الكتابة
            if not os.path.exists(bak):
                try:
                    shutil.copy2(txt, bak)
                except Exception:
                    pass
            try:
                rep, _tot = LocresTxtFile.patch(en_src, txt, translations)
            except Exception as e:
                _log(f"  فشل patch {os.path.basename(txt)}: {e}")
                continue
            # compile: .locres.txt → .locres عبر UE4LocalizationsTool -import
            # ⚠ الصيغة الصحيحة: العَلَم "-import" (بشَرطة) + cwd=مجلد الملف، والأداة
            # تقرأ .locres الموجود وتحدّث قيمه من الـ txt (لذا يجب أن يكون .locres موجوداً).
            ok = self._tool_import(tool, txt, _log)
            if not ok:
                _log(f"  ✗ فشل compile {os.path.basename(txt)}")
                continue
            applied += 1
            hit_total += rep
        _log(f"✓ تُرجم وجُمِّع {applied}/{total} ملف .locres من الكاش ({hit_total} نص).")
        if applied == 0:
            _log("⚠ لا توجد ترجمات في الكاش لهذه اللعبة — لن يتغيّر المود.")

        # نظّف ملفات .bak.bak الزائدة (تنتج حين يكون المصدر .bak)
        for root, _dirs, files in os.walk(legacy):
            for f in files:
                if f.lower().endswith(".bak.bak"):
                    try:
                        os.remove(os.path.join(root, f))
                    except Exception:
                        pass

        # 2) repak pack
        from games.tools_paths import repak as _repak_fn
        _REPAK = _repak_fn()
        if not os.path.exists(_REPAK):
            _log("✗ repak.exe غير موجود — اضبط مساره أو ضعه في tools/repak/.")
            return False, log
        pack_input = os.path.join(legacy, pack_subdir) if pack_subdir else legacy
        if not os.path.isdir(pack_input):
            _log(f"✗ مجلد الحزم غير موجود: {pack_input}")
            return False, log

        ready_dir = self._pkg.get_ready_dir(game_id)
        os.makedirs(ready_dir, exist_ok=True)
        if not out_name:
            out_name = (game_id + "_P.pak")
        out_pak = os.path.join(ready_dir, out_name)

        if progress_cb:
            progress_cb(total, total, "repak pack…")
        cmd = [_REPAK, "pack", "--version", pak_version,
               "--mount-point", mount, pack_input, out_pak]
        _log("CMD: " + " ".join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True)
        out = (r.stdout or "") + (r.stderr or "")
        for line in out.splitlines():
            _log("  " + line)
        if r.returncode != 0 or not os.path.exists(out_pak):
            _log("✗ فشل repak pack.")
            return False, log

        # 3) سجّل ملف ready في package.json إن لم يكن مسجَّلاً
        if not self._pkg.has_files(game_id):
            gtd = (wiz.get("game_target_dir", "") or "").strip()
            target = (gtd.rstrip("/\\") + "/" + out_name) if gtd else out_name
            self._pkg.register_file(game_id, out_name, target)

        _log(f"✓ اكتمل بناء المود (locres + repak {pak_version}) → ready/{out_name}.")
        return True, log

    # ── تثبيت / تحديث / إلغاء ───────────────────────────────────────────────
    def install(self, game_id: str, cfg: dict, game_path: str, cache,
                log: Optional[List[str]] = None,
                progress_cb: Optional[Callable[[int, int, str], None]] = None,
                model_filter: str = ""
                ) -> Tuple[bool, List[str]]:
        """يبني من الكاش ثم ينسخ ready/ → مجلد اللعبة.
        إن لم يوجد مصدر for_cache لكن توجد حزمة ready جاهزة → يثبّتها كما هي (بلا بناء)."""
        log = log if log is not None else []
        if self.has_source(game_id):
            ok, log = self.build(game_id, cfg, cache, log=log, progress_cb=progress_cb,
                                 model_filter=model_filter)
            if not ok:
                return False, log
        elif self.has_ready(game_id):
            log.append("ⓘ لا يوجد مصدر for_cache — تثبيت الحزمة الجاهزة في ready/ كما هي.")
        else:
            log.append("✗ لا مصدر for_cache ولا حزمة ready — لا شيء لتثبيته.")
            return False, log
        if not game_path or not os.path.isdir(game_path):
            log.append("✗ مسار اللعبة غير صالح — تعذّر التثبيت.")
            return False, log
        iok, ilog = self._pkg.install(game_id, game_path)
        log.extend(ilog)
        if iok:
            log.append("✓ ثُبِّتت الترجمة في مجلد اللعبة.")
        return iok, log

    def update_translations(self, game_id: str, cfg: dict, game_path: str, cache,
                            log: Optional[List[str]] = None,
                            progress_cb: Optional[Callable[[int, int, str], None]] = None,
                            model_filter: str = ""
                            ) -> Tuple[bool, List[str]]:
        """نفس التثبيت — يعيد البناء من الكاش (بعد تعديله) ثم يُثبّت."""
        return self.install(game_id, cfg, game_path, cache, log=log,
                            progress_cb=progress_cb, model_filter=model_filter)

    def uninstall(self, game_id: str, game_path: str) -> Tuple[bool, List[str]]:
        ok, log = self._pkg.uninstall(game_id, game_path)
        if ok:
            log.append("🗑 أُزيلت ملفات المود من مجلد اللعبة.")
        return ok, log


__all__ = ["IoStoreMod"]
