// يكشف تدفّق تحميل الخط في foundation.exe — Java (يعمل headless بلا PyGhidra)
// @category Foundation
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.symbol.Reference;
import java.util.LinkedHashSet;
import java.util.Set;

public class FindFreeType extends GhidraScript {
    DecompInterface ifc;

    void dump(Function f, String tag) {
        println("\n========== " + tag + " : " + f.getName() + " @ " + f.getEntryPoint() + " ==========");
        DecompileResults r = ifc.decompileFunction(f, 120, monitor);
        if (r != null && r.decompileCompleted())
            println(r.getDecompiledFunction().getC());
        else
            println("  (decompile failed)");
    }

    void listCalls(Function f) {
        println("\n--- calls in " + f.getName() + " ---");
        Set<String> seen = new LinkedHashSet<>();
        FunctionManager fm = currentProgram.getFunctionManager();
        InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            for (Reference ref : ins.getReferencesFrom()) {
                if (ref.getReferenceType().isCall()) {
                    Function t = fm.getFunctionAt(ref.getToAddress());
                    String nm = (t != null ? t.getName() : "?");
                    String line = "  " + ins.getAddress() + " call " + ref.getToAddress() + "  " + nm;
                    if (seen.add(line)) println(line);
                }
            }
        }
    }

    @Override
    public void run() throws Exception {
        ifc = new DecompInterface();
        ifc.openProgram(currentProgram);
        FunctionManager fm = currentProgram.getFunctionManager();

        Address a = toAddr(0x1403d42b8L); // xref لـ "FreeType is not initialized"
        Function addFont = fm.getFunctionContaining(a);
        if (addFont == null) { println("addFont not found!"); return; }
        dump(addFont, "addFont");
        listCalls(addFont);
        println("\nDONE");
    }
}
