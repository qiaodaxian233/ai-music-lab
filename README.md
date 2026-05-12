# ai-music-lab

个人 AI 音乐生成工作台，基于 [ACE-Step v1.5](https://github.com/ace-step/ACE-Step-1.5)。

本仓库本身不含模型代码，是 **ACE-Step 的包装层 + 历史索引 + 自动后处理 + LoRA 数据 wizard**。

## 快速开始

### Linux / Mac / WSL

```bash
# 一键安装(自动 clone ACE-Step + 建 venv + 装依赖)
bash setup.sh

# 激活环境
source .venv/bin/activate

# 启动 ACE-Step 主 UI(http://localhost:7860)
bash scripts/launch-ui.sh
```

### Windows

**第 1 次** 在 Git Bash 里跑 `setup.sh` 建环境(cmd 跑不了 .sh):

```bash
cd /e/path/to/ai-music-lab
bash setup.sh
```

**之后日常** 直接在资源管理器里**双击 .bat**启动:

| 双击文件 | 端口 | 作用 |
|---|---|---|
| `start-ui.bat` | 7860 | ACE-Step 主 UI(已带 12GB VRAM 优化参数) |
| `start-history.bat` | 7861 | 历史浏览器 |
| `start-lora-wizard.bat` | 7862 | LoRA 训练数据 wizard |
| `start-daw-export.bat` | 7863 | Song → Reaper 工程导出 |
| `start-postprocess.bat` | (无 UI) | 自动归一化 watcher |

可以同时双击多个,互不打扰。关窗口即停服务。

## 各工具一览

| 工具 | 端口 | Linux / Mac | Windows | 作用 |
|---|---|---|---|---|
| ACE-Step 主 UI | 7860 | `bash scripts/launch-ui.sh` | `start-ui.bat` | 生成 / LoRA 训练 |
| 📚 历史浏览器 | 7861 | `bash scripts/launch-history.sh` | `start-history.bat` | 搜/标/听/删 历史生成 |
| 🎓 LoRA 数据 wizard | 7862 | `bash scripts/launch-lora-wizard.sh` | `start-lora-wizard.bat` | 分析参考音频,准备训练集 |
| 🎹 Song → DAW Export | 7863 | `bash scripts/launch-daw-export.sh` | `start-daw-export.bat` | 拆 stem + 转 MIDI + 生成 Reaper 工程 |
| 🔄 后处理 watcher | (无 UI) | `bash scripts/launch-postprocess.sh` | `start-postprocess.bat` | 自动归一化新生成的歌 |

## 硬件要求

- GPU: ≥12GB VRAM
- 标准 ACE-Step 模型: 不到 4GB VRAM 即可
- XL 模型(质量更好): 最低 12GB(开 cpu_offload),推荐 ≥20GB

## 目录结构

```
ai-music-lab/
├── ACE-Step-1.5/       ← setup.sh 自动 clone,不在 git 里
├── lib/                ← 核心 Python 库
│   ├── history.py            ← 历史索引
│   ├── postprocess.py        ← 响度归一化 / tag / 转码
│   ├── training_data.py      ← LoRA 数据集分析与准备
│   ├── stem_separation.py    ← Demucs 6-stem 分离 (v0.3.0)
│   ├── audio_to_midi.py      ← Basic Pitch + 鼓 onset 检测 (v0.3.0)
│   └── reaper_project.py     ← Reaper .rpp 工程生成器 (v0.3.0)
├── scripts/            ← 启动 / 后处理脚本
│   ├── launch-ui.sh           ← ACE-Step 主 UI
│   ├── launch-history.sh      ← 历史浏览器 UI
│   ├── launch-lora-wizard.sh  ← LoRA 数据 wizard UI
│   ├── launch-daw-export.sh   ← Song → DAW Export UI (v0.3.0)
│   ├── launch-postprocess.sh  ← 后处理 watcher
│   ├── history-ui.py
│   ├── lora-wizard.py
│   ├── song-to-daw.py         ← (v0.3.0)
│   ├── auto-postprocess.py
│   ├── normalize.sh
│   └── batch-normalize.sh
├── prompts/            ← 风格 tag 库 / 歌词模板
├── loras/              ← 训练好的 LoRA(权重 gitignore)
├── datasets/           ← LoRA 训练数据(gitignore)
└── outputs/            ← 生成的音频(gitignore)
    └── projects/       ← DAW 工程导出 (v0.3.0, gitignore)
```

## 常用工作流

### 日常生成

```bash
# 1. 启动 ACE-Step UI 和后处理 watcher
bash scripts/launch-ui.sh &
bash scripts/launch-postprocess.sh &

# 2. 在 ACE-Step UI 里生成歌(http://localhost:7860)
#    生成完后,watcher 会自动:
#    - 响度归一化到 -14 LUFS
#    - 转 MP3
#    - 写 ID3 tag(标题、artist=AI)
#    - 登记到历史索引

# 3. 启动历史浏览器看自己生成过的所有歌
bash scripts/launch-history.sh
# 浏览器 http://localhost:7861 → 搜/听/标/评/删
```

### LoRA 训练流程

```bash
# 1. 启动 wizard
bash scripts/launch-lora-wizard.sh
# 浏览器 http://localhost:7862

# 2. UI 里建项目(比如叫 my-chinese-folk)
#    → wizard 会建好 datasets/my-chinese-folk/raw/ 目录

# 3. 把 5-20 首参考歌曲(MP3/WAV)拖到 datasets/my-chinese-folk/raw/

# 4. 回到 UI 点"分析并准备训练集"
#    → 自动算 BPM/key + 生成 caption 建议

# 5. 在表格里编辑 caption(描述每首歌的风格)→ 点"保存 captions"

# 6. 切到 ACE-Step 主 UI 的 "LoRA Training" 标签
#    数据集路径填: datasets/my-chinese-folk/
#    → 一键训练
```

### 摆脱 AI 标签:导出真实创作工程

```bash
# 1. 启动 Song → DAW Export
bash scripts/launch-daw-export.sh
# 浏览器 http://localhost:7863

# 2. 选 outputs/ 里满意的一首歌,勾上"生成 MIDI",点处理
#    → 5-15 分钟后产出 outputs/projects/<歌名>/<歌名>.rpp

# 3. 装 Reaper(reaper.fm,试用永久),双击 .rpp 打开

# 4. 工程里 ★ 07 YOUR VOCAL 轨已自动 arm record
#    → 戴耳机,按播放,跟着 AI 人声轨录你自己的人声
#    → 录几个 take 拼最好

# 5. 想换鼓/贝斯/钢琴音色?
#    → mute 02/03/05 Audio 轨,unmute 02b/03b/05b MIDI 轨
#    → 给 MIDI 轨加虚拟乐器(ReaSamplOmatic5000 / Spitfire LABS 等)

# 6. 调音量,File → Render 导出 → 这是一首真实有你创作的歌
```

### 手动后处理(如果没开 watcher)

```bash
bash scripts/normalize.sh outputs/song.wav            # 单文件
bash scripts/batch-normalize.sh outputs/              # 整目录
```

## 历史索引

历史数据保存在 `outputs/.history-index.json`(被 gitignore,本地私有)。

每条记录包含：filename、prompt、lyrics、seed、lora、rating(0-5)、tags、notes、favorited。

可以从 Python 脚本直接登记元数据：

```python
from lib import history

history.register(
    "my_song.wav",
    prompt="indie folk, female vocal, acoustic, 90 bpm",
    lyrics="[verse]...",
    seed=42,
    lora="my-folk-lora-v1",
)
```

## 更新

```bash
git pull                  # 拉本仓库
cd ACE-Step-1.5 && git pull && cd ..   # 拉 ACE-Step 主代码
```

## 维护者备忘

- Python 必须 ≥3.11.12(Ubuntu 自带的 3.11.0rc1 是预发布版会段错误)
- 改 prompt 库 / 配置时直接编辑 `prompts/styles.json`,推上去 git pull 就生效
- 生成的音频不上 git(私人内容)
- LoRA 权重文件 (.safetensors) 不上 git(太大),但同名 .json 配置会上去方便复现
