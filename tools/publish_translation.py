"""
tools/publish_translation.py
Publishes translation files to GitHub Releases and updates manifest.json.
Usage: python publish_translation.py <game_id> <version>
"""
import sys, json, os, subprocess

REPO = "nssr12/GameArabicTranslator"

def run(cmd, check=True):
    print(f">> {' '.join(cmd)}")
    r = subprocess.run(cmd, check=check)
    return r.returncode

def main():
    if len(sys.argv) < 3:
        print("Usage: publish_translation.py <GameId> <Version>")
        sys.exit(1)

    game_id = sys.argv[1]
    version = sys.argv[2]
    tag     = f"translation-{game_id}-v{version}"

    root      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ready_dir = os.path.join(root, "mods", game_id, "ready")

    # ── 1. Check ready/ folder ────────────────────────────────────────────────
    if not os.path.isdir(ready_dir):
        print(f"[ERROR] Folder not found: {ready_dir}")
        print("Run sync (مزامنة التعديل) from the Cache page first.")
        sys.exit(1)

    pak_files = [
        os.path.join(ready_dir, f)
        for f in os.listdir(ready_dir)
        if f.endswith((".pak", ".ucas", ".utoc"))
    ]
    if not pak_files:
        print(f"[ERROR] No .pak/.ucas/.utoc files in {ready_dir}")
        sys.exit(1)

    print(f"\n=== Publishing {game_id} v{version} ===")
    for p in pak_files:
        size_mb = os.path.getsize(p) / (1024 * 1024)
        print(f"  {os.path.basename(p)}  ({size_mb:.1f} MB)")

    # ── 2. Delete old release if exists ──────────────────────────────────────
    r = subprocess.run(["gh", "release", "view", tag, "--repo", REPO],
                       capture_output=True)
    if r.returncode == 0:
        print(f"\nRelease {tag} already exists — deleting...")
        run(["gh", "release", "delete", tag, "--repo", REPO,
             "--yes", "--cleanup-tag"])
        import time; time.sleep(3)

    # ── 3. Create Release and upload files ───────────────────────────────────
    print(f"\nCreating GitHub Release {tag} ...")
    cmd = [
        "gh", "release", "create", tag,
        "--repo", REPO,
        "--title", f"{game_id} Arabic Translation v{version}",
        "--notes", f"Arabic translation for {game_id} — version {version}",
    ] + pak_files
    run(cmd)
    print("Upload complete.")

    # ── 4. Update manifest.json ───────────────────────────────────────────────
    manifest_path = os.path.join(root, "manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
        m = json.load(f)

    if game_id not in m.get("translations", {}):
        print(f"[ERROR] '{game_id}' not found in manifest.json")
        sys.exit(1)

    t = m["translations"][game_id]
    t["version"] = version

    size_map   = {os.path.basename(p): os.path.getsize(p) for p in pak_files}
    total_mb   = round(sum(size_map.values()) / (1024 * 1024))
    t["size_mb"] = total_mb

    for f in t.get("files", []):
        f["url"]  = f"https://github.com/{REPO}/releases/download/{tag}/{f['name']}"
        if f["name"] in size_map:
            f["size"] = size_map[f["name"]]

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)

    print(f"manifest.json updated — {game_id} v{version} ({total_mb} MB)")

    # ── 5. Git commit + push ──────────────────────────────────────────────────
    run(["git", "-C", root, "add", "manifest.json"])
    run(["git", "-C", root, "commit", "-m",
         f"Update manifest: {game_id} v{version} ({total_mb} MB)"])
    run(["git", "-C", root, "push", "origin", "main"])

    print(f"\n=== Done! ===")
    print(f"Release: https://github.com/{REPO}/releases/tag/{tag}")
    print("Users will see the download button on next app launch.")

if __name__ == "__main__":
    main()
