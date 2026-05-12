"""Reaper .rpp 工程文件生成

.rpp 是开放文本格式. 我们生成的工程包含:
- 6 个音频 stem 轨 (drums/bass/guitar/piano/other/vocals_AI_ref)
- 3 个 MIDI 轨 (drums/bass/piano, 默认 mute 作为备选)
- 1 个空待录轨 (用户的人声, 已 arm record)
- 段落 marker (intro/verse/chorus)
- 项目 BPM 设到检测出来的值

注意:
- 路径写**相对路径**, .rpp 跟 stems/ 同目录, Reaper 能解析
- 不预装 plugin (PEAKCOL+FX 链格式 version-specific 不稳定),
  让用户自己加 ReaEQ/ReaComp (Reaper 自带, 30 秒能加完)
"""
import uuid
from pathlib import Path
from typing import Optional


def _guid() -> str:
    """Reaper GUID 格式: {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}"""
    return "{" + str(uuid.uuid4()).upper() + "}"


def _color_rgb(r: int, g: int, b: int) -> int:
    """RGB → Reaper PEAKCOL int (BGR + 0x01000000 flag)"""
    return 0x01000000 | (b << 16) | (g << 8) | r


# 预设颜色
COLOR_RED       = _color_rgb(220, 80, 80)
COLOR_YELLOW    = _color_rgb(220, 200, 80)
COLOR_BLUE      = _color_rgb(80, 130, 220)
COLOR_GREEN     = _color_rgb(80, 180, 100)
COLOR_PURPLE    = _color_rgb(180, 100, 200)
COLOR_GRAY      = _color_rgb(150, 150, 150)
COLOR_ORANGE    = _color_rgb(240, 140, 60)
COLOR_PINK      = _color_rgb(240, 130, 180)
COLOR_LIGHTGRAY = _color_rgb(100, 100, 100)


def _safe_string(s: str) -> str:
    """转义 .rpp 字符串里的内部引号"""
    return str(s).replace('"', "'")


# ─────────────── MIDI → Reaper events ───────────────

def midi_to_reaper_events(
    midi_path: Path,
    project_bpm: float = 120.0,
    ppq: int = 960,
) -> Optional[str]:
    """读 .mid 文件, 转成 Reaper 的 E 命令格式.

    Reaper MIDI event 格式:
        E <delta_ppq> <status_hex> <data1_hex> <data2_hex>

    Status:
        0x90 + ch = Note On (channel)
        0x80 + ch = Note Off
        0x9 (channel 10, idx 9) = drum channel

    返回 None 表示失败/空; 返回字符串则是 events 块 (无外层 wrapper).
    """
    try:
        import pretty_midi
    except ImportError:
        return None

    try:
        pm = pretty_midi.PrettyMIDI(str(midi_path))
    except Exception:
        return None

    if not pm.instruments:
        return None

    # 收集所有 note events 转成 (abs_ppq, status, pitch, vel)
    events = []
    for inst in pm.instruments:
        channel = 9 if inst.is_drum else 0   # drum = channel 10 (idx 9)
        for note in inst.notes:
            start_ppq = int(note.start * (project_bpm / 60.0) * ppq)
            end_ppq = int(note.end * (project_bpm / 60.0) * ppq)
            if end_ppq <= start_ppq:
                end_ppq = start_ppq + ppq // 16   # 最少 1/16 音
            vel = max(1, min(127, int(note.velocity)))

            events.append((start_ppq, 0x90 | channel, note.pitch, vel))
            events.append((end_ppq, 0x80 | channel, note.pitch, 0))

    if not events:
        return None

    # 排序: 时间, 同时间 note-off 在 note-on 前
    events.sort(key=lambda e: (e[0], 0 if (e[1] & 0xF0) == 0x80 else 1))

    lines = []
    prev_ppq = 0
    for abs_ppq, status, pitch, vel in events:
        delta = abs_ppq - prev_ppq
        if delta < 0:
            delta = 0
        lines.append(f"        E {delta} {status:02X} {pitch:02X} {vel:02X}")
        prev_ppq = abs_ppq

    # 末尾加 all-notes-off CC (避免悬挂)
    lines.append("        E 0 B0 7B 00")

    return "\n".join(lines)


# ─────────────── Item generators ───────────────

def _wav_item(
    relative_path: str,
    position: float,
    length: float,
    name: str = "",
) -> str:
    """音频 ITEM 块"""
    name = name or Path(relative_path).name
    return f"""    <ITEM
      POSITION {position}
      SNAPOFFS 0
      LENGTH {length}
      LOOP 0
      ALLTAKES 0
      FADEIN 1 0.01 0 1 0 0 0
      FADEOUT 1 0.01 0 1 0 0 0
      MUTE 0 0
      SEL 0
      IGUID {_guid()}
      IID 1
      NAME "{_safe_string(name)}"
      VOLPAN 1 0 1 -1
      SOFFS 0
      PLAYRATE 1 1 0 -1 0 0.0025
      CHANMODE 0
      GUID {_guid()}
      <SOURCE WAVE
        FILE "{_safe_string(relative_path)}"
      >
    >
"""


