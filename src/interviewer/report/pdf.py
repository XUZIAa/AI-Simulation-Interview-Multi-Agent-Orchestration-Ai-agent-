from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QMarginsF, QSizeF, QUrl
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument

from ..core.paths import export_dir
from ..core.types import GapSeverity
from ..data.repositories.review_repo import StoredMistake
from ..domain.review import ReviewReport
from ..ui.widgets.charts import RadarAxis, RadarChart

_INK = "#16181D"
_SUB = "#5C6270"
_LINE = "#E4E6EC"
_CARD = "#F7F8FA"
_ACCENT = "#5B5BD6"
_GOOD = "#0F8A5F"
_WARN = "#B4690E"
_BAD = "#DC2B3E"

_SEVERITY_TEXT = {
    GapSeverity.BLOCKER: ("致命缺口", _BAD),
    GapSeverity.MAJOR: ("重点缺口", _WARN),
    GapSeverity.MINOR: ("次要缺口", _SUB),
}

_FONT_CSS = "font-family:'Microsoft YaHei',sans-serif;"


def _esc(text: str) -> str:
    return html.escape(text or "").replace("\n", "<br>")


def _score_color(score: float) -> str:
    if score >= 80:
        return _GOOD
    if score >= 60:
        return _ACCENT
    if score >= 45:
        return _WARN
    return _BAD


def _radar_image(report: ReviewReport) -> QImage | None:
    dims = report.dimensions
    if len(dims) < 3:
        return None
    chart = RadarChart()
    chart.resize(460, 400)
    chart.set_axes([RadarAxis(label=d.dimension.label, value=d.score) for d in dims])
    image = QImage(460, 400, QImage.Format.Format_ARGB32)
    image.fill(0)
    chart.render(image)
    return image


def _bar(score: float) -> str:
    color = _score_color(score)
    width = max(2, min(100, int(score)))
    return (
        f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
        f'<td bgcolor="{color}" style="height:8px;width:{width}%;"></td>'
        f'<td style="height:8px;"></td></tr></table>'
    )


def _section(title: str, body: str) -> str:
    if not body.strip():
        return ""
    return (
        f'<p style="font-size:15pt;font-weight:bold;color:{_INK};'
        f'margin-top:20px;margin-bottom:6px;">{_esc(title)}</p>{body}'
    )


def _list(items: list[str], *, color: str = _INK) -> str:
    if not items:
        return ""
    rows = "".join(f'<li style="margin-bottom:3px;color:{color};">{_esc(x)}</li>' for x in items)
    return f'<ul style="margin-top:2px;">{rows}</ul>'


def _dimensions_html(report: ReviewReport) -> str:
    if not report.dimensions:
        return ""
    rows = ""
    for dim in report.dimensions:
        sc = _score_color(dim.score)
        rows += (
            f'<tr>'
            f'<td style="padding:6px 8px;color:{_INK};font-weight:bold;width:22%;">{_esc(dim.dimension.label)}</td>'
            f'<td style="padding:6px 8px;color:{sc};font-weight:bold;width:10%;">{dim.score:.0f}</td>'
            f'<td style="padding:6px 8px;width:28%;">{_bar(dim.score)}</td>'
            f'<td style="padding:6px 8px;color:{_SUB};">{_esc(dim.reason)}</td>'
            f'</tr>'
        )
    return f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:4px;">{rows}</table>'


def _prosody_html(report: ReviewReport) -> str:
    p = report.prosody
    if not p.verdict:
        return ""
    metrics = [
        f"语速 {p.words_per_minute:.0f} 字/分",
        f"口头禅每百字 {p.filler_ratio:.1f} 次",
        f"停顿占比 {p.pause_ratio * 100:.0f}%",
        f"被打断 {p.interrupted_count} 次",
    ]
    chips = "　".join(
        f'<span style="color:{_ACCENT};">{_esc(m)}</span>' for m in metrics
    )
    return (
        f'<p style="color:{_INK};margin:2px 0;">{chips}</p>'
        f'<p style="color:{_SUB};margin:4px 0;">{_esc(p.verdict)}</p>'
    )


def _plans_html(report: ReviewReport) -> str:
    if not report.improvement_plans:
        return ""
    blocks = ""
    for plan in report.improvement_plans:
        drills = "".join(
            f'<li style="color:{_INK};margin-bottom:2px;">{_esc(d.action)}'
            f'{f" · {_esc(d.time_cost)}" if d.time_cost else ""}</li>'
            for d in plan.drills
        )
        drills_html = f'<ul style="margin-top:4px;">{drills}</ul>' if drills else ""
        resources = ""
        if plan.resources:
            joined = _esc("、".join(plan.resources))
            resources = f'<p style="color:{_SUB};margin:2px 0;">推荐：{joined}</p>'
        nxt = ""
        if plan.next_mock_setup:
            nxt = f'<p style="color:{_SUB};margin:2px 0;">下次模拟：{_esc(plan.next_mock_setup)}</p>'
        blocks += (
            f'<div style="background:{_CARD};padding:10px 12px;margin-bottom:8px;">'
            f'<p style="font-weight:bold;color:{_ACCENT};margin:0 0 4px 0;">{_esc(plan.focus_area)}</p>'
            f'<p style="color:{_SUB};margin:2px 0;">{_esc(plan.diagnosis)}</p>'
            f'{drills_html}{resources}{nxt}</div>'
        )
    return blocks


