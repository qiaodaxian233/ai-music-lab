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
    ace_step_api,
    audio_highlight,
    audio_to_midi,
    batch_gen,
    cover_art,
    export_bundle,
    history,
    lora_manager,
    lora_merge,
    lrc_export,
    pinyin_tools,
    postprocess,
    prompt_library,
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


def _resolve_audio(song_rel: str, uploaded_path):
    """v0.5.5: 统一解析音频源。上传优先,否则 outputs/ 下拉。

    返回 (Path or None, 来源描述字符串)。
    外部上传(Suno / Udio / 任意 mp3 / wav)走 uploaded_path,
    OUTPUTS_DIR 下的歌走 song_rel。
    """
    if uploaded_path:
        p = Path(uploaded_path)
        if p.exists():
            return p, f"📤 上传: {p.name}"
    if song_rel:
        p = ROOT / song_rel
        if p.exists():
            return p, f"📂 outputs/: {song_rel}"
    return None, ""


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


def d_process(song_path, uploaded, do_midi, project_name, progress=gr.Progress()):
    src, src_label = _resolve_audio(song_path, uploaded)
    if not src:
        return "⚠ 没选 outputs/ 里的歌, 也没上传", ""

    log = []
    def L(m):
        log.append(m)
        return "\n".join(log)

    try:
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
# Prompt 工作室 (#4)
# ───────────────────────────────────────────────

def ps_refresh_presets():
    items = prompt_library.list_presets()
    choices = [name for name, _ in items]
    return gr.update(choices=choices, value=choices[0] if choices else None)


def ps_load_preset(name):
    if not name:
        return ""
    return prompt_library.get_preset(name) or ""


def ps_save_preset(name, prompt):
    if not name or not name.strip():
        return "⚠ 名称不能为空"
    if not prompt or not prompt.strip():
        return "⚠ Prompt 不能为空"
    try:
        is_new = prompt_library.save_preset(name.strip(), prompt.strip())
        return f"✓ {'新建' if is_new else '覆盖'} 预设: {name}"
    except Exception as e:
        return f"❌ {e}"


def ps_delete_preset(name):
    if not name:
        return "⚠ 选一个预设"
    ok = prompt_library.delete_preset(name)
    return "✓ 已删除" if ok else f"⚠ 没找到 {name}"


def ps_build_from_tags(*tag_lists):
    """所有 tag dropdown 的 value 拼起来。各 dropdown 是 multi-select 返 list。"""
    parts = []
    for tl in tag_lists:
        if isinstance(tl, list):
            parts.extend(tl)
        elif tl:
            parts.append(tl)
    return prompt_library.compose_prompt(*parts)


# ───────────────────────────────────────────────
# LoRA 管理面板 (#5)
# ───────────────────────────────────────────────

def lm_scan_table():
    rows = []
    for l in lora_manager.scan_loras():
        cfg = l.get("config") or {}
        rows.append([
            l["name"],
            l["ext"],
            f"{l['size_mb']:.0f} MB",
            "✓" if l["has_config"] else "—",
            cfg.get("description", "") or "",
            ", ".join(cfg.get("main_style_tags", []) or []),
        ])
    names = [l["name"] for l in lora_manager.scan_loras()]
    return rows, gr.update(choices=names, value=names[0] if names else None)


def lm_load_config(name):
    if not name:
        return "", "", "", 0, 0.0, "", "", ""
    cfg = lora_manager.get_config(name)
    return (
        cfg.get("description", ""),
        cfg.get("dataset_source", ""),
        cfg.get("recommended_prompt", ""),
        int(cfg.get("training_steps") or 0),
        float(cfg.get("learning_rate") or 0.0),
        ", ".join(cfg.get("main_style_tags") or []),
        cfg.get("usage_notes", ""),
        f"配置: {lora_manager.LORAS_DIR / (name + '.json')}",
    )


def lm_save_config(name, desc, dataset, rec_prompt, steps, lr, tags_str, notes):
    if not name:
        return "⚠ 没选 LoRA"
    tags = [t.strip() for t in (tags_str or "").split(",") if t.strip()]
    cfg = {
        "description": desc,
        "dataset_source": dataset,
        "recommended_prompt": rec_prompt,
        "training_steps": int(steps or 0),
        "learning_rate": float(lr or 0.0),
        "main_style_tags": tags,
        "usage_notes": notes,
    }
    p = lora_manager.save_config(name, cfg)
    return f"✓ 已保存配置 → {p}"


def lm_generate_samples(name, custom_prompt, seeds_str, duration, progress=gr.Progress()):
    """对选中 LoRA 生成示例曲。需要 ACE-Step 在线。"""
    if not name:
        return "⚠ 没选 LoRA", []
    seeds = []
    for s in (seeds_str or "42,1337,9999").split(","):
        s = s.strip()
        if s.isdigit():
            seeds.append(int(s))
    if not seeds:
        return "⚠ seeds 格式错误,用逗号分隔的整数", []

    def cb(i, total, msg):
        progress(i / total, desc=msg)

    try:
        paths = lora_manager.generate_samples(
            name,
            prompt=(custom_prompt or "").strip() or None,
            seeds=tuple(seeds),
            audio_duration=float(duration or 30),
            progress_callback=cb,
        )
        return (
            f"✓ 生成 {len(paths)} 首示例 → outputs/lora-samples/{name}/",
            [str(p) for p in paths],
        )
    except Exception as e:
        return f"❌ {e}", []


# ───────────────────────────────────────────────
# 批量生成 (#6)
# ───────────────────────────────────────────────

_batch_stop_flag = {"stop": False}


def bg_preview_csv(file):
    if file is None:
        return "⚠ 先上传或粘贴 CSV", []
    try:
        tasks = batch_gen.parse_csv(Path(file.name) if hasattr(file, "name") else Path(file))
    except Exception as e:
        return f"❌ CSV 解析失败: {e}", []
    if not tasks:
        return "⚠ CSV 没有有效任务(空 prompt 都被跳过)", []
    rows = [[t["row"], t["prompt"][:60], t["lyrics"][:30],
             t["duration"], t["seed"], t["lora"], t["filename"]] for t in tasks]
    return f"✓ 解析 {len(tasks)} 个任务", rows


def bg_load_template():
    return batch_gen.make_template_csv()


def bg_run(file, run_name, dry_run, progress=gr.Progress()):
    if file is None:
        return "⚠ 先上传 CSV", "", []
    try:
        tasks = batch_gen.parse_csv(Path(file.name) if hasattr(file, "name") else Path(file))
    except Exception as e:
        return f"❌ CSV 解析失败: {e}", "", []
    if not tasks:
        return "⚠ 没有有效任务", "", []

    _batch_stop_flag["stop"] = False

    def cb(i, total, msg):
        progress(i / total, desc=f"[{i}/{total}] {msg}")

    log = []
    try:
        report = batch_gen.run_batch(
            tasks,
            run_name=run_name.strip(),
            progress_callback=cb,
            stop_flag=lambda: _batch_stop_flag["stop"],
            dry_run=bool(dry_run),
        )
    except Exception as e:
        return f"❌ {e}", "\n".join(log), []

    rows = [[r["row"], r["status"], r.get("output") or "",
             (r.get("error") or "").splitlines()[0] if r.get("error") else ""]
            for r in report["results"]]
    summary = (f"✓ 完成 {report['ok']}/{report['total']} · "
               f"失败 {report['failed']} · "
               f"目录: {report['run_dir']}")
    return summary, str(report["report_path"]), rows


