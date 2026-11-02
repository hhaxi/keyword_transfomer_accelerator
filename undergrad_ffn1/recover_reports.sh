#!/usr/bin/env bash
# Works when invoked from the server's default csh/tcsh as: bash recover_reports.sh PATH
set -euo pipefail
if [[ $# -ne 1 || $1 == --help || $1 == -h ]]; then
    printf '%s\n' 'Usage: bash recover_reports.sh /absolute/path/to/design_compiled.ddc'
    if [[ $# -eq 1 ]]; then exit 0; else exit 2; fi
fi
if [[ ! -f $1 ]]; then printf 'DDC not found: %s\n' "$1" >&2; exit 1; fi
backend_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export KWT_RECOVER_DDC="$1"
exec dc_shell -f "$backend_dir/script/recover_reports.tcl"
