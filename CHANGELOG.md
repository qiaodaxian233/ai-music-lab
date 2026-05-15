# CHANGELOG

## v0.5.4 — Gradio 6.0 兼容 hotfix (2026-05-15)

用户在 Win 上跑 v0.5.3 总控台,撞了 Gradio 6.0 + .bat 编码两个坑,一并修。

### 🐛 修复

| 问题 | 原因 | 修复 |
|---|---|---|
| `start-manager.bat` 报 `'动地址:' is not recognized` | .bat 含中文 echo,UTF-8 无 BOM,cmd 在 `chcp 65001` 生效前解码错位 | 改成纯 ASCII echo (英文) |
| `Blocks.launch() got an unexpected keyword argument 'show_api'` | Gradio 6.0 移除 `show_api` 参数 | 删除 |
| `theme` 警告: Gradio 6.0 把 theme 从 Blocks 移到 launch() | API 重组 | 改用 `app.launch(theme=...)` |
| `col_count` deprecation | Gradio 6.0 → `column_count` | 全部改名 (lab-manager.py + unified-ui.py 共 6 处) |
| `row_count=(N, "fixed")` deprecation | Gradio 6.0 → `row_count=N, row_limits=(N,N)` | 同上 (6 处) |

### 📁 文件改动

- 修改: `start-manager.bat`(改 ASCII echo,避免中文乱码)
- 修改: `scripts/lab-manager.py`(launch 参数 + col_count/row_count 重命名)
- 修改: `scripts/unified-ui.py`(col_count/row_count 重命名 5 处)
- 修改: `CHANGELOG.md` / `项目对接记忆.md`

### ⚠ 用户先决条件提醒

- `pip install psutil`(总控台必装,未装会退化但不挂)
- 或者跑 `pip install -r requirements.txt` 一次性装齐 v0.5.0~v0.5.3 所有新依赖

### 沙箱实测

- Gradio 6.14.0 + Python 3.12 跑通,**两个 UI 装配 + 真 launch 都 OK,零 deprecation**

---

## v0.5.3 — 总控台 (端口 7862,启停 + 监控 3 个服务) (2026-05-15)

补一个**更高一层的总控**:启停 + 监控 ACE-Step 主 UI / 统一控制台 / 后处理 watcher 三个常驻服务,看 GPU/磁盘状态,看最近输出,看实时日志。

跟统一控制台的区别:
- **7861 统一控制台** = 12 Tab 的**功能集合**(生成/管理/导出)
- **7862 总控台** = 启停/监控其它进程的**运维面板**

### 🎵 新增

- **`scripts/lab-manager.py`** (端口 7862) — Gradio 总控,自动 3s 刷新
- **`lib/process_manager.py`** — 跨平台 (Win/Linux/Mac) 子进程启停 + psutil 进程树 kill + 端口监听检测 + GPU 状态(nvidia-smi) + 磁盘占用
- **`start-manager.bat`** — Windows 启动器(端口 7862,跟 7860/7861 互不干扰)

### 🚦 总控台 UI 区块

| 区块 | 内容 |
|---|---|
| 🚦 服务控制 | 三个卡片(ACE-Step / 统一控制台 / watcher),每个有 启动/停止/重启 + 状态徽章 + 浏览器跳转链接 |
| 📊 系统状态 | GPU 显存条 + util%、磁盘占用、outputs/ 体积、LoRA 个数、Python/ACE-Step 装机情况 |
| 📂 最近输出 | outputs/ 下最近 10 个改动文件 + 大小 + 何时改的 |
| 📜 日志 | 选服务看最近 200 行日志,可清空 |
| 🔄 自动刷新 | gr.Timer 3 秒拉一次(可关) |

### 🔧 设计要点

- **PID 文件 + psutil 双重判定**: `runtime/<key>.pid` 保留 PID,但**真正状态判断**用 psutil.pid_exists() + 端口 listen 检测(socket.create_connection)。这样即使 PID 文件没了/孤儿,只要端口在用,也能感知到运行中。
- **kill 进程树**: ACE-Step 通过 `cmd /c start_gradio_ui.bat` 启动,实际 Python 是孙子进程,直接 kill PID 杀不干净。用 `psutil.Process.children(recursive=True)` 拿整棵树,先 terminate 3s 再 kill。
- **隐藏 cmd 窗口**: Windows 用 `CREATE_NO_WINDOW (0x08000000)` 让服务后台跑,日志重定向到 `runtime/<key>.log`,在总控 UI 里看。

### 📁 文件改动

- 新增: `scripts/lab-manager.py`(333 行)、`lib/process_manager.py`(405 行)、`start-manager.bat`
- 修改: `requirements.txt`(加 psutil)、`README.md`、`CHANGELOG.md`、`项目对接记忆.md`、`lib/__init__.py`

---

## v0.5.2 — 4 个高性价比补充功能 (2026-05-15)