def bg_stop():
    _batch_stop_flag["stop"] = True
    return "⏸ 已请求停止,跑完当前一首后退出"


# ───────────────────────────────────────────────
# A/B 并排对比 (#7)
# ───────────────────────────────────────────────

def ab_song_choices():
    """返历史里所有歌 (按 created_at 倒序) 给两个下拉"""
    results = history.search()
    return [f"{s.get('filename', fid)}  [{fid[:6]}]" for fid, s in results]


def _ab_fid_from_label(label):
    """label = 'filename  [fid6]' → 完整 fid"""
    if not label:
        return None
    if "[" in label and label.endswith("]"):
        short = label[label.rindex("[") + 1:-1]
        index = history.load_index()
        for fid in index["songs"]:
            if fid.startswith(short):
                return fid
    return None


def _ab_render(fid):
    if not fid:
        return None, "—", "—", "—", "—", "—", "—"
    s = history.load_index()["songs"].get(fid, {})
    audio = ROOT / s.get("filename", "")
    return (
        str(audio) if audio.exists() else None,
        s.get("filename", "—"),
        (s.get("prompt") or "—")[:200],
        (s.get("lyrics") or "—")[:300],
        str(s.get("seed") or "—"),
        s.get("lora") or "—",
        "★" * int(s.get("rating") or 0),
    )


def ab_load_left(label):
    return _ab_render(_ab_fid_from_label(label))


def ab_load_right(label):
    return _ab_render(_ab_fid_from_label(label))


# ───────────────────────────────────────────────
# 封面 & 字幕 (#9 #10)
# ───────────────────────────────────────────────

def cv_song_choices():
    return _list_outputs_songs()


def cv_make_cover(song_rel, uploaded, title, subtitle, mode, sdxl_prompt, embed_mp3):
    audio, _src = _resolve_audio(song_rel, uploaded)
    if not audio:
        return None, "⚠ 选一首歌或上传"

    title = (title or audio.stem).strip()
    try:
        if mode == "sdxl":
            prompt = (sdxl_prompt or title).strip()
            cover_path = cover_art.make_cover_sdxl(prompt, title_overlay=title)
        else:
            cover_path = cover_art.make_cover_geometric(
                title, subtitle=(subtitle or "").strip(), seed=None,
            )
    except Exception as e:
        return None, f"❌ 生成封面失败: {e}"

    msg = f"✓ 封面 → {cover_path}"
    if embed_mp3:
        # 找同名 mp3
        mp3 = audio.with_suffix(".mp3")
        if mp3.exists():
            try:
                cover_art.embed_into_mp3(mp3, cover_path)
                msg += f"\n✓ 已嵌入到 ID3: {mp3.name}"
            except Exception as e:
                msg += f"\n⚠ 嵌入 MP3 失败: {e}"
        else:
            msg += f"\n⚠ 找不到 {mp3.name},未嵌入 (需要先把 wav 转 mp3)"
    return str(cover_path), msg


def cv_make_lrc(song_rel, uploaded, lyrics_override, mode, intro_offset, title, artist):
    audio, _src = _resolve_audio(song_rel, uploaded)
    if not audio:
        return None, "⚠ 选一首歌或上传"

    # 优先用 override,否则从历史索引拿
    lyrics = (lyrics_override or "").strip()
    if not lyrics:
        # 查历史
        for fid, s in history.search():
            if s.get("filename") == audio.name:
                lyrics = s.get("lyrics", "")
                break
    if not lyrics:
        return None, "⚠ 没歌词。在'歌词覆盖'里粘贴,或先在历史 Tab 给这首歌补歌词。"

    try:
        if mode == "whisper":
            p = lrc_export.export_lrc(
                audio, lyrics, mode="whisper",
                title=title.strip() or audio.stem, artist=artist.strip() or "AI",
            )
        else:
            duration = history.get_audio_duration(audio) or 60.0
            lrc_text = lrc_export.make_lrc_even(
                lyrics, duration,
                intro_offset=float(intro_offset or 4),
                title=title.strip() or audio.stem,
                artist=artist.strip() or "AI",
            )
            p = audio.with_suffix(".lrc")
            p.write_text(lrc_text, encoding="utf-8")
        return str(p), f"✓ LRC → {p}"
    except Exception as e:
        return None, f"❌ {e}"


# ───────────────────────────────────────────────
# 续写 / 翻唱 (#11 #12)
# ───────────────────────────────────────────────

def rv_song_choices():
    return _list_outputs_songs()


def rv_extend(song_rel, uploaded, seconds, direction, prompt, lyrics, seed, progress=gr.Progress()):
    src, _label = _resolve_audio(song_rel, uploaded)
    if not src:
        return None, "⚠ 选一首歌或上传"

    progress(0.1, desc="加载 ACE-Step pipeline (首次较慢)…")
    out = OUTPUTS_DIR / f"{src.stem}_ext{int(seconds)}s.wav"
    try:
        progress(0.3, desc="生成中…")
        ace_step_api.extend(
            src, float(seconds),
            output_path=out,
            prompt=prompt.strip(),
            lyrics=lyrics.strip(),
            seed=int(seed) if str(seed).strip() else None,
            direction=direction,
        )
        progress(1.0, desc="完成")
        return str(out), f"✓ 续写完成 → {out}"
    except Exception as e:
        return None, f"❌ {e}"


def rv_cover(song_rel, uploaded, new_prompt, new_lyrics, ref_strength, seed, progress=gr.Progress()):
    if not (new_prompt or "").strip():
        return None, "⚠ 必须填新风格 prompt"
    src, _label = _resolve_audio(song_rel, uploaded)
    if not src:
        return None, "⚠ 选一首歌或上传"

    progress(0.1, desc="加载 ACE-Step pipeline…")
    out = OUTPUTS_DIR / f"{src.stem}_cover.wav"
    try:
        progress(0.3, desc="生成中…")
        ace_step_api.cover(
            src,
            new_prompt=new_prompt.strip(),
            new_lyrics=new_lyrics.strip(),
            output_path=out,
            ref_audio_strength=float(ref_strength),
            seed=int(seed) if str(seed).strip() else None,
        )
        progress(1.0, desc="完成")
        return str(out), f"✓ 翻唱完成 → {out}"
    except Exception as e:
        return None, f"❌ {e}"


# ───────────────────────────────────────────────
# 一键转 MIDI (v0.5.1)
# ───────────────────────────────────────────────

def qm_song_choices():
    return _list_outputs_songs()


