"""AI Music Lab — 总控台 (v0.5.3)

端口 7862,管理 3 个常驻服务的启停 + 系统状态 + 日志查看。

跟统一控制台(7861)的区别:
- 7861 统一控制台 = 12 个 Tab 的功能集合(生成/管理/导出)
- 7862 本总控台   = 启停/监控 7861 + 7860(ACE-Step)+ watcher 三个进程

启动:
- Windows: 双击 start-manager.bat
- Linux/Mac: python scripts/lab-manager.py
"""
import sys
import time
from pathlib import Path

import gradio as gr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib import process_manager as pm

REFRESH_SEC = 3   # 状态自动刷新间隔


# ───────────────────────────────────────────────
# UI 辅助函数
# ───────────────────────────────────────────────

def _fmt_status(st: dict) -> str:
    """单服务一行状态文字"""
    pid_s = f"PID {st['pid']}" if st["pid"] else "—"
    port_s = (f":{st['port']} {'通' if st['port_listening'] else '不通'}"
              if st["port"] else "无端口")
    when = ""
    if st["started_at"]:
        secs = time.time() - st["started_at"]
        if secs < 60:
            when = f"  · {int(secs)}s 前启动"
        elif secs < 3600:
            when = f"  · {int(secs/60)}m 前启动"
        else:
            when = f"  · {int(secs/3600)}h 前启动"
    return f"{st['summary']}  ·  {pid_s}  ·  {port_s}{when}"


def _fmt_system(info: dict) -> str:
    lines = []
    # GPU
    g = info.get("gpu")
    if g:
        bar = _bar(g["used_mb"], g["total_mb"], 30)
        lines.append(
            f"GPU  {g['name']}\n"
            f"     {bar}  {g['used_mb']:>5}/{g['total_mb']:>5} MB  "
            f"util {g['util_pct']:>2}%"
        )
    else:
        lines.append("GPU  不可用 (nvidia-smi 没装/CPU only)")

    # 磁盘
    if "disk_free_gb" in info:
        free_pct = info['disk_free_gb'] / info['disk_total_gb'] * 100
        lines.append(f"磁盘 总 {info['disk_total_gb']} GB · 空 {info['disk_free_gb']} GB ({free_pct:.0f}%)")

    # 项目数据
    lines.append(
        f"项目 outputs/ {info['outputs_size_gb']} GB · "
        f"datasets/ {info['datasets_size_gb']} GB · "
        f"LoRA {info['loras_count']} 个"
    )

    # 元信息
    ace_status = "✓ 已装" if info["ace_step_installed"] else "❌ 未装 (跑 setup.sh)"
    lines.append(f"系统 Python {info['python']} · {info['platform']} · ACE-Step {ace_status}")

    return "\n".join(lines)


def _bar(used, total, width=20) -> str:
    if total <= 0:
        return "─" * width
    pct = min(1.0, used / total)
    filled = int(pct * width)
    return "█" * filled + "░" * (width - filled)


def _fmt_recent(items: list) -> list:
    """转 Gradio Dataframe 格式: [['路径', '大小', '何时'], ...]"""
    rows = []
    now = time.time()
    for f in items:
        ago = now - f["mtime"]
        if ago < 60:
            when = f"{int(ago)}s ago"
        elif ago < 3600:
            when = f"{int(ago/60)}m ago"
        elif ago < 86400:
            when = f"{int(ago/3600)}h ago"
        else:
            when = f"{int(ago/86400)}d ago"
        rows.append([f["path"], f"{f['size_mb']} MB", when])
    return rows


# ───────────────────────────────────────────────
# 动作回调
# ───────────────────────────────────────────────

def refresh_all():
    states = [pm.status(s) for s in pm.DEFAULT_SERVICES]
    info = pm.system_info()
    recent = pm.recent_outputs(15)
    return (
        _fmt_status(states[0]),
        _fmt_status(states[1]),
        _fmt_status(states[2]),
        _fmt_system(info),
        _fmt_recent(recent),
    )


def act_start(key):
    svc = pm.get_service(key)
    if not svc:
        return f"❌ 未知服务: {key}"
    r = pm.start_service(svc)
    if r["ok"]:
        return f"✓ 已启动 PID {r['pid']}, 等待端口就绪 (1~3 分钟首次冷启动)..."
    return f"⚠ {r['error']}"


