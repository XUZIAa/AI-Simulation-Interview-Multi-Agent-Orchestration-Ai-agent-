import CodeMirror from "@uiw/react-codemirror";
import { java } from "@codemirror/lang-java";
import { javascript } from "@codemirror/lang-javascript";
import { python } from "@codemirror/lang-python";
import {
  Code2,
  Lightbulb,
  Mic,
  MicOff,
  PhoneOff,
  Send,
  Video,
  VideoOff,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { type MeterHandle, type OrbHandle, LevelMeter, VoiceOrb } from "@/components/voice-orb";
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
import { type InterviewState, api, onEvent } from "@/lib/backend";
import type { StarProgress } from "@/lib/event-types";
import { INTERVIEW_PHASE, TURN_INTENT, labelOf } from "@/lib/labels";
import { cn } from "@/lib/utils";

const LANGUAGES = ["python", "javascript", "java"] as const;
type Language = (typeof LANGUAGES)[number];

const LANG_EXT = {
  python: python,
  javascript: javascript,
  java: java,
} as const;

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
  const [language, setLanguage] = useState<Language>("python");
  const [source, setSource] = useState("");
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
      onEvent("copilot_hint", (d) =>
        setHint({ keywords: d.keywords, outline: d.outline, caution: d.caution }),
      ),
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
    setHintCooling(true);
    setTimeout(() => setHintCooling(false), 3000);
    await api.post("/engine/hint", { auto: false }).catch(() => undefined);
  };

  const interrupt = async () => {
    await api.post("/engine/interrupt").catch(() => undefined);
  };

  const submitCode = async () => {
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
    ? { text: "连接断开", tone: "text-destructive" }
    : hearing
      ? { text: "正在听你说", tone: "text-candidate" }
      : talking
        ? { text: "面试官在说", tone: "text-interviewer" }
        : { text: "已接通", tone: "text-success" };

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <Card className="gap-0 py-3">
        <CardContent className="flex items-center gap-3 px-4">
          <Badge variant="secondary">{labelOf(INTERVIEW_PHASE, phase)}</Badge>
          <span className={cn("flex items-center gap-1.5 text-xs font-medium", link.tone)}>
            <span className="size-1.5 rounded-full bg-current" />
            {link.text}
          </span>
          {director && <span className="text-muted-foreground truncate text-xs">{director}</span>}
          <div className="flex-1" />
          <span className="font-mono text-xl font-semibold tabular-nums">{mmss(elapsed)}</span>
          <span className="text-muted-foreground text-xs">剩余 {mmss(remaining)}</span>
        </CardContent>
      </Card>

      <div className="flex min-h-0 flex-1 gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <div className="grid shrink-0 grid-cols-2 gap-3">
            <Card
              className={cn(
                "items-center justify-center gap-2 border-2 py-6 transition-colors",
                talking ? "border-interviewer" : "border-transparent",
              )}
            >
              <VoiceOrb handleRef={orb} size={148} />
              <p className="text-sm font-semibold">{state.persona.name}</p>
              <p className="text-muted-foreground text-xs">{state.persona.job_title || "面试官"}</p>
            </Card>

            <Card
              className={cn(
                "relative gap-0 overflow-hidden border-2 py-0 transition-colors",
                hearing ? "border-candidate" : "border-transparent",
              )}
            >
              <video
                ref={video}
                muted
                playsInline
                className={cn("size-full object-cover", cameraOn ? "block" : "hidden")}
              />
              {!cameraOn && (
                <div className="text-muted-foreground flex size-full min-h-[180px] flex-col items-center justify-center gap-2">
                  <VideoOff className="size-6" />
                  <span className="text-xs">摄像头已关闭</span>
                </div>
              )}
              <div className="absolute inset-x-3 bottom-2">
                <LevelMeter handleRef={meter} />
              </div>
              <span className="bg-background/70 absolute top-2 left-3 rounded px-1.5 py-0.5 text-xs backdrop-blur">
                我
              </span>
            </Card>
          </div>

          <Card className="min-h-0 flex-1 gap-0 py-3">
            <CardContent className="flex h-full min-h-0 flex-col px-4">
              <p className="text-muted-foreground mb-2 shrink-0 text-xs">实时字幕</p>
              <div ref={scroller} className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
                {lines.length === 0 ? (
                  <p className="text-muted-foreground py-8 text-center text-sm">
                    对话开始后字幕会出现在这里
                  </p>
                ) : (
                  lines.map((line) => (
                    <div
                      key={line.id}
                      className={cn(
                        "selectable rounded-lg px-3 py-2 text-sm",
                        line.speaker === "candidate"
                          ? "bg-candidate/10 ml-8"
                          : "bg-interviewer/10 mr-8",
                        line.partial && "opacity-60",
                      )}
                    >
                      <span className="text-muted-foreground mr-1.5 text-xs">
                        {line.speaker === "candidate" ? "我" : state.persona.name}
                      </span>
                      {line.text}
                    </div>
                  ))
                )}
              </div>
            </CardContent>
          </Card>

          {codeOpen && (
            <Card className="shrink-0 gap-2 py-3">
              <CardContent className="space-y-2 px-4">
                <div className="flex items-center gap-2">
                  <p className="flex-1 text-sm font-medium">代码沙盒</p>
                  <Select value={language} onValueChange={(v) => setLanguage(v as Language)}>
                    <SelectTrigger className="h-8 w-[130px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {LANGUAGES.map((l) => (
                        <SelectItem key={l} value={l}>
                          {l}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button size="sm" onClick={() => void submitCode()}>
                    <Send />
                    提交
                  </Button>
                </div>
                <div className="overflow-hidden rounded-lg border">
                  <CodeMirror
                    value={source}
                    height="200px"
                    extensions={[LANG_EXT[language]()]}
                    onChange={setSource}
                    theme={document.documentElement.classList.contains("dark") ? "dark" : "light"}
                  />
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        <div className="hidden w-[300px] shrink-0 flex-col gap-3 lg:flex">
          <Card className="gap-2 py-4">
            <CardContent className="space-y-2 px-4">
              <p className="flex items-center gap-1.5 text-sm font-medium">
                <Lightbulb className="text-warning size-4" />
                提词器
              </p>
              {!hint ? (
                <p className="text-muted-foreground text-xs">
                  卡壳时点下方「求助提词」，会给出关键词与展开方向
                </p>
              ) : (
                <div className="space-y-2">
                  <div className="flex flex-wrap gap-1.5">
                    {hint.keywords.map((k, i) => (
                      <Badge key={`${k}-${i}`} variant="secondary">
                        {k}
                      </Badge>
                    ))}
                  </div>
                  <ul className="text-muted-foreground space-y-1 text-xs">
                    {hint.outline.map((o, i) => (
                      <li key={`${o}-${i}`} className="selectable">
                        · {o}
                      </li>
                    ))}
                  </ul>
                  {hint.caution && <p className="text-warning text-xs">注意：{hint.caution}</p>}
                </div>
              )}
            </CardContent>
          </Card>

          {star.behavioral && (
            <Card className="gap-2 py-4">
              <CardContent className="space-y-2 px-4">
                <p className="text-sm font-medium">STAR 完整度</p>
                <p className="text-muted-foreground text-xs">
                  行为题回答需要逐项点亮，缺环节面试官会追问
                </p>
                <div className="flex gap-1.5">
                  {STAR_ELEMENTS.map((el) => {
                    const got = presentSet.has(el.key);
                    return (
                      <span
                        key={el.key}
                        className={cn(
                          "flex-1 rounded-md py-1.5 text-center text-xs font-semibold transition-colors",
                          got ? "bg-success/15 text-success" : "bg-muted text-muted-foreground",
                        )}
                      >
                        {el.label}
                      </span>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      <Card className="shrink-0 gap-0 py-3">
        <CardContent className="flex flex-wrap items-center gap-2 px-4">
          <Button variant={muted ? "secondary" : "outline"} onClick={() => void toggleMute()}>
            {muted ? <MicOff /> : <Mic />}
            {muted ? "已静音" : "静音"}
          </Button>
          <Button variant="outline" onClick={() => void toggleCamera()}>
            {cameraOn ? <Video /> : <VideoOff />}
            {cameraOn ? "关闭摄像头" : "开启摄像头"}
          </Button>
          <Button
            variant={codeOpen ? "secondary" : "outline"}
            onClick={() => setCodeOpen((v) => !v)}
          >
            <Code2 />
            代码沙盒
          </Button>
          <div className="flex-1" />
          <Button variant="outline" onClick={() => void interrupt()}>
            <Zap />
            打断面试官
          </Button>
          <Button onClick={() => void requestHint()} disabled={hintCooling}>
            <Lightbulb />
            求助提词
          </Button>
          <Button variant="destructive" onClick={() => void end()}>
            <PhoneOff />
            {confirmEnd ? "再点一次确认结束" : "结束面试"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

function mmss(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = String(Math.floor(total / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
}