def qm_run(song_rel, mode, with_bpm, with_markers, embed_meta, progress=gr.Progress()):
    if not song_rel:
        return None, None, None, "⚠ 选一首歌或上传"
    src = ROOT / song_rel
    if not src.exists():
        return None, None, None, f"❌ 找不到 {src}"

    progress(0.1, desc="检测 BPM…")
    out_dir = OUTPUTS_DIR / "midi" / src.stem
    try:
        progress(0.3, desc=f"转录 ({mode})…")
        report = audio_to_midi.quick_transcribe(
            src,
            output_dir=out_dir,
            mode=mode,
            with_bpm=bool(with_bpm),
            with_markers=bool(with_markers),
            embed_meta=bool(embed_meta),
        )
        progress(1.0, desc="完成")
    except Exception as e:
        return None, None, None, f"❌ {e}"

    if not report["ok"]:
        msg = "❌ 转换失败\n" + "\n".join(report["errors"])
        return None, None, None, msg

    files = [str(p) for p in report["files"]]
    mid = next((p for p in files if p.endswith(".mid")), None)
    bpm_file = next((p for p in files if p.endswith("bpm.txt")), None)
    markers_file = next((p for p in files if p.endswith("markers.txt")), None)

    lines = [f"✓ 输出目录: {report['output_dir']}"]
    if report["bpm"]:
        lines.append(f"  BPM: {report['bpm']:.1f}")
    if report["melodic"]:
        m = report["melodic"]
        lines.append(f"  melodic: {m['notes']} 个音符" if m["ok"] else f"  melodic 失败: {m['error']}")
    if report["drums"]:
        d = report["drums"]
        lines.append(f"  drums:   kick={d['kicks']} snare={d['snares']} hh={d['hihats']}"
                     if d["ok"] else f"  drums 失败: {d['error']}")
    if report.get("stems"):
        lines.append(f"  📤 分轨 ({len(report['stems'])} 个 stem):")
        for stem_name, r in report["stems"].items():
            if r["ok"]:
                if stem_name == "drums":
                    lines.append(f"    {stem_name:8} kick={r['kicks']} snare={r['snares']} hh={r['hihats']}")
                else:
                    lines.append(f"    {stem_name:8} {r['notes']} 个音符")
            else:
                lines.append(f"    {stem_name:8} ❌ {r['error']}")
    if report["markers"]:
        lines.append(f"  段落 marker: {len(report['markers'])} 个 ({report['markers'][0]['name']} … {report['markers'][-1]['name']})")
    if report["errors"]:
        lines.append("⚠ 警告:")
        lines.extend("  " + e for e in report["errors"])

    return mid, bpm_file, markers_file, "\n".join(lines)


def qm_run_upload(uploaded_file, mode, with_bpm, with_markers, embed_meta, progress=gr.Progress()):
    """直接对上传的音频跑(不需要先放 outputs)"""
    if uploaded_file is None:
        return None, None, None, "⚠ 先上传音频文件"
    src = Path(uploaded_file.name if hasattr(uploaded_file, "name") else uploaded_file)
    if not src.exists():
        return None, None, None, f"❌ 文件丢失: {src}"

    progress(0.1, desc="检测 BPM…")
    out_dir = OUTPUTS_DIR / "midi" / src.stem
    try:
        progress(0.3, desc=f"转录 ({mode})…")
        report = audio_to_midi.quick_transcribe(
            src,
            output_dir=out_dir,
            mode=mode,
            with_bpm=bool(with_bpm),
            with_markers=bool(with_markers),
            embed_meta=bool(embed_meta),
        )
        progress(1.0, desc="完成")
    except Exception as e:
        return None, None, None, f"❌ {e}"

    files = [str(p) for p in report["files"]]
    mid = next((p for p in files if p.endswith(".mid")), None)
    bpm_file = next((p for p in files if p.endswith("bpm.txt")), None)
    markers_file = next((p for p in files if p.endswith("markers.txt")), None)
    lines = [f"✓ 输出目录: {report['output_dir']}"]
    if report["bpm"]:
        lines.append(f"  BPM: {report['bpm']:.1f}")
    if report["melodic"]:
        m = report["melodic"]
        lines.append(f"  melodic: {m['notes']} 个音符" if m["ok"] else f"  melodic 失败: {m['error']}")
    if report["drums"]:
        d = report["drums"]
        lines.append(f"  drums:   kick={d['kicks']} snare={d['snares']} hh={d['hihats']}"
                     if d["ok"] else f"  drums 失败: {d['error']}")
    if report.get("stems"):
        lines.append(f"  📤 分轨 ({len(report['stems'])} 个 stem):")
        for stem_name, r in report["stems"].items():
            if r["ok"]:
                if stem_name == "drums":
                    lines.append(f"    {stem_name:8} kick={r['kicks']} snare={r['snares']} hh={r['hihats']}")
                else:
                    lines.append(f"    {stem_name:8} {r['notes']} 个音符")
            else:
                lines.append(f"    {stem_name:8} ❌ {r['error']}")
    if report["markers"]:
        lines.append(f"  段落 marker: {len(report['markers'])} 个")
    return mid, bpm_file, markers_file, "\n".join(lines)


# ───────────────────────────────────────────────
# 发行打包 (v0.5.2 功能 A + C)
# ───────────────────────────────────────────────

def pk_song_choices():
    return _list_outputs_songs()


def pk_build(song_rel, uploaded, mp3, cover, lrc, midi, metadata, cover_mode,
             progress=gr.Progress()):
    audio, _label = _resolve_audio(song_rel, uploaded)
    if not audio:
        return None, "⚠ 选一首歌或上传"

    def cb(i, total, msg):
        progress(i / total, desc=msg)

    try:
        r = export_bundle.build_bundle(
            audio,
            include_mp3=bool(mp3),
            include_cover=bool(cover),
            include_lrc=bool(lrc),
            include_midi=bool(midi),
            include_metadata=bool(metadata),
            cover_mode=cover_mode,
            progress_callback=cb,
        )
    except Exception as e:
        return None, f"❌ {e}"

    lines = [f"✓ 包大小 {r['size_mb']} MB → {r['zip_path']}"]
    if r["included"]:
        lines.append("✓ 已含: " + ", ".join(r["included"]))
    if r["missing"]:
        lines.append("⚠ 缺: " + ", ".join(r["missing"]))
    if r["errors"]:
        lines.append("❌ 错误:")
        lines.extend("  " + e for e in r["errors"])
    return str(r["zip_path"]), "\n".join(lines)


def pk_highlight(song_rel, uploaded, target_sec, strategy, fade_in, fade_out,
                 progress=gr.Progress()):
    audio, _label = _resolve_audio(song_rel, uploaded)
    if not audio:
        return None, "⚠ 选一首歌或上传"

    progress(0.1, desc="加载音频…")
    try:
        progress(0.4, desc=f"切 {int(target_sec)}s 片段({strategy})…")
        r = audio_highlight.make_highlight(
            audio,
            target_seconds=float(target_sec),
            strategy=strategy,
            fade_in_ms=float(fade_in),
            fade_out_ms=float(fade_out),
        )
        progress(1.0, desc="完成")
    except Exception as e:
        return None, f"❌ {e}"

    if not r["ok"]:
        return None, f"❌ {r.get('error')}"
    msg = (f"✓ {r['strategy_used']}\n"
           f"  片段: {r['start_sec']:.1f}s ~ {r['end_sec']:.1f}s "
           f"({r['duration']:.1f}s)\n"
           f"  输出: {r['output_path']}")
    return str(r["output_path"]), msg


