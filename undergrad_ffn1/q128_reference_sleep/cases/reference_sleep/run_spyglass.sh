#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
mode=${1:-lint}
if (( $# > 1 )) || [[ $mode != lint && $mode != gating && $mode != profile ]]; then
    printf 'Usage: bash run_spyglass.sh [lint|gating|profile]\n' >&2
    exit 2
fi
sg=${KWT_SG_SHELL:-sg_shell}
if ! command -v "$sg" >/dev/null 2>&1; then
    printf 'Classic SpyGlass sg_shell is missing. Load SpyGlass or set KWT_SG_SHELL.\n' >&2
    exit 1
fi
if [[ $mode != lint && -z ${KWT_SPYGLASS_LIB:-} && -z ${KWT_SPYGLASS_SGLIB:-} ]]; then
    printf 'SpyGlass Power needs a cell library. Set KWT_SPYGLASS_LIB (.lib) or KWT_SPYGLASS_SGLIB (.sglib).\n' >&2
    exit 2
fi
if [[ $mode == profile && -z ${KWT_SPYGLASS_SGDC:-} && -z ${KWT_SPYGLASS_SAIF:-} ]]; then
    printf 'Set KWT_SPYGLASS_SAIF to the task SAIF or supply an activity SGDC in KWT_SPYGLASS_SGDC.\n' >&2
    exit 2
fi

mkdir -p run/spyglass
attempt=$(mktemp -d "run/spyglass/${mode}.XXXXXXXX")
export KWT_SG_MODE="$mode" KWT_SG_RUN="$PWD/$attempt"
log="$attempt/launch.log"
printf 'Q128_SPYGLASS_START %s log=%s\n' "$mode" "$log"
"$sg" -tcl "$PWD/script/spyglass.tcl" </dev/null 2>&1 | tee "$log"
if ! grep -qx 'Q128_SPYGLASS_REPORT_WRITTEN' "$log" || [[ ! -s $attempt/messages.rpt ]]; then
    printf 'SpyGlass did not finish the requested goal. Inspect %s\n' "$log" >&2
    exit 1
fi
find "$attempt" -type f \( -iname '*.rpt' -o -iname '*.csv' -o -iname '*power*' -o -iname '*gat*' \) | sort > "$attempt/report_files.txt"
if grep -Eiq '^[[:space:]*]*(Total|Reported Messages)[[:space:]]*:[[:space:]]*[1-9][0-9]*[[:space:]]+fatals?([[:space:],]|$)' "$log"; then
    printf 'Q128_SPYGLASS_FATAL %s (reports retained; analysis incomplete)\n' "$attempt" >&2
    grep -nE 'PECHECK28|Could not check out' "$log" | head -n 12 >&2 || true
    exit 1
fi
printf 'Q128_SPYGLASS_REPORTS %s\n' "$PWD/$attempt"
