"""tools/foundation/disasm.py <hex_va_start> <count_bytes>
يفكّك مدى من foundation.exe حول VA معيّن."""
import sys, struct
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

EXE = r"D:/SteamLibrary/steamapps/common/Foundation/foundation.exe"


def main():
    va_start = int(sys.argv[1], 16)
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    pe = pefile.PE(EXE, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    text = next(s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text")
    tva = base + text.VirtualAddress
    tdata = text.get_data()
    off = va_start - tva
    if off < 0 or off >= len(tdata):
        print("VA خارج .text"); return
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    for ins in md.disasm(tdata[off: off + count], va_start):
        b = ' '.join(f'{x:02x}' for x in ins.bytes)
        print(f"  0x{ins.address:x}: {b:<26} {ins.mnemonic} {ins.op_str}")


if __name__ == "__main__":
    main()
