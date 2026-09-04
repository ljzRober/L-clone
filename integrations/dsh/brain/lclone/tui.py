"""终端单选菜单: 方向键选择 + 回车确认。

优先用 questionary(第三方, 基于 prompt_toolkit, 渲染稳定, 跨平台)。
未安装时自动用 `python -m pip install questionary` 补装(避开 pip.exe 启动器移动失效的问题);
补装失败或渲染异常时, 回退为「输入序号」(零依赖兜底)。
"""

from __future__ import annotations

import subprocess
import sys
from typing import List


def _numbered(options: List[str], title: str, default: int) -> str:
    """回退路径: 输入序号。"""
    if title:
        print(title)
    for i, opt in enumerate(options, 1):
        tag = "  ← 默认" if i - 1 == default else ""
        print(f"  {i}) {opt}{tag}")
    n = len(options)
    while True:
        v = input(f"选序号 [{default + 1}]: ").strip() or str(default + 1)
        if v.isdigit() and 1 <= int(v) <= n:
            return options[int(v) - 1]
        print(f"  无效, 请输入 1~{n} 的序号")


def _load_questionary():
    """返回 questionary 模块; 未安装时自动补装, 失败返回 None。"""
    try:
        import questionary
        return questionary
    except ImportError:
        pass

    try:
        print("检测到 questionary 未安装, 正在自动补装(方向键菜单依赖, 仅首次需要)...")
        # 用 `python -m pip` 而不是 pip.exe: 后者在 venv 被移动/改名后会失效
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "questionary"],
            check=False,
            timeout=180,
        )
        import questionary
        return questionary
    except Exception:
        return None


def select_one(options: List[str], title: str = "", default: int = 0) -> str:
    """单选菜单: 方向键选择 + 回车确认; 回退输入序号。返回选中的选项。"""
    if not options:
        return ""
    q = _load_questionary()
    if q is not None:
        try:
            choice = q.select(
                title or "请选择:",
                choices=options,
                default=options[default],
            ).ask()
        except Exception:
            # questionary 渲染失败(极端终端环境)时回退
            return _numbered(options, title, default)
        return choice if choice is not None else options[default]
    return _numbered(options, title, default)
