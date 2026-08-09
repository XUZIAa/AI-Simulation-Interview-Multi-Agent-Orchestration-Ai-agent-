"""把爬来的面经 md 编译成只读语料资源。

只保留三样东西：技术分类、问题表述、跨源频次。
链接、帖子编号、来源标题（含公司名）全部丢掉，不进产物。

产物是 zlib 压缩的 JSON，不是明文。这只是降低可读性，不是加密。
"""

from __future__ import annotations

import json
import re
import sys
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "爬取的"
OUT = ROOT / "src" / "interviewer" / "data" / "corpus" / "questions.bin"

# 行内 markdown 链接，连带把 URL 一起吃掉
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# 结尾的来源括号：（...）或 (...)，里面已经没有链接文本了
TRAILING_PAREN = re.compile(r"[（(][^（()）]*[）)]\s*$")
# 平台话题标签，如 #牛客AI配图神器#。限定必须含平台名，否则会误伤 C# / F#
PLATFORM_TAG = re.compile(r"#[^#\s]{0,24}?(?:牛客|nowcoder)[^#\s]{0,24}?#", re.IGNORECASE)
FREQ_PREFIX = re.compile(r"^\*\*(\d+)\s*源\*\*\s*[·・]\s*")
NUM_ITEM = re.compile(r"^\d+\.\s*")
BOLD = re.compile(r"\*\*(.+?)\*\*")
STAT_LINE = re.compile(r"出现于\s*(\d+)\s*篇面经")
LEADING_NOISE = re.compile(r"^\d+[，,、.]\s*")
ANSWER_TAG = re.compile(r"^[A-Z]\d*[：:]")

MIN_LEN = 6
MAX_LEN = 120

EMOJI = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff\u2b00-\u2bff\ufe0f]"
)

# 词面含品牌名但整体是技术术语，判隐私前先摘掉，否则会删掉「Java 字节码」这类核心考点
TECH_SHIELD = re.compile(
    r"字节码|字节数组|字节流|字节序|字节对齐|字节缓冲|个字节|多少字节|字节数|按字节|字节的顺序|"
    r"Survivor|survivor|"
    r"微信登录|微信支付|微信红包|支付宝支付|"
    r"上家公司|家公司|贵公司|公司的业务|网络工程|网络协议|网络编程|网络安全|网络模型",
)

# 不与技术术语撞车的公司与产品名，出现即判隐私
EXACT_BRANDS = (
    "字节跳动", "拼多多", "哔哩哔哩", "京东方", "小红书", "美团", "京东", "滴滴",
    "快手", "网易", "百度", "腾讯云", "阿里云", "华为云", "蚂蚁集团", "支付宝",
    "淘宝", "天猫", "飞书", "钉钉", "抖音", "豆包", "文心", "通义", "讯飞",
    "顺丰", "携程", "去哪儿", "新东方", "好未来", "作业帮", "猿辅导", "高途",
    "超星", "学习通", "用友", "东软", "浪潮", "神州数码", "中软", "软通",
    "同花顺", "东方财富", "海康威视", "大华股份", "紫光", "商汤", "旷视",
    "地平线", "寒武纪", "比亚迪", "蔚来", "小鹏", "理想汽车", "大疆", "虾皮",
    "工商银行", "建设银行", "招商银行", "农业银行", "国泰君安", "中信证券",
    "中国移动", "中国联通", "中国电信", "国家电网", "微软", "谷歌", "亚马逊",
    "英伟达", "甲骨文", "麒麟", "曙光", "Google", "啊B",
)

# 短名易误伤，必须配合指代公司的上下文
_AMBIGUOUS = ("字节", "阿里", "腾讯", "华为", "小米", "京东", "vivo", "OPPO", "荣耀", "平安", "中兴")
_CONTEXT = (
    "同学", "面试", "一面", "二面", "三面", "四面", "HR", "hr", "内推", "offer", "Offer",
    "实习", "校招", "社招", "这边", "那边", "入职", "离职", "投递", "面经", "岗位", "部门", "工作",
)
BRAND_CONTEXT = re.compile(
    r"(?:" + "|".join(map(re.escape, _AMBIGUOUS)) + r")[的\s]{0,2}"
    r"(?:" + "|".join(map(re.escape, _CONTEXT)) + r")"
)
BRAND_VERB = re.compile(
    r"(?:在|去|进|投|来|从|选择)\s*(?:" + "|".join(map(re.escape, _AMBIGUOUS)) + r")(?![码数组流序])"
)

# 学校与学历
SCHOOL = re.compile(r"21[15]|985|双非|本硕|研究生|[\u4e00-\u9fa5]{2,8}(?:大学|学院|科技大|理工大|师范大)")
# 面经叙事，不是面试题
NARRATIVE = re.compile(
    r"[一二三四五]面|挂了|凉经|还愿|楼主|OC\b|oc了|流程中|转正|HR面|hr面|"
    r"感谢.{0,10}机会|给后面的|兄弟们参考|面完|投了"
)


def is_private(question: str) -> bool:
    masked = TECH_SHIELD.sub("", question)
    if any(b in masked for b in EXACT_BRANDS):
        return True
    if BRAND_CONTEXT.search(masked) or BRAND_VERB.search(masked):
        return True
    if SCHOOL.search(masked) or NARRATIVE.search(masked):
        return True
    return False

# 产物里出现这些就说明清洗漏了
FORBIDDEN = ("http", "www.", "nowcoder", "](", "牛客")


# 拼音输入法把「协程」打成「携程」很常见。协程是高频考点，
# 在技术语境里纠正回来，而不是当公司名删掉。
COROUTINE_CTX = re.compile(r"线程|进程|并发|调度|阻塞|异步|栈|切换|性能|IO|io")


