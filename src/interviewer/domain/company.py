from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.types import CompanyTier, JobLevel, ScoreDimension


class CompanyProfile(BaseModel):
    """一类公司的真实考察偏好。出题、追问口径、评分权重都从这里派生。"""

    tier: CompanyTier
    summary: str
    interview_style: str
    hot_topics: tuple[str, ...]
    cold_topics: tuple[str, ...]
    jd_flavor: str
    algorithm: int = Field(ge=0, le=10)
    system_design: int = Field(ge=0, le=10)
    fundamentals: int = Field(ge=0, le=10)
    project: int = Field(ge=0, le=10)
    process: int = Field(ge=0, le=10)
    cost: int = Field(ge=0, le=10)
    stability: int = Field(ge=0, le=10)
    score_bias: dict[ScoreDimension, float] = Field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.tier.label

    def emphasis_line(self) -> str:
        pairs = (
            ("算法与数据结构", self.algorithm),
            ("系统设计", self.system_design),
            ("语言与框架原理", self.fundamentals),
            ("项目落地经验", self.project),
            ("流程与规范", self.process),
            ("成本与效率意识", self.cost),
            ("稳定性与容错", self.stability),
        )
        ranked = sorted(pairs, key=lambda kv: kv[1], reverse=True)
        return "、".join(f"{name}({score}/10)" for name, score in ranked if score > 0)

    def guidance_block(self) -> str:
        lines = [
            f"【公司类型】{self.tier.label}——{self.summary}",
            f"【这类公司的面试口径】{self.interview_style}",
            f"【必须覆盖的话题】{'、'.join(self.hot_topics)}",
            f"【考察配比】{self.emphasis_line()}",
        ]
        if self.cold_topics:
            lines.append(f"【不要浪费时间的话题】{'、'.join(self.cold_topics)}")
        return "\n".join(lines)


