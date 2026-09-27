// Decompile the functions that call an external symbol (e.g. DDX_Control)
// and whose C text contains every given marker.
// args: out.c SymbolName marker [marker ...]
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.address.*;
import java.io.*;
import java.util.*;

public class DecompCallers extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Function chk = getFunctionAt(toAddr(0x004b7320));
        if (chk != null) {
            chk.setName("__alloca_probe", SourceType.USER_DEFINED);
            chk.setCallFixup("alloca_probe");
        }
        Set<Function> funcs = new TreeSet<>(Comparator.comparing(Function::getEntryPoint));
        for (Symbol s : currentProgram.getSymbolTable().getSymbols(args[1])) {
            List<Address> targets = new ArrayList<>();
            targets.add(s.getAddress());
            for (Reference r : getReferencesTo(s.getAddress())) targets.add(r.getFromAddress());
            for (Address t : targets)
                for (Reference r : getReferencesTo(t)) {
                    Function f = getFunctionContaining(r.getFromAddress());
                    if (f != null) funcs.add(f);
                }
        }
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        PrintWriter pw = new PrintWriter(new FileWriter(args[0]));
        int n = 0;
        for (Function f : funcs) {
            DecompileResults res = di.decompileFunction(f, 60, monitor);
            if (!res.decompileCompleted()) continue;
            String c = res.getDecompiledFunction().getC();
            boolean ok = true;
            for (int i = 2; i < args.length; i++) ok &= c.contains(args[i]);
            if (!ok) continue;
            pw.println("\n//==== " + f.getName() + " @ " + f.getEntryPoint());
            pw.println(c);
            n++;
        }
        pw.close();
        println("callers matched: " + n + " of " + funcs.size());
    }
}
