"""
tools/publish_app.py
Builds the exe, zips it, creates GitHub Release, and updates manifest.json.
Usage: python publish_app.py <version>   e.g.  python publish_app.py 1.1
"""
import sys, json, os, subprocess, shutil, time

REPO = "nssr12/GameArabicTranslator"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def run(cmd, check=True):
    print(f">> {' '.join(str(c) for c in cmd)}")
    r = subprocess.run(cmd, cwd=ROOT, check=check)
    return r.returncode

def main():
    if len(sys.argv) < 2:
        print("Usage: publish_app.py <version>")
        sys.exit(1)

    version = sys.argv[1]
    tag     = f"v{version}"
    zip_name = f"GameArabicTranslator_v{version}.zip"
    zip_path = os.path.join(ROOT, "dist", zip_name)
    dist_dir = os.path.join(ROOT, "dist", "GameArabicTranslator")

    print(f"\n=== Building App v{version} ===\n")

    # ── 1. Clean old dist ─────────────────────────────────────────────────────
    if os.path.isdir(dist_dir):
        print("Cleaning previous build...")
        shutil.rmtree(dist_dir)
    if os.path.isfile(zip_path):
        os.remove(zip_path)

    # ── 2a. Sync APP_VERSION in translation_registry.py ──────────────────────
    registry_path = os.path.join(ROOT, "games", "translation_registry.py")
    with open(registry_path, encoding="utf-8") as f:
        reg_src = f.read()
    import re as _re
    reg_src = _re.sub(r'APP_VERSION\s*=\s*"[^"]+"', f'APP_VERSION = "{version}"', reg_src)
    with open(registry_path, "w", encoding="utf-8") as f:
        f.write(reg_src)
    print(f"APP_VERSION set to {version} in translation_registry.py")

    # ── 2. PyInstaller build ──────────────────────────────────────────────────
    print("\n[1/5] Building with PyInstaller...")
    run([sys.executable, "-m", "PyInstaller", "GameArabicTranslator.spec", "--noconfirm"])

    # ── 3. Create user folders + copy configs ─────────────────────────────────
    print("\n[2/5] Setting up user directories...")
    cache_dst = os.path.join(dist_dir, "data", "cache")
    os.makedirs(cache_dst, exist_ok=True)
    os.makedirs(os.path.join(dist_dir, "logs"), exist_ok=True)
    shutil.copy2(os.path.join(ROOT, "config.json"), dist_dir)
    shutil.copytree(
        os.path.join(ROOT, "games", "configs"),
        os.path.join(dist_dir, "games", "configs"),
        dirs_exist_ok=True,
    )
    # Copy pre-built translation caches so users see content on first launch
    cache_src = os.path.join(ROOT, "data", "cache")
    if os.path.isdir(cache_src):
        import glob as _glob
        for db in _glob.glob(os.path.join(cache_src, "*.db")):
            shutil.copy2(db, cache_dst)
            print(f"  Copied cache: {os.path.basename(db)}")
    # Copy icon
    icon_src = os.path.join(ROOT, "data", "icon.ico")
    if os.path.isfile(icon_src):
        icon_dst = os.path.join(dist_dir, "data")
        os.makedirs(icon_dst, exist_ok=True)
        shutil.copy2(icon_src, icon_dst)
    # Copy game cover images
    img_src = os.path.join(ROOT, "data", "game_images")
    if os.path.isdir(img_src):
        img_dst = os.path.join(dist_dir, "data", "game_images")
        shutil.copytree(img_src, img_dst, dirs_exist_ok=True)
        count = sum(1 for f in os.listdir(img_src) if os.path.isfile(os.path.join(img_src, f)))
        print(f"  Copied game_images: {count} image(s)")

    # ── 4. Create ZIP ─────────────────────────────────────────────────────────
    print(f"\n[3/5] Creating {zip_name}...")
    shutil.make_archive(
        os.path.join(ROOT, "dist", f"GameArabicTranslator_v{version}"),
        "zip",
        root_dir=os.path.join(ROOT, "dist"),
        base_dir="GameArabicTranslator",
    )
    size_mb = round(os.path.getsize(zip_path) / (1024 * 1024))
    print(f"ZIP: {zip_path}  ({size_mb} MB)")

    # ── 5. Delete old GitHub Release if exists ────────────────────────────────
    r = subprocess.run(["gh", "release", "view", tag, "--repo", REPO],
                       capture_output=True, cwd=ROOT)
    if r.returncode == 0:
        print(f"\nRelease {tag} exists — deleting...")
        run(["gh", "release", "delete", tag, "--repo", REPO,
             "--yes", "--cleanup-tag"])
        time.sleep(3)

    # ── 6. Create GitHub Release ──────────────────────────────────────────────
    print(f"\n[4/5] Creating GitHub Release {tag}...")
    run([
        "gh", "release", "create", tag,
        "--repo", REPO,
        "--title", f"Game Arabic Translator v{version}",
        "--notes", f"Game Arabic Translator v{version}",
        zip_path,
    ])

    download_url = (
        f"https://github.com/{REPO}/releases/download/{tag}/{zip_name}"
    )
    print(f"Release URL: {download_url}")

    # ── 7. Update manifest.json ───────────────────────────────────────────────
    print(f"\n[5/5] Updating manifest.json...")
    manifest_path = os.path.join(ROOT, "manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
        m = json.load(f)

    # sha256 للتحقّق الأمني عند المستخدم
    import hashlib
    _h = hashlib.sha256()
    with open(zip_path, "rb") as _zf:
        for _b in iter(lambda: _zf.read(1 << 20), b""):
            _h.update(_b)
    app_sha = _h.hexdigest()

    m["app"]["version"]      = version
    m["app"]["download_url"] = download_url
    m["app"]["sha256"]       = app_sha
    print(f"app sha256: {app_sha}")

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)

    # ── 8. Git commit + push ──────────────────────────────────────────────────
    run(["git", "add", "manifest.json", "games/translation_registry.py"])
    rc = run(["git", "commit", "-m", f"Release app v{version}"], check=False)
    if rc == 0:
        run(["git", "push", "origin", "HEAD:main"])
    else:
        print("manifest.json unchanged — skipping commit.")

    print(f"\n=== Done! ===")
    print(f"Version:  v{version}  ({size_mb} MB)")
    print(f"Release:  https://github.com/{REPO}/releases/tag/{tag}")
    print("Old users will see the update banner on next app launch.")

if __name__ == "__main__":
    main()