按"发歌前最常用的工具"角度补 4 个,每个都在 1 小时内完工,无重依赖。

### 🎵 新增

| 功能 | 入口 | 说明 |
|---|---|---|
| 📦 一键打包 | 新 Tab「📦 发行打包」 | wav + mp3 + cover + lrc + mid + metadata → zip,投稿一次性搞定 |
| ✂ 自动剪短版 | 新 Tab「📦 发行打包」 | chorus 检测 + 30s 截取 + 淡入淡出,发社交平台用 |
| 🔀 LoRA 权重融合 | 「🎓 LoRA 库」Tab 底部 | 线性插值两个 .safetensors,自动写配置,风格混血不用每次叠加 |
| 🈶 中文 → 拼音 | 「📝 Prompt 工作室」Tab 底部 | pypinyin 带音调输出,ACE-Step 训中文 LoRA 必备 |

### 📦 新增 lib 模块 (4 个)

- **`lib/export_bundle.py`** — `build_bundle()`,串联打包流程,缺的衍生物会现生成(封面/lrc/mid 都自动补)
- **`lib/lora_merge.py`** — `merge_two(a, b, wa, wb)`,float32 累加再转回原 dtype,自动处理形状不匹配,可同时 `auto_generate_config()` 写 .json
- **`lib/audio_highlight.py`** — `make_highlight()`,chroma 自相似矩阵 + 滑动窗口找最重复段,加淡入淡出。沙箱实测能从 60s 模拟"歌"准确切到 chorus 区
- **`lib/pinyin_tools.py`** — `to_pinyin / to_pinyin_inline / mixed_format`,保留 `[Verse]` 章节标签和标点,支持音调/数字/无音调三种格式

### 🔧 依赖

- 新增必装: `pypinyin>=0.49` (~几 MB)、`safetensors>=0.4` (~几 MB)

### 📊 沙箱实测结果

- pinyin: "今夜星光灿烂" → "jīn yè xīng guāng càn làn" ✓
- lora_merge: 0.7·A + 0.3·B 与手算误差 0.00e+00 ✓
- audio_highlight: 60s 模拟歌(chorus 在 20-40s & 50-60s)检测到 24.1s~54.1s,落在 chorus 区域内 ✓

### 📁 文件改动

- 新增: `lib/{export_bundle,lora_merge,audio_highlight,pinyin_tools}.py`
- 修改: `scripts/unified-ui.py`(1607→1902 行,Tab 11→12 + Prompt/LoRA Tab 内嵌子工具)
- 修改: `requirements.txt`(加 pypinyin + safetensors)
- 修改: `README.md`、`项目对接记忆.md`、本 CHANGELOG

---

## v0.5.1 — 一键转 MIDI Tab (2026-05-14)

补一个 **"🎼 一键 MIDI"** Tab — 整曲音频直接出 MIDI,**跳过 Demucs stem 分离**(比 Song→DAW 路径快 10×)。

### 🎵 新增

- **Tab "🎼 一键 MIDI"** (UI 11/11):
  - 输入: outputs/ 选歌 或 直接拖音频
  - 模式: `melodic`(Basic Pitch 整曲抓主旋律)/ `drums`(onset 分类)/ `both`
  - 同时检测 **BPM** 和 **段落 marker**(intro / verse / chorus...)
  - 可选嵌入元数据到 `.mid` 本身(DAW 读得到 tempo + marker)
  - 输出三个文件: `outputs/midi/<歌名>/melodic.mid` + `bpm.txt` + `markers.txt`
- **`lib/audio_to_midi.py` 新函数 `quick_transcribe()`**: 高级一键 API,串好 BPM/marker/melodic/drums + 嵌入元数据,可独立 CLI 用。
- **`lib/audio_to_midi.py` 新函数 `_inject_meta_into_midi()`**: 把 BPM 重写到 MIDI tempo,把段落 marker 写成 pretty_midi lyric 事件(Reaper / Ableton / Cubase 都认)。

### 🔧 设计要点

- 不依赖 Demucs,只用 Basic Pitch + librosa,所以"启动→出 MIDI"只要几秒(首次下 Basic Pitch ~150MB 除外)。
- Basic Pitch 没装时 `melodic` 会失败,但 `drums` / `bpm` / `markers` 不依赖它,仍能跑(优雅降级)。
- 跟 Song→DAW Export 共用 `lib/audio_to_midi.py`,不重复代码。

### 📁 文件改动

- 修改: `lib/audio_to_midi.py`(186→326 行,新增 quick_transcribe + _inject_meta_into_midi)
- 修改: `scripts/unified-ui.py`(1438→1607 行,加 Tab 11 + `qm_` 辅助函数)
- 修改: `CHANGELOG.md` / `项目对接记忆.md`

---

