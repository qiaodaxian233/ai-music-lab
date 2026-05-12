#!/usr/bin/env python3
"""Song → Reaper 工程导出 (Gradio UI)

工作流:
1. 选 outputs/ 里的歌
2. 点处理 → Demucs 6-stem + BPM + 段落 + MIDI 转录 + Reaper .rpp 生成
3. 用 Reaper 打开 outputs/projects/<歌名>/<歌名>.rpp
4. 录人声, 编辑 MIDI, 混音, 导出

启动: python scripts/song-to-daw.py
打开: http://localhost:7863
"""
import shutil
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gradio as gr

from lib import audio_to_midi, postprocess, reaper_project, stem_separation

OUTPUTS_DIR = ROOT / "outputs"
PROJECTS_DIR = OUTPUTS_DIR / "projects"
AUDIO_EXTS = (".wav", ".mp3", ".flac", ".ogg", ".m4a")


def list_songs():
    """outputs/ 顶层的音频文件 (按 mtime 倒序), 不包含 projects/ 子目录"""
    if not OUTPUTS_DIR.exists():
        return []
    files = []
    for p in OUTPUTS_DIR.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in AUDIO_EXTS:
            continue
        if p.name.startswith("."):
            continue
        files.append(p)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p.relative_to(ROOT)) for p in files]


def _safe_project_name(s: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in s)
    return safe.strip("_") or "untitled"


def _readme_text(name, bpm, duration, markers, stems, midi_files):
    lines = [
        f"# {name}",
        "",
        f"BPM (detected): {bpm:.1f}",
        f"时长: {duration:.1f} 秒",
        f"采样率: 44100 Hz",
        "",
    ]

    if markers:
        lines.append("## 段落 marker (经验型, 不保证准)")
        for m in markers:
            lines.append(f"  {m['position']:7.2f}s   {m['name']}")
        lines.append("")

    lines.extend([
        "## 轨道结构",
        "",
        "01 Vocals (AI ref) ⚠ MUTE  — AI 生成的人声, 仅作参考",
        "02 Drums (Audio)            — 鼓 stem, 默认开",
        "02b Drums (MIDI alt) ⚠ MUTE — 检测出的 kick/snare/hh MIDI",
        "03 Bass (Audio)             — 贝斯 stem",
        "03b Bass (MIDI alt) ⚠ MUTE  — Basic Pitch 转录的 MIDI",
        "04 Guitar (Audio only)      — 吉他 stem (多声部无法转 MIDI)",
        "05 Piano (Audio)            — 钢琴 stem",
        "05b Piano (MIDI alt) ⚠ MUTE — Basic Pitch 转录的 MIDI",
        "06 Other                    — pads/strings/弦乐等",
        "★ 07 YOUR VOCAL ● ARMED    — 你的人声待录! 选这轨,按 R,按播放,开唱",
        "",
        "## 推荐流程",
        "",
        "1. 双击 .rpp 用 Reaper 打开",
        "2. 戴耳机, 选 ★ 07 YOUR VOCAL 轨",
        "3. 按播放, 跟着 AI 人声(轨 01)唱, 录几个 take",
        "4. 切 Edit 模式拼接最好片段",
        "5. 想换鼓/贝斯/钢琴音色? 静音 02/03/05, 启用 02b/03b/05b, 给 MIDI 轨加虚拟乐器",
        "6. 给每轨加 ReaEQ + ReaComp (Reaper 自带, 右键轨道→FX)",
        "7. File → Render 导出 wav",
        "",
        "## 我没装 plugin chain",
        "",
        "Reaper 内置 ReaEQ / ReaComp / ReaVerbate / ReaSamplOmatic5000 都免费,",
        "右键 FX 添加. 我没在 .rpp 里硬编 plugin 参数, 因为参数格式跟 Reaper",
        "版本绑定不稳定. 自己加一次再保存模板, 下次一键复用.",
        "",
        "## MIDI 备选轨用法",
        "",
        "02b / 03b / 05b 默认 mute. 想用 MIDI 重做鼓/贝斯/钢琴音色时:",
        "1. mute 对应的 Audio 轨 (比如 02 Drums)",
        "2. unmute MIDI 轨 (比如 02b Drums MIDI)",
        "3. 选 MIDI 轨 → 右键 FX → 加虚拟乐器:",
        "   - 鼓: ReaSamplOmatic5000 (载入鼓采样) 或 EZdrummer",
        "   - 贝斯: ReaSynth 或者你的贝斯插件",
        "   - 钢琴: Spitfire LABS Soft Piano (免费) 或 Native Instruments Noire",
        "4. 播放, 听效果",
    ])

    return "\n".join(lines)


