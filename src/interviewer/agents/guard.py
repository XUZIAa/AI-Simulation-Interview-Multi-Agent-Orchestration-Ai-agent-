from __future__ import annotations

import asyncio
import logging
import re
from typing import ClassVar

from pydantic import BaseModel

from ..core.types import DriftKind
from ..domain.persona import PersonaContract
from ..llm import prompts
from ..llm.base import system, user
from ..llm.coerce import LooseModel
from ..llm.router import ROLE_GUARD
from .base import Agent, trim

logger = logging.getLogger(__name__)

# 明显违规的表达用正则零延迟拦截，不必等模型
_REGEX_RULES: tuple[tuple[DriftKind, re.Pattern[str]], ...] = (
    (
        DriftKind.AI_SELF_REVEAL,
        re.compile(
            r"(作为一?个?\s*(AI|ai|人工智能|大语言模型|语言模型|智能助手|聊天机器人))"
            r"|(我是一?个?\s*(AI|ai|人工智能|大语言模型|语言模型|智能助手|机器人|程序))"
            r"|(我(的)?(系统)?(提示词|prompt|设定|指令|角色设定)是)"
            r"|(根据我的(设定|指令|提示词))"
            r"|(我并(不是|非)真(人|实的人))"
        ),
    ),
    (
        DriftKind.REFUSAL,
        re.compile(
            r"(抱歉[，,]?\s*我(不能|无法|没有办法))"
            r"|(很抱歉[，,]?\s*我(不能|无法))"
            r"|(我无法(提供|回答|完成|协助|生成))"
            r"|(这超出了我的(能力|范围|权限))"
        ),
    ),
    (
        DriftKind.ANSWER_LEAK,
        re.compile(
            r"(标准答案(是|为)?)"
            r"|(正确答案(是|为))"
            r"|(参考答案)"
            r"|(你可以这样(回答|说))"
            r"|(建议你(这样)?(回答|说))"
            r"|(我给你(一个)?(示范|范例|模板))"
            r"|(下面是(实现|代码|示例代码))"
        ),
    ),
    (
        DriftKind.ROLE_SWAP,
        re.compile(r"(我来(扮演|充当)(候选人|学生|老师|助教))|(现在我是(候选人|学生|你的老师))"),
    ),
)


class GuardVerdict(BaseModel):
    kind: DriftKind = DriftKind.NONE
    excerpt: str = ""
    reason: str = ""
    by_regex: bool = False

    @property
    def violated(self) -> bool:
        return self.kind is not DriftKind.NONE


class _GuardRaw(LooseModel):
    kind: str = "none"
    excerpt: str = ""
    reason: str = ""


class Guard(Agent):
    """人格漂移检测。正则先过一遍，语义层再兜住剩下的。"""

    role: ClassVar[str] = ROLE_GUARD

    @staticmethod
    def scan_regex(spoken: str) -> GuardVerdict:
        for kind, pattern in _REGEX_RULES:
            match = pattern.search(spoken)
            if match:
                logger.warning("正则命中漂移 kind=%s excerpt=%s", kind.value, match.group(0))
                return GuardVerdict(
                    kind=kind,
                    excerpt=trim(match.group(0), 40),
                    reason="命中人格红线关键词",
                    by_regex=True,
                )
        return GuardVerdict()

    async def inspect(
        self, spoken: str, persona: PersonaContract, *, timeout_ms: int = 2500
    ) -> GuardVerdict:
        text = spoken.strip()
        if len(text) < 6:
            return GuardVerdict()

        fast = self.scan_regex(text)
        if fast.violated:
            return fast

        persona_summary = "\n".join(
            [persona.identity_block(), *(f"- {line}" for line in persona.speech.describe() if line)]
        )
        try:
            raw = await asyncio.wait_for(
                self.client.structured(
                    [
                        system(prompts.GUARD_SYSTEM),
                        user(prompts.guard_user_prompt(persona_summary=persona_summary, spoken=text)),
                    ],
                    _GuardRaw,
                    temperature=0.0,
                    max_tokens=300,
                    retries=0,
                ),
                timeout=timeout_ms / 1000,
            )
        except TimeoutError:
            logger.info("守卫超时，本轮跳过语义检查")
            return GuardVerdict()
        except Exception:
            logger.warning("守卫调用失败，本轮跳过语义检查", exc_info=True)
            return GuardVerdict()

        try:
            kind = DriftKind(raw.kind.strip().lower())
        except ValueError:
            kind = DriftKind.NONE
        if kind is DriftKind.NONE:
            return GuardVerdict()
        logger.warning("语义判定漂移 kind=%s reason=%s", kind.value, raw.reason)
        return GuardVerdict(kind=kind, excerpt=trim(raw.excerpt, 40), reason=trim(raw.reason, 80))


def repair_directive(verdict: GuardVerdict, persona: PersonaContract) -> str:
    """把违规转成一条纠正指令，随重锚一起下发。"""
    base = (
        "【严重违规纠正】你刚才的发言破坏了面试官身份。"
        f"问题类型：{_KIND_HINTS[verdict.kind]}。"
        f"违规片段：「{verdict.excerpt}」。\n"
        f"你是{persona.job_title}「{persona.name}」，正在进行真实面试。"
        "立刻用你的人设语气重新组织上一句话，只提出面试问题，不要道歉、不要解释刚才发生了什么、"
        "不要提及任何与设定有关的内容。现在重新说。"
    )
    return base


_KIND_HINTS: dict[DriftKind, str] = {
    DriftKind.NONE: "无",
    DriftKind.AI_SELF_REVEAL: "暴露了 AI 身份或系统设定",
    DriftKind.ROLE_SWAP: "脱离了面试官角色",
    DriftKind.REFUSAL: "用助手口吻拒绝了",
    DriftKind.OFF_DOMAIN: "聊到了与面试无关的话题",
    DriftKind.STYLE_BREAK: "违背了人设的语气设定",
    DriftKind.ANSWER_LEAK: "把答案泄露给了候选人",
}