def _midi_item(
    midi_path: Path,
    position: float,
    length: float,
    project_bpm: float,
    name: str = "",
) -> str:
    """MIDI ITEM 块, 把 .mid 文件的 events 嵌入到 .rpp 里"""
    events_text = midi_to_reaper_events(midi_path, project_bpm)
    if not events_text:
        return ""

    name = name or midi_path.stem

    return f"""    <ITEM
      POSITION {position}
      SNAPOFFS 0
      LENGTH {length}
      LOOP 0
      ALLTAKES 0
      FADEIN 0 0 0 0 0 0 0
      FADEOUT 0 0 0 0 0 0 0
      MUTE 0 0
      SEL 0
      IGUID {_guid()}
      IID 2
      NAME "{_safe_string(name)}"
      VOLPAN 1 0 1 -1
      SOFFS 0
      PLAYRATE 1 1 0 -1 0 0.0025
      CHANMODE 0
      GUID {_guid()}
      <SOURCE MIDI
        HASDATA 1 960 QN
        CCINTERP 32
        POOLEDEVTS {_guid()}
{events_text}
      >
    >
"""


def _track(
    name: str,
    color: int = COLOR_GRAY,
    items_text: str = "",
    armed: bool = False,
    muted: bool = False,
    volume: float = 1.0,
) -> str:
    """轨道块"""
    mute_flag = 1 if muted else 0
    arm_flag = 1 if armed else 0

    return f"""  <TRACK {_guid()}
    NAME "{_safe_string(name)}"
    PEAKCOL {color}
    BEAT -1
    AUTOMODE 0
    VOLPAN {volume} 0 -1 -1 1
    MUTESOLO {mute_flag} 0 0
    IPHASE 0
    PANLAWFLAGS 0 0 1 0
    ISBUS 0 0
    BUSCOMP 0 0 0 0 0
    SHOWINMIX 1 0.6667 0.5 1 0.5 -1 -1 -1
    REC {arm_flag} 0 0 0 0 0 0 0
    VU 2
    TRACKHEIGHT 0 0 0 0 0 0
    INQ 0 0 0 0.5 100 0 0 100
    NCHAN 2
    FX 1
    TRACKID {_guid()}
    PERF 0
{items_text}  >
"""


def _markers_text(markers: list) -> str:
    """段落 marker 行"""
    if not markers:
        return ""
    lines = []
    for i, m in enumerate(markers, start=1):
        name = _safe_string(m.get("name", f"Marker {i}"))
        pos = m.get("position", 0)
        lines.append(f'  MARKER {i} {pos} "{name}" 0')
    return "\n".join(lines) + "\n"


# ─────────────── Project assembly ───────────────

def build_project_text(
    bpm: float,
    sample_rate: int,
    tracks_text: str,
    markers: list = None,
) -> str:
    """生成完整 .rpp 文本"""
    markers_str = _markers_text(markers or [])

    return f"""<REAPER_PROJECT 0.1 "7.0/generic" 0
  RIPPLE 0
  GROUPOVERRIDE 0 0 0
  AUTOXFADE 257
  ENVATTACH 3
  POOLEDENVATTACH 0
  MIXERUIFLAGS 11 48
  PEAKGAIN 1
  FEEDBACK 0
  PANLAW 1
  PROJOFFS 0 0 0
  MAXPROJLEN 0 600
  GRID 3199 8 1 8 1 0 0 0
  TIMEMODE 1 5 -1 30 0 0 -1
  VIDEO_CONFIG 0 0 256
  PANMODE 3
  PANLAWFLAGS 3
  CURSOR 0
  ZOOM 100 0 0
  VZOOMEX 6 0
  USE_REC_CFG 0
  RECMODE 1
  SMPTESYNC 0 30 100 40 1000 300 0 0 1 0 0
  LOOP 0
  LOOPGRAN 0 4
  RECORD_PATH "" ""
  <RECORD_CFG
  >
  <APPLYFX_CFG
  >
  RENDER_FILE ""
  RENDER_PATTERN ""
  RENDER_FMT 0 2 0
  RENDER_1X 0
  RENDER_RANGE 1 0 0 18 1000
  RENDER_RESAMPLE 3 0 1
  RENDER_ADDTOPROJ 0
  RENDER_STEMS 0
  RENDER_DITHER 0
  TIMELOCKMODE 1
  TEMPOENVLOCKMODE 1
  ITEMMIX 0
  DEFPITCHMODE 589824 0
  TAKELANE 1
  SAMPLERATE {sample_rate} 0 0
  <RENDER_CFG
  >
  LOCK 1
  <METRONOME 6 2
    VOL 0.25 0.125
    FREQ 800 1600 1
    BEATLEN 4
    SAMPLES "" ""
    PATTERN 2863311530 2863311529
  >
  GLOBAL_AUTO -1
  TEMPO {bpm} 4 4
{markers_str}{tracks_text}>
"""