def process(song_path, do_midi, project_name, progress=gr.Progress()):
    """主流程"""
    if not song_path:
        return "⚠ 没选歌", ""

    log = []
    def L(msg):
        log.append(msg)
        return "\n".join(log)

    try:
        src = ROOT / song_path
        if not src.exists():
            return f"❌ 找不到文件: {src}", L(f"❌ {src}")

        project_name = _safe_project_name(project_name) if project_name else _safe_project_name(src.stem)
        project_dir = PROJECTS_DIR / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        L(f"📁 项目目录: {project_dir}")
        L(f"🎵 输入文件: {src.name}")

        # ─── Step 1: Stem separation ───
        progress(0.05, desc="第 1/4 步: 6-stem 分离 (Demucs)...")
        L("\n[1/4] Demucs 6-stem 分离")
        L("  首次运行会下载 ~5GB 模型. GPU ~1-3 分钟,CPU ~5-10 分钟.")

        tmp_dir = project_dir / "_demucs_tmp"
        sep_result = stem_separation.separate_song(src, tmp_dir)

        if not sep_result["ok"]:
            return "❌ Demucs 失败", L(f"  ❌ {sep_result['error']}")

        L(f"  ✓ 分出 {len(sep_result['stems'])} 个 stem: {list(sep_result['stems'].keys())}")

        # 移动到 project_dir/stems/ 并按约定命名
        stems_dir = project_dir / "stems"
        stems_dir.mkdir(exist_ok=True)

        name_map = {
            "vocals": "01_vocals_AI_reference",
            "drums":  "02_drums",
            "bass":   "03_bass",
            "guitar": "04_guitar",
            "piano":  "05_piano",
            "other":  "06_other",
        }

        renamed_stems = {}
        for stem_name, stem_path in sep_result["stems"].items():
            new_name = name_map.get(stem_name, stem_name)
            new_path = stems_dir / f"{new_name}.wav"
            if new_path.exists():
                new_path.unlink()
            shutil.move(str(stem_path), str(new_path))
            renamed_stems[stem_name] = new_path

        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

        L(f"  ✓ 已移到 {stems_dir}")

        # ─── Step 2: BPM + markers ───
        progress(0.45, desc="第 2/4 步: 检测 BPM 和段落...")
        L("\n[2/4] BPM + 段落检测 (librosa)")

        bpm = audio_to_midi.detect_bpm(src)
        L(f"  ✓ BPM: {bpm:.1f}")

        markers = audio_to_midi.detect_structure_markers(src)
        L(f"  ✓ 检测到 {len(markers)} 个段落 marker")

        duration = postprocess._get_duration(src) or 180.0
        L(f"  ✓ 时长: {duration:.1f}s")

        # ─── Step 3: MIDI transcription ───
        midi_files = {}
        if do_midi:
            progress(0.55, desc="第 3/4 步: 转录 MIDI...")
            L("\n[3/4] MIDI 转录")

            if "piano" in renamed_stems:
                progress(0.6, desc="转录钢琴 MIDI (Basic Pitch)...")
                mp = stems_dir / "05_piano.mid"
                r = audio_to_midi.transcribe_melodic(renamed_stems["piano"], mp)
                if r["ok"]:
                    midi_files["piano"] = mp
                    L(f"  ✓ 钢琴 MIDI: {r['notes']} 音符")
                else:
                    L(f"  ⚠ 钢琴 MIDI 跳过: {r['error']}")

            if "bass" in renamed_stems:
                progress(0.7, desc="转录贝斯 MIDI...")
                mp = stems_dir / "03_bass.mid"
                r = audio_to_midi.transcribe_melodic(renamed_stems["bass"], mp)
                if r["ok"]:
                    midi_files["bass"] = mp
                    L(f"  ✓ 贝斯 MIDI: {r['notes']} 音符")
                else:
                    L(f"  ⚠ 贝斯 MIDI 跳过: {r['error']}")

            if "drums" in renamed_stems:
                progress(0.8, desc="转录鼓 MIDI...")
                mp = stems_dir / "02_drums.mid"
                r = audio_to_midi.transcribe_drums(renamed_stems["drums"], mp, bpm=bpm)
                if r["ok"]:
                    midi_files["drums"] = mp
                    L(f"  ✓ 鼓 MIDI: kick={r['kicks']} snare={r['snares']} hh={r['hihats']}")
                else:
                    L(f"  ⚠ 鼓 MIDI 跳过: {r['error']}")
        else:
            L("\n[3/4] MIDI 转录: 跳过 (用户未勾选)")

        # ─── Step 4: Reaper project ───
        progress(0.9, desc="第 4/4 步: 生成 Reaper 工程文件...")
        L("\n[4/4] 生成 Reaper .rpp 工程")

        rpp_path = reaper_project.generate_project(
            project_dir=project_dir,
            project_name=project_name,
            stems=renamed_stems,
            midi_files=midi_files,
            bpm=bpm,
            duration=duration,
            markers=markers,
        )

        L(f"  ✓ {rpp_path.name}")

        # README
        readme = project_dir / "README.txt"
        readme.write_text(
            _readme_text(project_name, bpm, duration, markers,
                         renamed_stems, midi_files),
            encoding="utf-8",
        )
        L(f"  ✓ README.txt")

        progress(1.0, desc="完成!")
        result = (
            f"✅ 完工!\n"
            f"📁 {project_dir}\n"
            f"🎹 用 Reaper 打开: {rpp_path.name}"
        )
        L(f"\n{result}")

        return result, "\n".join(log)

    except Exception as e:
        tb = traceback.format_exc()
        L(f"\n❌ 异常:\n{tb}")
        return f"❌ {e}", "\n".join(log)


