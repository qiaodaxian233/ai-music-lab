#!/bin/bash
# 单文件响度归一化到 -14 LUFS(Spotify / YouTube / Apple Music 标准)
# 用法: bash scripts/normalize.sh path/to/song.wav
set -e

if [ -z "$1" ]; then
  echo "用法: $0 <audio-file>"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "❌ 没装 ffmpeg。Ubuntu: sudo apt install ffmpeg"
  exit 1
fi

in="$1"
ext="${in##*.}"
base="${in%.*}"
out="${base}_normalized.${ext}"

ffmpeg -i "$in" -af "loudnorm=I=-14:TP=-1.5:LRA=11" -y "$out" 2>&1 | tail -5
echo "✓ $out"
