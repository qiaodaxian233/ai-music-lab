#!/bin/bash
# 启动自动后处理 watcher
# 它监视 outputs/,新文件出现就自动归一化 + 转 MP3 + 加 tag
#
# 用法:
#   bash scripts/launch-postprocess.sh                # 前台运行(Ctrl+C 退出)
#   bash scripts/launch-postprocess.sh --scan-existing  # 启动时先处理已有文件
#   bash scripts/launch-postprocess.sh --no-mp3       # 不转 MP3,只归一化
#   bash scripts/launch-postprocess.sh --fade         # 加淡入淡出
#
# 后台运行:
#   nohup bash scripts/launch-postprocess.sh > postprocess.log 2>&1 &
#   echo $! > postprocess.pid
# 停止:
#   kill $(cat postprocess.pid) && rm postprocess.pid

set -e
cd "$(dirname "$0")/.."

if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python scripts/auto-postprocess.py "$@"
