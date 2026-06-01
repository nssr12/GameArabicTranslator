"""
tools/clean_broken_tag_translations.py
======================================
يكتشف الترجمات المعطوبة (التاقات مكسورة بسبب bug قديم في restore) ويحذفها
من كاش الـ SQLite حتى يُعاد ترجمتها بـ filter المُصلَّح.

معايير الاعتبار "معطوبة":
  - عدد علامات الفتح `<اسم` في الترجمة != عدد علامات الفتح في الأصل
  - أو: عدد التاقات الكاملة `<...>` في الترجمة < عدد علامات الفتح فيها
    (يعني فيه تاق مفتوح بدون إغلاق)

الاستخدام:
    python tools/clean_broken_tag_translations.py                 # فحص فقط (dry-run)
    python tools/clean_broken_tag_translations.py --game Palworld # فحص لعبة محدّدة
    python tools/clean_broken_tag_translations.py --delete         # احذف فعلياً
    python tools/clean_broken_tag_translations.py --delete --yes   # بدون تأكيد
"""
from __future__ import annotations
import argparse
import glob
import os
import re
import sqlite3
import sys

# نمط selfclosing مع attrs: <name attrs/> — هذا هو الـ bug الفعلي
_RX_SELFCLOSE_FULL = re.compile(
    r'<([a-zA-Z][a-zA-Z0-9_]*)\s+([^<>]*?)/\s*>'
)


def is_broken(original: str, translated: str) -> bool:
    """يُرجع True لو في الأصل selfclosing tag (<name attrs/>) لكن في الترجمة
    نسخة مكسورة منه (عدد ناقص أو attrs مكسورة).

    نتجاهل التاقات بدون attrs (مثل <br>, <hr>) لأنها لا تُكسَر عادةً،
    والتاقات المزدوجة (<noparse>...</noparse>) لأن المودل قد يحذفها عمداً.
    """
    if not original or not translated:
        return False
    orig_tags = _RX_SELFCLOSE_FULL.findall(original)
    if not orig_tags:
        return False

    for name, attrs in orig_tags:
        # نتأكد كل selfclosing tag يظهر في الترجمة كاملاً
        # نمط: <name attrs/> — مع نفس الـ name و closure صحيحة
        rx = re.compile(
            r'<' + re.escape(name) + r'\s+[^<>]*?/\s*>'
        )
        orig_count  = len(re.findall(
            r'<' + re.escape(name) + r'\s+[^<>]*?/\s*>',
            original
        ))
        trans_count = len(rx.findall(translated))
        if trans_count != orig_count:
            return True

        # علامة إضافية: لو attrs الأصلية موجودة في الترجمة بدون wrapper كامل
        # (مثل |Umihebi_Fire|/> ظاهرة لكن <characterName id= مفقود)
        if attrs and "|" in attrs:
            # خذ آخر جزء بين | … | كـ "بصمة" (مثل |SoldierBee|)
            m = re.search(r'\|([^|<>]+)\|', attrs)
            if m:
                fingerprint = m.group(0)   # |SoldierBee|
                if fingerprint in translated:
                    # تحقّق: هل قبلها مباشرة <name id=؟ لو لا → مكسور
                    pos = translated.find(fingerprint)
                    prefix = translated[max(0, pos-60):pos]
                    if f"<{name}" not in prefix:
                        return True
    return False


def scan_db(db_path: str) -> tuple[int, list[tuple[str, str, str]]]:
    """يفحص قاعدة بيانات. يُرجع (total_rows, broken_rows[(orig, ar, model)])."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT original_text, translated_text, model_used FROM translations"
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"  ! cannot read {db_path}: {e}")
        return 0, []
    finally:
        con.close()

    broken = [(o, t, m) for (o, t, m) in rows if is_broken(o, t)]
    return len(rows), broken


def delete_broken(db_path: str, broken: list[tuple[str, str, str]]) -> int:
    """يحذف الصفوف المعطوبة. يُرجع عدد الصفوف المحذوفة فعلياً."""
    if not broken:
        return 0
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        # المفتاح الفريد: (original_text, model_used)
        deleted = 0
        for orig, _ar, model in broken:
            cur.execute(
                "DELETE FROM translations WHERE original_text=? AND model_used=?",
                (orig, model),
            )
            deleted += cur.rowcount
        con.commit()
        return deleted
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", help="اسم لعبة محدّدة (مثل Palworld). الافتراضي: الكل")
    ap.add_argument("--delete", action="store_true", help="احذف فعلياً (الافتراضي: فحص فقط)")
    ap.add_argument("--yes", action="store_true", help="لا تطلب تأكيداً")
    ap.add_argument("--show", type=int, default=3, help="عدد الأمثلة المعروضة لكل لعبة")
    args = ap.parse_args()

    pattern = f"data/cache/{args.game}.db" if args.game else "data/cache/*.db"
    dbs = sorted(p for p in glob.glob(pattern)
                 if "backup" not in p.lower())
    if not dbs:
        print(f"لا يوجد كاش مطابق: {pattern}")
        return 1

    grand_total = 0
    grand_broken = 0
    plans: list[tuple[str, int, list]] = []

    print("=" * 70)
    print("فحص الترجمات المعطوبة (تاقات مكسورة)")
    print("=" * 70)
    for db in dbs:
        name = os.path.basename(db)
        total, broken = scan_db(db)
        grand_total += total
        grand_broken += len(broken)
        if broken:
            plans.append((db, total, broken))
            pct = 100 * len(broken) / total if total else 0
            print(f"\n  {name}")
            print(f"     total      : {total:,}")
            print(f"     broken     : {len(broken):,}  ({pct:.1f}%)")
            for i, (o, t, m) in enumerate(broken[:args.show]):
                print(f"     [{i+1}] model: {m}")
                print(f"         orig: {o[:80]}")
                print(f"         ar  : {t[:80]}")

    print("\n" + "=" * 70)
    print(f"المجموع: {grand_broken:,} معطوبة من {grand_total:,}  "
          f"({100*grand_broken/grand_total:.1f}% لو grand_total)")
    print("=" * 70)

    if not args.delete:
        print("\nهذا فحص فقط (dry-run). للحذف الفعلي: أضف --delete")
        return 0

    if grand_broken == 0:
        print("لا يوجد ما يُحذَف.")
        return 0

    if not args.yes:
        ans = input(f"\nاحذف {grand_broken:,} ترجمة معطوبة؟ (yes/no): ").strip().lower()
        if ans not in ("y", "yes", "نعم"):
            print("ألغي.")
            return 0

    total_deleted = 0
    for db, _total, broken in plans:
        deleted = delete_broken(db, broken)
        total_deleted += deleted
        print(f"  {os.path.basename(db):30s} حُذف: {deleted:,}")

    print(f"\n✓ حُذفت {total_deleted:,} ترجمة معطوبة. سيُعاد ترجمتها عند الطلب.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
