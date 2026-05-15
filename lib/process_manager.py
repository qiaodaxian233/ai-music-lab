"""服务进程管理 (v0.5.3)

启停 + 监控三个常驻服务:
- ACE-Step UI (端口 7860, 调 ACE-Step-1.5/start_gradio_ui.bat / .sh)
- 统一控制台 (端口 7861, 调 scripts/unified-ui.py)
- 后处理 watcher (无端口, 调 scripts/auto-postprocess.py)

跨平台: Windows / Linux / Mac (Windows 用 cmd.exe 启 .bat,POSIX 直接 Python)
依赖: psutil (跨平台找子进程 + kill 进程树)
"""
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
RUNTIME.mkdir(parents=True, exist_ok=True)

IS_WINDOWS = sys.platform.startswith("win")


# ───────────────────────────────────────────────
# Service 定义
# ───────────────────────────────────────────────

@dataclass
class Service:
    key: str             # 唯一标识 (acestep / unified / watcher)
    name: str            # 显示名
    port: Optional[int]  # 监听端口 (无端口的服务传 None)
    cmd_windows: list[str]
    cmd_posix: list[str]
    cwd: Path = field(default_factory=lambda: ROOT)
    log_lines_tail: int = 60

    @property
    def cmd(self) -> list[str]:
        return self.cmd_windows if IS_WINDOWS else self.cmd_posix

    @property
    def pid_file(self) -> Path:
        return RUNTIME / f"{self.key}.pid"

    @property
    def log_file(self) -> Path:
        return RUNTIME / f"{self.key}.log"


# 三个内置服务定义
DEFAULT_SERVICES = [
    Service(
        key="acestep",
        name="🎹 ACE-Step 主 UI",
        port=7860,
        cmd_windows=["cmd", "/c", "start_gradio_ui.bat"],
        cmd_posix=["bash", "start_gradio_ui.sh"],
        cwd=ROOT / "ACE-Step-1.5",
    ),
    Service(
        key="unified",
        name="🎛 统一控制台",
        port=7861,
        cmd_windows=[sys.executable, "scripts/unified-ui.py"],
        cmd_posix=[sys.executable, "scripts/unified-ui.py"],
        cwd=ROOT,
    ),
    Service(
        key="watcher",
        name="🔄 后处理 watcher",
        port=None,
        cmd_windows=[sys.executable, "scripts/auto-postprocess.py"],
        cmd_posix=[sys.executable, "scripts/auto-postprocess.py"],
        cwd=ROOT,
    ),
]


def get_service(key: str) -> Optional[Service]:
    for s in DEFAULT_SERVICES:
        if s.key == key:
            return s
    return None


# ───────────────────────────────────────────────
# 进程检测 (psutil 优先,无 psutil 退化)
# ───────────────────────────────────────────────

def _have_psutil() -> bool:
    try:
        import psutil  # noqa: F401
        return True
    except ImportError:
        return False


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if _have_psutil():
        import psutil
        return psutil.pid_exists(pid)
    # 退化: signal 0
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def port_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    if not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def kill_tree(pid: int) -> bool:
    """kill 整个进程树。用 psutil 最稳。"""
    if not pid_alive(pid):
        return False

    if _have_psutil():
        import psutil
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for c in children:
                try:
                    c.terminate()
                except psutil.NoSuchProcess:
                    pass
            try:
                parent.terminate()
            except psutil.NoSuchProcess:
                pass
            # 等 3s 优雅退出
            gone, alive = psutil.wait_procs([parent] + children, timeout=3)
            for p in alive:
                try:
                    p.kill()
                except psutil.NoSuchProcess:
                    pass
            return True
        except psutil.NoSuchProcess:
            return False

    # 退化: 单纯 kill
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, check=False)
        else:
            os.kill(pid, 15)
            time.sleep(1)
            if pid_alive(pid):
                os.kill(pid, 9)
        return True
    except Exception:
        return False


# ───────────────────────────────────────────────
# 启 / 停 / 状态
# ───────────────────────────────────────────────