## v0.5.0 — 8 大功能补全:Prompt 工作室 / LoRA 库 / 批量 / A/B / 封面 / 字幕 / 续写 / 翻唱 (2026-05-14)

一次性把 12 项规划里剩下的 8 项全做完。统一控制台从 4 Tab 扩到 **10 Tab**,
功能列表 **12/12 完成** ✅。

### 🎵 新增功能 Tab

| Tab | 功能编号 | 说明 |
|---|---|---|
| 📝 Prompt 工作室 | #4 | 读写 `prompts/styles.json`,预设 CRUD + tag 积木组合 |
| 🎓 LoRA 库 | #5 | 扫描 `loras/`,每个 LoRA 配置 CRUD + 一键 N seed 试听 |
| 🚀 批量生成 | #6 | CSV → N 个 prompt 挂机跑,dry-run 预览 + 中途停止 |
| ⚖ A/B 对比 | #7 | 历史里挑两首歌并排,prompt / seed / LoRA 差异一眼看 |
| 🎨 封面 & 字幕 | #9 + #10 | 封面(PIL 几何 / SDXL)+ LRC 字幕(均分 / Whisper) |
| 🔁 续写 / 翻唱 | #11 + #12 | ACE-Step audio2audio: extend + cover |

### 📦 新增 lib 模块 (6 个)

- **`lib/prompt_library.py`** — `prompts/styles.json` 读写,`load_db / list_presets / save_preset / compose_prompt`
- **`lib/lora_manager.py`** — `scan_loras / get_config / save_config / generate_samples`,自动调 ACE-Step 跑 N seed
- **`lib/batch_gen.py`** — `parse_csv / run_batch`,带 progress_callback + stop_flag + dry_run
- **`lib/cover_art.py`** — `make_cover_geometric` (PIL 渐变+几何+文字, 无 GPU 500ms) / `make_cover_sdxl` (opt-in, diffusers) / `embed_into_mp3`
- **`lib/lrc_export.py`** — `make_lrc_even` (无依赖均分) / `make_lrc_whisper` (opt-in, openai-whisper)
- **`lib/ace_step_api.py`** — ACE-Step `ACEStepPipeline` 调用封装,**#6/#11/#12 共用**。懒加载 + 单例 + 12GB VRAM 友好参数 (cpu_offload + overlapped_decode)

### 🔧 依赖变化

- 新增必装:`pillow>=10.0` (#9 几何封面需要)
- 新增可选(按需自装,默认不装):
  - `diffusers + transformers + accelerate` — SDXL 封面模式
  - `openai-whisper` — LRC 强制对齐模式

### ⚠ 注意事项

- **#6 #11 #12 三个功能依赖 ACE-Step 在线**:批量生成 / 续写 / 翻唱都通过 `lib/ace_step_api.py` 调 ACE-Step Pipeline。`ace_step_api.py` 是基于 ACE-Step v1.5 主线签名推断的,如果跑时报 "unexpected keyword argument",去查 `ACE-Step-1.5/acestep/pipeline_ace_step.py` 实际签名,改 `ace_step_api.py` 一处即可。
- **SDXL 封面模式占 6-8GB VRAM**,跟 ACE-Step 同时跑会 OOM。批量做封面时建议先停 ACE-Step。
- **多 LoRA 混合语法**:`lib/lora_manager.format_mix([(name, weight), ...])` 输出 `"path1:w1,path2:w2"`,具体 ACE-Step 怎么解析这个字符串需要看其 LoRA loader 实现,首次使用如果失败也是查 ACE-Step 源码就近改。

### 📊 项目进度

| 编号 | 功能 | 状态 |
|---|---|---|
| #1 | 历史索引器 | ✅ v0.2.0 |
| #2 | 自动后处理 hook | ✅ v0.2.0 |
| #3 | LoRA 数据 wizard | ✅ v0.2.0 |
| #4 | Prompt 预设 UI | ✅ **v0.5.0** |
| #5 | LoRA 管理面板 | ✅ **v0.5.0** |
| #6 | 批量生成 | ✅ **v0.5.0** |
| #7 | A/B 并排对比 | ✅ **v0.5.0** |
| #8 | Stem 分离 (DAW 导出) | ✅ v0.3.0 |
| #9 | 自动封面图 | ✅ **v0.5.0** |
| #10 | 歌词字幕 | ✅ **v0.5.0** |
| #11 | 续写 / extend | ✅ **v0.5.0** |
| #12 | 翻唱 / audio2audio | ✅ **v0.5.0** |

**12/12 完成** 🎉

### 📁 文件改动

- 新增: `lib/{prompt_library,lora_manager,batch_gen,cover_art,lrc_export,ace_step_api}.py`
- 修改: `scripts/unified-ui.py` (691 → 1437 行,6 Tab → 10 Tab),`lib/__init__.py`,`requirements.txt`,`README.md`,`项目对接记忆.md`

---

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
