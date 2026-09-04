"""Web 服务管理: start / stop / status / restart (后台常驻)。

用法:
  lclone serve start    后台启动 web (脱离当前进程, 日志 lclone-web.log)
  lclone serve stop     停止
  lclone serve status   查看状态
  lclone serve restart  重启
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from . import config

_ROOT = Path(__file__).resolve().parent.parent
PIDFILE = _ROOT / "lclone-web.pid"
LOGFILE = _ROOT / "lclone-web.log"


def _port() -> int:
    return config.get_int("BRAIN_PORT", 8000)


def _host() -> str:
    return config.get("BRAIN_HOST") or "127.0.0.1"


def is_running() -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        r = s.connect_ex(("127.0.0.1", _port()))
        s.close()
        return r == 0
    except Exception:
        return False


def _read_pid():
    if not PIDFILE.exists():
        return None
    try:
        return int(PIDFILE.read_text().strip())
    except (ValueError, OSError):
        return None


def start() -> str:
    if is_running():
        return f"web 已在运行 (http://127.0.0.1:{_port()})"
    logf = open(LOGFILE, "a")
    proc = subprocess.Popen(
        [sys.executable, "-m", "lclone", "web", "--host", _host(), "--port", str(_port())],
        cwd=str(_ROOT), stdout=logf, stderr=subprocess.STDOUT,
        start_new_session=True,  # 脱离父进程 (setsid), 关闭终端也不死
    )
    PIDFILE.write_text(str(proc.pid))
    time.sleep(1.5)
    if is_running():
        return f"web 已启动 (PID {proc.pid}, http://127.0.0.1:{_port()}, 日志 {LOGFILE})"
    return f"启动可能失败, 看日志 {LOGFILE}"


def stop() -> str:
    killed = False
    pid = _read_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            killed = True
        except ProcessLookupError:
            pass
    # 兜底: 按端口杀 (处理 pidfile 过期的情况)
    try:
        out = subprocess.run(
            ["lsof", "-ti", f":{_port()}"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        for p in out.splitlines():
            try:
                os.kill(int(p), signal.SIGKILL)
                killed = True
            except (ValueError, ProcessLookupError):
                pass
    except Exception:
        pass
    if PIDFILE.exists():
        PIDFILE.unlink()
    time.sleep(0.5)
    return "web 已停止" if not is_running() else "停止失败 (可能还在优雅退出, 稍等重试)"


def status() -> str:
    if is_running():
        pid = _read_pid()
        return f"web 运行中 (http://127.0.0.1:{_port()}" + (f", PID {pid})" if pid else ")")
    return f"web 未运行 (端口 {_port()})"


def restart() -> str:
    msg = stop() + "\n" + start()
    return msg
