"""Nexus 分体式启动器：EXE 只做入口，业务代码放在外部 lib/app（仅 .pyc）。

PyInstaller 只分析本文件与第三方依赖；app 包通过 importlib 动态加载，
不会被塞进 EXE 的 PYZ 归档，避免 EXE 被一次性解包出全部业务逻辑。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

def _collect_dependencies() -> None:
    """仅供 PyInstaller 静态分析：导入构建时生成的依赖清单，运行时不调用。"""
    import bundle_imports  # noqa: F401


def _base() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def main() -> int:
    base = _base()
    lib = base / "lib"
    if lib.is_dir():
        sys.path.insert(0, str(lib))
    else:  # 开发模式：直接从仓库根目录加载源码
        sys.path.insert(0, str(base))
    module = importlib.import_module("app.main")
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
