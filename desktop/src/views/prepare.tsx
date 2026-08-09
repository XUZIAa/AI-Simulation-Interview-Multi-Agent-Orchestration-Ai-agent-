import { open } from "@tauri-apps/plugin-dialog";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ClipboardPaste,
  Loader2,
  Play,
  Sparkles,
  Target,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  type InterviewState,
  type PersonaContract,
  type Schemas,
  type StoredGap,
  type StoredJob,
  type StoredResume,
  api,
  onEvent,
} from "@/lib/backend";
import { COMPANY_TIER, GAP_SEVERITY, JOB_LEVEL, labelOf } from "@/lib/labels";
import { cn } from "@/lib/utils";

type GapReport = Schemas["GapReport"];

const DURATIONS = [10, 20, 30, 45];

const TITLE_PRESETS = [
  "后端开发工程师",
  "前端开发工程师",
  "算法工程师",
  "数据开发工程师",
  "全栈工程师",
  "测试开发工程师",
  "运维/SRE",
  "客户端开发工程师",
];

const SEVERITY_STYLE: Record<string, string> = {
  blocker: "bg-destructive/10 text-destructive border-destructive/20",
  major: "bg-warning/10 text-warning border-warning/20",
  minor: "bg-muted text-muted-foreground",
};

const STEPS = [
  { title: "简历", heading: "先给我你的简历", hint: "AI 会解析你的经历与项目，据此设计问题" },
  { title: "目标岗位", heading: "你要面的是什么岗位", hint: "有 JD 就传，没有就填岗位名生成一份" },
  {
    title: "差距诊断",
    heading: "看看你和这个岗位差多少",
    hint: "做过这步，题库会围绕短板出题",
    optional: true,
  },
  { title: "面试设置", heading: "选面试官和节奏", hint: "确认后生成题库，约需一分钟" },
];

/** 一个长任务的界面状态。进度由后端按 task_id 通过事件回推。 */
interface TaskState {
  running: boolean;
  stage: string;
  percent: number;
  error: string;
}

const IDLE: TaskState = { running: false, stage: "", percent: 0, error: "" };

/** 已生成待用的题库 */
export interface PreparedBank {
  fingerprint: string;
  state: InterviewState;
}

interface Props {
  onStart: (state: InterviewState) => void;
  /** 出题要一分钟，缓存必须由不会卸载的上层持有，否则进房间再返回就白等一遍 */
  bank: React.RefObject<PreparedBank | null>;
}