def _rewrites_html(report: ReviewReport) -> str:
    if not report.rewrites:
        return ""
    blocks = ""
    for rw in report.rewrites[:6]:
        why = _list(rw.why_better, color=_SUB)
        blocks += (
            f'<div style="border-left:3px solid {_ACCENT};padding:4px 12px;margin-bottom:10px;">'
            f'<p style="color:{_INK};font-weight:bold;margin:0 0 4px 0;">{_esc(rw.question)}</p>'
            f'<p style="color:{_BAD};margin:2px 0;">你的回答：{_esc(rw.original)}</p>'
            f'<p style="color:{_GOOD};margin:2px 0;">满分示范：{_esc(rw.rewritten)}</p>'
            f'{why}</div>'
        )
    return blocks


def _mistakes_html(items: list) -> str:
    if not items:
        return ""
    blocks = ""
    for m in items:
        label, color = _SEVERITY_TEXT.get(m.severity, ("重点", _WARN))
        points = _list(list(m.key_points), color=_SUB)
        topic = f'　<span style="color:{_SUB};">{_esc(m.topic)}</span>' if m.topic else ""
        hint = f'<p style="color:{_SUB};margin:2px 0;">{_esc(m.review_hint)}</p>' if m.review_hint else ""
        blocks += (
            f'<div style="background:{_CARD};padding:10px 12px;margin-bottom:8px;">'
            f'<p style="margin:0 0 3px 0;"><b style="color:{_INK};">{_esc(m.knowledge_point)}</b>'
            f'　<span style="color:{color};">[{label}]</span>{topic}</p>'
            f'{hint}{points}</div>'
        )
    return blocks


def _build_html(report: ReviewReport, *, title: str, has_radar: bool) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    minutes = report.duration_ms // 60000
    overall_color = _score_color(report.overall_score)

    header = (
        f'<p style="font-size:22pt;font-weight:bold;color:{_INK};margin:0;">面试复盘报告</p>'
        f'<p style="color:{_SUB};margin:4px 0 0 0;">{_esc(title)}</p>'
        f'<p style="color:{_SUB};margin:2px 0 0 0;">生成于 {now}　·　时长 {minutes} 分钟</p>'
        f'<hr color="{_LINE}">'
    )

    overall = (
        f'<table width="100%"><tr>'
        f'<td style="font-size:40pt;font-weight:bold;color:{overall_color};width:130px;">{report.overall_score:.0f}'
        f'<span style="font-size:14pt;color:{_SUB};">/100</span></td>'
        f'<td style="color:{_INK};font-size:13pt;vertical-align:middle;">{_esc(report.headline)}</td>'
        f'</tr></table>'
    )
    if report.summary:
        overall += f'<p style="color:{_SUB};margin:6px 0;">{_esc(report.summary)}</p>'

    radar = (
        '<div align="center"><img src="mem://radar" width="360" height="313"></div>'
        if has_radar
        else ""
    )

    parts = [
        header,
        overall,
        _section("能力雷达", radar + _dimensions_html(report)),
        _section("亮点", _list(report.strengths, color=_GOOD)),
        _section("待改进", _list(report.improvements, color=_WARN)),
        _section("情绪与语速", _prosody_html(report)),
        _section("专项提升方案", _plans_html(report)),
        _section("满分答案重构", _rewrites_html(report)),
        _section("错题清单", _mistakes_html(report.mistakes)),
        _section("下一步行动", _list(report.next_actions, color=_INK)),
    ]
    body = "".join(parts)
    return f'<html><body style="{_FONT_CSS}color:{_INK};">{body}</body></html>'


def _write_pdf(html_body: str, path: Path, *, radar: QImage | None = None) -> Path:
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(14, 14, 14, 16), QPageLayout.Unit.Millimeter)
    writer.setResolution(96)

    doc = QTextDocument()
    if radar is not None:
        doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl("mem://radar"), radar)
    doc.setPageSize(QSizeF(writer.width(), writer.height()))
    doc.setHtml(html_body)
    doc.print_(writer)
    return path


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def export_review_pdf(report: ReviewReport, *, title: str) -> Path:
    radar = _radar_image(report)
    html_body = _build_html(report, title=title, has_radar=radar is not None)
    path = export_dir() / f"面试报告_{report.session_id}_{_timestamp()}.pdf"
    return _write_pdf(html_body, path, radar=radar)


def export_mistakes_pdf(items: list[StoredMistake]) -> Path:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    header = (
        f'<p style="font-size:22pt;font-weight:bold;color:{_INK};margin:0;">高频错题本</p>'
        f'<p style="color:{_SUB};margin:4px 0;">导出于 {now}　·　共 {len(items)} 条</p>'
        f'<hr color="{_LINE}">'
    )
    body = header + _mistakes_html([m.item for m in items])
    html_body = f'<html><body style="{_FONT_CSS}color:{_INK};">{body}</body></html>'
    path = export_dir() / f"错题本_{_timestamp()}.pdf"
    return _write_pdf(html_body, path)
