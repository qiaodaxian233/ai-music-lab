#!/usr/bin/env python3
"""AI Music Lab 统一控制台

把 4 个工具合到一个 UI 里:
- 📚 历史浏览器
- 🎓 LoRA 数据 wizard
- 🎹 Song → DAW Export
- 🔄 后处理控制

启动: python scripts/unified-ui.py
打开: http://localhost:7861

ACE-Step 主 UI (7860) 不能整合, 那是 ACE-Step 自己的 Gradio,
顶部给个跳转链接.
"""
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gradio as gr

from lib import (
    audio_to_midi,
    history,
    postprocess,
    reaper_project,
    stem_separation,
    training_data,
)

OUTPUTS_DIR = ROOT / "outputs"
PROJECTS_DIR = OUTPUTS_DIR / "projects"
DATASETS_DIR = ROOT / "datasets"
AUDIO_EXTS = (".wav", ".mp3", ".flac", ".ogg", ".m4a")

# 后处理 watcher 子进程句柄
_watcher_proc: subprocess.Popen | None = None


# ───────────────────────────────────────────────
# 历史浏览器
# ───────────────────────────────────────────────

def _fmt_duration(sec):
    if not sec:
        return "?"
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def _fmt_rating(n):
    n = int(n or 0)
    return "★" * n + "☆" * (5 - n)


def _build_history_rows(results):
    rows = []
    for fid, s in results:
        rows.append([
            "⭐" if s.get("favorited") else "",
            _fmt_rating(s.get("rating")),
            s.get("filename", ""),
            _fmt_duration(s.get("duration_seconds")),
            (s.get("prompt") or "")[:60] + ("…" if len(s.get("prompt") or "") > 60 else ""),
            ", ".join(s.get("tags") or [])[:40],
            (s.get("created_at") or "")[:19],
            fid,  # 隐藏列,定位用
        ])
    return rows


def h_refresh(query, fav_only, min_rating):
    added, total = history.scan_and_update()
    results = history.search(query, fav_only, int(min_rating or 0))
    return (
        f"扫描完成 · 新增 {added} 首 · 共 {total} 首 · 当前筛选 {len(results)} 首",
        _build_history_rows(results),
    )


def h_search(query, fav_only, min_rating):
    results = history.search(query, fav_only, int(min_rating or 0))
    return (
        f"当前筛选 {len(results)} 首",
        _build_history_rows(results),
    )


def h_select(rows, evt: gr.SelectData):
    """点击一行 → 加载详情 + 更新全局选中状态"""
    empty = [None, "", "", "", 0, "", 0, "", False, "", ""]
    if not rows or evt.index is None:
        return empty
    row_idx = evt.index[0] if isinstance(evt.index, list) else evt.index
    if row_idx >= len(rows):
        return empty

    fid = rows[row_idx][-1]
    index = history.load_index()
    s = index["songs"].get(fid, {})

    audio_path = OUTPUTS_DIR / s.get("filename", "")
    audio = str(audio_path) if audio_path.exists() else None

    # 最后一个返回值是 selected_song 的相对路径, 给其他 Tab 用
    selected_rel = s.get("filename", "") if audio else ""

    return [
        audio,
        fid,
        s.get("filename", ""),
        s.get("prompt", "") or "",
        s.get("lyrics", "") or "",
        s.get("seed") if s.get("seed") is not None else 0,
        s.get("lora", "") or "",
        int(s.get("rating") or 0),
        ", ".join(s.get("tags") or []),
        bool(s.get("favorited")),
        s.get("notes", "") or "",
        selected_rel,   # 给 gr.State 用
    ]


def h_save(fid, prompt, lyrics, seed, lora, rating, tags, favorited, notes):
    if not fid:
        return "⚠ 先在左侧选一首歌"
    tags_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    history.update_entry(
        fid,
        prompt=prompt or "",
        lyrics=lyrics or "",
        seed=int(seed) if seed else None,
        lora=lora or "",
        rating=int(rating or 0),
        tags=tags_list,
        favorited=bool(favorited),
        notes=notes or "",
    )
    return "✓ 已保存"


