"""批量生成 (功能 #6)

从 CSV / JSONL 读 N 行 prompt,挂机跑,每首歌写到 outputs/batch-<run-id>/。

CSV 格式 (UTF-8,首行表头,| 或 , 分隔):
    prompt | lyrics | duration | seed | lora | infer_step | guidance_scale | filename

最少只需要 prompt 列。其它列可缺,缺则用 task 默认值。
filename 列可指定输出文件名(不含扩展名),不填则用 row-<n>.wav。

API:
- parse_csv(path) -> list[dict]   把 CSV 解析成任务字典列表
- run_batch(tasks, ...) 主驱动循环,可传 progress_callback 报告 (i, total, msg)
"""
import csv
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
BATCH_OUT_ROOT = ROOT / "outputs" / "batches"

VALID_KEYS = {
    "prompt", "lyrics", "duration", "seed", "lora",
    "infer_step", "guidance_scale", "filename",
}


# ───────────────────────────────────────────────
# CSV 解析
# ───────────────────────────────────────────────

def _sniff_dialect(sample: str):
    try:
        return csv.Sniffer().sniff(sample, delimiters=",|\t;")
    except csv.Error:
        # 自动猜不出来,用 |
        class D(csv.Dialect):
            delimiter = "|"
            quotechar = '"'
            escapechar = None
            doublequote = True
            skipinitialspace = True
            lineterminator = "\n"
            quoting = csv.QUOTE_MINIMAL
        return D()


def parse_csv(path: Path) -> list[dict]:
    """返回 [{prompt, lyrics, duration, seed, lora, infer_step, guidance_scale, filename}, ...]
    类型转换: duration/guidance_scale=float, seed/infer_step=int(或 None)
    """
    raw = Path(path).read_text(encoding="utf-8")
    if not raw.strip():
        return []
    sample = "\n".join(raw.splitlines()[:5])
    dialect = _sniff_dialect(sample)

    reader = csv.DictReader(raw.splitlines(), dialect=dialect)
    tasks = []
    for i, row in enumerate(reader, start=1):
        # 清理表头(去掉空格),只保留已知 key
        clean = {}
        for k, v in row.items():
            if k is None:
                continue
            k = k.strip().lower()
            if k in VALID_KEYS and v is not None:
                clean[k] = v.strip()

        prompt = clean.get("prompt", "")
        if not prompt:
            continue  # 跳过空 prompt 行

        task = {
            "row": i,
            "prompt": prompt,
            "lyrics": clean.get("lyrics", ""),
            "duration": _to_float(clean.get("duration"), 60.0),
            "seed": _to_int(clean.get("seed"), None),
            "lora": clean.get("lora", ""),
            "infer_step": _to_int(clean.get("infer_step"), 60),
            "guidance_scale": _to_float(clean.get("guidance_scale"), 15.0),
            "filename": clean.get("filename", ""),
        }
        tasks.append(task)
    return tasks


def _to_int(v, default):
    if v is None or v == "":
        return default
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _to_float(v, default):
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ───────────────────────────────────────────────
# 跑批
# ───────────────────────────────────────────────

def run_batch(
    tasks: list[dict],
    *,
    run_name: str = "",
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    stop_flag: Optional[Callable[[], bool]] = None,
    dry_run: bool = False,
) -> dict:
    """执行批量任务。

    参数:
        run_name: 子目录名 (留空则用时间戳)
        progress_callback(i, total, msg): UI 报告进度
        stop_flag(): 返 True 提前停止 (UI 停止按钮用)
        dry_run: True 时不真生成,只打 log (UI 预览用)

    返回 report: {run_dir, total, ok, failed, results: [{row, status, output, error}]}
    """
    run_name = run_name.strip() or time.strftime("run-%Y%m%d-%H%M%S")
    run_dir = BATCH_OUT_ROOT / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    total = len(tasks)
    results = []
    ok = failed = 0

    for i, t in enumerate(tasks, start=1):
        if stop_flag and stop_flag():
            results.append({"row": t["row"], "status": "stopped", "output": None, "error": None})
            break

        # 决定文件名
        stem = t["filename"] or f"row-{t['row']:03d}"
        if not stem.endswith(".wav"):
            stem_path = run_dir / f"{stem}.wav"
        else:
            stem_path = run_dir / stem

        if progress_callback:
            progress_callback(i, total, f"row {t['row']}: {t['prompt'][:50]}…")

        if dry_run:
            results.append({
                "row": t["row"],
                "status": "dry-run",
                "output": str(stem_path),
                "error": None,
            })
            ok += 1
            continue

        try:
            from lib import ace_step_api
            ace_step_api.generate(
                prompt=t["prompt"],
                lyrics=t["lyrics"],
                audio_duration=t["duration"],
                output_path=stem_path,
                seed=t["seed"],
                infer_step=t["infer_step"],
                guidance_scale=t["guidance_scale"],
                lora_name_or_path=t["lora"] or None,
            )
            results.append({
                "row": t["row"],
                "status": "ok",
                "output": str(stem_path),
                "error": None,
            })
            ok += 1
        except Exception as e:
            tb = traceback.format_exc()
            results.append({
                "row": t["row"],
                "status": "failed",
                "output": None,
                "error": f"{e}\n{tb}",
            })
            failed += 1

    # 写 report.txt
    report_path = run_dir / "report.txt"
    lines = [
        f"批量任务 {run_name}",
        f"完成 {ok}/{total}, 失败 {failed}",
        "",
    ]
    for r in results:
        lines.append(f"row={r['row']:>3}  {r['status']:<8}  {r.get('output') or ''}")
        if r.get("error"):
            lines.append(f"    错误: {r['error'].splitlines()[0]}")
    report_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "run_dir": run_dir,
        "total": total,
        "ok": ok,
        "failed": failed,
        "results": results,
        "report_path": report_path,
    }


# ───────────────────────────────────────────────
# 模板生成 (UI 用)
# ───────────────────────────────────────────────

def make_template_csv() -> str:
    """返回示例 CSV 字符串,用户可参照填。"""
    return (
        "prompt | lyrics | duration | seed | lora | infer_step | guidance_scale | filename\n"
        "indie folk, female vocal, acoustic guitar, 90 bpm |  | 60 | 42 |  | 60 | 15 | folk-test-01\n"
        "synthwave, instrumental, 80s, 120 bpm |  | 45 | 1337 |  | 60 | 15 | synth-test-01\n"
        "lofi hip hop, instrumental, mellow, 75 bpm |  | 30 | 9999 |  | 50 | 12 | lofi-test-01\n"
    )
