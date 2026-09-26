// Decompile every function that references a global (e.g. a CPS page buffer pointer).
// args: out.c hexaddr
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class DecompRefs extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Function chk = getFunctionAt(toAddr(0x004b7320));
        if (chk != null) {
            chk.setName("__alloca_probe", SourceType.USER_DEFINED);
            chk.setCallFixup("alloca_probe");
        }
        Set<Function> funcs = new TreeSet<>(Comparator.comparing(Function::getEntryPoint));
        for (Reference r : getReferencesTo(toAddr(Long.parseLong(args[1], 16)))) {
            Function f = getFunctionContaining(r.getFromAddress());
            if (f != null) funcs.add(f);
        }
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        PrintWriter pw = new PrintWriter(new FileWriter(args[0]));
        for (Function f : funcs) {
            DecompileResults res = di.decompileFunction(f, 120, monitor);
            pw.println("\n//==== " + f.getName() + " @ " + f.getEntryPoint());
            pw.println("//callers: " + f.getCallingFunctions(monitor));
            pw.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// failed: " + res.getErrorMessage());
        }
        pw.close();
        println("decompiled " + funcs.size());
    }
}
