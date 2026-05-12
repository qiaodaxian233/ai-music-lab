"""后处理: 响度归一化、ID3 tag、格式转换"""
import shutil
import subprocess
from pathlib import Path
from typing import Optional


def _ffmpeg_or_die():
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg 未安装。Ubuntu: sudo apt install ffmpeg")


def normalize_loudness(
    input_path: Path,
    output_path: Optional[Path] = None,
    target_lufs: float = -14.0,
    true_peak: float = -1.5,
    lra: float = 11.0,
) -> Path:
    """响度归一化到目标 LUFS。默认 -14 LUFS = Spotify/YouTube 标准。"""
    _ffmpeg_or_die()
    if output_path is None:
        output_path = input_path.with_stem(input_path.stem + "_normalized")

    cmd = [
        "ffmpeg", "-i", str(input_path),
        "-af", f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}",
        "-y", str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path


def tag_audio(
    path: Path,
    title: str = "",
    artist: str = "AI",
    album: str = "ai-music-lab",
    comment: str = "",
    genre: str = "",
) -> bool:
    """写元数据(MP3 走 ID3,FLAC/OGG 走 Vorbis,WAV 写不了元数据建议先转 MP3)。"""
    try:
        from mutagen import File as MutagenFile
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import ID3NoHeaderError
    except ImportError:
        print("⚠ mutagen 未安装,跳过 tag")
        return False

    ext = path.suffix.lower()
    if ext == ".wav":
        # WAV 不支持标准 tag,建议先 wav_to_mp3
        return False

    try:
        if ext == ".mp3":
            try:
                tags = EasyID3(str(path))
            except ID3NoHeaderError:
                from mutagen.id3 import ID3
                tags = ID3()
                tags.save(str(path))
                tags = EasyID3(str(path))
            if title:   tags["title"] = title
            if artist:  tags["artist"] = artist
            if album:   tags["album"] = album
            if genre:   tags["genre"] = genre
            tags.save(str(path))
            # COMM 单独走 ID3
            if comment:
                from mutagen.id3 import ID3, COMM
                full = ID3(str(path))
                full["COMM"] = COMM(encoding=3, lang="eng", desc="", text=comment)
                full.save(str(path))
            return True
        else:
            f = MutagenFile(str(path), easy=True)
            if f is None:
                return False
            if title:   f["title"] = title
            if artist:  f["artist"] = artist
            if album:   f["album"] = album
            if genre:   f["genre"] = genre
            if comment: f["comment"] = comment
            f.save()
            return True
    except Exception as e:
        print(f"⚠ Tag 写入失败 {path.name}: {e}")
        return False


def wav_to_mp3(
    wav_path: Path,
    mp3_path: Optional[Path] = None,
    bitrate: str = "320k",
) -> Path:
    """转 MP3。"""
    _ffmpeg_or_die()
    if mp3_path is None:
        mp3_path = wav_path.with_suffix(".mp3")
    cmd = [
        "ffmpeg", "-i", str(wav_path),
        "-codec:a", "libmp3lame", "-b:a", bitrate,
        "-y", str(mp3_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return mp3_path


def fade_in_out(
    input_path: Path,
    output_path: Optional[Path] = None,
    fade_in_sec: float = 0.5,
    fade_out_sec: float = 2.0,
) -> Path:
    """加淡入淡出(避免开头/结尾突兀)。"""
    _ffmpeg_or_die()
    if output_path is None:
        output_path = input_path.with_stem(input_path.stem + "_faded")
    # 获取时长
    duration = _get_duration(input_path)
    if duration is None:
        raise RuntimeError(f"无法获取时长: {input_path}")
    fade_out_start = max(0, duration - fade_out_sec)
    cmd = [
        "ffmpeg", "-i", str(input_path),
        "-af", f"afade=t=in:d={fade_in_sec},afade=t=out:st={fade_out_start}:d={fade_out_sec}",
        "-y", str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path


def _get_duration(path: Path) -> Optional[float]:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return None


def process_one(
    input_path: Path,
    *,
    normalize: bool = True,
    fade: bool = False,
    convert_mp3: bool = True,
    title: str = "",
    artist: str = "AI",
    album: str = "ai-music-lab",
    delete_intermediates: bool = True,
) -> dict:
    """端到端处理一个文件,返回报告。

    管线: 原始 → (淡入淡出) → 归一化 → (转 MP3) → ID3 tag
    """
    report = {"input": str(input_path), "steps": [], "output": str(input_path), "errors": []}
    current = input_path
    intermediates = []

    try:
        if fade:
            faded = fade_in_out(current)
            report["steps"].append(f"fade: {faded.name}")
            if current != input_path:
                intermediates.append(current)
            current = faded

        if normalize:
            norm = normalize_loudness(current)
            report["steps"].append(f"normalize: {norm.name}")
            if current != input_path:
                intermediates.append(current)
            current = norm

        if convert_mp3 and current.suffix.lower() == ".wav":
            mp3 = wav_to_mp3(current)
            report["steps"].append(f"mp3: {mp3.name}")
            if current != input_path:
                intermediates.append(current)
            current = mp3

        # tag (MP3/FLAC 支持)
        if title or artist:
            tag_audio(current, title=title or input_path.stem,
                      artist=artist, album=album)
            report["steps"].append("tag")

        report["output"] = str(current)

        if delete_intermediates:
            for f in intermediates:
                try:
                    f.unlink()
                except FileNotFoundError:
                    pass

    except Exception as e:
        report["errors"].append(str(e))

    return report
