from __future__ import annotations

from enum import StrEnum


class InterviewPhase(StrEnum):
    """面试阶段，导演据此收敛提问范围。"""

    WARMUP = "warmup"
    RESUME_DEEP_DIVE = "resume_deep_dive"
    TECH_DEPTH = "tech_depth"
    BEHAVIORAL = "behavioral"
    CODING = "coding"
    STRESS = "stress"
    CANDIDATE_QA = "candidate_qa"
    CLOSING = "closing"
    FINISHED = "finished"

    @property
    def label(self) -> str:
        return _PHASE_LABELS[self]


_PHASE_LABELS: dict[InterviewPhase, str] = {
    InterviewPhase.WARMUP: "开场破冰",
    InterviewPhase.RESUME_DEEP_DIVE: "简历深挖",
    InterviewPhase.TECH_DEPTH: "技术深度",
    InterviewPhase.BEHAVIORAL: "行为面试",
    InterviewPhase.CODING: "编码环节",
    InterviewPhase.STRESS: "压力测试",
    InterviewPhase.CANDIDATE_QA: "候选人提问",
    InterviewPhase.CLOSING: "面试收尾",
    InterviewPhase.FINISHED: "已结束",
}

PHASE_ORDER: tuple[InterviewPhase, ...] = (
    InterviewPhase.WARMUP,
    InterviewPhase.RESUME_DEEP_DIVE,
    InterviewPhase.TECH_DEPTH,
    InterviewPhase.BEHAVIORAL,
    InterviewPhase.CODING,
    InterviewPhase.STRESS,
    InterviewPhase.CANDIDATE_QA,
    InterviewPhase.CLOSING,
)


class Speaker(StrEnum):
    INTERVIEWER = "interviewer"
    CANDIDATE = "candidate"

    @property
    def label(self) -> str:
        return "面试官" if self is Speaker.INTERVIEWER else "我"


class TurnIntent(StrEnum):
    """导演下发给实时模型的意图，实时模型只负责用人设语气表达。"""

    ASK_NEW = "ask_new"
    FOLLOW_UP = "follow_up"
    STAR_PROBE = "star_probe"
    BOUNDARY_TEST = "boundary_test"
    INTERRUPT = "interrupt"
    PRESSURE = "pressure"
    ACKNOWLEDGE = "acknowledge"
    TRANSITION = "transition"
    CODING_HANDOFF = "coding_handoff"
    CLOSE = "close"

    @property
    def label(self) -> str:
        return _INTENT_LABELS[self]


_INTENT_LABELS: dict[TurnIntent, str] = {
    TurnIntent.ASK_NEW: "提出新问题",
    TurnIntent.FOLLOW_UP: "顺着回答追问",
    TurnIntent.STAR_PROBE: "引导补全 STAR",
    TurnIntent.BOUNDARY_TEST: "边界与极限测试",
    TurnIntent.INTERRUPT: "打断候选人",
    TurnIntent.PRESSURE: "施加压力",
    TurnIntent.ACKNOWLEDGE: "简短回应",
    TurnIntent.TRANSITION: "切换环节",
    TurnIntent.CODING_HANDOFF: "移交编码环节",
    TurnIntent.CLOSE: "结束面试",
}


class ScoreDimension(StrEnum):
    TECH_DEPTH = "tech_depth"
    EXPRESSION = "expression"
    RESILIENCE = "resilience"
    VALUE_FIT = "value_fit"
    CODING = "coding"
    COLLABORATION = "collaboration"

    @property
    def label(self) -> str:
        return _DIMENSION_LABELS[self]


_DIMENSION_LABELS: dict[ScoreDimension, str] = {
    ScoreDimension.TECH_DEPTH: "技术深度",
    ScoreDimension.EXPRESSION: "逻辑表达",
    ScoreDimension.RESILIENCE: "抗压能力",
    ScoreDimension.VALUE_FIT: "价值观匹配",
    ScoreDimension.CODING: "编码能力",
    ScoreDimension.COLLABORATION: "沟通协作",
}


class StarElement(StrEnum):
    SITUATION = "situation"
    TASK = "task"
    ACTION = "action"
    RESULT = "result"

    @property
    def label(self) -> str:
        return _STAR_LABELS[self]


_STAR_LABELS: dict[StarElement, str] = {
    StarElement.SITUATION: "情境 Situation",
    StarElement.TASK: "任务 Task",
    StarElement.ACTION: "行动 Action",
    StarElement.RESULT: "结果 Result",
}


class AnnotationKind(StrEnum):
    STRENGTH = "strength"
    WEAKNESS = "weakness"
    FILLER = "filler"
    OFF_TOPIC = "off_topic"

    @property
    def label(self) -> str:
        return _ANNOTATION_LABELS[self]


