"""
lib/acestep_dataset_export.py — v0.5.7

把 ai-music-lab 的 datasets/<name>/ (metadata.csv + audio/) 转成
ACE-Step "数据集构建" Tab 期望的 sidecar 格式 + 放到 ACE-Step 内部目录,
绕过 ACE-Step 的 safe_path 检查。

ACE-Step 训练对每个音频要 3 个 sidecar 文件:
    <stem>.wav            音频本体
    <stem>.lyrics.txt     歌词(纯文本,不带时间戳)。训人声 LoRA 推荐填,训风格 LoRA 可空
    <stem>.caption.txt    流派/音色/情绪描述,1 行
    <stem>.json           元数据(bpm/key/duration)

路径限制:ACE-Step 拒绝外部路径,所以默认把输出写到 ACE-Step-1.5/datasets/<name>-acestep/ 里。

API:
    from lib.acestep_dataset_export import export_to_acestep
    out_dir, n = export_to_acestep(
        source_dir='datasets/saya',
        acestep_root='ACE-Step-1.5',
        lyrics_mode='from_lrc',   # 'empty' | 'from_caption' | 'from_lrc'
        link_mode='copy',         # 'copy' | 'hardlink' | 'symlink'
        overwrite=False,
    )
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Tuple, Optional, Union

PathLike = Union[str, Path]

AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus"}


def export_to_acestep(
    source_dir: PathLike,
    acestep_root: PathLike = "ACE-Step-1.5",
    output_dir: Optional[PathLike] = None,
    lyrics_mode: str = "empty",
    link_mode: str = "copy",
    overwrite: bool = False,
    strict_safe_path: bool = True,
) -> Tuple[Path, int]:
    """
    把 source_dir(含 metadata.csv + audio/)导出到 ACE-Step sidecar 格式。

    Args:
        source_dir: 形如 datasets/saya/
        acestep_root: ACE-Step 安装根(.../ACE-Step-1.5/)
        output_dir: 输出目录。默认 <acestep_root>/datasets/<source_name>-acestep/
        lyrics_mode:
            'empty'        每首给空 lyrics.txt(训纯音色/风格 LoRA 用)
            'from_caption' 拿 caption 当 lyrics 占位(不推荐,只是兜底)
            'from_lrc'     读 source_dir/raw/<stem>.lrc 并剥时间戳,无 lrc 则留空
        link_mode:
            'copy'      shutil.copy2(默认,最稳)
            'hardlink'  os.link(零拷贝,要求同盘 NTFS/ext4)
            'symlink'   软链(Win 需开发者模式,可能被 ACE-Step 拒)
        overwrite: 若输出目录非空,True 清空重写;False 抛 FileExistsError
        strict_safe_path: True 强制输出在 acestep_root 内(否则 ACE-Step 会 reject)

    Returns:
        (output_dir 绝对路径, 成功导出的音频条数)
    """
    if lyrics_mode not in ("empty", "from_caption", "from_lrc"):
        raise ValueError(f"lyrics_mode 必须是 empty/from_caption/from_lrc,收到 {lyrics_mode!r}")
    if link_mode not in ("copy", "hardlink", "symlink"):
        raise ValueError(f"link_mode 必须是 copy/hardlink/symlink,收到 {link_mode!r}")

    source = Path(source_dir).resolve()
    csv_path = source / "metadata.csv"
    audio_dir = source / "audio"
    raw_dir = source / "raw"

    if not csv_path.exists():
        raise FileNotFoundError(f"找不到 metadata.csv: {csv_path}")
    if not audio_dir.exists() and not raw_dir.exists():
        raise FileNotFoundError(f"audio/ 或 raw/ 至少要有一个: {source}")

    ace_root = Path(acestep_root).resolve()
    if strict_safe_path and not ace_root.exists():
        raise FileNotFoundError(
            f"acestep_root 不存在: {ace_root}。如果只是要离线导出测试,传 strict_safe_path=False。"
        )

    if output_dir is None:
        if not ace_root.exists():
            raise FileNotFoundError(
                f"自动定位 output_dir 需要 acestep_root 存在,但 {ace_root} 不存在。"
            )
        output_dir = ace_root / "datasets" / f"{source.name}-acestep"
    out = Path(output_dir).resolve()

    if strict_safe_path and ace_root.exists():
        try:
            out.relative_to(ace_root)
        except ValueError:
            raise ValueError(
                f"输出目录 {out} 不在 acestep_root {ace_root} 内,"
                f"ACE-Step 的 safe_path 检查会拒。"
                f"要么把 output_dir 改到 ace_root 内,要么 strict_safe_path=False。"
            )

    # 准备输出目录
    if out.exists() and any(out.iterdir()):
        if not overwrite:
            raise FileExistsError(
                f"{out} 已存在且非空。传 overwrite=True 覆盖,或先手动删掉。"
            )
        # 清空
        for child in out.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    out.mkdir(parents=True, exist_ok=True)

    # 读 metadata.csv
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        raise ValueError(f"metadata.csv 为空: {csv_path}")

    n_exported = 0
    warnings = []

    for row in rows:
        filename = (row.get("filename") or row.get("file") or "").strip()
        if not filename:
            warnings.append(f"行缺 filename 列,跳过: {row}")
            continue

        # 找音频源(优先 audio/,fallback raw/)
        candidates = [audio_dir / filename, raw_dir / filename]
        src_audio = next((p for p in candidates if p.exists()), None)
        if src_audio is None:
            warnings.append(f"找不到音频文件,跳过: {filename}")
            continue

        if src_audio.suffix.lower() not in AUDIO_EXTS:
            warnings.append(f"非音频后缀,跳过: {filename}")
            continue

        stem = src_audio.stem
        dst_audio = out / src_audio.name

        # 放音频
        if dst_audio.exists():
            dst_audio.unlink()
        try:
            if link_mode == "copy":
                shutil.copy2(src_audio, dst_audio)
            elif link_mode == "hardlink":
                try:
                    os.link(src_audio, dst_audio)
                except (OSError, NotImplementedError) as e:
                    warnings.append(f"hardlink 失败({e}),降级 copy: {filename}")
                    shutil.copy2(src_audio, dst_audio)
            elif link_mode == "symlink":
                try:
                    os.symlink(src_audio, dst_audio)
                except (OSError, NotImplementedError) as e:
                    warnings.append(f"symlink 失败({e}),降级 copy: {filename}")
                    shutil.copy2(src_audio, dst_audio)
        except Exception as e:
            warnings.append(f"放置音频失败({e}),跳过: {filename}")
            continue

        # caption.txt
        caption = (row.get("caption") or "").strip()
        (out / f"{stem}.caption.txt").write_text(caption, encoding="utf-8")

        # lyrics.txt
        lyrics_text = _build_lyrics(
            stem=stem,
            row_caption=caption,
            lyrics_mode=lyrics_mode,
            source=source,
            src_audio=src_audio,
        )
        (out / f"{stem}.lyrics.txt").write_text(lyrics_text, encoding="utf-8")

        # <stem>.json
        meta = _build_meta(row, src_audio.name)
        (out / f"{stem}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        n_exported += 1

    # 写一个 _export_report.txt(给用户查问题用)
    report_lines = [
        f"source: {source}",
        f"output: {out}",
        f"exported: {n_exported}/{len(rows)}",
        f"lyrics_mode: {lyrics_mode}",
        f"link_mode: {link_mode}",
    ]
    if warnings:
        report_lines.append("")
        report_lines.append("warnings:")
        report_lines.extend(f"  - {w}" for w in warnings)
    (out / "_export_report.txt").write_text("\n".join(report_lines), encoding="utf-8")

    return out, n_exported


def _build_lyrics(
    stem: str,
    row_caption: str,
    lyrics_mode: str,
    source: Path,
    src_audio: Path,
) -> str:
    if lyrics_mode == "empty":
        return ""
    if lyrics_mode == "from_caption":
        return row_caption
    if lyrics_mode == "from_lrc":
        # 优先 datasets/<name>/lyrics/<stem>.lrc → raw/<stem>.lrc → 音频同名.lrc → 音频同名.txt
        candidates = [
            source / "lyrics" / f"{stem}.lrc",
            source / "raw" / f"{stem}.lrc",
            src_audio.with_suffix(".lrc"),
            source / "lyrics" / f"{stem}.txt",
            src_audio.with_suffix(".txt"),
        ]
        for c in candidates:
            if c.exists():
                txt = c.read_text(encoding="utf-8", errors="ignore")
                if c.suffix.lower() == ".lrc":
                    return _strip_lrc(txt)
                return txt.strip()
        return ""
    return ""


_LRC_TS = re.compile(r"\[\d{1,2}:\d{2}(?:[.:]\d+)?\]")
_LRC_META = re.compile(r"^\[(?:ar|ti|al|by|offset|length|re|ve|au|hash):.*\]$", re.IGNORECASE)


def _strip_lrc(lrc: str) -> str:
    out = []
    for line in lrc.splitlines():
        s = line.strip()
        if not s:
            continue
        if _LRC_META.match(s):
            continue
        s = _LRC_TS.sub("", s).strip()
        if s:
            out.append(s)
    return "\n".join(out)


def _build_meta(row: dict, filename: str) -> dict:
    def _f(v):
        if v in (None, "", "None"):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _s(v):
        if v in (None, "None"):
            return None
        s = str(v).strip()
        return s or None

    return {
        "filename": filename,
        "bpm": _f(row.get("bpm") or row.get("BPM")),
        "key": _s(row.get("key")),
        "duration": _f(row.get("duration")),
        "caption": _s(row.get("caption")) or "",
    }


# ─── CLI ───

def _main():
    import argparse
    p = argparse.ArgumentParser(
        description="导出 ai-music-lab 数据集到 ACE-Step sidecar 格式"
    )
    p.add_argument("source", help="源数据集目录(含 metadata.csv + audio/)")
    p.add_argument("--acestep-root", default="ACE-Step-1.5",
                   help="ACE-Step 安装根(默认 ACE-Step-1.5)")
    p.add_argument("--output", default=None,
                   help="输出目录(默认 <acestep-root>/datasets/<name>-acestep/)")
    p.add_argument("--lyrics-mode", choices=["empty", "from_caption", "from_lrc"],
                   default="empty")
    p.add_argument("--link-mode", choices=["copy", "hardlink", "symlink"],
                   default="copy")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--no-strict-safe-path", action="store_true",
                   help="跳过 ACE-Step 内部路径检查(仅离线测试用)")
    args = p.parse_args()

    try:
        out, n = export_to_acestep(
            source_dir=args.source,
            acestep_root=args.acestep_root,
            output_dir=args.output,
            lyrics_mode=args.lyrics_mode,
            link_mode=args.link_mode,
            overwrite=args.overwrite,
            strict_safe_path=not args.no_strict_safe_path,
        )
    except Exception as e:
        print(f"❌ 导出失败: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"✅ 导出完成: {n} 首")
    print(f"📁 输出: {out}")
    print(f"📄 ACE-Step 数据集构建 Tab 里填: {out}")


if __name__ == "__main__":
    _main()
