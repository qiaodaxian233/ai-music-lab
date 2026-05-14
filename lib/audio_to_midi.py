"""Audio → MIDI 转录

- transcribe_melodic: 用 Spotify Basic Pitch 转录旋律乐器 (钢琴/贝斯/单音吉他/人声)
- transcribe_drums: 简单 onset + 频谱分类 (kick/snare/hh), 质量看歌
- detect_bpm: librosa beat track
- detect_structure_markers: 段落边界检测 (intro/verse/chorus)
- quick_transcribe: 一键串 (v0.5.1): 整曲音频 → MIDI + BPM + 段落 marker, 跳过 stem 分离
"""
from pathlib import Path
from typing import Optional

# GM drum map
KICK = 36
SNARE = 38
CLOSED_HH = 42
OPEN_HH = 46


def check_basic_pitch() -> bool:
    try:
        import basic_pitch  # noqa: F401
        return True
    except ImportError:
        return False


def transcribe_melodic(audio_path: Path, midi_path: Path) -> dict:
    """用 Basic Pitch 转录单旋律乐器到 MIDI.

    返回 {ok: bool, error: str|None, notes: int}
    """
    if not check_basic_pitch():
        return {"ok": False, "error": "basic-pitch 未装", "notes": 0}

    try:
        from basic_pitch.inference import predict

        midi_path.parent.mkdir(parents=True, exist_ok=True)
        model_output, midi_data, note_events = predict(str(audio_path))
        midi_data.write(str(midi_path))
        return {"ok": True, "error": None, "notes": len(note_events)}
    except Exception as e:
        return {"ok": False, "error": str(e), "notes": 0}


def transcribe_drums(
    audio_path: Path,
    midi_path: Path,
    bpm: float = 120.0,
) -> dict:
    """简单鼓转录: onset 检测 + 三段频谱分类.

    用 librosa, 不依赖 ADTLib 那种难装的包.
    简单 4/4 流行鼓质量还可以, 复杂打击乐就一般.

    返回 {ok, error, kicks, snares, hihats, total}
    """
    try:
        import librosa
        import numpy as np
        import pretty_midi
    except ImportError as e:
        return {
            "ok": False,
            "error": f"缺包: {e}",
            "kicks": 0, "snares": 0, "hihats": 0, "total": 0,
        }

    try:
        y, sr = librosa.load(str(audio_path), sr=22050, mono=True)

        onset_times = librosa.onset.onset_detect(
            y=y, sr=sr,
            units="time",
            backtrack=True,
            delta=0.15,
            wait=4,
        )

        pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
        drums = pretty_midi.Instrument(program=0, is_drum=True, name="Drums")

        n_kick = n_snare = n_hh = 0

        for t in onset_times:
            start_sample = int(t * sr)
            end_sample = min(start_sample + int(0.05 * sr), len(y))
            if end_sample - start_sample < 100:
                continue
            snippet = y[start_sample:end_sample]

            fft = np.abs(np.fft.rfft(snippet))
            freqs = np.fft.rfftfreq(len(snippet), 1.0 / sr)

            low = float(np.sum(fft[freqs < 150]))
            mid = float(np.sum(fft[(freqs >= 200) & (freqs < 1500)]))
            high = float(np.sum(fft[freqs >= 5000]))
            total = low + mid + high + 1e-9

            if low / total > 0.45:
                pitch = KICK
                n_kick += 1
            elif high / total > 0.35:
                pitch = CLOSED_HH
                n_hh += 1
            else:
                pitch = SNARE
                n_snare += 1

            drums.notes.append(pretty_midi.Note(
                velocity=80,
                pitch=pitch,
                start=float(t),
                end=float(t) + 0.08,
            ))

        pm.instruments.append(drums)
        midi_path.parent.mkdir(parents=True, exist_ok=True)
        pm.write(str(midi_path))

        return {
            "ok": True,
            "error": None,
            "kicks": n_kick,
            "snares": n_snare,
            "hihats": n_hh,
            "total": n_kick + n_snare + n_hh,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "kicks": 0, "snares": 0, "hihats": 0, "total": 0,
        }


def detect_bpm(audio_path: Path) -> float:
    """检测 BPM, 失败默认 120"""
    try:
        import librosa
        y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        return float(tempo.item() if hasattr(tempo, "item") else tempo)
    except Exception:
        return 120.0


def detect_structure_markers(audio_path: Path, max_markers: int = 6) -> list:
    """段落边界检测, 返回 [{position: float seconds, name: str}].

    用 librosa agglomerative segmentation. 流行歌 5-7 段比较合理.
    名字按经验起 (Intro/Verse/Chorus...), 不保证准, 但能帮你定位.
    """
    try:
        import librosa

        y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
        duration = len(y) / sr

        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        # k 段
        k = min(max_markers, max(3, int(duration / 30)))
        bounds = librosa.segment.agglomerative(chroma, k=k)
        bound_times = librosa.frames_to_time(bounds, sr=sr)

        # 经验型命名: 流行歌通常 intro→verse→chorus→verse→chorus→bridge→chorus→outro
        section_names = [
            "Intro", "Verse 1", "Chorus 1", "Verse 2",
            "Chorus 2", "Bridge", "Chorus 3", "Outro",
        ]

        markers = []
        for i, t in enumerate(bound_times):
            if i >= len(section_names):
                name = f"Section {i + 1}"
            else:
                name = section_names[i]
            markers.append({"position": float(t), "name": name})

        return markers
    except Exception:
        return []


