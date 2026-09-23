#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v python3 >/dev/null || { echo 'Python 3.12+ is required.' >&2; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required"'
docker compose version >/dev/null
docker info >/dev/null
if [[ ! -x .venv/bin/python ]]; then python3 -m venv .venv; fi
.venv/bin/python -m ensurepip --upgrade
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e backend -e host-runner
if [[ ! -f .env ]]; then cp .env.example .env; fi
echo 'Dependencies ready. Configure existing integrations in .env, then run ./scripts/start.sh.'