export function PrepareView({ onStart, bank }: Props) {
  const [step, setStep] = useState(0);

  const [resumes, setResumes] = useState<StoredResume[]>([]);
  const [jobs, setJobs] = useState<StoredJob[]>([]);
  const [personas, setPersonas] = useState<PersonaContract[]>([]);

  const [resumeId, setResumeId] = useState<number | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const [personaName, setPersonaName] = useState("");
  const [tier, setTier] = useState("big_tech");
  const [level, setLevel] = useState("mid");
  const [minutes, setMinutes] = useState(30);
  const [coding, setCoding] = useState(false);

  const [gap, setGap] = useState<GapReport | null>(null);
  const [genTitle, setGenTitle] = useState("");
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState("");

  const [resumeTask, setResumeTask] = useState(IDLE);
  const [jobTask, setJobTask] = useState(IDLE);
  const [gapTask, setGapTask] = useState(IDLE);
  const [buildTask, setBuildTask] = useState(IDLE);

  const load = useCallback(async () => {
    try {
      const [r, j, p] = await Promise.all([
        api.get<StoredResume[]>("/library/resumes?limit=50"),
        api.get<StoredJob[]>("/library/jobs?limit=50"),
        api.get<PersonaContract[]>("/personas"),
      ]);
      setResumes(r);
      setJobs(j);
      setPersonas(p);
      setResumeId((prev) => prev ?? r[0]?.id ?? null);
      setJobId((prev) => prev ?? j[0]?.id ?? null);
      setPersonaName((prev) => prev || (p[0]?.name ?? ""));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载资料失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 长任务进度统一从这里进，按 task_id 分派
  useEffect(() => {
    return onEvent("task_progress", (data) => {
      const apply = (setter: typeof setResumeTask) =>
        setter((prev) => ({ ...prev, stage: data.stage, percent: data.percent }));
      if (data.task_id === "resume") apply(setResumeTask);
      else if (data.task_id === "job") apply(setJobTask);
      else if (data.task_id === "gap") apply(setGapTask);
      else if (data.task_id === "build") apply(setBuildTask);
    });
  }, []);

  const resume = resumes.find((r) => r.id === resumeId) ?? null;
  const job = jobs.find((j) => j.id === jobId) ?? null;
  const persona = personas.find((p) => p.name === personaName) ?? null;
  const canDiagnose = resume != null && job != null && !gapTask.running;
  const ready = resume != null && job != null && persona != null;
  const anyRunning =
    resumeTask.running || jobTask.running || gapTask.running || buildTask.running;

  // 每一步能否离开。诊断是可选的，不设门槛
  const passable = [resume != null, job != null, true, ready];
  // 能否直接跳到某一步：它前面所有必答步骤都过了
  const reachable = (i: number) => passable.slice(0, i).every(Boolean);

  const runTask = async <T,>(
    setter: (s: TaskState) => void,
    call: () => Promise<T>,
  ): Promise<T | null> => {
    setter({ running: true, stage: "正在处理", percent: 0, error: "" });
    try {
      const result = await call();
      setter({ ...IDLE, stage: "完成", percent: 100 });
      return result;
    } catch (err) {
      const message = err instanceof Error ? err.message : "处理失败";
      // 真实原因要留在界面上，toast 会消失
      setter({ ...IDLE, error: message });
      toast.error(message);
      return null;
    }
  };

  const pickResume = async () => {
    const path = await open({
      multiple: false,
      filters: [{ name: "简历", extensions: ["pdf", "docx", "txt", "md"] }],
    });
    if (typeof path !== "string") return;
    const stored = await runTask(setResumeTask, () =>
      api.post<StoredResume>("/prepare/resume", { path, task_id: "resume" }),
    );
    if (stored) {
      await load();
      setResumeId(stored.id);
      setGap(null);
      bank.current = null;
    }
  };

  const pickJobFile = async () => {
    const path = await open({
      multiple: false,
      filters: [{ name: "岗位描述", extensions: ["pdf", "docx", "txt", "md"] }],
    });
    if (typeof path !== "string") return;
    const stored = await runTask(setJobTask, () =>
      api.post<StoredJob>("/prepare/job-file", { path, task_id: "job" }),
    );
    if (stored) await afterJob(stored);
  };

  const submitPaste = async () => {
    const raw = pasteText.trim();
    if (!raw) return;
    setPasteOpen(false);
    const stored = await runTask(setJobTask, () =>
      api.post<StoredJob>("/prepare/job-text", { raw, task_id: "job" }),
    );
    setPasteText("");
    if (stored) await afterJob(stored);
  };

  const generateJob = async () => {
    const title = genTitle.trim();
    if (!title) {
      toast.error("先填岗位名称");
      return;
    }
    const stored = await runTask(setJobTask, () =>
      api.post<StoredJob>("/prepare/job-synthesize", {
        title,
        tier,
        level,
        task_id: "job",
      }),
    );
    if (stored) await afterJob(stored);
  };

  const afterJob = async (stored: StoredJob) => {
    await load();
    setJobId(stored.id);
    setGap(null);
    bank.current = null;
  };

  const diagnose = async () => {
    if (!resume || !job) return;
    const stored = await runTask(setGapTask, () =>
      api.post<StoredGap>("/prepare/diagnose", {
        resume_id: resume.id,
        job_id: job.id,
        task_id: "gap",
      }),
    );
    if (stored) setGap(stored.report);
  };

  const start = async () => {
    if (!ready || !persona || !resume || !job) return;
    const fingerprint = [
      persona.id ?? persona.name,
      resume.id,
      job.id,
      tier,
      level,
      minutes,
      coding,
    ].join("|");
    if (bank.current?.fingerprint === fingerprint) {
      onStart(bank.current.state);
      return;
    }
    const state = await runTask(setBuildTask, () =>
      api.post<InterviewState>("/prepare/session", {
        persona,
        resume_id: resume.id,
        job_id: job.id,
        tier,
        level,
        minutes,
        coding_enabled: coding,
        task_id: "build",
      }),
    );
    if (state) {
      bank.current = { fingerprint, state };
      onStart(state);
    }
  };

  const current = STEPS[step];
  const last = step === STEPS.length - 1;

  return (
    <div className="wizard-canvas h-full overflow-y-auto">
      <div className="mx-auto max-w-[680px] px-7 pt-11 pb-14">
        <h1 className="text-[26px] font-semibold tracking-[-0.025em]">完成这几步开始面试</h1>
        <p className="text-muted-foreground mt-2 text-[13.5px]">
          四步走完，AI 会据此生成一套贴合你经历的题库
        </p>

        <nav className="mt-7 flex items-center gap-1.5">
          {STEPS.map((s, i) => {
            const active = i === step;
            const done = i < step && passable[i];
            const open = reachable(i);
            return (
              <button
                key={s.title}
                type="button"
                disabled={!open}
                onClick={() => setStep(i)}
                className={cn(
                  "flex items-center gap-1.5 rounded-full py-1 pr-2.5 pl-1.5 text-[12.5px] transition-colors duration-150 ease-out",
                  active
                    ? "bg-card text-foreground border font-medium"
                    : open
                      ? "text-muted-foreground hover:text-foreground"
                      : "text-muted-foreground/40 cursor-not-allowed",
                )}
              >
                {done ? (
                  <Check className="text-success size-3.5" />
                ) : (
                  <span
                    className={cn(
                      "size-1.5 rounded-full",
                      active ? "bg-primary" : "bg-muted-foreground/35",
                    )}
                  />
                )}
                {s.title}
              </button>
            );
          })}
        </nav>

        {/* 堆叠的后层卡片只露出边缘，暗示这是一叠步骤而不是孤立一屏 */}
        <div className="relative mt-7">
          <div
            aria-hidden
            className="bg-card/40 absolute -top-3 right-6 left-6 h-12 rounded-t-2xl border border-b-0"
          />
          <div
            aria-hidden
            className="bg-card/70 absolute -top-1.5 right-3 left-3 h-12 rounded-t-2xl border border-b-0"
          />

          <section className="bg-card relative rounded-2xl border p-6 shadow-[0_1px_2px_rgba(16,18,29,0.04),0_14px_36px_-18px_rgba(16,18,29,0.16)]">
            <div className="flex items-baseline gap-2.5">
              <h2 className="text-[17px] font-semibold tracking-[-0.015em]">{current.heading}</h2>
              {current.optional && (
                <Badge variant="secondary" className="text-[10px]">
                  可跳过
                </Badge>
              )}
            </div>
            <p className="text-muted-foreground mt-1.5 text-[13px]">{current.hint}</p>

            <div className="mt-6">
            {step === 0 && (
              <div className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  <Select
                    value={resumeId != null ? String(resumeId) : ""}
                    onValueChange={(v) => {
                      setResumeId(Number(v));
                      setGap(null);
                      bank.current = null;
                    }}
                  >
                    <SelectTrigger className="min-w-[240px] flex-1">
                      <SelectValue placeholder="选择已有简历" />
                    </SelectTrigger>
                    <SelectContent>
                      {resumes.map((r) => (
                        <SelectItem key={r.id} value={String(r.id)}>
                          {r.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    variant="outline"
                    onClick={() => void pickResume()}
                    disabled={resumeTask.running}
                  >
                    {resumeTask.running ? <Loader2 className="animate-spin" /> : <Upload />}
                    上传新简历
                  </Button>
                </div>
                <TaskLine task={resumeTask} idle="支持 PDF / DOCX / TXT，解析期间请勿重复上传" />
                {resume && (
                  <dl className="divide-border divide-y border-t text-sm">
                    <Row label="候选人" value={resume.profile.candidate_name} />
                    <Row label="当前职位" value={resume.profile.current_title} />
                    <Row
                      label="经验"
                      value={
                        resume.profile.years_of_experience
                          ? `${resume.profile.years_of_experience} 年`
                          : ""
                      }
                    />
                    <Row
                      label="技能与项目"
                      value={`${resume.profile.skills.length} 项技能 · ${resume.profile.projects.length} 个项目`}
                    />
                  </dl>
                )}
              </div>
            )}

            {step === 1 && (
              <div className="space-y-6">
                <div className="grid gap-4 sm:grid-cols-2">
                  <Labeled label="公司类型">
                    <Select value={tier} onValueChange={setTier}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {Object.entries(COMPANY_TIER).map(([k, v]) => (
                          <SelectItem key={k} value={k}>
                            {v}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Labeled>
                  <Labeled label="目标级别">
                    <Select value={level} onValueChange={setLevel}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {Object.entries(JOB_LEVEL).map(([k, v]) => (
                          <SelectItem key={k} value={k}>
                            {v}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Labeled>
                </div>

                <div className="flex flex-wrap gap-2">
                  <Select
                    value={jobId != null ? String(jobId) : ""}
                    onValueChange={(v) => {
                      setJobId(Number(v));
                      setGap(null);
                      bank.current = null;
                    }}
                  >
                    <SelectTrigger className="min-w-[240px] flex-1">
                      <SelectValue placeholder="选择已有岗位" />
                    </SelectTrigger>
                    <SelectContent>
                      {jobs.map((j) => (
                        <SelectItem key={j.id} value={String(j.id)}>
                          {j.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    variant="outline"
                    onClick={() => void pickJobFile()}
                    disabled={jobTask.running}
                  >
                    <Upload />
                    上传文件
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => setPasteOpen(true)}
                    disabled={jobTask.running}
                  >
                    <ClipboardPaste />
                    粘贴文本
                  </Button>
                </div>

                <div className="space-y-2.5 border-t pt-5">
                  <p className="text-muted-foreground text-sm">
                    没有 JD？只填岗位名称，按上面的公司类型与级别生成一份贴合市场的
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Input
                      list="title-presets"
                      value={genTitle}
                      placeholder="如 后端开发工程师"
                      onChange={(e) => setGenTitle(e.target.value)}
                      className="min-w-[200px] flex-1"
                    />
                    <datalist id="title-presets">
                      {TITLE_PRESETS.map((t) => (
                        <option key={t} value={t} />
                      ))}
                    </datalist>
                    <Button
                      variant="outline"
                      onClick={() => void generateJob()}
                      disabled={jobTask.running}
                    >
                      {jobTask.running ? <Loader2 className="animate-spin" /> : <Sparkles />}
                      一键生成
                    </Button>
                  </div>
                </div>

                <TaskLine task={jobTask} idle="" />
                {job && (
                  <dl className="divide-border divide-y border-t text-sm">
                    <Row label="公司" value={job.description.company} />
                    <Row label="岗位" value={job.description.title} />
                    <Row
                      label="硬性要求"
                      value={
                        job.description.must_have.length
                          ? `${job.description.must_have.length} 条`
                          : ""
                      }
                    />
                  </dl>
                )}
              </div>
            )}

            {step === 2 && (
              <div className="space-y-5">
                <p className="text-muted-foreground text-sm leading-relaxed">
                  把简历和 JD 摆在一起比对：指出缺哪些硬性要求，并给出面试时用现有经历弥补的话术。
                </p>
                <div>
                  <Button onClick={() => void diagnose()} disabled={!canDiagnose}>
                    {gapTask.running ? <Loader2 className="animate-spin" /> : <Target />}
                    {gap ? "重新诊断" : "开始诊断"}
                  </Button>
                </div>
                <TaskLine task={gapTask} idle={canDiagnose ? "" : "先选好简历和岗位"} />
                {gap && <GapPanel report={gap} />}
              </div>
            )}

            {step === 3 && (
              <div className="space-y-6">
                <Labeled label="面试官">
                  <Select value={personaName} onValueChange={setPersonaName}>
                    <SelectTrigger>
                      <SelectValue placeholder="选择面试官" />
                    </SelectTrigger>
                    <SelectContent>
                      {personas.map((p) => (
                        <SelectItem key={p.id ?? p.name} value={p.name}>
                          {p.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Labeled>

                <Labeled label="面试时长（到点强制收尾）">
                  <div className="flex gap-2">
                    {DURATIONS.map((m) => (
                      <button
                        key={m}
                        type="button"
                        onClick={() => setMinutes(m)}
                        className={cn(
                          "h-9 flex-1 rounded-lg border text-sm transition-colors duration-150 ease-out",
                          minutes === m
                            ? "border-foreground/25 bg-accent font-medium"
                            : "text-muted-foreground hover:text-foreground hover:bg-accent/50",
                        )}
                      >
                        {m} 分钟
                      </button>
                    ))}
                  </div>
                </Labeled>

                <div className="flex items-center justify-between gap-4 border-t pt-5">
                  <div>
                    <p className="text-sm font-medium">代码沙盒环节</p>
                    <p className="text-muted-foreground mt-0.5 text-xs">
                      技术岗会插入手写代码并讲思路
                    </p>
                  </div>
                  <Switch checked={coding} onCheckedChange={setCoding} />
                </div>

                <TaskLine
                  task={buildTask}
                  idle={
                    bank.current ? "题库已生成，点开始直接进入" : "点开始会先生成题库，约需一分钟"
                  }
                />
              </div>
            )}
            </div>

            <div className="mt-7 flex items-center justify-between gap-3 border-t pt-5">
              {step > 0 ? (
                <Button variant="ghost" onClick={() => setStep(step - 1)} disabled={anyRunning}>
                  <ArrowLeft />
                  上一步
                </Button>
              ) : (
                <span />
              )}

              {last ? (
                <Button onClick={() => void start()} disabled={!ready || anyRunning}>
                  {buildTask.running ? <Loader2 className="animate-spin" /> : <Play />}
                  开始面试
                </Button>
              ) : (
                <Button
                  onClick={() => setStep(step + 1)}
                  disabled={!passable[step] || anyRunning}
                  title={passable[step] ? undefined : "先完成这一步"}
                >
                  下一步
                  <ArrowRight />
                </Button>
              )}
            </div>
          </section>
        </div>
      </div>

      <Dialog open={pasteOpen} onOpenChange={setPasteOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>粘贴岗位描述</DialogTitle>
            <DialogDescription>把 JD 原文贴进来，AI 会自动结构化</DialogDescription>
          </DialogHeader>
          <Textarea
            rows={12}
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
            placeholder="粘贴 JD 全文…"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setPasteOpen(false)}>
              取消
            </Button>
            <Button onClick={() => void submitPaste()} disabled={!pasteText.trim()}>
              解析
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** 摘要行。空值直接不渲染，避免出现「当前职位：」这种空标签 */
function Row({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className="flex items-baseline justify-between gap-4 py-2.5">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="selectable min-w-0 truncate text-right">{value}</dd>
    </div>
  );
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <Label className="text-muted-foreground text-xs font-normal">{label}</Label>
      {children}
    </div>
  );
}

function TaskLine({ task, idle }: { task: TaskState; idle: string }) {
  if (task.running) {
    return (
      <div className="space-y-1.5">
        <p className="text-muted-foreground text-sm">
          {task.stage} {task.percent > 0 && `· ${task.percent}%`}
        </p>
        <Progress value={task.percent} className="h-1" />
      </div>
    );
  }
  if (task.error) {
    return <p className="text-destructive selectable text-sm">{task.error}</p>;
  }
  return idle ? <p className="text-muted-foreground text-sm">{idle}</p> : null;
}

function GapPanel({ report }: { report: GapReport }) {
  return (
    <div className="space-y-6 border-t pt-6">
      <div className="flex items-baseline gap-4">
        <p data-numeric className="text-4xl font-semibold tracking-[-0.03em]">
          {report.match_score.toFixed(0)}
          <span className="text-muted-foreground ml-1 text-sm font-normal tracking-normal">
            / 100 匹配
          </span>
        </p>
      </div>
      {report.verdict && <p className="selectable text-sm leading-relaxed">{report.verdict}</p>}

      {report.gaps.length > 0 && (
        <div>
          <p className="text-muted-foreground mb-1 text-xs">技能盲区与补救话术</p>
          <div className="divide-border divide-y border-t">
            {report.gaps.slice(0, 6).map((g, i) => (
              <div key={`${g.skill}-${i}`} className="space-y-1.5 py-3.5">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium">{g.skill}</p>
                  <Badge variant="outline" className={SEVERITY_STYLE[g.severity]}>
                    {labelOf(GAP_SEVERITY, g.severity)}
                  </Badge>
                </div>
                {g.why_gap && (
                  <p className="text-muted-foreground selectable text-sm">缺口：{g.why_gap}</p>
                )}
                {g.talking_script && (
                  <p className="selectable text-sm">话术：{g.talking_script}</p>
                )}
                {g.study_hint && (
                  <p className="text-muted-foreground selectable text-xs">补强：{g.study_hint}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {report.matches.length > 0 && (
        <div className="space-y-2">
          <p className="text-muted-foreground text-xs">已匹配优势</p>
          <div className="flex flex-wrap gap-1.5">
            {report.matches.slice(0, 14).map((m, i) => (
              <Badge key={`${m.skill}-${i}`} variant="secondary">
                {m.skill}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {report.predicted_questions.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-muted-foreground text-xs">可能被问到</p>
          <ul className="space-y-1 text-sm">
            {report.predicted_questions.slice(0, 6).map((q, i) => (
              <li key={`${q}-${i}`} className="selectable text-muted-foreground">
                {q}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
