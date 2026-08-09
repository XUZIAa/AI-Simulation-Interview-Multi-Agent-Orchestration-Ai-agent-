import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ClipboardList,
  FileDown,
  FileWarning,
  Gauge,
  Loader2,
  Radar as RadarIcon,
  Sparkles,
  Target,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from "recharts";
import { toast } from "sonner";

import { EmptyState, PageContainer } from "@/components/page-container";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { type ReviewReport, type Schemas, type TurnRecord, api, onEvent } from "@/lib/backend";
import { ANNOTATION_KIND, GAP_SEVERITY, SCORE_DIMENSION, labelOf } from "@/lib/labels";
import { cn } from "@/lib/utils";

type SessionSummary = Schemas["SessionSummary"];

const ANNOTATION_STYLE: Record<string, string> = {
  strength: "border-l-success bg-success/5",
  weakness: "border-l-destructive bg-destructive/5",
  filler: "border-l-warning bg-warning/5",
  off_topic: "border-l-muted-foreground bg-muted/40",
};

const ANNOTATION_BADGE: Record<string, string> = {
  strength: "bg-success/10 text-success border-success/20",
  weakness: "bg-destructive/10 text-destructive border-destructive/20",
  filler: "bg-warning/10 text-warning border-warning/20",
  off_topic: "bg-muted text-muted-foreground",
};

const DIM_COLOR = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--interviewer)",
];

type Phase = "loading" | "generating" | "ready" | "absent" | "too_short" | "prompt";

interface Props {
  sessionId: number;
  autoGenerate: boolean;
  onBack: () => void;
}

