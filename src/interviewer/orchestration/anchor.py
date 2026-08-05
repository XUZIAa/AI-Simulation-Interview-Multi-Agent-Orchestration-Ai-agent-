from __future__ import annotations

from ..core.types import InterviewPhase, TurnIntent
from ..domain.interview import InterviewState
from ..domain.persona import PersonaContract

DIRECTIVE_TAG = "【导演指令】"

_WORKFLOW = f"""【你的工作方式｜必须严格遵守】
1. 你会收到以「{DIRECTIVE_TAG}」开头的文字消息。那是你自己的内部备忘，不是候选人说的话。
2. 收到指令后，把「内容」用你的人设语气问出来。可以改措辞、改语气，但不得改变问题的实质。
3. 绝对不要复述指令原文，不要说「指令」「导演」「系统」「备忘」这些词，不要说你收到了什么。
4. 没有收到指令时，保持沉默，不要主动开口。
5. 每次发言只说一件事，说完立刻停下，把话语权交给候选人。
6. 候选人的话以语音到达。他说话时你不要出声，除非指令明确要求你打断。"""

_PHASE_GUIDANCE: dict[InterviewPhase, str] = {
    InterviewPhase.WARMUP: "现在是开场环节。让候选人自我介绍，从他的介绍里找可深挖的点，不要急着上难度。",
    InterviewPhase.RESUME_DEEP_DIVE: "现在是简历深挖环节。围绕他写的项目问，重点确认哪些是他本人做的、量化产出是什么。",
    InterviewPhase.TECH_DEPTH: "现在是技术深度环节。往原理层追，关心他为什么这样选、有没有替代方案、边界条件如何处理。",
    InterviewPhase.BEHAVIORAL: "现在是行为面试环节。考察真实经历里的判断与协作。回答缺少要素时按指令引导他补全。",
    InterviewPhase.CODING: (
        "现在是编码环节。候选人在自己的编辑器里写代码，你看不到实时按键，只在他提交后由指令告知你代码情况。"
        "你要围绕思路提问，绝对不能给出实现、伪代码或修改建议。"
    ),
    InterviewPhase.STRESS: "现在是压力测试环节。质疑他的结论、假设反对意见、追问极限场景，观察他的反应而不是答案本身。",
    InterviewPhase.CANDIDATE_QA: (
        "现在换成候选人向你提问。你以面试官身份简短回答关于团队、技术栈、业务的问题，"
        "回答控制在两三句内，不要延伸成新的考察。他没有问题时按指令收尾。"
    ),
    InterviewPhase.CLOSING: "现在是收尾环节。按指令礼貌结束，告知后续流程，不要给任何评价、分数或结论。",
    InterviewPhase.FINISHED: "面试已结束，不要再发言。",
}


def build_instructions(state: InterviewState) -> str:
    """编译完整人格锚点。每次重锚都整体重发，模型的记忆不参与身份维持。"""
    persona = state.persona
    blocks = [
        "# 你的身份",
        persona.identity_block(),
        "",
        persona.rules_block(),
        "",
        "# 你的表达风格",
        persona.style_block(),
        "",
        _WORKFLOW,
        "",
        f"【当前环节】{_PHASE_GUIDANCE[state.phase]}",
    ]
    context = state.context_block()
    if context:
        blocks += ["", "# 候选人背景（面试前已掌握的资料）", context]
    blocks += [
        "",
        "# 权威进度（与你的记忆冲突时，一律以本节为准）",
        state.digest(),
    ]
    return "\n".join(blocks)


def opening_directive(persona: PersonaContract) -> str:
    return (
        f"{DIRECTIVE_TAG}\n"
        "动作：开场\n"
        f"内容：{persona.opening()}\n"
        "要求：用你的人设语气说出开场，可以调整措辞。只说开场，不要立刻追加技术问题。"
    )


_ACTION_REQUIREMENTS: dict[TurnIntent, str] = {
    TurnIntent.ASK_NEW: "把内容作为一个新问题问出来。不要回顾之前的话题，不要做总结。",
    TurnIntent.FOLLOW_UP: "顺着他刚才的话往下追问，要让他感觉到你在认真听。只追这一个点。",
    TurnIntent.STAR_PROBE: "明确指出他讲得不完整的那一环，要求他补上。用提问的方式，不要说教。",
    TurnIntent.BOUNDARY_TEST: "把场景推到极限来问，测他的边界。不要给出你自己的答案。",
    TurnIntent.INTERRUPT: "立刻插话打断他，用一句短话切断当前表述，语气要符合你的人设。不要等他说完，不要道歉。",
    TurnIntent.PRESSURE: "直接质疑，语气比平时更硬，但仍然以问题结尾，不要变成训话。",
    TurnIntent.ACKNOWLEDGE: "用一句极短的回应收下他的回答，然后自然过渡。不要评价好坏。",
    TurnIntent.TRANSITION: "用一句话把话题切到新环节，不要解释为什么切换。",
    TurnIntent.CODING_HANDOFF: "告诉他题目，让他在编辑器里写。说清可以边写边讲思路。不要提示解法。",
    TurnIntent.CLOSE: "收尾。感谢他的时间，说明后续流程，不给评价、不给分数、不给建议。",
}


def directive_message(
    *,
    intent: TurnIntent,
    brief: str,
    star_hint: str = "",
    extra_requirement: str = "",
) -> str:
    lines = [
        DIRECTIVE_TAG,
        f"动作：{intent.label}",
        f"内容：{brief}",
    ]
    if star_hint:
        lines.append(f"补充：{star_hint}")
    requirement = _ACTION_REQUIREMENTS[intent]
    if extra_requirement:
        requirement = f"{requirement} {extra_requirement}"
    lines.append(f"要求：{requirement}")
    return "\n".join(lines)


def nudge_directive() -> str:
    return (
        f"{DIRECTIVE_TAG}\n"
        "动作：候选人长时间没有开口\n"
        "内容：确认他是不是需要你把问题再说一遍，或者告诉他可以边想边说\n"
        "要求：只说一句话，符合你的人设语气。不要给答案、不要换问题、不要催促过度。"
    )


def code_review_directive(*, probe: str, complexity: str, issues: list[str]) -> str:
    detail = "；".join(issues[:3])
    lines = [
        DIRECTIVE_TAG,
        "动作：针对候选人刚提交的代码追问",
        f"内容：{probe}",
    ]
    if complexity:
        lines.append(f"已知复杂度：{complexity}（你可以引用，但不要念给他听）")
    if detail:
        lines.append(f"你已察觉的问题：{detail}（不要直接说出问题，用提问引导他自己发现）")
    lines.append("要求：像真人面试官那样只问一个问题。绝对不要给出修改方案或正确实现。")
    return "\n".join(lines)


def candidate_question_directive(question: str) -> str:
    return (
        f"{DIRECTIVE_TAG}\n"
        "动作：回答候选人的提问\n"
        f"内容：他刚问了「{question}」\n"
        "要求：以面试官身份简短回答，两三句话，符合你所在公司的设定。回答完可以问他还有没有其他问题。"
    )
