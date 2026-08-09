import { BookMarked, Check, Loader2, RotateCcw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { EmptyState, PageContainer } from "@/components/page-container";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { type Schemas, type StoredMistake, api } from "@/lib/backend";
import { GAP_SEVERITY, labelOf } from "@/lib/labels";
import type { PageId } from "@/lib/pages";

type Counts = Schemas["MistakeCounts"];

const SEVERITY_STYLE: Record<string, string> = {
  blocker: "bg-destructive/10 text-destructive border-destructive/20",
  major: "bg-warning/10 text-warning border-warning/20",
  minor: "bg-muted text-muted-foreground",
};

interface Props {
  onNavigate: (page: PageId) => void;
}

export function MistakesView({ onNavigate }: Props) {
  const [items, setItems] = useState<StoredMistake[]>([]);
  const [topics, setTopics] = useState<string[]>([]);
  const [topic, setTopic] = useState("__all__");
  const [includeMastered, setIncludeMastered] = useState(false);
  const [counts, setCounts] = useState<Counts | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const query = new URLSearchParams({
        include_mastered: String(includeMastered),
        limit: "200",
      });
      if (topic !== "__all__") query.set("topic", topic);
      const [list, c] = await Promise.all([
        api.get<StoredMistake[]>(`/mistakes?${query}`),
        api.get<Counts>("/mistakes/counts"),
      ]);
      setItems(list);
      setCounts(c);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载错题失败");
    } finally {
      setLoading(false);
    }
  }, [topic, includeMastered]);

  useEffect(() => {
    void api
      .get<string[]>("/mistakes/topics")
      .then(setTopics)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = async (item: StoredMistake) => {
    setBusy(item.id);
    try {
      await api.post("/mistakes/mastered", {
        mistake_id: item.id,
        mastered: !item.mastered,
      });
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "更新失败");
    } finally {
      setBusy(null);
    }
  };

  const remove = async (item: StoredMistake) => {
    setBusy(item.id);
    try {
      await api.del(`/mistakes/${item.id}`);
      await load();
      toast.success("已删除");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败");
    } finally {
      setBusy(null);
    }
  };

  const subtitle = counts
    ? `待复习 ${counts.pending} 条 · 已掌握 ${counts.mastered} 条`
    : "历次面试答得不好的知识点会自动汇聚到这里";

  return (
    <PageContainer
      title="错题本"
      description={subtitle}
      actions={
        <Button variant="outline" onClick={() => window.print()} disabled={items.length === 0}>
          导出
        </Button>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Select value={topic} onValueChange={setTopic}>
            <SelectTrigger className="w-[200px]">
              <SelectValue placeholder="全部主题" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">全部主题</SelectItem>
              {topics.map((t) => (
                <SelectItem key={t} value={t}>
                  {t}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={includeMastered ? "all" : "pending"}
            onValueChange={(v) => setIncludeMastered(v === "all")}
          >
            <SelectTrigger className="w-[190px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="pending">仅未掌握</SelectItem>
              <SelectItem value="all">全部（含已掌握）</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {loading ? (
          <div className="space-y-3">
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        ) : items.length === 0 ? (
          <Card>
            <CardContent>
              <EmptyState
                icon={BookMarked}
                title="还没有错题"
                hint="面试中答得不好的知识点会自动汇总到这里，形成专属复习清单。同一知识点反复答错会累计次数，优先复习高频项。"
                action={
                  <Button size="sm" onClick={() => onNavigate("prepare")}>
                    开始一场面试
                  </Button>
                }
              />
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {items.map((stored) => {
              const item = stored.item;
              return (
                <Card key={stored.id} className={stored.mastered ? "opacity-60" : undefined}>
                  <CardContent className="space-y-2.5">
                    <div className="flex items-start justify-between gap-3">
                      <p className="flex-1 text-[15px] leading-snug font-semibold">
                        {item.knowledge_point}
                      </p>
                      <div className="flex shrink-0 items-center gap-1.5">
                        {stored.hit_count > 1 && (
                          <Badge variant="outline" className="border-destructive/20 bg-destructive/10 text-destructive">
                            错 {stored.hit_count} 次
                          </Badge>
                        )}
                        <Badge variant="outline" className={SEVERITY_STYLE[item.severity]}>
                          {labelOf(GAP_SEVERITY, item.severity)}
                        </Badge>
                      </div>
                    </div>

                    {item.topic && <p className="text-muted-foreground text-xs">{item.topic}</p>}
                    {item.question && (
                      <p className="text-muted-foreground selectable text-sm">
                        题目：{item.question}
                      </p>
                    )}
                    {item.review_hint && (
                      <p className="text-accent-foreground bg-accent/50 selectable rounded-md px-3 py-2 text-sm">
                        复习要点：{item.review_hint}
                      </p>
                    )}
                    {item.key_points.length > 0 && (
                      <ul className="text-muted-foreground space-y-0.5 text-sm">
                        {item.key_points.slice(0, 5).map((point, i) => (
                          <li key={`${stored.id}-${i}`} className="selectable">
                            · {point}
                          </li>
                        ))}
                      </ul>
                    )}

                    <div className="flex justify-end gap-2 pt-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy === stored.id}
                        onClick={() => void toggle(stored)}
                      >
                        {busy === stored.id ? (
                          <Loader2 className="animate-spin" />
                        ) : stored.mastered ? (
                          <RotateCcw />
                        ) : (
                          <Check />
                        )}
                        {stored.mastered ? "取消掌握" : "标记为已掌握"}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-destructive hover:text-destructive"
                        disabled={busy === stored.id}
                        onClick={() => void remove(stored)}
                      >
                        <Trash2 />
                        删除
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </div>
    </PageContainer>
  );
}
