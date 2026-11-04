#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Subprocess tests must import this checkout too. A reused editable virtualenv
# can otherwise resolve children against the original, older working tree.
export PYTHONPATH="$PWD/backend:$PWD/host-runner:$PWD/scripts${PYTHONPATH:+:$PYTHONPATH}"
.venv/bin/ruff check backend host-runner scripts packaging
.venv/bin/ruff format --check backend host-runner scripts packaging
.venv/bin/python -m pytest -q
