#!/usr/bin/env python3
"""LoRA 训练数据准备 wizard (Gradio UI)

工作流:
1. 把参考音频(MP3/WAV)放到 datasets/<项目名>/raw/ 目录
2. 启动这个 UI: python scripts/lora-wizard.py
3. 输入项目名 → 点"分析" → 看每首歌的 BPM/key + 建议 caption
4. 在表格里编辑 caption
5. 点"导出训练集" → 生成 datasets/<项目名>/audio/ + metadata.csv
6. 把 datasets/<项目名>/ 路径填到 ACE-Step UI 的 LoRA Training 标签里训练

打开: http://localhost:7862
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gradio as gr
from lib import training_data

DATASETS_DIR = ROOT / "datasets"
DATASETS_DIR.mkdir(parents=True, exist_ok=True)


def list_projects():
    """列出 datasets/ 下的已有项目"""
    return [p.name for p in DATASETS_DIR.iterdir() if p.is_dir()]


def do_analyze(project_name: str, target_sr: int, target_channels: int):
    """分析 + 准备数据集"""
    project_name = (project_name or "").strip()
    if not project_name:
        return "⚠ 请填项目名", []

    if not training_data._check_librosa():
        return "❌ librosa 未装。运行: pip install librosa soundfile", []

    project_dir = DATASETS_DIR / project_name
    raw_dir = project_dir / "raw"

    if not raw_dir.exists():
        return (
            f"❌ 没找到 {raw_dir}\n\n"
            f"请先把参考音频(MP3/WAV)放到这个目录,然后再点分析。"
        ), []

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
        f"下一步: 在下面表格里编辑 caption,然后点'保存 captions',再去 ACE-Step UI 训练。"
    )
    if report["errors"]:
        msg += "\n\n⚠ 部分失败:\n" + "\n".join(report["errors"][:5])

    return msg, rows


def do_save_captions(project_name: str, table_data):
    """把表格里改过的 caption 写回 metadata.csv"""
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


def do_create_project(new_name: str):
    """创建新项目骨架(空 raw/ 目录)"""
    new_name = (new_name or "").strip()
    if not new_name:
        return "⚠ 填个名字", gr.update()
    # 文件名清理
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in new_name)
    if safe != new_name:
        new_name = safe
    raw_dir = DATASETS_DIR / new_name / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    return (
        f"✓ 已建 {raw_dir}\n\n"
        f"现在把参考音频(MP3/WAV)拖到这个文件夹,然后回到上面点分析。",
        gr.update(choices=list_projects(), value=new_name),
    )


with gr.Blocks(title="LoRA 数据 wizard") as app:
    gr.Markdown("""
# 🎓 LoRA 训练数据准备

**工作流:**
1. 这里建项目 → 把参考音频(5-20 首)放到 `datasets/<项目名>/raw/`
2. 回到这里点「分析」→ 自动算 BPM / key + 建议 caption
3. 编辑 caption(描述每首歌的风格和特点)
4. 点「保存 captions」→ 写回 metadata.csv
5. 启动 ACE-Step UI(launch-ui.sh),切到 LoRA Training 标签,数据集填 `datasets/<项目名>/`

**Caption 写法建议**: 像写 prompt 一样描述这首歌 — 风格、人声、乐器、情绪、BPM、key。
LoRA 学的就是 caption ↔ 音频的关联,描述越精准训出来越准。
    """)

    with gr.Row():
        with gr.Column(scale=2):
            project_dropdown = gr.Dropdown(
                label="选择项目",
                choices=list_projects(),
                allow_custom_value=True,
                interactive=True,
            )
            with gr.Row():
                new_project_box = gr.Textbox(label="或新建项目", scale=2,
                                             placeholder="如: my-chinese-folk")
                create_btn = gr.Button("➕ 创建", scale=1)

        with gr.Column(scale=1):
            sr_box = gr.Number(label="目标采样率", value=44100, precision=0)
            ch_box = gr.Number(label="目标声道数(1=mono 2=stereo)", value=2, precision=0)

    analyze_btn = gr.Button("🔍 分析并准备训练集", variant="primary", size="lg")
    status_box = gr.Textbox(label="状态", interactive=False, lines=4)

    gr.Markdown("### 编辑 captions(双击单元格编辑)")
    table = gr.Dataframe(
        headers=["filename", "BPM", "key", "duration", "caption ← 在这里编辑"],
        datatype=["str", "str", "str", "str", "str"],
        interactive=True,
        row_count=(10, "dynamic"),
        col_count=(5, "fixed"),
        wrap=True,
    )

    save_btn = gr.Button("💾 保存 captions 到 metadata.csv", variant="primary")
    save_status = gr.Textbox(label="保存结果", interactive=False)

    # ─── 事件 ───
    create_btn.click(do_create_project, [new_project_box], [status_box, project_dropdown])
    analyze_btn.click(do_analyze, [project_dropdown, sr_box, ch_box], [status_box, table])
    save_btn.click(do_save_captions, [project_dropdown, table], [save_status])


if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7862, inbrowser=False)
