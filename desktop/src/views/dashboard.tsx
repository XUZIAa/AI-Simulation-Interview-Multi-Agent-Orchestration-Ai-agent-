import {
  Activity,
  Award,
  ChevronRight,
  Clock,
  History,
  LayoutDashboard,
  Plus,
  RotateCcw,
  TrendingUp,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";

import { EmptyState, PageContainer } from "@/components/page-container";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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

const STATUS_TEXT: Record<string, string> = {
  draft: "未开始",
  running: "进行中",
  // 强退的面试会被认领成这个状态，对用户来说是「还没出复盘」而非正在生成
  reviewing: "待复盘",
  completed: "已完成",
  aborted: "已中止",
};

interface Props {
  onNavigate: (page: PageId) => void;
  /** 启动时认领到的中断面试。扫描会改写会话状态，只能在启动时做一次 */
  interrupted: InterruptedSession[];
}

export function DashboardView({ onNavigate, interrupted }: Props) {
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

  return (
    <PageContainer
      wide
      title="工作台"
      description="准备好了就开始下一场模拟，每一场都会沉淀成你的成长轨迹"
      actions={
        <Button onClick={() => onNavigate("prepare")}>
          <Plus />
          开始新面试
        </Button>
      }
    >
      <div className="space-y-5">
        {interrupted.length > 0 && (
          <Card className="border-warning/40 bg-warning/5 gap-0 py-4">
            <CardContent className="flex items-center justify-between gap-4 px-5">
              <div className="flex items-center gap-3">
                <RotateCcw className="text-warning size-4 shrink-0" />
                <p className="text-sm">
                  检测到 {interrupted.length} 场未正常结束的面试，记录已保留
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={() => onNavigate("growth")}>
                去查看
              </Button>
            </CardContent>
          </Card>
        )}

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile
            icon={LayoutDashboard}
            label="累计面试"
            value={stats ? `${stats.total_sessions}` : null}
            unit="场"
            tone="text-primary"
          />
          <StatTile
            icon={Activity}
            label="平均分"
            value={fmt(stats?.average_score)}
            tone="text-chart-5"
          />
          <StatTile
            icon={Award}
            label="历史最高分"
            value={fmt(stats?.best_score)}
            tone="text-warning"
          />
          <StatTile
            icon={Clock}
            label="累计时长"
            value={stats ? `${stats.total_minutes}` : null}
            unit="分钟"
            tone="text-success"
          />
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <TrendingUp className="text-primary size-4" />
                分数走势
              </CardTitle>
            </CardHeader>
            <CardContent className="h-56">
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
                  <LineChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
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
                      dot={{ r: 3, fill: "var(--primary)" }}
                      activeDot={{ r: 5 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Zap className="text-warning size-4" />
                快速开始
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5">
              {loading ? (
                <>
                  <Skeleton className="h-11 w-full" />
                  <Skeleton className="h-11 w-full" />
                  <Skeleton className="h-11 w-full" />
                </>
              ) : (
                personas.slice(0, 4).map((p) => (
                  <button
                    key={p.id ?? p.name}
                    type="button"
                    onClick={() => onNavigate("prepare")}
                    className="hover:bg-accent flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors"
                  >
                    <span className="bg-primary/10 text-primary flex size-8 shrink-0 items-center justify-center rounded-lg text-xs font-semibold">
                      {p.name.slice(0, 2)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{p.name}</span>
                      <span className="text-muted-foreground block truncate text-xs">
                        {p.job_title || p.archetype}
                      </span>
                    </span>
                  </button>
                ))
              )}
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <History className="text-muted-foreground size-4" />
              最近面试
            </CardTitle>
            <CardAction>
              <Button variant="ghost" size="sm" onClick={() => onNavigate("mistakes")}>
                全部错题
                <ChevronRight />
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-2">
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
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
                {sessions.map((s) => (
                  <li key={s.id} className="flex items-center justify-between gap-3 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{s.title}</p>
                      <p className="text-muted-foreground text-xs">
                        {s.persona_name} · {new Date(s.created_at).toLocaleString("zh-CN")} ·{" "}
                        {Math.round(s.duration_ms / 60000)} 分钟
                      </p>
                    </div>
                    <span
                      className={cn(
                        "shrink-0 rounded-md px-2 py-0.5 text-xs font-medium",
                        s.overall_score != null
                          ? "bg-primary/10 text-primary"
                          : "bg-muted text-muted-foreground",
                      )}
                    >
                      {s.overall_score != null
                        ? s.overall_score.toFixed(1)
                        : (STATUS_TEXT[s.status] ?? s.status)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  );
}

function fmt(value: number | null | undefined): string | null {
  if (value == null) return "暂无";
  return value.toFixed(1);
}

function StatTile({
  icon: Icon,
  label,
  value,
  unit,
  tone,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string | null;
  unit?: string;
  tone: string;
}) {
  return (
    <Card className="gap-0 py-4">
      <CardContent className="px-5">
        <div className="flex items-center gap-1.5">
          <Icon className={cn("size-3.5", tone)} />
          <p className="text-muted-foreground text-xs">{label}</p>
        </div>
        {value === null ? (
          <Skeleton className="mt-2 h-7 w-16" />
        ) : (
          <p className="mt-1.5 text-2xl font-semibold tracking-tight">
            {value}
            {unit && <span className="text-muted-foreground ml-1 text-sm font-normal">{unit}</span>}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
