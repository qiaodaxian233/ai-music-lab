"""一键导出包 (v0.5.2 功能 A)

把一首歌相关的所有衍生物打成 zip,给朋友/平台投稿一次性搞定:
- audio:        原 wav (必)
- mp3:          自动从 wav 转 (可选, postprocess 复用)
- cover.png:    封面 (geometric / SDXL, 如果不存在则现生成)
- lyrics.lrc:   字幕 (均分,如果 .lrc 不存在则现生成)
- melody.mid:   主旋律 MIDI (如果 outputs/midi/<stem>/melodic.mid 不存在则现生成)
- metadata.json: 历史索引里的全部 metadata

输出: outputs/bundles/<歌名>.zip
"""
import json
import shutil
import zipfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
BUNDLES_DIR = ROOT / "outputs" / "bundles"


def build_bundle(
    audio_path: Path,
    *,
    output_zip: Optional[Path] = None,
    include_mp3: bool = True,
    include_cover: bool = True,
    include_lrc: bool = True,
    include_midi: bool = True,
    include_metadata: bool = True,
    cover_mode: str = "geometric",
    progress_callback=None,
) -> dict:
    """打包一首歌的所有衍生物。

    返回: {ok, zip_path, included: [...], missing: [...], errors: [...]}
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        return {"ok": False, "zip_path": None, "included": [],
                "missing": [], "errors": [f"找不到 {audio_path}"]}

    BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
    if output_zip is None:
        output_zip = BUNDLES_DIR / f"{audio_path.stem}.zip"
    output_zip = Path(output_zip)

    # 收集要打包的文件
    staging = BUNDLES_DIR / f"_staging_{audio_path.stem}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    included = []
    missing = []
    errors = []

    def step(i, total, msg):
        if progress_callback:
            progress_callback(i, total, msg)

    total_steps = 1 + sum([include_mp3, include_cover, include_lrc,
                           include_midi, include_metadata])
    s = 0

    # 1. 原 audio (必须)
    s += 1
    step(s, total_steps, f"复制 {audio_path.name}")
    dst_audio = staging / audio_path.name
    shutil.copy2(audio_path, dst_audio)
    included.append(audio_path.name)

    # 2. mp3 (用 postprocess 转)
    if include_mp3:
        s += 1
        step(s, total_steps, "转 MP3")
        if audio_path.suffix.lower() == ".mp3":
            included.append("(原文件已是 mp3)")
        else:
            mp3_path = audio_path.with_suffix(".mp3")
            if not mp3_path.exists():
                try:
                    from lib import postprocess
                    postprocess.convert_to_mp3(audio_path, mp3_path)
                except Exception as e:
                    errors.append(f"mp3 转换失败: {e}")
                    mp3_path = None
            if mp3_path and mp3_path.exists():
                shutil.copy2(mp3_path, staging / mp3_path.name)
                included.append(mp3_path.name)
            else:
                missing.append("mp3")

    # 3. cover
    if include_cover:
        s += 1
        step(s, total_steps, "封面")
        cover_path = ROOT / "outputs" / "covers" / f"{audio_path.stem}.png"
        # 找已有
        existing = None
        if cover_path.exists():
            existing = cover_path
        else:
            # 找近似命名 (cover_art 用了 hash 后缀)
            covers_dir = ROOT / "outputs" / "covers"
            if covers_dir.exists():
                for c in covers_dir.glob(f"{audio_path.stem}*.png"):
                    existing = c
                    break

        if not existing:
            try:
                from lib import cover_art
                if cover_mode == "sdxl":
                    existing = cover_art.make_cover_sdxl(audio_path.stem)
                else:
                    existing = cover_art.make_cover_geometric(audio_path.stem)
            except Exception as e:
                errors.append(f"封面生成失败: {e}")

        if existing and existing.exists():
            shutil.copy2(existing, staging / "cover.png")
            included.append("cover.png")
        else:
            missing.append("cover")

    # 4. lrc
    if include_lrc:
        s += 1
        step(s, total_steps, "歌词字幕")
        lrc_path = audio_path.with_suffix(".lrc")
        if not lrc_path.exists():
            # 从历史索引拉歌词
            try:
                from lib import history, lrc_export
                lyrics = ""
                for fid, song in history.search():
                    if song.get("filename") == audio_path.name:
                        lyrics = song.get("lyrics", "")
                        break
                if lyrics:
                    lrc_export.export_lrc(audio_path, lyrics, mode="even")
            except Exception as e:
                errors.append(f"lrc 生成失败: {e}")

        if lrc_path.exists():
            shutil.copy2(lrc_path, staging / "lyrics.lrc")
            included.append("lyrics.lrc")
        else:
            missing.append("lyrics (没历史/无歌词)")

    # 5. midi
    if include_midi:
        s += 1
        step(s, total_steps, "MIDI")
        midi_path = ROOT / "outputs" / "midi" / audio_path.stem / "melodic.mid"
        if not midi_path.exists():
            try:
                from lib import audio_to_midi
                r = audio_to_midi.quick_transcribe(
                    audio_path, mode="melodic",
                    with_bpm=False, with_markers=False,
                )
                if r["melodic"] and r["melodic"]["ok"]:
                    midi_path = ROOT / "outputs" / "midi" / audio_path.stem / "melodic.mid"
            except Exception as e:
                errors.append(f"midi 生成失败: {e}")

        if midi_path.exists():
            shutil.copy2(midi_path, staging / "melody.mid")
            included.append("melody.mid")
        else:
            missing.append("midi (basic-pitch 未装?)")

    # 6. metadata
    if include_metadata:
        s += 1
        step(s, total_steps, "metadata")
        try:
            from lib import history
            meta = {}
            for fid, song in history.search():
                if song.get("filename") == audio_path.name:
                    meta = song
                    break
            if meta:
                (staging / "metadata.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                included.append("metadata.json")
            else:
                missing.append("metadata (历史索引里没这首)")
        except Exception as e:
            errors.append(f"metadata 失败: {e}")

    # 打 zip
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in staging.iterdir():
            zf.write(f, arcname=f.name)

    shutil.rmtree(staging, ignore_errors=True)

    return {
        "ok": True,
        "zip_path": output_zip,
        "included": included,
        "missing": missing,
        "errors": errors,
        "size_mb": round(output_zip.stat().st_size / 1024 / 1024, 1),
    }
