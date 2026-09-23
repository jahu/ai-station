#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/ruff check backend host-runner
.venv/bin/ruff format --check backend host-runner
.venv/bin/python -m pytest -q
