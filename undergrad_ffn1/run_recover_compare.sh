#!/usr/bin/env bash
# Source-only patch + report recovery from completed runs. No synthesis command.
set -euo pipefail
recovery_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$recovery_dir"
exec python3 tools/recover_sweep.py "$@"