def generate_project(
    project_dir: Path,
    project_name: str,
    stems: dict,         # {stem_name (drums/bass/...): Path}
    midi_files: dict,    # {stem_name: Path}, can be empty
    bpm: float,
    duration: float,
    markers: list = None,
    sample_rate: int = 44100,
) -> Path:
    """生成完整 Reaper 工程, 返回 .rpp 路径.

    工程结构 (按轨道顺序):
      01 Vocals (AI ref, mute)
      02 Drums Audio
      02b Drums MIDI (mute, 备选)
      03 Bass Audio
      03b Bass MIDI (mute, 备选)
      04 Guitar Audio (无 MIDI)
      05 Piano Audio
      05b Piano MIDI (mute, 备选)
      06 Other (pads/strings)
      07 ★ YOUR VOCAL (armed for record)
    """
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    rpp_path = project_dir / f"{project_name}.rpp"

    tracks = []

    def rel(p: Path) -> str:
        """stems 路径相对 .rpp 路径"""
        try:
            return str(p.relative_to(project_dir)).replace("\\", "/")
        except ValueError:
            return str(p)

    # 1. Vocals (AI reference, muted)
    if "vocals" in stems:
        items = _wav_item(rel(stems["vocals"]), 0, duration,
                          "Vocals (AI Reference - replace with YOUR recording)")
        tracks.append(_track(
            "01 Vocals (AI ref) — mute me after recording",
            COLOR_GRAY, items, muted=True,
        ))

    # 2. Drums Audio
    if "drums" in stems:
        items = _wav_item(rel(stems["drums"]), 0, duration)
        tracks.append(_track("02 Drums (Audio)", COLOR_YELLOW, items))

    # 2b. Drums MIDI
    if "drums" in midi_files and midi_files["drums"].exists():
        midi_items = _midi_item(midi_files["drums"], 0, duration, bpm,
                                "drums.mid (kick/snare/hh detected)")
        if midi_items:
            tracks.append(_track(
                "02b Drums (MIDI alt) — unmute to swap drum sounds",
                COLOR_YELLOW, midi_items, muted=True, volume=0.7,
            ))

    # 3. Bass Audio
    if "bass" in stems:
        items = _wav_item(rel(stems["bass"]), 0, duration)
        tracks.append(_track("03 Bass (Audio)", COLOR_BLUE, items))

    # 3b. Bass MIDI
    if "bass" in midi_files and midi_files["bass"].exists():
        midi_items = _midi_item(midi_files["bass"], 0, duration, bpm,
                                "bass.mid")
        if midi_items:
            tracks.append(_track(
                "03b Bass (MIDI alt)",
                COLOR_BLUE, midi_items, muted=True, volume=0.7,
            ))

    # 4. Guitar (audio only, no MIDI)
    if "guitar" in stems:
        items = _wav_item(rel(stems["guitar"]), 0, duration)
        tracks.append(_track(
            "04 Guitar (Audio only — multi-voice MIDI unsupported)",
            COLOR_GREEN, items,
        ))

    # 5. Piano Audio
    if "piano" in stems:
        items = _wav_item(rel(stems["piano"]), 0, duration)
        tracks.append(_track("05 Piano (Audio)", COLOR_PURPLE, items))

    # 5b. Piano MIDI
    if "piano" in midi_files and midi_files["piano"].exists():
        midi_items = _midi_item(midi_files["piano"], 0, duration, bpm,
                                "piano.mid")
        if midi_items:
            tracks.append(_track(
                "05b Piano (MIDI alt)",
                COLOR_PURPLE, midi_items, muted=True, volume=0.7,
            ))

    # 6. Other (pads/strings)
    if "other" in stems:
        items = _wav_item(rel(stems["other"]), 0, duration)
        tracks.append(_track(
            "06 Other (pads/strings/etc)",
            COLOR_LIGHTGRAY, items,
        ))

    # 7. YOUR Vocal (armed, empty)
    tracks.append(_track(
        "★ 07 YOUR VOCAL — press R to arm then record",
        COLOR_PINK, "", armed=True,
    ))

    project_text = build_project_text(
        bpm=bpm,
        sample_rate=sample_rate,
        tracks_text="\n".join(tracks),
        markers=markers,
    )

    rpp_path.write_text(project_text, encoding="utf-8")
    return rpp_path
