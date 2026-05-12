# CHANGELOG

## v0.4.0 — 统一控制台 + .bat 启动器精简 (2026-05-12)

把 4 个独立 UI 合并到一个统一控制台,联动 + 单端口 + 单窗口。

### 🎵 新增

- **`scripts/unified-ui.py`** (端口 7861, 690 行) — 统一控制台,4 个 Tab:
  - 📚 历史浏览器
  - 🎓 LoRA 训练数据
  - 🎹 Song → DAW Export
  - 🔄 后处理控制 (含 watcher 启停)
- **`start-lab.bat`** — 启动统一控制台
- **跨 Tab 联动**:
  - 历史 Tab 选一首歌 → 全局 `gr.State` 共享
  - DAW Tab 「⬅ 用历史 Tab 选中的歌」按钮 → 一键预填
  - 后处理 Tab 「🔧 立即后处理选中的歌」按钮 → 对选中的歌跑一次

### 🔧 修复

- **`start-ui.bat`** 重写: 之前错误写了 `python app.py`, 实际 ACE-Step-1.5
  的入口不是 app.py. 新版**直接调用 ACE-Step 自带的 `start_gradio_ui.bat`**,
  让 ACE-Step 官方启动器接管 venv/依赖/参数, 跨版本不会再坏.

### 🗑 删除 (功能已被统一控制台取代)

- `start-history.bat`
- `start-lora-wizard.bat`
- `start-daw-export.bat`
- `start-postprocess.bat`

但 `scripts/{history-ui,lora-wizard,song-to-daw,auto-postprocess}.py` **保留**,
高级用户可单独启动:
```bash
python scripts/history-ui.py     # :7861
python scripts/lora-wizard.py    # :7862
python scripts/song-to-daw.py    # :7863
```

### 📝 文档

- README.md: Windows 启动一节重写,主推 2-bat (start-ui + start-lab)
- 项目对接记忆.md: 同步

---

## v0.3.1 — Windows 启动器 + 行尾规范 (2026-05-12)

修复 Windows 用户 `git clone` 后 `.sh` 文件被 Git 自动转 CRLF 导致 bash 跑不动的问题
(`$'\r': command not found` / `syntax error: unexpected end of file`)。

### 新增

- **5 个 Windows `.bat` 启动器** (双击运行,自带 12GB VRAM 优化参数):
  - `start-ui.bat` (7860) — ACE-Step 主 UI
  - `start-history.bat` (7861) — 历史浏览器
  - `start-lora-wizard.bat` (7862) — LoRA wizard
  - `start-daw-export.bat` (7863) — Song → DAW Export
  - `start-postprocess.bat` — 后处理 watcher
- **`.gitattributes`** 锁定行尾规范:
  - `.sh` / `.py` / `.md` / `.json` → LF
  - `.bat` / `.cmd` → CRLF
  - 音频 / 模型权重 → binary

### 文档

- README.md 加 Windows 启动一节, 工具表分两套

### 后续 Windows 用户须知

如果你已经 `git pull` 拿过仓库, `.sh` 文件可能还是 CRLF, 跑一次:

```bash
sed -i 's/\r$//' setup.sh scripts/*.sh
```

之后再 pull 不会再坏(`.gitattributes` 接管了)。

---

## v0.3.0 — Song → Reaper 工程导出 (2026-05-12)

新增"AI 歌 → 真人创作工程文件"完整流水线。让你的作品有工程文件作为创作证据,
配合你的电容麦录人声 = 实质性人类创作贡献,摆脱 AI 标签。

### 🎹 完整流水线 (`scripts/song-to-daw.py`, 端口 7863)

输入 `outputs/` 里一首 AI 生成的歌,自动产出 Reaper 工程目录:

```
outputs/projects/<工程名>/
├── <工程名>.rpp                       ← Reaper 工程文件(双击打开)
├── README.txt                         ← BPM / 段落 / 操作指南
└── stems/
    ├── 01_vocals_AI_reference.wav     ← AI 人声(工程里默认 mute)
    ├── 02_drums.wav + 02_drums.mid    ← 鼓 stem + MIDI
    ├── 03_bass.wav + 03_bass.mid      ← 贝斯 stem + MIDI
    ├── 04_guitar.wav                  ← 吉他(无 MIDI,多声部转录不支持)
    ├── 05_piano.wav + 05_piano.mid    ← 钢琴 stem + MIDI
    └── 06_other.wav                   ← pads/strings/etc
```

工程内含 10 个预配置轨:
- 6 个音频 stem 轨
- 3 个 MIDI 备选轨(默认 mute,启用后接虚拟乐器换音色)
- **1 个空待录轨(已 arm record,你的人声)**
- 段落 marker(intro/verse/chorus/bridge/outro 自动检测)
- 项目 BPM 设到检测到的值

### 🔧 新增模块

- `lib/stem_separation.py` — Demucs htdemucs_6s 6-stem 分离封装
- `lib/audio_to_midi.py` — Basic Pitch (钢琴/贝斯) + librosa 鼓 onset 检测
- `lib/reaper_project.py` — `.rpp` 文件生成器,**MIDI 事件直接嵌入工程文件**
  (不用用户额外导入 .mid 文件), 支持 marker / 颜色 / 待录状态 / mute
- `scripts/song-to-daw.py` — Gradio UI 端口 7863
- `scripts/launch-daw-export.sh` — 启动脚本

### 📦 新依赖

- `demucs>=4.0` — 6-stem 分离(首次下载 htdemucs_6s 模型 ~5GB)
- `basic-pitch>=0.4` — Spotify 开源 audio-to-MIDI(钢琴/贝斯效果好)
- `pretty_midi>=0.2` — MIDI 读写

### ⚠️ 已知局限(诚实说)

- **吉他不转 MIDI**:多声部和弦转录是音乐 AI 没解决的难题,留音频
- **鼓 MIDI 看歌**:简单 4/4 流行鼓 80% 准;复杂打击乐 / trap hi-hat / jazz feel 抓不准
- **不预装 plugin 链**:Reaper plugin 参数格式跟版本绑定,稳定性差。
  用户用 Reaper 自带的 ReaEQ/ReaComp/ReaSamplOmatic5000,30 秒手动加完
- **段落 marker 经验型命名**:agglomerative 切段挺准,但 "Verse/Chorus" 名字是按
  流行歌经验起的,不保证一一对应。Reaper 里随时改名

---

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
