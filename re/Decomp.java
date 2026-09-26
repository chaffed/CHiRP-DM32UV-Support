// Decompile given functions (and optionally their callers) after fixing the _chkstk call fixup.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class Decomp extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Function chk = getFunctionAt(toAddr(0x004b7320));
        if (chk != null) {
            chk.setName("__alloca_probe", SourceType.USER_DEFINED);
            chk.setCallFixup("alloca_probe");
        }
        PrintWriter pw = new PrintWriter(new FileWriter(args[0]));
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        for (int i = 1; i < args.length; i++) {
            Function f = getFunctionAt(toAddr(Long.parseLong(args[i], 16)));
            if (f == null) { pw.println("// no function at " + args[i]); continue; }
            DecompileResults res = di.decompileFunction(f, 300, monitor);
            pw.println("\n//==== " + f.getName() + " @ " + f.getEntryPoint());
            pw.println("//callers: " + f.getCallingFunctions(monitor));
            pw.println("//callees: " + f.getCalledFunctions(monitor));
            pw.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// failed: " + res.getErrorMessage());
        }
        pw.close();
    }
}
