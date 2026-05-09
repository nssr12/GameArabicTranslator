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

    # ── 2. PyInstaller build ──────────────────────────────────────────────────
    print("\n[1/5] Building with PyInstaller...")
    run(["pyinstaller", "GameArabicTranslator.spec", "--noconfirm"])

    # ── 3. Create user folders + copy configs ─────────────────────────────────
    print("\n[2/5] Setting up user directories...")
    os.makedirs(os.path.join(dist_dir, "data", "cache"), exist_ok=True)
    os.makedirs(os.path.join(dist_dir, "logs"),          exist_ok=True)
    shutil.copy2(os.path.join(ROOT, "config.json"), dist_dir)
    shutil.copytree(
        os.path.join(ROOT, "games", "configs"),
        os.path.join(dist_dir, "games", "configs"),
        dirs_exist_ok=True,
    )

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

    m["app"]["version"]      = version
    m["app"]["download_url"] = download_url

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)

    # ── 8. Git commit + push ──────────────────────────────────────────────────
    run(["git", "add", "manifest.json"])
    run(["git", "commit", "-m", f"Release app v{version}"])
    run(["git", "push", "origin", "main"])

    print(f"\n=== Done! ===")
    print(f"Version:  v{version}  ({size_mb} MB)")
    print(f"Release:  https://github.com/{REPO}/releases/tag/{tag}")
    print("Old users will see the update banner on next app launch.")

if __name__ == "__main__":
    main()
