"""一键 LoRA 数据集打包 (v0.5.6)

拖一堆音频 → 选模式 → 自动:
  1. (可选) Demucs 拆 vocals stem,只留人声(训音色 / 翻唱用)
  2. 复制到 datasets/<项目>/raw/
  3. 跑 training_data.prepare_dataset() 出 metadata.csv

输出: datasets/<项目>/
  ├── raw/                  ← 处理后的训练源文件(vocals 或原混合)
  ├── audio/                ← 重采样统一格式后的训练音频 (prepare_dataset 写)
  ├── metadata.csv          ← caption / BPM / key / 路径
  └── _tmp_stems/           ← Demucs 临时(处理完自动删)
"""
import shutil
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DATASETS_DIR = ROOT / "datasets"


def quick_import(
    audio_paths: list,
    dataset_name: str,
    *,
    mode: str = "vocal_only",  # 'vocal_only' | 'full_mix'
    target_sr: int = 44100,
    target_channels: int = 2,
    progress_callback=None,
    cleanup_stems: bool = True,
) -> dict:
    """一键打包. 上传 N 个音频 → 自动建/扩展 datasets/<name>/.

    audio_paths: gr.File(file_count="multiple") 返的路径列表 (字符串或 Path 都行)
    dataset_name: datasets/ 下的项目名 (没有就建,已存在就追加)
    mode:
      'vocal_only': 先 Demucs 拆 6-stem, 只留 vocals.wav (训人声音色推荐)
      'full_mix':   直接用原混合 (训整曲风格用)
    target_sr / target_channels: prepare_dataset 重采样目标
    cleanup_stems: True 处理完删 _tmp_stems/ 省磁盘 (默认开)

    返回:
      {ok, dataset_dir, raw_dir, imported, total, mode_used, errors,
       prepare_result: {total, succeeded, ...}}
    """
    if not audio_paths:
        return {"ok": False, "errors": ["没传文件"], "imported": 0, "total": 0}

    name = (dataset_name or "").strip()
    if not name:
        return {"ok": False, "errors": ["数据集名不能为空"], "imported": 0, "total": 0}

    # 防恶意路径
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    if safe != name:
        name = safe

    dataset_dir = DATASETS_DIR / name
    raw_dir = dataset_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    tmp_stems_root = dataset_dir / "_tmp_stems"

    paths = [Path(p) for p in audio_paths if p]
    n_total = len(paths)
    n_done = 0
    errors = []

    # 检查 mode 依赖
    if mode == "vocal_only":
        try:
            from lib import stem_separation
            if not stem_separation.check_demucs():
                return {
                    "ok": False,
                    "errors": ["Demucs 未装。pip install demucs (~几百 MB),"
                               "或者改 mode='full_mix' 跳过拆轨"],
                    "imported": 0, "total": n_total,
                }
        except ImportError as e:
            return {"ok": False, "errors": [f"stem_separation 模块缺: {e}"],
                    "imported": 0, "total": n_total}

    def cb(i, total, msg):
        if progress_callback:
            progress_callback(i, total, msg)

    # 逐文件处理
    for i, src in enumerate(paths, start=1):
        if not src.exists():
            errors.append(f"丢失: {src}")
            continue

        cb(i, n_total + 1, f"[{i}/{n_total}] {src.name}")

        if mode == "vocal_only":
            stem_out = tmp_stems_root / src.stem
            sep = stem_separation.separate_song(src, stem_out)
            if not sep["ok"]:
                errors.append(f"{src.name} Demucs 失败: {sep['error']}")
                continue
            vocals = sep["stems"].get("vocals")
            if not vocals or not Path(vocals).exists():
                errors.append(f"{src.name} 没找到 vocals stem")
                continue
            # 拷贝 vocals 到 raw 目录,带个后缀防混淆
            dst = raw_dir / f"{src.stem}_vocals.wav"
            try:
                shutil.copy2(vocals, dst)
                n_done += 1
            except Exception as e:
                errors.append(f"{src.name} 拷贝 vocals 失败: {e}")
        else:
            # full_mix: 直接拷原文件
            dst = raw_dir / src.name
            try:
                shutil.copy2(src, dst)
                n_done += 1
            except Exception as e:
                errors.append(f"{src.name} 拷贝失败: {e}")

    # 清 _tmp_stems
    if cleanup_stems and tmp_stems_root.exists():
        try:
            shutil.rmtree(tmp_stems_root, ignore_errors=True)
        except Exception:
            pass

    # 没一个成功就提前返
    if n_done == 0:
        return {
            "ok": False,
            "dataset_dir": dataset_dir,
            "raw_dir": raw_dir,
            "imported": 0,
            "total": n_total,
            "mode_used": mode,
            "errors": errors or ["全部失败"],
            "prepare_result": None,
        }

    # 自动调 prepare_dataset 分析 + 出 metadata.csv
    cb(n_total + 1, n_total + 1, "分析 BPM/key/caption 并写 metadata.csv...")
    try:
        from lib import training_data
        prep = training_data.prepare_dataset(
            raw_dir, dataset_dir,
            target_sr=target_sr,
            target_channels=target_channels,
            mode_hint=mode,
        )
    except Exception as e:
        return {
            "ok": False,
            "dataset_dir": dataset_dir,
            "raw_dir": raw_dir,
            "imported": n_done,
            "total": n_total,
            "mode_used": mode,
            "errors": errors + [f"prepare_dataset 异常: {e}"],
            "prepare_result": None,
        }

    return {
        "ok": True,
        "dataset_dir": dataset_dir,
        "raw_dir": raw_dir,
        "imported": n_done,
        "total": n_total,
        "mode_used": mode,
        "errors": errors,
        "prepare_result": prep,
    }
