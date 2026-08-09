import { Copy, Loader2, Plus, Save, Trash2, UserRoundCog } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { EmptyState, PageContainer } from "@/components/page-container";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { type PersonaContract, type Schemas, api } from "@/lib/backend";
import { COMPANY_TIER } from "@/lib/labels";
import { cn } from "@/lib/utils";

type Catalog = Schemas["Catalog"];

const ARCHETYPE: Record<string, string> = {
  irritable_cto: "暴躁的 CTO",
  gentle_hr: "温和的 HR",
  picky_biz_leader: "刁钻的业务线 Leader",
  foreign_corp: "中英夹杂的外企 Manager",
  academic_purist: "抠原理的学术派",
  silent_observer: "沉默施压的观察者",
  rapid_fire: "连环追问的快枪手",
  structured: "按提纲推进的标准型",
  custom: "自定义人设",
};

/** 每个维度两端的含义。只标数字用户看不懂调的是什么。 */
const SPEECH_DIMS = [
  { key: "verbosity", label: "说话长度", low: "一句问完", high: "语气舒展" },
  { key: "warmth", label: "态度温度", low: "冷硬", high: "热情" },
  { key: "formality", label: "用语正式度", low: "口语化", high: "严谨" },
  { key: "speech_rate", label: "语速", low: "刻意放慢", high: "快节奏紧逼" },
  { key: "code_switch", label: "中英夹杂", low: "全中文", high: "每句夹英文" },
] as const;

const PRESSURE_DIMS = [
  { key: "aggression", label: "攻击性", low: "只提问不否定", high: "毫不客气" },
  { key: "interrupt_tendency", label: "打断倾向", low: "绝不打断", high: "听到废话就插话" },
  { key: "silence_pressure", label: "沉默施压", low: "不使用", high: "长沉默制造不适" },
  { key: "challenge_frequency", label: "质疑频率", low: "很少质疑", high: "步步质疑" },
  { key: "tolerance_for_vagueness", label: "含糊容忍度", low: "必须精确", high: "允许模糊" },
] as const;

const PROBING_DIMS = [
  { key: "divergence", label: "发散强度", low: "紧扣提纲", high: "自由联想" },
  { key: "follow_up_depth", label: "追问深度", low: "问一层", high: "追到极限" },
  { key: "project_focus", label: "项目经历", low: "少问", high: "重点考察" },
  { key: "fundamentals_focus", label: "基础原理", low: "少问", high: "重点考察" },
  { key: "system_design_focus", label: "系统设计", low: "少问", high: "重点考察" },
  { key: "coding_focus", label: "编码能力", low: "少问", high: "重点考察" },
  { key: "behavioral_focus", label: "行为面试", low: "少问", high: "重点考察" },
] as const;

