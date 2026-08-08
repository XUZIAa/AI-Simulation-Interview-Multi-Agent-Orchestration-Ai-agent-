from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...app.async_utils import spawn
from ...app.context import AppContext
from ...core.providers_catalog import model_traits
from ...core.types import CompanyTier, GapSeverity, JobLevel, SessionStatus
from ...data.repositories.library_repo import StoredGap, StoredJob, StoredResume
from ...domain.interview import InterviewState
from ...domain.persona import PersonaContract
from ...domain.resume import GapReport
from ...llm.router import ROLE_ANALYST
from ..navigation import Navigator
from ..theme import Color
from ..widgets.charts import ScoreRing
from ..widgets.common import (
    AutoLabel,
    Badge,
    Card,
    Chip,
    Divider,
    combo_enum,
    faint,
    ghost_button,
    h3,
    icon_button,
    lead,
    page_title,
    primary_button,
)
from ..widgets.flow_layout import FlowLayout

_SEVERITY_COLOR = {
    GapSeverity.BLOCKER: Color.DANGER,
    GapSeverity.MAJOR: Color.WARNING,
    GapSeverity.MINOR: Color.TEXT_FAINT,
}
_DURATIONS = (10, 20, 30, 45)


class _PasteDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("粘贴 JD 文本")
        self.setMinimumSize(560, 460)
        self.setStyleSheet(f"QDialog {{ background: {Color.BG_ELEVATED}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(h3("粘贴岗位描述"))
        self._edit = QPlainTextEdit()
        self._edit.setPlaceholderText("把 JD 原文贴进来，AI 会自动结构化。")
        layout.addWidget(self._edit, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(ghost_button("取消", self.reject))
        buttons.addWidget(primary_button("解析", self.accept))
        layout.addLayout(buttons)

    def text(self) -> str:
        return self._edit.toPlainText().strip()


class PrepareView(QWidget):
    def __init__(self, context: AppContext, nav: Navigator) -> None:
        super().__init__()
        self._ctx = context
        self._nav = nav
        self._resume: StoredResume | None = None
        self._job: StoredJob | None = None
        self._gap: StoredGap | None = None
        self._minutes = 30
        self._pending_persona = ""
        self._slow_warned = False
        # 已生成待用的题库。出题要花几十秒，进房间失败后不该让人再等一遍
        self._built: tuple[str, InterviewState] | None = None
        self._building = False
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        host = QWidget()
        self._layout = QVBoxLayout(host)
        self._layout.setContentsMargins(36, 30, 36, 30)
        self._layout.setSpacing(18)
        scroll.setWidget(host)

        head = QVBoxLayout()
        head.setSpacing(4)
        head.addWidget(page_title("准备面试"))
        head.addWidget(lead("上传简历与目标 JD，AI 会先诊断差距，再据此生成贴合你经历的题库。"))
        self._layout.addLayout(head)

        self._layout.addWidget(self._resume_card())
        self._layout.addWidget(self._job_card())
        self._layout.addWidget(self._gap_card())
        self._layout.addWidget(self._launch_card())
        self._layout.addStretch(1)

    # ---------- 简历 ----------

    def _resume_card(self) -> Card:
        card = Card()
        card.add(h3("1 · 简历"))
        self._resume_combo = QComboBox()
        self._resume_combo.currentIndexChanged.connect(self._on_resume_pick)
        self._resume_btn = icon_button("upload", "上传简历文件", self._upload_resume)
        self._resume_btn.setFixedWidth(150)
        card.add_layout(self._pick_row(self._resume_combo, self._resume_btn))
        self._resume_status = faint("支持 PDF / DOCX / TXT。", wrap=True)
        card.add(self._resume_status)
        self._resume_summary = AutoLabel()
        card.add(self._resume_summary)
        return card

    # ---------- 岗位 ----------

    def _job_card(self) -> Card:
        card = Card()
        card.add(h3("2 · 目标岗位"))
        tier_row = QHBoxLayout()
        tier_row.setSpacing(10)
        self._tier_combo = QComboBox()
        for tier in CompanyTier:
            self._tier_combo.addItem(tier.label, tier)
        self._tier_combo.setCurrentIndex(0)
        self._level_combo = QComboBox()
        for level in JobLevel:
            self._level_combo.addItem(level.label, level)
        self._level_combo.setCurrentIndex(2)
        tier_row.addWidget(self._labeled("公司类型", self._tier_combo), 1)
        tier_row.addWidget(self._labeled("目标级别", self._level_combo), 1)
        card.add_layout(tier_row)

        self._job_combo = QComboBox()
        self._job_combo.currentIndexChanged.connect(self._on_job_pick)
        card.add_layout(self._pick_row(self._job_combo, None))

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self._job_upload_btn = icon_button("upload", "上传 JD 文件", self._upload_job)
        self._job_paste_btn = icon_button("copy", "粘贴 JD 文本", self._paste_job)
        actions.addWidget(self._job_upload_btn)
        actions.addWidget(self._job_paste_btn)
        actions.addStretch(1)
        card.add_layout(actions)

        gen = Card(elevated=False)
        gen.body().setSpacing(10)
        gen.add(faint("没有 JD？只填岗位名称，按上面的公司类型与级别一键生成一份贴合市场的 JD。"))
        gen_row = QHBoxLayout()
        gen_row.setSpacing(10)
        self._gen_title = QComboBox()
        self._gen_title.setEditable(True)
        self._gen_title.addItems(
            ["后端开发工程师", "前端开发工程师", "算法工程师", "数据开发工程师",
             "全栈工程师", "测试开发工程师", "运维/SRE", "客户端开发工程师"]
        )
        self._gen_title.setCurrentText("")
        self._gen_btn = icon_button("sparkles", "一键生成 JD", self._generate_job, kind="Primary")
        self._gen_btn.setFixedWidth(150)
        gen_row.addWidget(self._gen_title, 1)
        gen_row.addWidget(self._gen_btn)
        gen.add_layout(gen_row)
        card.add(gen)

        self._job_status = AutoLabel(color=Color.TEXT_FAINT)
        card.add(self._job_status)
        self._job_summary = AutoLabel()
        card.add(self._job_summary)
        return card

    # ---------- 差距 ----------

    def _gap_card(self) -> Card:
        card = Card()
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(h3("3 · 差距诊断"))
        top.addWidget(Badge("可选", color=Color.TEXT_FAINT))
        top.addStretch(1)
        self._diag_btn = icon_button("target", "开始诊断", self._diagnose, kind="Primary")
        self._diag_btn.setFixedWidth(130)
        self._diag_btn.setEnabled(False)
        top.addWidget(self._diag_btn)
        card.add_layout(top)
        card.add(
            faint(
                "把简历和 JD 摆在一起比对：指出你缺哪些硬性要求，"
                "并给出面试时怎么用现有经历弥补的话术。做过这步，题库会围绕你的短板出题。",
                wrap=True,
            )
        )
        self._gap_status = faint("先选好简历和岗位，才能开始诊断。", wrap=True)
        card.add(self._gap_status)
        self._gap_body = QVBoxLayout()
        self._gap_body.setSpacing(12)
        card.add_layout(self._gap_body)
        return card

    # ---------- 开始 ----------

    def _launch_card(self) -> Card:
        card = Card()
        card.add(h3("4 · 面试设置"))
        row = QHBoxLayout()
        row.setSpacing(10)
        self._persona_combo = QComboBox()
        row.addWidget(self._labeled("面试官", self._persona_combo), 2)
        card.add_layout(row)

        dur_wrap = QVBoxLayout()
        dur_wrap.setSpacing(6)
        dur_wrap.addWidget(faint("面试时长（到点强制收尾）"))
        dur_row = QHBoxLayout()
        dur_row.setSpacing(8)
        self._dur_group = QButtonGroup(self)
        self._dur_group.setExclusive(True)
        for minutes in _DURATIONS:
            btn = QPushButton(f"{minutes} 分钟")
            btn.setObjectName("Choice")
            btn.setCheckable(True)
            btn.setChecked(minutes == self._minutes)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(40)
            btn.clicked.connect(lambda _=False, m=minutes: self._set_minutes(m))
            self._dur_group.addButton(btn, minutes)
            dur_row.addWidget(btn)
        dur_row.addStretch(1)
        self._dur_group.button(30).setChecked(True)
        dur_wrap.addLayout(dur_row)
        card.add_layout(dur_wrap)

        self._coding_chip = Chip("开启代码沙盒环节", selectable=True)
        coding_row = QHBoxLayout()
        coding_row.addWidget(self._coding_chip)
        coding_row.addStretch(1)
        card.add_layout(coding_row)

        card.add(Divider())
        self._launch_status = faint("需要先备好简历、岗位与面试官。")
        card.add(self._launch_status)
        self._start_btn = icon_button("play", "开始面试", self._start, kind="Primary")
        self._start_btn.setEnabled(False)
        card.add(self._start_btn)
        return card

    # ---------- 布局辅助 ----------

    def _pick_row(self, combo: QComboBox, button: QPushButton | None):
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(combo, 1)
        if button is not None:
            row.addWidget(button)
        return row

    def _labeled(self, caption: str, widget: QWidget) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(faint(caption))
        layout.addWidget(widget)
        return wrap

    def _set_minutes(self, minutes: int) -> None:
        self._minutes = minutes

    # ---------- 数据加载 ----------

    def on_show(self) -> None:
        spawn(self._load_lists(), context="加载准备资料")
        spawn(self._drop_used_build(), context="校验已生成题库")
        self._warn_slow_model()

    async def _drop_used_build(self) -> None:
        """已经开过的场次不能复用：那一场的题库连同记录都属于它自己。

        启动失败会把状态回滚成 DRAFT，这种才是真正没用过、可以直接再进的。
        """
        built = self._built
        if built is None:
            return
        status = await self._ctx.sessions.status(built[1].session_id)
        if status is not SessionStatus.DRAFT:
            self._built = None
            self._refresh_gates()

    def _warn_slow_model(self) -> None:
        """推理模型跑解析和出题会慢到分钟级，进页面就先讲清楚，别让人干等。"""
        if self._slow_warned:
            return
        model = self._ctx.config.settings.chat_model(ROLE_ANALYST)
        if not model_traits(model).reasoning:
            return
        self._slow_warned = True
        self._nav.toast(
            f"分析师用的是推理模型 {model}，解析简历与出题每步都要数分钟。"
            "到「设置」换成 deepseek-chat 会快很多。",
            kind="warning",
        )

    def preselect_persona(self, contract: PersonaContract) -> None:
        """从工作台"快速开始"进来时带上指定面试官，列表可能还没加载完，先挂起。"""
        self._pending_persona = contract.name
        self._apply_pending_persona()

    def _apply_pending_persona(self) -> None:
        if not self._pending_persona:
            return
        for i in range(self._persona_combo.count()):
            data = self._persona_combo.itemData(i)
            if data is not None and data.name == self._pending_persona:
                self._persona_combo.setCurrentIndex(i)
                self._pending_persona = ""
                return

    async def _load_lists(self) -> None:
        resumes = await self._ctx.library.list_resumes()
        jobs = await self._ctx.library.list_jobs()
        personas = await self._ctx.personas.list_all()

        self._fill_combo(self._resume_combo, [("选择已有简历…", None)] + [(r.label, r) for r in resumes])
        self._fill_combo(self._job_combo, [("选择已有岗位…", None)] + [(j.label, j) for j in jobs])
        self._persona_combo.clear()
        for persona in personas:
            self._persona_combo.addItem(f"{persona.name}（{persona.company_tier.label}）", persona)
        self._apply_pending_persona()
        self._refresh_gates()

    @staticmethod
    def _fill_combo(combo: QComboBox, items: list[tuple[str, object]]) -> None:
        combo.blockSignals(True)
        combo.clear()
        for label, data in items:
            combo.addItem(label, data)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _on_resume_pick(self) -> None:
        data = self._resume_combo.currentData()
        if isinstance(data, StoredResume):
            self._resume = data
            self._gap = None
            self._render_resume()
        self._refresh_gates()

    def _on_job_pick(self) -> None:
        data = self._job_combo.currentData()
        if isinstance(data, StoredJob):
            self._job = data
            self._gap = None
            self._render_job()
        self._refresh_gates()

    def _render_resume(self) -> None:
        if self._resume is None:
            return
        p = self._resume.profile
        bits = [f"{p.candidate_name or '候选人'}"]
        if p.years_of_experience:
            bits.append(f"{p.years_of_experience:g} 年经验")
        if p.skills:
            bits.append("技能：" + "、".join(p.skills[:12]))
        self._resume_summary.setText("　·　".join(bits))
        self._resume_status.setText(f"已选择：{self._resume.label}")

    def _render_job(self) -> None:
        if self._job is None:
            return
        jd = self._job.description
        bits = [f"{jd.company} {jd.title}".strip()]
        if jd.must_have:
            bits.append("硬性要求：" + "、".join(jd.must_have[:10]))
        self._job_summary.setText("\n".join(bits))
        self._job_status.setText(f"已选择：{self._job.label}")

    # ---------- 异步动作 ----------

    @staticmethod
    def _set_status(label: QLabel, text: str, *, error: bool = False) -> None:
        label.setText(text)
        color = Color.DANGER if error else Color.TEXT_FAINT
        label.setStyleSheet(f"color: {color}; font-size: 13px;")

    def _run(
        self,
        factory: Callable[[Callable[[str, int], None]], Awaitable],
        status: QLabel,
        *lock: QWidget,
    ) -> None:
        """跑一步资料处理。lock 里的控件在解析期间禁用，避免重复提交。"""
        for widget in lock:
            widget.setEnabled(False)

        def progress(stage: str, pct: int) -> None:
            self._set_status(status, f"{stage} … {pct}%")

        def restore() -> None:
            for widget in lock:
                widget.setEnabled(True)

        def ok(result) -> None:
            restore()
            self._on_step_done(result)

        def err(exc: Exception) -> None:
            restore()
            # 真实原因要留在界面上，toast 会消失
            reason = getattr(exc, "user_message", "") or str(exc) or exc.__class__.__name__
            self._set_status(status, reason, error=True)
            self._nav.toast(reason, kind="error")

        spawn(factory(progress), on_success=ok, on_error=err, context="资料处理")

    def _on_step_done(self, result) -> None:
        if isinstance(result, StoredResume):
            self._resume = result
            self._gap = None
            spawn(self._reload_resumes(result), context="刷新简历列表")
        elif isinstance(result, StoredJob):
            self._job = result
            self._gap = None
            spawn(self._reload_jobs(result), context="刷新岗位列表")
        elif isinstance(result, StoredGap):
            self._gap = result
            self._render_gap(result.report)
            self._gap_status.setText("诊断完成")
        self._refresh_gates()

    async def _reload_resumes(self, current: StoredResume) -> None:
        resumes = await self._ctx.library.list_resumes()
        self._fill_combo(self._resume_combo, [("选择已有简历…", None)] + [(r.label, r) for r in resumes])
        idx = self._resume_combo.findData(current)
        for i in range(self._resume_combo.count()):
            data = self._resume_combo.itemData(i)
            if isinstance(data, StoredResume) and data.id == current.id:
                idx = i
                break
        if idx >= 0:
            self._resume_combo.setCurrentIndex(idx)
        self._render_resume()
        self._refresh_gates()

    async def _reload_jobs(self, current: StoredJob) -> None:
        jobs = await self._ctx.library.list_jobs()
        self._fill_combo(self._job_combo, [("选择已有岗位…", None)] + [(j.label, j) for j in jobs])
        for i in range(self._job_combo.count()):
            data = self._job_combo.itemData(i)
            if isinstance(data, StoredJob) and data.id == current.id:
                self._job_combo.setCurrentIndex(i)
                break
        self._render_job()
        self._refresh_gates()

    def _upload_resume(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择简历", "", "文档 (*.pdf *.docx *.txt *.md)")
        if not path:
            return
        self._run(
            lambda cb: self._ctx.prepare.ingest_resume(Path(path), on_progress=cb),
            self._resume_status,
            self._resume_btn,
            self._resume_combo,
        )

    def _upload_job(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 JD 文件", "", "文档 (*.pdf *.docx *.txt *.md)")
        if not path:
            return
        self._run(
            lambda cb: self._ctx.prepare.ingest_job_file(Path(path), on_progress=cb),
            self._job_status,
            *self._job_locks(),
        )

    def _paste_job(self) -> None:
        dialog = _PasteDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        text = dialog.text()
        if not text:
            return
        self._run(
            lambda cb: self._ctx.prepare.ingest_job_text(text, on_progress=cb),
            self._job_status,
            *self._job_locks(),
        )

    def _job_locks(self) -> tuple[QWidget, ...]:
        """岗位来源互斥：任一路径在解析时，其余入口都锁住。"""
        return (
            self._job_upload_btn,
            self._job_paste_btn,
            self._gen_btn,
            self._job_combo,
            self._gen_title,
        )

    def _generate_job(self) -> None:
        title = self._gen_title.currentText().strip()
        if not title:
            self._nav.toast("先填岗位名称再生成", kind="warning")
            return
        tier = combo_enum(self._tier_combo, CompanyTier, CompanyTier.BIG_TECH)
        level = combo_enum(self._level_combo, JobLevel, JobLevel.MID)
        self._run(
            lambda cb: self._ctx.prepare.synthesize_job(title=title, tier=tier, level=level, on_progress=cb),
            self._job_status,
            *self._job_locks(),
        )

    def _diagnose(self) -> None:
        if self._resume is None or self._job is None:
            return
        self._run(
            lambda cb: self._ctx.prepare.diagnose(
                resume_id=self._resume.id, job_id=self._job.id, on_progress=cb
            ),
            self._gap_status,
            self._diag_btn,
        )

    def _render_gap(self, report: GapReport) -> None:
        while self._gap_body.count():
            item = self._gap_body.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

        head = QHBoxLayout()
        ring = ScoreRing(size=120)
        ring.set_score(report.match_score)
        head.addWidget(ring)
        verdict = QLabel(report.verdict or "已完成匹配分析")
        verdict.setWordWrap(True)
        verdict.setStyleSheet(f"color: {Color.TEXT}; font-size: 14px;")
        head.addWidget(verdict, 1)
        self._gap_body.addLayout(head)

        if report.gaps:
            self._gap_body.addWidget(faint("技能盲区与补救话术"))
            for gap in report.gaps[:6]:
                self._gap_body.addWidget(self._gap_item(gap))
        if report.matches:
            self._gap_body.addWidget(faint("已匹配优势"))
            flow_host = QWidget()
            flow = FlowLayout(flow_host, spacing=8)
            for match in report.matches[:14]:
                flow.addWidget(Chip(match.skill))
            self._gap_body.addWidget(flow_host)
        if report.predicted_questions:
            self._gap_body.addWidget(faint("可能被问到"))
            for q in report.predicted_questions[:6]:
                item = QLabel("· " + q)
                item.setWordWrap(True)
                item.setStyleSheet(f"color: {Color.TEXT_MUTED}; font-size: 13px;")
                self._gap_body.addWidget(item)

    def _gap_item(self, gap) -> QWidget:
        box = Card(elevated=False)
        box.body().setSpacing(6)
        top = QHBoxLayout()
        name = QLabel(gap.skill)
        name.setStyleSheet(f"color: {Color.TEXT}; font-weight: 600;")
        top.addWidget(name, 1)
        top.addWidget(Badge(gap.severity.label, color=_SEVERITY_COLOR.get(gap.severity, Color.WARNING)))
        box.add_layout(top)
        if gap.why_gap:
            box.add(self._small(f"缺口：{gap.why_gap}", Color.TEXT_MUTED))
        if gap.talking_script:
            box.add(self._small(f"话术：{gap.talking_script}", Color.ACCENT))
        if gap.study_hint:
            box.add(self._small(f"补强：{gap.study_hint}", Color.TEXT_FAINT))
        return box

    def _small(self, text: str, color: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {color}; font-size: 13px;")
        return lbl

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

    # ---------- 门槛 ----------

    def _refresh_gates(self) -> None:
        self._diag_btn.setEnabled(self._resume is not None and self._job is not None)
        ready = self._resume is not None and self._job is not None and self._persona_combo.count() > 0
        # 出题期间必须一直压着按钮：这个方法会被列表刷新、重进本页等多条路径调到，
        # 无条件放开就等于允许再点一次，于是同一份资料被并发出题、多创建一场会话
        self._start_btn.setEnabled(ready and not self._building)
        if self._building:
            return
        if not ready:
            self._launch_status.setText("需要先备好简历、岗位与面试官。")
        elif self._built is not None:
            self._launch_status.setText("题库已生成，点「开始面试」直接进入。")
        else:
            self._launch_status.setText("资料齐了，点「开始面试」会先生成题库，约需一分钟。")

    def _fingerprint(
        self,
        persona: PersonaContract,
        resume: StoredResume,
        job: StoredJob,
        tier: CompanyTier,
        level: JobLevel,
        coding: bool,
    ) -> str:
        """题库复用的判据：这些输入一样，生成的题库就该是同一份。"""
        parts = (
            str(persona.id or persona.name),
            str(resume.id),
            str(job.id),
            tier.value,
            level.value,
            str(self._minutes),
            str(int(coding)),
        )
        return "|".join(parts)

    def _start(self) -> None:
        persona = self._persona_combo.currentData()
        if not isinstance(persona, PersonaContract) or self._resume is None or self._job is None:
            return
        tier = combo_enum(self._tier_combo, CompanyTier, CompanyTier.BIG_TECH)
        level = combo_enum(self._level_combo, JobLevel, JobLevel.MID)
        coding = self._coding_chip.selected
        self._start_btn.setEnabled(False)

        fingerprint = self._fingerprint(persona, self._resume, self._job, tier, level, coding)
        if self._built is not None and self._built[0] == fingerprint:
            self._launch(self._built[1])
            return

        self._building = True
        self._launch_status.setText("正在生成题库并排定流程…")

        def progress(stage: str, pct: int) -> None:
            self._launch_status.setText(f"{stage} … {pct}%")

        def ready(state: InterviewState) -> None:
            self._building = False
            self._built = (fingerprint, state)
            self._launch(state)

        def failed(exc: Exception) -> None:
            self._building = False
            self._launch_failed(exc)

        spawn(
            self._ctx.prepare.build_session(
                persona=persona,
                resume_id=self._resume.id,
                job_id=self._job.id,
                tier=tier,
                level=level,
                minutes=self._minutes,
                coding_enabled=coding,
                on_progress=progress,
            ),
            on_success=ready,
            on_error=failed,
            context="准备面试",
        )

    def _launch(self, state: InterviewState) -> None:
        # 不在这里恢复按钮：马上就跳进房间了，恢复只会让人以为还要再点一次。
        # 若房间没起来退回本页，on_show 会重新算门槛并放开按钮。
        self._launch_status.setText("正在进入面试…")
        self._nav.start_interview(state)

    def _launch_failed(self, exc: Exception) -> None:
        self._start_btn.setEnabled(True)
        reason = getattr(exc, "user_message", "") or str(exc) or exc.__class__.__name__
        self._set_status(self._launch_status, reason, error=True)
        self._nav.toast(reason, kind="error")
