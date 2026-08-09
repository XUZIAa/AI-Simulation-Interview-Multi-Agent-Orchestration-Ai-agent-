"""真题语料的只读检索。

语料是离线编译的产物，只含分类、问题表述和跨源频次，不含任何来源信息。
检索命中为空时调用方应当什么都不注入，让出题回到原有行为。
"""

from __future__ import annotations

import json
import logging
import re
import zlib
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

logger = logging.getLogger(__name__)

RESOURCE = "questions.bin"
# 英文技术词：Redis、MySQL、Spring Boot、C++、.NET 之类
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,20}")
# 这些词到处都在，用来检索等于全表扫描
_STOP = {
    "the", "and", "for", "with", "http", "https", "com", "www", "api", "sdk",
    "开发", "使用", "熟悉", "掌握", "了解", "熟练", "经验", "能力", "以上", "相关",
    "负责", "参与", "以及", "或者", "包括", "优先", "良好", "具备", "工作", "技术",
}


@dataclass(frozen=True)
class RealQuestion:
    category: str
    text: str
    sources: int


@lru_cache(maxsize=1)
def _load() -> tuple[RealQuestion, ...]:
    try:
        blob = resources.files(__package__).joinpath(RESOURCE).read_bytes()
    except FileNotFoundError:
        logger.info("没有真题语料，出题按原有流程走")
        return ()
    try:
        payload = json.loads(zlib.decompress(blob).decode("utf-8"))
    except Exception:
        logger.warning("真题语料解析失败，已忽略", exc_info=True)
        return ()
    items = tuple(
        RealQuestion(category=it.get("c", ""), text=it.get("q", ""), sources=int(it.get("n", 1)))
        for it in payload.get("items", ())
        if it.get("q")
    )
    logger.info("真题语料已载入 %d 条", len(items))
    return items


def _terms(fragments: list[str]) -> list[str]:
    """从 JD 条目与技能列表里抠出可用于匹配的词。

    JD 条目是整句，只取其中的英文技术词；技能名本身够短就整体当词用。
    """
    found: set[str] = set()
    for text in fragments:
        raw = text.strip()
        if not raw:
            continue
        for hit in _LATIN.finditer(raw):
            word = hit.group().strip(".-")
            if len(word) >= 2 and word.lower() not in _STOP:
                found.add(word)
        if 2 <= len(raw) <= 12 and raw not in _STOP:
            found.add(raw)
    return sorted(found, key=len, reverse=True)


# 语料只覆盖 Java 后端与 Agent／大模型应用两个方向。
# 别的岗位即使 JD 里同样出现 MySQL、Redis、Linux，考察视角也完全不同
# （运维关心集群与容量，这里的题是 InnoDB 索引结构），一律不注入。
_OFF_SCOPE_TITLE = (
    "测试", "运维", "SRE", "sre", "DBA", "dba", "产品", "运营", "设计", "UI", "ui",
    "数据分析", "数据仓库", "数仓", "BI", "ETL", "商业智能",
    "算法", "机器学习", "深度学习", "视觉", "语音", "推荐系统", "搜索引擎研发",
    "嵌入式", "单片机", "硬件", "FPGA", "驱动", "固件", "电路", "射频",
    "安卓", "Android", "android", "iOS", "ios", "客户端", "鸿蒙", "小程序",
    "游戏", "Unity", "unity", "虚幻", "美术", "策划",
    "安全", "渗透", "逆向", "风控", "合规", "审计",
    "实施", "售前", "售后", "支持", "培训", "销售", "财务", "人力", "行政", "法务",
    "C++", "Golang 开发", "Go 开发", "PHP", "Python 开发", ".NET", "Net 开发",
)

_JAVA_SIGNAL = (
    "Java", "java", "JAVA", "Spring", "spring", "SpringBoot", "JVM", "jvm",
    "MyBatis", "mybatis", "Mybatis", "Tomcat", "tomcat", "JUC", "juc",
    "Netty", "netty", "Dubbo", "dubbo", "Maven", "maven", "Gradle", "JDK", "jdk",
)
_AGENT_SIGNAL = (
    "Agent", "agent", "智能体", "RAG", "rag", "LLM", "llm", "大模型", "大语言模型",
    "Prompt", "prompt", "提示词", "向量数据库", "Embedding", "embedding",
    "LangChain", "langchain", "AIGC", "aigc", "多模态", "微调", "MCP", "mcp",
)
_MIN_SIGNAL = 2


def job_in_scope(title: str, fragments: list[str]) -> bool:
    """判断岗位是否落在语料覆盖范围内。

    排斥词只看岗位名：JD 正文里出现「需要写单元测试」不代表这是测试岗。
    方向信号看岗位名加 JD，要求命中两个以上，避免偶然提一次 Java 就放行。
    """
    if any(bad in title for bad in _OFF_SCOPE_TITLE):
        return False
    blob = " ".join([title, *fragments])
    java = sum(1 for w in _JAVA_SIGNAL if w in blob)
    agent = sum(1 for w in _AGENT_SIGNAL if w in blob)
    return java >= _MIN_SIGNAL or agent >= _MIN_SIGNAL


@lru_cache(maxsize=256)
def _boundary(term: str) -> re.Pattern[str] | None:
    """英文词要卡词边界，否则 CAN 会命中 canal、ID 会命中 android。
    中文没有词边界，直接子串匹配。"""
    if not term.isascii():
        return None
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)


def search_real_questions(
    fragments: list[str],
    *,
    title: str = "",
    limit: int = 28,
    per_category: int = 4,
    min_sources: int = 2,
    min_useful: int = 8,
) -> list[RealQuestion]:
    """按技能词检索真题。

    先过岗位方向门禁：不在覆盖范围内直接返回空，不做检索。
    min_sources 滤掉只在一篇面经里出现过的偶发问法；
    命中不足 min_useful 时判定覆盖不够，返回空让调用方保持原行为；
    per_category 限制单一技术栈的占比，避免参考题偏科。
    """
    items = _load()
    if not items:
        return []
    if not job_in_scope(title, fragments):
        return []
    terms = _terms(fragments)
    if not terms:
        return []

    probes = [(t.lower(), _boundary(t)) for t in terms]
    scored: list[tuple[int, int, RealQuestion]] = []
    for question in items:
        if question.sources < min_sources:
            continue
        text = question.text.lower()
        category = question.category.lower()
        hits = 0
        for probe, pattern in probes:
            # 先用子串粗筛，绝大多数题在这一步就被排除
            if probe not in text and probe not in category:
                continue
            if pattern is not None and not (
                pattern.search(question.text) or pattern.search(question.category)
            ):
                continue
            hits += 1
        if hits:
            scored.append((hits, question.sources, question))

    if len(scored) < min_useful:
        return []

    scored.sort(key=lambda row: (-row[0], -row[1]))

    picked: list[RealQuestion] = []
    used: dict[str, int] = {}
    for _, _, question in scored:
        seen = used.get(question.category, 0)
        if seen >= per_category:
            continue
        used[question.category] = seen + 1
        picked.append(question)
        if len(picked) >= limit:
            break
    return picked
