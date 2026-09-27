// For each string given, list functions that reference it and the functions they call.
// args: string...
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.mem.*;
import java.util.*;

public class StrUsers extends GhidraScript {
    public void run() throws Exception {
        Memory mem = currentProgram.getMemory();
        for (String t : getScriptArgs()) {
            byte[] b = (t + "\0").getBytes("latin1");
            Address a = mem.findBytes(currentProgram.getMinAddress(), b, null, true, monitor);
            while (a != null) {
                for (Reference r : getReferencesTo(a)) {
                    Function f = getFunctionContaining(r.getFromAddress());
                    if (f == null) { println("STR " + t + " @" + a + " ref from " + r.getFromAddress() + " (no function)"); continue; }
                    Set<String> callees = new TreeSet<>();
                    for (Function c : f.getCalledFunctions(monitor)) callees.add(c.getName());
                    println("STR " + t + " used by " + f.getName() + " callees=" + callees);
                }
                a = mem.findBytes(a.add(1), b, null, true, monitor);
            }
        }
    }
}
