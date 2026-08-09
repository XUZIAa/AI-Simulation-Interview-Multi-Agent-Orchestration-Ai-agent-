from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path

from ..core.errors import ConfigError
from ..domain.coding import (
    MAX_OUTPUT_CHARS,
    RUN_TIMEOUT_MS,
    CaseOutcome,
    CodingCase,
    JudgeOutcome,
    RunOutcome,
)

logger = logging.getLogger(__name__)

_SUFFIX = {"python": ".py", "javascript": ".js"}

# 打包后 sys.executable 是 interviewer-backend.exe，直接执行会把整个后端
# 重新拉起来。约定这个开关让入口脚本转去执行用户代码。
EXEC_FLAG = "--exec-python"


def _python_cmd(path: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, EXEC_FLAG, str(path)]
    return [sys.executable, str(path)]


def _node_cmd(path: Path) -> list[str]:
    node = shutil.which("node")
    if not node:
        raise ConfigError("没找到 Node.js，无法运行 JavaScript。装好 Node 后重启应用，或改用 Python")
    return [node, str(path)]


def _command(language: str, path: Path) -> list[str]:
    if language == "python":
        return _python_cmd(path)
    if language == "javascript":
        return _node_cmd(path)
    raise ConfigError(f"不支持运行 {language}")


def _clip(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n…输出超过 {MAX_OUTPUT_CHARS} 字符，已截断"


async def run_source(
    *,
    language: str,
    source: str,
    stdin_text: str = "",
    timeout_ms: int = RUN_TIMEOUT_MS,
) -> RunOutcome:
    """在子进程里跑一段代码。超时强杀，输出截断，避免拖死后端。"""
    suffix = _SUFFIX.get(language)
    if suffix is None:
        raise ConfigError(f"不支持运行 {language}")

    with tempfile.TemporaryDirectory(prefix="interviewer-run-") as tmp:
        path = Path(tmp) / f"main{suffix}"
        path.write_text(source, encoding="utf-8")
        cmd = _command(language, path)

        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmp,
            )
        except OSError as exc:
            raise ConfigError(f"启动运行进程失败：{exc}") from exc

        try:
            out, err = await asyncio.wait_for(
                proc.communicate(stdin_text.encode("utf-8")),
                timeout=timeout_ms / 1000,
            )
        except TimeoutError:
            proc.kill()
            # 回收管道，否则子进程残留成僵尸
            await asyncio.gather(proc.wait(), return_exceptions=True)
            elapsed = int((time.monotonic() - started) * 1000)
            return RunOutcome(
                ok=False,
                stderr=f"运行超过 {timeout_ms / 1000:.0f} 秒被终止，检查是否死循环",
                exit_code=-1,
                duration_ms=elapsed,
                timed_out=True,
            )

        elapsed = int((time.monotonic() - started) * 1000)
        code = proc.returncode or 0
        return RunOutcome(
            ok=code == 0,
            stdout=_clip(out),
            stderr=_clip(err),
            exit_code=code,
            duration_ms=elapsed,
            timed_out=False,
        )


def _same(actual: str, expected: str) -> bool:
    """按行比较并忽略行尾空白，避免因为一个换行判错。"""
    a = [line.rstrip() for line in actual.strip().splitlines()]
    b = [line.rstrip() for line in expected.strip().splitlines()]
    return a == b


async def judge(
    *,
    language: str,
    source: str,
    cases: list[CodingCase],
    timeout_ms: int = RUN_TIMEOUT_MS,
) -> JudgeOutcome:
    """逐条跑用例。串行执行：并行会让超时判断互相干扰。"""
    outcomes: list[CaseOutcome] = []
    for index, case in enumerate(cases):
        result = await run_source(
            language=language,
            source=source,
            stdin_text=case.input,
            timeout_ms=timeout_ms,
        )
        passed = result.ok and _same(result.stdout, case.expected)
        outcomes.append(
            CaseOutcome(
                index=index,
                passed=passed,
                input=case.input,
                expected=case.expected,
                actual=result.stdout,
                stderr=result.stderr,
                duration_ms=result.duration_ms,
                timed_out=result.timed_out,
            )
        )
    return JudgeOutcome(
        passed=sum(1 for o in outcomes if o.passed),
        total=len(outcomes),
        cases=outcomes,
    )
