#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/frontend.sh ci
exec ./scripts/start.sh --dev "$@"
