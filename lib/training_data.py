"""LoRA 训练数据准备

把一堆参考音频(MP3/WAV)分析 BPM/key,生成 caption 建议,
重采样到统一格式,导出成 ACE-Step 可用的数据集目录。
"""
import csv
import shutil
import subprocess
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DATASETS_DIR = ROOT / "datasets"

AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}

# 主流 12 大调 + 12 小调
KEY_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _check_librosa() -> bool:
    try:
        import librosa  # noqa
        return True
    except ImportError:
        return False


def analyze_audio(path: Path) -> dict:
    """提取 BPM、key、duration、sample_rate。失败时尽量返回部分结果。"""
    info: dict = {
        "filename": path.name,
        "duration": None,
        "sample_rate": None,
        "bpm": None,
        "key": None,
        "error": None,
    }

    if not _check_librosa():
        info["error"] = "librosa 未安装,跑 pip install librosa"
        return info

    try:
        import librosa
        import numpy as np

        # 用较低 sr 加速分析(对 BPM/key 检测足够)
        y, sr = librosa.load(str(path), sr=22050, mono=True)
        info["sample_rate"] = int(sr)
        info["duration"] = float(len(y) / sr)

        # BPM
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        # tempo 可能是 ndarray 或 float
        tempo_val = float(tempo.item() if hasattr(tempo, "item") else tempo)
        info["bpm"] = int(round(tempo_val))

        # Key (chroma 取最强 pitch class)
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        chroma_mean = np.mean(chroma, axis=1)
        key_idx = int(np.argmax(chroma_mean))
        info["key"] = KEY_NAMES[key_idx]

    except Exception as e:
        info["error"] = str(e)

    return info


# 文件名 → 风格关键词(尽量帮你猜个初始 tag,你再手改)
STYLE_KEYWORDS = {
    "folk": "indie folk",
    "rock": "rock",
    "pop": "pop",
    "jazz": "jazz",
    "edm": "edm",
    "lofi": "lofi hip hop",
    "hiphop": "hip hop",
    "trap": "trap",
    "ballad": "ballad",
    "ambient": "ambient",
    "synth": "synthwave",
    "country": "country",
    "rnb": "r&b",
    "soul": "soul",
    "funk": "funk",
    "punk": "punk rock",
    "metal": "metal",
    "classical": "classical",
    "电子": "electronic",
    "民谣": "indie folk, chinese",
    "摇滚": "rock, chinese",
}


def suggest_caption(info: dict, source_filename: str = "",
                    mode_hint: Optional[str] = None) -> str:
    """从文件名 + 分析结果生成起始 caption。

    起始 caption 会包含一个 `[...]` 占位符提醒用户填补流派/乐器/情绪
    (这些纯靠音频自动分析不可靠,得人来标)。

    mode_hint: 'vocal_only' / 'full_mix' / None。vocal_only 模式会在
    caption 前加 "solo vocal" 提示这是人声音色训练用。
    """
    parts = []

    # 1. 人声训练提示
    if mode_hint == "vocal_only":
        parts.append("solo vocal")

    # 2. 从文件名识别风格关键词
    name_lower = (source_filename or info.get("filename", "")).lower()
    matched_style = None
    for kw, tag in STYLE_KEYWORDS.items():
        if kw in name_lower:
            matched_style = tag
            break
    if matched_style:
        parts.append(matched_style)

    # 3. 速度档位 + 精确 BPM
    bpm = info.get("bpm")
    if bpm:
        if bpm < 70:
            parts.append("slow")
        elif bpm < 100:
            parts.append("mid-tempo")
        elif bpm < 130:
            parts.append("upbeat")
        else:
            parts.append("fast")
        parts.append(f"{int(bpm)} bpm")

    # 4. 调
    if info.get("key"):
        parts.append(f"key of {info['key']}")

    # 5. 占位符提醒用户填
    parts.append("[填: 流派/乐器/情绪/语言]")

    return ", ".join(parts)


def prepare_dataset(
    source_dir: Path,
    output_dir: Path,
    target_sr: int = 44100,
    target_format: str = "wav",
    target_channels: int = 2,
    mode_hint: Optional[str] = None,
) -> dict:
    """准备 LoRA 训练数据集。

    流程:
    1. 扫描 source_dir 里的音频
    2. 重采样 + 转格式输出到 output_dir/audio/
    3. 用 librosa 分析每首的 BPM/key
    4. 生成 caption 建议(含 placeholder)
    5. 写 metadata.csv

    mode_hint: 'vocal_only' / 'full_mix' (透传给 suggest_caption,
    vocal_only 时 caption 前加 'solo vocal')
    """
    if not shutil.which("ffmpeg"):
        return {"error": "ffmpeg 未安装"}

    source_dir = Path(source_dir)
    output_dir = Path(output_dir)

    if not source_dir.is_dir():
        return {"error": f"源目录不存在: {source_dir}"}

    audio_out = output_dir / "audio"
    audio_out.mkdir(parents=True, exist_ok=True)

    report = {
        "source": str(source_dir),
        "output": str(output_dir),
        "total": 0,
        "succeeded": 0,
        "errors": [],
        "tracks": [],
    }

    for src in sorted(source_dir.iterdir()):
        if not src.is_file() or src.suffix.lower() not in AUDIO_EXTS:
            continue
        report["total"] += 1

        # 安全的输出文件名(去掉空格 / 特殊字符)
        safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in src.stem)
        dst = audio_out / f"{safe_stem}.{target_format}"

        # 重采样转格式
        try:
            cmd = [
                "ffmpeg", "-i", str(src),
                "-ar", str(target_sr),
                "-ac", str(target_channels),
                "-y", str(dst),
            ]
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            report["errors"].append(f"{src.name}: ffmpeg 失败")
            continue
        except Exception as e:
            report["errors"].append(f"{src.name}: {e}")
            continue

        # 分析
        info = analyze_audio(dst)
        info["source_filename"] = src.name
        info["dataset_filename"] = dst.name
        info["suggested_caption"] = suggest_caption(info, src.name, mode_hint=mode_hint)
        info["caption"] = info["suggested_caption"]  # 默认用建议,UI 里可改

        report["tracks"].append(info)
        report["succeeded"] += 1

    # 写 metadata.csv (ACE-Step LoRA 训练用)
    csv_path = output_dir / "metadata.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "caption", "bpm", "key", "duration"])
        for t in report["tracks"]:
            writer.writerow([
                t["dataset_filename"],
                t.get("caption", ""),
                t.get("bpm", ""),
                t.get("key", ""),
                f"{t['duration']:.1f}" if t.get("duration") else "",
            ])
    report["csv_path"] = str(csv_path)

    return report


def update_captions(metadata_csv: Path, captions: dict[str, str]) -> int:
    """在 prepare_dataset 之后,允许 UI 批量改 caption 然后回写 CSV。

    captions: {filename: new_caption}
    返回更新行数。
    """
    rows = []
    with metadata_csv.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            rows.append(row)

    fname_idx = header.index("filename")
    caption_idx = header.index("caption")

    updated = 0
    for row in rows:
        fname = row[fname_idx]
        if fname in captions:
            row[caption_idx] = captions[fname]
            updated += 1

    with metadata_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    return updated
