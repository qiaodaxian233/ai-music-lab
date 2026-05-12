# CHANGELOG

## v0.1.0 — 初始骨架 (2026-05-12)

- 一键安装 `setup.sh`（自动 clone ACE-Step、建 venv、装依赖、检查 ffmpeg）
- 12GB VRAM 优化的启动脚本 `scripts/launch-ui.sh`（开 `torch_compile` + `cpu_offload` + `overlapped_decode`）
- ffmpeg 响度归一化脚本（`-14 LUFS` 流媒体标准）
  - `scripts/normalize.sh` 单文件
  - `scripts/batch-normalize.sh` 整目录
- 风格 tag 预设库 `prompts/styles.json`（15 个常用组合 + 按类别拆分的 tag 词典）
- 歌词结构模板 `prompts/lyrics-templates.md`（含标准流行结构 / 极简 / EDM 节奏感版本 / 中文技巧）
- `.gitignore` 排除模型权重、生成音频、训练数据集
