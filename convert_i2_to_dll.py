import json
import sys
import os

GAME_PATH = r'C:\Program Files (x86)\Steam\steamapps\common\Flotsam'
I2_FULL = os.path.join(GAME_PATH, 'BepInEx', 'config', 'ArabicGameTranslator', 'flotsam_i2_full.json')
DLL_JSON = os.path.join(GAME_PATH, 'BepInEx', 'config', 'ArabicGameTranslator', 'flotsam_i2_translated_only.json')

print("Converting I2Languages format -> DLL format...")

with open(I2_FULL, 'r', encoding='utf-8') as f:
    i2data = json.load(f)

terms = i2data.get('mSource', {}).get('mTerms', {}).get('Array', [])

entries = []
for term in terms:
    name = term.get('Term', '')
    langs = term.get('Languages', {}).get('Array', [])
    
    if not name or not langs:
        continue
    
    arabic = langs[-1] if langs else ''
    
    if arabic and arabic.strip():
        entries.append({
            'key': name,
            'Arabic': arabic
        })

with open(DLL_JSON, 'w', encoding='utf-8') as f:
    json.dump({'entries': entries}, f, ensure_ascii=False, indent=2)

print(f"Converted {len(entries)} entries")
print(f"Saved to: {DLL_JSON}")
print()
print("Now restart Flotsam to apply.")
