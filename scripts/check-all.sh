#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/check.sh
./scripts/frontend.sh run format:check
./scripts/frontend.sh run lint
./scripts/frontend.sh run typecheck
./scripts/frontend.sh test
./scripts/frontend.sh run build
docker compose config --quiet
docker compose -f compose.yaml -f compose.dev.yaml config --quiet
docker build -t ai-station:local-check .
