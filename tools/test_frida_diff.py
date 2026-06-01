"""
test_frida_diff.py — أداة diff-based لاستخراج نصوص شاشة معيّنة من Manor Lords.

التدفّق:
    1. شغّل اللعبة في القائمة الرئيسية
    2. شغّل: python tools/test_frida_diff.py
    3. > s main                 ← snapshot للقائمة الرئيسية
    4. [في اللعبة، افتح Settings]
    5. > scan                   ← أعد scan الذاكرة (يلتقط النصوص الجديدة)
    6. > s settings             ← snapshot لشاشة Settings
    7. > d main settings        ← اعرض الفرق = نصوص Settings الجديدة فقط
    8. > save main settings settings_only.txt
    9. > q

أوامر سريعة:
    s <label>           = snapshot الآن باسم label
    list                = اعرض كل snapshots
    d <from> <to>       = diff (نصوص في to ليست في from)
    save <from> <to> <file> = احفظ الـ diff إلى ملف
    scan                = أعد scan الذاكرة فوراً (بدل انتظار 5ث)
    clear-acc           = امسح النصوص المتراكمة
    clear-snaps         = امسح كل snapshots
    stats               = إحصاءات
    h / help            = هذه المساعدة
    q / quit            = خروج
"""
from __future__ import annotations

import sys
import time
import threading
import shlex
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ_ROOT))

HELP = """
أوامر:
  s <label>                   snapshot النصوص الآن باسم label
  list                        اعرض كل snapshots
  d <from> <to>               diff (نصوص in to ليست in from)
  save <from> <to> <file>     احفظ diff في ملف
  scan                        scan فوري
  show <label> [n]            اعرض أوّل n نص من snapshot
  stats                       إحصاءات
  clear-acc                   امسح النصوص المتراكمة
  clear-snaps                 امسح snapshots
  h, help                     هذه المساعدة
  q, quit                     خروج
"""


def banner(msg):
    print("\n" + "═" * 70)
    print(f"  {msg}")
    print("═" * 70)


