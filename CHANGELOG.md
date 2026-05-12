# CHANGELOG

## v0.2.0 — 历史索引 + 自动后处理 + LoRA wizard (2026-05-12)

三大件:

### 📚 生成历史索引器 (`lib/history.py` + `scripts/history-ui.py`)
- 自动扫描 `outputs/` 把所有生成过的歌建立索引
- 每首记录: filename / prompt / lyrics / seed / LoRA / rating (0-5) / tags / notes / favorited
- 索引存在 `outputs/.history-index.json`(gitignore, 本地私有)
- Gradio UI 端口 **7861**: 搜索 / 试听 / 评分 / 打标签 / 收藏 / 删除
- 支持同名 `.json` sidecar 文件自动合并(为未来 ACE-Step 元数据预留)
- 可从 Python 脚本调用 `history.register(filename, **metadata)` 登记富元数据

### 🔄 自动后处理 watcher (`scripts/auto-postprocess.py`)
- 用 watchdog 监视 `outputs/` 目录
- 新音频文件出现 → 等文件大小稳定 → 自动处理:
  - 响度归一化到 -14 LUFS (Spotify/YouTube 标准)
  - 可选淡入淡出 (`--fade`)
  - 可选转 MP3 320kbps (默认开)
  - 写 ID3 tag (标题=文件名,artist=AI,album=ai-music-lab)
  - 登记到历史索引
- 跳过 `_normalized` / `_faded` 后缀文件,避免无限循环
- 启动选项: `--scan-existing` 处理已有文件, `--no-mp3` 保留 WAV, `--keep-intermediates` 不删中间文件

### 🎓 LoRA 数据准备 wizard (`lib/training_data.py` + `scripts/lora-wizard.py`)
- 工作流: UI 建项目 → 把 MP3/WAV 放进 `datasets/<项目>/raw/` → 点分析
- 用 librosa 自动检测:
  - BPM (节拍追踪)
  - Key (chroma 取最强 pitch class, 12 大调)
  - 时长 / 采样率
- 从文件名+分析结果生成 caption 建议(能猜出 folk/rock/lofi/民谣/摇滚等关键词)
- 表格里编辑 caption → 保存到 `metadata.csv`
- 重采样到统一采样率(默认 44.1kHz)+ 声道(默认 stereo)→ 输出到 `datasets/<项目>/audio/`
- 输出格式直接喂给 ACE-Step 的 LoRA Training 标签即可
- Gradio UI 端口 **7862**

### 其他
- `requirements.txt` 加: watchdog, librosa, soundfile
- `scripts/launch-history.sh` / `launch-lora-wizard.sh` / `launch-postprocess.sh` 启动脚本
- README 重写,加常用工作流和 LoRA 训练完整步骤

---

## v0.1.0 — 初始骨架 (2026-05-12)

- 一键安装 `setup.sh`(自动 clone ACE-Step、建 venv、装依赖、检查 ffmpeg)
- 12GB VRAM 优化的启动脚本 `scripts/launch-ui.sh`(开 `torch_compile` + `cpu_offload` + `overlapped_decode`)
- ffmpeg 响度归一化脚本(`-14 LUFS` 流媒体标准)
  - `scripts/normalize.sh` 单文件
  - `scripts/batch-normalize.sh` 整目录
- 风格 tag 预设库 `prompts/styles.json`(15 个常用组合 + 按类别拆分的 tag 词典)
- 歌词结构模板 `prompts/lyrics-templates.md`(含标准流行结构 / 极简 / EDM 节奏感版本 / 中文技巧)
- `.gitignore` 排除模型权重、生成音频、训练数据集
