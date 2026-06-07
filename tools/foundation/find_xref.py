"""
tools/foundation/find_xref.py <string>
======================================
يجد سلسلة ASCII داخل foundation.exe ويبحث عن كل التعليمات التي تشير إليها
بإزاحة rip-relative (lea reg,[rip+disp] = 48/4C 8D ?? disp32).
يطبع disassembly حول كل XREF لتحديد دوال المحرّك المعنيّة.
"""
import sys, struct
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

EXE = r"D:/SteamLibrary/steamapps/common/Foundation/foundation.exe"


def rva_of_offset(pe, off):
    for s in pe.sections:
        if s.PointerToRawData <= off < s.PointerToRawData + s.SizeOfRawData:
            return s.VirtualAddress + (off - s.PointerToRawData)
    return None


def main():
    target = sys.argv[1].encode() if len(sys.argv) > 1 else b"FreeType is not initialized"
    pe = pefile.PE(EXE, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    raw = open(EXE, "rb").read()

    # 1) جد كل ظهور للسلسلة + VA
    str_vas = []
    i = 0
    while True:
        j = raw.find(target, i)
        if j < 0:
            break
        rva = rva_of_offset(pe, j)
        if rva is not None:
            str_vas.append(base + rva)
        i = j + 1
    print(f"السلسلة {target!r}: {len(str_vas)} ظهور → " + ", ".join(hex(v) for v in str_vas))
    if not str_vas:
        return

    # 2) .text
    text = next(s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text")
    tdata = text.get_data()
    tva = base + text.VirtualAddress

    # 3) امسح lea reg,[rip+disp32] (48/4C 8D) واحسب الهدف
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    targets = set(str_vas)
    xrefs = []
    n = len(tdata)
    idx = 0
    while idx < n - 7:
        b0 = tdata[idx]
        if b0 in (0x48, 0x4C) and tdata[idx + 1] == 0x8D:
            modrm = tdata[idx + 2]
            # rip-relative: mod=00, rm=101
            if (modrm & 0xC7) == 0x05:
                disp = struct.unpack_from("<i", tdata, idx + 3)[0]
                insn_va = tva + idx
                tgt = insn_va + 7 + disp
                if tgt in targets:
                    xrefs.append((insn_va, idx, tgt))
        idx += 1

    print(f"\n=== XREFs: {len(xrefs)} ===")
    for insn_va, idx, tgt in xrefs:
        print(f"\n--- xref @0x{insn_va:x} → str 0x{tgt:x} ---")
        start = max(0, idx - 60)
        for ins in md.disasm(tdata[start: idx + 40], tva + start):
            mark = "  <<<" if ins.address == insn_va else ""
            print(f"  0x{ins.address:x}: {ins.mnemonic} {ins.op_str}{mark}")


if __name__ == "__main__":
    main()
