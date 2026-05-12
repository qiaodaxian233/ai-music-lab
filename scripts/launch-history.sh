#!/bin/bash
# 启动历史浏览器 (Gradio,端口 7861)
set -e
cd "$(dirname "$0")/.."

if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python scripts/history-ui.py
