# Ghidra headless script — يكشف تدفّق تحميل الخط في foundation.exe
# @category Foundation
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

fm = currentProgram.getFunctionManager()
ref = currentProgram.getReferenceManager()
base = currentProgram.getImageBase().getOffset()
mon = ConsoleTaskMonitor()

ifc = DecompInterface()
ifc.openProgram(currentProgram)


def decompile(func, tag):
    print("\n==================== %s : %s @ %s ====================" % (
        tag, func.getName(), func.getEntryPoint()))
    r = ifc.decompileFunction(func, 90, mon)
    if r and r.decompileCompleted():
        print(r.getDecompiledFunction().getC())
    else:
        print("  (decompile failed)")


# 1) دالة addFont — تحوي xref لـ "FreeType is not initialized" عند 0x1403d42b8
addfont = fm.getFunctionContaining(toAddr(0x1403d42b8))
if addfont:
    decompile(addfont, "addFont")
    # اطبع كل دوال يستدعيها addFont (للتتبّع)
    print("\n--- called functions in addFont ---")
    called = set()
    body = addfont.getBody()
    inst = currentProgram.getListing().getInstructions(body, True)
    for i in inst:
        for ref0 in i.getReferencesFrom():
            if ref0.getReferenceType().isCall():
                t = fm.getFunctionAt(ref0.getToAddress())
                nm = t.getName() if t else "?"
                key = (ref0.getToAddress().toString(), nm)
                if key not in called:
                    called.add(key)
                    print("  call %s  %s" % key)

# 2) ابحث عن دوال تستورد FreeType: ابحث عن السلسلة "cmap"/"glyf"/"FT_" refs
print("\n--- searching FT_New_Memory_Face style funcs (flags=1 + Open_Args) ---")
# نبحث عن الدوال الصغيرة التي تُمرَّر إليها (memory_base,size) وتنادي دالة كبيرة مشتركة.
# نترك التفاصيل لقراءة decompile addFont أعلاه.
print("DONE")