_PROFILES: dict[CompanyTier, CompanyProfile] = {
    CompanyTier.BIG_TECH: CompanyProfile(
        tier=CompanyTier.BIG_TECH,
        summary="人多、系统大、分工细，招人看基础深度和规模经验",
        interview_style=(
            "先问项目再往原理层追，喜欢连续追问直到你答不出来；"
            "关心数据规模、QPS、延迟指标，几乎必问「量级放大十倍会怎样」；"
            "算法题是标配，答不出会明显影响评价"
        ),
        hot_topics=("高并发", "分布式一致性", "缓存与存储选型", "算法复杂度", "线上故障排查", "监控与指标"),
        cold_topics=("具体某个 IDE 的用法", "行业特定业务流程"),
        jd_flavor="强调技术栈深度、大规模系统经验、扎实的计算机基础，通常明确写出算法与数据结构要求",
        algorithm=9,
        system_design=9,
        fundamentals=9,
        project=7,
        process=4,
        cost=3,
        stability=6,
        score_bias={ScoreDimension.TECH_DEPTH: 1.15, ScoreDimension.CODING: 1.1},
    ),
    CompanyTier.MID_TECH: CompanyProfile(
        tier=CompanyTier.MID_TECH,
        summary="团队不大、一人多岗，招人看能不能独立把事情做完",
        interview_style=(
            "重点问「这个模块是不是你一个人做的」「上线后出问题谁处理」；"
            "喜欢全栈或跨模块能力，会问你不熟的相邻领域看你怎么应对；"
            "不太抠算法，但很在意交付速度和独立性"
        ),
        hot_topics=("独立负责的模块", "技术选型理由", "上线与回滚", "跨模块协作", "问题定位过程"),
        cold_topics=("超大规模架构", "论文级算法优化"),
        jd_flavor="强调独立负责能力、全栈或多技术栈、快速上手、能扛业务需求",
        algorithm=5,
        system_design=6,
        fundamentals=6,
        project=9,
        process=5,
        cost=5,
        stability=7,
        score_bias={ScoreDimension.TECH_DEPTH: 1.0, ScoreDimension.COLLABORATION: 1.1},
    ),
    CompanyTier.STARTUP: CompanyProfile(
        tier=CompanyTier.STARTUP,
        summary="资源紧、变化快，招人看主动性和扛事能力",
        interview_style=(
            "几乎不问八股，直接问你做过什么、带来什么结果；"
            "会用「资源只有一半你怎么办」「这事没人管你会不会接」这类问题测 ownership；"
            "对成本和时间极度敏感，会问「为什么不用现成的」"
        ),
        hot_topics=("从 0 到 1 的经历", "ownership", "资源受限下的取舍", "成本控制", "主动补位"),
        cold_topics=("大公司流程", "多层审批机制"),
        jd_flavor="不设明确边界，强调主动性、抗压、从 0 搭建能力，常写「能接受快速变化」",
        algorithm=3,
        system_design=5,
        fundamentals=5,
        project=10,
        process=2,
        cost=7,
        stability=5,
        score_bias={ScoreDimension.VALUE_FIT: 1.2, ScoreDimension.RESILIENCE: 1.15},
    ),
    CompanyTier.MANUFACTURING: CompanyProfile(
        tier=CompanyTier.MANUFACTURING,
        summary="软件服务产线与设备，停机就是钱，招人看稳定和规范",
        interview_style=(
            "反复确认系统稳定性：「产线不能停，你的程序挂了怎么办」；"
            "关心与硬件、PLC、设备、产线人员的配合经验；"
            "在意文档、变更流程、现场调试和故障复现能力，几乎不问算法"
        ),
        hot_topics=(
            "系统稳定性与容错",
            "现场问题排查",
            "与硬件/设备联调",
            "变更与发布流程",
            "数据采集与实时性",
            "文档与交接",
        ),
        cold_topics=("互联网高并发", "算法竞赛题", "前端炫技"),
        jd_flavor="强调工业场景经验（MES/SCADA/PLC/嵌入式/数采）、稳定性要求、规范意识、能下现场",
        algorithm=2,
        system_design=4,
        fundamentals=5,
        project=8,
        process=9,
        cost=8,
        stability=10,
        score_bias={ScoreDimension.RESILIENCE: 1.1, ScoreDimension.COLLABORATION: 1.2},
    ),
    CompanyTier.STATE_OWNED: CompanyProfile(
        tier=CompanyTier.STATE_OWNED,
        summary="信息化建设为主，流程规范优先，招人看沉稳与合规",
        interview_style=(
            "语气克制、按提纲走，很少高压追问；"
            "关心项目验收、需求对接、多方协调、文档交付；"
            "会问信息安全、等保、国产化替代相关的经验"
        ),
        hot_topics=("需求对接与验收", "文档与规范", "信息安全合规", "国产化适配", "多部门协作", "系统运维"),
        cold_topics=("激进的技术选型", "996 式交付"),
        jd_flavor="强调信息化项目经验、规范文档、安全合规、国产化环境适配，通常有学历与稳定性要求",
        algorithm=3,
        system_design=5,
        fundamentals=5,
        project=6,
        process=10,
        cost=6,
        stability=9,
        score_bias={ScoreDimension.COLLABORATION: 1.2, ScoreDimension.VALUE_FIT: 1.1},
    ),
    CompanyTier.FOREIGN: CompanyProfile(
        tier=CompanyTier.FOREIGN,
        summary="流程成熟、跨时区协作，招人看工程素养和沟通",
        interview_style=(
            "中英混说，名词一律英文；关心 ownership、impact、stakeholder 沟通；"
            "重视代码质量、测试覆盖、code review 文化；"
            "会问「你怎么说服对方」「有分歧时怎么 align」"
        ),
        hot_topics=("代码质量与测试", "code review", "跨时区协作", "影响力与说服", "工程规范", "技术文档"),
        cold_topics=("拼时长", "野路子救火"),
        jd_flavor="强调英文沟通、工程规范、单元测试、敏捷流程，常写 global team 协作要求",
        algorithm=6,
        system_design=7,
        fundamentals=7,
        project=7,
        process=8,
        cost=5,
        stability=8,
        score_bias={ScoreDimension.EXPRESSION: 1.15, ScoreDimension.COLLABORATION: 1.15},
    ),
    CompanyTier.FINANCE: CompanyProfile(
        tier=CompanyTier.FINANCE,
        summary="钱不能错、系统不能停，招人看严谨与容灾",
        interview_style=(
            "对数据一致性刨根问底：「这笔钱扣了但没到账怎么办」；"
            "必问事务、对账、幂等、重试、容灾切换；"
            "关心合规审计与操作留痕，对「大概没问题」零容忍"
        ),
        hot_topics=("分布式事务", "幂等与对账", "高可用与容灾", "审计留痕", "资金安全", "灰度与回滚"),
        cold_topics=("前端动效", "快速试错"),
        jd_flavor="强调金融级稳定性、分布式事务、灾备演练、合规审计，通常要求相关行业背景",
        algorithm=6,
        system_design=8,
        fundamentals=8,
        project=7,
        process=9,
        cost=4,
        stability=10,
        score_bias={ScoreDimension.TECH_DEPTH: 1.1, ScoreDimension.RESILIENCE: 1.1},
    ),
    CompanyTier.OUTSOURCE: CompanyProfile(
        tier=CompanyTier.OUTSOURCE,
        summary="按甲方要求交付，招人看上手速度和适配能力",
        interview_style=(
            "先核对技术栈清单，逐项确认你会不会、做过几年；"
            "关心能否驻场、能否同时跟多个项目、能否适应甲方规范；"
            "问题偏广不偏深，更在意「拿来就能干」"
        ),
        hot_topics=("技术栈清单核对", "交付周期", "多项目并行", "甲方规范适配", "驻场经验"),
        cold_topics=("底层原理探究", "长期架构演进"),
        jd_flavor="逐条列出技术栈与版本、明确项目周期与驻场要求，强调即刻上手",
        algorithm=3,
        system_design=4,
        fundamentals=4,
        project=8,
        process=7,
        cost=8,
        stability=6,
        score_bias={ScoreDimension.EXPRESSION: 1.05, ScoreDimension.COLLABORATION: 1.1},
    ),
}


