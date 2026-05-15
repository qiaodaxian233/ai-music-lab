"""自动剪短版 / Highlight Clip (v0.5.2 功能 C)

从整曲找最有代表性的 30 秒(通常是 chorus),加淡入淡出导出。

算法:
1. 用 librosa 算 chroma + tempo
2. 跑 agglomerative segmentation 找段落
3. 用 recurrence_matrix 评估每个段落跟全曲其他段的相似度 (重复=chorus)
4. 选相似度最高的段, 取中心位置往前后扩到 30 秒
5. 加 50ms 淡入 + 1s 淡出 写盘

输出: outputs/highlights/<歌名>_30s.wav
"""
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
HIGHLIGHTS_DIR = ROOT / "outputs" / "highlights"


def make_highlight(
    audio_path: Path,
    *,
    output_path: Optional[Path] = None,
    target_seconds: float = 30.0,
    fade_in_ms: float = 50.0,
    fade_out_ms: float = 1000.0,
    strategy: str = "chorus",  # 'chorus' | 'middle' | 'start'
) -> dict:
    """切 30 秒高潮片段。

    strategy:
        chorus: 找最重复的段落(默认,推荐)
        middle: 直接取曲子中间 (兜底,librosa 失败时)
        start:  从头取 (最简单)

    返回 {ok, output_path, start_sec, end_sec, duration, strategy_used, error}
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        return {"ok": False, "error": f"找不到 {audio_path}"}

    if output_path is None:
        HIGHLIGHTS_DIR.mkdir(parents=True, exist_ok=True)
        output_path = HIGHLIGHTS_DIR / f"{audio_path.stem}_{int(target_seconds)}s.wav"
    output_path = Path(output_path)

    try:
        import librosa
        import soundfile as sf
        import numpy as np
    except ImportError as e:
        return {"ok": False, "error": f"缺包: {e}"}

    try:
        # 用原 sr 加载, 保持音质
        y, sr = librosa.load(str(audio_path), sr=None, mono=False)
        if y.ndim == 1:
            y_mono = y
        else:
            y_mono = librosa.to_mono(y)
        duration = len(y_mono) / sr
    except Exception as e:
        return {"ok": False, "error": f"加载音频失败: {e}"}

    if duration <= target_seconds:
        # 比目标短直接当 highlight
        _write_with_fade(y, sr, output_path, fade_in_ms, fade_out_ms)
        return {
            "ok": True, "output_path": output_path,
            "start_sec": 0, "end_sec": duration,
            "duration": duration, "strategy_used": "full (太短)",
        }

    start = None
    strategy_used = strategy

    if strategy == "chorus":
        try:
            start = _find_chorus_start(y_mono, sr, target_seconds)
            strategy_used = "chorus (检测到)"
        except Exception:
            strategy_used = "chorus 检测失败, 回退到 middle"
            start = None

    if start is None and strategy in ("chorus", "middle"):
        start = max(0.0, (duration - target_seconds) / 2)
        if strategy_used.startswith("chorus") and "失败" not in strategy_used:
            strategy_used = "middle"

    if start is None:
        start = 0.0
        strategy_used = "start"

    end = min(duration, start + target_seconds)
    start_sample = int(start * sr)
    end_sample = int(end * sr)
    if y.ndim == 1:
        clip = y[start_sample:end_sample]
    else:
        clip = y[:, start_sample:end_sample]

    _write_with_fade(clip, sr, output_path, fade_in_ms, fade_out_ms)

    return {
        "ok": True,
        "output_path": output_path,
        "start_sec": float(start),
        "end_sec": float(end),
        "duration": float(end - start),
        "strategy_used": strategy_used,
    }


def _find_chorus_start(y_mono, sr, target_seconds: float) -> float:
    """用 chroma 自相似矩阵找最"重复"的位置(经验上是 chorus)"""
    import librosa
    import numpy as np

    # 减少计算量: 把音频降到 22050 单声道
    if sr > 22050:
        y22 = librosa.resample(y_mono, orig_sr=sr, target_sr=22050)
        sr22 = 22050
    else:
        y22, sr22 = y_mono, sr

    duration = len(y22) / sr22

    # chroma 算自相似矩阵
    hop = 2048
    chroma = librosa.feature.chroma_cqt(y=y22, sr=sr22, hop_length=hop)
    # 平滑
    chroma = librosa.decompose.nn_filter(chroma,
                                         aggregate=np.median,
                                         metric="cosine")
    rec = librosa.segment.recurrence_matrix(chroma, mode="affinity",
                                             metric="cosine", sparse=False)

    # 每个时间点的"重复度" = 跟其他点的相似度之和
    repetition_score = rec.sum(axis=1)

    # 求 target_seconds 的滑动窗口最大值
    frame_per_sec = sr22 / hop
    win = int(target_seconds * frame_per_sec)
    if win >= len(repetition_score):
        return max(0.0, (duration - target_seconds) / 2)

    # 用累计和加速
    cumsum = np.cumsum(repetition_score)
    cumsum = np.concatenate([[0], cumsum])
    window_sums = cumsum[win:] - cumsum[:-win]
    best_frame = int(np.argmax(window_sums))
    start_sec = best_frame / frame_per_sec
    # 边界保护
    return max(0.0, min(start_sec, duration - target_seconds))


def _write_with_fade(audio, sr: int, output_path: Path,
                     fade_in_ms: float, fade_out_ms: float):
    """加淡入淡出后写盘"""
    import numpy as np
    import soundfile as sf

    if audio.ndim == 1:
        y = audio.astype(np.float32, copy=True)
    else:
        y = audio.astype(np.float32, copy=True)

    n_in = int(fade_in_ms / 1000 * sr)
    n_out = int(fade_out_ms / 1000 * sr)
    length = y.shape[-1]
    n_in = min(n_in, length // 2)
    n_out = min(n_out, length // 2)

    if n_in > 0:
        ramp_in = np.linspace(0.0, 1.0, n_in, dtype=np.float32)
        if y.ndim == 1:
            y[:n_in] *= ramp_in
        else:
            y[:, :n_in] *= ramp_in
    if n_out > 0:
        ramp_out = np.linspace(1.0, 0.0, n_out, dtype=np.float32)
        if y.ndim == 1:
            y[-n_out:] *= ramp_out
        else:
            y[:, -n_out:] *= ramp_out

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if y.ndim == 1:
        sf.write(str(output_path), y, sr)
    else:
        sf.write(str(output_path), y.T, sr)  # soundfile 要 (frames, channels)
