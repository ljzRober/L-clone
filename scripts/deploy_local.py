#!/usr/bin/env python3
"""一键本地部署 L-clone: 建 venv → 装依赖 → setup 向导 → doctor 自检 → 启动 web。

只部署后端服务(不碰 AI 工具前端的 skill/hooks/插件); 接入工具另跑 lclone integrate。

跨平台: Windows / macOS / Linux 通用(只要装了 Python 3.10+)。

用法:
  python scripts/deploy_local.py                  # 交互式: 选 provider + 填 key
  python scripts/deploy_local.py --offline        # 离线 dummy 模式(零依赖零 key)
  python scripts/deploy_local.py --mirror         # 国内用清华镜像装依赖
  python scripts/deploy_local.py --provider openai
  python scripts/deploy_local.py --no-serve       # 只配置不启动 web
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def run(args, **kw) -> None:
    print(f"\n$ {' '.join(str(a) for a in args)}")
    # 不捕获输出(stdin/stdout 直通), 保证 install 交互式提示可用
    subprocess.run([str(a) for a in args], check=True, **kw)


def ensure_venv() -> None:
    py = venv_python()
    if py.exists():
        print(f"✓ 虚拟环境已存在: {py}")
        return
    print("创建虚拟环境 .venv ...")
    run([sys.executable, "-m", "venv", str(VENV)])


def main() -> int:
    ap = argparse.ArgumentParser(description="一键本地部署 L-clone")
    ap.add_argument("--offline", action="store_true",
                    help="离线 dummy 模式(无需 API Key)")
    ap.add_argument("--mirror", action="store_true",
                    help="用清华镜像安装依赖")
    ap.add_argument("--provider", default=None,
                    help="模型服务商: deepseek/openai/siliconflow/zhipu/dummy")
    ap.add_argument("--no-serve", action="store_true",
                    help="只配置不启动 web")
    args = ap.parse_args()

    os.chdir(ROOT)
    ensure_venv()
    py = venv_python()

    # 1. 安装依赖
    pip = [py, "-m", "pip", "install", "-r", "requirements.txt"]
    if args.mirror:
        pip += ["-i", MIRROR]
    run(pip)

    # 2. 部署后端(setup): 生成 .env + init DB + 注册项目; 不碰前端 skill/hooks/插件
    setup = [py, "-m", "lclone", "setup"]
    if args.offline:
        setup += ["--provider", "dummy", "--yes"]
    elif args.provider:
        setup += ["--provider", args.provider]
    run(setup)

    # 3. 自检(离线跳过真调 LLM)
    doctor = [py, "-m", "lclone", "doctor"]
    if not args.offline:
        doctor.append("--check-llm")
    run(doctor)

    # 4. 启动 web
    if args.no_serve:
        print("\n✓ 配置完成(未启动 web)。手动启动: lclone serve start")
    else:
        run([py, "-m", "lclone", "serve", "start"])

    print("\n✓ 部署完成。")
    print("  Web 面板:   http://127.0.0.1:8000")
    print("  API 文档:   http://127.0.0.1:8000/docs")
    print("  添加项目:   lclone proj add <名> <仓库路径> --charter \"大方向\"")
    print("  后台管理:   lclone serve status/stop/restart")
    print("  接入 AI 工具(可选, 单独命令): lclone integrate [--target claude|codex|dsh|commit|all]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
