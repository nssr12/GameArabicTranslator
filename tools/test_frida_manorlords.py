"""
test_frida_manorlords.py — أداة سطر أوامر لاختبار Frida hook على Manor Lords.

الاستخدام:
    1) شغّل Manor Lords من Steam
    2) شغّل هذا السكريبت:  python tools/test_frida_manorlords.py
    3) راقب النصوص الملتقطة في الـ console
    4) اضغط Ctrl+C للخروج

ما يفعله:
    ✓ ينتظر/يتّصل بـ ManorLords-Win64-Shipping.exe
    ✓ يُحمّل hooking/hooks/manorlords_hook_v2.js
    ✓ يستلم النصوص الملتقطة + يحفظها في data/cache/Manor Lords.db كـ failed
        (لكي تظهر في صفحة الكاش > فاشل ويستطيع المستخدم ترجمتها يدوياً أو بـ AI)
    ✓ يحفظ نسخة من النصوص في tmp/manorlords_captured.txt للتشخيص
    ✓ يستفسر الكاش كل 30 ث ويُرسل أي ترجمات متاحة للـ hook
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# اجعل المشروع متاحاً للـ import
PROJ_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ_ROOT))


def banner(msg: str):
    print("\n" + "═" * 70)
    print(f"  {msg}")
    print("═" * 70)


def main():
    ap = argparse.ArgumentParser(description="اختبار Frida hook على Manor Lords")
    ap.add_argument("--process", default="ManorLords-Win64-Shipping.exe",
                    help="اسم العملية (افتراضي: ManorLords-Win64-Shipping.exe)")
    ap.add_argument("--hook", default=str(PROJ_ROOT / "hooking/hooks/manorlords_hook_v5.js"),
                    help="مسار Frida script (افتراضي: v5 — aggressive CVar description killer)")
    ap.add_argument("--wait", type=int, default=60,
                    help="ثواني انتظار اللعبة لتعمل (افتراضي 60)")
    ap.add_argument("--sync-interval", type=int, default=30,
                    help="فترة مزامنة الترجمات (ث)")
    ap.add_argument("--save-to-cache", action="store_true",
                    help="احفظ النصوص الملتقطة في data/cache/Manor Lords.db")
    ap.add_argument("--no-translate", action="store_true",
                    help="لا تطلب ترجمات للنصوص الملتقطة (التقاط فقط)")
    args = ap.parse_args()

    banner("Frida Test Runner — Manor Lords")

    # ── تحميل frida ─────────────────────────────────────────────────────
    try:
        import frida
        print(f"✓ Frida {frida.__version__}")
    except ImportError:
        print("✗ frida غير مثبَّت. شغّل: pip install frida")
        return 1

    # ── ابحث عن العملية ─────────────────────────────────────────────────
    device = frida.get_local_device()
    pid = None
    print(f"⏳ أبحث عن {args.process} (مهلة {args.wait} ث)...")
    deadline = time.time() + args.wait
    while time.time() < deadline:
        procs = device.enumerate_processes()
        for p in procs:
            if args.process.lower() in p.name.lower():
                pid = p.pid
                print(f"✓ وُجدت: PID={pid} | name={p.name}")
                break
        if pid:
            break
        time.sleep(1)
    if not pid:
        print(f"✗ {args.process} لم تُوجَد. شغّل Manor Lords من Steam ثم أعد المحاولة.")
        return 2

    # ── attach ──────────────────────────────────────────────────────────
    try:
        session = device.attach(pid)
        print(f"✓ متّصل بالعملية {pid}")
    except Exception as e:
        print(f"✗ فشل attach: {e}")
        return 3

    # ── حمّل الـ hook ───────────────────────────────────────────────────
    hook_path = Path(args.hook)
    if not hook_path.exists():
        print(f"✗ hook غير موجود: {hook_path}")
        return 4
    with open(hook_path, encoding="utf-8") as f:
        script_src = f.read()

    # ── إعداد الكاش (اختياري) ──────────────────────────────────────────
    cache = None
    if args.save_to_cache:
        try:
            from engine.cache import TranslationCache
            cache = TranslationCache(str(PROJ_ROOT / "data/cache/translations.db"))
            cache._game_db_path = lambda gn: str(PROJ_ROOT / f"data/cache/{gn}.db")
            print("✓ Cache مُحمَّل (Manor Lords.db)")
        except Exception as e:
            print(f"⚠ Cache فشل: {e}")
            cache = None

    # ── حالة الجلسة ────────────────────────────────────────────────────
    captured_texts: set[str] = set()
    captured_file = PROJ_ROOT / "tmp" / "manorlords_captured.txt"
    captured_file.parent.mkdir(parents=True, exist_ok=True)

    def save_captured(text: str):
        """يحفظ نصاً ملتقطاً في الكاش (failed) + ملف tmp."""
        if text in captured_texts:
            return
        captured_texts.add(text)
        # ملف tmp
        try:
            with open(captured_file, "a", encoding="utf-8") as f:
                f.write(text.replace("\n", "\\n") + "\n")
        except Exception:
            pass
        # cache
        if cache and not args.no_translate:
            try:
                cache.mark_failed("Manor Lords", text, "frida_captured", model_used="")
            except Exception:
                pass

    # ── message handler ────────────────────────────────────────────────
    def on_message(message, data):
        msg_type = message.get("type")
        if msg_type == "send":
            payload = message.get("payload", {})
            ptype = payload.get("type", "")
            pmsg = payload.get("message", "")
            if ptype == "text_found":
                text = payload.get("text", "")
                if text:
                    save_captured(text)
                    n = len(captured_texts)
                    if n <= 50 or n % 10 == 0:
                        print(f"  📝 [{n:4d}] {text[:80]!r}")
            elif ptype == "scan_complete":
                print(f"  🔍 {pmsg}")
            elif ptype == "replaced":
                print(f"  ✏  {pmsg}")
            elif ptype == "ready":
                print(f"  ✅ {pmsg}")
            elif ptype == "log":
                print(f"  📋 {pmsg}")
            elif ptype == "error":
                print(f"  ❌ {pmsg}")
            else:
                print(f"  📨 {payload}")
        elif msg_type == "error":
            print(f"  ❌ Frida error: {message.get('description', '')}")

    script = session.create_script(script_src)
    script.on("message", on_message)
    script.load()
    print("✓ Hook مُحمَّل\n")

    # ── حلقة المزامنة (إرسال ترجمات من cache للـ hook كل N ث) ─────────
    last_sync = 0
    try:
        banner("الالتقاط بدأ — Ctrl+C للخروج")
        print(f"📂 النصوص الملتقطة → {captured_file}")
        if cache:
            print(f"💾 Cache → data/cache/Manor Lords.db (كـ failed_translations)")
        print()
        while True:
            time.sleep(2)
            now = time.time()
            if cache and (now - last_sync) >= args.sync_interval:
                last_sync = now
                try:
                    # احصل على كل الترجمات الناجحة + أرسلها للـ hook
                    translations = {}
                    for en, ar in cache.iter_best_translations("Manor Lords"):
                        if en and ar:
                            translations[en] = ar
                    if translations:
                        try:
                            n = script.exports_sync.pingbatch({"translations": translations})
                            print(f"  🔄 sync: أرسل {len(translations)} ترجمة للـ hook (cache في الـ hook الآن: {n})")
                        except Exception as e:
                            print(f"  ⚠ sync فشل: {e}")
                except Exception as e:
                    print(f"  ⚠ cache iter فشل: {e}")
    except KeyboardInterrupt:
        print("\n\n⏹  متوقّف بواسطة المستخدم")
    finally:
        # احفظ إحصائيات نهائية + breakdown للفلاتر
        try:
            stats = script.exports_sync.getstats()
            banner("الإحصاءات النهائية")
            print(json.dumps(stats, indent=2, ensure_ascii=False))

            # ملخّص الفلاتر
            total_cand = stats.get("candidates_total", 0)
            if total_cand > 0:
                kept = stats.get("texts_found", 0)
                print(f"\n📊 من أصل {total_cand:,} مرشّح: قُبل {kept:,} ({100*kept/total_cand:.1f}%)")
                filters = {
                    "قصير/طويل": stats.get("filtered_short", 0),
                    "عربي بالفعل": stats.get("filtered_arabic", 0),
                    "CVar references (r.X.Y)": stats.get("filtered_cvar_ref", 0),
                    "مصطلحات تقنية (PSO, GPU, ...)": stats.get("filtered_tech_term", 0),
                    "option lists (0:, 1:, ...)": stats.get("filtered_option_list", 0),
                    "MetaSound nodes": stats.get("filtered_metasound", 0),
                    "asset paths": stats.get("filtered_asset_path", 0),
                    "audio devices": stats.get("filtered_audio_device", 0),
                    "Windows paths": stats.get("filtered_path", 0),
                    "UE internal": stats.get("filtered_ue_internal", 0),
                    "CVar description prefix": stats.get("filtered_desc_prefix", 0),
                    "naturalness score": stats.get("filtered_score", 0),
                }
                for name, count in sorted(filters.items(), key=lambda x: -x[1]):
                    if count > 0:
                        print(f"   ✗ {name}: {count:,}")

            print(f"\n📁 ranges scanned: {stats.get('ranges_scanned', 0):,} | "
                  f"file-backed تجاهلت: {stats.get('ranges_skipped_file_backed', 0):,}")
        except Exception as e:
            print(f"⚠ فشل قراءة الإحصاءات: {e}")
        print(f"\n📊 إجمالي النصوص الملتقطة: {len(captured_texts)}")
        print(f"📂 الملف: {captured_file}")
        if cache:
            print(f"💾 Cache: data/cache/Manor Lords.db")
        try:
            script.unload()
        except Exception:
            pass
        try:
            session.detach()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