# ───────────────────────────────────────────────
# LoRA 合并 (v0.5.2 功能 B) — 嵌入 LoRA 库 Tab
# ───────────────────────────────────────────────

def lo_merge_run(name_a, name_b, weight_a, weight_b, output_name, normalize,
                 write_config):
    if not name_a or not name_b:
        return "⚠ A 和 B 都要选"
    if name_a == name_b:
        return "⚠ A 和 B 不能是同一个"

    # 找 .safetensors 路径
    src_a = src_b = None
    for ext in lora_manager.WEIGHT_EXTS:
        if (lora_manager.LORAS_DIR / f"{name_a}{ext}").exists():
            src_a = lora_manager.LORAS_DIR / f"{name_a}{ext}"
            break
    for ext in lora_manager.WEIGHT_EXTS:
        if (lora_manager.LORAS_DIR / f"{name_b}{ext}").exists():
            src_b = lora_manager.LORAS_DIR / f"{name_b}{ext}"
            break

    if not src_a or not src_b:
        return f"❌ 找不到权重文件 ({name_a} / {name_b})"

    # 只支持 .safetensors 融合
    if src_a.suffix != ".safetensors" or src_b.suffix != ".safetensors":
        return ("❌ 目前只支持 .safetensors 融合。"
                f"A={src_a.suffix} B={src_b.suffix}")

    try:
        r = lora_merge.merge_two(
            src_a, src_b,
            weight_a=float(weight_a), weight_b=float(weight_b),
            output_name=(output_name or "").strip() or None,
            normalize=bool(normalize),
        )
    except Exception as e:
        return f"❌ {e}"

    if not r["ok"]:
        return f"❌ {r.get('error')}"

    msg_lines = [
        f"✓ 融合完成 → {r['output_path']} ({r['size_mb']} MB)",
        f"  实际权重: A={r['weight_a']:.3f}, B={r['weight_b']:.3f}",
        f"  张量: 共同 {r['common_keys']} / 仅 A {r['only_a_keys']} / 仅 B {r['only_b_keys']}",
    ]
    if r["shape_mismatches"]:
        msg_lines.append(f"⚠ {len(r['shape_mismatches'])} 个张量形状不匹配,只用 A 的:")
        for sm in r["shape_mismatches"][:3]:
            msg_lines.append(f"    {sm}")

    if write_config:
        try:
            cfg_path = lora_merge.auto_generate_config(
                r["output_path"], src_a, src_b, r["weight_a"], r["weight_b"],
            )
            msg_lines.append(f"✓ 自动写配置 → {cfg_path}")
        except Exception as e:
            msg_lines.append(f"⚠ 配置写入失败: {e}")

    msg_lines.append("→ 点击 LoRA 库顶部「🔄 重新扫描」就能看到新 LoRA")
    return "\n".join(msg_lines)


# ───────────────────────────────────────────────
# 中文 → 拼音 (v0.5.2 功能 D) — 嵌入 Prompt 工作室 Tab
# ───────────────────────────────────────────────

def py_convert(text, tone, fmt):
    if not (text or "").strip():
        return ""
    try:
        if fmt == "并排显示 (汉字 + 拼音)":
            return pinyin_tools.mixed_format(text, tone=tone)
        elif fmt == "纯拼音 (送 prompt)":
            return pinyin_tools.to_pinyin_inline(text, tone=tone)
        else:
            return pinyin_tools.to_pinyin(text, tone=tone)
    except Exception as e:
        return f"❌ {e}\n\n提示: 没装 pypinyin? pip install pypinyin"


# ───────────────────────────────────────────────
# UI 组装
# ───────────────────────────────────────────────

