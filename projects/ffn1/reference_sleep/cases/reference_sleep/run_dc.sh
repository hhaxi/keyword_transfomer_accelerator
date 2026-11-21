#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"

mode=${1:-clock_gate}
case "$mode" in
    baseline|clock_gate|both) ;;
    *) printf 'Usage: bash run_dc.sh [baseline|clock_gate|both]\n' >&2; exit 2 ;;
esac
if (( $# > 1 )); then
    printf 'Usage: bash run_dc.sh [baseline|clock_gate|both]\n' >&2
    exit 2
fi
if ! command -v dc_shell >/dev/null 2>&1; then
    printf 'dc_shell is missing from PATH. Load the server Synopsys environment first.\n' >&2
    exit 1
fi

mkdir -p run/launch_logs
run_one() {
    local name=$1 enable=$2 log
    log=$(mktemp "run/launch_logs/${name}.XXXXXXXX.log")
    printf 'Q128_DC_START %s log=%s\n' "$name" "$log"
    KWT_GATE_CLOCK=$enable KWT_SYNTHESIS_SCOPE=soc dc_shell -f "$PWD/script/run_all.tcl" 2>&1 | tee "$log"
}

if [[ $mode == baseline || $mode == both ]]; then
    run_one baseline 0
fi
if [[ $mode == clock_gate || $mode == both ]]; then
    run_one clock_gate 1
fi
