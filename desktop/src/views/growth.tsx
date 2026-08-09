import { ArrowDown, ArrowUp, TrendingUp } from "lucide-react";
import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { toast } from "sonner";

import { EmptyState, PageContainer } from "@/components/page-container";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { type TrendPoint, api } from "@/lib/backend";
import { SCORE_DIMENSION } from "@/lib/labels";
import type { PageId } from "@/lib/pages";
import { cn } from "@/lib/utils";

const DIM_COLOR = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--interviewer)",
];

type DimensionSeries = Record<string, TrendPoint[]>;

interface Props {
  onNavigate: (page: PageId) => void;
}

export function GrowthView({ onNavigate }: Props) {
  const [overall, setOverall] = useState<TrendPoint[]>([]);
  const [dims, setDims] = useState<DimensionSeries>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void (async () => {
      try {
        const [o, d] = await Promise.all([
          api.get<TrendPoint[]>("/trends/overall?limit=30"),
          api.get<DimensionSeries>("/trends/dimensions?limit=30"),
        ]);
        setOverall(o);
        setDims(d);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "加载成长轨迹失败");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const overallData = overall.map((p) => ({
    name: shortDate(p.recorded_at),
    score: round1(p.score),
  }));

  const dimKeys = Object.keys(dims).filter((k) => (dims[k]?.length ?? 0) > 0);
  const longest = dimKeys.reduce((max, k) => Math.max(max, dims[k].length), 0);
  const dimData = Array.from({ length: longest }, (_, i) => {
    const row: Record<string, string | number> = { name: "" };
    for (const key of dimKeys) {
      const point = dims[key][i];
      if (!point) continue;
      row.name = shortDate(point.recorded_at);
      row[key] = round1(point.score);
    }
    return row;
  });

  const delta = overall.length >= 2 ? overall[overall.length - 1].score - overall[0].score : 0;
  const latest = overall.length > 0 ? overall[overall.length - 1].score : null;

  return (
    <PageContainer
      wide
      title="成长轨迹"
      description="从第一次模拟到最近一场，看着分数一点点涨起来"
    >
      {loading ? (
        <div className="space-y-4">
          <Skeleton className="h-72 w-full" />
          <Skeleton className="h-72 w-full" />
        </div>
      ) : overall.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState
              icon={TrendingUp}
              title="还没有成长数据"
              hint="完成一场面试并生成复盘后，这里会画出分数曲线。同一岗位多次模拟，曲线对比才有意义。"
              action={
                <Button size="sm" onClick={() => onNavigate("prepare")}>
                  开始一场面试
                </Button>
              }
            />
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">综合得分曲线</CardTitle>
              <CardDescription className="flex items-center gap-1.5">
                <span>最近 {latest?.toFixed(0)} 分</span>
                <span className="text-border">·</span>
                <span>共 {overall.length} 场</span>
                {overall.length >= 2 && (
                  <>
                    <span className="text-border">·</span>
                    <span
                      className={cn(
                        "inline-flex items-center gap-0.5",
                        delta >= 0 ? "text-success" : "text-destructive",
                      )}
                    >
                      {delta >= 0 ? (
                        <ArrowUp className="size-3" />
                      ) : (
                        <ArrowDown className="size-3" />
                      )}
                      较首场 {Math.abs(delta).toFixed(0)}
                    </span>
                  </>
                )}
              </CardDescription>
            </CardHeader>
            <CardContent className="h-64">
              {overallData.length < 2 ? (
                <EmptyState
                  icon={TrendingUp}
                  title="至少两场才能看出趋势"
                  hint="目前只有一场记录，再完成一场就能画出曲线"
                />
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={overallData} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="name" {...axisProps} />
                    <YAxis domain={[0, 100]} {...axisProps} />
                    <Tooltip {...tooltipProps} formatter={(v) => [`${v}`, "综合"]} />
                    <Line
                      type="monotone"
                      dataKey="score"
                      name="综合"
                      stroke="var(--primary)"
                      strokeWidth={2.2}
                      dot={{ r: 3 }}
                      activeDot={{ r: 5 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {dimKeys.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">各维度趋势</CardTitle>
                <CardDescription>技术深度、逻辑表达、抗压能力分别追踪</CardDescription>
              </CardHeader>
              <CardContent className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={dimData} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="name" {...axisProps} />
                    <YAxis domain={[0, 100]} {...axisProps} />
                    <Tooltip {...tooltipProps} />
                    <Legend
                      wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
                      iconType="circle"
                      iconSize={8}
                    />
                    {dimKeys.map((key, i) => (
                      <Line
                        key={key}
                        type="monotone"
                        dataKey={key}
                        name={SCORE_DIMENSION[key] ?? key}
                        stroke={DIM_COLOR[i % DIM_COLOR.length]}
                        strokeWidth={1.8}
                        dot={{ r: 2.5 }}
                        connectNulls
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </PageContainer>
  );
}

const axisProps = {
  tick: { fontSize: 11, fill: "var(--muted-foreground)" },
  axisLine: false,
  tickLine: false,
} as const;

const tooltipProps = {
  contentStyle: {
    background: "var(--popover)",
    border: "1px solid var(--border)",
    borderRadius: 10,
    fontSize: 12,
    color: "var(--popover-foreground)",
  },
} as const;

function shortDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}-${d.getDate()}`;
}

function round1(v: number): number {
  return Math.round(v * 10) / 10;
}
