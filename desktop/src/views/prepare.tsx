import { open } from "@tauri-apps/plugin-dialog";
import { ClipboardPaste, Loader2, Play, Sparkles, Target, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { PageContainer } from "@/components/page-container";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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

/** 一个长任务的界面状态。进度由后端按 task_id 通过事件回推。 */
interface TaskState {
  running: boolean;
  stage: string;
  percent: number;
  error: string;
}

const IDLE: TaskState = { running: false, stage: "", percent: 0, error: "" };

interface Props {
  onStart: (state: InterviewState) => void;
}

export function PrepareView({ onStart }: Props) {
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

  // 已生成待用的题库。出题要几十秒，进房间失败后不该让人再等一遍
  const built = useRef<{ fingerprint: string; state: InterviewState } | null>(null);

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

  // 长任务进度统一从这里进，按 task_id 分派到对应的卡片
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
      built.current = null;
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
    built.current = null;
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
    const fingerprint = [persona.id ?? persona.name, resume.id, job.id, tier, level, minutes, coding].join(
      "|",
    );
    if (built.current?.fingerprint === fingerprint) {
      onStart(built.current.state);
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
      built.current = { fingerprint, state };
      onStart(state);
    }
  };

  return (
    <PageContainer
      wide
      title="准备面试"
      description="上传简历与目标 JD，AI 会先诊断差距，再据此生成贴合你经历的题库"
    >
      <div className="space-y-4">
        <StepCard step={1} title="简历" done={resume != null}>
          <div className="flex flex-wrap gap-2">
            <Select
              value={resumeId != null ? String(resumeId) : ""}
              onValueChange={(v) => {
                setResumeId(Number(v));
                setGap(null);
                built.current = null;
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
            <Button variant="outline" onClick={() => void pickResume()} disabled={resumeTask.running}>
              {resumeTask.running ? <Loader2 className="animate-spin" /> : <Upload />}
              上传简历
            </Button>
          </div>
          <TaskLine task={resumeTask} idle="支持 PDF / DOCX / TXT。解析期间请勿重复上传" />
          {resume && (
            <p className="text-muted-foreground selectable text-sm">
              {[
                resume.profile.candidate_name,
                resume.profile.current_title,
                resume.profile.years_of_experience
                  ? `${resume.profile.years_of_experience} 年经验`
                  : "",
                resume.profile.skills.length ? `${resume.profile.skills.length} 项技能` : "",
                resume.profile.projects.length ? `${resume.profile.projects.length} 个项目` : "",
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
        </StepCard>

        <StepCard step={2} title="目标岗位" done={job != null}>
          <div className="grid gap-3 sm:grid-cols-2">
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
                built.current = null;
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
            <Button variant="outline" onClick={() => void pickJobFile()} disabled={jobTask.running}>
              <Upload />
              上传文件
            </Button>
            <Button variant="outline" onClick={() => setPasteOpen(true)} disabled={jobTask.running}>
              <ClipboardPaste />
              粘贴文本
            </Button>
          </div>

          <div className="bg-muted/50 space-y-2 rounded-lg p-3">
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
              <Button onClick={() => void generateJob()} disabled={jobTask.running}>
                {jobTask.running ? <Loader2 className="animate-spin" /> : <Sparkles />}
                一键生成
              </Button>
            </div>
          </div>

          <TaskLine task={jobTask} idle="" />
          {job && (
            <p className="text-muted-foreground selectable text-sm">
              {[
                job.description.company,
                job.description.title,
                job.description.must_have.length
                  ? `硬性要求 ${job.description.must_have.length} 条`
                  : "",
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
        </StepCard>

        <StepCard
          step={3}
          title="差距诊断"
          optional
          done={gap != null}
          action={
            <Button onClick={() => void diagnose()} disabled={!canDiagnose}>
              {gapTask.running ? <Loader2 className="animate-spin" /> : <Target />}
              开始诊断
            </Button>
          }
        >
          <p className="text-muted-foreground text-sm">
            把简历和 JD 摆在一起比对：指出缺哪些硬性要求，并给出面试时用现有经历弥补的话术。做过这步，题库会围绕短板出题。
          </p>
          <TaskLine
            task={gapTask}
            idle={canDiagnose ? "" : "先选好简历和岗位，才能开始诊断"}
          />
          {gap && <GapPanel report={gap} />}
        </StepCard>

        <StepCard step={4} title="面试设置" done={ready}>
          <div className="grid gap-3 sm:grid-cols-2">
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
                      "h-9 flex-1 rounded-lg border text-sm font-medium transition-colors",
                      minutes === m
                        ? "border-primary bg-primary text-primary-foreground"
                        : "hover:bg-accent",
                    )}
                  >
                    {m} 分钟
                  </button>
                ))}
              </div>
            </Labeled>
          </div>

          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm font-medium">代码沙盒环节</p>
              <p className="text-muted-foreground text-xs">技术岗会插入手写代码并讲思路</p>
            </div>
            <Switch checked={coding} onCheckedChange={setCoding} />
          </div>

          <TaskLine
            task={buildTask}
            idle={
              !ready
                ? "需要先备好简历、岗位与面试官"
                : built.current
                  ? "题库已生成，点开始直接进入"
                  : "点开始会先生成题库，约需一分钟"
            }
          />

          <Button
            size="lg"
            className="w-full"
            disabled={!ready || anyRunning}
            onClick={() => void start()}
          >
            {buildTask.running ? <Loader2 className="animate-spin" /> : <Play />}
            开始面试
          </Button>
        </StepCard>
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
    </PageContainer>
  );
}

function StepCard({
  step,
  title,
  done,
  optional,
  action,
  children,
}: {
  step: number;
  title: string;
  done: boolean;
  optional?: boolean;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <span
            className={cn(
              "flex size-6 items-center justify-center rounded-full text-xs font-semibold",
              done ? "bg-success text-background" : "bg-muted text-muted-foreground",
            )}
          >
            {step}
          </span>
          {title}
          {optional && (
            <Badge variant="secondary" className="text-[10px]">
              可选
            </Badge>
          )}
        </CardTitle>
        {action && <div className="col-start-2 row-span-2 row-start-1 justify-self-end">{action}</div>}
      </CardHeader>
      <CardContent className="space-y-3">{children}</CardContent>
    </Card>
  );
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
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
        <Progress value={task.percent} className="h-1.5" />
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
    <div className="space-y-4 border-t pt-4">
      <div className="flex items-start gap-4">
        <div className="relative size-20 shrink-0">
          <svg viewBox="0 0 100 100" className="size-full -rotate-90">
            <circle cx="50" cy="50" r="42" fill="none" stroke="var(--muted)" strokeWidth="10" />
            <circle
              cx="50"
              cy="50"
              r="42"
              fill="none"
              stroke="var(--primary)"
              strokeWidth="10"
              strokeLinecap="round"
              strokeDasharray={`${(report.match_score / 100) * 264} 264`}
            />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-lg font-semibold">
            {report.match_score.toFixed(0)}
          </span>
        </div>
        <p className="selectable flex-1 text-sm">{report.verdict || "已完成匹配分析"}</p>
      </div>

      {report.gaps.length > 0 && (
        <div className="space-y-2">
          <p className="text-muted-foreground text-xs">技能盲区与补救话术</p>
          {report.gaps.slice(0, 6).map((g, i) => (
            <div key={`${g.skill}-${i}`} className="bg-muted/40 space-y-1.5 rounded-lg p-3">
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
                <p className="text-accent-foreground selectable text-sm">话术：{g.talking_script}</p>
              )}
              {g.study_hint && (
                <p className="text-muted-foreground selectable text-xs">补强：{g.study_hint}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {report.matches.length > 0 && (
        <div className="space-y-1.5">
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
        <div className="space-y-1">
          <p className="text-muted-foreground text-xs">可能被问到</p>
          <ul className="text-muted-foreground space-y-0.5 text-sm">
            {report.predicted_questions.slice(0, 6).map((q, i) => (
              <li key={`${q}-${i}`} className="selectable">
                · {q}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
