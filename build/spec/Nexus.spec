# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

_CONSOLE = bool(os.environ.get("NEXUS_CONSOLE"))
_NAME = "NexusDebug" if _CONSOLE else "Nexus"

# PyInstaller 在 spec 命名空间里注入 SPECPATH（本文件所在目录）。
# 从 build/spec 回到仓库根目录，保证换机器、换盘符也能直接构建。
_SPEC_DIR = globals().get("SPECPATH") or os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(_SPEC_DIR, "..", ".."))

hiddenimports = ['uiautomation', 'comtypes.gen', 'tkinter', '_tkinter', 'tkinter.constants',
                 'webview.platforms.winforms', 'pystray._win32',
                 'cryptography.hazmat.primitives.ciphers.aead']
hiddenimports += collect_submodules('uiautomation')

datas = [(os.path.join(ROOT, 'app', 'web'), 'app/web')]
binaries = []
for pkg in ('sherpa_onnx', 'sounddevice', '_sounddevice_data', 'winpty'):
    pkg_datas, pkg_binaries, pkg_imports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_imports

# 办公文档依赖：只收模板等数据文件，不要 collect_all（会扫到 pandas/表提取，
# 进而把 matplotlib / torch 整条依赖链拖进包里）。
for pkg in ('docx', 'pptx', 'openpyxl'):
    datas += collect_data_files(pkg)

# PDF：pypdfium2 依赖包内的 pdfium.dll，必须显式收集二进制。
_pdfium_datas, _pdfium_binaries, _pdfium_imports = collect_all('pypdfium2_raw')
datas += _pdfium_datas
binaries += _pdfium_binaries
hiddenimports += _pdfium_imports + ['pypdfium2', 'pypdfium2_raw']


a = Analysis(
    [os.path.join(ROOT, 'build', 'launcher.py')],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pandas', 'matplotlib', 'scipy', 'torch', 'torchvision', 'tensorflow',
        'triton', 'IPython', 'pygments', 'jedi', 'parso', 'nbformat',
        'nbconvert', 'jupyter', 'jupyter_client', 'jupyter_core', 'notebook',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=_CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'app', 'web', 'assets', 'nexus.ico'),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=_NAME,
)
