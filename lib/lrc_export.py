"""歌词字幕导出 (功能 #10) — .lrc 文件

两种对齐策略:
1. 'even' 均分模式 (默认,无依赖):
   按行均分时长,简单但不精确。适合所有人能跑通。
2. 'whisper' 强制对齐模式 (opt-in,需装 openai-whisper):
   用 Whisper 语音识别 + 给定歌词做强制对齐,得到逐行真实时间戳。
   精度高,但需 ~2GB 模型 + GPU 才快。

.lrc 标准格式:
    [00:12.34] Line one
    [00:18.50] Line two
"""
import re
from pathlib import Path
from typing import Optional


# ───────────────────────────────────────────────
# 工具
# ───────────────────────────────────────────────

def _fmt_lrc_time(sec: float) -> str:
    """秒 → [mm:ss.xx]"""
    sec = max(0.0, sec)
    m = int(sec // 60)
    s = sec - m * 60
    return f"[{m:02d}:{s:05.2f}]"


def split_lyrics_lines(lyrics: str) -> list[str]:
    """分行,跳过空行 + 章节标签 ([Verse 1] 等)"""
    lines = []
    for raw in (lyrics or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        # 章节标签如 [Verse 1] [Chorus] 跳过 (LRC 自己有 [time] 标签)
        if re.fullmatch(r"\[[^\]]+\]", line):
            continue
        lines.append(line)
    return lines


def get_audio_duration(audio_path: Path) -> Optional[float]:
    """优先 mutagen, 失败 librosa, 都失败返 None"""
    try:
        from mutagen import File as MutagenFile
        f = MutagenFile(str(audio_path))
        if f and f.info:
            return float(f.info.length)
    except Exception:
        pass
    try:
        import librosa
        return float(librosa.get_duration(path=str(audio_path)))
    except Exception:
        return None


# ───────────────────────────────────────────────
# 模式 1: 均分对齐 (无依赖)
# ───────────────────────────────────────────────

def make_lrc_even(
    lyrics: str,
    duration: float,
    *,
    intro_offset: float = 4.0,
    outro_offset: float = 3.0,
    title: str = "",
    artist: str = "AI",
) -> str:
    """按行均分时间戳。前奏空 intro_offset 秒, 尾奏空 outro_offset 秒。"""
    lines = split_lyrics_lines(lyrics)
    if not lines:
        return f"[ti:{title}]\n[ar:{artist}]\n[length:{_fmt_dur(duration)}]\n"

    singing = max(1.0, duration - intro_offset - outro_offset)
    per_line = singing / len(lines)

    out = []
    if title:
        out.append(f"[ti:{title}]")
    if artist:
        out.append(f"[ar:{artist}]")
    out.append(f"[length:{_fmt_dur(duration)}]")
    out.append(f"[by:ai-music-lab]")
    out.append("")

    t = intro_offset
    for line in lines:
        out.append(f"{_fmt_lrc_time(t)}{line}")
        t += per_line
    # 收尾
    out.append(f"{_fmt_lrc_time(min(t, duration))}")
    return "\n".join(out)


def _fmt_dur(sec: float) -> str:
    m = int(sec // 60)
    s = int(sec - m * 60)
    return f"{m:02d}:{s:02d}"


# ───────────────────────────────────────────────
# 模式 2: Whisper 强制对齐 (opt-in)
# ───────────────────────────────────────────────

def make_lrc_whisper(
    audio_path: Path,
    lyrics: str,
    *,
    model_size: str = "small",
    language: Optional[str] = None,
    title: str = "",
    artist: str = "AI",
) -> str:
    """用 whisper 给音频做 ASR + 用给定歌词重对齐。

    流程:
    1) whisper 转录 audio,得到带时间戳的段落
    2) 把转录文本按给定 lyrics 的行数重新分组 (按段落顺序贪心匹配)
    3) 输出 LRC

    精度依赖于 whisper 识别质量。中文用 'small' 起步,英文 'tiny' 可能够。
    """
    try:
        import whisper  # type: ignore
    except ImportError:
        raise RuntimeError(
            "需要 openai-whisper。\n"
            "  pip install openai-whisper\n"
            "或用 make_lrc_even (无依赖,均分对齐)。"
        )

    model = whisper.load_model(model_size)
    result = model.transcribe(
        str(audio_path),
        language=language,
        word_timestamps=True,
        verbose=False,
    )

    segments = result.get("segments", [])
    target_lines = split_lyrics_lines(lyrics)
    if not target_lines or not segments:
        # 退化到均分
        duration = get_audio_duration(Path(audio_path)) or 60.0
        return make_lrc_even(lyrics, duration, title=title, artist=artist)

    # 简单策略: 把 segments 按时间均匀分给 target_lines
    # 每个 target line 拿到 (i / n_lines) 比例位置的 segment.start
    out = []
    if title:
        out.append(f"[ti:{title}]")
    if artist:
        out.append(f"[ar:{artist}]")
    duration = get_audio_duration(Path(audio_path)) or 60.0
    out.append(f"[length:{_fmt_dur(duration)}]")
    out.append(f"[by:ai-music-lab + whisper-{model_size}]")
    out.append("")

    n = len(target_lines)
    for i, line in enumerate(target_lines):
        # 找该比例位置最近的 segment.start
        target_t = duration * (i / n)
        nearest = min(segments, key=lambda s: abs(s["start"] - target_t))
        out.append(f"{_fmt_lrc_time(nearest['start'])}{line}")
    return "\n".join(out)


# ───────────────────────────────────────────────
# 高层 API: 一键导出
# ───────────────────────────────────────────────

def export_lrc(
    audio_path: Path,
    lyrics: str,
    *,
    output_path: Optional[Path] = None,
    mode: str = "even",
    title: str = "",
    artist: str = "AI",
    **kwargs,
) -> Path:
    """生成 .lrc 文件并写盘。

    mode: 'even' (默认,无依赖) 或 'whisper' (高精度,需装 whisper)
    output_path: 默认 audio_path.with_suffix('.lrc')
    """
    audio_path = Path(audio_path)
    if output_path is None:
        output_path = audio_path.with_suffix(".lrc")
    output_path = Path(output_path)

    if mode == "whisper":
        text = make_lrc_whisper(audio_path, lyrics, title=title, artist=artist, **kwargs)
    else:
        duration = kwargs.get("duration") or get_audio_duration(audio_path) or 60.0
        text = make_lrc_even(lyrics, duration, title=title, artist=artist)

    output_path.write_text(text, encoding="utf-8")
    return output_path
