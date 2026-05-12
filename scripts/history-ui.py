#!/usr/bin/env python3
"""生成历史浏览器 (Gradio UI)

启动: python scripts/history-ui.py
打开: http://localhost:7861
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gradio as gr
from lib import history


# ─────────────── 辅助 ───────────────
def fmt_duration(sec):
    if not sec:
        return "?"
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def fmt_rating(n):
    n = int(n or 0)
    return "★" * n + "☆" * (5 - n)


def build_rows(results):
    rows = []
    for fid, s in results:
        rows.append([
            "⭐" if s.get("favorited") else "",
            fmt_rating(s.get("rating")),
            s.get("filename", ""),
            fmt_duration(s.get("duration_seconds")),
            (s.get("prompt") or "")[:60] + ("…" if len(s.get("prompt") or "") > 60 else ""),
            ", ".join(s.get("tags") or [])[:40],
            (s.get("created_at") or "")[:19],
            fid,  # 隐藏列,用于 select 时定位
        ])
    return rows


# ─────────────── 操作 ───────────────
def do_refresh(query, fav_only, min_rating):
    added, total = history.scan_and_update()
    results = history.search(query, fav_only, int(min_rating or 0))
    return (
        f"扫描完成 · 新增 {added} 首 · 共 {total} 首 · 当前筛选 {len(results)} 首",
        build_rows(results),
    )


def do_search(query, fav_only, min_rating):
    results = history.search(query, fav_only, int(min_rating or 0))
    return (
        f"当前筛选 {len(results)} 首",
        build_rows(results),
    )


def do_select(rows, evt: gr.SelectData):
    """点击某一行时,加载到右侧编辑器。"""
    if not rows or evt.index is None:
        return [None, "", "", "", 0, "", 0, "", False, ""]
    row_idx = evt.index[0] if isinstance(evt.index, list) else evt.index
    if row_idx >= len(rows):
        return [None, "", "", "", 0, "", 0, "", False, ""]

    fid = rows[row_idx][-1]
    index = history.load_index()
    s = index["songs"].get(fid, {})

    audio_path = ROOT / "outputs" / s.get("filename", "")
    audio = str(audio_path) if audio_path.exists() else None

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
    ]


def do_save(fid, prompt, lyrics, seed, lora, rating, tags, favorited, notes):
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


def do_delete(fid, also_file):
    if not fid:
        return "⚠ 先选一首歌", None, ""
    ok = history.delete_entry(fid, delete_file=bool(also_file))
    msg = "✓ 已删除" + (" 含文件" if also_file else " 仅索引")
    return msg, None, ""


# ─────────────── UI ───────────────
with gr.Blocks(title="ai-music-lab 历史") as app:
    gr.Markdown("# 🎵 生成历史浏览器\n所有标注、评分、标签都保存在 `outputs/.history-index.json`")

    with gr.Row():
        with gr.Column(scale=3):
            with gr.Row():
                search_box = gr.Textbox(label="搜索", placeholder="prompt / 歌词 / 标签 / 备注 / 文件名",
                                        scale=4)
                refresh_btn = gr.Button("🔄 重新扫描", scale=1)
            with gr.Row():
                fav_filter = gr.Checkbox(label="只看收藏 ⭐", value=False)
                rating_filter = gr.Slider(label="最低评分", minimum=0, maximum=5, step=1, value=0)

            status = gr.Textbox(label="状态", interactive=False)

            table = gr.Dataframe(
                headers=["⭐", "评分", "文件名", "时长", "Prompt", "Tags", "时间", "id"],
                datatype=["str"] * 8,
                interactive=False,
                row_count=(20, "dynamic"),
                col_count=(8, "fixed"),
                wrap=True,
            )

        with gr.Column(scale=2):
            gr.Markdown("### 详情 / 编辑")
            audio_player = gr.Audio(label="试听", interactive=False)

            with gr.Row():
                fid_box = gr.Textbox(label="ID", interactive=False, scale=1)
                filename_box = gr.Textbox(label="文件名", interactive=False, scale=2)

            prompt_box = gr.Textbox(label="Prompt / 风格 tags", lines=2)
            lyrics_box = gr.Textbox(label="歌词", lines=6)

            with gr.Row():
                seed_box = gr.Number(label="Seed", precision=0)
                lora_box = gr.Textbox(label="使用的 LoRA")

            with gr.Row():
                rating_box = gr.Slider(label="评分", minimum=0, maximum=5, step=1, value=0)
                fav_box = gr.Checkbox(label="收藏")

            tags_box = gr.Textbox(label="标签 (逗号分隔)", placeholder="如: 副歌好听, 失败案例, 给生日礼物用")
            notes_box = gr.Textbox(label="备注", lines=2)

            with gr.Row():
                save_btn = gr.Button("💾 保存", variant="primary")
                delete_btn = gr.Button("🗑 删除", variant="stop")
                delete_file_chk = gr.Checkbox(label="同时删文件")

            action_status = gr.Textbox(label="操作结果", interactive=False)

    # ─────────────── 事件 ───────────────
    refresh_btn.click(do_refresh, [search_box, fav_filter, rating_filter], [status, table])
    search_box.submit(do_search, [search_box, fav_filter, rating_filter], [status, table])
    fav_filter.change(do_search, [search_box, fav_filter, rating_filter], [status, table])
    rating_filter.change(do_search, [search_box, fav_filter, rating_filter], [status, table])

    table.select(
        do_select,
        [table],
        [audio_player, fid_box, filename_box, prompt_box, lyrics_box,
         seed_box, lora_box, rating_box, tags_box, fav_box, notes_box],
    )

    save_btn.click(
        do_save,
        [fid_box, prompt_box, lyrics_box, seed_box, lora_box,
         rating_box, tags_box, fav_box, notes_box],
        [action_status],
    )

    delete_btn.click(
        do_delete,
        [fid_box, delete_file_chk],
        [action_status, audio_player, fid_box],
    )

    # 启动时自动扫描
    app.load(do_refresh, [search_box, fav_filter, rating_filter], [status, table])


if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7861, inbrowser=False)
