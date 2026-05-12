#!/bin/bash
# 启动 LoRA 数据准备 wizard (Gradio,端口 7862)
set -e
cd "$(dirname "$0")/.."

if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python scripts/lora-wizard.py
