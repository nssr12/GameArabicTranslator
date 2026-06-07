"""
tools/manorlords/fix_tags.py — إصلاح ترجمات الكاش المكسورة التاقات (Manor Lords).

الفلتر القديم لم يحمِ تاقات UE RichText (`<i>`/`</>`/`<r>`…) فأضاف المودل
`</i>`/`</h>` أو حذف/أعاد ترتيب التاقات → عرض مكسور في اللعبة.

هذه الأداة:
  1) تفحص الكاش عن صفوف تاقات الأصل ≠ تاقات الترجمة.
  2) تُعيد ترجمتها عبر engine.ue_richtext.translate (حماية كل التاقات).
  3) تقبل فقط لو تطابقت التاقات؛ وإلا تُبقي القديمة (لا تُفسد أكثر).

الاستخدام:
  python tools/manorlords/fix_tags.py [--game "Manor Lords"] [--dry-run] [--limit N]
"""
from __future__ import annotations
import argparse
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from engine import ue_richtext as ue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="Manor Lords")
    ap.add_argument("--dry-run", action="store_true", help="فحص فقط بلا تعديل")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    from engine.cache import TranslationCache
    cache = TranslationCache()

    import sqlite3
    db = cache._game_db_path(args.game)
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT original_text, translated_text, model_used FROM translations"
    ).fetchall()
    con.close()

    broken = [(o, t, m) for o, t, m in rows
              if ue.tags_of(o) and not ue.tags_match(o, t)]
    print(f"📋 {len(rows)} صف | مكسورة التاقات: {len(broken)}")
    if args.limit:
        broken = broken[: args.limit]
        print(f"   (limit: {len(broken)})")
    if args.dry_run:
        for o, t, m in broken[:30]:
            print(f"  ✗ {o[:60]!r}\n     {t[:60]!r}")
        return

    # المحرّك
    from engine.translator import TranslationEngine
    engine = TranslationEngine(os.path.join(_ROOT, "config.json"))
    engine.set_active_model("ollama")
    engine.load_active_model()
    tr = engine.get_translator("ollama")
    model = getattr(tr, "model", "ollama") or "ollama"
    print(f"🤖 {model} | حماية UE RichText\n")

    fixed = still = err = 0
    t0 = time.time()
    for i, (o, old, m) in enumerate(broken, 1):
        try:
            new = ue.translate(o, engine)
        except Exception:
            new = None
        if new and ue.tags_match(o, new):
            # احفظ تحت نفس المودل (يحدّث الصف) — أو model النشط لو لا تاقات
            cache.put(args.game, o, new, model=model, mode_used="ue_richtext")
            fixed += 1
        elif new is None:
            still += 1
        else:
            err += 1
        if i % 20 == 0 or i == len(broken):
            dt = time.time() - t0
            rate = i / dt if dt else 0
            eta = (len(broken) - i) / rate if rate else 0
            print(f"  [{i}/{len(broken)}] أُصلح={fixed} بقي مكسور={still} "
                  f"تاق غير مطابق={err} | {rate:.1f}/s ETA {eta/60:.1f}د", flush=True)

    print(f"\n✅ أُصلح {fixed} | تعذّر {still+err} (أُبقيت القديمة)")


if __name__ == "__main__":
    main()