# ───────────────────────────────────────────────
# quick_transcribe: 一键 (v0.5.1)
# ───────────────────────────────────────────────

def quick_transcribe(
    audio_path: Path,
    *,
    output_dir: Optional[Path] = None,
    mode: str = "melodic",   # 'melodic' | 'drums' | 'both'
    with_bpm: bool = True,
    with_markers: bool = True,
    embed_meta: bool = True,  # 把 BPM/marker 嵌进 .mid 文件本身
) -> dict:
    """整曲音频 → MIDI + BPM + 段落 marker, **跳过 stem 分离**.

    输出到 output_dir (默认 outputs/midi/<stem>/):
      - melodic.mid  (mode='melodic' 或 'both')
      - drums.mid    (mode='drums'   或 'both')
      - bpm.txt      (with_bpm=True)
      - markers.txt  (with_markers=True)

    embed_meta=True 会把 BPM 写进 MIDI 的 initial_tempo,把 markers 写成
    pretty_midi 的 lyric/text 事件 (DAW 能读到当作段落 marker).

    返回 {
      ok: bool,
      output_dir: Path,
      files: [Path, ...],
      bpm: float | None,
      markers: list,
      melodic: {ok, error, notes} | None,
      drums:   {ok, error, kicks, snares, hihats, total} | None,
      errors: [str, ...],
    }
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        return {"ok": False, "errors": [f"找不到 {audio_path}"], "files": []}

    if output_dir is None:
        output_dir = audio_path.parent.parent / "outputs" / "midi" / audio_path.stem
        # 如果 audio 不在 outputs 里, 上面那个相对路径会乱跳, 兜底:
        if "outputs" not in str(audio_path):
            output_dir = audio_path.parent / "midi" / audio_path.stem
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "ok": True,
        "output_dir": output_dir,
        "files": [],
        "bpm": None,
        "markers": [],
        "melodic": None,
        "drums": None,
        "errors": [],
    }

    # 1. BPM (轻量, 先跑)
    if with_bpm or mode in ("drums", "both") or embed_meta:
        try:
            result["bpm"] = detect_bpm(audio_path)
        except Exception as e:
            result["errors"].append(f"BPM 检测失败: {e}")
            result["bpm"] = 120.0
        if with_bpm:
            bpm_path = output_dir / "bpm.txt"
            bpm_path.write_text(f"{result['bpm']:.2f}\n", encoding="utf-8")
            result["files"].append(bpm_path)

    # 2. 段落 marker
    if with_markers or embed_meta:
        try:
            result["markers"] = detect_structure_markers(audio_path)
        except Exception as e:
            result["errors"].append(f"段落检测失败: {e}")
            result["markers"] = []
        if with_markers and result["markers"]:
            mk_path = output_dir / "markers.txt"
            lines = ["# position(sec)\tname"]
            for m in result["markers"]:
                lines.append(f"{m['position']:.2f}\t{m['name']}")
            mk_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result["files"].append(mk_path)

    # 3. melodic MIDI (Basic Pitch)
    if mode in ("melodic", "both"):
        mp = output_dir / "melodic.mid"
        r = transcribe_melodic(audio_path, mp)
        result["melodic"] = r
        if r["ok"]:
            if embed_meta and (result["bpm"] or result["markers"]):
                _inject_meta_into_midi(mp, result["bpm"] or 120.0, result["markers"])
            result["files"].append(mp)
        else:
            result["errors"].append(f"melodic 失败: {r['error']}")

    # 4. drums MIDI
    if mode in ("drums", "both"):
        dp = output_dir / "drums.mid"
        r = transcribe_drums(audio_path, dp, bpm=result["bpm"] or 120.0)
        result["drums"] = r
        if r["ok"]:
            if embed_meta and result["markers"]:
                _inject_meta_into_midi(dp, result["bpm"] or 120.0, result["markers"])
            result["files"].append(dp)
        else:
            result["errors"].append(f"drums 失败: {r['error']}")

    result["ok"] = bool(result["files"]) and not any(
        e for e in result["errors"]
        if "melodic 失败" in e or "drums 失败" in e
    )
    return result


def _inject_meta_into_midi(midi_path: Path, bpm: float, markers: list):
    """把 BPM + markers 写进 .mid 文件. markers 用 pretty_midi 的 text 事件.

    DAW (Reaper / Ableton / Cubase) 都能读 text 事件当 marker.
    """
    try:
        import pretty_midi
        pm = pretty_midi.PrettyMIDI(str(midi_path))
        # 重新设 tempo (pretty_midi 没有简单 API 改 initial_tempo,绕个弯)
        # 一种办法: 在 MIDI 头加 tempo change
        # pretty_midi 提供 _tick_scales 但 API 私有, 这里只能新建一个再 merge
        # 实践中 Basic Pitch 输出的 MIDI tempo 通常是 120,
        # 重新写一个相同内容但 tempo 不同的 MIDI:
        new = pretty_midi.PrettyMIDI(initial_tempo=float(bpm))
        for inst in pm.instruments:
            new.instruments.append(inst)
        # markers → text 事件 (放在 lyrics, DAW 多数把它当 marker)
        for m in markers:
            new.lyrics.append(pretty_midi.Lyric(
                text=m["name"],
                time=float(m["position"]),
            ))
        new.write(str(midi_path))
    except Exception:
        # 失败不致命, .mid 仍然有效, 只是没 tempo/marker
        pass
