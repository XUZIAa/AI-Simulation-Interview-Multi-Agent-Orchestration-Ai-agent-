# PyInstaller 配置：把 Python 后端打成独立可执行文件，供 Tauri 以 sidecar 方式分发。
from PyInstaller.utils.hooks import collect_submodules

hidden = [
    # uvicorn 的协议实现全靠运行时按名字加载，静态分析看不见
    *collect_submodules("uvicorn"),
    "anyio._backends._asyncio",
    "aiosqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "keyring.backends.Windows",
    "sounddevice",
    "_sounddevice_data",
]

a = Analysis(
    ["backend_main.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    # 界面由 Tauri 承担，后端不该拉进任何 GUI 库
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="interviewer-backend",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="interviewer-backend",
)
