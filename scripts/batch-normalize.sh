#!/bin/bash
# 批量归一化整个目录
# 用法: bash scripts/batch-normalize.sh outputs/
set -e

dir="${1:-outputs}"
script_dir="$(dirname "$0")"
count=0

for f in "$dir"/*.wav "$dir"/*.mp3 "$dir"/*.flac; do
  [ -f "$f" ] || continue
  # 跳过已经处理过的
  [[ "$f" == *_normalized.* ]] && continue
  bash "$script_dir/normalize.sh" "$f"
  count=$((count + 1))
done

echo ""
echo "✅ 处理了 $count 个文件"
