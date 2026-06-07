"""
tools/fix_added_periods.py
==========================
يُصحّح الترجمات التي أضاف فيها المودل نقطة (أو علامة نهاية جملة) ليست في الأصل
الإنجليزي. يحذف العلامة الزائدة **في مكانها** دون حذف الترجمة كاملةً.

السبب: مودلات صغيرة (12b) تميل لإضافة نقطة في النهاية رغم برومت المنع. هذه النقطة
تُسبّب مشاكل عرض RTL (مثل نقطة حمراء منفصلة عند تداخلها مع تاقات اللون).

يستخدم نفس منطق engine/models/base.py::enforce_trailing_punctuation
(تماثل علامة النهاية) لضمان اتساق التصحيح مع الترجمات الجديدة.

الاستخدام:
    python tools/fix_added_periods.py                  # فحص فقط (dry-run)، كل الألعاب
    python tools/fix_added_periods.py --game "Farthest Frontier"
    python tools/fix_added_periods.py --apply          # صحّح فعلياً
    python tools/fix_added_periods.py --apply --yes    # بدون تأكيد
"""
from __future__ import annotations
import argparse
import glob
import os
import sqlite3
import sys

# نستورد دالة التصحيح نفسها المستخدمة في زمن التشغيل لضمان سلوك متطابق
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.models.base import enforce_trailing_punctuation


def scan_db(db_path: str):
    """يُرجع (total, fixes[(id, orig, old, new)])."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT id, original_text, translated_text FROM translations"
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"  ! تعذّر قراءة {db_path}: {e}")
        return 0, []
    finally:
        con.close()

    fixes = []
    for _id, orig, ar in rows:
        new = enforce_trailing_punctuation(orig, ar)
        if new != ar:
            fixes.append((_id, orig, ar, new))
    return len(rows), fixes


def apply_fixes(db_path: str, fixes) -> int:
    if not fixes:
        return 0
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        n = 0
        for _id, _orig, _old, new in fixes:
            cur.execute(
                "UPDATE translations SET translated_text=? WHERE id=?",
                (new, _id),
            )
            n += cur.rowcount
        con.commit()
        return n
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", help="اسم لعبة محدّدة. الافتراضي: الكل")
    ap.add_argument("--apply", action="store_true", help="صحّح فعلياً (الافتراضي: فحص فقط)")
    ap.add_argument("--yes", action="store_true", help="لا تطلب تأكيداً")
    ap.add_argument("--show", type=int, default=4, help="عدد الأمثلة المعروضة لكل لعبة")
    args = ap.parse_args()

    pattern = f"data/cache/{args.game}.db" if args.game else "data/cache/*.db"
    dbs = sorted(p for p in glob.glob(pattern) if "backup" not in p.lower())
    if not dbs:
        print(f"لا يوجد كاش مطابق: {pattern}")
        return 1

    grand_total = grand_fix = 0
    plans = []

    print("=" * 70)
    print("فحص النقاط الزائدة (علامة نهاية أضافها المودل وليست في الأصل)")
    print("=" * 70)
    for db in dbs:
        total, fixes = scan_db(db)
        grand_total += total
        grand_fix += len(fixes)
        if fixes:
            plans.append((db, fixes))
            pct = 100 * len(fixes) / total if total else 0
            print(f"\n  {os.path.basename(db)}")
            print(f"     total : {total:,}")
            print(f"     fixes : {len(fixes):,}  ({pct:.1f}%)")
            for i, (_id, o, old, new) in enumerate(fixes[:args.show]):
                print(f"     [{i+1}] orig: {o[:70]}")
                print(f"         قبل : {old[:70]}")
                print(f"         بعد : {new[:70]}")

    print("\n" + "=" * 70)
    pct = 100 * grand_fix / grand_total if grand_total else 0
    print(f"المجموع: {grand_fix:,} بحاجة تصحيح من {grand_total:,}  ({pct:.1f}%)")
    print("=" * 70)

    if not args.apply:
        print("\nهذا فحص فقط (dry-run). للتصحيح الفعلي: أضف --apply")
        return 0

    if grand_fix == 0:
        print("لا يوجد ما يُصحَّح.")
        return 0

    if not args.yes:
        ans = input(f"\nصحّح {grand_fix:,} ترجمة؟ (yes/no): ").strip().lower()
        if ans not in ("y", "yes", "نعم"):
            print("ألغي.")
            return 0

    total_fixed = 0
    for db, fixes in plans:
        n = apply_fixes(db, fixes)
        total_fixed += n
        print(f"  {os.path.basename(db):30s} صُحّح: {n:,}")

    print(f"\n✓ صُحّحت {total_fixed:,} ترجمة. أعد تصدير translations.txt لتطبيقها داخل اللعبة.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
