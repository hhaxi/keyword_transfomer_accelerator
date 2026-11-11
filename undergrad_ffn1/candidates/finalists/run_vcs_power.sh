#!/usr/bin/env bash
# Bash 4.3; source the server VCS/DC environment before launching.
set -euo pipefail
backend_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python3 "$backend_dir/tools/vcs_power.py" "$@"
