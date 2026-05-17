"""
rebuild_xunity_translations.py — يُعيد بناء translations.txt الخاص بـ XUnity من كاش التطبيق.

السبب:
  XUnity.AutoTranslator يحفظ نسخة محلية من الترجمات في translations.txt.
  إذا أُنشئت هذه النسخة بالصيغة القديمة (apply_bidi=True + get_display)،
  فستحتوي على نص بصيغة visual-order. مع isRightToLeftText=true الجديد،
  يحدث عكس مزدوج → نص مقلوب.

الحل:
  نُعيد بناء translations.txt من كاش التطبيق (Flotsam.db) الذي يحتوي
  على عربي بترتيب منطقي صحيح (base chars 0x600-0x6FF).
  نطبّق reshape فقط (بلا get_display) ليكون متوافقاً مع المسار الحالي.
"""
import argparse
import os
import re
import sqlite3
import sys

try:
    import arabic_reshaper
except ImportError:
    print("ERROR: arabic_reshaper غير مُثبّت. شغّل: pip install arabic-reshaper")
    sys.exit(1)


def needs_translation(text: str) -> bool:
    t = text.strip()
    if len(t) < 3:
        return False
    if not re.search(r"[A-Za-z؀-ۿ]", t):
        return False
    return True


def rebuild(db_path: str, out_path: str) -> int:
    if not os.path.exists(db_path):
        print(f"ERROR: لم يُعثر على قاعدة بيانات الكاش: {db_path}")
        return 0

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT original_text, translated_text FROM translations"
    ).fetchall()
    conn.close()

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    count = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for orig, trans in rows:
            if not orig or not trans:
                continue
            # نُطبّق نفس معالجة الـ proxy: حذف الأسطر الداخلية
            cleaned = " ".join(orig.replace("\\n", " ").replace("\n", " ").split())
            if not cleaned or not needs_translation(cleaned):
                continue
            # reshape فقط (بلا get_display) — logical order بحروف Presentation Forms
            reshaped = arabic_reshaper.reshape(trans)
            # تنسيق XUnity: original=translated في سطر واحد، \n→\\n
            line_orig = cleaned.replace("\n", "\\n").replace("\r", "")
            line_trans = reshaped.replace("\n", "\\n").replace("\r", "")
            f.write(f"{line_orig}={line_trans}\n")
            count += 1

    return count


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "--db",
        default=r"d:/GameArabicTranslator/data/cache/Flotsam.db",
        help="مسار قاعدة بيانات الكاش",
    )
    p.add_argument(
        "--out",
        default=r"C:/Program Files (x86)/Steam/steamapps/common/Flotsam/BepInEx/config/ArabicGameTranslator/translations.txt",
        help="مسار ملف translations.txt الخاص بـ XUnity",
    )
    args = p.parse_args()

    n = rebuild(args.db, args.out)
    print(f"✅ تم كتابة {n} ترجمة إلى:\n  {args.out}")
