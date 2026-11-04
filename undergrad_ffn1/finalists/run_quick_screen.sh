#!/usr/bin/env bash
# Same task00 for all four candidates; old full-study files stay untouched.
set -euo pipefail
backend_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python3 "$backend_dir/tools/quick_screen.py" "$@"
