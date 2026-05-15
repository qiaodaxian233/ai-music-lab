"""ai-music-lab 核心库

模块:
- history: 生成历史索引(扫描 outputs/、metadata、CRUD)
- postprocess: 后处理(响度归一化、ID3 tag、格式转换)
- training_data: LoRA 训练数据准备(BPM/key 分析、caption、dataset 导出)
- stem_separation: Demucs 6-stem 分离
- audio_to_midi: Basic Pitch + 鼓 onset 转 MIDI + quick_transcribe (v0.5.1)
- reaper_project: Reaper .rpp 工程生成

v0.5.0:
- prompt_library: prompts/styles.json 读写 + tag 组合 (#4)
- lora_manager:   loras/ 扫描 + 配置 CRUD + 一键试听 (#5)
- batch_gen:      CSV 批量生成挂机跑 (#6)
- cover_art:      封面图 (PIL 几何 / SDXL) + MP3 ID3 嵌入 (#9)
- lrc_export:     .lrc 字幕 (均分 / Whisper 对齐) (#10)
- ace_step_api:   ACE-Step pipeline 调用封装,#6/#11/#12 共用

v0.5.2:
- export_bundle:  一键打包 wav+mp3+cover+lrc+mid+metadata 成 zip
- lora_merge:     LoRA .safetensors 线性融合
- audio_highlight: chroma 自相似找 chorus,切 30s + 淡入淡出
- pinyin_tools:   中文歌词 → 拼音 (训中文 LoRA 必备)
"""
