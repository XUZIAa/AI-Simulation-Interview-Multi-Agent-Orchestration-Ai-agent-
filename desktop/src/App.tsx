import { AlertCircle, Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  BackendError,
  type InterruptedSession,
  type InterviewState,
  api,
  ensureBackend,
  isEventChannelOpen,
  onConnectionChange,
  onEvent,
  openEventChannel,
} from "@/lib/backend";
import type { PageId } from "@/lib/pages";
import { DashboardView } from "@/views/dashboard";
import { GrowthView } from "@/views/growth";
import { MistakesView } from "@/views/mistakes";
import { PersonaView } from "@/views/persona";
import { type PreparedBank, PrepareView } from "@/views/prepare";
import { ReviewView } from "@/views/review";
import { RoomView } from "@/views/room";
import { SettingsView } from "@/views/settings";

type Phase = "booting" | "ready" | "failed";

export default function App() {
  const [phase, setPhase] = useState<Phase>("booting");
  const [error, setError] = useState("");
  const [page, setPage] = useState<PageId>("dashboard");
  const [connected, setConnected] = useState(false);
  const [interrupted, setInterrupted] = useState<InterruptedSession[]>([]);
  // 复盘页要知道看哪一场、是否需要现场生成
  const [review, setReview] = useState<{ sessionId: number; generate: boolean } | null>(null);
  const [session, setSession] = useState<InterviewState | null>(null);
  const booted = useRef(false);
  // 准备页会随导航卸载，题库缓存放这里才能跨页面存活
  const bank = useRef<PreparedBank | null>(null);

  const openReview = (sessionId: number, generate = false) => {
    setReview({ sessionId, generate });
    setPage("review");
  };

  const boot = useCallback(async () => {
    setPhase("booting");
    setError("");
    try {
      await ensureBackend();
      await openEventChannel();
      // 认领上次强退遗留的面试。这一步会改写会话状态，只在启动时做
      const stale = await api
        .post<InterruptedSession[]>("/recovery/scan")
        .catch(() => [] as InterruptedSession[]);
      setInterrupted(stale);
      setPhase("ready");
    } catch (err) {
      if (err instanceof BackendError) {
        setError(err.detail ? `${err.message}\n\n${err.detail}` : err.message);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
      setPhase("failed");
    }
  }, []);

  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    void boot();
  }, [boot]);

  useEffect(() => {
    setConnected(isEventChannelOpen());
    const offConn = onConnectionChange(setConnected);
    // 引擎的非致命故障要让人看见，否则面试中出问题只能靠猜
    const offFailure = onEvent("engine_failure", (data) => {
      toast.error(data.user_message, { description: data.detail || undefined });
    });
    return () => {
      offConn();
      offFailure();
    };
  }, []);

  if (phase !== "ready") {
    return (
      <>
        <BootScreen phase={phase} error={error} onRetry={boot} />
        <Toaster position="bottom-right" />
      </>
    );
  }

  return (
    <TooltipProvider delayDuration={300}>
      <AppShell page={page} onNavigate={setPage} connected={connected}>
        {page === "dashboard" && (
          <DashboardView
            onNavigate={setPage}
            interrupted={interrupted}
            onOpenReview={openReview}
          />
        )}
        {page === "settings" && <SettingsView />}
        {page === "mistakes" && <MistakesView onNavigate={setPage} />}
        {page === "growth" && <GrowthView onNavigate={setPage} />}
        {page === "persona" && <PersonaView />}
        {page === "prepare" && (
          <PrepareView
            bank={bank}
            onStart={(state) => {
              setSession(state);
              setPage("room");
            }}
          />
        )}
        {page === "room" && session && (
          <RoomView
            state={session}
            onFinished={(sessionId, reviewable) => {
              setSession(null);
              // 题库已消耗，下一场必须重新出题，否则会拿到完全相同的题目
              bank.current = null;
              if (reviewable) {
                openReview(sessionId, true);
              } else {
                toast.warning("面试不足 5 分钟，未生成完整复盘");
                setPage("dashboard");
              }
            }}
            onAbort={() => {
              setSession(null);
              setPage("prepare");
            }}
          />
        )}
        {page === "review" && review && (
          <ReviewView
            sessionId={review.sessionId}
            autoGenerate={review.generate}
            onBack={() => setPage("dashboard")}
          />
        )}
      </AppShell>
      <Toaster position="bottom-right" />
    </TooltipProvider>
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
    <div className="bg-background flex h-full items-center justify-center p-8">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            {phase === "booting" ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <AlertCircle className="text-destructive size-4" />
            )}
            {phase === "booting" ? "正在启动本机后端" : "后端启动失败"}
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