with gr.Blocks(title="AI Music Lab 控制台") as app:
    # 跨 Tab 共享: 历史里选中的歌的相对路径 (相对 ROOT)
    selected_song = gr.State("")

    gr.Markdown("""
# 🎵 AI Music Lab 控制台

🎹 **生成新歌请打开 [ACE-Step 主 UI](http://localhost:7860)** (另跑 `start_gradio_ui.bat`)

12 个 Tab: 历史 / LoRA 数据 / DAW 导出 / 后处理 / Prompt 工作室 / LoRA 库 / 批量生成 / A/B 对比 / 封面&字幕 / 续写&翻唱 / 一键 MIDI / 发行打包。
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
                        row_count=20,
                        column_count=(8, "fixed"),
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
                row_count=10,
                column_count=(5, "fixed"),
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

            with gr.Accordion("📤 或上传外部音频 (Suno / Udio / 任意 mp3 wav flac)", open=False):
                d_upload = gr.File(label="拖音频进来 (上传优先于上面下拉)",
                                   file_types=["audio"], type="filepath")

            d_go_btn = gr.Button("🚀 开始处理", variant="primary", size="lg")
            d_result = gr.Textbox(label="结果", lines=3, interactive=False)
            d_log = gr.Textbox(label="过程日志", lines=20, interactive=False)

            d_refresh_btn.click(lambda: gr.update(choices=_list_outputs_songs()),
                                outputs=[d_dropdown])
            d_use_history_btn.click(d_use_history_selection,
                                    [selected_song], [d_dropdown, d_log])
            d_go_btn.click(d_process,
                           [d_dropdown, d_upload, d_do_midi, d_project_name],
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

        # ─── Tab 5: Prompt 工作室 (#4) ───
        with gr.TabItem("📝 Prompt 工作室"):
            gr.Markdown("""
读写 `prompts/styles.json`。**左边**: 预设的整段 prompt,选一个直接复制到 ACE-Step 用。
**右边**: 按分类挑 tag,自动组合成 prompt。试出好组合点 💾 加进预设。
""")
            with gr.Row():
                # 左: 预设
                with gr.Column(scale=1):
                    gr.Markdown("### 📦 预设")
                    ps_dropdown = gr.Dropdown(
                        label="选预设",
                        choices=[n for n, _ in prompt_library.list_presets()],
                        interactive=True,
                    )
                    with gr.Row():
                        ps_refresh_btn = gr.Button("🔄", size="sm")
                        ps_delete_btn = gr.Button("🗑 删除", size="sm", variant="stop")
                    ps_preset_text = gr.Textbox(label="预设内容(可编辑后保存覆盖)",
                                                lines=3, interactive=True)
                    with gr.Row():
                        ps_save_name = gr.Textbox(label="保存为(新建)或保留原名覆盖",
                                                  placeholder="例: my-folk-v2", scale=2)
                        ps_save_btn = gr.Button("💾 保存", variant="primary", scale=1)
                    ps_status = gr.Textbox(label="状态", interactive=False)

                # 右: tag 积木
                with gr.Column(scale=2):
                    gr.Markdown("### 🧩 tag 积木 (多选, 自动拼)")
                    ps_tag_pickers = []
                    for cat in prompt_library.list_categories():
                        picker = gr.Dropdown(
                            label=cat,
                            choices=prompt_library.list_tags(cat),
                            multiselect=True,
                            interactive=True,
                        )
                        ps_tag_pickers.append(picker)
                    ps_extra = gr.Textbox(label="额外手写 (逗号分隔)",
                                          placeholder="例: 70 bpm, dreamy")
                    ps_built = gr.Textbox(label="🪄 组合结果 (复制到 ACE-Step)",
                                          lines=3, interactive=True)
                    ps_build_btn = gr.Button("🪄 组合 prompt", variant="primary")
                    gr.Markdown("**写作提示**: " + " · ".join(prompt_library.get_writing_tips()[:3]))

            ps_dropdown.change(ps_load_preset, [ps_dropdown], [ps_preset_text])
            ps_refresh_btn.click(ps_refresh_presets, outputs=[ps_dropdown])
            ps_delete_btn.click(ps_delete_preset, [ps_dropdown], [ps_status]).then(
                ps_refresh_presets, outputs=[ps_dropdown])
            ps_save_btn.click(ps_save_preset, [ps_save_name, ps_preset_text],
                              [ps_status]).then(
                ps_refresh_presets, outputs=[ps_dropdown])
            ps_build_btn.click(ps_build_from_tags,
                               ps_tag_pickers + [ps_extra], [ps_built])

            # ─── 子工具: 中文 → 拼音 (v0.5.2 #D) ───
            gr.Markdown("---")
            gr.Markdown("""### 🈶 中文 → 拼音 (训中文 LoRA / 写中文歌词必备)
ACE-Step 对**拼音**识别率比汉字高很多(模型在英文+拼音上训得多)。""")
            with gr.Row():
                with gr.Column(scale=2):
                    py_in = gr.Textbox(label="中文输入",
                                       lines=8,
                                       placeholder="支持章节标签 [Verse 1] [Chorus] 等(保留不转)")
                with gr.Column(scale=2):
                    py_out = gr.Textbox(label="拼音输出 (可复制)",
                                        lines=8, interactive=True)
            with gr.Row():
                py_tone = gr.Radio(
                    [("带音调 nǐ hǎo", "tone_marks"),
                     ("数字调 ni3 hao3", "numbers"),
                     ("无音调 ni hao", "none")],
                    label="音调样式",
                    value="tone_marks",
                )
                py_fmt = gr.Radio(
                    ["逐行 (歌词模式)", "并排显示 (汉字 + 拼音)", "纯拼音 (送 prompt)"],
                    label="格式",
                    value="逐行 (歌词模式)",
                )
                py_btn = gr.Button("🈶 转换", variant="primary")
            py_btn.click(py_convert, [py_in, py_tone, py_fmt], [py_out])

        # ─── Tab 6: LoRA 库 (#5) ───
        with gr.TabItem("🎓 LoRA 库"):
            gr.Markdown("""
扫描 `loras/`,管理每个 LoRA 的配置(描述/数据源/推荐 prompt)
并一键生成 3 首示例曲(用不同 seed 同 prompt)。
**自动试听需要 ACE-Step 装好**(批量场景占用大,跑前关掉 ACE-Step 主 UI)。
""")
            with gr.Row():
                with gr.Column(scale=2):
                    lm_table = gr.Dataframe(
                        headers=["名称", "格式", "大小", "配置", "描述", "tags"],
                        datatype=["str"] * 6,
                        interactive=False,
                        row_count=8,
                        column_count=(6, "fixed"),
                        wrap=True,
                    )
                    lm_refresh_btn = gr.Button("🔄 重新扫描 loras/", size="sm")

                with gr.Column(scale=2):
                    gr.Markdown("### 配置")
                    lm_dropdown = gr.Dropdown(label="选 LoRA", choices=[], interactive=True)
                    lm_path_hint = gr.Markdown("配置: —")
                    lm_desc = gr.Textbox(label="描述", lines=2)
                    lm_dataset = gr.Textbox(label="数据来源", placeholder="哪些歌、多少首")
                    lm_rec_prompt = gr.Textbox(label="推荐 prompt", lines=2,
                                               placeholder="叠这个 LoRA 时建议的 prompt 写法")
                    with gr.Row():
                        lm_steps = gr.Number(label="训练步数", value=0, precision=0)
                        lm_lr = gr.Number(label="学习率", value=0.0)
                    lm_tags = gr.Textbox(label="主要风格 tag (逗号分隔)")
                    lm_notes = gr.Textbox(label="用法备注", lines=2)
                    lm_save_btn = gr.Button("💾 保存配置", variant="primary")
                    lm_save_status = gr.Textbox(label="保存结果", interactive=False)

            gr.Markdown("---")
            gr.Markdown("### 🎵 自动试听 (调 ACE-Step 生成 N 首示例)")
            with gr.Row():
                lm_test_prompt = gr.Textbox(
                    label="测试 prompt (留空用配置里的 recommended_prompt)",
                    scale=3,
                )
                lm_test_seeds = gr.Textbox(label="seeds (逗号分隔)",
                                           value="42,1337,9999", scale=1)
                lm_test_duration = gr.Number(label="时长(秒)", value=30, scale=1)
            lm_test_btn = gr.Button("🚀 生成示例", variant="primary")
            lm_test_status = gr.Textbox(label="进度", interactive=False)
            lm_test_files = gr.Files(label="生成的样本(下载/试听)")

            lm_dropdown.change(
                lm_load_config, [lm_dropdown],
                [lm_desc, lm_dataset, lm_rec_prompt, lm_steps, lm_lr,
                 lm_tags, lm_notes, lm_path_hint],
            )
            lm_save_btn.click(
                lm_save_config,
                [lm_dropdown, lm_desc, lm_dataset, lm_rec_prompt,
                 lm_steps, lm_lr, lm_tags, lm_notes],
                [lm_save_status],
            )
            lm_test_btn.click(
                lm_generate_samples,
                [lm_dropdown, lm_test_prompt, lm_test_seeds, lm_test_duration],
                [lm_test_status, lm_test_files],
            )

            # ─── 子工具: LoRA 权重融合 (v0.5.2 #B) ───
            gr.Markdown("---")
            gr.Markdown("""### 🔀 LoRA 权重融合
线性插值两个 LoRA 的 .safetensors,产新文件,跟原 LoRA 一样用。
公式: `merged = wa·A + wb·B` (共同 key)。**只支持 .safetensors**。
**装 safetensors**: `pip install safetensors` (没装会报错)。""")
            with gr.Row():
                lo_a = gr.Dropdown(label="LoRA A", choices=[], interactive=True)
                lo_wa = gr.Slider(label="A 权重", minimum=0.0, maximum=2.0,
                                  step=0.05, value=0.5)
                lo_b = gr.Dropdown(label="LoRA B", choices=[], interactive=True)
                lo_wb = gr.Slider(label="B 权重", minimum=0.0, maximum=2.0,
                                  step=0.05, value=0.5)
            with gr.Row():
                lo_outname = gr.Textbox(label="输出名 (不含扩展名,留空自动 A_x_B)",
                                        placeholder="例: rock-folk-blend-v1")
                lo_normalize = gr.Checkbox(label="归一化权重 (wa+wb=1)", value=False)
                lo_write_cfg = gr.Checkbox(label="自动写 .json 配置", value=True)
            lo_merge_btn = gr.Button("🔀 融合", variant="primary")
            lo_merge_status = gr.Textbox(label="结果", lines=6, interactive=False)

            # 刷新表的时候顺便刷新 merge 下拉
            def _lm_refresh_all():
                rows, dd = lm_scan_table()
                names = [l["name"] for l in lora_manager.scan_loras()]
                return rows, dd, gr.update(choices=names), gr.update(choices=names)

            lm_refresh_btn.click(
                _lm_refresh_all,
                outputs=[lm_table, lm_dropdown, lo_a, lo_b],
            )
            lo_merge_btn.click(
                lo_merge_run,
                [lo_a, lo_b, lo_wa, lo_wb, lo_outname, lo_normalize, lo_write_cfg],
                [lo_merge_status],
            )

        # ─── Tab 7: 批量生成 (#6) ───
        with gr.TabItem("🚀 批量生成"):
            gr.Markdown("""
从 CSV 读 N 行 prompt 挂机跑。每首歌写到 `outputs/batches/<run-name>/row-XXX.wav`。

**CSV 列**(顺序可乱,| 或 , 分隔):
`prompt | lyrics | duration | seed | lora | infer_step | guidance_scale | filename`

**dry-run**: 只验证 CSV 不真生成。先 dry-run 一次,确认任务列表对再正式跑。
""")
            with gr.Row():
                with gr.Column(scale=1):
                    bg_file = gr.File(label="上传 CSV", file_types=[".csv", ".txt"])
                    bg_template_btn = gr.Button("📄 看模板 CSV", size="sm")
                    bg_template_text = gr.Textbox(label="模板 (复制后另存为 .csv 编辑)",
                                                  value="", interactive=False,
                                                  lines=4, max_lines=8)
                with gr.Column(scale=2):
                    bg_table = gr.Dataframe(
                        headers=["#", "prompt", "lyrics", "时长", "seed", "lora", "filename"],
                        datatype=["number"] + ["str"] * 6,
                        interactive=False,
                        row_count=8,
                        column_count=(7, "fixed"),
                        wrap=True,
                    )
                    with gr.Row():
                        bg_run_name = gr.Textbox(label="run 名 (留空用时间戳)",
                                                 placeholder="例: monday-folk-batch")
                        bg_dry = gr.Checkbox(label="dry-run (不真生成)", value=True)
                    with gr.Row():
                        bg_preview_btn = gr.Button("👀 预览", size="sm")
                        bg_run_btn = gr.Button("🚀 开跑", variant="primary")
                        bg_stop_btn = gr.Button("⏸ 停止", variant="stop", size="sm")

            bg_status = gr.Textbox(label="状态", interactive=False)
            bg_report_path = gr.Textbox(label="report.txt 路径", interactive=False)
            bg_result_table = gr.Dataframe(
                headers=["#", "状态", "输出", "错误(首行)"],
                datatype=["number", "str", "str", "str"],
                interactive=False,
                row_count=10,
                column_count=(4, "fixed"),
                wrap=True,
            )

            bg_template_btn.click(bg_load_template, outputs=[bg_template_text])
            bg_preview_btn.click(bg_preview_csv, [bg_file], [bg_status, bg_table])
            bg_run_btn.click(bg_run, [bg_file, bg_run_name, bg_dry],
                             [bg_status, bg_report_path, bg_result_table])
            bg_stop_btn.click(bg_stop, outputs=[bg_status])

        # ─── Tab 8: A/B 对比 (#7) ───
        with gr.TabItem("⚖ A/B 对比"):
            gr.Markdown("""
从历史里挑两首歌并排放,对比 prompt / seed / LoRA / 评分 差异。
**试听**: 各自播放器独立。先按需要点'刷新列表'同步最新历史。
""")
            ab_refresh_btn = gr.Button("🔄 刷新历史列表", size="sm")

            with gr.Row():
                with gr.Column():
                    gr.Markdown("### 🅰 A 版本")
                    ab_left_pick = gr.Dropdown(
                        label="选歌", choices=ab_song_choices(), interactive=True,
                    )
                    ab_left_audio = gr.Audio(label="试听 A", interactive=False)
                    ab_left_name = gr.Textbox(label="文件名", interactive=False)
                    ab_left_prompt = gr.Textbox(label="Prompt", lines=2, interactive=False)
                    ab_left_lyrics = gr.Textbox(label="歌词", lines=4, interactive=False)
                    with gr.Row():
                        ab_left_seed = gr.Textbox(label="Seed", interactive=False)
                        ab_left_lora = gr.Textbox(label="LoRA", interactive=False)
                    ab_left_rating = gr.Textbox(label="评分", interactive=False)

                with gr.Column():
                    gr.Markdown("### 🅱 B 版本")
                    ab_right_pick = gr.Dropdown(
                        label="选歌", choices=ab_song_choices(), interactive=True,
                    )
                    ab_right_audio = gr.Audio(label="试听 B", interactive=False)
                    ab_right_name = gr.Textbox(label="文件名", interactive=False)
                    ab_right_prompt = gr.Textbox(label="Prompt", lines=2, interactive=False)
                    ab_right_lyrics = gr.Textbox(label="歌词", lines=4, interactive=False)
                    with gr.Row():
                        ab_right_seed = gr.Textbox(label="Seed", interactive=False)
                        ab_right_lora = gr.Textbox(label="LoRA", interactive=False)
                    ab_right_rating = gr.Textbox(label="评分", interactive=False)

            ab_refresh_btn.click(
                lambda: (gr.update(choices=ab_song_choices()),
                         gr.update(choices=ab_song_choices())),
                outputs=[ab_left_pick, ab_right_pick],
            )
            ab_left_pick.change(
                ab_load_left, [ab_left_pick],
                [ab_left_audio, ab_left_name, ab_left_prompt, ab_left_lyrics,
                 ab_left_seed, ab_left_lora, ab_left_rating],
            )
            ab_right_pick.change(
                ab_load_right, [ab_right_pick],
                [ab_right_audio, ab_right_name, ab_right_prompt, ab_right_lyrics,
                 ab_right_seed, ab_right_lora, ab_right_rating],
            )

        # ─── Tab 9: 封面 & 字幕 (#9 #10) ───
        with gr.TabItem("🎨 封面 & 字幕"):
            gr.Markdown("""
**封面**: 'geometric' 模式 0 显存 (PIL 几何) · 'sdxl' 模式 6-8GB VRAM (装 diffusers,首次下 ~6GB 模型)。
**字幕**: 导出 `.lrc` 文件,'even' 模式按行均分(无依赖)· 'whisper' 模式音频对齐(装 openai-whisper)。
""")
            with gr.Row():
                cv_song = gr.Dropdown(label="选 outputs/ 里的歌",
                                      choices=cv_song_choices(), interactive=True)
                cv_refresh_btn = gr.Button("🔄", size="sm")
                cv_use_hist = gr.Button("⬅ 用历史 Tab 选中的歌", size="sm")

            with gr.Accordion("📤 或上传外部音频 (Suno / Udio / 任意 mp3 wav flac)", open=False):
                cv_upload = gr.File(label="拖音频进来 (上传优先于上面下拉)",
                                    file_types=["audio"], type="filepath")

            with gr.Row():
                # 封面侧
                with gr.Column():
                    gr.Markdown("### 🎨 封面")
                    cv_title = gr.Textbox(label="标题 (留空用文件名)")
                    cv_subtitle = gr.Textbox(label="副标题",
                                             placeholder="例: synthwave · 2026")
                    cv_mode = gr.Radio(["geometric", "sdxl"], label="模式",
                                       value="geometric")
                    cv_sdxl_prompt = gr.Textbox(
                        label="SDXL prompt (仅 sdxl 模式)",
                        placeholder="例: retro 80s neon city, vaporwave aesthetic",
                    )
                    cv_embed = gr.Checkbox(label="同时嵌入到 MP3 ID3 (需要同名 .mp3)",
                                           value=False)
                    cv_make_cover_btn = gr.Button("🎨 生成封面", variant="primary")
                    cv_cover_img = gr.Image(label="封面", type="filepath",
                                            interactive=False)
                    cv_cover_status = gr.Textbox(label="状态", interactive=False, lines=2)

                # 字幕侧
                with gr.Column():
                    gr.Markdown("### 🎤 LRC 字幕")
                    cv_lrc_lyrics = gr.Textbox(
                        label="歌词覆盖 (留空从历史索引读)",
                        lines=8,
                        placeholder="一行一句,空行/章节标签会被跳过",
                    )
                    cv_lrc_mode = gr.Radio(["even", "whisper"], label="对齐",
                                           value="even")
                    cv_lrc_intro = gr.Number(label="前奏空 N 秒 (even 模式)",
                                             value=4.0)
                    with gr.Row():
                        cv_lrc_title = gr.Textbox(label="标题 [ti:]")
                        cv_lrc_artist = gr.Textbox(label="演唱者 [ar:]", value="AI")
                    cv_make_lrc_btn = gr.Button("🎤 生成 LRC", variant="primary")
                    cv_lrc_file = gr.File(label="下载 .lrc", interactive=False)
                    cv_lrc_status = gr.Textbox(label="状态", interactive=False, lines=2)

            cv_refresh_btn.click(lambda: gr.update(choices=cv_song_choices()),
                                 outputs=[cv_song])
            cv_use_hist.click(
                lambda rel: gr.update(value=rel) if rel else gr.update(),
                [selected_song], [cv_song],
            )
            cv_make_cover_btn.click(
                cv_make_cover,
                [cv_song, cv_upload, cv_title, cv_subtitle, cv_mode, cv_sdxl_prompt, cv_embed],
                [cv_cover_img, cv_cover_status],
            )
            cv_make_lrc_btn.click(
                cv_make_lrc,
                [cv_song, cv_upload, cv_lrc_lyrics, cv_lrc_mode, cv_lrc_intro,
                 cv_lrc_title, cv_lrc_artist],
                [cv_lrc_file, cv_lrc_status],
            )

        # ─── Tab 10: 续写 / 翻唱 (#11 #12) ───
        with gr.TabItem("🔁 续写 / 翻唱"):
            gr.Markdown("""
两种 audio2audio 变体:
- **续写**: 给已有歌加 N 秒(头或尾),保持风格连贯
- **翻唱**: 保留旋律/结构, 换新风格/新词 (ref_audio_strength 控制保留度)

**两者都需要 ACE-Step 在线**(首次调用加载 pipeline 慢,后续秒级)。
""")
            with gr.Row():
                rv_song = gr.Dropdown(label="选源歌",
                                      choices=rv_song_choices(), interactive=True)
                rv_refresh_btn = gr.Button("🔄", size="sm")
                rv_use_hist = gr.Button("⬅ 用历史 Tab 选中的歌", size="sm")

            with gr.Accordion("📤 或上传外部音频 (Suno / Udio / 任意 mp3 wav flac)", open=False):
                rv_upload = gr.File(label="拖音频进来 (上传优先于上面下拉)",
                                    file_types=["audio"], type="filepath")

            with gr.Tabs():
                # 续写
                with gr.TabItem("续写 (extend)"):
                    with gr.Row():
                        ext_seconds = gr.Slider(label="续写时长(秒)", minimum=5,
                                                maximum=60, step=5, value=20)
                        ext_dir = gr.Radio(["tail", "head"], label="方向",
                                           value="tail")
                    ext_prompt = gr.Textbox(label="风格 prompt (留空保留原风格)",
                                            placeholder="不填则跟源歌一致")
                    ext_lyrics = gr.Textbox(label="续写歌词", lines=3)
                    ext_seed = gr.Textbox(label="Seed (可留空随机)")
                    ext_btn = gr.Button("🔁 续写", variant="primary")
                    ext_audio = gr.Audio(label="续写结果", interactive=False)
                    ext_status = gr.Textbox(label="状态", interactive=False)

                # 翻唱
                with gr.TabItem("翻唱 (cover)"):
                    cov_prompt = gr.Textbox(label="新风格 prompt (必填)",
                                            placeholder="例: punk rock, male vocal, distorted")
                    cov_lyrics = gr.Textbox(label="新歌词 (留空保留原词)", lines=4)
                    cov_strength = gr.Slider(
                        label="保留源歌强度 (0=全新, 1=照搬, 0.4-0.6 甜区)",
                        minimum=0.0, maximum=1.0, step=0.05, value=0.5,
                    )
                    cov_seed = gr.Textbox(label="Seed (可留空随机)")
                    cov_btn = gr.Button("🔁 翻唱", variant="primary")
                    cov_audio = gr.Audio(label="翻唱结果", interactive=False)
                    cov_status = gr.Textbox(label="状态", interactive=False)

            rv_refresh_btn.click(lambda: gr.update(choices=rv_song_choices()),
                                 outputs=[rv_song])
            rv_use_hist.click(
                lambda rel: gr.update(value=rel) if rel else gr.update(),
                [selected_song], [rv_song],
            )
            ext_btn.click(
                rv_extend,
                [rv_song, rv_upload, ext_seconds, ext_dir, ext_prompt, ext_lyrics, ext_seed],
                [ext_audio, ext_status],
            )
            cov_btn.click(
                rv_cover,
                [rv_song, rv_upload, cov_prompt, cov_lyrics, cov_strength, cov_seed],
                [cov_audio, cov_status],
            )

        # ─── Tab 11: 一键转 MIDI (v0.5.1) ───
        with gr.TabItem("🎼 一键 MIDI"):
            gr.Markdown("""
**整曲音频 → MIDI + BPM + 段落 marker**

**输出**: `outputs/midi/<歌名>/`

**模式**:
- `melodic` (默认,快 ~10s): Basic Pitch 抓主旋律 → **1 个 melodic.mid**(所有乐器混一起)
- `drums` (快): onset 分类成 kick/snare/hh → 1 个 drums.mid
- `both` (快): melodic + drums 两个 mid
- `split` (慢 ~1-3 分钟,**推荐想分轨导 DAW 用**):
  Demucs 先拆 6 stem,每个 stem 单独出 MIDI → **6 个 mid**(bass / vocals / guitar / piano / other / drums),导 DAW 后每条轨挂不同 VST

**首次跑**: Basic Pitch ~150MB(melodic/both),Demucs ~5GB(split)。
""")
            with gr.Row():
                with gr.Column(scale=2):
                    gr.Markdown("### 从 outputs/ 选歌")
                    qm_song = gr.Dropdown(label="选歌",
                                          choices=qm_song_choices(), interactive=True)
                    with gr.Row():
                        qm_refresh_btn = gr.Button("🔄", size="sm")
                        qm_use_hist = gr.Button("⬅ 用历史 Tab 选中的歌",
                                                size="sm", variant="secondary")

                with gr.Column(scale=2):
                    gr.Markdown("### 或上传任意音频")
                    qm_upload = gr.File(label="拖音频进来",
                                        file_types=["audio"], type="filepath")

            gr.Markdown("---")
            with gr.Row():
                qm_mode = gr.Radio(["melodic", "drums", "both", "split"],
                                   label="转录模式", value="melodic",
                                   info="split = 拆轨 (Demucs, 慢但分乐器), 其它 = 整曲直转 (快)")
                qm_with_bpm = gr.Checkbox(label="检测 BPM 并写 bpm.txt", value=True)
                qm_with_markers = gr.Checkbox(label="检测段落 marker 并写 markers.txt",
                                              value=True)
                qm_embed = gr.Checkbox(label="把 BPM / marker 嵌进 .mid",
                                       value=True)

            with gr.Row():
                qm_run_btn = gr.Button("🎼 从 outputs/ 转", variant="primary")
                qm_run_upload_btn = gr.Button("🎼 转上传的音频", variant="primary")

            qm_status = gr.Textbox(label="结果", lines=6, interactive=False)
            with gr.Row():
                qm_mid_out = gr.File(label="MIDI 文件(主)", interactive=False)
                qm_bpm_out = gr.File(label="bpm.txt", interactive=False)
                qm_markers_out = gr.File(label="markers.txt", interactive=False)

            qm_refresh_btn.click(lambda: gr.update(choices=qm_song_choices()),
                                 outputs=[qm_song])
            qm_use_hist.click(
                lambda rel: gr.update(value=rel) if rel else gr.update(),
                [selected_song], [qm_song],
            )
            qm_run_btn.click(
                qm_run,
                [qm_song, qm_mode, qm_with_bpm, qm_with_markers, qm_embed],
                [qm_mid_out, qm_bpm_out, qm_markers_out, qm_status],
            )
            qm_run_upload_btn.click(
                qm_run_upload,
                [qm_upload, qm_mode, qm_with_bpm, qm_with_markers, qm_embed],
                [qm_mid_out, qm_bpm_out, qm_markers_out, qm_status],
            )

        # ─── Tab 12: 发行打包 (v0.5.2 #A + #C) ───
        with gr.TabItem("📦 发行打包"):
            gr.Markdown("""
发歌前的最后一步:
- **打包**:一键把 wav + mp3 + cover + lrc + mid + metadata 打成 zip,给朋友/平台投稿
- **剪短版**:从全曲检测 chorus,截 30 秒带淡入淡出的预告片,发社交平台
""")
            with gr.Row():
                pk_song = gr.Dropdown(label="选 outputs/ 里的歌",
                                      choices=pk_song_choices(), interactive=True)
                pk_refresh_btn = gr.Button("🔄", size="sm")
                pk_use_hist = gr.Button("⬅ 用历史 Tab 选中的歌", size="sm")

            with gr.Accordion("📤 或上传外部音频 (Suno / Udio / 任意 mp3 wav flac)", open=False):
                pk_upload = gr.File(label="拖音频进来 (上传优先于上面下拉)",
                                    file_types=["audio"], type="filepath")

            with gr.Row():
                # 打包侧
                with gr.Column():
                    gr.Markdown("### 📦 打包成 zip")
                    pk_inc_mp3 = gr.Checkbox(label="含 MP3 (没 mp3 会自动转)",
                                             value=True)
                    pk_inc_cover = gr.Checkbox(label="含封面 (没有则生成)",
                                               value=True)
                    pk_cover_mode = gr.Radio(["geometric", "sdxl"],
                                             label="自动生成封面用哪种",
                                             value="geometric")
                    pk_inc_lrc = gr.Checkbox(label="含歌词 .lrc (没有则按均分生成)",
                                             value=True)
                    pk_inc_midi = gr.Checkbox(label="含主旋律 .mid (没有则用 Basic Pitch 现转)",
                                              value=True)
                    pk_inc_meta = gr.Checkbox(label="含 metadata.json (从历史索引导出)",
                                              value=True)
                    pk_build_btn = gr.Button("📦 打包", variant="primary")
                    pk_zip_out = gr.File(label="下载 zip", interactive=False)
                    pk_build_status = gr.Textbox(label="状态", lines=5, interactive=False)

                # 剪短版侧
                with gr.Column():
                    gr.Markdown("### ✂ 自动剪短版 (chorus 检测)")
                    with gr.Row():
                        pk_target = gr.Slider(label="目标时长 (秒)",
                                              minimum=15, maximum=90, step=5,
                                              value=30)
                        pk_strategy = gr.Radio(["chorus", "middle", "start"],
                                               label="策略", value="chorus")
                    with gr.Row():
                        pk_fade_in = gr.Number(label="淡入 (ms)", value=50)
                        pk_fade_out = gr.Number(label="淡出 (ms)", value=1000)
                    pk_clip_btn = gr.Button("✂ 剪短版", variant="primary")
                    pk_clip_audio = gr.Audio(label="预览", interactive=False)
                    pk_clip_status = gr.Textbox(label="状态", lines=4, interactive=False)

            pk_refresh_btn.click(lambda: gr.update(choices=pk_song_choices()),
                                 outputs=[pk_song])
            pk_use_hist.click(
                lambda rel: gr.update(value=rel) if rel else gr.update(),
                [selected_song], [pk_song],
            )
            pk_build_btn.click(
                pk_build,
                [pk_song, pk_upload, pk_inc_mp3, pk_inc_cover, pk_inc_lrc,
                 pk_inc_midi, pk_inc_meta, pk_cover_mode],
                [pk_zip_out, pk_build_status],
            )
            pk_clip_btn.click(
                pk_highlight,
                [pk_song, pk_upload, pk_target, pk_strategy, pk_fade_in, pk_fade_out],
                [pk_clip_audio, pk_clip_status],
            )

    gr.Markdown("""
---

**端口 7861** · 关掉窗口即停止. 跨 Tab 联动通过 `outputs/` 文件系统自动生效.
""")


if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7861, inbrowser=False)
