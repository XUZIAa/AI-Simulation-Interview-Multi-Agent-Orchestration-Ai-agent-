from __future__ import annotations

from ..core.types import Speaker
from ..domain.interview import InterviewState, QuestionRecord, TurnRecord


def _stamp(ms: int) -> str:
    total = max(0, ms) // 1000
    return f"{total // 60:02d}:{total % 60:02d}"


def format_turns(turns: list[TurnRecord], *, limit: int | None = None) -> str:
    """带轮次号的逐字稿。轮次号是批注锚点，格式不能随意改。"""
    selected = turns if limit is None else turns[-limit:]
    lines: list[str] = []
    for turn in selected:
        if not turn.text.strip():
            continue
        mark = "（被打断）" if turn.was_interrupted else ""
        lines.append(f"[#{turn.index} {_stamp(turn.started_at_ms)} {turn.speaker.label}]{mark} {turn.text}")
    return "\n".join(lines)


def format_questions(questions: list[QuestionRecord]) -> str:
    lines: list[str] = []
    for q in questions:
        if not q.spoken_text and not q.brief:
            continue
        lines.append(
            f"[Q{q.index} {q.phase.label}] 问：{q.spoken_text or q.brief}\n"
            f"        答：{q.answer_text.strip() or '（未作答）'}"
        )
    return "\n".join(lines)


def coding_summary(state: InterviewState) -> str:
    if not state.code_snapshot.strip():
        return ""
    return f"语言：{state.code_language}\n代码：\n```{state.code_language}\n{state.code_snapshot[:6000]}\n```"


def candidate_word_count(turns: list[TurnRecord]) -> int:
    return sum(len(t.text) for t in turns if t.speaker is Speaker.CANDIDATE)