def start_service(svc: Service) -> dict:
    """启动一个服务。返回 {ok, pid, error}"""
    # 已经在跑?
    st = status(svc)
    if st["running"]:
        return {"ok": False, "pid": st["pid"], "error": "已经在跑了"}

    if not svc.cwd.exists():
        return {"ok": False, "pid": None, "error": f"工作目录不存在: {svc.cwd}"}

    # 日志重定向
    log_fp = open(svc.log_file, "a", encoding="utf-8", errors="replace")
    log_fp.write(f"\n\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 {svc.name} =====\n")
    log_fp.flush()

    # 启动 flags
    kwargs = dict(
        cwd=str(svc.cwd),
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    if IS_WINDOWS:
        # CREATE_NO_WINDOW (0x08000000) 隐藏窗口
        kwargs["creationflags"] = 0x08000000
    else:
        kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(svc.cmd, **kwargs)
    except Exception as e:
        log_fp.close()
        return {"ok": False, "pid": None, "error": f"启动失败: {e}"}

    svc.pid_file.write_text(str(proc.pid), encoding="utf-8")
    return {"ok": True, "pid": proc.pid, "error": None}


def stop_service(svc: Service) -> dict:
    """停止一个服务。返回 {ok, was_running, error}"""
    pid = read_pid(svc)
    if pid is None or not pid_alive(pid):
        # PID 文件没了/PID 死了,但端口可能被孤儿 Python 占
        if svc.port and port_listening(svc.port):
            # 找占端口的进程 kill
            if _have_psutil():
                import psutil
                for c in psutil.net_connections(kind="inet"):
                    if (c.laddr and c.laddr.port == svc.port
                            and c.status == "LISTEN" and c.pid):
                        kill_tree(c.pid)
                        break
                svc.pid_file.unlink(missing_ok=True)
                return {"ok": True, "was_running": True, "error": None}
        svc.pid_file.unlink(missing_ok=True)
        return {"ok": True, "was_running": False, "error": None}

    ok = kill_tree(pid)
    svc.pid_file.unlink(missing_ok=True)
    return {"ok": ok, "was_running": True, "error": None if ok else "kill 失败"}


def read_pid(svc: Service) -> Optional[int]:
    if not svc.pid_file.exists():
        return None
    try:
        return int(svc.pid_file.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def status(svc: Service) -> dict:
    """{running, pid, port_listening, started_at, log_tail, summary}"""
    pid = read_pid(svc)
    alive = pid is not None and pid_alive(pid)
    listening = port_listening(svc.port) if svc.port else None

    started_at = None
    if svc.pid_file.exists():
        try:
            started_at = svc.pid_file.stat().st_mtime
        except OSError:
            pass

    # 运行判定: PID 还活着 (有端口的话端口听才算"完全 ready")
    if svc.port is None:
        running = alive
        ready = alive
    else:
        running = alive or listening
        ready = alive and listening

    log_tail = read_log_tail(svc)

    if ready:
        summary = "🟢 运行中"
    elif running:
        summary = "🟡 启动中 (端口未通)"
    else:
        summary = "🔴 已停"

    return {
        "key": svc.key,
        "name": svc.name,
        "port": svc.port,
        "running": running,
        "ready": ready,
        "pid": pid if alive else None,
        "port_listening": listening,
        "started_at": started_at,
        "log_tail": log_tail,
        "summary": summary,
    }


def read_log_tail(svc: Service, n: Optional[int] = None) -> str:
    n = n or svc.log_lines_tail
    if not svc.log_file.exists():
        return "(日志为空)"
    try:
        # 简单尾读
        with open(svc.log_file, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 32768)  # 读最后 32K
            f.seek(-chunk, 2)
            data = f.read().decode("utf-8", errors="replace")
        lines = data.splitlines()
        return "\n".join(lines[-n:])
    except Exception as e:
        return f"(读日志失败: {e})"


def clear_log(svc: Service) -> bool:
    try:
        svc.log_file.write_text("", encoding="utf-8")
        return True
    except Exception:
        return False


# ───────────────────────────────────────────────
# 系统信息
# ───────────────────────────────────────────────

def system_info() -> dict:
    info = {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "cwd": str(ROOT),
        "ace_step_installed": (ROOT / "ACE-Step-1.5").exists(),
        "outputs_size_gb": _dir_size_gb(ROOT / "outputs"),
        "datasets_size_gb": _dir_size_gb(ROOT / "datasets"),
        "loras_count": _count_lora_files(),
    }

    # GPU (用 nvidia-smi)
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = [x.strip() for x in r.stdout.strip().split(",")]
            if len(parts) >= 5:
                info["gpu"] = {
                    "name": parts[0],
                    "total_mb": int(parts[1]),
                    "used_mb": int(parts[2]),
                    "free_mb": int(parts[3]),
                    "util_pct": int(parts[4]),
                }
        else:
            info["gpu"] = None
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        info["gpu"] = None

    # 总磁盘 (outputs 所在卷)
    try:
        import shutil
        total, used, free = shutil.disk_usage(str(ROOT))
        info["disk_total_gb"] = round(total / 1024**3, 1)
        info["disk_free_gb"] = round(free / 1024**3, 1)
    except Exception:
        pass

    return info


def _dir_size_gb(p: Path) -> float:
    if not p.exists():
        return 0.0
    total = 0
    try:
        for f in p.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except (OSError, PermissionError):
        pass
    return round(total / 1024**3, 2)


def _count_lora_files() -> int:
    p = ROOT / "loras"
    if not p.exists():
        return 0
    return sum(1 for f in p.iterdir()
               if f.is_file() and f.suffix in (".safetensors", ".bin", ".pt", ".ckpt"))


def recent_outputs(limit: int = 10) -> list[dict]:
    """outputs/ 下最近改动的 N 个文件"""
    out = ROOT / "outputs"
    if not out.exists():
        return []
    files = []
    for f in out.rglob("*"):
        if f.is_file() and not f.name.startswith("."):
            try:
                files.append({
                    "path": str(f.relative_to(ROOT)),
                    "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
                    "mtime": f.stat().st_mtime,
                })
            except OSError:
                continue
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return files[:limit]
