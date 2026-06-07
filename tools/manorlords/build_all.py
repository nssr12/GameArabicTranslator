"""
tools/manorlords/build_all.py — بناء مود Manor Lords العربي الكامل (كل جداول الترجمة).

لكل DT_Translation_*.uasset في HoodedHorse:
  1) tojson  (UAssetGUI + usmap، VER_UE5_5)   — يتخطّى لو .json أحدث من .uasset
  2) ترجمة عمود en_US (كاش + Ollama، حماية تاقات)  → يكتب العربي مكان en_US
  3) fromjson → uasset مترجم (يحفظ .orig مرّة واحدة)
ثم يحزم كل الجداول المترجمة في مود .pak واحد (repak V11) ويثبّته.

يحمّل المحرّك مرّة واحدة. الكاش (Manor Lords.db) يُعاد استخدامه عبر الجداول.

الاستخدام:
  python tools/manorlords/build_all.py [--tables-dir DIR] [--include-combined]
         [--no-engine] [--pack-only] [--name zzz_ManorLords_Arabic] [--install]
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import subprocess
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

UAGUI = os.path.join(_ROOT, "tools", "UAssetGUI", "UAssetGUI.exe")
USMAP = "ManorLords"
UE_VER = "VER_UE5_5"
HOODED = os.path.join(_ROOT, "mods", "Manor Lords", "for_cache",
                      "ManorLords", "Content", "Translation", "HoodedHorse")
SRC_COL = "en_US"
GAME = "Manor Lords"


def collect_values(node, col, out):
    if isinstance(node, dict):
        if (node.get("Name") == col and "StrPropertyData" in str(node.get("$type", ""))
                and isinstance(node.get("Value"), str)):
            out.append(node)
        for v in node.values():
            collect_values(v, col, out)
    elif isinstance(node, list):
        for v in node:
            collect_values(v, col, out)


def tojson(uasset, jsonp):
    r = subprocess.run([UAGUI, "tojson", uasset, jsonp, UE_VER, USMAP],
                       capture_output=True, text=True)
    return r.returncode == 0 and os.path.exists(jsonp)


def fromjson(jsonp, uasset):
    r = subprocess.run([UAGUI, "fromjson", jsonp, uasset, USMAP],
                       capture_output=True, text=True)
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables-dir", default=HOODED)
    ap.add_argument("--include-combined", action="store_true",
                    help="ضمّ CombinedDataTables/CDT_* أيضاً")
    ap.add_argument("--no-engine", action="store_true")
    ap.add_argument("--pack-only", action="store_true", help="تخطّى الترجمة، احزم الموجود فقط")
    ap.add_argument("--name", default="zzz_ManorLords_Arabic")
    ap.add_argument("--install", action="store_true")
    args = ap.parse_args()

    tables = sorted(glob.glob(os.path.join(args.tables_dir, "DT_Translation_*.uasset")))
    if args.include_combined:
        tables += sorted(glob.glob(os.path.join(args.tables_dir, "CombinedDataTables", "*.uasset")))
    # استبعد ملفات .orig
    tables = [t for t in tables if not t.endswith(".orig")]
    print(f"📋 {len(tables)} جدول")

    # ── المحرّك + الكاش (مرّة واحدة) ──
    cache = ft = None
    active_model = "cache"
    if not args.pack_only:
        from engine.cache import TranslationCache
        cache = TranslationCache()
        if not args.no_engine:
            from engine.translator import TranslationEngine
            from engine.filtered_translator import FilteredTranslator, get_global_tag_mode
            engine = TranslationEngine(os.path.join(_ROOT, "config.json"))
            engine.set_active_model("ollama")
            engine.load_active_model()
            tr = engine.get_translator("ollama")
            active_model = getattr(tr, "model", "ollama") or "ollama"
            ft = FilteredTranslator(engine, tag_mode=get_global_tag_mode())
            print(f"🤖 {active_model} | tag_mode={ft.tag_mode}")

    translated_assets = []
    g_hits = g_new = g_fail = 0
    t_start = time.time()

    for ti, uasset in enumerate(tables, 1):
        name = os.path.basename(uasset)
        jsonp = os.path.splitext(uasset)[0] + ".json"

        if not args.pack_only:
            # 1) tojson (لو لزم)
            if not os.path.exists(jsonp) or os.path.getmtime(uasset) > os.path.getmtime(jsonp):
                if not tojson(uasset, jsonp):
                    print(f"  ✗ tojson فشل: {name}"); continue
            with open(jsonp, encoding="utf-8") as f:
                data = json.load(f)
            objs = []
            collect_values(data, SRC_COL, objs)
            uniq = list({o["Value"] for o in objs if o["Value"].strip()})

            # 2) ترجمة
            mapping = {}
            h = n = fl = 0
            for en in uniq:
                ar = cache.get_best(GAME, en)
                if ar:
                    h += 1
                elif ft is not None:
                    ar, mode = ft.translate_with_info(en)
                    if ar:
                        cache.put(GAME, en, ar, model=active_model, mode_used=mode); n += 1
                    else:
                        fl += 1
                if ar:
                    mapping[en] = ar
            g_hits += h; g_new += n; g_fail += fl

            # اكتب العربي + fromjson
            for o in objs:
                if o["Value"] in mapping:
                    o["Value"] = mapping[o["Value"]]
            arp = os.path.splitext(uasset)[0] + "_ar.json"
            with open(arp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # backup أصلي مرّة واحدة
            if not os.path.exists(uasset + ".orig"):
                import shutil
                shutil.copy2(uasset, uasset + ".orig")
                ux = os.path.splitext(uasset)[0] + ".uexp"
                if os.path.exists(ux): shutil.copy2(ux, ux + ".orig")
            if not fromjson(arp, uasset):
                print(f"  ✗ fromjson فشل: {name}"); continue

            el = time.time() - t_start
            print(f"[{ti}/{len(tables)}] {name:48} كاش={h} جديد={n} فشل={fl} "
                  f"| إجمالي جديد={g_new} | {el/60:.1f}د", flush=True)

        translated_assets.append(uasset)

    print(f"\n✅ الترجمة: كاش={g_hits} جديد={g_new} فشل={g_fail}")

    # ── الحزم ──
    if translated_assets:
        print(f"\n📦 حزم {len(translated_assets)} جدول في مود واحد …")
        cmd = [sys.executable, os.path.join(_ROOT, "tools", "manorlords", "pack_mod.py"),
               "--files"] + translated_assets + ["--name", args.name]
        if args.install:
            cmd.append("--install")
        subprocess.run(cmd)


if __name__ == "__main__":
    main()
