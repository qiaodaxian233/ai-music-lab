#!/bin/bash
# 启动 ACE-Step Gradio UI,针对 12GB VRAM 优化
set -e
cd "$(dirname "$0")/.."

if [ ! -d "ACE-Step-1.5" ]; then
  echo "❌ ACE-Step-1.5 not found. 先跑 bash setup.sh"
  exit 1
fi

if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

cd ACE-Step-1.5

# 12GB VRAM 优化:
#   --torch_compile true        ← 编译加速(首次启动慢1-2分钟,稳态快20-30%)
#   --cpu_offload true          ← 不活跃层放 CPU,显存吃紧时必开
#   --overlapped_decode true    ← DiT 和 VAE 解码重叠,省时间
acestep \
  --torch_compile true \
  --cpu_offload true \
  --overlapped_decode true \
  --port 7860