def main():
    process_name = "ManorLords-Win64-Shipping.exe"
    hook_path = PROJ_ROOT / "hooking/hooks/manorlords_hook_v6_diff.js"
    wait_seconds = 60

    banner("Frida Diff Tool — Manor Lords")

    try:
        import frida
        print(f"✓ Frida {frida.__version__}")
    except ImportError:
        print("✗ frida غير مثبَّت. pip install frida")
        return 1

    device = frida.get_local_device()
    pid = None
    print(f"⏳ أبحث عن {process_name} (مهلة {wait_seconds}ث)...")
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        for p in device.enumerate_processes():
            if process_name.lower() in p.name.lower():
                pid = p.pid
                print(f"✓ PID={pid} | {p.name}")
                break
        if pid:
            break
        time.sleep(1)
    if not pid:
        print(f"✗ {process_name} لم تُوجَد. شغّل اللعبة من Steam ثم أعد المحاولة.")
        return 2

    try:
        session = device.attach(pid)
        print(f"✓ متّصل بالعملية {pid}")
    except Exception as e:
        print(f"✗ فشل attach: {e}")
        return 3

    if not hook_path.exists():
        print(f"✗ hook غير موجود: {hook_path}")
        return 4
    script_src = hook_path.read_text(encoding="utf-8")

    def on_message(message, data):
        msg_type = message.get("type")
        if msg_type == "send":
            payload = message.get("payload", {})
            ptype = payload.get("type", "")
            pmsg = payload.get("message", "")
            if ptype in ("scan_complete", "log", "ready", "replaced"):
                print(f"  [{ptype}] {pmsg}")
            elif ptype == "error":
                print(f"  ❌ {pmsg}")
        elif msg_type == "error":
            print(f"  ❌ Frida: {message.get('description', '')}")

    script = session.create_script(script_src)
    script.on("message", on_message)
    script.load()
    print("✓ Hook v6-diff مُحمَّل\n")
    print("⏳ scan الأوّلي يعمل في الخلفية الآن (10-30 ث)... انتظر رسالة [ready] قبل أوّل snapshot")

    print(HELP)
    print("⚙ scan دوري كل 5ث. تأكّد من فتح اللعبة في الشاشة المرادة قبل أي snapshot.\n")

    def cmd_snapshot(label):
        try:
            r = script.exports_sync.snapshot(label)
            if r.get("ok"):
                print(f"  ✓ snapshot '{r['label']}' — {r['size']} نص")
            else:
                print(f"  ✗ {r.get('error')}")
        except Exception as e:
            print(f"  ✗ {e}")

    def cmd_list():
        try:
            snaps = script.exports_sync.listsnapshots()
            if not snaps:
                print("  (لا snapshots)")
                return
            print(f"  Snapshots ({len(snaps)}):")
            for s in snaps:
                print(f"    • {s['label']:20s}  {s['size']:5d} نص")
        except Exception as e:
            print(f"  ✗ {e}")

    def cmd_diff(from_lbl, to_lbl, save_file=None):
        try:
            r = script.exports_sync.diffsnapshots(from_lbl, to_lbl)
            if not r.get("ok"):
                print(f"  ✗ {r.get('error')}")
                return
            texts = r["texts"]
            print(f"\n  📊 diff '{from_lbl}' → '{to_lbl}':")
            print(f"     from:  {r['from_size']:5d} نص")
            print(f"     to:    {r['to_size']:5d} نص")
            print(f"     جديد:  {r['diff_size']:5d} نص ⭐")
            if save_file:
                p = Path(save_file)
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    for t in texts:
                        f.write(t.replace("\n", "\\n") + "\n")
                print(f"     💾 محفوظ: {p}")
            else:
                # اعرض أوّل 50
                limit = min(50, len(texts))
                print(f"     عرض أوّل {limit}:")
                for i, t in enumerate(texts[:limit]):
                    display = t if len(t) <= 80 else t[:77] + "..."
                    print(f"     [{i+1:3d}] {display!r}")
                if len(texts) > limit:
                    print(f"     ... + {len(texts) - limit} نص آخر (استخدم 'save' لحفظ الكل)")
        except Exception as e:
            print(f"  ✗ {e}")

    def cmd_show(label, n=20):
        try:
            r = script.exports_sync.getsnapshot(label)
            if not r.get("ok"):
                print(f"  ✗ {r.get('error')}")
                return
            texts = r["texts"]
            limit = min(int(n), len(texts))
            for i, t in enumerate(texts[:limit]):
                display = t if len(t) <= 80 else t[:77] + "..."
                print(f"  [{i+1:3d}] {display!r}")
            if len(texts) > limit:
                print(f"  ... + {len(texts) - limit} نص آخر")
        except Exception as e:
            print(f"  ✗ {e}")

    def cmd_scan():
        try:
            n = script.exports_sync.rescannow()
            print(f"  ✓ scan انتهى. إجمالي نصوص متراكمة: {n}")
        except Exception as e:
            print(f"  ✗ {e}")

    def cmd_clear_acc():
        try:
            r = script.exports_sync.clearaccumulated()
            print(f"  ✓ مُسحت {r['cleared']} نص متراكم")
        except Exception as e:
            print(f"  ✗ {e}")

    def cmd_clear_snaps():
        try:
            r = script.exports_sync.clearsnapshots()
            print(f"  ✓ مُسحت {r['cleared']} snapshot")
        except Exception as e:
            print(f"  ✗ {e}")

    def cmd_stats():
        try:
            s = script.exports_sync.getstats()
            print(f"  scans={s['scans']}  candidates={s['candidates_total']}  kept={s['texts_found']}  tracked={s['tracked_texts']}  snapshots={s['snapshot_count']}")
            print(f"  ✗ تقني: cvar_ref={s['filtered_cvar_ref']}  tech={s['filtered_tech_term']}  desc={s['filtered_desc_prefix']}  score={s['filtered_score']}")
        except Exception as e:
            print(f"  ✗ {e}")

    # ============ REPL ============
    try:
        while True:
            try:
                line = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n⏹ خروج")
                break
            if not line:
                continue
            try:
                parts = shlex.split(line)
            except Exception:
                parts = line.split()
            cmd = parts[0].lower()
            args = parts[1:]

            if cmd in ("q", "quit", "exit"):
                break
            elif cmd in ("h", "help", "?"):
                print(HELP)
            elif cmd == "s" and args:
                cmd_snapshot(args[0])
            elif cmd == "list":
                cmd_list()
            elif cmd == "d" and len(args) >= 2:
                cmd_diff(args[0], args[1])
            elif cmd == "save" and len(args) >= 3:
                cmd_diff(args[0], args[1], save_file=args[2])
            elif cmd == "show" and args:
                n = args[1] if len(args) > 1 else 20
                cmd_show(args[0], n)
            elif cmd == "scan":
                cmd_scan()
            elif cmd == "clear-acc":
                cmd_clear_acc()
            elif cmd == "clear-snaps":
                cmd_clear_snaps()
            elif cmd == "stats":
                cmd_stats()
            else:
                print(f"  ✗ أمر غير معروف: {cmd!r}. اكتب 'h' للمساعدة")

    finally:
        try: script.unload()
        except Exception: pass
        try: session.detach()
        except Exception: pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
