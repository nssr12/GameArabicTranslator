"""
games/manorlords_mod.py — تعريب Manor Lords عبر مود DataTable (.pak).

النهج (مُثبَت):
  اللعبة تخزّن النصوص في DataTables فيها عمود لكل لغة (en_US, de_DE, …) بلا عربي.
  نكتب العربي **مكان عمود en_US** → نعيد بناء uasset → نحزمه في .pak (repak V11).
  UE5 يشكّل ويعكس BiDi أصلاً، وخط اللعبة فيه عربي → بلا تعديل خط/RTL.

⚠ Manor Lords (UE5.5) يقبل **pak version 11** فقط. نستخدم repak --version V11
   (UnrealPak من UE5.7 ينتج v12 → كراش).

الواجهة (مثل FoundationMod):
  get_install_status / build / install / update_translations / uninstall / status_counts

البناء **من الكاش فقط** (بلا Ollama) — سريع. الترجمة الدفعية للجداول تتم عبر
tools/manorlords/build_all.py (يملأ الكاش)، ثم هذا الكلاس يطبّق الكاش ويحزم.
"""
from __future__ import annotations
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import List, Optional, Tuple, Callable

_AR = re.compile(r'[؀-ۿ]')   # نطاق العربية — لكشف المصادر التالفة

from engine.ue_rtl_reverse import reverse_for_display
from engine import rtl_overrides

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UAGUI = os.path.join(ROOT, "tools", "UAssetGUI", "UAssetGUI.exe")
REPAK = os.path.join(ROOT, "tools", "repak", "repak.exe")
FORCACHE = os.path.join(ROOT, "mods", "Manor Lords", "for_cache")
HOODED = os.path.join(FORCACHE, "ManorLords", "Content", "Translation", "HoodedHorse")
READY = os.path.join(ROOT, "mods", "Manor Lords", "ready")

PAK_NAME = "zzz_ManorLords_Arabic_P.pak"
USMAP = "ManorLords"
UE_VER = "VER_UE5_5"
GAME = "Manor Lords"          # مفتاح الكاش
SRC_COL = "en_US"             # العمود المصدر الذي نستبدله بالعربي
MOUNT = "../../../"
PAK_VERSION = "V11"
SIDECARS = (".uexp", ".ubulk", ".uptnl")


def _collect(node, col, out):
    if isinstance(node, dict):
        if (node.get("Name") == col and "StrPropertyData" in str(node.get("$type", ""))
                and isinstance(node.get("Value"), str)):
            out.append(node)
        for v in node.values():
            _collect(v, col, out)
    elif isinstance(node, list):
        for v in node:
            _collect(v, col, out)


def _run(cmd) -> bool:
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0


