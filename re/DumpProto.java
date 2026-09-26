// Decompile functions that reference protocol strings or serial I/O imports.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.mem.*;
import java.util.*;
import java.io.*;

public class DumpProto extends GhidraScript {
    public void run() throws Exception {
        String out = getScriptArgs()[0];
        PrintWriter pw = new PrintWriter(new FileWriter(out));
        String[] targets = {"PSEARCH","PASSSTA","SYSINFO","PROGRAM","66660501","374612","bfcps",
                            "\\\\.\\COM%d","(*.enc)|*.enc||","IDS_READ_FAIL"};
        String[] imports = {"WriteFile","ReadFile","CreateFileA","SetCommState","PurgeComm"};
        Set<Function> funcs = new LinkedHashSet<>();
        Map<Function,List<String>> why = new HashMap<>();
        Memory mem = currentProgram.getMemory();
        for (String t : targets) {
            byte[] b = (t + "\0").getBytes("latin1");
            Address a = mem.findBytes(currentProgram.getMinAddress(), b, null, true, monitor);
            while (a != null) {
                pw.println("STRING " + t + " @ " + a);
                for (Reference r : getReferencesTo(a)) {
                    Function f = getFunctionContaining(r.getFromAddress());
                    if (f != null) { funcs.add(f); why.computeIfAbsent(f,k->new ArrayList<>()).add(t+"@"+r.getFromAddress()); }
                }
                a = mem.findBytes(a.add(1), b, null, true, monitor);
            }
        }
        SymbolTable st = currentProgram.getSymbolTable();
        for (String imp : imports) {
            for (Symbol s : st.getSymbols(imp)) {
                for (Reference r : getReferencesTo(s.getAddress())) {
                    for (Reference r2 : getReferencesTo(r.getFromAddress())) {}
                    Function f = getFunctionContaining(r.getFromAddress());
                    if (f != null) { funcs.add(f); why.computeIfAbsent(f,k->new ArrayList<>()).add(imp); }
                    // IAT thunk: follow references to the pointer
                    for (Reference r3 : getReferencesTo(r.getFromAddress())) {
                        Function g = getFunctionContaining(r3.getFromAddress());
                        if (g != null) { funcs.add(g); why.computeIfAbsent(g,k->new ArrayList<>()).add(imp); }
                    }
                }
            }
        }
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        for (Function f : funcs) {
            DecompileResults res = di.decompileFunction(f, 120, monitor);
            pw.println("\n//==== " + f.getName() + " @ " + f.getEntryPoint() + " refs=" + why.get(f));
            pw.println("//callers: " + f.getCallingFunctions(monitor));
            pw.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// decompile failed");
        }
        pw.close();
        println("functions dumped: " + funcs.size());
    }
}
