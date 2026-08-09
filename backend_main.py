"""PyInstaller 入口壳。

interviewer.backend 内部用的是相对导入，被当作顶层脚本直接执行时没有父包。
这里以模块方式引入，让包结构成立。

另外承担代码沙盒的执行入口：打包后 sys.executable 就是本程序，
要跑候选人的 Python 代码只能从这里转发，且必须在引入后端之前完成，
否则子进程会去连数据库和音频设备。
"""

import sys

if __name__ == "__main__" and len(sys.argv) >= 3 and sys.argv[1] == "--exec-python":
    import runpy

    target = sys.argv[2]
    sys.argv = [target, *sys.argv[3:]]
    runpy.run_path(target, run_name="__main__")
    raise SystemExit(0)

from interviewer.backend import main

if __name__ == "__main__":
    raise SystemExit(main())