def h_delete(fid, also_file):
    if not fid:
        return "⚠ 先选一首歌", None, ""
    history.delete_entry(fid, delete_file=bool(also_file))
    msg = "✓ 已删除" + (" 含文件" if also_file else " 仅索引")
    return msg, None, ""


# ───────────────────────────────────────────────
# LoRA wizard
# ───────────────────────────────────────────────

def _list_lora_projects():
    if not DATASETS_DIR.exists():
        return []
    return [p.name for p in DATASETS_DIR.iterdir() if p.is_dir()]


def l_create_project(new_name: str):
    new_name = (new_name or "").strip()
    if not new_name:
        return "⚠ 填个名字", gr.update()
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in new_name)
    if safe != new_name:
        new_name = safe
    raw_dir = DATASETS_DIR / new_name / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    return (
        f"✓ 已建 {raw_dir}\n\n把参考音频拖到这,然后回来点分析。",
        gr.update(choices=_list_lora_projects(), value=new_name),
    )


def l_analyze(project_name: str, target_sr: int, target_channels: int):
    project_name = (project_name or "").strip()
    if not project_name:
        return "⚠ 请填项目名", []

    if not training_data._check_librosa():
        return "❌ librosa 未装。运行: pip install librosa soundfile", []

    project_dir = DATASETS_DIR / project_name
    raw_dir = project_dir / "raw"
    if not raw_dir.exists():
        return f"❌ 没找到 {raw_dir}\n请先把参考音频放到这个目录。", []

    report = training_data.prepare_dataset(
        source_dir=raw_dir,
        output_dir=project_dir,
        target_sr=int(target_sr),
        target_format="wav",
        target_channels=int(target_channels),
    )
    if "error" in report:
        return f"❌ {report['error']}", []
    if report["total"] == 0:
        return f"⚠ {raw_dir} 里没找到音频文件", []

    rows = []
    for t in report["tracks"]:
        rows.append([
            t["dataset_filename"],
            t.get("bpm", "") or "",
            t.get("key", "") or "",
            f"{t['duration']:.1f}s" if t.get("duration") else "",
            t.get("caption", ""),
        ])

    msg = (
        f"✅ 分析完成 · 处理 {report['succeeded']}/{report['total']} 首\n"
        f"📁 训练集目录: {report['output']}\n"
        f"📄 metadata.csv: {report['csv_path']}\n\n"
        f"下一步: 在表格里编辑 caption,然后点'保存 captions',再去 ACE-Step UI 训练。"
    )
    if report["errors"]:
        msg += "\n\n⚠ 部分失败:\n" + "\n".join(report["errors"][:5])

    return msg, rows


def l_save_captions(project_name: str, table_data):
    project_name = (project_name or "").strip()
    if not project_name:
        return "⚠ 请填项目名"
    csv_path = DATASETS_DIR / project_name / "metadata.csv"
    if not csv_path.exists():
        return f"❌ 还没生成 metadata.csv,先点'分析'"
    if not table_data:
        return "⚠ 表格为空"
    captions = {}
    for row in table_data:
        if len(row) >= 5:
            fname = (row[0] or "").strip()
            caption = (row[4] or "").strip()
            if fname:
                captions[fname] = caption
    updated = training_data.update_captions(csv_path, captions)
    return f"✓ 已保存 {updated} 条 caption 到 {csv_path}"


# ───────────────────────────────────────────────
# Song → DAW Export
# ───────────────────────────────────────────────

def _list_outputs_songs():
    """outputs/ 顶层音频文件, 按 mtime 倒序"""
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