def company_profile(tier: CompanyTier) -> CompanyProfile:
    return _PROFILES[tier]


def all_profiles() -> list[CompanyProfile]:
    return [_PROFILES[tier] for tier in CompanyTier]


def score_weights(tier: CompanyTier) -> dict[ScoreDimension, float]:
    """在基础权重上叠加公司偏移，得到这类公司真实的评分口径。"""
    base: dict[ScoreDimension, float] = {
        ScoreDimension.TECH_DEPTH: 0.32,
        ScoreDimension.EXPRESSION: 0.2,
        ScoreDimension.RESILIENCE: 0.14,
        ScoreDimension.VALUE_FIT: 0.12,
        ScoreDimension.CODING: 0.14,
        ScoreDimension.COLLABORATION: 0.08,
    }
    bias = _PROFILES[tier].score_bias
    return {dim: weight * bias.get(dim, 1.0) for dim, weight in base.items()}


def level_expectation(tier: CompanyTier, level: JobLevel) -> str:
    """同一岗位不同级别的考察落点差异。"""
    profile = _PROFILES[tier]
    by_level = {
        JobLevel.INTERN: "考察基础是否扎实、学习能力、有没有动手做过完整的东西，不要求架构视野",
        JobLevel.JUNIOR: "考察独立完成模块的能力、基础原理、能否按规范交付，允许在架构问题上答不全",
        JobLevel.MID: "考察独立负责子系统、技术选型理由、跨模块协作，要能讲清权衡",
        JobLevel.SENIOR: "考察架构设计、复杂问题拆解、带人与推动落地，必须能讲清取舍和风险",
        JobLevel.EXPERT: "考察技术判断力、跨团队影响、长期演进规划，要能对方案下结论并承担后果",
    }
    return f"{by_level[level]}。结合{profile.tier.label}的口径：{profile.interview_style.split('；')[0]}。"
