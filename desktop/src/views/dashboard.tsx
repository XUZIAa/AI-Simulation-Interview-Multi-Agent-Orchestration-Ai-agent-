import {
  CheckCircle2,
  ChevronRight,
  Clock,
  FileText,
  History,
  type LucideIcon,
  PlayCircle,
  Plus,
  RotateCcw,
  TrendingUp,
  UserRound,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";

import { EmptyState, PageContainer } from "@/components/page-container";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type GlobalStats,
  type InterruptedSession,
  type PersonaContract,
  type SessionSummary,
  type TrendPoint,
  api,
} from "@/lib/backend";
import type { PageId } from "@/lib/pages";
import { cn } from "@/lib/utils";

/** 会话状态决定列表项的图标与色调，全部由后端 status 驱动 */
const STATUS_META: Record<
  string,
  { icon: LucideIcon; wrap: string; fg: string; text: string }
> = {
  completed: { icon: CheckCircle2, wrap: "bg-success/10", fg: "text-success", text: "已完成" },
  reviewing: { icon: Clock, wrap: "bg-warning/12", fg: "text-warning", text: "待复盘" },
  running: { icon: PlayCircle, wrap: "bg-primary/10", fg: "text-primary", text: "进行中" },
  aborted: { icon: XCircle, wrap: "bg-muted", fg: "text-muted-foreground", text: "已中止" },
  draft: { icon: FileText, wrap: "bg-muted", fg: "text-muted-foreground", text: "未开始" },
};

const FALLBACK_META = STATUS_META.draft;

/** 压力档位取自人设契约的 aggression（0~10），不按名字猜。
 *  颜色之外必须给文字，只靠色相传达信息对色觉障碍不可读。 */
function pressureTone(aggression: number): { wrap: string; fg: string; text: string } {
  if (aggression <= 3) return { wrap: "bg-chart-5/12", fg: "text-chart-5", text: "温和" };
  if (aggression <= 6) return { wrap: "bg-warning/12", fg: "text-warning", text: "偏紧" };
  return { wrap: "bg-destructive/10", fg: "text-destructive", text: "高压" };
}

function greeting(): string {
  const h = new Date().getHours();
  if (h < 6) return "夜深了";
  if (h < 11) return "早上好";
  if (h < 14) return "中午好";
  if (h < 18) return "下午好";
  return "晚上好";
}

