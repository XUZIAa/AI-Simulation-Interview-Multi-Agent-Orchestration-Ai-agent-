import {
  AudioLines,
  Check,
  ExternalLink,
  Eye,
  EyeOff,
  Loader2,
  Save,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { PageContainer } from "@/components/page-container";
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
import { Switch } from "@/components/ui/switch";
import { type AppSettings, type Schemas, api } from "@/lib/backend";
import { cn } from "@/lib/utils";

type Catalog = Schemas["Catalog"];
type ProviderOption = Schemas["ProviderOption"];
type AudioDevices = Schemas["AudioDevices"];
type ProbeOutcome = Schemas["ProbeOutcome"];

type ProbeState = Record<string, { pending: boolean; result?: ProbeOutcome }>;

export function SettingsView() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [devices, setDevices] = useState<AudioDevices | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [keyPresent, setKeyPresent] = useState<Record<string, boolean>>({});
  const [keyDraft, setKeyDraft] = useState<Record<string, string>>({});
  const [reveal, setReveal] = useState<Record<string, boolean>>({});
  const [probe, setProbe] = useState<ProbeState>({});
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const [cat, dev, cfg] = await Promise.all([
        api.get<Catalog>("/catalog"),
        api.get<AudioDevices>("/audio/devices"),
        api.get<AppSettings>("/config"),
      ]);
      setCatalog(cat);
      setDevices(dev);
      setSettings(cfg);
      const keys = Array.from(
        new Set([...cat.chat.map((p) => p.credential_key), ...cat.realtime.map((p) => p.credential_key)]),
      );
      const present = await Promise.all(
        keys.map((k) =>
          api
            .get<{ present: boolean }>(`/config/keys/${k}`)
            .then((r) => [k, r.present] as const)
            .catch(() => [k, false] as const),
        ),
      );
      setKeyPresent(Object.fromEntries(present));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载设置失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!settings) return;
    setSaving(true);
    try {
      // 先落密钥再存配置：配置保存会触发模型客户端重建，届时应当已能取到新密钥
      for (const [providerKey, value] of Object.entries(keyDraft)) {
        if (!value.trim()) continue;
        await api.post("/config/keys", { provider_key: providerKey, api_key: value.trim() });
      }
      await api.post("/config", settings);
      setKeyDraft({});
      const refreshed = Object.fromEntries(
        Object.entries(keyPresent).map(([k, v]) => [k, v || Boolean(keyDraft[k]?.trim())]),
      );
      setKeyPresent(refreshed);
      toast.success("设置已保存");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const runProbe = async (id: string, body: Record<string, unknown>) => {
    setProbe((prev) => ({ ...prev, [id]: { pending: true } }));
    try {
      const result = await api.post<ProbeOutcome>("/config/probe", body);
      setProbe((prev) => ({ ...prev, [id]: { pending: false, result } }));
    } catch (err) {
      setProbe((prev) => ({
        ...prev,
        [id]: {
          pending: false,
          result: {
            ok: false,
            detail: err instanceof Error ? err.message : "测试失败",
            latency_ms: 0,
          },
        },
      }));
    }
  };

  if (!catalog || !settings || !devices) {
    return (
      <PageContainer title="设置" description="模型、密钥、语言与音频">
        <div className="space-y-4">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      </PageContainer>
    );
  }

  const realtime = catalog.realtime.find((p) => p.key === settings.realtime.provider);
  const credentialKeys = Array.from(
    new Set([
      ...catalog.chat.filter((p) => p.key !== "custom").map((p) => p.key),
      ...catalog.realtime.map((p) => p.credential_key),
    ]),
  );
  const providerByKey = new Map<string, ProviderOption>(
    [...catalog.chat, ...catalog.realtime].map((p) => [p.credential_key, p]),
  );

  return (
    <PageContainer
      title="设置"
      description="所有数据留在本机，密钥存入系统凭据管理器"
      actions={
        <Button onClick={() => void save()} disabled={saving}>
          {saving ? <Loader2 className="animate-spin" /> : <Save />}
          保存
        </Button>
      }
    >
      <div className="space-y-5">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ShieldCheck className="text-success size-4" />
              API Key
            </CardTitle>
            <CardDescription>
              填过的密钥不会回传到界面。改动后点右上角保存，测试按钮可随时验证是否可用
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {credentialKeys.map((key) => {
              const provider = providerByKey.get(key);
              const state = probe[`key:${key}`];
              return (
                <div key={key} className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <Label className="text-sm">{provider?.label ?? key}</Label>
                    <div className="flex items-center gap-2">
                      {keyPresent[key] && !keyDraft[key] && (
                        <span className="text-success flex items-center gap-1 text-xs">
                          <Check className="size-3" />
                          已配置
                        </span>
                      )}
                      {provider?.console_url && (
                        <a
                          href={provider.console_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-xs"
                        >
                          获取
                          <ExternalLink className="size-3" />
                        </a>
                      )}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <div className="relative flex-1">
                      <Input
                        type={reveal[key] ? "text" : "password"}
                        placeholder={keyPresent[key] ? "已保存，留空表示不修改" : "粘贴 API Key"}
                        value={keyDraft[key] ?? ""}
                        onChange={(e) =>
                          setKeyDraft((prev) => ({ ...prev, [key]: e.target.value }))
                        }
                        className="pr-9"
                      />
                      <button
                        type="button"
                        onClick={() => setReveal((prev) => ({ ...prev, [key]: !prev[key] }))}
                        className="text-muted-foreground hover:text-foreground absolute top-1/2 right-2 -translate-y-1/2"
                        aria-label={reveal[key] ? "隐藏" : "显示"}
                      >
                        {reveal[key] ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                      </button>
                    </div>
                    <Button
                      variant="outline"
                      disabled={state?.pending || (!keyPresent[key] && !keyDraft[key]?.trim())}
                      onClick={() =>
                        void runProbe(`key:${key}`, {
                          provider_key: key,
                          api_key: keyDraft[key]?.trim() ?? "",
                        })
                      }
                    >
                      {state?.pending ? <Loader2 className="animate-spin" /> : null}
                      测试
                    </Button>
                  </div>
                  {state?.result && <ProbeLine result={state.result} />}
                </div>
              );
            })}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Sparkles className="text-primary size-4" />
              模型
            </CardTitle>
            <CardDescription>
              四个角色可分别绑定。导演与复盘吃长上下文，提词与守卫在延迟敏感链路上要快
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {catalog.roles.map((role) => {
              const binding = settings.roles[role.key] ?? { provider: "deepseek", model: "" };
              const provider = catalog.chat.find((p) => p.key === binding.provider);
              const id = `role:${role.key}`;
              const state = probe[id];
              return (
                <div key={role.key} className="space-y-1.5">
                  <Label className="text-sm">{role.label}</Label>
                  <div className="flex flex-wrap gap-2">
                    <Select
                      value={binding.provider}
                      onValueChange={(v) => {
                        const next = catalog.chat.find((p) => p.key === v);
                        setSettings({
                          ...settings,
                          roles: {
                            ...settings.roles,
                            [role.key]: { provider: v, model: next?.default_model ?? "" },
                          },
                        });
                      }}
                    >
                      <SelectTrigger className="w-[190px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {catalog.chat.map((p) => (
                          <SelectItem key={p.key} value={p.key}>
                            {p.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Select
                      value={binding.model || (provider?.default_model ?? "")}
                      onValueChange={(v) =>
                        setSettings({
                          ...settings,
                          roles: {
                            ...settings.roles,
                            [role.key]: { ...binding, model: v },
                          },
                        })
                      }
                    >
                      <SelectTrigger className="min-w-[210px] flex-1">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {(provider?.models ?? []).map((m) => (
                          <SelectItem key={m} value={m}>
                            {m}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      variant="outline"
                      disabled={state?.pending}
                      onClick={() =>
                        void runProbe(id, {
                          provider_key: binding.provider,
                          model: binding.model || provider?.default_model || "",
                        })
                      }
                    >
                      {state?.pending ? <Loader2 className="animate-spin" /> : null}
                      测试
                    </Button>
                  </div>
                  {state?.result && <ProbeLine result={state.result} />}
                </div>
              );
            })}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <AudioLines className="text-interviewer size-4" />
              实时语音
            </CardTitle>
            <CardDescription>面试官的声音由这里的模型生成，语义打断依赖它的能力</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="供应商">
                <Select
                  value={settings.realtime.provider}
                  onValueChange={(v) => {
                    const next = catalog.realtime.find((p) => p.key === v);
                    setSettings({
                      ...settings,
                      realtime: {
                        ...settings.realtime,
                        provider: v,
                        model: next?.default_model ?? "",
                        voice: next?.voices[0]?.value ?? "",
                      },
                    });
                  }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {catalog.realtime.map((p) => (
                      <SelectItem key={p.key} value={p.key}>
                        {p.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="模型">
                <Select
                  value={settings.realtime.model || (realtime?.default_model ?? "")}
                  onValueChange={(v) =>
                    setSettings({ ...settings, realtime: { ...settings.realtime, model: v } })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(realtime?.models ?? []).map((m) => (
                      <SelectItem key={m} value={m}>
                        {m}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="默认音色">
                <Select
                  value={settings.realtime.voice || (realtime?.voices[0]?.value ?? "")}
                  onValueChange={(v) =>
                    setSettings({ ...settings, realtime: { ...settings.realtime, voice: v } })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(realtime?.voices ?? []).map((v) => (
                      <SelectItem key={v.value} value={v.value}>
                        {v.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label={`语气随机度 ${settings.realtime.temperature.toFixed(2)}`}>
                <Slider
                  min={0.1}
                  max={1.5}
                  step={0.05}
                  value={[settings.realtime.temperature]}
                  onValueChange={([v]) =>
                    setSettings({
                      ...settings,
                      realtime: { ...settings.realtime, temperature: v },
                    })
                  }
                />
              </Field>
            </div>
            <div>
              <Button
                variant="outline"
                disabled={probe["rt"]?.pending}
                onClick={() =>
                  void runProbe("rt", {
                    provider_key: settings.realtime.provider,
                    model: settings.realtime.model,
                    realtime: true,
                  })
                }
              >
                {probe["rt"]?.pending ? <Loader2 className="animate-spin" /> : null}
                测试实时语音连通
              </Button>
              {probe["rt"]?.result && <ProbeLine result={probe["rt"].result} className="mt-2" />}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">音频</CardTitle>
            <CardDescription>
              强烈建议戴耳机。外放时回声门控会持续工作，但仍不如物理隔离可靠
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="麦克风">
                <Select
                  value={settings.audio.input_device || "__default__"}
                  onValueChange={(v) =>
                    setSettings({
                      ...settings,
                      audio: { ...settings.audio, input_device: v === "__default__" ? "" : v },
                    })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__default__">系统默认</SelectItem>
                    {devices.inputs.map((d) => (
                      <SelectItem key={d.index} value={d.name}>
                        {d.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="扬声器">
                <Select
                  value={settings.audio.output_device || "__default__"}
                  onValueChange={(v) =>
                    setSettings({
                      ...settings,
                      audio: { ...settings.audio, output_device: v === "__default__" ? "" : v },
                    })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__default__">系统默认</SelectItem>
                    {devices.outputs.map((d) => (
                      <SelectItem key={d.index} value={d.name}>
                        {d.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label={`人声灵敏度 ${settings.audio.vad_threshold.toFixed(2)}`}>
                <Slider
                  min={0.05}
                  max={0.95}
                  step={0.01}
                  value={[settings.audio.vad_threshold]}
                  onValueChange={([v]) =>
                    setSettings({ ...settings, audio: { ...settings.audio, vad_threshold: v } })
                  }
                />
              </Field>
              <Field label={`断句静音时长 ${settings.audio.silence_duration_ms} ms`}>
                <Slider
                  min={200}
                  max={2000}
                  step={20}
                  value={[settings.audio.silence_duration_ms]}
                  onValueChange={([v]) =>
                    setSettings({
                      ...settings,
                      audio: { ...settings.audio, silence_duration_ms: v },
                    })
                  }
                />
              </Field>
            </div>
            <ToggleRow
              label="语义打断"
              hint="区分「嗯嗯」这类附和与真正的插话"
              checked={settings.audio.semantic_vad}
              onChange={(v) =>
                setSettings({ ...settings, audio: { ...settings.audio, semantic_vad: v } })
              }
            />
            <ToggleRow
              label="自动增益"
              hint="按说话音量自动调整采集增益，静音时不放大底噪"
              checked={settings.audio.auto_gain}
              onChange={(v) =>
                setSettings({ ...settings, audio: { ...settings.audio, auto_gain: v } })
              }
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">功能</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <ToggleRow
              label="摄像头自视图"
              hint="画面只在本机渲染，不经网络"
              checked={settings.features.camera_enabled}
              onChange={(v) =>
                setSettings({ ...settings, features: { ...settings.features, camera_enabled: v } })
              }
            />
            <ToggleRow
              label="实时提词"
              hint="卡壳时给关键词与展开方向"
              checked={settings.features.copilot_enabled}
              onChange={(v) =>
                setSettings({ ...settings, features: { ...settings.features, copilot_enabled: v } })
              }
            />
            <ToggleRow
              label="代码环节"
              hint="技术岗面试中插入手写代码与讲思路"
              checked={settings.features.coding_round_enabled}
              onChange={(v) =>
                setSettings({
                  ...settings,
                  features: { ...settings.features, coding_round_enabled: v },
                })
              }
            />
            <ToggleRow
              label="保存录音"
              hint="留在本机，用于复盘时回听"
              checked={settings.features.save_audio}
              onChange={(v) =>
                setSettings({ ...settings, features: { ...settings.features, save_audio: v } })
              }
            />
          </CardContent>
        </Card>
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

function ToggleRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <p className="text-sm font-medium">{label}</p>
        <p className="text-muted-foreground text-xs">{hint}</p>
      </div>
      <Switch checked={checked} onCheckedChange={onChange} />
    </div>
  );
}

function ProbeLine({ result, className }: { result: ProbeOutcome; className?: string }) {
  return (
    <p
      className={cn(
        "flex items-center gap-1.5 text-xs",
        result.ok ? "text-success" : "text-destructive",
        className,
      )}
    >
      {result.ok ? <Check className="size-3.5 shrink-0" /> : <X className="size-3.5 shrink-0" />}
      <span className="selectable">{result.detail}</span>
    </p>
  );
}
