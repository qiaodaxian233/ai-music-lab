#!/usr/bin/env python3
"""自动后处理 watcher

监视 outputs/ 目录,新音频文件出现时自动:
1. 响度归一化到 -14 LUFS
2. (可选) 转 MP3 + 加 ID3 tag
3. 登记到历史索引

启动: python scripts/auto-postprocess.py
后台: nohup python scripts/auto-postprocess.py > postprocess.log 2>&1 &
停止: Ctrl+C 或 kill 对应 PID
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib import history, postprocess

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:
    print("❌ 需要 watchdog: pip install watchdog")
    sys.exit(1)


OUTPUTS_DIR = ROOT / "outputs"
AUDIO_EXTS = {".wav", ".mp3", ".flac"}

# 已处理过的 path 记录,防重复(同一个文件可能短时间多次事件)
processed: set[str] = set()


def should_skip(path: Path) -> bool:
    """跳过条件"""
    name = path.name
    if name.startswith("."):
        return True
    if path.suffix.lower() not in AUDIO_EXTS:
        return True
    # 跳过已经处理过的(避免无限循环)
    if "_normalized" in path.stem:
        return True
    if "_faded" in path.stem:
        return True
    if str(path) in processed:
        return True
    return False


def wait_for_stable(path: Path, timeout: float = 30.0) -> bool:
    """等文件大小稳定再处理(模型还在写)"""
    last_size = -1
    waited = 0.0
    while waited < timeout:
        try:
            current = path.stat().st_size
        except FileNotFoundError:
            return False
        if current > 0 and current == last_size:
            return True
        last_size = current
        time.sleep(1.0)
        waited += 1.0
    return False


def process(path: Path, args):
    if should_skip(path):
        return

    print(f"📥 新文件: {path.name}")
    processed.add(str(path))

    if not wait_for_stable(path):
        print(f"  ⚠ 文件未稳定,跳过")
        return

    try:
        report = postprocess.process_one(
            path,
            normalize=args.normalize,
            fade=args.fade,
            convert_mp3=args.mp3,
            title=path.stem,
            artist=args.artist,
            album=args.album,
            delete_intermediates=not args.keep_intermediates,
        )

        if report["errors"]:
            print(f"  ❌ 错误: {report['errors']}")
            return

        print(f"  ✓ 处理完成: {' → '.join(report['steps'])}")
        print(f"     输出: {Path(report['output']).name}")

        # 登记历史
        history.scan_and_update()

    except Exception as e:
        print(f"  ❌ 异常: {e}")


class Handler(FileSystemEventHandler):
    def __init__(self, args):
        self.args = args

    def on_created(self, event):
        if event.is_directory:
            return
        process(Path(event.src_path), self.args)

    def on_moved(self, event):
        # 有些工具是先写临时文件再 rename
        if event.is_directory:
            return
        process(Path(event.dest_path), self.args)


def main():
    parser = argparse.ArgumentParser(description="auto post-process watcher")
    parser.add_argument("--no-normalize", dest="normalize", action="store_false",
                        help="不做响度归一化")
    parser.add_argument("--fade", action="store_true", help="加淡入淡出")
    parser.add_argument("--no-mp3", dest="mp3", action="store_false",
                        help="不转 MP3 (保留 WAV)")
    parser.add_argument("--keep-intermediates", action="store_true",
                        help="保留中间文件(归一化前的 WAV 等)")
    parser.add_argument("--artist", default="AI", help="ID3 artist 字段")
    parser.add_argument("--album", default="ai-music-lab", help="ID3 album 字段")
    parser.add_argument("--scan-existing", action="store_true",
                        help="启动时先处理已存在的未归一化文件")
    args = parser.parse_args()

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"🎵 后处理 watcher 已启动")
    print(f"   监视: {OUTPUTS_DIR}")
    print(f"   归一化: {'✓' if args.normalize else '✗'}  "
          f"淡入淡出: {'✓' if args.fade else '✗'}  "
          f"转 MP3: {'✓' if args.mp3 else '✗'}")
    print(f"   Ctrl+C 退出")
    print()

    if args.scan_existing:
        print("📂 扫描已有文件...")
        for f in OUTPUTS_DIR.iterdir():
            if f.is_file():
                process(f, args)
        print()

    observer = Observer()
    observer.schedule(Handler(args), str(OUTPUTS_DIR), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 退出")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
