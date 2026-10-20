#!/usr/bin/env python3
"""构建 Tauri sidecar：PyInstaller 打包 chalkpress.ipc，输出到 src-tauri/binaries/。

用法：python packaging/build_sidecar.py [--dev]
--dev 模式以 chalkpress-core-dev 命名输出（开发用）；默认输出 chalkpress-core-<target-triple> 供 Tauri externalBin 使用。
"""
import argparse
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
MODEL_DIR = ROOT / "build" / "model"
OUT = ROOT / "src-tauri" / "binaries"


def target_triple(override: str | None = None) -> str:
    if override:
        return override
    out = subprocess.check_output(["rustc", "-vV"], text=True)
    return next(l.split(": ", 1)[1].strip() for l in out.splitlines()
                if l.startswith("host:"))


def ensure_model():
    if MODEL_DIR.is_dir() and any(MODEL_DIR.iterdir()):
        return
    print("下载 whisper-small 模型到 build/model ...", file=sys.stderr)
    from huggingface_hub import snapshot_download
    # HF 对 GitHub runner 共享 IP 匿名限流（429），偶发，重试即可过
    for attempt in (1, 2, 3):
        try:
            snapshot_download("Systran/faster-whisper-small", local_dir=str(MODEL_DIR))
            return
        except Exception as exc:
            if attempt == 3:
                raise
            wait = 30 * attempt
            print(f"模型下载失败（{exc}），{wait}s 后重试（{attempt}/3）", file=sys.stderr)
            time.sleep(wait)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", action="store_true")
    ap.add_argument("--triple", help="覆盖目标三元组（无 rustc 的宿主上交叉构建 sidecar 用）")
    args = ap.parse_args()
    ensure_model()
    OUT.mkdir(parents=True, exist_ok=True)
    collects = ["faster_whisper", "ctranslate2", "imageio_ffmpeg", "onnxruntime",
                "tokenizers", "av", "pypinyin"]
    # mlx-whisper 仅 macOS 安装（requirements 平台受限）：装了才收录，
    # 供 asr.best_backend() 在 Apple 芯片上自动选用 GPU 加速引擎
    if importlib.util.find_spec("mlx_whisper"):
        collects += ["mlx_whisper", "mlx"]
    sep = ";" if sys.platform == "win32" else ":"
    triple = target_triple(args.triple)
    # ipc.py 用相对导入（from .config import ...），不能作为顶层脚本打包；
    # 改打包一个以包路径导入的入口 stub
    work = ROOT / "build" / "pyi"
    work.mkdir(parents=True, exist_ok=True)
    stub = work / "_sidecar_entry.py"
    stub.write_text("from chalkpress.ipc import main\n\nmain()\n", encoding="utf-8")
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile",
        "--name", f"chalkpress-core-{triple}" if not args.dev else "chalkpress-core-dev",
        *[arg for pkg in collects for arg in ("--collect-all", pkg)],
        "--add-data", f"{MODEL_DIR}{sep}models/faster-whisper-small",
        "--distpath", str(OUT), "--workpath", str(work),
        "--specpath", str(work), "--paths", str(ROOT),
        str(stub),
    ], check=True, cwd=ROOT)
    # onefile：Tauri externalBin 要求单个可执行文件；启动解压稍慢是可接受的代价


if __name__ == "__main__":
    main()
