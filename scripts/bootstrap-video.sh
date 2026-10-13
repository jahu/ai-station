#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Optional project-owned environment; never installs models, drivers or a service.
if [[ $# != 1 || ! -f "$1/requirements.txt" || ! -f "$1/nodes.py" ]]; then
  echo "Usage: ./scripts/bootstrap-video.sh /path/to/existing/ComfyUI" >&2
  exit 2
fi
python3 -m venv .tools/video-runtime
.tools/video-runtime/bin/python -m pip install -r "$1/requirements.txt"
echo "Video Python: $PWD/.tools/video-runtime/bin/python"
echo "Set the five video paths in .env as described in docs/video.md."
