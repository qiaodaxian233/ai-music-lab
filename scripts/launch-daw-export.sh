#!/bin/bash
# 启动 Song → DAW Export UI (Gradio, 端口 7863)
set -e
cd "$(dirname "$0")/.."

if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python scripts/song-to-daw.py