_ANNOTATION_LABELS: dict[AnnotationKind, str] = {
    AnnotationKind.STRENGTH: "亮点",
    AnnotationKind.WEAKNESS: "待改进",
    AnnotationKind.FILLER: "冗余表达",
    AnnotationKind.OFF_TOPIC: "偏离问题",
}


class SessionStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    ABORTED = "aborted"

    @property
    def label(self) -> str:
        return _SESSION_LABELS[self]


_SESSION_LABELS: dict[SessionStatus, str] = {
    SessionStatus.DRAFT: "未开始",
    SessionStatus.RUNNING: "进行中",
    SessionStatus.REVIEWING: "生成复盘",
    SessionStatus.COMPLETED: "已完成",
    SessionStatus.ABORTED: "已中止",
}


class GapSeverity(StrEnum):
    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"

    @property
    def label(self) -> str:
        return {"blocker": "致命缺口", "major": "重点缺口", "minor": "次要缺口"}[self.value]


class CompanyTier(StrEnum):
    """公司类型。它决定考什么、怎么问、以及分数怎么加权。"""

    BIG_TECH = "big_tech"
    MID_TECH = "mid_tech"
    STARTUP = "startup"
    MANUFACTURING = "manufacturing"
    STATE_OWNED = "state_owned"
    FOREIGN = "foreign"
    FINANCE = "finance"
    OUTSOURCE = "outsource"

    @property
    def label(self) -> str:
        return _TIER_LABELS[self]


_TIER_LABELS: dict[CompanyTier, str] = {
    CompanyTier.BIG_TECH: "互联网大厂",
    CompanyTier.MID_TECH: "中型科技公司",
    CompanyTier.STARTUP: "创业公司",
    CompanyTier.MANUFACTURING: "制造业 / 工业软件",
    CompanyTier.STATE_OWNED: "国企 / 事业单位",
    CompanyTier.FOREIGN: "外企 / 跨国研发中心",
    CompanyTier.FINANCE: "银行 / 券商 / 金融科技",
    CompanyTier.OUTSOURCE: "外包 / 乙方交付",
}


class JobLevel(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    EXPERT = "expert"

    @property
    def label(self) -> str:
        return _LEVEL_LABELS[self]

    @property
    def years_hint(self) -> str:
        return _LEVEL_YEARS[self]


_LEVEL_LABELS: dict[JobLevel, str] = {
    JobLevel.INTERN: "实习 / 应届",
    JobLevel.JUNIOR: "初级（1-3 年）",
    JobLevel.MID: "中级（3-5 年）",
    JobLevel.SENIOR: "高级（5-8 年）",
    JobLevel.EXPERT: "专家 / 架构（8 年以上）",
}

_LEVEL_YEARS: dict[JobLevel, str] = {
    JobLevel.INTERN: "在校或 1 年以内",
    JobLevel.JUNIOR: "1-3 年",
    JobLevel.MID: "3-5 年",
    JobLevel.SENIOR: "5-8 年",
    JobLevel.EXPERT: "8 年以上",
}


class QuestionSource(StrEnum):
    """题目来源。决定这道题为什么值得问，也决定它能不能被跳过。"""

    JD_REQUIREMENT = "jd"
    RESUME_PROJECT = "project"
    RESUME_SKILL = "skill"
    FUNDAMENTAL = "fundamental"
    BEHAVIORAL = "behavioral"
    CODING = "coding"

    @property
    def label(self) -> str:
        return _SOURCE_LABELS[self]


_SOURCE_LABELS: dict[QuestionSource, str] = {
    QuestionSource.JD_REQUIREMENT: "JD 硬性要求",
    QuestionSource.RESUME_PROJECT: "简历项目",
    QuestionSource.RESUME_SKILL: "简历技能",
    QuestionSource.FUNDAMENTAL: "岗位基础",
    QuestionSource.BEHAVIORAL: "行为与价值观",
    QuestionSource.CODING: "编码题",
}


# 深度阶梯。加深还是换领域，由这四级决定，不交给模型自由裁量
DEPTH_LABELS: dict[int, str] = {
    1: "概念层（是什么、用过没有）",
    2: "实践层（你们怎么做的、具体怎么落地）",
    3: "原理层（为什么这样选、底层如何实现、有何权衡）",
    4: "边界层（极限场景、故障、规模放大十倍）",
}
MAX_DEPTH = 4


class DriftKind(StrEnum):
    """人格漂移的具体形态，Guard 命中后用于决定修复动作。"""

    NONE = "none"
    AI_SELF_REVEAL = "ai_self_reveal"
    ROLE_SWAP = "role_swap"
    REFUSAL = "refusal"
    OFF_DOMAIN = "off_domain"
    STYLE_BREAK = "style_break"
    ANSWER_LEAK = "answer_leak"
