from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

from pydantic import Field

from ..domain.coding import CodingCase, CodingChallenge
from ..llm import prompts
from ..llm.base import system, user
from ..llm.coerce import LooseModel
from ..llm.router import ROLE_ANALYST
from .base import Agent, trim

logger = logging.getLogger(__name__)

MIN_CASES = 2
MAX_CASES = 6


class _CaseRaw(LooseModel):
    input: str = ""
    expected: str = ""
    note: str = ""


class _ChallengeRaw(LooseModel):
    title: str = ""
    statement: str = ""
    io_format: str = ""
    starter_python: str = ""
    starter_javascript: str = ""
    reference_python: str = ""
    reference_javascript: str = ""
    cases: list[_CaseRaw] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)


class CodingComposer(Agent):
    """出一道能自动判题的编码题。

    与题库分开：题库的口述题只要题干，这里必须凑齐输入输出格式、
    起始代码、用例和参考答案，缺一样前端就没法判题。
    """

    role: ClassVar[str] = ROLE_ANALYST

    async def compose(
        self,
        *,
        skill: str,
        job_title: str,
        level_expectation: str,
        minutes: int,
        timeout_ms: int = 90000,
    ) -> CodingChallenge:
        raw = await asyncio.wait_for(
            self.client.structured(
                [
                    system(prompts.CODING_COMPOSE_SYSTEM),
                    user(
                        prompts.coding_compose_user_prompt(
                            skill=skill,
                            job_title=job_title,
                            level_expectation=level_expectation,
                            minutes=minutes,
                        )
                    ),
                ],
                _ChallengeRaw,
                temperature=0.4,
                max_tokens=2600,
            ),
            timeout=timeout_ms / 1000,
        )

        cases = [
            CodingCase(
                input=c.input.rstrip(),
                expected=c.expected.rstrip(),
                note=trim(c.note, 60),
            )
            for c in raw.cases
            if c.expected.strip()
        ][:MAX_CASES]

        return CodingChallenge(
            title=trim(raw.title, 60) or f"{skill} 编码题",
            statement=raw.statement.strip(),
            io_format=raw.io_format.strip(),
            starter={
                "python": raw.starter_python.strip(),
                "javascript": raw.starter_javascript.strip(),
            },
            reference={
                "python": raw.reference_python.strip(),
                "javascript": raw.reference_javascript.strip(),
            },
            cases=cases,
            hints=[trim(h, 80) for h in raw.hints if h.strip()][:3],
        )
