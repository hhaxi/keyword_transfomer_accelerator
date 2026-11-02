#!/usr/bin/env bash
# All paths derive from this upload directory, independent of launch cwd.
set -euo pipefail
compare_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
action=dc
scope=soc
jobs=2
repeat=0
resume=0
while (($#)); do
    case "$1" in
        --dc) action=dc ;;
        --sim) action=sim ;;
        --all) action=all ;;
        --scope) shift; scope="$1" ;;
        --jobs) shift; jobs="$1" ;;
        --repeat-identical-hardware) repeat=1 ;;
        --resume) resume=1 ;;
        -h|--help)
            printf '%s\n' 'Usage: bash run_compare.sh [--dc|--sim|--all] [--scope soc|accelerator|both] [--jobs N] [--resume] [--repeat-identical-hardware]' \
                'Default: 16-case DC comparison, reusing 4 identical-hardware groups, full SoC scope.' \
                '--sim/--all require Python3, NumPy, RV32 GCC, Verilator and Make.'
            exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done
cd -- "$compare_dir"
python3 tools/sweep.py prepare
if [[ "$action" == sim || "$action" == all ]]; then
    if [[ "$resume" == 1 ]]; then
        python3 tools/sweep.py sim --tasks 12 --jobs "$jobs" --resume
    else
        python3 tools/sweep.py sim --tasks 12 --jobs "$jobs"
    fi
fi
if [[ "$action" == dc || "$action" == all ]]; then
    if [[ "$repeat" == 1 ]]; then
        python3 tools/sweep.py dc --scope "$scope" --repeat-identical-hardware
    else
        python3 tools/sweep.py dc --scope "$scope"
    fi
fi
python3 tools/sweep.py collect
