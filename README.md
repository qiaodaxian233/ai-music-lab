# ai-music-lab

个人 AI 音乐生成工作台，基于 [ACE-Step v1.5](https://github.com/ace-step/ACE-Step-1.5)。

本仓库本身不含模型代码，是 **ACE-Step 的包装层 + 历史索引 + 自动后处理 + LoRA 数据 wizard**。

## 快速开始

```bash
# 一键安装(自动 clone ACE-Step + 建 venv + 装依赖)
bash setup.sh

# 激活环境
source .venv/bin/activate

# 启动 ACE-Step 主 UI(http://localhost:7860)
bash scripts/launch-ui.sh
```

## 三个独立小工具(端口分开,按需启动)

| 工具 | 端口 | 启动命令 | 作用 |
|---|---|---|---|
| ACE-Step 主 UI | 7860 | `bash scripts/launch-ui.sh` | 生成 / LoRA 训练 |
| 📚 历史浏览器 | 7861 | `bash scripts/launch-history.sh` | 搜/标/听/删 历史生成 |
| 🎓 LoRA 数据 wizard | 7862 | `bash scripts/launch-lora-wizard.sh` | 分析参考音频,准备训练集 |
| 🔄 后处理 watcher | (无 UI) | `bash scripts/launch-postprocess.sh` | 自动归一化新生成的歌 |

四个可以同时开,互不打扰。

## 硬件要求

- GPU: ≥12GB VRAM
- 标准 ACE-Step 模型: 不到 4GB VRAM 即可
- XL 模型(质量更好): 最低 12GB(开 cpu_offload),推荐 ≥20GB

## 目录结构

```
ai-music-lab/
├── ACE-Step-1.5/       ← setup.sh 自动 clone,不在 git 里
├── lib/                ← 核心 Python 库
│   ├── history.py      ← 历史索引
│   ├── postprocess.py  ← 响度归一化 / tag / 转码
│   └── training_data.py← LoRA 数据集分析与准备
├── scripts/            ← 启动 / 后处理脚本
│   ├── launch-ui.sh           ← ACE-Step 主 UI
│   ├── launch-history.sh      ← 历史浏览器 UI
│   ├── launch-lora-wizard.sh  ← LoRA 数据 wizard UI
│   ├── launch-postprocess.sh  ← 后处理 watcher
│   ├── history-ui.py          ← Gradio 历史浏览器
│   ├── auto-postprocess.py    ← watcher 主程序
│   ├── lora-wizard.py         ← Gradio LoRA 数据 UI
│   ├── normalize.sh           ← 单文件归一化
│   └── batch-normalize.sh     ← 批量归一化
├── prompts/            ← 风格 tag 库 / 歌词模板
├── loras/              ← 训练好的 LoRA(权重 gitignore)
├── datasets/           ← LoRA 训练数据(gitignore,音频太大)
└── outputs/            ← 生成的音频(gitignore)
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
