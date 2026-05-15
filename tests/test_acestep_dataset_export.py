"""
tests/test_acestep_dataset_export.py — 验证 v0.5.7 导出逻辑

模拟:
  datasets/test/
    audio/song1.wav, song2.wav, song3.wav
    raw/song2.lrc (一个带 lrc,验 from_lrc)
    metadata.csv

期望输出:
  ACE-Step-1.5/datasets/test-acestep/
    song1.wav + song1.lyrics.txt + song1.caption.txt + song1.json
    song2.wav + song2.lyrics.txt(从 lrc 剥) + song2.caption.txt + song2.json
    song3.wav + ...
    _export_report.txt
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# 让 lib 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.acestep_dataset_export import export_to_acestep, _strip_lrc


def _make_fake_wav(p: Path):
    """造个最小合法 wav header(44 字节)+ 几帧静音。"""
    import struct
    sr = 44100
    n = 100  # 100 个 16-bit mono samples
    data = b"\x00\x00" * n
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + struct.pack("<H", 1)        # PCM
        + struct.pack("<H", 1)        # mono
        + struct.pack("<I", sr)
        + struct.pack("<I", sr * 2)
        + struct.pack("<H", 2)
        + struct.pack("<H", 16)
        + b"data"
        + struct.pack("<I", len(data))
    )
    p.write_bytes(header + data)


def _setup(tmpdir: Path):
    src = tmpdir / "datasets" / "test"
    (src / "audio").mkdir(parents=True)
    (src / "raw").mkdir()

    _make_fake_wav(src / "audio" / "song1.wav")
    _make_fake_wav(src / "audio" / "song2.wav")
    _make_fake_wav(src / "audio" / "song3.wav")

    # song2 配一个 .lrc
    (src / "raw" / "song2.lrc").write_text(
        "[ar:saya]\n"
        "[ti:test]\n"
        "[00:01.50]第一句歌词\n"
        "[00:05.20]第二句歌词\n"
        "[00:09.00]\n"  # 空行
        "[00:12.30]第三句歌词\n",
        encoding="utf-8",
    )

    (src / "metadata.csv").write_text(
        "filename,caption,bpm,key,duration\n"
        "song1.wav,\"solo vocal, mid-tempo, 92 bpm, key of C, indie folk\",92,C,180.5\n"
        "song2.wav,\"solo vocal, slow, 70 bpm, key of A minor, chinese\",70,Am,210.3\n"
        "song3.wav,\"solo vocal, upbeat, 120 bpm, key of G, pop\",120,G,165.0\n",
        encoding="utf-8",
    )

    ace = tmpdir / "ACE-Step-1.5"
    ace.mkdir()
    return src, ace


def test_export_empty_lyrics():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src, ace = _setup(td)

        out, n = export_to_acestep(
            source_dir=src,
            acestep_root=ace,
            lyrics_mode="empty",
            link_mode="copy",
        )

        assert n == 3, f"应导 3 首,实际 {n}"
        assert out == (ace / "datasets" / "test-acestep").resolve()

        for stem in ("song1", "song2", "song3"):
            assert (out / f"{stem}.wav").exists(), f"缺 {stem}.wav"
            assert (out / f"{stem}.lyrics.txt").exists(), f"缺 {stem}.lyrics.txt"
            assert (out / f"{stem}.caption.txt").exists(), f"缺 {stem}.caption.txt"
            assert (out / f"{stem}.json").exists(), f"缺 {stem}.json"

            # 空 lyrics
            assert (out / f"{stem}.lyrics.txt").read_text(encoding="utf-8") == ""

            # caption 完整
            cap = (out / f"{stem}.caption.txt").read_text(encoding="utf-8")
            assert "bpm" in cap

            # json 结构
            meta = json.loads((out / f"{stem}.json").read_text(encoding="utf-8"))
            assert meta["filename"] == f"{stem}.wav"
            assert meta["bpm"] is not None
            assert meta["key"] is not None
            assert meta["duration"] is not None

        # 检验报告
        report = (out / "_export_report.txt").read_text(encoding="utf-8")
        assert "exported: 3/3" in report
        print("✅ test_export_empty_lyrics passed")


def test_export_from_lrc():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src, ace = _setup(td)

        out, n = export_to_acestep(
            source_dir=src,
            acestep_root=ace,
            lyrics_mode="from_lrc",
            link_mode="copy",
        )

        assert n == 3

        # song1 没 lrc → 空
        assert (out / "song1.lyrics.txt").read_text(encoding="utf-8") == ""
        # song3 没 lrc → 空
        assert (out / "song3.lyrics.txt").read_text(encoding="utf-8") == ""

        # song2 有 lrc → 时间戳剥光、元数据剥光
        lyrics2 = (out / "song2.lyrics.txt").read_text(encoding="utf-8")
        assert "[" not in lyrics2, f"残留方括号: {lyrics2!r}"
        assert "ar:" not in lyrics2
        assert "第一句歌词" in lyrics2
        assert "第二句歌词" in lyrics2
        assert "第三句歌词" in lyrics2
        # 空行应被去掉
        assert "\n\n" not in lyrics2
        print("✅ test_export_from_lrc passed")


def test_safe_path_check():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src, ace = _setup(td)

        # 输出在 ACE 外面 → 应该拒
        outside = td / "outside_output"
        outside.mkdir()
        try:
            export_to_acestep(
                source_dir=src,
                acestep_root=ace,
                output_dir=outside,
            )
            raise AssertionError("应该抛 ValueError(safe_path)")
        except ValueError as e:
            assert "safe_path" in str(e) or "acestep_root" in str(e)
        print("✅ test_safe_path_check passed")


def test_overwrite():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src, ace = _setup(td)

        # 第一次成功
        out, _ = export_to_acestep(src, ace, lyrics_mode="empty")

        # 第二次不带 overwrite → 应该拒
        try:
            export_to_acestep(src, ace, lyrics_mode="empty")
            raise AssertionError("应该抛 FileExistsError")
        except FileExistsError:
            pass

        # 加 overwrite → 通
        out2, n2 = export_to_acestep(src, ace, lyrics_mode="empty", overwrite=True)
        assert out2 == out
        assert n2 == 3
        print("✅ test_overwrite passed")


def test_strip_lrc_unit():
    s = "[ar:saya]\n[ti:T]\n[00:01.50]hello\n[01:02.99]world\n[02:00]end\n"
    assert _strip_lrc(s) == "hello\nworld\nend"

    # 异常格式不崩
    assert _strip_lrc("") == ""
    assert _strip_lrc("[broken") == "[broken"
    print("✅ test_strip_lrc_unit passed")


def test_missing_audio_skipped():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src, ace = _setup(td)

        # 故意删一首
        (src / "audio" / "song2.wav").unlink()

        out, n = export_to_acestep(src, ace, lyrics_mode="empty")
        assert n == 2, f"应导 2 首,实际 {n}"

        # song2 不该出现
        assert not (out / "song2.wav").exists()
        assert not (out / "song2.lyrics.txt").exists()

        # 报告应该提到
        report = (out / "_export_report.txt").read_text(encoding="utf-8")
        assert "song2" in report
        assert "exported: 2/3" in report
        print("✅ test_missing_audio_skipped passed")


def test_hardlink_works_or_falls_back():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src, ace = _setup(td)

        out, n = export_to_acestep(src, ace, lyrics_mode="empty", link_mode="hardlink")
        assert n == 3
        # 文件都该存在(无论 hardlink 还是 fallback copy)
        for stem in ("song1", "song2", "song3"):
            assert (out / f"{stem}.wav").exists()
        print("✅ test_hardlink_works_or_falls_back passed")


def test_cli_invocation():
    """跑 CLI 模拟 unified-ui 之外的用法。"""
    import subprocess
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src, ace = _setup(td)

        mod = str(Path(__file__).resolve().parent.parent / "lib" / "acestep_dataset_export.py")
        r = subprocess.run(
            [sys.executable, mod, str(src),
             "--acestep-root", str(ace),
             "--lyrics-mode", "from_lrc",
             "--overwrite"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"CLI 退出 {r.returncode}\nSTDOUT:{r.stdout}\nSTDERR:{r.stderr}"
        assert "✅" in r.stdout
        print("✅ test_cli_invocation passed")


if __name__ == "__main__":
    test_strip_lrc_unit()
    test_export_empty_lyrics()
    test_export_from_lrc()
    test_safe_path_check()
    test_overwrite()
    test_missing_audio_skipped()
    test_hardlink_works_or_falls_back()
    test_cli_invocation()
    print("\n🎉 全部 8 个测试通过")
