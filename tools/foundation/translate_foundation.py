"""
tools/foundation/translate_foundation.py
=========================================
مترجم دفعي لملفات localization الخاصة بـ Foundation (Hurricane engine).

• يقرأ كل localization/en/*.json (بنية متداخلة، BOM، tabs).
• يترجم كل قيمة نصّية ورقية (leaf) عبر FilteredTranslator (نفس cascade + حماية
  التاقات/الـ placeholders مثل {1} و {IMG1}).
• كاش per-game في data/cache/Foundation.db (قابل للاستئناف — لا يُعيد ترجمة مخزّن).
• يكتب localization/ar/*.json بنفس البنية.
• الترجمة تُخزَّن بالترتيب المنطقي (logical). التشكيل (presentation forms + عكس)
  يُطبَّق اختيارياً عند الكتابة عبر --shape (نقرّره بعد ما نحسم سلوك خط اللعبة).

الاستخدام:
    python tools/foundation/translate_foundation.py --analyze        # إحصاء فقط
    python tools/foundation/translate_foundation.py                  # ترجمة (logical)
    python tools/foundation/translate_foundation.py --shape          # + تشكيل عند الكتابة
    python tools/foundation/translate_foundation.py --only menu.json # ملف واحد
    python tools/foundation/translate_foundation.py --write-only     # أعد كتابة ar/ من الكاش بلا ترجمة
"""
from __future__ import annotations
import argparse, json, os, re, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from engine.translator import TranslationEngine
from engine.cache import TranslationCache
from engine.filtered_translator import FilteredTranslator, get_global_tag_mode
from engine.models.base import TOKEN_RE
from engine import arabic_shaper
from engine.rtl_layout import layout_rtl

GAME = "Foundation"
LOC = r"D:/SteamLibrary/steamapps/common/Foundation/localization"
EN = os.path.join(LOC, "en")
AR = os.path.join(LOC, "ar")

# حرف لاتيني واحد على الأقل بعد إزالة التاقات/الأرقام = قابل للترجمة
_LETTER = re.compile(r"[A-Za-z]")


def is_translatable(text: str) -> bool:
    if not text or not text.strip():
        return False
    stripped = TOKEN_RE.sub(" ", text)          # احذف {1}, {IMG1}, %s, tags...
    return bool(_LETTER.search(stripped))       # يبقى نص حقيقي؟


def walk_strings(obj, path=()):
    """مولّد (path, value) لكل قيمة نصّية في بنية JSON متداخلة."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_strings(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_strings(v, path + (i,))
    elif isinstance(obj, str):
        yield path, obj


def set_at(obj, path, value):
    for k in path[:-1]:
        obj = obj[k]
    obj[path[-1]] = value


def resolve_model_name(engine) -> str:
    key = engine.get_active_model() or "unknown"
    tr = engine.get_translator(key)
    return getattr(tr, "model", None) or key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--shape", action="store_true", help="طبّق تشكيل العربي + تخطيط RTL عند الكتابة")
    ap.add_argument("--wrap", type=int, default=0, help="حدّ لفّ الكلمات (0=فواصل صريحة فقط؛ موصى ~50)")
    ap.add_argument("--only", help="ملف واحد فقط (مثل menu.json)")
    ap.add_argument("--write-only", action="store_true", help="أعد كتابة ar/ من الكاش بلا ترجمة AI")
    ap.add_argument("--limit", type=int, default=0, help="حدّ عدد الترجمات الجديدة (اختبار)")
    args = ap.parse_args()

    files = sorted(f for f in os.listdir(EN) if f.endswith(".json"))
    if args.only:
        files = [f for f in files if f == args.only]
    if not files:
        print("لا ملفات JSON."); return 1

    # إحصاء
    total = uniq = 0
    seen = set()
    per_file = {}
    for fn in files:
        data = json.load(open(os.path.join(EN, fn), encoding="utf-8-sig"))
        cnt = 0
        for _p, v in walk_strings(data):
            if is_translatable(v):
                cnt += 1; total += 1
                if v not in seen:
                    seen.add(v); uniq += 1
        per_file[fn] = cnt
    print(f"ملفات: {len(files)} | نصوص قابلة للترجمة: {total} | فريدة: {uniq}")
    for fn in files:
        print(f"   {fn:34} {per_file[fn]}")
    if args.analyze:
        return 0

    os.makedirs(AR, exist_ok=True)

    cache = TranslationCache(os.path.join(ROOT, "data", "cache", f"{GAME}.db"))
    engine = ft = model = None
    if not args.write_only:
        engine = TranslationEngine(os.path.join(ROOT, "config.json"))
        if engine.get_active_model():
            engine.load_active_model() if hasattr(engine, "load_active_model") else None
        model = resolve_model_name(engine)
        ft = FilteredTranslator(engine, tag_mode=get_global_tag_mode())
        print(f"المحرّك: {model} | tag_mode={ft.tag_mode}")

    def shape(s: str) -> str:
        return layout_rtl(s, max_line_len=args.wrap) if args.shape else s

    new_count = 0
    t0 = time.time()
    for fn in files:
        data = json.load(open(os.path.join(EN, fn), encoding="utf-8-sig"))
        translated = hit = miss = 0
        for path, en_text in walk_strings(data):
            if not is_translatable(en_text):
                continue
            ar = cache.get_best(GAME, en_text)
            if ar:
                hit += 1
            elif not args.write_only:
                if args.limit and new_count >= args.limit:
                    continue
                result, mode = ft.translate_with_info(en_text)
                if result:
                    cache.put(GAME, en_text, result, model=model, mode_used=mode)
                    ar = result; new_count += 1; miss += 1
                    if new_count % 25 == 0:
                        rate = new_count / max(1e-6, time.time() - t0)
                        print(f"   …{new_count} ترجمة جديدة ({rate:.1f}/ث)")
            if ar:
                set_at(data, path, shape(ar))
                translated += 1
        # اكتب ar/<file>
        with open(os.path.join(AR, fn), "w", encoding="utf-8-sig") as f:
            json.dump(data, f, ensure_ascii=False, indent="\t")
        print(f"✓ {fn:30} مترجَم={translated} (cache={hit}, جديد={miss})")

    print(f"\nانتهى. ترجمات جديدة: {new_count} | الزمن: {time.time()-t0:.0f}ث")
    print(f"الناتج: {AR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
