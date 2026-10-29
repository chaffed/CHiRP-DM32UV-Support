// List the functions whose entry point lies in [lo, hi] (hex), with size and caller count.
// args: lo hi
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;

public class ListFuncs extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        long lo = Long.parseLong(a[0], 16), hi = Long.parseLong(a[1], 16);
        for (Function f : currentProgram.getFunctionManager().getFunctions(toAddr(lo), true)) {
            if (f.getEntryPoint().getOffset() > hi) break;
            println("FUNC " + f.getEntryPoint() + " size=" + f.getBody().getNumAddresses()
                    + " callers=" + f.getCallingFunctions(monitor).size()
                    + " callees=" + f.getCalledFunctions(monitor));
        }
    }
}
