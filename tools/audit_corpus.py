"""语料隐私审计。只读不改。

难点在区分「技术语境里的品牌词」和「指代某家公司」：
「几个字节」「Survivor 区」「微信登录接口」都是技术题，不能当隐私删；
「跟拼多多的同学聊过」「腾讯云点播」才是要处理的。
所以用白名单加上下文限定，而不是见名就杀。
"""

from __future__ import annotations

import json
import re
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "src" / "interviewer" / "data" / "corpus" / "questions.bin"
REPORT = ROOT / "tools" / "audit-report.txt"

# 直接判定为泄漏的硬模式
HARD: dict[str, re.Pattern[str]] = {
    "URL 或域名": re.compile(r"https?://|www\.|\.com|\.cn/|nowcoder", re.I),
    "帖子编号": re.compile(r"\bS\d{3,4}\b"),
    "手机号": re.compile(r"1[3-9]\d{9}"),
    "邮箱": re.compile(r"[\w.+-]+@[\w-]+\.\w+"),
    "话题标签": re.compile(r"#[^#\s]{2,24}#"),
    "面试轮次日期": re.compile(r"\d{1,2}月\d{1,2}[日号].{0,12}(?:面|经)"),
}

# 这些词面里含品牌名，但整体是技术术语，必须先摘掉再判断
TECH_SHIELD = re.compile(
    r"字节码|字节数组|字节流|字节序|字节对齐|字节缓冲|个字节|多少字节|字节数|按字节|"
    r"Survivor|survivor|"
    r"微信登录|微信支付|微信红包|支付宝支付|"
    r"上家公司|家公司|贵公司|公司的业务|网络工程|网络协议|网络编程|网络安全|网络模型",
)

# 不会与技术术语撞车的公司与产品全名，出现即命中
EXACT_BRANDS = (
    "字节跳动", "拼多多", "哔哩哔哩", "京东方", "小红书", "美团", "京东", "滴滴",
    "快手", "网易", "百度", "腾讯云", "阿里云", "华为云", "蚂蚁集团", "支付宝",
    "淘宝", "天猫", "飞书", "钉钉", "抖音", "豆包", "文心", "通义", "讯飞",
    "顺丰", "携程", "去哪儿", "新东方", "好未来", "作业帮", "猿辅导", "高途",
    "超星", "学习通", "用友", "东软", "浪潮", "神州数码", "中软", "软通",
    "同花顺", "东方财富", "海康威视", "大华股份", "紫光", "商汤", "旷视",
    "地平线", "寒武纪", "比亚迪", "蔚来", "小鹏", "理想汽车", "大疆",
    "工商银行", "建设银行", "招商银行", "农业银行", "国泰君安", "中信证券",
    "中国移动", "中国联通", "中国电信", "国家电网", "微软", "谷歌", "亚马逊",
    "英伟达", "甲骨文", "麒麟", "曙光",
)

# 短名容易误伤，必须配合「指代公司」的上下文才算命中
AMBIGUOUS = ("字节", "阿里", "腾讯", "华为", "小米", "京东", "vivo", "OPPO", "荣耀", "平安", "中兴")
CONTEXT = (
    "同学", "面试", "一面", "二面", "三面", "四面", "HR", "hr", "内推", "offer", "Offer",
    "实习", "校招", "社招", "这边", "那边", "入职", "离职", "投递", "面经", "岗位", "部门",
)
AMBIGUOUS_RE = re.compile(
    r"(?:" + "|".join(map(re.escape, AMBIGUOUS)) + r")"
    r"(?:[的\s]{0,2})"
    r"(?:" + "|".join(map(re.escape, CONTEXT)) + r")"
)
# 「在字节」「去阿里」「进腾讯」这类动词加公司
VERB_BRAND_RE = re.compile(
    r"(?:在|去|进|投|来|从)\s*(?:" + "|".join(map(re.escape, AMBIGUOUS)) + r")(?![码数组流序])"
)


def scan(items: list[dict]) -> tuple[dict[str, list[tuple[int, str]]], set[int]]:
    found: dict[str, list[tuple[int, str]]] = {}
    flagged: set[int] = set()

    for name, pattern in HARD.items():
        hits = [(i, it["q"]) for i, it in enumerate(items) if pattern.search(it["q"])]
        found[name] = hits
        flagged.update(i for i, _ in hits)

    exact: list[tuple[int, str]] = []
    ctx: list[tuple[int, str]] = []
    for i, it in enumerate(items):
        q = it["q"]
        masked = TECH_SHIELD.sub("", q)
        if any(b in masked for b in EXACT_BRANDS):
            exact.append((i, q))
            flagged.add(i)
            continue
        if AMBIGUOUS_RE.search(masked) or VERB_BRAND_RE.search(masked):
            ctx.append((i, q))
            flagged.add(i)

    found["公司全名"] = exact
    found["公司加语境"] = ctx
    return found, flagged


def main() -> int:
    if not CORPUS.exists():
        print(f"找不到语料 {CORPUS}", file=sys.stderr)
        return 1

    items = json.loads(zlib.decompress(CORPUS.read_bytes()).decode("utf-8"))["items"]
    found, flagged = scan(items)

    lines = [f"语料 {len(items)} 题", ""]
    for name, hits in found.items():
        lines.append(f"[{name}] {len(hits)} 条")
        for _, q in hits[:40]:
            lines.append(f"    {q}")
        lines.append("")
    lines.append(f"合计需处理 {len(flagged)} 条，占 {len(flagged) / len(items) * 100:.2f}%")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告已写入 {REPORT.relative_to(ROOT)}，命中 {len(flagged)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
