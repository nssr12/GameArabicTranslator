"""
tools/manorlords/translate_dt.py — ترجمة DataTable واحد من Manor Lords.

Manor Lords يخزّن النصوص في DataTables فيها عمود لكل لغة (en_US, de_DE, …)
— لا يوجد عمود عربي. الحل: نكتب العربي **مكان عمود en_US** (تبقى اللعبة
إنجليزية وتظهر عربي).

التدفّق:
  uasset --(UAssetGUI tojson)--> JSON  [تُعمَل خارج السكربت]
  JSON  --(هذا السكربت)--> JSON مترجم (en_US ← عربي)
  JSON  --(UAssetGUI fromjson)--> uasset  [تُعمَل خارج السكربت]

يُعيد استخدام كاش اللعبة (data/cache/Manor Lords.db) أولاً، ثم Ollama للباقي.
يحمي تاقات RichText عبر FilteredTranslator (tag_mode من config).

الاستخدام:
  python tools/manorlords/translate_dt.py --json PATH.json [--source-col en_US]
         [--shape] [--limit N] [--game "Manor Lords"] [--no-engine]

  --shape     : طبّق تشكيل/عكس RTL (engine/rtl_layout) — افتراضي مُطفأ (نترك UE5
                يشكّل أصلاً؛ نفعّله فقط لو فشل العرض الأصلي).
  --no-engine : كاش فقط (بلا Ollama) — للنصوص غير المترجمة يُبقي الإنجليزي.
  --limit N   : ترجم أوّل N نص فريد فقط (للتجربة السريعة).
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time

# اجعل جذر المشروع قابلاً للاستيراد
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def collect_values(node, col: str, out: list):
    """يجمع كل كائنات StrPropertyData التي اسمها == col (بمرجع للكائن نفسه)."""
    if isinstance(node, dict):
        if (node.get("Name") == col
                and "StrPropertyData" in str(node.get("$type", ""))
                and isinstance(node.get("Value"), str)):
            out.append(node)
        for v in node.values():
            collect_values(v, col, out)
    elif isinstance(node, list):
        for v in node:
            collect_values(v, col, out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True, help="مسار ملف JSON الناتج من UAssetGUI tojson")
    ap.add_argument("--source-col", default="en_US", help="العمود المصدر الذي نستبدله بالعربي")
    ap.add_argument("--game", default="Manor Lords")
    ap.add_argument("--shape", action="store_true", help="طبّق تشكيل/عكس RTL")
    ap.add_argument("--wrap", type=int, default=0, help="حد لفّ الأسطر عند --shape (0=بلا لفّ)")
    ap.add_argument("--no-engine", action="store_true", help="كاش فقط بلا Ollama")
    ap.add_argument("--limit", type=int, default=0, help="ترجم أوّل N نص فريد فقط")
    ap.add_argument("--out", default="", help="ملف الإخراج (افتراضي: نفس الملف)")
    args = ap.parse_args()

    path = args.json
    if not os.path.exists(path):
        print(f"❌ غير موجود: {path}")
        sys.exit(1)

    print(f"📂 تحميل {os.path.basename(path)} …")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    objs: list = []
    collect_values(data, args.source_col, objs)
    # القيم الفريدة غير الفارغة
    uniq = []
    seen = set()
    for o in objs:
        v = o["Value"]
        if v.strip() and v not in seen:
            seen.add(v)
            uniq.append(v)
    print(f"🔎 {len(objs)} خلية في عمود {args.source_col} — {len(uniq)} نص فريد")

    if args.limit:
        uniq = uniq[: args.limit]
        print(f"   (limit: نترجم {len(uniq)} فقط)")

    # ── الكاش ──
    from engine.cache import TranslationCache
    cache = TranslationCache()

    # ── المحرّك (اختياري) ──
    from engine import ue_richtext as ue
    engine = None
    active_model_name = "cache"
    if not args.no_engine:
        from engine.translator import TranslationEngine
        engine = TranslationEngine(os.path.join(_ROOT, "config.json"))
        if not engine.set_active_model("ollama"):
            print("❌ تعذّر تفعيل ollama")
            sys.exit(1)
        engine.load_active_model()
        tr = engine.get_translator("ollama")
        active_model_name = getattr(tr, "model", "ollama") or "ollama"
        print(f"🤖 المحرّك: {active_model_name} | حماية: UE RichText (كل التاقات)")

    # ── RTL (اختياري) ──
    shape_fn = None
    if args.shape:
        from engine.rtl_layout import layout_rtl
        shape_fn = lambda s: layout_rtl(s, max_line_len=args.wrap)
        print(f"🔁 تشكيل RTL مفعّل (wrap={args.wrap})")

    # ⚠ حارس: لا تترجم مصدراً فيه عربي (= الملف مُترجَم مسبقاً → نتجنّب عربي→عربي)
    import re as _re
    _AR = _re.compile(r'[؀-ۿ]')
    ar_src = [en for en in uniq if _AR.search(en)]
    if ar_src:
        print(f"⚠ تخطّي {len(ar_src)} مصدر فيه عربي (الملف مُترجَم؟). "
              f"استخدم النسخة الإنجليزية (.orig).")
        uniq = [en for en in uniq if not _AR.search(en)]

    # ── الترجمة ──
    mapping: dict = {}
    hits = miss = newt = fail = 0
    t0 = time.time()
    for i, en in enumerate(uniq, 1):
        ar = cache.get_best(args.game, en)
        if ar:
            hits += 1
        elif engine is not None:
            ar = ue.translate(en, engine)   # حماية UE RichText الكاملة
            if ar:
                cache.put(args.game, en, ar, model=active_model_name, mode_used="ue_richtext")
                newt += 1
            else:
                fail += 1
        else:
            miss += 1
        if ar:
            mapping[en] = shape_fn(ar) if shape_fn else ar
        if i % 25 == 0 or i == len(uniq):
            dt = time.time() - t0
            rate = i / dt if dt else 0
            eta = (len(uniq) - i) / rate if rate else 0
            print(f"  [{i}/{len(uniq)}] كاش={hits} جديد={newt} فشل={fail} "
                  f"| {rate:.1f}/s ETA {eta/60:.1f}د", flush=True)

    print(f"\n✅ ترجمة جاهزة: {len(mapping)} نص "
          f"(كاش {hits} + جديد {newt} + فشل {fail} + بلا محرّك {miss})")

    # ── كتابة العربي في عمود en_US ──
    applied = 0
    for o in objs:
        v = o["Value"]
        if v in mapping:
            o["Value"] = mapping[v]
            applied += 1
    print(f"✍  كُتب في {applied} خلية")

    out = args.out or path
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"💾 حُفظ: {out}")


if __name__ == "__main__":
    main()
