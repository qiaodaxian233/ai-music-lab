"""Audio → MIDI 转录

- transcribe_melodic: 用 Spotify Basic Pitch 转录旋律乐器 (钢琴/贝斯/单音吉他/人声)
- transcribe_drums: 简单 onset + 频谱分类 (kick/snare/hh), 质量看歌
- detect_bpm: librosa beat track
- detect_structure_markers: 段落边界检测 (intro/verse/chorus)
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
