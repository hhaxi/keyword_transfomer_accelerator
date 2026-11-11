#!/usr/bin/env bash
# Bash 4.3 compatible; source the server Synopsys environment first.
set -euo pipefail
backend_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if (($# == 0)); then
    python3 "$backend_dir/tools/power_server.py" --dc --collect
else
    python3 "$backend_dir/tools/power_server.py" "$@"
fi
