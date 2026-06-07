"""
tools/foundation/find_ft.py
===========================
يبحث عن FT_New_Memory_Face داخل foundation.exe (static FreeType، بلا رموز).

البصمة: الدالة تبني FT_Open_Args على المكدّس:
    args.flags(+0)        = FT_OPEN_MEMORY (1)   → mov dword [rsp+D], 1
    args.memory_base(+8)  = file_base (rdx)       → mov [rsp+D+8], rdx
    args.memory_size(+16) = file_size (r8)        → mov [rsp+D+0x10], r8
ثم: lea rdx, [rsp+D] ; call FT_Open_Face

نمسح .text عن `C7 44 24 D 01 00 00 00` (mov dword[rsp+D],1) ثم نتحقّق من وجود
تخزين rdx عند D+8 و r8 عند D+0x10 ضمن نافذة قريبة، ونلتقط هدف الـ call.
"""
import sys, struct
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

EXE = r"D:/SteamLibrary/steamapps/common/Foundation/foundation.exe"


def main():
    pe = pefile.PE(EXE, fast_load=True)
    image_base = pe.OPTIONAL_HEADER.ImageBase
    text = None
    for s in pe.sections:
        name = s.Name.rstrip(b"\x00").decode("latin1")
        if name == ".text":
            text = s
            break
    data = text.get_data()
    text_va = image_base + text.VirtualAddress
    print(f"image_base=0x{image_base:x}  .text VA=0x{text_va:x}  size={len(data)}")

    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = False

    # 1) جد كل mov dword ptr [rsp+D], 1  →  C7 44 24 D 01 00 00 00
    candidates = []
    i = 0
    pat = b"\xC7\x44\x24"
    while True:
        j = data.find(pat, i)
        if j < 0:
            break
        D = data[j + 3]
        imm = struct.unpack_from("<I", data, j + 4)[0]
        if imm == 1:
            candidates.append((j, D))
        i = j + 1
    print(f"عدد mov dword[rsp+D],1 = {len(candidates)}")

    # 2) لكل مرشّح (flags=FT_OPEN_MEMORY=1 في [rsp+D]): ابحث عن تمرير &args في rdx
    #    lea rdx,[rsp+D] = 48 8D 54 24 D  ثم call قريب → نمط FT_Open_Face(lib,&args,...)
    hits = []
    for off, D in candidates:
        lea_rdx_rsp = bytes([0x48, 0x8D, 0x54, 0x24, D])
        win = data[off: off + 90]
        p = win.find(lea_rdx_rsp)
        if p >= 0:
            # تأكّد من وجود call بعد الـ lea مباشرة (خلال 12 بايت)
            tail = win[p: p + 16]
            if b"\xE8" in tail:
                va = text_va + off
                hits.append((off, D, va))

    print(f"\n=== مرشّحات FT_New_Memory_Face: {len(hits)} ===")
    for off, D, va in hits:
        # حاول قراءة هدف الـ call التالي (E8 rel32) خلال 96 بايت
        call_info = ""
        seg = data[off: off + 120]
        k = seg.find(b"\xE8")
        if k >= 0 and k + 5 <= len(seg):
            rel = struct.unpack_from("<i", seg, k + 1)[0]
            call_src_va = va + k + 5
            target = call_src_va + rel
            call_info = f"  call→0x{target:x}"
        print(f"  VA=0x{va:x}  D=0x{D:x}{call_info}")

    # اطبع disassembly لأول مرشّحين للتأكيد البصري
    for off, D, va in hits[:2]:
        print(f"\n--- disasm @0x{va:x} ---")
        start = max(0, off - 32)
        for ins in md.disasm(data[start: off + 96], text_va + start):
            print(f"  0x{ins.address:x}: {ins.mnemonic} {ins.op_str}")
            if ins.address > va + 70:
                break


if __name__ == "__main__":
    main()