# ─────────────── UI ───────────────

with gr.Blocks(title="Song → DAW Export") as app:
    gr.Markdown("""
# 🎹 Song → Reaper 工程导出

把 AI 生成的歌拆成 stem + MIDI, 自动生成 Reaper 工程. 打开就能录人声 + 编辑 MIDI + 混音.

**首次运行会下载 Demucs htdemucs_6s 模型 (~5GB) 和 Basic Pitch 模型 (~150MB), 慢, 之后秒级.**
""")

    with gr.Row():
        with gr.Column(scale=2):
            song_dropdown = gr.Dropdown(
                label="选 outputs/ 里的歌",
                choices=list_songs(),
                interactive=True,
            )
            refresh_btn = gr.Button("🔄 刷新列表", size="sm")

        with gr.Column(scale=2):
            project_name_box = gr.Textbox(
                label="工程名 (留空用歌的文件名)",
                placeholder="例: my-first-song",
            )
            do_midi = gr.Checkbox(
                label="同时生成 MIDI (Basic Pitch + 鼓检测, 多花 1-2 分钟)",
                value=True,
            )

    go_btn = gr.Button("🚀 开始处理", variant="primary", size="lg")

    result_box = gr.Textbox(label="结果", lines=3, interactive=False)
    log_box = gr.Textbox(label="过程日志", lines=22, interactive=False)

    refresh_btn.click(
        lambda: gr.update(choices=list_songs()),
        outputs=[song_dropdown],
    )
    go_btn.click(
        process,
        inputs=[song_dropdown, do_midi, project_name_box],
        outputs=[result_box, log_box],
    )

    gr.Markdown("""
---

## 时间预估

| 步骤 | GPU (12GB) | CPU |
|---|---|---|
| Demucs 6-stem | 1-3 分钟 | 5-10 分钟 |
| BPM / 段落 | 几秒 | 几秒 |
| MIDI 转录 | 1-2 分钟 | 2-4 分钟 |
| Reaper 工程生成 | 秒级 | 秒级 |

## 输出位置

`outputs/projects/<工程名>/`
- `<工程名>.rpp` ← 双击用 Reaper 打开
- `stems/` ← 6 个 WAV + 3 个 MIDI
- `README.txt` ← 操作指南

## 下一步

1. 没装 Reaper? [reaper.fm](https://www.reaper.fm/download.php) 下载, 试用永久, $60 注册
2. 用 Reaper 打开 .rpp 后, 在 ★ 07 YOUR VOCAL 轨按 R 录音
""")


if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7863, inbrowser=False)
