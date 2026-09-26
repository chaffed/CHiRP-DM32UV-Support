// List functions that reference the CPS's per-tag page buffers (pointer globals).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.util.*;

public class BufRefs extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();   // pairs: label hexaddr
        for (int i = 0; i + 1 < args.length; i += 2) {
            Map<String,Integer> byFunc = new TreeMap<>();
            for (Reference r : getReferencesTo(toAddr(Long.parseLong(args[i + 1], 16)))) {
                Function f = getFunctionContaining(r.getFromAddress());
                String n = f == null ? "?" + r.getFromAddress() : f.getName() + "@" + f.getEntryPoint();
                byFunc.merge(n, 1, Integer::sum);
            }
            println("BUF " + args[i] + " " + args[i + 1] + " refs=" + byFunc);
        }
    }
}