def act_stop(key):
    svc = pm.get_service(key)
    if not svc:
        return f"❌ 未知服务: {key}"
    r = pm.stop_service(svc)
    if r["ok"]:
        return "✓ 已停" if r["was_running"] else "ℹ 本来就没在跑"
    return f"❌ 停止失败: {r['error']}"


def act_restart(key):
    svc = pm.get_service(key)
    if not svc:
        return "❌ 未知服务"
    pm.stop_service(svc)
    time.sleep(1)
    r = pm.start_service(svc)
    return f"✓ 重启 PID {r['pid']}" if r["ok"] else f"⚠ {r['error']}"


def act_log(key):
    svc = pm.get_service(key)
    if not svc:
        return "❌ 未知服务"
    return pm.read_log_tail(svc, n=200)


def act_clear_log(key):
    svc = pm.get_service(key)
    if not svc:
        return "❌"
    return "✓ 已清空" if pm.clear_log(svc) else "⚠ 失败"


# ───────────────────────────────────────────────
# UI
# ───────────────────────────────────────────────

with gr.Blocks(title="AI Music Lab — 总控台 :7862", theme=gr.themes.Soft()) as app:
    gr.Markdown("""
# 🎛 AI Music Lab — 总控台

启停 / 监控 3 个常驻服务,看 GPU/磁盘状态,看最近输出。**生成新歌去 ACE-Step UI,功能去统一控制台。**
""")

    # ─── 服务控制 ───
    gr.Markdown("## 🚦 服务控制")

    with gr.Row():
        # ACE-Step
        with gr.Column():
            gr.Markdown("### 🎹 ACE-Step 主 UI")
            ace_status = gr.Textbox(label="状态", interactive=False, lines=1)
            with gr.Row():
                ace_start = gr.Button("▶ 启动", variant="primary", size="sm")
                ace_stop = gr.Button("■ 停止", variant="stop", size="sm")
                ace_restart = gr.Button("🔄 重启", size="sm")
            ace_open = gr.HTML(
                '<a href="http://127.0.0.1:7860" target="_blank" '
                'style="display:inline-block;padding:6px 14px;background:#3b82f6;'
                'color:white;border-radius:6px;text-decoration:none;font-size:14px;">'
                '🌐 打开 :7860</a>'
            )
            ace_action_msg = gr.Textbox(label="动作", interactive=False, lines=1)

        # 统一控制台
        with gr.Column():
            gr.Markdown("### 🎛 统一控制台 (12 Tab)")
            uni_status = gr.Textbox(label="状态", interactive=False, lines=1)
            with gr.Row():
                uni_start = gr.Button("▶ 启动", variant="primary", size="sm")
                uni_stop = gr.Button("■ 停止", variant="stop", size="sm")
                uni_restart = gr.Button("🔄 重启", size="sm")
            uni_open = gr.HTML(
                '<a href="http://127.0.0.1:7861" target="_blank" '
                'style="display:inline-block;padding:6px 14px;background:#3b82f6;'
                'color:white;border-radius:6px;text-decoration:none;font-size:14px;">'
                '🌐 打开 :7861</a>'
            )
            uni_action_msg = gr.Textbox(label="动作", interactive=False, lines=1)

        # Watcher
        with gr.Column():
            gr.Markdown("### 🔄 后处理 watcher")
            wat_status = gr.Textbox(label="状态", interactive=False, lines=1)
            with gr.Row():
                wat_start = gr.Button("▶ 启动", variant="primary", size="sm")
                wat_stop = gr.Button("■ 停止", variant="stop", size="sm")
                wat_restart = gr.Button("🔄 重启", size="sm")
            gr.Markdown("无 Web UI (后台进程)", elem_id="watcher_no_ui")
            wat_action_msg = gr.Textbox(label="动作", interactive=False, lines=1)

    # ─── 系统状态 ───
    gr.Markdown("## 📊 系统状态")
    sys_info = gr.Textbox(label="", interactive=False, lines=5,
                          show_label=False, max_lines=8)

    # ─── 最近输出 ───
    gr.Markdown("## 📂 最近输出 (outputs/)")
    recent_table = gr.Dataframe(
        headers=["路径", "大小", "何时"],
        datatype=["str", "str", "str"],
        interactive=False,
        row_count=(10, "fixed"),
        col_count=(3, "fixed"),
        wrap=True,
    )

    # ─── 日志 ───
    gr.Markdown("## 📜 日志")
    with gr.Row():
        log_pick = gr.Radio(
            choices=[("ACE-Step", "acestep"), ("统一控制台", "unified"),
                     ("watcher", "watcher")],
            value="acestep",
            label="看哪个服务的日志",
        )
        log_refresh = gr.Button("🔄 刷新日志", size="sm")
        log_clear = gr.Button("🗑 清空日志", size="sm", variant="stop")
    log_box = gr.Textbox(label="最近 200 行", lines=15, max_lines=30,
                         interactive=False)

    # ─── 刷新区 ───
    gr.Markdown("---")
    with gr.Row():
        refresh_btn = gr.Button("🔄 立刻刷新全部状态", variant="primary", scale=2)
        auto_refresh = gr.Checkbox(label=f"自动刷新 ({REFRESH_SEC}s)", value=True, scale=1)

    # ─── 事件绑定 ───
    outputs_for_refresh = [ace_status, uni_status, wat_status, sys_info, recent_table]

    refresh_btn.click(refresh_all, outputs=outputs_for_refresh)
    app.load(refresh_all, outputs=outputs_for_refresh)

    # 服务动作 - 启停后立刻拉一次状态
    def _start_and_refresh(key):
        msg = act_start(key)
        return msg, *refresh_all()

    def _stop_and_refresh(key):
        msg = act_stop(key)
        return msg, *refresh_all()

    def _restart_and_refresh(key):
        msg = act_restart(key)
        return msg, *refresh_all()

    ace_start.click(lambda: _start_and_refresh("acestep"),
                    outputs=[ace_action_msg] + outputs_for_refresh)
    ace_stop.click(lambda: _stop_and_refresh("acestep"),
                   outputs=[ace_action_msg] + outputs_for_refresh)
    ace_restart.click(lambda: _restart_and_refresh("acestep"),
                      outputs=[ace_action_msg] + outputs_for_refresh)

    uni_start.click(lambda: _start_and_refresh("unified"),
                    outputs=[uni_action_msg] + outputs_for_refresh)
    uni_stop.click(lambda: _stop_and_refresh("unified"),
                   outputs=[uni_action_msg] + outputs_for_refresh)
    uni_restart.click(lambda: _restart_and_refresh("unified"),
                      outputs=[uni_action_msg] + outputs_for_refresh)

    wat_start.click(lambda: _start_and_refresh("watcher"),
                    outputs=[wat_action_msg] + outputs_for_refresh)
    wat_stop.click(lambda: _stop_and_refresh("watcher"),
                   outputs=[wat_action_msg] + outputs_for_refresh)
    wat_restart.click(lambda: _restart_and_refresh("watcher"),
                      outputs=[wat_action_msg] + outputs_for_refresh)

    log_refresh.click(act_log, [log_pick], [log_box])
    log_clear.click(act_clear_log, [log_pick], [log_box])
    log_pick.change(act_log, [log_pick], [log_box])

    # ─── 自动刷新 (用 gr.Timer, Gradio 4.x 支持) ───
    try:
        timer = gr.Timer(REFRESH_SEC, active=True)

        def _maybe_refresh(enabled):
            if enabled:
                return refresh_all()
            return (gr.update(), gr.update(), gr.update(), gr.update(), gr.update())

        timer.tick(_maybe_refresh, [auto_refresh], outputs_for_refresh)
    except (AttributeError, TypeError):
        # 老 Gradio 没 Timer, 退化到手动刷新
        gr.Markdown("⚠ 当前 Gradio 版本无 Timer 自动刷新,点🔄按钮手动刷")


if __name__ == "__main__":
    print("=" * 60)
    print("  🎛 AI Music Lab — 总控台")
    print("=" * 60)
    print("  端口:        7862")
    print("  访问:        http://127.0.0.1:7862")
    print("  跟它一起开的:")
    print("    7860       ACE-Step 主 UI (生成新歌)")
    print("    7861       统一控制台 (12 Tab 功能)")
    print("  本管理器只负责启停 + 监控这两个 + watcher")
    print("=" * 60)
    app.launch(server_name="127.0.0.1", server_port=7862,
               inbrowser=True, show_api=False, quiet=False)
