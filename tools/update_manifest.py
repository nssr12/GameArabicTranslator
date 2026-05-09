"""
tools/update_manifest.py
Called by publish_translation.bat to update manifest.json with real file sizes.
Usage: python update_manifest.py <game_id> <version> <ready_dir>
"""
import sys, json, os

game_id   = sys.argv[1]
version   = sys.argv[2]
ready_dir = sys.argv[3]
repo      = "nssr12/GameArabicTranslator"
tag       = f"translation-{game_id}-v{version}"

manifest_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "manifest.json")

with open(manifest_path, encoding="utf-8") as f:
    m = json.load(f)

if game_id not in m.get("translations", {}):
    print(f"[update_manifest] ERROR: '{game_id}' not found in manifest.json")
    sys.exit(1)

t = m["translations"][game_id]
t["version"] = version

# Calculate total size in MB
total_bytes = 0
size_map = {}
for fname in os.listdir(ready_dir):
    fpath = os.path.join(ready_dir, fname)
    if os.path.isfile(fpath) and fname.endswith((".pak", ".ucas", ".utoc")):
        size = os.path.getsize(fpath)
        size_map[fname] = size
        total_bytes += size

t["size_mb"] = round(total_bytes / (1024 * 1024))

for f in t.get("files", []):
    f["url"] = f"https://github.com/{repo}/releases/download/{tag}/{f['name']}"
    if f["name"] in size_map:
        f["size"] = size_map[f["name"]]

with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(m, f, ensure_ascii=False, indent=2)

print(f"[update_manifest] {game_id} v{version} — {t['size_mb']} MB — OK")
