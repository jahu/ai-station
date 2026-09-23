#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# No host Node installation required; only this project's frontend is mounted.
exec docker run --rm --init --user "$(id -u):$(id -g)" \
  --cap-drop ALL --security-opt no-new-privileges \
  -e npm_config_cache=/tmp/npm -v "$PWD/frontend:/workspace" -w /workspace \
  node:22-alpine npm "$@"
