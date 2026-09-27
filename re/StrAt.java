// Print the C strings at the given addresses. args: hexaddr...
import ghidra.app.script.GhidraScript;
public class StrAt extends GhidraScript {
    public void run() throws Exception {
        for (String a : getScriptArgs()) {
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < 40; i++) {
                byte b = getByte(toAddr(Long.parseLong(a, 16) + i));
                if (b == 0) break;
                sb.append((char) (b & 0xff));
            }
            println("STRAT " + a + " = " + sb);
        }
    }
}
