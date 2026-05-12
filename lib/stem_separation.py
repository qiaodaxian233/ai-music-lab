"""6-stem 分离, 基于 Demucs htdemucs_6s 模型.

模型大小约 5GB, 首次运行会自动下载. 12GB VRAM 够用.
输出 6 个 stem: drums, bass, other, vocals, guitar, piano.
"""
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

STEM_NAMES_6S = ["drums", "bass", "other", "vocals", "guitar", "piano"]


def check_demucs() -> bool:
    try:
        import demucs  # noqa: F401
        return True
    except ImportError:
        return False


def separate_song(
    input_path: Path,
    output_dir: Path,
    model: str = "htdemucs_6s",
    use_gpu: Optional[bool] = None,
) -> dict:
    """把一首歌分成 6 个 stem.

    返回 dict:
        ok: bool
        error: str | None
        stems: {stem_name: Path}
        stems_dir: Path
    """
    if not check_demucs():
        return {
            "ok": False,
            "error": "demucs 未装。运行: pip install demucs",
            "stems": {},
        }

    input_path = Path(input_path).resolve()
    output_dir = Path(output_dir).resolve()

    if not input_path.exists():
        return {"ok": False, "error": f"找不到文件: {input_path}", "stems": {}}

    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "demucs.separate",
        "-n", model,
        "-o", str(output_dir),
        str(input_path),
    ]

    if use_gpu is False:
        cmd.extend(["--device", "cpu"])

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        return {
            "ok": False,
            "error": f"Demucs 失败: {(e.stderr or '')[:500]}",
            "stems": {},
        }

    # Demucs 默认输出到 output_dir/<model>/<song_name>/*.wav
    song_name = input_path.stem
    stems_dir = output_dir / model / song_name

    if not stems_dir.exists():
        # 有时 Demucs 用不同的输出路径,扫一下
        for candidate in output_dir.rglob(f"{song_name}"):
            if candidate.is_dir():
                stems_dir = candidate
                break

    if not stems_dir.exists():
        return {
            "ok": False,
            "error": f"找不到 stems 输出目录,期望: {stems_dir}",
            "stems": {},
        }

    stems = {}
    for stem_name in STEM_NAMES_6S:
        stem_path = stems_dir / f"{stem_name}.wav"
        if stem_path.exists():
            stems[stem_name] = stem_path

    if not stems:
        return {
            "ok": False,
            "error": f"在 {stems_dir} 找不到 stem 文件",
            "stems": {},
        }

    return {
        "ok": True,
        "error": None,
        "stems": stems,
        "stems_dir": stems_dir,
        "model": model,
    }