/** 相对日期比绝对时间戳更好扫。超过一周才退回月日 */
function relDate(iso: string): string {
  const then = new Date(iso);
  const a = new Date(then.getFullYear(), then.getMonth(), then.getDate()).getTime();
  const now = new Date();
  const b = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const days = Math.round((b - a) / 86400000);
  if (days <= 0) return "今天";
  if (days === 1) return "昨天";
  if (days < 7) return `${days} 天前`;
  return then.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

interface Props {
  onNavigate: (page: PageId) => void;
  /** 启动时认领到的中断面试。扫描会改写会话状态，只能在启动时做一次 */
  interrupted: InterruptedSession[];
  onOpenReview: (sessionId: number, generate?: boolean) => void;
}

export function DashboardView({ onNavigate, interrupted, onOpenReview }: Props) {
  const [stats, setStats] = useState<GlobalStats | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [personas, setPersonas] = useState<PersonaContract[]>([]);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [s, list, ps, tr] = await Promise.all([
        api.get<GlobalStats>("/sessions/stats"),
        api.get<SessionSummary[]>("/sessions?limit=8"),
        api.get<PersonaContract[]>("/personas"),
        api.get<TrendPoint[]>("/trends/overall?limit=12"),
      ]);
      setStats(s);
      setSessions(list);
      setPersonas(ps);
      setTrend(tr);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载工作台失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const chartData = trend.map((p, i) => ({
    name: `${i + 1}`,
    score: Math.round(p.score * 10) / 10,
  }));

  const today = new Date().toLocaleDateString("zh-CN", { month: "long", day: "numeric" });
  const summary = stats
    ? stats.total_sessions > 0
      ? `今天是 ${today}，累计完成 ${stats.total_sessions} 场模拟`
      : `今天是 ${today}，还没有开始第一场`
    : `今天是 ${today}`;

  return (
    <PageContainer
      wide
      title={greeting()}
      description={summary}
      actions={
        <Button onClick={() => onNavigate("prepare")}>
          <Plus />
          开始新面试
        </Button>
      }
    >
      <div className="space-y-4">
        {interrupted.length > 0 && (
          <div className="border-warning/30 bg-warning/[0.07] flex items-center justify-between gap-4 rounded-xl border px-4 py-3">
            <div className="flex items-center gap-3">
              <span className="bg-warning/15 flex size-9 shrink-0 items-center justify-center rounded-lg">
                <RotateCcw className="text-warning size-4" />
              </span>
              <div className="min-w-0">
                <p className="text-[13px] font-medium">
                  有 {interrupted.length} 场面试没有正常结束
                </p>
                <p className="text-muted-foreground mt-0.5 text-xs">
                  记录已完整保留，可以去成长轨迹里补出复盘
                </p>
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={() => onNavigate("growth")}>
              去查看
            </Button>
          </div>
        )}

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.95fr)_minmax(0,1fr)]">
          <div className="space-y-4">
            <Panel
              title="最近面试"
              action={
                <button
                  type="button"
                  onClick={() => onNavigate("mistakes")}
                  className="text-primary flex items-center gap-0.5 text-[13px] font-medium hover:underline"
                >
                  全部错题
                  <ChevronRight className="size-3.5" />
                </button>
              }
              flush
            >
              {loading ? (
                <div className="space-y-4 p-5">
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                </div>
              ) : sessions.length === 0 ? (
                <EmptyState
                  icon={History}
                  title="还没有面试记录"
                  hint="完成第一场模拟后，这里会留下轨迹"
                  action={
                    <Button size="sm" onClick={() => onNavigate("prepare")}>
                      开始第一场
                    </Button>
                  }
                />
              ) : (
                <ul className="divide-border divide-y">
                  {sessions.map((s) => {
                    const meta = STATUS_META[s.status] ?? FALLBACK_META;
                    return (
                      <li key={s.id}>
                        <button
                          type="button"
                          onClick={() => onOpenReview(s.id)}
                          className="hover:bg-accent/40 flex w-full items-center gap-3 px-5 py-3.5 text-left transition-colors duration-150 ease-out"
                        >
                          <span
                            className={cn(
                              "flex size-9 shrink-0 items-center justify-center rounded-lg",
                              meta.wrap,
                            )}
                          >
                            <meta.icon className={cn("size-4", meta.fg)} />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-[13px] font-medium">
                              {s.title}
                            </span>
                            <span className="text-muted-foreground mt-0.5 block truncate text-xs">
                              <span data-numeric>
                                {s.persona_name} · {Math.round(s.duration_ms / 60000)} 分钟
                              </span>
                            </span>
                          </span>
                          <span className="shrink-0 text-right">
                            {s.overall_score != null ? (
                              <span
                                data-numeric
                                className="block text-[15px] font-semibold tracking-[-0.02em]"
                              >
                                {s.overall_score.toFixed(1)}
                              </span>
                            ) : (
                              <span className="text-muted-foreground block text-xs font-medium">
                                {meta.text}
                              </span>
                            )}
                            <span className="text-muted-foreground mt-0.5 block text-xs">
                              {relDate(s.created_at)}
                            </span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Panel>

            <Panel title="分数走势">
              <div className="h-56">
                {loading ? (
                  <Skeleton className="h-full w-full" />
                ) : chartData.length < 2 ? (
                  <EmptyState
                    icon={TrendingUp}
                    title="至少完成两场才能看出趋势"
                    hint="每场面试结束后生成复盘，分数会落在这里"
                  />
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 6, right: 6, bottom: 0, left: -22 }}>
                      <CartesianGrid stroke="var(--border)" vertical={false} />
                      <XAxis
                        dataKey="name"
                        tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis
                        domain={[0, 100]}
                        tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <Tooltip
                        cursor={{ stroke: "var(--border)" }}
                        contentStyle={{
                          background: "var(--popover)",
                          border: "1px solid var(--border)",
                          borderRadius: 10,
                          fontSize: 12,
                          color: "var(--popover-foreground)",
                        }}
                        labelFormatter={(v) => `第 ${v} 场`}
                        formatter={(v) => [`${v}`, "总分"]}
                      />
                      <Line
                        type="monotone"
                        dataKey="score"
                        stroke="var(--primary)"
                        strokeWidth={2}
                        dot={{ r: 2.5, fill: "var(--primary)", strokeWidth: 0 }}
                        activeDot={{ r: 4.5, strokeWidth: 0 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </div>
            </Panel>
          </div>

          <div className="space-y-4">
            <Panel title="能力概览">
              <div className="border-primary/15 bg-primary/[0.05] rounded-lg border p-4">
                <p className="text-muted-foreground text-xs">平均分</p>
                {stats ? (
                  <p data-numeric className="mt-1 text-3xl font-semibold tracking-[-0.03em]">
                    {stats.average_score != null ? stats.average_score.toFixed(1) : "—"}
                  </p>
                ) : (
                  <Skeleton className="mt-1.5 h-8 w-20" />
                )}
                <p className="text-muted-foreground mt-1.5 text-xs">
                  {stats?.best_score != null ? (
                    <span data-numeric>历史最高 {stats.best_score.toFixed(1)}</span>
                  ) : (
                    "完成复盘后开始累计"
                  )}
                </p>
              </div>

              <dl className="mt-4 space-y-3">
                <StatRow label="累计面试" value={stats ? `${stats.total_sessions}` : null} unit="场" />
                <StatRow
                  label="累计时长"
                  value={stats ? `${stats.total_minutes}` : null}
                  unit="分钟"
                />
                <StatRow
                  label="可用人设"
                  value={loading ? null : `${personas.length}`}
                  unit="个"
                />
              </dl>
            </Panel>

            <Panel title="快速开始" flush>
              {loading ? (
                <div className="space-y-4 p-5">
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                </div>
              ) : personas.length === 0 ? (
                <EmptyState
                  icon={UserRound}
                  title="还没有面试官"
                  hint="去人设工坊建一个"
                  action={
                    <Button size="sm" onClick={() => onNavigate("persona")}>
                      新建人设
                    </Button>
                  }
                />
              ) : (
                <ul className="divide-border divide-y">
                  {personas.slice(0, 4).map((p) => {
                    const tone = pressureTone(p.pressure.aggression);
                    return (
                      <li key={p.id ?? p.name}>
                        <button
                          type="button"
                          onClick={() => onNavigate("prepare")}
                          className="hover:bg-accent/40 group flex w-full items-center gap-3 px-5 py-3 text-left transition-colors duration-150 ease-out"
                        >
                          <span
                            className={cn(
                              "flex size-9 shrink-0 items-center justify-center rounded-lg",
                              tone.wrap,
                            )}
                          >
                            <UserRound className={cn("size-4", tone.fg)} />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-[13px] font-medium">{p.name}</span>
                            <span className="text-muted-foreground mt-0.5 block truncate text-xs">
                              {p.job_title || p.archetype} · {tone.text}
                            </span>
                          </span>
                          <ChevronRight className="text-muted-foreground size-4 shrink-0 opacity-0 transition-opacity duration-150 ease-out group-hover:opacity-60" />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Panel>
          </div>
        </div>
      </div>
    </PageContainer>
  );
}

/** 参考商业 SaaS 的面板规格：白底、1px 边框、无阴影、标题区带分隔线。
 *  flush 用于内容自带内边距的场景（列表项要整行可点，不能被外层 padding 截断）。 */
function Panel({
  title,
  action,
  flush,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  flush?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-card overflow-hidden rounded-xl border">
      <header className="flex items-center justify-between gap-3 border-b px-5 py-3.5">
        <h2 className="text-[15px] font-semibold tracking-[-0.01em]">{title}</h2>
        {action}
      </header>
      <div className={flush ? undefined : "p-5"}>{children}</div>
    </section>
  );
}

function StatRow({
  label,
  value,
  unit,
}: {
  label: string;
  value: string | null;
  unit: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      {value === null ? (
        <Skeleton className="h-4 w-10" />
      ) : (
        <dd data-numeric className="text-sm font-medium">
          {value}
          <span className="text-muted-foreground ml-1 text-xs font-normal">{unit}</span>
        </dd>
      )}
    </div>
  );
}
