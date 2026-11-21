#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
# --report-only never invokes the per-case EDA scripts.
exec "${PYTHON:-python3}" run_combined.py "$@"
