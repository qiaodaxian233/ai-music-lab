# ai-music-lab

个人 AI 音乐生成工作台，基于 [ACE-Step v1.5](https://github.com/ace-step/ACE-Step-1.5)。

本仓库本身不含模型代码，只是 **ACE-Step 的包装层 + 个人配置/脚本/资产仓库**。

## 快速开始

```bash
# 一键安装(自动 clone ACE-Step + 建 venv + 装依赖)
bash setup.sh

# 激活环境
source .venv/bin/activate

# 启动 UI(浏览器打开 http://localhost:7860)
bash scripts/launch-ui.sh
```

## 硬件要求

- GPU: ≥12GB VRAM
- 标准 ACE-Step 模型: 不到 4GB VRAM 即可
- XL 模型(质量更好): 最低 12GB(开 cpu_offload),推荐 ≥20GB

## 目录结构

```
ai-music-lab/
├── ACE-Step-1.5/       ← setup.sh 自动 clone,不在 git 里
├── prompts/            ← 风格 tag 库 / 歌词模板
├── scripts/            ← 启动 / 后处理 / 批量脚本
├── configs/            ← 推理参数预设(待加)
├── loras/              ← 训练好的 LoRA(权重 gitignore)
├── datasets/           ← LoRA 训练数据(gitignore,音频太大)
└── outputs/            ← 生成的音频(gitignore)
```

## 常用命令

```bash
# 启动 UI
bash scripts/launch-ui.sh

# 单首归一化到 -14 LUFS(Spotify/YouTube 标准响度)
bash scripts/normalize.sh outputs/song.wav

# 批量归一化整个目录
bash scripts/batch-normalize.sh outputs/
```

## LoRA 训练

ACE-Step 自带 LoRA 训练 UI:

1. 收集 5-20 首参考歌曲(MP3/WAV),放到 `datasets/<项目名>/`
2. 启动 UI → 切到 "LoRA Training" 标签页
3. 指定数据集路径,填名字,点训练
4. 训完的 LoRA 自动保存,生成时可选用

12GB 显存训练略紧,UI 里勾上 gradient checkpointing。

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
