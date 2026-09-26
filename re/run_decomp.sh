#!/bin/sh
# Decompile functions from the Baofeng CPS with headless Ghidra.
#
# usage: run_decomp.sh out.c addr [addr...]
#
# Needs:
#   GHIDRA_HOME  Ghidra install dir (the one containing support/analyzeHeadless)
#   CPS_EXE      path to "DMR CPS.exe" (file "16" in the extracted v1.60 installer)
# The first run imports and analyses the binary into ./ghidra_proj.
set -e
cd "$(dirname "$0")"
: "${GHIDRA_HOME:?set GHIDRA_HOME to your Ghidra install directory}"
HEADLESS="$GHIDRA_HOME/support/analyzeHeadless"
[ -x "$HEADLESS" ] || HEADLESS="$GHIDRA_HOME/libexec/support/analyzeHeadless"
out=$1; shift

if [ ! -d ghidra_proj ]; then
    : "${CPS_EXE:?set CPS_EXE to the path of DMR CPS.exe for the first run}"
    mkdir -p ghidra_proj
    cp "$CPS_EXE" DMR_CPS.exe
    "$HEADLESS" ghidra_proj dm32uv -import DMR_CPS.exe >import.log 2>&1
    # Functions that Ghidra's auto-analysis misses: the Read/Write dialog worker.
    "$HEADLESS" ghidra_proj dm32uv -process DMR_CPS.exe -noanalysis \
        -scriptPath "$PWD" -postScript MakeFuncs.java 00449ae0 0044a210 >makefuncs.log 2>&1
fi

"$HEADLESS" ghidra_proj dm32uv -process DMR_CPS.exe -noanalysis \
    -scriptPath "$PWD" -postScript Decomp.java "$PWD/$out" "$@" 2>&1 \
    | grep -E 'ERROR|Exception' || true