export function PersonaView() {
  const [list, setList] = useState<PersonaContract[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [current, setCurrent] = useState<PersonaContract | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (keepId?: number | null) => {
    try {
      const [items, cat] = await Promise.all([
        api.get<PersonaContract[]>("/personas"),
        api.get<Catalog>("/catalog"),
      ]);
      setList(items);
      setCatalog(cat);
      const target = keepId != null ? items.find((p) => p.id === keepId) : items[0];
      setCurrent(target ?? items[0] ?? null);
      setDirty(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载人设失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const patch = (updater: (draft: PersonaContract) => PersonaContract) => {
    setCurrent((prev) => (prev ? updater(prev) : prev));
    setDirty(true);
  };

  const save = async () => {
    if (!current) return;
    if (!current.name.trim()) {
      toast.error("先给人设起个名字");
      return;
    }
    setSaving(true);
    try {
      const saved = await api.post<PersonaContract>("/personas", current);
      await load(saved.id);
      toast.success("人设已保存");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const duplicate = async () => {
    if (!current) return;
    try {
      const { name } = await api.post<{ name: string }>("/personas/unique-name", {
        base: current.name,
      });
      // 复制出来的是新人设：清掉 id 与内置标记，否则会覆盖原件
      setCurrent({ ...current, id: null, name, is_builtin: false });
      setDirty(true);
      toast.info(`已复制为「${name}」，保存后生效`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "复制失败");
    }
  };

  const remove = async () => {
    if (!current?.id) return;
    try {
      await api.del(`/personas/${current.id}`);
      await load();
      toast.success("已删除");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败");
    }
  };

  const create = () => {
    const base = list.find((p) => p.archetype === "structured") ?? list[0];
    if (!base) return;
    setCurrent({ ...base, id: null, name: "新人设", is_builtin: false, archetype: "custom" });
    setDirty(true);
  };

  if (loading) {
    return (
      <PageContainer title="人设工坊" description="面试官的性格是结构化定义的，可调、可存、可分享">
        <Skeleton className="h-96 w-full" />
      </PageContainer>
    );
  }

  const realtimeVoices = catalog?.realtime[0]?.voices ?? [];

  return (
    <PageContainer
      wide
      title="人设工坊"
      description="面试官的性格由 17 个维度定义，不是一段自由发挥的提示词"
      actions={
        <>
          <Button variant="outline" onClick={create}>
            <Plus />
            新建
          </Button>
          {current && (
            <Button variant="outline" onClick={() => void duplicate()}>
              <Copy />
              复制
            </Button>
          )}
          {current?.id != null && !current.is_builtin && (
            <Button
              variant="outline"
              className="text-destructive hover:text-destructive"
              onClick={() => void remove()}
            >
              <Trash2 />
              删除
            </Button>
          )}
          <Button onClick={() => void save()} disabled={saving || !dirty}>
            {saving ? <Loader2 className="animate-spin" /> : <Save />}
            保存
          </Button>
        </>
      }
    >
      <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
        <Card className="h-fit py-4">
          <CardContent className="space-y-1 px-3">
            {list.length === 0 ? (
              <EmptyState icon={UserRoundCog} title="还没有人设" />
            ) : (
              list.map((p) => (
                <button
                  key={p.id ?? p.name}
                  type="button"
                  onClick={() => {
                    setCurrent(p);
                    setDirty(false);
                  }}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm transition-colors",
                    current?.id === p.id && current?.name === p.name
                      ? "bg-accent font-medium"
                      : "hover:bg-accent/60",
                  )}
                >
                  <span className="min-w-0 flex-1 truncate">{p.name}</span>
                  {p.is_builtin && (
                    <Badge variant="secondary" className="shrink-0 text-[10px]">
                      内置
                    </Badge>
                  )}
                </button>
              ))
            )}
          </CardContent>
        </Card>

        {current ? (
          <div className="space-y-4">
            {current.is_builtin && (
              <Card className="border-primary/30 bg-primary/5 gap-0 py-3">
                <CardContent className="px-4">
                  <p className="text-sm">
                    这是内置人设。可以直接改并保存，也可以「复制」出一份再改，原件保留。
                  </p>
                </CardContent>
              </Card>
            )}

            <Card>
              <CardHeader>
                <CardTitle className="text-base">基本信息</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-3 sm:grid-cols-2">
                <Field label="人设名称">
                  <Input
                    value={current.name}
                    onChange={(e) => patch((d) => ({ ...d, name: e.target.value }))}
                  />
                </Field>
                <Field label="原型">
                  <Select
                    value={current.archetype}
                    onValueChange={(v) =>
                      patch((d) => ({ ...d, archetype: v as PersonaContract["archetype"] }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {Object.entries(ARCHETYPE).map(([k, v]) => (
                        <SelectItem key={k} value={k}>
                          {v}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="公司画像">
                  <Select
                    value={current.company_tier}
                    onValueChange={(v) =>
                      patch((d) => ({ ...d, company_tier: v as PersonaContract["company_tier"] }))
                    }
                  >
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
                </Field>
                <Field label="面试官职位">
                  <Input
                    value={current.job_title}
                    placeholder="如 后端技术负责人"
                    onChange={(e) => patch((d) => ({ ...d, job_title: e.target.value }))}
                  />
                </Field>
                <Field label="音色">
                  <Select
                    value={current.voice || "__default__"}
                    onValueChange={(v) =>
                      patch((d) => ({ ...d, voice: v === "__default__" ? "" : v }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__default__">跟随设置</SelectItem>
                      {realtimeVoices.map((v) => (
                        <SelectItem key={v.value} value={v.value}>
                          {v.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="公司氛围补充">
                  <Input
                    value={current.company_flavor}
                    placeholder="如 强调结果导向、汇报链条短"
                    onChange={(e) => patch((d) => ({ ...d, company_flavor: e.target.value }))}
                  />
                </Field>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">性格维度</CardTitle>
                <CardDescription>
                  这些值会编译成运行时指令，每轮重新注入，所以面试官不会聊几句就忘了自己是谁
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Tabs defaultValue="speech">
                  <TabsList className="mb-3">
                    <TabsTrigger value="speech">说话风格</TabsTrigger>
                    <TabsTrigger value="pressure">压力策略</TabsTrigger>
                    <TabsTrigger value="probing">考察侧重</TabsTrigger>
                  </TabsList>

                  <TabsContent value="speech" className="space-y-4">
                    {SPEECH_DIMS.map((dim) => (
                      <LevelRow
                        key={dim.key}
                        label={dim.label}
                        low={dim.low}
                        high={dim.high}
                        value={current.speech[dim.key]}
                        onChange={(v) =>
                          patch((d) => ({ ...d, speech: { ...d.speech, [dim.key]: v } }))
                        }
                      />
                    ))}
                    <Field label="口头禅（逗号分隔，自然穿插）">
                      <Input
                        value={current.speech.catchphrases.join("，")}
                        placeholder="如 你觉得呢，说具体点"
                        onChange={(e) =>
                          patch((d) => ({
                            ...d,
                            speech: { ...d.speech, catchphrases: splitList(e.target.value) },
                          }))
                        }
                      />
                    </Field>
                    <Field label="禁止说的表达（逗号分隔）">
                      <Input
                        value={current.speech.banned_phrases.join("，")}
                        onChange={(e) =>
                          patch((d) => ({
                            ...d,
                            speech: { ...d.speech, banned_phrases: splitList(e.target.value) },
                          }))
                        }
                      />
                    </Field>
                  </TabsContent>

                  <TabsContent value="pressure" className="space-y-4">
                    {PRESSURE_DIMS.map((dim) => (
                      <LevelRow
                        key={dim.key}
                        label={dim.label}
                        low={dim.low}
                        high={dim.high}
                        value={current.pressure[dim.key]}
                        onChange={(v) =>
                          patch((d) => ({ ...d, pressure: { ...d.pressure, [dim.key]: v } }))
                        }
                      />
                    ))}
                  </TabsContent>

                  <TabsContent value="probing" className="space-y-4">
                    {PROBING_DIMS.map((dim) => (
                      <LevelRow
                        key={dim.key}
                        label={dim.label}
                        low={dim.low}
                        high={dim.high}
                        value={current.probing[dim.key]}
                        onChange={(v) =>
                          patch((d) => ({ ...d, probing: { ...d.probing, [dim.key]: v } }))
                        }
                      />
                    ))}
                  </TabsContent>
                </Tabs>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">开场与补充规则</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <Field label="开场白（留空则由模型按人设自行开场）">
                  <Textarea
                    rows={2}
                    value={current.opening_line}
                    onChange={(e) => patch((d) => ({ ...d, opening_line: e.target.value }))}
                  />
                </Field>
                <Field label="补充规则（每行一条，会并入人格指令）">
                  <Textarea
                    rows={4}
                    value={current.extra_rules.join("\n")}
                    placeholder={"如\n必须问到分布式事务\n不要问算法题"}
                    onChange={(e) =>
                      patch((d) => ({
                        ...d,
                        extra_rules: e.target.value
                          .split("\n")
                          .map((s) => s.trim())
                          .filter(Boolean),
                      }))
                    }
                  />
                </Field>
              </CardContent>
            </Card>
          </div>
        ) : (
          <Card>
            <CardContent>
              <EmptyState icon={UserRoundCog} title="选一个人设开始调整" />
            </CardContent>
          </Card>
        )}
      </div>
    </PageContainer>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-muted-foreground text-xs font-normal">{label}</Label>
      {children}
    </div>
  );
}

function LevelRow({
  label,
  low,
  high,
  value,
  onChange,
}: {
  label: string;
  low: string;
  high: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <Label className="text-sm">{label}</Label>
        <span className="text-muted-foreground font-mono text-xs">{value}</span>
      </div>
      <Slider min={0} max={10} step={1} value={[value]} onValueChange={([v]) => onChange(v)} />
      <div className="text-muted-foreground flex justify-between text-[11px]">
        <span>{low}</span>
        <span>{high}</span>
      </div>
    </div>
  );
}

function splitList(raw: string): string[] {
  return raw
    .split(/[，,]/)
    .map((s) => s.trim())
    .filter(Boolean);
}
