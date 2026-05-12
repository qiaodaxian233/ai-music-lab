#!/bin/bash
# ai-music-lab 一键安装
set -e

cd "$(dirname "$0")"

echo "🎵 ai-music-lab 初始化"
echo ""

# 1. 检查 Python 版本
PYV=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
echo "Python 版本: $PYV"
if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11, 12) else 1)' 2>/dev/null; then
  echo "✓ Python 版本符合要求"
else
  echo "⚠ 建议 Python ≥3.11.12 (当前 $PYV)"
  echo "  Ubuntu 自带的 3.11.0rc1 是预发布版,跑 vLLM 后端会段错误"
  echo "  Ubuntu 升级:"
  echo "    sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt update"
  echo "    sudo apt install python3.11"
  read -p "继续吗? (y/N) " ans
  [ "$ans" = "y" ] || exit 1
fi

# 2. Clone ACE-Step
if [ ! -d "ACE-Step-1.5" ]; then
  echo ""
  echo "📥 Clone ACE-Step-1.5..."
  git clone https://github.com/ace-step/ACE-Step-1.5.git
else
  echo "✓ ACE-Step-1.5 已存在(跳过 clone)"
fi

# 3. 建虚拟环境
if [ ! -d ".venv" ]; then
  echo ""
  echo "🐍 创建 Python 虚拟环境..."
  python3 -m venv .venv
else
  echo "✓ .venv 已存在(跳过创建)"
fi

# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip --quiet

# 4. 装 ACE-Step
echo ""
echo "📦 安装 ACE-Step (首次几分钟,要下 PyTorch 等大包)..."
cd ACE-Step-1.5
pip install -e .
cd ..

# 5. 装我们的辅助工具
echo ""
echo "📦 安装 ai-music-lab 辅助工具..."
pip install -r requirements.txt --quiet

# 6. 检查 ffmpeg
echo ""
if command -v ffmpeg >/dev/null 2>&1; then
  echo "✓ ffmpeg 已安装"
else
  echo "⚠ 没装 ffmpeg(后处理脚本需要)"
  echo "  Ubuntu/Debian: sudo apt install ffmpeg"
  echo "  Mac: brew install ffmpeg"
  echo "  Windows: 去 https://ffmpeg.org/download.html 下载,加进 PATH"
fi

# 创建本地目录(被 gitignore 但需要存在)
mkdir -p outputs loras datasets

echo ""
echo "✅ 完成!"
echo ""
echo "下一步:"
echo "  source .venv/bin/activate"
echo "  bash scripts/launch-ui.sh"
echo ""
echo "首次启动会自动下载 ACE-Step 模型权重(几个 GB),耐心等待。"
