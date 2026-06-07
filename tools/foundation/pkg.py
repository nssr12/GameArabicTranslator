"""
tools/foundation/pkg.py
=======================
محلّل/معدّل صيغة حزمة Foundation (.package).

اكتُشفت الصيغة بالهندسة العكسية:
  Header: [u32 version][32 bytes ascii hash][...سجلات...]
  TOC record: [u32 name_len][name bytes][u8 flag][u64 data_offset][u64 data_size]

ملاحظة: السجلات الأولى (enum/metadata) قد تختلف، لذا نمسح الملف ونلتقط
كل سجل يطابق النمط ويكون offset+size ضمن حدود الملف (تحقّق سلامة).

الاستخدام:
    python pkg.py list   <package>            # اسرد كل الأصول (الخطوط مميّزة)
    python pkg.py extract <package> <name> <out>
    python pkg.py find   <package> <substr>   # ابحث بالاسم
"""
from __future__ import annotations
import struct, sys, os, re

PRINTABLE = re.compile(rb'^[\x20-\x7e]+$')


def scan_toc(path: str):
    """يمسح الملف ويُرجع قائمة (name, flag, offset, size, record_pos).
    يلتقط السجلات بنمط [u32 len][name][u8][u64 off][u64 size] مع تحقّق الحدود."""
    fsize = os.path.getsize(path)
    entries = []
    CHUNK = 64 * 1024 * 1024
    with open(path, 'rb') as f:
        # نقرأ منطقة الرأس الكبيرة التي تحوي الـ TOC (عادة < 50MB).
        # TOC قبل بلوكات البيانات الضخمة. نقرأ أول 64MB ونمسحها.
        data = f.read(CHUNK)
    n = len(data)
    i = 0
    # امسح بحثاً عن سجلات: u32 len معقول (1..200) + اسم printable + 17 بايت trailer
    while i < n - 4:
        ln = struct.unpack_from('<I', data, i)[0]
        if 1 <= ln <= 200 and i + 4 + ln + 17 <= n:
            name = data[i+4:i+4+ln]
            if PRINTABLE.match(name):
                p = i + 4 + ln
                flag = data[p]
                off = struct.unpack_from('<Q', data, p+1)[0]
                size = struct.unpack_from('<Q', data, p+9)[0]
                if 0 < off < fsize and 0 < size <= fsize and off + size <= fsize:
                    entries.append({
                        'name': name.decode('latin1'),
                        'flag': flag, 'offset': off, 'size': size,
                        'rec_pos': i,                 # موقع السجل في الملف
                        'off_field_pos': p + 1,       # موقع u64 offset (للتعديل)
                        'size_field_pos': p + 9,      # موقع u64 size (للتعديل)
                    })
                    i = p + 17
                    continue
        i += 1
    return entries


def extract(path: str, name: str, out: str):
    ents = scan_toc(path)
    match = [e for e in ents if e['name'] == name]
    if not match:
        match = [e for e in ents if name in e['name']]
    if not match:
        print(f"لم يُعثر على: {name}")
        return 1
    e = match[0]
    with open(path, 'rb') as f:
        f.seek(e['offset']); blob = f.read(e['size'])
    with open(out, 'wb') as g:
        g.write(blob)
    print(f"✓ استُخرج {e['name']} ({e['size']} بايت) → {out}")
    print(f"   أول 4 بايت: {blob[:4].hex()}")
    return 0


def main():
    if len(sys.argv) < 3:
        print(__doc__); return 1
    cmd, path = sys.argv[1], sys.argv[2]
    if cmd == 'list':
        ents = scan_toc(path)
        print(f"إجمالي الأصول الملتقطة: {len(ents)}")
        fonts = [e for e in ents if re.search(r'font|noto|\.ttf|\.otf|\.ttc', e['name'], re.I)]
        print(f"\n=== أصول الخطوط ({len(fonts)}) ===")
        for e in fonts:
            print(f"  {e['name']:<45} off={e['offset']:>12} size={e['size']:>9} flag={e['flag']}")
    elif cmd == 'find':
        sub = sys.argv[3]
        for e in scan_toc(path):
            if sub.lower() in e['name'].lower():
                print(f"  {e['name']:<50} off={e['offset']:>12} size={e['size']:>9}")
    elif cmd == 'extract':
        return extract(path, sys.argv[3], sys.argv[4])
    return 0


if __name__ == '__main__':
    sys.exit(main())
