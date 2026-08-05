from __future__ import annotations

import re
from collections import defaultdict
from itertools import pairwise

from ..core.types import Speaker
from ..domain.interview import TurnRecord
from ..domain.review import ProsodyReport, QuestionProsody

_HAN = re.compile(r"[\u4e00-\u9fff]")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")

# 高频填充词。中文口语里这些词本身合法，靠密度而非出现判定问题
_FILLERS: tuple[str, ...] = (
    "嗯",
    "呃",
    "唉",
    "那个",
    "这个",
    "然后",
    "就是说",
    "就是",
    "其实",
    "怎么说呢",
    "你知道",
    "对吧",
    "反正",
    "基本上",
    "或者说",
    "um",
    "uh",
    "like",
    "you know",
)

_FAST_WPM = 315.0
_SLOW_WPM = 155.0
_FILLER_PER_100 = 5.5
_HIGH_PAUSE_RATIO = 0.34
_LONG_PAUSE_MS = 4200


def count_units(text: str) -> int:
    """中文按字、英文按词计量，统一成「字/分钟」的分子。"""
    return len(_HAN.findall(text)) + len(_LATIN_WORD.findall(text))


def count_fillers(text: str) -> int:
    lowered = text.lower()
    return sum(lowered.count(f) for f in _FILLERS)


def analyze(turns: list[TurnRecord], *, total_duration_ms: int) -> ProsodyReport:
    candidate = [t for t in turns if t.speaker is Speaker.CANDIDATE and t.text.strip()]
    if not candidate:
        return ProsodyReport(verdict="本场没有采集到有效的候选人语音。")

    speak_ms = sum(max(0, t.duration_ms) for t in candidate)
    units = sum(count_units(t.text) for t in candidate)
    fillers = sum(count_fillers(t.text) for t in candidate)

    pauses = _pauses(candidate)
    pause_total = sum(pauses)
    longest_pause = max(pauses, default=0)
    span = speak_ms + pause_total

    wpm = units / (speak_ms / 60000) if speak_ms > 0 else 0.0
    filler_ratio = fillers / (units / 100) if units >= 20 else 0.0
    pause_ratio = pause_total / span if span > 0 else 0.0

    per_question = _per_question(candidate)
    report = ProsodyReport(
        words_per_minute=round(wpm, 1),
        filler_ratio=round(filler_ratio, 2),
        pause_ratio=round(pause_ratio, 3),
        longest_pause_ms=longest_pause,
        speaking_ratio=round(speak_ms / total_duration_ms, 3) if total_duration_ms > 0 else 0.0,
        interrupted_count=sum(1 for t in candidate if t.was_interrupted),
        per_question=per_question,
    )
    report.verdict = _verdict(report)
    return report


def _pauses(candidate: list[TurnRecord]) -> list[int]:
    """同一个问题内相邻发言段之间的间隔视为思考停顿。"""
    gaps: list[int] = []
    for prev, cur in pairwise(candidate):
        if prev.question_index != cur.question_index:
            continue
        gap = cur.started_at_ms - (prev.started_at_ms + prev.duration_ms)
        if 400 <= gap <= 30000:
            gaps.append(gap)
    return gaps


def _per_question(candidate: list[TurnRecord]) -> list[QuestionProsody]:
    grouped: dict[int, list[TurnRecord]] = defaultdict(list)
    for turn in candidate:
        if turn.question_index is not None:
            grouped[turn.question_index].append(turn)

    result: list[QuestionProsody] = []
    for index, group in sorted(grouped.items()):
        speak_ms = sum(max(0, t.duration_ms) for t in group)
        units = sum(count_units(t.text) for t in group)
        gaps = _pauses(group)
        gap_total = sum(gaps)
        span = speak_ms + gap_total
        result.append(
            QuestionProsody(
                question_index=index,
                words_per_minute=round(units / (speak_ms / 60000), 1) if speak_ms > 0 else 0.0,
                filler_count=sum(count_fillers(t.text) for t in group),
                pause_ratio=round(gap_total / span, 3) if span > 0 else 0.0,
                longest_pause_ms=max(gaps, default=0),
            )
        )
    return result


def _verdict(report: ProsodyReport) -> str:
    issues: list[str] = []
    if report.words_per_minute >= _FAST_WPM:
        issues.append(f"整体语速偏快（{report.words_per_minute:.0f} 字/分，正常区间 180~300）")
    elif 0 < report.words_per_minute <= _SLOW_WPM:
        issues.append(f"整体语速偏慢（{report.words_per_minute:.0f} 字/分），显得不够自信")
    if report.filler_ratio >= _FILLER_PER_100:
        issues.append(f"口头禅密度偏高（每百字 {report.filler_ratio:.1f} 次）")
    if report.pause_ratio >= _HIGH_PAUSE_RATIO:
        issues.append(f"思考停顿占比 {report.pause_ratio * 100:.0f}%，答题过程断续")
    if report.longest_pause_ms >= _LONG_PAUSE_MS:
        issues.append(f"最长一次卡顿 {report.longest_pause_ms / 1000:.1f} 秒")
    if report.interrupted_count >= 2:
        issues.append(f"被面试官打断 {report.interrupted_count} 次，说明回答没有先给结论")

    worst = report.worst_question()
    if worst and issues:
        issues.append(f"问题最集中的是第 {worst.question_index} 题")

    if not issues:
        return (
            f"语速 {report.words_per_minute:.0f} 字/分、停顿占比 {report.pause_ratio * 100:.0f}%，"
            "节奏平稳，表达状态良好。"
        )
    return "；".join(issues) + "。"


def summary_for_model(report: ProsodyReport) -> str:
    """喂给复盘模型的客观指标，模型不得改动这些数字。"""
    lines = [
        f"语速：{report.words_per_minute:.0f} 字/分",
        f"口头禅密度：每百字 {report.filler_ratio:.1f} 次",
        f"思考停顿占比：{report.pause_ratio * 100:.0f}%",
        f"最长停顿：{report.longest_pause_ms / 1000:.1f} 秒",
        f"发言时长占比：{report.speaking_ratio * 100:.0f}%",
        f"被打断次数：{report.interrupted_count}",
    ]
    if report.per_question:
        worst = report.worst_question()
        if worst:
            lines.append(
                f"语速最快的一题：第 {worst.question_index} 题（{worst.words_per_minute:.0f} 字/分，"
                f"停顿占比 {worst.pause_ratio * 100:.0f}%）"
            )
    return "\n".join(lines)
