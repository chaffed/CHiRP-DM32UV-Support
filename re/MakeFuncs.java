// Disassemble and create functions at the given entry addresses, then re-run analysis.
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.*;
public class MakeFuncs extends GhidraScript {
    public void run() throws Exception {
        for (String a : getScriptArgs()) {
            Address ad = toAddr(Long.parseLong(a, 16));
            disassemble(ad);
            if (getFunctionAt(ad) == null) new CreateFunctionCmd(ad).applyTo(currentProgram, monitor);
            println("func " + a + " -> " + getFunctionAt(ad));
        }
        analyzeChanges(currentProgram);
    }
}
