from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

from pydantic import BaseModel, Field

from ..core.types import StarElement
from ..llm import prompts
from ..llm.base import system, user
from ..llm.coerce import LooseModel
from ..llm.router import ROLE_ASSIST, ROLE_DIRECTOR
from .base import Agent, clamp, trim

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# STAR 完整度
# ---------------------------------------------------------------------------


class StarVerdict(BaseModel):
    present: list[StarElement] = Field(default_factory=list)
    weakest: StarElement | None = None
    probe_hint: str = ""


class _StarRaw(LooseModel):
    present: list[str] = Field(default_factory=list)
    weakest: str | None = None
    probe_hint: str = ""


class StarAnalyst(Agent):
    """行为题的 STAR 完整度判定。近线执行，不阻塞对话。"""

    role: ClassVar[str] = ROLE_ASSIST

    async def analyze(self, *, question: str, answer: str, timeout_ms: int = 6000) -> StarVerdict | None:
        if len(answer.strip()) < 20:
            return None
        try:
            raw = await asyncio.wait_for(
                self.client.structured(
                    [
                        system(prompts.STAR_SYSTEM),
                        user(prompts.star_user_prompt(question=question, answer=answer)),
                    ],
                    _StarRaw,
                    temperature=0.1,
                    max_tokens=400,
                    retries=0,
                ),
                timeout=timeout_ms / 1000,
            )
        except Exception:
            logger.info("STAR 判定未完成，本轮跳过", exc_info=True)
            return None

        present: list[StarElement] = []
        for item in raw.present:
            try:
                element = StarElement(item.strip().lower())
            except ValueError:
                continue
            if element not in present:
                present.append(element)

        weakest: StarElement | None = None
        if raw.weakest:
            try:
                weakest = StarElement(raw.weakest.strip().lower())
            except ValueError:
                weakest = None
        if weakest is None:
            missing = [e for e in StarElement if e not in present]
            weakest = missing[0] if missing else None

        return StarVerdict(present=present, weakest=weakest, probe_hint=trim(raw.probe_hint, 80))


# ---------------------------------------------------------------------------
# Copilot 提词器
# ---------------------------------------------------------------------------


class CopilotHintPayload(LooseModel):
    keywords: list[str] = Field(default_factory=list)
    outline: list[str] = Field(default_factory=list)
    caution: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.keywords and not self.outline


class Copilot(Agent):
    """卡壳时给抓手。必须快，超时就不给，绝不让用户等。"""

    role: ClassVar[str] = ROLE_ASSIST

    async def hint(
        self,
        *,
        question: str,
        partial_answer: str,
        resume_digest: str,
        timeout_ms: int = 9000,
    ) -> CopilotHintPayload:
        if not question.strip():
            return CopilotHintPayload()
        try:
            raw = await asyncio.wait_for(
                self.client.structured(
                    [
                        system(prompts.COPILOT_SYSTEM),
                        user(
                            prompts.copilot_user_prompt(
                                question=question,
                                partial_answer=partial_answer,
                                resume_digest=resume_digest,
                            )
                        ),
                    ],
                    CopilotHintPayload,
                    temperature=0.4,
                    max_tokens=600,
                    retries=0,
                ),
                timeout=timeout_ms / 1000,
            )
        except TimeoutError:
            logger.warning("提词器超时（%d ms 内未返回）", timeout_ms)
            return CopilotHintPayload()
        except Exception as exc:
            # 近线失败不打断面试，但原因必须留痕，否则用户只看到「没能给出建议」
            logger.warning("提词器调用失败: %s", getattr(exc, "user_message", "") or exc)
            return CopilotHintPayload()
        return CopilotHintPayload(
            keywords=[trim(k, 12) for k in raw.keywords if k.strip()][:7],
            outline=[trim(o, 40) for o in raw.outline if o.strip()][:4],
            caution=trim(raw.caution, 50),
        )


# ---------------------------------------------------------------------------
# 代码追问
# ---------------------------------------------------------------------------


class CodeProbe(LooseModel):
    verdict: str = ""
    complexity: str = ""
    probe: str = ""
    probe_kind: str = "correctness"
    issues: list[str] = Field(default_factory=list)
    quality: float = 0.0


class CodeExaminer(Agent):
    """读候选人的代码，产出一个真人式的追问。不给答案。"""

    role: ClassVar[str] = ROLE_DIRECTOR

    async def probe(
        self, *, language: str, source: str, problem: str, timeout_ms: int = 25000
    ) -> CodeProbe | None:
        if len(source.strip()) < 20:
            return None
        try:
            raw = await asyncio.wait_for(
                self.client.structured(
                    [
                        system(prompts.CODE_PROBE_SYSTEM),
                        user(
                            prompts.code_probe_user_prompt(
                                language=language, source=source, problem=problem
                            )
                        ),
                    ],
                    CodeProbe,
                    temperature=0.3,
                    max_tokens=900,
                ),
                timeout=timeout_ms / 1000,
            )
        except Exception:
            logger.warning("代码追问未完成", exc_info=True)
            return None
        return CodeProbe(
            verdict=trim(raw.verdict, 80),
            complexity=trim(raw.complexity, 40),
            probe=trim(raw.probe, 120),
            probe_kind=raw.probe_kind.strip().lower() or "correctness",
            issues=[trim(i, 30) for i in raw.issues if i.strip()][:4],
            quality=clamp(raw.quality),
        )