class ManorLordsMod:
    # ── دعم / أدوات ──────────────────────────────────────────────────────
    @staticmethod
    def is_supported(cfg: dict) -> bool:
        return cfg.get("mod_mode") == "datatable_pak"

    @staticmethod
    def tools_exist() -> Tuple[bool, str]:
        miss = [n for n, p in (("UAssetGUI", UAGUI), ("repak", REPAK)) if not os.path.exists(p)]
        if miss:
            return False, "أدوات مفقودة: " + ", ".join(miss)
        if not os.path.isdir(HOODED):
            return False, f"ملفات اللعبة غير مستخرجة في {HOODED}"
        return True, ""

    @staticmethod
    def paks_dir(game_path: str) -> str:
        return os.path.join(game_path, "ManorLords", "Content", "Paks")

    @staticmethod
    def installed_pak(game_path: str) -> str:
        return os.path.join(ManorLordsMod.paks_dir(game_path), PAK_NAME)

    def get_install_status(self, cfg: dict, game_path: str) -> Optional[bool]:
        if not game_path or not os.path.isdir(game_path):
            return None
        return os.path.exists(self.installed_pak(game_path))

    # ── جرد الجداول ──────────────────────────────────────────────────────
    @staticmethod
    def list_tables(include_combined: bool = False) -> List[str]:
        t = sorted(glob.glob(os.path.join(HOODED, "DT_Translation_*.uasset")))
        if include_combined:
            t += sorted(glob.glob(os.path.join(HOODED, "CombinedDataTables", "*.uasset")))
        return [x for x in t if not x.endswith(".orig")]

    @staticmethod
    def _english_src(uasset: str) -> str:
        """يرجّح النسخة الإنجليزية الأصلية (.orig) لو موجودة."""
        return uasset + ".orig" if os.path.exists(uasset + ".orig") else uasset

    def status_counts(self, cache, include_combined: bool = False) -> dict:
        """إحصاء: عدد الجداول + نصوص مترجمة/كلية (من الكاش) — للعرض."""
        tables = self.list_tables(include_combined)
        total = translated = 0
        for ua in tables:
            jp = os.path.splitext(ua)[0] + ".json"
            src = self._english_src(ua)
            if not os.path.exists(jp) or os.path.getmtime(src) > os.path.getmtime(jp):
                if not _run([UAGUI, "tojson", src, jp, UE_VER, USMAP]):
                    continue
            try:
                data = json.load(open(jp, encoding="utf-8"))
            except Exception:
                continue
            objs: list = []
            _collect(data, SRC_COL, objs)
            uniq = {o["Value"] for o in objs if o["Value"].strip()}
            total += len(uniq)
            translated += sum(1 for en in uniq if cache.get_best(GAME, en))
        return {"tables": len(tables), "total": total, "translated": translated}

    # ── البناء (كاش → uassets مترجمة → pak) ──────────────────────────────
    def build(self, cache, log: Optional[List[str]] = None,
              progress_cb: Optional[Callable[[int, int, str], None]] = None,
              include_combined: bool = False) -> Tuple[bool, str]:
        log = log if log is not None else []
        ok, msg = self.tools_exist()
        if not ok:
            log.append("❌ " + msg)
            return False, ""
        tables = self.list_tables(include_combined)
        if not tables:
            log.append("❌ لا توجد جداول DT_Translation_*")
            return False, ""

        rtl_marked = rtl_overrides.load(GAME)        # نصوص مُعلَّمة للعكس
        rtl_tables = rtl_overrides.load_tables(GAME)  # جداول كاملة للعكس (الموسوعة)
        if rtl_marked or rtl_tables:
            log.append(f"🔁 عكس RTL: {len(rtl_marked)} نص + {len(rtl_tables)} جدول كامل")
        # work = مجلّد عمل (أزواج المصدر الإنجليزي + JSON) — لا يُحزَم.
        # stage = يحوي فقط الـ uassets المترجمة — هو ما يحزمه repak.
        work = tempfile.mkdtemp(prefix="mlwork_")
        stage = tempfile.mkdtemp(prefix="mlmod_")
        applied_total = 0
        try:
            for i, ua in enumerate(tables, 1):
                name = os.path.basename(ua)            # DT_X.uasset
                table_stem = os.path.splitext(name)[0]  # DT_X
                reverse_whole_table = table_stem in rtl_tables
                if progress_cb:
                    progress_cb(i, len(tables), name)
                # ⚠ المصدر دائماً النسخة الإنجليزية. UAssetGUI يحتاج زوج .uasset+.uexp
                # بأسماء صحيحة، لذا ننسخ .orig (لو وُجد) لأسماء صحيحة في work قبل tojson.
                jp = os.path.join(work, name + ".json")
                if not self._tojson_english(ua, work, name, jp, log):
                    continue
                try:
                    data = json.load(open(jp, encoding="utf-8"))
                except Exception as e:
                    log.append(f"  ✗ قراءة JSON فشلت: {name} ({e})")
                    continue
                objs: list = []
                _collect(data, SRC_COL, objs)
                # طبّق الكاش (المصدر إنجليزي؛ نتجاهل أي قيمة عربية احتياطاً)
                applied = 0
                for o in objs:
                    en = o["Value"]
                    if not en.strip() or _AR.search(en):
                        continue
                    ar = cache.get_best(GAME, en)
                    if ar:
                        # عكس RTL: لجدول كامل مُعلَّم (الموسوعة) أو لنص مُعلَّم بعينه
                        if reverse_whole_table or en in rtl_marked:
                            ar = reverse_for_display(ar)
                        o["Value"] = ar
                        applied += 1
                applied_total += applied
                # اكتب uasset مترجم في stage بالمسار النسبي الصحيح
                rel = os.path.relpath(ua, FORCACHE).replace("\\", "/")
                dst = os.path.join(stage, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                bj = os.path.join(work, name + ".build.json")
                json.dump(data, open(bj, "w", encoding="utf-8"), ensure_ascii=False)
                if not _run([UAGUI, "fromjson", bj, dst, USMAP]):
                    log.append(f"  ✗ fromjson فشل: {name}")
                    continue

            # احزم stage
            os.makedirs(READY, exist_ok=True)
            out_pak = os.path.join(READY, PAK_NAME)
            if os.path.exists(out_pak):
                os.remove(out_pak)
            cmd = [REPAK, "pack", "--version", PAK_VERSION, "--mount-point", MOUNT, stage, out_pak]
            if not _run(cmd) or not os.path.exists(out_pak):
                log.append("❌ فشل حزم repak")
                return False, ""
            log.append(f"✅ بُني المود: {applied_total} نص مترجَم في {len(tables)} جدول")
            log.append(f"   {out_pak}  ({os.path.getsize(out_pak)//1024} KB)")
            return True, out_pak
        finally:
            shutil.rmtree(stage, ignore_errors=True)
            shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def _tojson_english(ua: str, work: str, name: str, jp: str, log: list) -> bool:
        """يولّد JSON من النسخة الإنجليزية. لو وُجد .orig ننسخ زوج (uasset+uexp)
        بأسماء صحيحة في work (UAssetGUI لا يقرأ امتداد .orig)، وإلا نستخدم ua مباشرة."""
        stem = os.path.splitext(ua)[0]              # …/DT_X
        if os.path.exists(ua + ".orig"):
            src = os.path.join(work, name)          # work/DT_X.uasset
            shutil.copy2(ua + ".orig", src)
            uexp_orig = stem + ".uexp.orig"
            if os.path.exists(uexp_orig):
                shutil.copy2(uexp_orig, os.path.splitext(src)[0] + ".uexp")
        else:
            src = ua                                # ua نفسه إنجليزي (لم يُترجَم)
        if not _run([UAGUI, "tojson", src, jp, UE_VER, USMAP]) or not os.path.exists(jp):
            log.append(f"  ✗ tojson فشل: {name}")
            return False
        return True

    # ── تثبيت / تحديث / إلغاء ────────────────────────────────────────────
    def install(self, cfg: dict, game_path: str, cache,
                log: Optional[List[str]] = None,
                progress_cb=None, include_combined: bool = False) -> Tuple[bool, List[str]]:
        log = log if log is not None else []
        if not game_path or not os.path.isdir(game_path):
            log.append("❌ مسار اللعبة غير صحيح")
            return False, log
        ok, pak = self.build(cache, log, progress_cb, include_combined)
        if not ok:
            return False, log
        paks = self.paks_dir(game_path)
        if not os.path.isdir(paks):
            log.append(f"❌ مجلّد Paks غير موجود: {paks}")
            return False, log
        dst = self.installed_pak(game_path)
        shutil.copy2(pak, dst)
        log.append(f"📥 ثُبّت في: {dst}")
        log.append("🎮 شغّل اللعبة عبر Steam — كل النصوص عربية")
        return True, log

    def update_translations(self, cfg: dict, game_path: str, cache,
                            log: Optional[List[str]] = None,
                            progress_cb=None, include_combined: bool = False) -> Tuple[bool, List[str]]:
        # نفس install (يعيد البناء من الكاش الحالي بعد تعديلات المستخدم)
        return self.install(cfg, game_path, cache, log, progress_cb, include_combined)

    def uninstall(self, cfg: dict, game_path: str) -> Tuple[bool, List[str]]:
        log: List[str] = []
        dst = self.installed_pak(game_path)
        if os.path.exists(dst):
            try:
                os.remove(dst)
                log.append(f"🗑️ أُزيل المود: {dst}")
            except OSError as e:
                log.append(f"❌ تعذّر الحذف: {e}")
                return False, log
        else:
            log.append("○ المود غير مثبّت أصلاً")
        log.append("✅ عادت اللعبة للإنجليزية — أعد تشغيلها")
        return True, log
