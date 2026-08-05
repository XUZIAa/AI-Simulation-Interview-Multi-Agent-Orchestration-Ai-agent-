"""PyInstaller 入口。使用绝对导入，便于打包器把 interviewer 作为顶层包收集。"""
from __future__ import annotations

import sys

from interviewer.ui.app import run

if __name__ == "__main__":
    sys.exit(run())