def _daw_readme_text(name, bpm, duration, markers, stems, midi_files):
    lines = [
        f"# {name}",
        "",
        f"BPM (detected): {bpm:.1f}",
        f"时长: {duration:.1f} 秒",
        "",
    ]
    if markers:
        lines.append("## 段落 marker")
        for m in markers:
            lines.append(f"  {m['position']:7.2f}s   {m['name']}")
        lines.append("")
    lines.extend([
        "## 轨道结构",
        "01 Vocals (AI ref) ⚠ MUTE",
        "02 Drums (Audio) + 02b Drums (MIDI)",
        "03 Bass (Audio) + 03b Bass (MIDI)",
        "04 Guitar (Audio only)",
        "05 Piano (Audio) + 05b Piano (MIDI)",
        "06 Other (pads/strings)",
        "★ 07 YOUR VOCAL ● 已 arm 待录",
        "",
        "Reaper 打开 .rpp → 选 07 轨 → 按 R → 录人声",
    ])
    return "\n".join(lines)


def d_use_history_selection(selected_rel: str):
    """从全局 selected_song 拉值, 填到 song_dropdown"""
    if not selected_rel:
        return gr.update(), "⚠ 还没在 📚 历史 Tab 里选歌呢"
    return gr.update(value=selected_rel), f"✓ 已选: {selected_rel}"


def d_process(song_path, do_midi, project_name, progress=gr.Progress()):
    if not song_path:
        return "⚠ 没选歌", ""

    log = []
    def L(m):
        log.append(m)
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

        # 1. Stem 分离
        progress(0.05, desc="第 1/4 步: 6-stem 分离 (Demucs)...")
        L("\n[1/4] Demucs 6-stem")
        tmp_dir = project_dir / "_demucs_tmp"
        sep_result = stem_separation.separate_song(src, tmp_dir)
        if not sep_result["ok"]:
            return "❌ Demucs 失败", L(f"  ❌ {sep_result['error']}")
        L(f"  ✓ 分出 {len(sep_result['stems'])} 个 stem")

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
        L(f"  ✓ 已整理到 {stems_dir}")

        # 2. BPM / markers
        progress(0.45, desc="第 2/4 步: BPM / 段落...")
        L("\n[2/4] BPM + 段落 (librosa)")
        bpm = audio_to_midi.detect_bpm(src)
        markers = audio_to_midi.detect_structure_markers(src)
        duration = postprocess._get_duration(src) or 180.0
        L(f"  ✓ BPM {bpm:.1f}  marker {len(markers)}  时长 {duration:.1f}s")

        # 3. MIDI
        midi_files = {}
        if do_midi:
            progress(0.55, desc="第 3/4 步: 转录 MIDI...")
            L("\n[3/4] MIDI 转录")
            if "piano" in renamed_stems:
                progress(0.6, desc="钢琴 MIDI...")
                mp = stems_dir / "05_piano.mid"
                r = audio_to_midi.transcribe_melodic(renamed_stems["piano"], mp)
                if r["ok"]:
                    midi_files["piano"] = mp
                    L(f"  ✓ 钢琴 {r['notes']} 音符")
                else:
                    L(f"  ⚠ 钢琴跳过: {r['error']}")
            if "bass" in renamed_stems:
                progress(0.7, desc="贝斯 MIDI...")
                mp = stems_dir / "03_bass.mid"
                r = audio_to_midi.transcribe_melodic(renamed_stems["bass"], mp)
                if r["ok"]:
                    midi_files["bass"] = mp
                    L(f"  ✓ 贝斯 {r['notes']} 音符")
                else:
                    L(f"  ⚠ 贝斯跳过: {r['error']}")
            if "drums" in renamed_stems:
                progress(0.8, desc="鼓 MIDI...")
                mp = stems_dir / "02_drums.mid"
                r = audio_to_midi.transcribe_drums(renamed_stems["drums"], mp, bpm=bpm)
                if r["ok"]:
                    midi_files["drums"] = mp
                    L(f"  ✓ 鼓 kick={r['kicks']} snare={r['snares']} hh={r['hihats']}")
                else:
                    L(f"  ⚠ 鼓跳过: {r['error']}")
        else:
            L("\n[3/4] MIDI 转录: 跳过")

        # 4. Reaper
        progress(0.9, desc="第 4/4 步: 生成 Reaper 工程...")
        L("\n[4/4] Reaper .rpp")
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

        readme = project_dir / "README.txt"
        readme.write_text(
            _daw_readme_text(project_name, bpm, duration, markers, renamed_stems, midi_files),
            encoding="utf-8",
        )

        progress(1.0, desc="完成!")
        result = f"✅ 完工!\n📁 {project_dir}\n🎹 Reaper 打开: {rpp_path.name}"
        L(f"\n{result}")
        return result, "\n".join(log)
    except Exception as e:
        tb = traceback.format_exc()
        return f"❌ {e}", L(f"\n❌ 异常:\n{tb}")


