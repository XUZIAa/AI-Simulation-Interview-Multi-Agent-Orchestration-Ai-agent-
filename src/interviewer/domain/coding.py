from __future__ import annotations

from pydantic import BaseModel, Field

# 只列真能跑起来的语言。Python 用 sidecar 自带的运行时，
# JavaScript 依赖系统 Node，取不到就明确报错而不是假装能跑。
CODING_LANGUAGES: tuple[str, ...] = ("python", "javascript")

MAX_OUTPUT_CHARS = 8000
RUN_TIMEOUT_MS = 6000


class CodingCase(BaseModel):
    """一条用例。走标准输入输出，不往用户代码里注入调用，判题只比字符串。"""

    input: str = ""
    expected: str = ""
    note: str = ""


class CodingChallenge(BaseModel):
    """一道完整编码题。与题库的口述题分开：那边只有题干，这里要能判题。"""

    title: str = ""
    statement: str = ""
    io_format: str = ""
    starter: dict[str, str] = Field(default_factory=dict)
    reference: dict[str, str] = Field(default_factory=dict)
    cases: list[CodingCase] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)

    def starter_for(self, language: str) -> str:
        return self.starter.get(language, "")

    def reference_for(self, language: str) -> str:
        return self.reference.get(language, "")


class RunOutcome(BaseModel):
    """一次自由运行的结果。ok 只代表进程正常退出，不代表答案对。"""

    ok: bool = False
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: int = 0
    timed_out: bool = False


class CaseOutcome(BaseModel):
    index: int
    passed: bool
    input: str = ""
    expected: str = ""
    actual: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False


class JudgeOutcome(BaseModel):
    passed: int = 0
    total: int = 0
    cases: list[CaseOutcome] = Field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return self.total > 0 and self.passed == self.total
