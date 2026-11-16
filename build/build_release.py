"""构建 Nexus 发行产物：分体式绿色包 + NSIS 安装包 + 双语 README。

用法（Windows）：
    python build\\build_release.py             # 全量：PyInstaller + 字节码外置 + 安装包
    python build\\build_release.py --skip-build  # 复用已有 dist\\Nexus，只重做产物
"""
from __future__ import annotations

import argparse
import ast
import compileall
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from importlib.util import find_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "Nexus"
WORK = ROOT / "build" / "work"
SPEC = ROOT / "build" / "spec" / "Nexus.spec"
LAUNCHER = ROOT / "build" / "launcher.py"
APP = ROOT / "app"
RELEASE = ROOT / "release"
INSTALLER = ROOT / "build" / "installer"
MAKENSIS = Path(
    os.environ.get("MAKENSIS")
    or shutil.which("makensis")
    or r"C:\Program Files (x86)\NSIS\makensis.exe"
)


def version() -> str:
    text = (APP / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)', text)
    return m.group(1) if m else "0.0.0"


def log(message: str) -> None:
    print(f"\n=== {message} ===", flush=True)


def run(cmd: list[str]) -> None:
    print(">", subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def reset(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def generate_bundle_imports() -> None:
    """扫描 app 源码里的 import，生成仅供 PyInstaller 收集依赖的清单。

    EXE 只分析 launcher.py，而业务代码在外部 lib\\app，PyInstaller 看不到
    app 用到的标准库/第三方模块；这里把清单生成成一个空调用模块，让
    PyInstaller 把 sqlite3、cryptography 等一并打进 _internal。
    """
    names: set[str] = set()
    for path in APP.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level or not node.module:
                    continue
                names.add(node.module)
                # from PIL import ImageGrab 这类子模块也要收集，
                # 否则分体式打包会漏掉 PIL.ImageGrab，截图接口返回“缺少截图组件”。
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    candidate = f"{node.module}.{alias.name}"
                    try:
                        if find_spec(candidate) is not None:
                            names.add(candidate)
                    except (ImportError, ModuleNotFoundError, ValueError):
                        pass
    top = {name for name in names
           if name.split(".")[0] not in ("app", "__future__")}
    lines = [
        '"""构建时自动生成：仅供 PyInstaller 收集依赖，运行时不执行。"""',
        "",
        "",
        "def collect() -> None:",
    ]
    for name in sorted(top):
        lines.append(f"    import {name}  # noqa: F401")
    target = ROOT / "build" / "bundle_imports.py"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"依赖清单：{len(top)} 个模块 -> {target}", flush=True)


def write_version_info(ver: str) -> Path:
    """生成 PyInstaller 版本资源文件，让 Nexus.exe 的属性面板显示真实版本。"""
    parts = re.findall(r"\d+", ver)
    nums = [int(p) for p in parts[:4]] or [0]
    nums += [0] * (4 - len(nums))
    quad = ", ".join(str(n) for n in nums)
    target = ROOT / "build" / "spec" / "version_info.txt"
    target.write_text(
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        f"    filevers=({quad}),\n"
        f"    prodvers=({quad}),\n"
        "    mask=0x3f,\n"
        "    flags=0x0,\n"
        "    OS=0x40004,\n"
        "    fileType=0x1,\n"
        "    subtype=0x0,\n"
        "    date=(0, 0)\n"
        "  ),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        "      StringTable('080404B0', [\n"
        "        StringStruct('CompanyName', 'donghai'),\n"
        "        StringStruct('FileDescription', 'Nexus 桌面智能助手'),\n"
        f"        StringStruct('FileVersion', '{ver}'),\n"
        "        StringStruct('InternalName', 'Nexus'),\n"
        "        StringStruct('OriginalFilename', 'Nexus.exe'),\n"
        "        StringStruct('ProductName', 'Nexus'),\n"
        f"        StringStruct('ProductVersion', '{ver}'),\n"
        "        StringStruct('LegalCopyright', 'Copyright (c) 2026 donghai')])\n"
        "    ]),\n"
        "    VarFileInfo([VarStruct('Translation', [0x0804, 1200])])\n"
        "  ]\n"
        ")\n",
        encoding="utf-8",
    )
    print(f"版本资源：{ver} -> {target}", flush=True)
    return target


def build_pyinstaller() -> None:
    log("PyInstaller 分体式构建")
    write_version_info(version())
    generate_bundle_imports()
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(ROOT / "dist"), "--workpath", str(WORK),
         str(SPEC)])


def stage_bytecode() -> None:
    """把 app 源码编译成 .pyc 放到 lib/app，并删除 .py，确保不随包分发源码。"""
    log("外置业务字节码 lib\\app")
    lib_app = DIST / "lib" / "app"
    reset(DIST / "lib")
    shutil.copytree(
        APP, lib_app,
        ignore=shutil.ignore_patterns("__pycache__", "web", "*.pyc"),
    )
    ok = compileall.compile_dir(str(lib_app), legacy=True, force=True, quiet=1)
    if not ok:
        raise SystemExit("字节码编译失败")
    removed = 0
    for path in lib_app.rglob("*.py"):
        path.unlink()
        removed += 1
    pyc = list(lib_app.rglob("*.pyc"))
    if not pyc:
        raise SystemExit("lib\\app 中没有生成任何 .pyc")
    if list(lib_app.rglob("*.py")):
        raise SystemExit("lib\\app 中仍残留 .py 源码")
    print(f"已编译 {len(pyc)} 个 .pyc，删除 {removed} 个 .py", flush=True)


def render_readme(ver: str) -> None:
    log("生成双语 README.html")
    import markdown

    md_path = ROOT / "README.md"
    body = markdown.markdown(
        md_path.read_text(encoding="utf-8"),
        extensions=["tables", "fenced_code", "sane_lists"],
    )
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nexus {ver} - 使用说明 / Read Me</title>
<style>
  :root {{ color-scheme: light; }}
  body {{
    margin: 0; padding: 40px 24px 64px;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", system-ui, sans-serif;
    font-size: 15px; line-height: 1.75; color: #1f2328; background: #f6f8fb;
  }}
  main {{ max-width: 900px; margin: 0 auto; background: #fff; border-radius: 14px;
         padding: 40px 48px; box-shadow: 0 8px 32px rgba(20, 40, 80, .08); }}
  h1 {{ font-size: 30px; margin: 0 0 8px; color: #0b2a5b; }}
  h2 {{ font-size: 22px; margin: 36px 0 12px; padding-bottom: 8px;
        border-bottom: 1px solid #e6ebf2; color: #123a77; }}
  h3 {{ font-size: 17px; margin: 24px 0 8px; }}
  a {{ color: #1a63c9; }}
  code {{ font-family: Consolas, "Cascadia Mono", monospace; background: #f0f3f8;
          padding: 2px 6px; border-radius: 4px; font-size: 13px; }}
  pre {{ background: #0f172a; color: #e6edf7; padding: 16px 18px; border-radius: 10px;
         overflow: auto; }}
  pre code {{ background: none; color: inherit; padding: 0; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0 20px; }}
  th, td {{ border: 1px solid #e2e8f0; padding: 8px 12px; text-align: left; }}
  th {{ background: #f2f6fc; }}
  blockquote {{ margin: 12px 0; padding: 10px 16px; background: #f3f8ff;
                border-left: 4px solid #4b8bf4; color: #33475f; }}
  hr {{ border: none; border-top: 1px solid #e6ebf2; margin: 28px 0; }}
  .lang {{ display: inline-block; margin-right: 10px; }}
</style>
</head>
<body><main>
{body}
</main></body>
</html>
"""
    (ROOT / "README.html").write_text(html, encoding="utf-8")


def copy_docs() -> None:
    for name in ("README.md", "README.html"):
        shutil.copy2(ROOT / name, DIST / name)


def build_portable(ver: str) -> Path:
    """覆盖式更新绿色包目录，data 目录原地不动（绝不移动或删除用户数据）。"""
    log("生成绿色包")
    out_dir = RELEASE / f"Nexus-Portable-{ver}"
    out_dir.mkdir(parents=True, exist_ok=True)
    kept = sum(1 for p in (out_dir / "data").rglob("*") if p.is_file()) \
        if (out_dir / "data").exists() else 0
    for entry in list(out_dir.iterdir()):
        if entry.name == "data":
            continue
        try:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except OSError as e:
            raise SystemExit(f"无法更新绿色包，请先关闭正在运行的 Nexus：{e}")
    for src in DIST.iterdir():
        if src.name == "data":
            continue
        dest = out_dir / src.name
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
    (out_dir / "portable.flag").write_text("", encoding="utf-8")
    zip_path = RELEASE / f"Nexus-Portable-{ver}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(out_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(out_dir)
            if rel.parts and rel.parts[0] == "data":
                continue
            zf.write(path, path.relative_to(out_dir.parent))
    print(f"绿色包：{out_dir}\n压缩包：{zip_path}", flush=True)
    if kept:
        after = sum(1 for p in (out_dir / "data").rglob("*") if p.is_file())
        print(f"已保留用户数据：{after}/{kept} 个文件（配置、密钥、会话仍可继续使用）", flush=True)
    return zip_path


def build_installer(ver: str) -> Path:
    log("生成 NSIS 安装包")
    if not MAKENSIS.exists():
        raise SystemExit(f"找不到 NSIS：{MAKENSIS}")
    nsi = INSTALLER / "Nexus.nsi"
    data = nsi.read_bytes()
    if not data.startswith(b"\xef\xbb\xbf"):
        nsi.write_bytes(b"\xef\xbb\xbf" + data)
    stage = INSTALLER / "files"
    reset(stage)
    shutil.copytree(DIST, stage / "Nexus")
    out = RELEASE / f"Nexus-Setup-{ver}.exe"
    if out.exists():
        out.unlink()
    run([str(MAKENSIS), "/V2",
         f"/DSTAGE={stage}", f"/DVERSION={ver}", f"/DOUTFILE={out}",
         str(INSTALLER / "Nexus.nsi")])
    print(f"安装包：{out}", flush=True)
    return out


def write_checksums(paths: list[Path]) -> None:
    lines = []
    for path in paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    (RELEASE / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 Nexus 发行产物")
    parser.add_argument("--skip-build", action="store_true",
                        help="跳过 PyInstaller，复用 dist\\Nexus")
    args = parser.parse_args()
    ver = version()
    RELEASE.mkdir(parents=True, exist_ok=True)
    if not args.skip_build:
        build_pyinstaller()
    if not DIST.exists():
        raise SystemExit("dist\\Nexus 不存在，请先运行完整构建")
    stage_bytecode()
    render_readme(ver)
    copy_docs()
    zip_path = build_portable(ver)
    setup = build_installer(ver)
    write_checksums([setup, zip_path])
    log("完成")
    print(f"版本：{ver}\n安装包：{setup}\n绿色包：{zip_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