def fix_typo(text: str) -> str:
    if "携程" in text and COROUTINE_CTX.search(text):
        return text.replace("携程", "协程")
    return text


def strip_sources(text: str) -> str:
    text = PLATFORM_TAG.sub("", text)
    text = EMOJI.sub("", text)
    text = LINK.sub("", text)
    # 反复剥，一条目可能挂多个来源括号
    for _ in range(3):
        stripped = TRAILING_PAREN.sub("", text).strip()
        if stripped == text.strip():
            break
        text = stripped
    return text.strip(" 　·、；;，,")


# 经验建议不是面试题，但常含「原理」「怎么」这类词，会骗过下面的疑问词判断
ADVICE = re.compile(
    r"^建议|建议重点准备|重点准备|可以看看|推荐看|多刷|好好准备|准备一下|复习一下|"
    r"^注意[:：]|^总结[:：]|^反思|^感受|^心得|^经验[:：]"
)


def usable(question: str) -> bool:
    if not (MIN_LEN <= len(question) <= MAX_LEN):
        return False
    if ANSWER_TAG.match(question) or ADVICE.search(question):
        return False
    if any(bad in question.lower() for bad in ("http", "nowcoder", "www.")):
        return False
    # 纯叙述的经验分享通常没有问号也没有疑问词
    if "?" not in question and "？" not in question:
        hints = ("什么", "如何", "怎么", "为何", "为什么", "区别", "原理", "实现", "介绍", "说说",
                 "讲讲", "设计", "优化", "流程", "机制", "场景", "手撕", "写个", "写一个", "比较")
        if not any(h in question for h in hints):
            return False
    return True


def parse_full_bank(path: Path) -> list[tuple[str, str, int]]:
    """全量题库：### 分类 下面是 - **N 源** · 问题（来源）"""
    rows: list[tuple[str, str, int]] = []
    category = ""
    in_bank = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            in_bank = "完整去重题库" in line
            continue
        if not in_bank:
            continue
        if line.startswith("### "):
            category = line[4:].strip()
            continue
        if not line.startswith("- ") or not category:
            continue
        body = line[2:].strip()
        freq = 1
        hit = FREQ_PREFIX.match(body)
        if hit:
            freq = int(hit.group(1))
            body = body[hit.end() :]
        question = LEADING_NOISE.sub("", strip_sources(body))
        question = fix_typo(BOLD.sub(r"\1", question).strip())
        if usable(question):
            rows.append((category, question, freq))
    return rows


def parse_digest(path: Path) -> list[tuple[str, str, int]]:
    """背诵版：N. **题目** 后面跟统计行；来源行整行丢弃（含公司名）"""
    rows: list[tuple[str, str, int]] = []
    category = ""
    in_bank = False
    pending: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            in_bank = "背诵题目" in line
            continue
        if not in_bank:
            continue
        if line.startswith("### "):
            category = line[4:].strip()
            pending = None
            continue
        if line.startswith("- 代表来源"):
            continue
        if line.startswith("- 统计") and pending:
            hit = STAT_LINE.search(line)
            rows.append((category, pending, int(hit.group(1)) if hit else 1))
            pending = None
            continue
        if NUM_ITEM.match(line) and category:
            body = NUM_ITEM.sub("", line)
            question = fix_typo(BOLD.sub(r"\1", strip_sources(body)).strip())
            pending = question if usable(question) else None
    return rows


def main() -> int:
    if not SOURCE_DIR.is_dir():
        print(f"找不到语料目录 {SOURCE_DIR}", file=sys.stderr)
        return 1

    rows: list[tuple[str, str, int]] = []
    for path in sorted(SOURCE_DIR.glob("*.md")):
        if "背诵" in path.name:
            got = parse_digest(path)
        else:
            got = parse_full_bank(path)
        print(f"{path.name}：抽出 {len(got)} 条")
        rows.extend(got)

    # 同一问题可能跨文件重复，频次取最大值（背诵版的统计更准）
    best: dict[str, tuple[str, str, int]] = {}
    for category, question, freq in rows:
        key = re.sub(r"[\s　,，。.?？!！、；;：:]", "", question).lower()
        prev = best.get(key)
        if prev is None or freq > prev[2]:
            best[key] = (category, question, freq)

    deduped = sorted(best.values(), key=lambda r: (-r[2], r[0]))

    # 隐私过滤放在去重之后：同一问题只需判定一次
    items = [row for row in deduped if not is_private(row[1])]
    dropped = len(deduped) - len(items)
    print(f"\n隐私过滤剔除 {dropped} 条（公司、学校、面经叙事）")

    leaked = [q for _, q, _ in items if any(b in q for b in FORBIDDEN)]
    if leaked:
        print(f"清洗未通过，{len(leaked)} 条仍带来源痕迹，例如：{leaked[:3]}", file=sys.stderr)
        return 2

    payload = {
        "version": 1,
        "items": [{"c": c, "q": q, "n": n} for c, q, n in items],
    }
    blob = zlib.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"), 9)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(blob)

    cats = Counter(c for c, _, _ in items)
    print(f"\n去重后 {len(items)} 题，覆盖 {len(cats)} 个分类")
    print(f"产物 {OUT.relative_to(ROOT)}  {len(blob) / 1024:.0f} KB（压缩前 {len(json.dumps(payload, ensure_ascii=False)) / 1024:.0f} KB）")
    print("\n分类分布（前 10）：")
    for name, count in cats.most_common(10):
        print(f"  {name:<34} {count:>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
