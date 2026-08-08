import { listen } from "@tauri-apps/api/event";
import { AlertCircle, CheckCircle2, Loader2, Radio, RefreshCw, Server } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  type BackendInfo,
  BackendError,
  api,
  ensureBackend,
  inTauri,
  isEventChannelOpen,
  onConnectionChange,
  onEvent,
  openEventChannel,
} from "@/lib/backend";
import { cn } from "@/lib/utils";

interface ServerMeta {
  name: string;
  version: string;
  event_names: string[];
  subscribers: number;
}

interface GlobalStats {
  total_sessions: number;
  completed_sessions: number;
  total_minutes: number;
  best_score: number | null;
  latest_score: number | null;
  average_score: number | null;
}

interface SessionSummary {
  id: number;
  title: string;
  status: string;
  persona_name: string;
  created_at: string;
  duration_ms: number;
  overall_score: number | null;
  planned_minutes: number;
}

type Phase = "booting" | "ready" | "failed";

export default function App() {
  const [phase, setPhase] = useState<Phase>("booting");
  const [error, setError] = useState("");
  const [conn, setConn] = useState<BackendInfo | null>(null);
  const [meta, setMeta] = useState<ServerMeta | null>(null);
  const [stats, setStats] = useState<GlobalStats | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [wsOpen, setWsOpen] = useState(false);
  const [eventLog, setEventLog] = useState<string[]>([]);
  const bootedRef = useRef(false);

  const boot = useCallback(async () => {
    setPhase("booting");
    setError("");
    try {
      const info = await ensureBackend();
      setConn(info);
      await openEventChannel();
      const [metaRes, statsRes, sessionRes] = await Promise.all([
        api.get<ServerMeta>("/info"),
        api.get<GlobalStats>("/sessions/stats"),
        api.get<SessionSummary[]>("/sessions?limit=6"),
      ]);
      setMeta(metaRes);
      setStats(statsRes);
      setSessions(sessionRes);
      setPhase("ready");
    } catch (err) {
      // 业务错误自带给用户看的话术，其余才退回原始信息
      if (err instanceof BackendError) {
        setError(err.detail ? `${err.message}\n\n${err.detail}` : err.message);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
      setPhase("failed");
    }
  }, []);

  useEffect(() => {
    if (bootedRef.current) return;
    bootedRef.current = true;
    void boot();
  }, [boot]);

  useEffect(() => {
    setWsOpen(isEventChannelOpen());
    const offConn = onConnectionChange(setWsOpen);
    // 任何一类事件到达都说明桥是通的，这里只记录不解读
    const names = ["task_progress", "phase_changed", "realtime_state_changed", "engine_failure"];
    const offs = names.map((name) =>
      onEvent(name, (data) =>
        setEventLog((prev) => [`${name} ${JSON.stringify(data)}`, ...prev].slice(0, 6)),
      ),
    );
    // 浏览器里没有 Tauri 运行时，监听它的事件会直接抛错
    const offLog = inTauri()
      ? listen<string>("backend-log", (ev) => {
          // uvicorn 的启动横幅没有诊断价值，只留业务与告警
          const line = ev.payload;
          if (/uvicorn|Started server|Waiting for|Application startup/.test(line)) return;
          const brief = line.replace(/^\d{4}-\d{2}-\d{2} [\d:,]+\s+/, "");
          setEventLog((prev) => [brief, ...prev].slice(0, 6));
        })
      : null;
    return () => {
      offConn();
      offs.forEach((off) => off());
      void offLog?.then((fn) => fn());
    };
  }, []);

  if (phase !== "ready") {
    return (
      <BootScreen phase={phase} error={error} onRetry={boot} />
    );
  }

  return (
    <div className="bg-background flex h-full flex-col">
      {/* 标题栏不进滚动容器：跟着内容滚会在首屏被裁掉 */}
      <header className="bg-background/80 flex shrink-0 items-center justify-between gap-4 border-b px-8 py-5 backdrop-blur">
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold tracking-tight">工作台</h1>
          <p className="text-muted-foreground mt-0.5 truncate text-sm">
            新界面骨架已接通后端，正在逐页迁移
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <StatusPill ok={wsOpen} label={wsOpen ? "已连接" : "已断开"} />
          <Button variant="outline" size="sm" onClick={() => void boot()}>
            <RefreshCw />
            刷新
          </Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl space-y-5 p-8">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="累计面试" value={stats ? `${stats.total_sessions}` : "-"} unit="场" />
          <Metric label="已完成" value={stats ? `${stats.completed_sessions}` : "-"} unit="场" />
          <Metric label="累计时长" value={stats ? `${stats.total_minutes}` : "-"} unit="分钟" />
          <Metric
            label="最高分"
            value={stats?.best_score != null ? stats.best_score.toFixed(1) : "暂无"}
          />
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Server className="size-4" />
              本机通道
            </CardTitle>
            <CardDescription>
              后端以子进程方式运行，仅监听回环地址并要求 token 认证
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm sm:grid-cols-2">
            <Field label="服务地址" value={conn?.http_base ?? "-"} />
            <Field label="事件端点" value={conn ? new URL(conn.ws_events).pathname : "-"} />
            <Field label="接口版本" value={meta ? `v${meta.version}` : "-"} />
            <Field label="事件类型" value={meta ? `${meta.event_names.length} 种` : "-"} />
          </CardContent>
        </Card>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">最近面试</CardTitle>
              <CardDescription>数据取自后端 SQLite，与 Qt 版本是同一份</CardDescription>
            </CardHeader>
            <CardContent>
              {sessions.length === 0 ? (
                <p className="text-muted-foreground py-8 text-center text-sm">还没有面试记录</p>
              ) : (
                <ul className="divide-border divide-y">
                  {sessions.map((s) => (
                    <li key={s.id} className="flex items-center justify-between gap-3 py-2.5">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">{s.title}</p>
                        <p className="text-muted-foreground text-xs">
                          {s.persona_name} · {new Date(s.created_at).toLocaleString("zh-CN")}
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
                        {s.overall_score != null ? s.overall_score.toFixed(1) : s.status}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Radio className="size-4" />
                事件桥
              </CardTitle>
              <CardDescription>后端推来的事件会实时出现在这里</CardDescription>
            </CardHeader>
            <CardContent>
              {eventLog.length === 0 ? (
                <p className="text-muted-foreground py-8 text-center text-sm">
                  暂无事件。面试开始后这里会持续刷新
                </p>
              ) : (
                <ul className="space-y-1.5">
                  {eventLog.map((line, i) => (
                    <li
                      key={`${line}-${i}`}
                      className="bg-muted/60 text-muted-foreground selectable truncate rounded-md px-2.5 py-1.5 font-mono text-xs"
                    >
                      {line}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
          </div>
        </div>
      </div>
    </div>
  );
}

function BootScreen({
  phase,
  error,
  onRetry,
}: {
  phase: Phase;
  error: string;
  onRetry: () => void;
}) {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            {phase === "booting" ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <AlertCircle className="text-destructive size-4" />
            )}
            {phase === "booting" ? "正在启动后端" : "后端启动失败"}
          </CardTitle>
          <CardDescription>
            {phase === "booting"
              ? "首次启动要初始化数据库与音频设备，请稍候"
              : "下面是后端进程的原始输出，通常能直接看出原因"}
          </CardDescription>
        </CardHeader>
        {phase === "failed" && (
          <CardContent className="space-y-4">
            <pre className="bg-muted selectable max-h-64 overflow-auto rounded-lg p-3 text-xs whitespace-pre-wrap">
              {error || "没有捕获到输出"}
            </pre>
            <Button onClick={onRetry} className="w-full">
              重试
            </Button>
          </CardContent>
        )}
      </Card>
    </div>
  );
}

function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
        ok ? "bg-success/10 text-success" : "bg-destructive/10 text-destructive",
      )}
    >
      {ok ? <CheckCircle2 className="size-3.5" /> : <AlertCircle className="size-3.5" />}
      {label}
    </span>
  );
}

function Metric({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <Card className="gap-2 py-4">
      <CardContent className="px-4">
        <p className="text-muted-foreground text-xs">{label}</p>
        <p className="mt-1 text-2xl font-semibold tracking-tight">
          {value}
          {unit && <span className="text-muted-foreground ml-1 text-sm font-normal">{unit}</span>}
        </p>
      </CardContent>
    </Card>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className="selectable mt-0.5 truncate font-mono text-xs">{value}</p>
    </div>
  );
}
