# -*- mode: python ; coding: utf-8 -*-
"""打包配置。生成 dist/AI模拟面试/ 目录，内含可执行文件与全部依赖。

构建：uv run pyinstaller interviewer.spec --noconfirm
"""
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

binaries = []
datas = []
hiddenimports = []

# sounddevice 自带的 PortAudio 动态库必须一起带走，否则运行期找不到音频后端
binaries += collect_dynamic_libs("sounddevice")
datas += collect_data_files("sounddevice")

# pdfplumber 依赖 pdfminer.six 的字符映射数据文件
datas += collect_data_files("pdfminer")

# keyring 的后端通过入口点动态发现，Windows 凭据库后端要显式带上
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += ["win32ctypes.core", "win32ctypes.pywin32"]

# 音视频与图像模块不会被静态分析捕获
hiddenimports += ["PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSvg"]

# SQLAlchemy 按字符串懒加载 DBAPI 驱动，aiosqlite 及其 sqlite 方言必须显式带上
hiddenimports += collect_submodules("aiosqlite")
hiddenimports += ["sqlalchemy.dialects.sqlite.aiosqlite", "greenlet"]

# 兜底：把应用自身所有子模块显式纳入，避免任何动态导入被漏
hiddenimports += collect_submodules("interviewer")

a = Analysis(
    ["launch.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQuick3D",
        "PySide6.Qt3DCore",
        "PySide6.QtDesigner",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    # 必须用 ASCII 文件名：非 ASCII 的 exe 名会让引导器在 CRT 层触发非法参数而崩溃。
    # 界面标题与全部文案仍为中文，用户看到的是「AI 模拟面试」。
    name="Interviewer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Interviewer",
)