# ───────────────────────────────────────────────
# 后处理控制
# ───────────────────────────────────────────────

def p_status():
    global _watcher_proc
    if _watcher_proc and _watcher_proc.poll() is None:
        return f"▶ 运行中 (PID {_watcher_proc.pid})"
    return "⏸ 已停止"


def p_start():
    global _watcher_proc
    if _watcher_proc and _watcher_proc.poll() is None:
        return p_status() + " (已在运行,无需重启)"
    script_path = ROOT / "scripts" / "auto-postprocess.py"
    _watcher_proc = subprocess.Popen(
        [sys.executable, str(script_path)],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return p_status()


def p_stop():
    global _watcher_proc
    if _watcher_proc and _watcher_proc.poll() is None:
        _watcher_proc.terminate()
        try:
            _watcher_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _watcher_proc.kill()
    _watcher_proc = None
    return p_status()


def p_run_once(selected_rel: str):
    """对历史里选中的歌跑一次后处理(手动)"""
    if not selected_rel:
        return "⚠ 先在 📚 历史 Tab 里选一首歌"
    audio_path = ROOT / selected_rel
    if not audio_path.exists():
        return f"❌ 找不到 {audio_path}"
    try:
        result = postprocess.process_one(audio_path)
        return f"✓ 完成: {result.get('output', audio_path.name)}\n{result.get('details', '')}"
    except Exception as e:
        return f"❌ 失败: {e}"


# ───────────────────────────────────────────────
# UI 组装
# ───────────────────────────────────────────────

with gr.Blocks(title="AI Music Lab 控制台") as app:
    # 跨 Tab 共享: 历史里选中的歌的相对路径 (相对 ROOT)
    selected_song = gr.State("")

    gr.Markdown("""
# 🎵 AI Music Lab 控制台

🎹 **生成新歌请打开 [ACE-Step 主 UI](http://localhost:7860)** (另跑 `start_gradio_ui.bat`)

这里管理生成完的歌:浏览历史 / 训练 LoRA / 拆 stem 导出 Reaper 工程 / 后处理控制。
""")

    with gr.Tabs():

        # ─── Tab 1: 历史浏览器 ───
        with gr.TabItem("📚 历史浏览器"):
            gr.Markdown("所有标注/评分/标签保存在 `outputs/.history-index.json`。\n"
                        "**在这里选一首歌,可以在 🎹 DAW 导出 / 🔄 后处理 Tab 里直接用。**")
            with gr.Row():
                with gr.Column(scale=3):
                    with gr.Row():
                        h_search_box = gr.Textbox(label="搜索",
                                                  placeholder="prompt / 歌词 / 标签 / 备注 / 文件名",
                                                  scale=4)
                        h_refresh_btn = gr.Button("🔄 重新扫描", scale=1)
                    with gr.Row():
                        h_fav = gr.Checkbox(label="只看收藏 ⭐", value=False)
                        h_rating = gr.Slider(label="最低评分", minimum=0, maximum=5,
                                             step=1, value=0)
                    h_status = gr.Textbox(label="状态", interactive=False)
                    h_table = gr.Dataframe(
                        headers=["⭐", "评分", "文件名", "时长", "Prompt", "Tags", "时间", "id"],
                        datatype=["str"] * 8,
                        interactive=False,
                        row_count=(20, "dynamic"),
                        col_count=(8, "fixed"),
                        wrap=True,
                    )

                with gr.Column(scale=2):
                    gr.Markdown("### 详情 / 编辑")
                    h_audio = gr.Audio(label="试听", interactive=False)
                    with gr.Row():
                        h_fid = gr.Textbox(label="ID", interactive=False, scale=1)
                        h_filename = gr.Textbox(label="文件名", interactive=False, scale=2)
                    h_prompt = gr.Textbox(label="Prompt / 风格 tags", lines=2)
                    h_lyrics = gr.Textbox(label="歌词", lines=6)
                    with gr.Row():
                        h_seed = gr.Number(label="Seed", precision=0)
                        h_lora = gr.Textbox(label="使用的 LoRA")
                    with gr.Row():
                        h_rating_edit = gr.Slider(label="评分", minimum=0, maximum=5,
                                                  step=1, value=0)
                        h_fav_edit = gr.Checkbox(label="收藏")
                    h_tags = gr.Textbox(label="标签 (逗号分隔)",
                                        placeholder="如: 副歌好听, 失败案例, 给生日礼物用")
                    h_notes = gr.Textbox(label="备注", lines=2)
                    with gr.Row():
                        h_save_btn = gr.Button("💾 保存", variant="primary")
                        h_delete_btn = gr.Button("🗑 删除", variant="stop")
                        h_delete_file = gr.Checkbox(label="同时删文件")
                    h_action_status = gr.Textbox(label="操作结果", interactive=False)

            # 历史事件
            h_refresh_btn.click(h_refresh, [h_search_box, h_fav, h_rating],
                                [h_status, h_table])
            h_search_box.submit(h_search, [h_search_box, h_fav, h_rating],
                                [h_status, h_table])
            h_fav.change(h_search, [h_search_box, h_fav, h_rating], [h_status, h_table])
            h_rating.change(h_search, [h_search_box, h_fav, h_rating], [h_status, h_table])
            h_table.select(
                h_select, [h_table],
                [h_audio, h_fid, h_filename, h_prompt, h_lyrics,
                 h_seed, h_lora, h_rating_edit, h_tags, h_fav_edit, h_notes,
                 selected_song],   # ← 全局 State 跨 Tab
            )
            h_save_btn.click(
                h_save,
                [h_fid, h_prompt, h_lyrics, h_seed, h_lora,
                 h_rating_edit, h_tags, h_fav_edit, h_notes],
                [h_action_status],
            )
            h_delete_btn.click(h_delete, [h_fid, h_delete_file],
                               [h_action_status, h_audio, h_fid])
            app.load(h_refresh, [h_search_box, h_fav, h_rating], [h_status, h_table])

        # ─── Tab 2: LoRA wizard ───
        with gr.TabItem("🎓 LoRA 训练数据"):
            gr.Markdown("""
**工作流**: 建项目 → 把参考歌(5-20 首)放到 `datasets/<项目名>/raw/` →
点分析 → 编辑 caption → 保存 → 去 ACE-Step UI 训练。
""")
            with gr.Row():
                with gr.Column(scale=2):
                    l_dropdown = gr.Dropdown(label="选择项目",
                                             choices=_list_lora_projects(),
                                             allow_custom_value=True, interactive=True)
                    with gr.Row():
                        l_new_box = gr.Textbox(label="或新建项目", scale=2,
                                               placeholder="如: my-chinese-folk")
                        l_create_btn = gr.Button("➕ 创建", scale=1)
                with gr.Column(scale=1):
                    l_sr = gr.Number(label="目标采样率", value=44100, precision=0)
                    l_ch = gr.Number(label="目标声道(1=mono 2=stereo)", value=2, precision=0)

            l_analyze_btn = gr.Button("🔍 分析并准备训练集", variant="primary", size="lg")
            l_status = gr.Textbox(label="状态", interactive=False, lines=4)

            gr.Markdown("### 编辑 captions(双击单元格编辑)")
            l_table = gr.Dataframe(
                headers=["filename", "BPM", "key", "duration", "caption ← 编辑这列"],
                datatype=["str"] * 5,
                interactive=True,
                row_count=(10, "dynamic"),
                col_count=(5, "fixed"),
                wrap=True,
            )
            l_save_btn = gr.Button("💾 保存 captions 到 metadata.csv", variant="primary")
            l_save_status = gr.Textbox(label="保存结果", interactive=False)

            l_create_btn.click(l_create_project, [l_new_box], [l_status, l_dropdown])
            l_analyze_btn.click(l_analyze, [l_dropdown, l_sr, l_ch], [l_status, l_table])
            l_save_btn.click(l_save_captions, [l_dropdown, l_table], [l_save_status])

        # ─── Tab 3: Song → DAW Export ───
        with gr.TabItem("🎹 Song → DAW Export"):
            gr.Markdown("""
拆 stem + 转 MIDI + 生成 Reaper 工程. 打开 .rpp 就能录人声 + 编辑 MIDI + 混音.

**首次运行下 Demucs (~5GB) + Basic Pitch (~150MB), 慢, 之后秒级.**
""")
            with gr.Row():
                with gr.Column(scale=2):
                    d_dropdown = gr.Dropdown(label="选 outputs/ 里的歌",
                                             choices=_list_outputs_songs(),
                                             interactive=True)
                    with gr.Row():
                        d_refresh_btn = gr.Button("🔄 刷新列表", size="sm")
                        d_use_history_btn = gr.Button("⬅ 用历史 Tab 选中的歌",
                                                      size="sm", variant="secondary")
                with gr.Column(scale=2):
                    d_project_name = gr.Textbox(label="工程名 (留空用歌的文件名)",
                                                placeholder="例: my-first-song")
                    d_do_midi = gr.Checkbox(
                        label="同时生成 MIDI (Basic Pitch + 鼓检测, 多花 1-2 分钟)",
                        value=True,
                    )

            d_go_btn = gr.Button("🚀 开始处理", variant="primary", size="lg")
            d_result = gr.Textbox(label="结果", lines=3, interactive=False)
            d_log = gr.Textbox(label="过程日志", lines=20, interactive=False)

            d_refresh_btn.click(lambda: gr.update(choices=_list_outputs_songs()),
                                outputs=[d_dropdown])
            d_use_history_btn.click(d_use_history_selection,
                                    [selected_song], [d_dropdown, d_log])
            d_go_btn.click(d_process,
                           [d_dropdown, d_do_midi, d_project_name],
                           [d_result, d_log])

            gr.Markdown("""
**输出位置**: `outputs/projects/<工程名>/`
- `<工程名>.rpp` ← 双击用 Reaper 打开
- `stems/` ← 6 WAV + 3 MIDI
- `README.txt` ← 操作指南

没装 Reaper? [reaper.fm](https://www.reaper.fm/download.php) 下载,试用永久,$60 注册。
""")

        # ─── Tab 4: 后处理控制 ───
        with gr.TabItem("🔄 后处理控制"):
            gr.Markdown("""
**自动后处理 watcher**: 监视 `outputs/` 目录,新音频自动归一化到 -14 LUFS 并登记到历史。

**手动后处理**: 对历史 Tab 里选中的歌跑一次后处理 (调试用)。
""")
            with gr.Row():
                p_status_box = gr.Textbox(label="watcher 状态",
                                          value=p_status(), interactive=False)
                p_refresh_btn = gr.Button("🔄 刷新状态", size="sm")

            with gr.Row():
                p_start_btn = gr.Button("▶ 启动 watcher", variant="primary")
                p_stop_btn = gr.Button("⏸ 停止 watcher", variant="stop")

            gr.Markdown("---")
            gr.Markdown("### 对历史里选中的歌手动跑一次")
            p_run_btn = gr.Button("🔧 立即后处理选中的歌")
            p_run_result = gr.Textbox(label="结果", interactive=False, lines=4)

            p_start_btn.click(p_start, outputs=[p_status_box])
            p_stop_btn.click(p_stop, outputs=[p_status_box])
            p_refresh_btn.click(lambda: p_status(), outputs=[p_status_box])
            p_run_btn.click(p_run_once, [selected_song], [p_run_result])

    gr.Markdown("""
---

**端口 7861** · 关掉窗口即停止. 跨 Tab 联动通过 `outputs/` 文件系统自动生效.
""")


if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7861, inbrowser=False)