export function ReviewView({ sessionId, autoGenerate, onBack }: Props) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [report, setReport] = useState<ReviewReport | null>(null);
  const [turns, setTurns] = useState<TurnRecord[]>([]);
  const [title, setTitle] = useState("面试复盘");
  const [progress, setProgress] = useState({ stage: "", percent: 0 });

  // 复盘要跑多个模型调用，几十秒起，没有进度反馈用户会以为卡死
  useEffect(() => {
    return onEvent("review_progress", (data) =>
      setProgress({ stage: data.stage, percent: data.percent }),
    );
  }, []);

  const generate = useCallback(async () => {
    setPhase("generating");
    setProgress({ stage: "正在准备", percent: 0 });
    try {
      const fresh = await api.post<ReviewReport>("/review/generate", { session_id: sessionId });
      setReport(fresh);
      setPhase("ready");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "生成复盘失败");
      setPhase("prompt");
    }
  }, [sessionId]);

  useEffect(() => {
    void (async () => {
      setPhase("loading");
      try {
        const [existing, list, turnList] = await Promise.all([
          autoGenerate
            ? Promise.resolve(null)
            : api.get<ReviewReport | null>(`/review/${sessionId}`),
          api.get<SessionSummary[]>("/sessions?limit=80"),
          api.get<TurnRecord[]>(`/sessions/${sessionId}/turns`),
        ]);
        const summary = list.find((s) => s.id === sessionId);
        if (summary) setTitle(summary.title);
        setTurns(turnList);

        if (existing) {
          setReport(existing);
          setPhase("ready");
          return;
        }
        const state = await api.get<Schemas["InterviewState"] | null>(
          `/sessions/${sessionId}/state`,
        );
        if (!state) {
          setPhase("absent");
          return;
        }
        if (!state.reviewable) {
          setPhase("too_short");
          return;
        }
        if (autoGenerate) {
          await generate();
        } else {
          setPhase("prompt");
        }
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "加载复盘失败");
        setPhase("absent");
      }
    })();
  }, [sessionId, autoGenerate, generate]);

  const backButton = (
    <Button variant="outline" onClick={onBack}>
      <ArrowLeft />
      返回
    </Button>
  );

  if (phase !== "ready" || !report) {
    return (
      <PageContainer wide title={title} description="复盘报告" actions={backButton}>
        <Card>
          <CardContent>
            {phase === "loading" && (
              <div className="space-y-3 py-6">
                <Skeleton className="h-24 w-full" />
                <Skeleton className="h-40 w-full" />
              </div>
            )}
            {phase === "generating" && (
              <div className="space-y-3 py-12 text-center">
                <Loader2 className="text-primary mx-auto size-6 animate-spin" />
                <p className="text-sm font-medium">{progress.stage || "正在生成复盘"}</p>
                <Progress value={progress.percent} className="mx-auto h-1.5 max-w-sm" />
                <p className="text-muted-foreground text-xs">
                  要跑多轮模型分析，通常需要一分钟左右
                </p>
              </div>
            )}
            {phase === "prompt" && (
              <EmptyState
                icon={Sparkles}
                title="这场面试还没生成复盘"
                hint="生成过程会分析逐字稿、评分、重写答案并汇总错题"
                action={<Button onClick={() => void generate()}>生成复盘</Button>}
              />
            )}
            {phase === "too_short" && (
              <EmptyState
                icon={FileWarning}
                title="本场面试不足 5 分钟"
                hint="时长太短拿不到有意义的评估，记录已保留但不生成完整复盘"
              />
            )}
            {phase === "absent" && (
              <EmptyState icon={FileWarning} title="找不到这场面试的数据" />
            )}
          </CardContent>
        </Card>
      </PageContainer>
    );
  }

  const radarData = report.dimensions.map((d) => ({
    dimension: labelOf(SCORE_DIMENSION, d.dimension),
    score: Math.round(d.score),
  }));
  const turnById = new Map(turns.map((t) => [t.index, t]));

  return (
    <PageContainer
      wide
      title={title}
      description={`时长 ${Math.round(report.duration_ms / 60000)} 分钟`}
      actions={
        <>
          {backButton}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button onClick={() => window.print()}>
                <FileDown />
                导出 PDF
              </Button>
            </TooltipTrigger>
            <TooltipContent>在弹出的对话框里把目标选成「另存为 PDF」</TooltipContent>
          </Tooltip>
        </>
      }
    >
      <div className="space-y-4">
        <Card>
          <CardContent className="flex flex-wrap items-start gap-6">
            <ScoreRing score={report.overall_score} />
            <div className="min-w-[240px] flex-1 space-y-2">
              <p className="text-primary text-lg font-semibold">{report.headline || "面试复盘"}</p>
              {report.summary && (
                <p className="text-muted-foreground selectable text-sm leading-relaxed">
                  {report.summary}
                </p>
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <RadarIcon className="text-primary size-4" />
              多维能力
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-6 lg:grid-cols-[340px_1fr]">
            <div className="h-[300px]">
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={radarData} outerRadius="72%">
                  <PolarGrid stroke="var(--border)" />
                  <PolarAngleAxis
                    dataKey="dimension"
                    tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                  />
                  <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                  <Radar
                    dataKey="score"
                    stroke="var(--primary)"
                    fill="var(--primary)"
                    fillOpacity={0.25}
                    strokeWidth={2}
                  />
                </RadarChart>
              </ResponsiveContainer>
            </div>
            <div className="space-y-3">
              {report.dimensions.map((d, i) => (
                <div key={d.dimension} className="space-y-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-sm font-medium">
                      {labelOf(SCORE_DIMENSION, d.dimension)}
                    </span>
                    <span
                      className="text-sm font-bold"
                      style={{ color: DIM_COLOR[i % DIM_COLOR.length] }}
                    >
                      {d.score.toFixed(0)}
                    </span>
                  </div>
                  <div className="bg-muted h-1.5 overflow-hidden rounded-full">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{
                        width: `${Math.max(0, Math.min(100, d.score))}%`,
                        background: DIM_COLOR[i % DIM_COLOR.length],
                      }}
                    />
                  </div>
                  {d.reason && (
                    <p className="text-muted-foreground selectable text-xs">{d.reason}</p>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {(report.strengths.length > 0 || report.improvements.length > 0) && (
          <div className="grid gap-4 md:grid-cols-2">
            <BulletCard
              icon={CheckCircle2}
              title="亮点"
              tone="text-success"
              items={report.strengths}
            />
            <BulletCard
              icon={AlertTriangle}
              title="待改进"
              tone="text-warning"
              items={report.improvements}
            />
          </div>
        )}

        {report.prosody.verdict && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Gauge className="text-chart-5 size-4" />
                语速与停顿
              </CardTitle>
              <CardDescription>规则计算，不经模型判断</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <Badge variant="secondary">
                  语速 {report.prosody.words_per_minute.toFixed(0)} 字/分
                </Badge>
                <Badge variant="secondary">
                  口头禅 每百字 {report.prosody.filler_ratio.toFixed(1)}
                </Badge>
                <Badge variant="secondary">
                  停顿占比 {(report.prosody.pause_ratio * 100).toFixed(0)}%
                </Badge>
                <Badge variant="secondary">被打断 {report.prosody.interrupted_count} 次</Badge>
                <Badge variant="secondary">
                  最长停顿 {(report.prosody.longest_pause_ms / 1000).toFixed(1)} 秒
                </Badge>
              </div>
              <p className="text-muted-foreground selectable text-sm">{report.prosody.verdict}</p>
            </CardContent>
          </Card>
        )}

        {report.improvement_plans.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Target className="text-primary size-4" />
                专项提升方案
              </CardTitle>
              <CardDescription>针对本场暴露的短板，给出可执行的训练动作</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {report.improvement_plans.map((plan, i) => (
                <div key={`${plan.focus_area}-${i}`} className="bg-muted/40 space-y-2 rounded-lg p-4">
                  <p className="font-medium">{plan.focus_area}</p>
                  {plan.diagnosis && (
                    <p className="text-muted-foreground selectable text-sm">
                      诊断：{plan.diagnosis}
                    </p>
                  )}
                  {plan.expected_gain && (
                    <p className="text-success selectable text-sm">预期收益：{plan.expected_gain}</p>
                  )}
                  {plan.drills.length > 0 && (
                    <ul className="space-y-1 text-sm">
                      {plan.drills.map((drill, j) => (
                        <li key={`${drill.action}-${j}`} className="selectable">
                          · {drill.action}
                          {drill.time_cost && (
                            <span className="text-muted-foreground">（{drill.time_cost}）</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  {plan.resources.length > 0 && (
                    <p className="text-muted-foreground selectable text-xs">
                      推荐资料：{plan.resources.join("、")}
                    </p>
                  )}
                  {plan.next_mock_setup && (
                    <p className="text-muted-foreground selectable text-xs">
                      下次模拟建议：{plan.next_mock_setup}
                    </p>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {report.rewrites.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">满分答案重构</CardTitle>
              <CardDescription>结合你的真实经历改写，不是通用模板</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {report.rewrites.map((rw, i) => (
                <div key={`${rw.question_index}-${i}`} className="space-y-2">
                  <p className="selectable text-sm font-medium">{rw.question}</p>
                  {rw.original && (
                    <div className="border-muted-foreground/30 border-l-2 pl-3">
                      <p className="text-muted-foreground text-xs">你的回答</p>
                      <p className="text-muted-foreground selectable text-sm">{rw.original}</p>
                    </div>
                  )}
                  <div className="border-l-success bg-success/5 rounded-r-lg border-l-2 py-2 pl-3">
                    <p className="text-success text-xs">这么说更好</p>
                    <p className="selectable text-sm leading-relaxed">{rw.rewritten}</p>
                  </div>
                  {rw.why_better && (
                    <p className="text-muted-foreground selectable text-xs">
                      为什么更好：{rw.why_better}
                    </p>
                  )}
                  {i < report.rewrites.length - 1 && <div className="border-t pt-1" />}
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {report.annotations.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ClipboardList className="text-muted-foreground size-4" />
                逐字稿批注
              </CardTitle>
              <CardDescription>标出表现好与差的具体位置</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {report.annotations.map((note, i) => {
                const turn = turnById.get(note.turn_index);
                return (
                  <div
                    key={`${note.turn_index}-${i}`}
                    className={cn(
                      "space-y-1.5 rounded-r-lg border-l-2 py-2.5 pr-3 pl-3",
                      ANNOTATION_STYLE[note.kind] ?? "border-l-border",
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className={ANNOTATION_BADGE[note.kind]}>
                        {labelOf(ANNOTATION_KIND, note.kind)}
                      </Badge>
                      <span className="text-muted-foreground text-xs">
                        第 {note.turn_index + 1} 轮
                      </span>
                    </div>
                    {(note.quote || turn?.text) && (
                      <p className="selectable text-sm italic">
                        「{note.quote || turn?.text?.slice(0, 120)}」
                      </p>
                    )}
                    <p className="text-muted-foreground selectable text-sm">{note.comment}</p>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        )}

        {report.mistakes.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">本场错题</CardTitle>
              <CardDescription>已自动汇入错题本，可在那里统一复习</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {report.mistakes.map((m, i) => (
                <div key={`${m.knowledge_point}-${i}`} className="bg-muted/40 space-y-1 rounded-lg p-3">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium">{m.knowledge_point}</p>
                    <Badge variant="outline">{labelOf(GAP_SEVERITY, m.severity)}</Badge>
                  </div>
                  {m.review_hint && (
                    <p className="text-muted-foreground selectable text-sm">{m.review_hint}</p>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {report.abandoned_skills.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">放弃深挖的技能点</CardTitle>
              <CardDescription>连续答不上来时面试官会换方向，这些是当时停下的地方</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {report.abandoned_skills.map((s, i) => (
                <Badge key={`${s.skill}-${i}`} variant="secondary">
                  {s.skill}
                  <span className="text-muted-foreground ml-1">D{s.abandoned_at_depth}</span>
                </Badge>
              ))}
            </CardContent>
          </Card>
        )}

        {report.next_actions.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">接下来做什么</CardTitle>
            </CardHeader>
            <CardContent>
              <ol className="space-y-1.5">
                {report.next_actions.map((action, i) => (
                  <li key={`${action}-${i}`} className="flex gap-2 text-sm">
                    <span className="bg-primary/10 text-primary flex size-5 shrink-0 items-center justify-center rounded-full text-xs font-semibold">
                      {i + 1}
                    </span>
                    <span className="selectable">{action}</span>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
        )}
      </div>
    </PageContainer>
  );
}

function ScoreRing({ score }: { score: number }) {
  const clamped = Math.max(0, Math.min(100, score));
  const tone =
    clamped >= 80 ? "var(--success)" : clamped >= 60 ? "var(--warning)" : "var(--destructive)";
  return (
    <div className="relative size-32 shrink-0">
      <svg viewBox="0 0 100 100" className="size-full -rotate-90">
        <circle cx="50" cy="50" r="43" fill="none" stroke="var(--muted)" strokeWidth="9" />
        <circle
          cx="50"
          cy="50"
          r="43"
          fill="none"
          stroke={tone}
          strokeWidth="9"
          strokeLinecap="round"
          strokeDasharray={`${(clamped / 100) * 270} 270`}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-semibold tracking-tight">{clamped.toFixed(0)}</span>
        <span className="text-muted-foreground text-xs">综合得分</span>
      </div>
    </div>
  );
}

function BulletCard({
  icon: Icon,
  title,
  tone,
  items,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  tone: string;
  items: string[];
}) {
  if (items.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon className={cn("size-4", tone)} />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {items.map((item, i) => (
            <li key={`${item}-${i}`} className="flex gap-2 text-sm">
              <span className={cn("shrink-0", tone)}>•</span>
              <span className="text-muted-foreground selectable">{item}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
