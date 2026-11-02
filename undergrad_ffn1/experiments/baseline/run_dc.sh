#!/usr/bin/env bash
# Launch from any cwd after uploading backend/ to the current user's Desktop.
set -euo pipefail
backend_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
allow_modified_rtl=0
while (($#)); do
    case "$1" in
        --allow-modified-rtl) allow_modified_rtl=1 ;;
        --soc) export KWT_SYNTHESIS_SCOPE=soc ;;
        --accelerator) export KWT_SYNTHESIS_SCOPE=accelerator ;;
        -h|--help)
            printf '%s\n' 'Usage: bash run_dc.sh [--soc|--accelerator] [--allow-modified-rtl]' \
                'Default scope: reference SoC (E203, accelerator, shared SRAM and TCMs).' \
                'Allow intentional RTL hash changes with warnings; all other checks remain enabled.'
            exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done
# Bash before 4.4 treats an empty array as unset under `set -u`.
if [[ "$allow_modified_rtl" == 1 ]]; then
    python3 "$backend_dir/tools/check_package.py" --allow-modified-rtl
else
    python3 "$backend_dir/tools/check_package.py"
fi
if command -v tclsh >/dev/null 2>&1; then
    tclsh "$backend_dir/script/preflight.tcl"
fi
if ! command -v dc_shell >/dev/null 2>&1; then
    printf '%s\n' 'dc_shell is not on PATH. Source the server-provided Synopsys environment first.' >&2
    exit 1
fi
mkdir -p -- "$backend_dir/run"
launch_log="$backend_dir/run/launch_$(date +%Y%m%d_%H%M%S)_$$.log"
cd -- "$backend_dir"
dc_shell -f "$backend_dir/script/run_all.tcl" 2>&1 | tee "$launch_log"
