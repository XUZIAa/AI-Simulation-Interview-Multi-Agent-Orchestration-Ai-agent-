import {
  Code2,
  Lightbulb,
  Mic,
  MicOff,
  PhoneOff,
  Video,
  VideoOff,
  X,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { CodingPanel } from "@/components/coding-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { type MeterHandle, type OrbHandle, LevelMeter, VoiceOrb } from "@/components/voice-orb";
import { type InterviewState, api, onEvent } from "@/lib/backend";
import type { StarProgress } from "@/lib/event-types";
import { INTERVIEW_PHASE, TURN_INTENT, labelOf } from "@/lib/labels";
import { cn } from "@/lib/utils";

const STAR_ELEMENTS: { key: string; label: string }[] = [
  { key: "situation", label: "情境" },
  { key: "task", label: "任务" },
  { key: "action", label: "行动" },
  { key: "result", label: "结果" },
];

interface Line {
  id: string;
  speaker: string;
  text: string;
  partial: boolean;
}

interface Props {
  state: InterviewState;
  onFinished: (sessionId: number, reviewable: boolean) => void;
  onAbort: () => void;
}

export function RoomView({ state, onFinished, onAbort }: Props) {
  const [connected, setConnected] = useState(false);
  const [phase, setPhase] = useState(state.phase);
  const [elapsed, setElapsed] = useState(0);
  const [remaining, setRemaining] = useState(state.plan.total_ms);
  const [muted, setMuted] = useState(false);
  const [cameraOn, setCameraOn] = useState(false);
  const [codeOpen, setCodeOpen] = useState(false);
  const [promptOpen, setPromptOpen] = useState(true);
  const [lines, setLines] = useState<Line[]>([]);
  const [hint, setHint] = useState<{ keywords: string[]; outline: string[]; caution: string } | null>(
    null,
  );
  const [star, setStar] = useState<{ present: StarProgress["present"]; behavioral: boolean }>({
    present: [],
    behavioral: false,
  });
  const [director, setDirector] = useState("");
  const [hearing, setHearing] = useState(false);
  const [talking, setTalking] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [hintCooling, setHintCooling] = useState(false);

  const orb = useRef<OrbHandle | null>(null);
  const meter = useRef<MeterHandle | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  // 引擎启动与整场等待都挂在这一个请求上
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      try {
        await api.post("/engine/start", { session_id: state.session_id });
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "面试启动失败");
        onAbort();
        return;
      }
      try {
        await api.post("/engine/wait-finished");
      } catch {
        // 连接中断也算结束，交给收尾流程判断能不能复盘
      }
      const result = await api
        .post<{ session_id: number | null; reviewable: boolean }>("/engine/stop", {})
        .catch(() => ({ session_id: state.session_id, reviewable: false }));
      onFinished(result.session_id ?? state.session_id, result.reviewable);
    })();
  }, [state.session_id, onFinished, onAbort]);

  useEffect(() => {
    const offs = [
      onEvent("realtime_state_changed", (d) => setConnected(d.connected)),
      onEvent("phase_changed", (d) => setPhase(d.phase)),
      onEvent("elapsed_tick", (d) => {
        setElapsed(d.elapsed_ms);
        setRemaining(d.remaining_ms);
      }),
      // 电平直接推给 canvas，不进 React 状态
      onEvent("audio_level", (d) => {
        orb.current?.setLevel(d.interviewer);
        meter.current?.setLevel(d.candidate);
      }),
      onEvent("interviewer_speaking", (d) => {
        setTalking(d.speaking);
        orb.current?.setActive(d.speaking);
      }),
      onEvent("speech_activity", (d) => setHearing(d.speaking)),
      onEvent("transcript_delta", (d) =>
        setLines((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last?.partial && last.speaker === d.speaker) {
            next[next.length - 1] = { ...last, text: d.text };
            return next;
          }
          next.push({ id: `p-${Date.now()}`, speaker: d.speaker, text: d.text, partial: true });
          return next;
        }),
      ),
      onEvent("transcript_committed", (d) =>
        setLines((prev) => {
          const next = prev.filter((l) => !(l.partial && l.speaker === d.speaker));
          next.push({
            id: `c-${d.turn_id}-${next.length}`,
            speaker: d.speaker,
            text: d.text,
            partial: false,
          });
          return next.slice(-200);
        }),
      ),
      onEvent("director_decided", (d) =>
        setDirector(`${labelOf(TURN_INTENT, d.intent)}${d.target_skill ? ` · ${d.target_skill}` : ""}`),
      ),
      onEvent("copilot_hint", (d) => {
        setHint({ keywords: d.keywords, outline: d.outline, caution: d.caution });
        setPromptOpen(true);
      }),
      onEvent("star_progress", (d) =>
        setStar({ present: d.present, behavioral: d.is_behavioral }),
      ),
      onEvent("interruption_fired", (d) => toast.info(d.reason)),
      onEvent("drift_detected", (d) => {
        if (d.repaired) return;
        toast.warning("检测到人格漂移，已尝试修正");
      }),
    ];
    return () => offs.forEach((off) => off());
  }, []);

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  const toggleCamera = useCallback(async () => {
    if (cameraOn) {
      stream.current?.getTracks().forEach((t) => t.stop());
      stream.current = null;
      if (video.current) video.current.srcObject = null;
      setCameraOn(false);
      return;
    }
    try {
      const media = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      stream.current = media;
      if (video.current) {
        video.current.srcObject = media;
        await video.current.play();
      }
      setCameraOn(true);
    } catch {
      toast.error("没有检测到摄像头，或权限被拒绝");
    }
  }, [cameraOn]);

  // 离开房间必须停掉摄像头，否则指示灯一直亮着
  useEffect(() => {
    return () => stream.current?.getTracks().forEach((t) => t.stop());
  }, []);

  const toggleMute = async () => {
    const next = !muted;
    setMuted(next);
    await api.post("/engine/mute", { muted: next }).catch(() => undefined);
  };

  const requestHint = async () => {
    setPromptOpen(true);
    setHintCooling(true);
    setTimeout(() => setHintCooling(false), 3000);
    await api.post("/engine/hint", { auto: false }).catch(() => undefined);
  };

  const interrupt = async () => {
    await api.post("/engine/interrupt").catch(() => undefined);
  };

  const submitCode = async (language: string, source: string) => {
    if (!source.trim()) {
      toast.error("先写点代码再提交");
      return;
    }
    toast.info("已提交，面试官正在看你的代码");
    await api.post("/engine/code", { language, source }).catch(() => undefined);
  };

  const end = async () => {
    if (!confirmEnd) {
      setConfirmEnd(true);
      setTimeout(() => setConfirmEnd(false), 4000);
      return;
    }
    await api.post("/engine/finish-early").catch(() => undefined);
  };

  // 转成集合再判断：字面量联合数组的 includes 参数类型会被收得过窄
  const presentSet = new Set<string>(star.present);

  const link = !connected
    ? { text: "连接断开", tone: "text-red-400" }
    : hearing
      ? { text: "正在听你说", tone: "text-emerald-400" }
      : talking
        ? { text: "面试官在说", tone: "text-indigo-300" }
        : { text: "已接通", tone: "text-neutral-400" };

  return (
    <div className="flex h-full flex-col bg-neutral-800 text-neutral-100">
      <div className="flex min-h-0 flex-1">
        {/* 通话区。开代码沙盒后让位，语音球缩到角落 */}
        <div className={cn("relative min-h-0", codeOpen ? "w-[300px] shrink-0" : "min-w-0 flex-1")}>
          {/* 字幕悬浮在顶部，半透明压在场景上 */}
          <div
            className={cn(
              "absolute inset-x-0 top-0 z-10 mx-auto",
              codeOpen ? "px-3 pt-3" : "max-w-2xl px-4 pt-4",
            )}
          >
            <div
              ref={scroller}
              className={cn(
                "selectable overflow-y-auto rounded-xl bg-black/55 px-4 py-3 backdrop-blur-md",
                codeOpen ? "max-h-[30vh]" : "max-h-[26vh]",
              )}
            >
              {lines.length === 0 ? (
                <p className="text-[12.5px] text-neutral-400">对话开始后字幕会出现在这里</p>
              ) : (
                <div className="space-y-1.5">
                  {lines.slice(-14).map((line) => (
                    <p
                      key={line.id}
                      className={cn(
                        "text-[13px] leading-relaxed",
                        line.speaker === "candidate" ? "text-neutral-400" : "text-neutral-100",
                        line.partial && "opacity-70",
                      )}
                    >
                      <span className="mr-1.5 text-[11px] text-neutral-500">
                        {line.speaker === "candidate" ? "我" : state.persona.name}
                      </span>
                      {line.text}
                    </p>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* 语音球居中 */}
          <div className="flex h-full items-center justify-center">
            <div className="flex flex-col items-center gap-3">
              <VoiceOrb handleRef={orb} size={codeOpen ? 96 : 176} />
              <div className="text-center">
                <p className="text-[13.5px] font-medium">{state.persona.name}</p>
                <p className="mt-0.5 text-[11.5px] text-neutral-400">
                  {state.persona.job_title || "面试官"}
                </p>
              </div>
            </div>
          </div>

          {/* 自己的画面缩在右下 */}
          <div
            className={cn(
              "absolute overflow-hidden rounded-xl bg-black ring-1 transition-colors",
              hearing ? "ring-emerald-500/60" : "ring-white/10",
              codeOpen ? "right-3 bottom-3 h-[92px] w-[124px]" : "right-5 bottom-5 h-[168px] w-[224px]",
            )}
          >
            <video
              ref={video}
              muted
              playsInline
              className={cn("size-full object-cover", cameraOn ? "block" : "hidden")}
            />
            {!cameraOn && (
              <div className="flex size-full flex-col items-center justify-center gap-1.5 text-neutral-500">
                <VideoOff className="size-5" />
                <span className="text-[11px]">摄像头已关</span>
              </div>
            )}
            <div className="absolute inset-x-2.5 bottom-2 flex items-center gap-2">
              <span className="text-[11px] text-neutral-300">我</span>
              <div className="min-w-0 flex-1">
                <LevelMeter handleRef={meter} />
              </div>
            </div>
          </div>
        </div>

        {codeOpen && (
          <div className="min-w-0 flex-1">
            <CodingPanel onSubmit={(l, s) => void submitCode(l, s)} onClose={() => setCodeOpen(false)} />
          </div>
        )}

        {/* 提词器：浮层，可随时关掉 */}
        {promptOpen && (
          <aside className="w-[268px] shrink-0 overflow-y-auto border-l border-white/10 bg-neutral-900 p-4">
            <div className="flex items-center gap-2">
              <Lightbulb className="size-4 text-amber-400" />
              <span className="flex-1 text-[13px] font-medium">提词器</span>
              <button
                type="button"
                onClick={() => setPromptOpen(false)}
                aria-label="关闭提词器"
                className="rounded p-1 text-neutral-400 transition-colors hover:bg-white/10 hover:text-white"
              >
                <X className="size-3.5" />
              </button>
            </div>

            {!hint ? (
              <p className="mt-3 text-[12px] leading-relaxed text-neutral-400">
                卡壳时点下方「求助提词」，这里会给出关键词和展开方向
              </p>
            ) : (
              <div className="mt-3 space-y-3">
                <div className="flex flex-wrap gap-1.5">
                  {hint.keywords.map((k, i) => (
                    <Badge
                      key={`${k}-${i}`}
                      variant="secondary"
                      className="bg-white/10 text-[11px] text-neutral-100"
                    >
                      {k}
                    </Badge>
                  ))}
                </div>
                <ul className="space-y-1.5">
                  {hint.outline.map((o, i) => (
                    <li key={`${o}-${i}`} className="selectable text-[12px] text-neutral-300">
                      · {o}
                    </li>
                  ))}
                </ul>
                {hint.caution && (
                  <p className="selectable text-[12px] text-amber-400">注意：{hint.caution}</p>
                )}
              </div>
            )}

            {star.behavioral && (
              <div className="mt-5 border-t border-white/10 pt-4">
                <p className="text-[12.5px] font-medium">STAR 完整度</p>
                <p className="mt-1 text-[11.5px] text-neutral-400">缺环节面试官会继续追问</p>
                <div className="mt-2 flex gap-1.5">
                  {STAR_ELEMENTS.map((el) => {
                    const got = presentSet.has(el.key);
                    return (
                      <span
                        key={el.key}
                        className={cn(
                          "flex-1 rounded-md py-1.5 text-center text-[11px] font-semibold transition-colors",
                          got
                            ? "bg-emerald-500/20 text-emerald-300"
                            : "bg-white/5 text-neutral-500",
                        )}
                      >
                        {el.label}
                      </span>
                    );
                  })}
                </div>
              </div>
            )}
          </aside>
        )}
      </div>

      {/* 底部控制栏 */}
      <footer className="flex h-14 shrink-0 items-center gap-3 border-t border-white/10 bg-neutral-900 px-4">
        <div className="flex min-w-0 items-center gap-2.5">
          <Badge variant="secondary" className="bg-white/10 text-[11px] text-neutral-200">
            {labelOf(INTERVIEW_PHASE, phase)}
          </Badge>
          <span className={cn("flex items-center gap-1.5 text-[11.5px]", link.tone)}>
            <span className="size-1.5 rounded-full bg-current" />
            {link.text}
          </span>
          <span data-numeric className="text-[13px] font-medium text-neutral-200">
            {mmss(elapsed)}
            <span className="ml-1 text-[11.5px] text-neutral-500">/ {mmss(elapsed + remaining)}</span>
          </span>
          {director && !codeOpen && (
            <span className="truncate text-[11.5px] text-neutral-500">{director}</span>
          )}
        </div>

        <div className="flex-1" />

        <IconAction label={muted ? "取消静音" : "静音"} onClick={() => void toggleMute()} on={muted}>
          {muted ? <MicOff /> : <Mic />}
        </IconAction>
        <IconAction
          label={cameraOn ? "关闭摄像头" : "开启摄像头"}
          onClick={() => void toggleCamera()}
          on={cameraOn}
        >
          {cameraOn ? <Video /> : <VideoOff />}
        </IconAction>
        <IconAction label="代码沙盒" onClick={() => setCodeOpen((v) => !v)} on={codeOpen}>
          <Code2 />
        </IconAction>
        <IconAction label="打断面试官" onClick={() => void interrupt()}>
          <Zap />
        </IconAction>
        <IconAction
          label={promptOpen ? "关闭提词器" : "打开提词器"}
          onClick={() => setPromptOpen((v) => !v)}
          on={promptOpen}
        >
          <Lightbulb />
        </IconAction>

        <Button
          size="sm"
          className="ml-1 h-8 bg-white/10 text-neutral-100 hover:bg-white/20"
          onClick={() => void requestHint()}
          disabled={hintCooling}
        >
          求助提词
        </Button>
        <Button size="sm" variant="destructive" className="h-8" onClick={() => void end()}>
          <PhoneOff />
          {confirmEnd ? "再点一次确认" : "结束面试"}
        </Button>
      </footer>
    </div>
  );
}

function IconAction({
  label,
  onClick,
  on,
  children,
}: {
  label: string;
  onClick: () => void;
  on?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onClick}
          aria-label={label}
          className={cn(
            "flex size-9 items-center justify-center rounded-full transition-colors [&>svg]:size-4",
            on ? "bg-white/20 text-white" : "bg-white/8 text-neutral-300 hover:bg-white/15",
          )}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );
}

function mmss(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = String(Math.floor(total / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
}
