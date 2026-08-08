"""PyInstaller 入口壳。

interviewer.backend 内部用的是相对导入，被当作顶层脚本直接执行时没有父包。
这里以模块方式引入，让包结构成立。
"""

from interviewer.backend import main

if __name__ == "__main__":
    raise SystemExit(main())
