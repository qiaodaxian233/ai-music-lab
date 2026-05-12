"""生成历史索引器

每首歌一条记录,存在 outputs/.history-index.json。
记录字段: filename, prompt, lyrics, seed, lora, rating, tags, notes, favorited, etc.
"""
import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, Any

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT / "outputs"
INDEX_PATH = OUTPUTS_DIR / ".history-index.json"

AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _default_index() -> dict:
    return {"version": 1, "songs": {}}


def load_index() -> dict:
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return _default_index()
    return _default_index()


def save_index(index: dict) -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def get_audio_duration(path: Path) -> Optional[float]:
    """秒数,失败返回 None。优先用 mutagen,后退到 wave。"""
    try:
        from mutagen import File as MutagenFile
        f = MutagenFile(str(path))
        if f is not None and f.info is not None:
            return float(f.info.length)
    except Exception:
        pass
    try:
        import wave
        with wave.open(str(path)) as w:
            return w.getnframes() / w.getframerate()
    except Exception:
        return None


def _load_sidecar(audio_path: Path) -> dict:
    """如果同名 .json 存在(比如未来 ACE-Step 自带的元数据),自动合并。"""
    sidecar = audio_path.with_suffix(".json")
    if sidecar.exists():
        try:
            return json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _new_entry(audio_path: Path) -> dict:
    stat = audio_path.stat()
    entry: dict[str, Any] = {
        "filename": audio_path.name,
        "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(timespec="seconds"),
        "file_size_bytes": stat.st_size,
        "duration_seconds": get_audio_duration(audio_path),
        "prompt": "",
        "lyrics": "",
        "seed": None,
        "params": {},
        "lora": "",
        "rating": 0,
        "tags": [],
        "notes": "",
        "favorited": False,
        "normalized": "_normalized" in audio_path.stem,
        "linked_normalized_id": None,
        "linked_original_id": None,
    }
    # merge sidecar JSON if present
    sidecar = _load_sidecar(audio_path)
    for k, v in sidecar.items():
        if k in entry and entry[k] in ("", None, [], {}, 0, False):
            entry[k] = v
    return entry


def scan_and_update(outputs_dir: Path = OUTPUTS_DIR) -> tuple[int, int]:
    """扫描 outputs/,加入未追踪的文件。返回 (新增数, 总数)。"""
    index = load_index()
    songs = index["songs"]

    # filename -> existing id
    filename_to_id = {s["filename"]: fid for fid, s in songs.items()}
    existing_files = set(filename_to_id.keys())

    if not outputs_dir.exists():
        return 0, len(songs)

    added = 0
    for path in outputs_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in AUDIO_EXTS:
            continue
        if path.name.startswith("."):
            continue
        if path.name in existing_files:
            continue

        fid = _new_id()
        songs[fid] = _new_entry(path)
        added += 1

    # link _normalized.wav with original
    for fid, s in list(songs.items()):
        if s.get("normalized") and not s.get("linked_original_id"):
            # try to find original (filename without _normalized)
            orig_name = s["filename"].replace("_normalized", "")
            orig_id = filename_to_id.get(orig_name) or next(
                (i for i, ss in songs.items() if ss["filename"] == orig_name), None
            )
            if orig_id:
                s["linked_original_id"] = orig_id
                songs[orig_id]["linked_normalized_id"] = fid

    save_index(index)
    return added, len(songs)


def register(filename: str, **metadata) -> Optional[str]:
    """生成完之后手动登记一条富元数据(从生成脚本调用)。"""
    path = OUTPUTS_DIR / filename
    if not path.exists():
        return None
    scan_and_update()
    index = load_index()
    fid = next((i for i, s in index["songs"].items() if s["filename"] == filename), None)
    if not fid:
        return None
    update_entry(fid, **metadata)
    return fid


def update_entry(fid: str, **fields) -> bool:
    index = load_index()
    if fid not in index["songs"]:
        return False
    # 防止覆盖关键 id 字段
    fields.pop("filename", None)
    index["songs"][fid].update(fields)
    save_index(index)
    return True


def delete_entry(fid: str, delete_file: bool = False) -> bool:
    index = load_index()
    if fid not in index["songs"]:
        return False
    entry = index["songs"][fid]
    if delete_file:
        try:
            (OUTPUTS_DIR / entry["filename"]).unlink()
        except FileNotFoundError:
            pass
    del index["songs"][fid]
    save_index(index)
    return True


def search(query: str = "", favorites_only: bool = False,
           min_rating: int = 0) -> list[tuple[str, dict]]:
    """返回 [(fid, entry), ...] 按 created_at 倒序"""
    index = load_index()
    q = query.lower().strip()
    results = []
    for fid, s in index["songs"].items():
        if favorites_only and not s.get("favorited"):
            continue
        if min_rating and (s.get("rating") or 0) < min_rating:
            continue
        if q:
            hay = " ".join([
                s.get("filename", ""),
                s.get("prompt", ""),
                s.get("lyrics", ""),
                s.get("lora", ""),
                s.get("notes", ""),
                ",".join(s.get("tags", []) or []),
            ]).lower()
            if q not in hay:
                continue
        results.append((fid, s))
    results.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)
    return results


if __name__ == "__main__":
    # CLI: 重新扫描
    added, total = scan_and_update()
    print(f"✓ 扫描完成,新增 {added} 首,共 {total} 首")
