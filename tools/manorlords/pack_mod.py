"""
tools/manorlords/pack_mod.py — حزم ملفات uasset مترجمة في مود .pak لـ Manor Lords.

⚠ Manor Lords (UE5.5) يقبل **pak version 11** فقط. UnrealPak من UE_5.7 ينتج v12
   (مرفوض → كراش "Invalid pak file version (12)"). لذا نستخدم **repak** مع --version V11.

Manor Lords يستخدم .pak خالص (IoStore معطّل). المود = .pak يُوضع في Content/Paks/
مباشرة مع لاحقة _P (أولوية patch) واسم يرتّب أخيراً (zzz_) لأعلى أولوية.

Mount point: ../../../  والمسار الكامل يشمل ManorLords/Content/  (مطابق للعبة).

الاستخدام:
  python tools/manorlords/pack_mod.py --files "<abs uasset>" [...] \
      [--content-root "<.../for_cache>"] [--name zzz_ManorLords_Arabic] \
      [--compression Zlib] [--install]

  لكل uasset يُضمَّن تلقائياً .uexp/.ubulk المجاور.
  --install : ينسخ الـ pak الناتج إلى Content/Paks/ مباشرة.
"""
from __future__ import annotations
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPAK = os.path.join(_ROOT, "tools", "repak", "repak.exe")
GAME_PAKS = r"C:/Program Files (x86)/Steam/steamapps/common/Manor Lords/ManorLords/Content/Paks"
MOUNT_POINT = "../../../"
PAK_VERSION = "V11"          # ← UE pak format 11 (يطابق Manor Lords)
DEFAULT_CONTENT_ROOT = os.path.join(_ROOT, "mods", "Manor Lords", "for_cache")
SIDECARS = (".uexp", ".ubulk", ".uptnl")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="+", required=True, help="ملفات .uasset المترجمة (مطلقة)")
    ap.add_argument("--content-root", default=DEFAULT_CONTENT_ROOT,
                    help="جذر الحزم — افتراضي for_cache/ ليصبح المسار ManorLords/Content/…")
    ap.add_argument("--name", default="zzz_ManorLords_Arabic")
    ap.add_argument("--compression", default="", help="Zlib|Gzip|Zstd|LZ4|Oodle (افتراضي بلا ضغط)")
    ap.add_argument("--version", default=PAK_VERSION)
    ap.add_argument("--out-dir", default=os.path.join(_ROOT, "mods", "Manor Lords", "ready"))
    ap.add_argument("--install", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(REPAK):
        print(f"❌ repak مفقود: {REPAK}"); sys.exit(1)
    content_root = os.path.abspath(args.content_root)

    # اجمع كل الملفات + sidecars
    members = []
    for f in args.files:
        f = os.path.abspath(f)
        if not os.path.exists(f):
            print(f"❌ غير موجود: {f}"); sys.exit(1)
        members.append(f)
        stem = os.path.splitext(f)[0]
        for sc in SIDECARS:
            if os.path.exists(stem + sc):
                members.append(stem + sc)

    # جهّز staging dir بالبنية النسبية الصحيحة (repak يحزم مجلداً)
    stage = tempfile.mkdtemp(prefix="mlpak_")
    try:
        for m in members:
            rel = os.path.relpath(m, content_root).replace("\\", "/")
            dst = os.path.join(stage, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(m, dst)
            print(f"  + {rel}")

        os.makedirs(args.out_dir, exist_ok=True)
        out_pak = os.path.join(args.out_dir, f"{args.name}_P.pak")
        if os.path.exists(out_pak):
            os.remove(out_pak)

        cmd = [REPAK, "pack", "--version", args.version, "--mount-point", MOUNT_POINT]
        if args.compression:
            cmd += ["--compression", args.compression]
        cmd += [stage, out_pak]

        print(f"\n📦 repak pack (version {args.version}"
              f"{', '+args.compression if args.compression else ', بلا ضغط'}) …")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.stdout.strip(): print(r.stdout.strip())
        if r.returncode != 0:
            print("❌ فشل repak:\n", r.stderr[-1500:]); sys.exit(1)

        ok = os.path.exists(out_pak)
        print(("✅ نجح" if ok else "❌ فشل"))
        if not ok: sys.exit(1)
        print(f"💾 {out_pak}  ({os.path.getsize(out_pak)} bytes)")

        if args.install:
            dst = os.path.join(GAME_PAKS, os.path.basename(out_pak))
            shutil.copy2(out_pak, dst)
            print(f"📥 ثُبّت: {dst}")
    finally:
        shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    main()
