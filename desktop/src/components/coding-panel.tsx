import { java } from "@codemirror/lang-java";
import { javascript } from "@codemirror/lang-javascript";
import { python } from "@codemirror/lang-python";
import CodeMirror from "@uiw/react-codemirror";
import {
  Check,
  ChevronDown,
  Eye,
  EyeOff,
  Lightbulb,
  Loader2,
  Play,
  RotateCcw,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  type CodingChallenge,
  type JudgeOutcome,
  type RunOutcome,
  api,
} from "@/lib/backend";
import { cn } from "@/lib/utils";

// 后端只保证这两种能真的跑起来，别的语言不列出来假装支持
const LANGUAGES = [
  { key: "python", label: "Python" },
  { key: "javascript", label: "JavaScript" },
] as const;

type Language = (typeof LANGUAGES)[number]["key"];

const LANG_EXT = { python, javascript, java } as const;

type Tab = "run" | "cases";

interface Props {
  onSubmit: (language: string, source: string) => void;
  onClose: () => void;
}

export function CodingPanel({ onSubmit, onClose }: Props) {
  const [challenge, setChallenge] = useState<CodingChallenge | null>(null);
  const [composing, setComposing] = useState(false);
  const [language, setLanguage] = useState<Language>("python");
  const [source, setSource] = useState("");
  const [running, setRunning] = useState(false);
  const [judging, setJudging] = useState(false);
  const [stdin, setStdin] = useState("");
  const [run, setRun] = useState<RunOutcome | null>(null);
  const [verdict, setVerdict] = useState<JudgeOutcome | null>(null);
  const [tab, setTab] = useState<Tab>("cases");
  const [showAnswer, setShowAnswer] = useState(false);
  const [showHints, setShowHints] = useState(false);

  const dark = document.documentElement.classList.contains("dark");

  const compose = async () => {
    setComposing(true);
    try {
      const next = await api.post<CodingChallenge>("/coding/challenge", { skill: "" });
      setChallenge(next);
      setSource(next.starter[language] ?? "");
      setStdin(next.cases[0]?.input ?? "");
      setVerdict(null);
      setRun(null);
      setShowAnswer(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "出题失败");
    } finally {
      setComposing(false);
    }
  };

  const switchLanguage = (next: Language) => {
    setLanguage(next);
    // 只在还没动过代码时替换骨架，避免把人写的东西冲掉
    const current = challenge?.starter[language] ?? "";
    if (challenge && (!source.trim() || source === current)) {
      setSource(challenge.starter[next] ?? "");
    }
  };

  const doRun = async () => {
    if (!source.trim()) {
      toast.error("先写点代码");
      return;
    }
    setRunning(true);
    setTab("run");
    try {
      setRun(await api.post<RunOutcome>("/coding/run", { language, source, stdin }));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "运行失败");
    } finally {
      setRunning(false);
    }
  };

  const doJudge = async () => {
    if (!challenge?.cases.length) {
      toast.error("这道题没有用例");
      return;
    }
    setJudging(true);
    setTab("cases");
    try {
      const result = await api.post<JudgeOutcome>("/coding/judge", {
        language,
        source,
        cases: challenge.cases,
      });
      setVerdict(result);
      if (result.passed === result.total) toast.success(`全部通过 ${result.passed}/${result.total}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "判题失败");
    } finally {
      setJudging(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-neutral-900 text-neutral-100">
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-white/10 px-3">
        <span className="text-[13px] font-medium">代码沙盒</span>
        {challenge && (
          <span className="truncate text-[12px] text-neutral-400">{challenge.title}</span>
        )}
        <div className="flex-1" />
        <Button
          size="sm"
          variant="ghost"
          className="h-7 text-neutral-300 hover:bg-white/10 hover:text-white"
          onClick={onClose}
        >
          <X />
          关闭
        </Button>
      </header>

      {!challenge ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
          <p className="text-[13px] text-neutral-400">
            让面试官出一道编码题，可以直接运行和对用例
          </p>
          <Button onClick={() => void compose()} disabled={composing}>
            {composing ? <Loader2 className="animate-spin" /> : <Sparkles />}
            {composing ? "正在出题（约一分钟）" : "出一道题"}
          </Button>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
          {/* 题面 */}
          <div className="min-h-0 overflow-y-auto border-r border-white/10 p-4">
            <div className="prose prose-invert prose-sm selectable max-w-none prose-headings:text-[14px] prose-p:text-[13px] prose-li:text-[13px] prose-code:text-[12px]">
              <Markdown remarkPlugins={[remarkGfm]}>{challenge.statement}</Markdown>
            </div>

            {challenge.io_format && (
              <div className="mt-4">
                <p className="mb-1.5 text-[11px] font-semibold tracking-wide text-neutral-400">
                  输入输出格式
                </p>
                <pre className="selectable overflow-x-auto rounded-lg bg-black/40 p-3 text-[12px] whitespace-pre-wrap text-neutral-200">
                  {challenge.io_format}
                </pre>
              </div>
            )}

            {challenge.cases.length > 0 && (
              <div className="mt-4 space-y-2">
                <p className="text-[11px] font-semibold tracking-wide text-neutral-400">样例</p>
                {challenge.cases.slice(0, 2).map((c, i) => (
                  <div key={i} className="rounded-lg bg-black/40 p-3 text-[12px]">
                    <p className="text-neutral-400">输入</p>
                    <pre className="selectable mt-0.5 whitespace-pre-wrap text-neutral-100">
                      {c.input || "（无）"}
                    </pre>
                    <p className="mt-2 text-neutral-400">输出</p>
                    <pre className="selectable mt-0.5 whitespace-pre-wrap text-neutral-100">
                      {c.expected}
                    </pre>
                  </div>
                ))}
              </div>
            )}

            {challenge.hints.length > 0 && (
              <div className="mt-4">
                <button
                  type="button"
                  onClick={() => setShowHints((v) => !v)}
                  className="flex items-center gap-1.5 text-[12px] text-neutral-400 hover:text-neutral-200"
                >
                  <Lightbulb className="size-3.5" />
                  提示 {challenge.hints.length} 条
                  <ChevronDown className={cn("size-3.5 transition-transform", showHints && "rotate-180")} />
                </button>
                {showHints && (
                  <ul className="mt-2 space-y-1.5">
                    {challenge.hints.map((h, i) => (
                      <li key={i} className="selectable text-[12px] text-neutral-300">
                        {i + 1}. {h}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            <div className="mt-4 border-t border-white/10 pt-3">
              <button
                type="button"
                onClick={() => setShowAnswer((v) => !v)}
                className="flex items-center gap-1.5 text-[12px] text-neutral-400 hover:text-neutral-200"
              >
                {showAnswer ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                {showAnswer ? "收起参考答案" : "看参考答案"}
              </button>
              {showAnswer && (
                <pre className="selectable mt-2 overflow-x-auto rounded-lg bg-black/40 p-3 text-[12px] text-neutral-200">
                  {challenge.reference[language] || "这门语言没有参考答案"}
                </pre>
              )}
            </div>
          </div>

          {/* 编辑器与结果 */}
          <div className="flex min-h-0 flex-col">
            <div className="flex h-10 shrink-0 items-center gap-2 border-b border-white/10 px-3">
              <Select value={language} onValueChange={(v) => switchLanguage(v as Language)}>
                <SelectTrigger className="h-7 w-[130px] border-white/15 bg-white/5 text-[12px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LANGUAGES.map((l) => (
                    <SelectItem key={l.key} value={l.key}>
                      {l.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-neutral-300 hover:bg-white/10 hover:text-white"
                onClick={() => setSource(challenge.starter[language] ?? "")}
              >
                <RotateCcw />
                重置
              </Button>
              <div className="flex-1" />
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-neutral-300 hover:bg-white/10 hover:text-white"
                onClick={() => void doRun()}
                disabled={running}
              >
                {running ? <Loader2 className="animate-spin" /> : <Play />}
                运行
              </Button>
              <Button size="sm" className="h-7" onClick={() => void doJudge()} disabled={judging}>
                {judging ? <Loader2 className="animate-spin" /> : <Check />}
                跑用例
              </Button>
              <Button
                size="sm"
                variant="secondary"
                className="h-7"
                onClick={() => onSubmit(language, source)}
              >
                <Send />
                交给面试官
              </Button>
            </div>

            <div className="min-h-0 flex-1 overflow-hidden">
              <CodeMirror
                value={source}
                height="100%"
                className="h-full text-[13px]"
                extensions={[LANG_EXT[language]()]}
                onChange={setSource}
                theme={dark ? "dark" : "light"}
                basicSetup={{ autocompletion: false, highlightActiveLine: true }}
              />
            </div>

            <div className="flex h-[38%] min-h-0 shrink-0 flex-col border-t border-white/10">
              <div className="flex h-8 shrink-0 items-center gap-1 px-2">
                <TabButton active={tab === "cases"} onClick={() => setTab("cases")}>
                  用例
                  {verdict && (
                    <Badge
                      variant="secondary"
                      className={cn(
                        "ml-1.5 h-4 px-1 text-[10px]",
                        verdict.passed === verdict.total
                          ? "bg-emerald-500/20 text-emerald-300"
                          : "bg-red-500/20 text-red-300",
                      )}
                    >
                      {verdict.passed}/{verdict.total}
                    </Badge>
                  )}
                </TabButton>
                <TabButton active={tab === "run"} onClick={() => setTab("run")}>
                  自定义运行
                </TabButton>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
                {tab === "cases" ? (
                  !verdict ? (
                    <p className="pt-3 text-[12px] text-neutral-500">
                      点「跑用例」逐条对照期望输出
                    </p>
                  ) : (
                    <ul className="space-y-1.5 pt-1">
                      {verdict.cases.map((c) => (
                        <li key={c.index} className="rounded-lg bg-black/40 p-2.5 text-[12px]">
                          <div className="flex items-center gap-2">
                            <span
                              className={cn(
                                "flex size-4 items-center justify-center rounded-full text-[10px] font-semibold",
                                c.passed
                                  ? "bg-emerald-500/20 text-emerald-300"
                                  : "bg-red-500/20 text-red-300",
                              )}
                            >
                              {c.passed ? "✓" : "✕"}
                            </span>
                            <span className="text-neutral-300">用例 {c.index + 1}</span>
                            <span className="text-neutral-500">{c.duration_ms}ms</span>
                            {c.timed_out && <span className="text-amber-400">超时</span>}
                          </div>
                          {!c.passed && (
                            <div className="selectable mt-1.5 grid gap-1 text-[11.5px] text-neutral-400">
                              <span>输入 {c.input || "（无）"}</span>
                              <span>期望 {c.expected}</span>
                              <span className="text-red-300">实际 {c.actual.trim() || "（空）"}</span>
                              {c.stderr && (
                                <span className="text-red-300">错误 {c.stderr.trim()}</span>
                              )}
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  )
                ) : (
                  <div className="space-y-2 pt-1">
                    <textarea
                      value={stdin}
                      onChange={(e) => setStdin(e.target.value)}
                      rows={3}
                      spellCheck={false}
                      placeholder="标准输入"
                      className="selectable w-full resize-none rounded-lg bg-black/40 p-2.5 font-mono text-[12px] text-neutral-100 outline-none placeholder:text-neutral-600"
                    />
                    {run && (
                      <div className="rounded-lg bg-black/40 p-2.5 text-[12px]">
                        <div className="flex items-center gap-2 text-neutral-400">
                          <span className={run.ok ? "text-emerald-400" : "text-red-400"}>
                            {run.timed_out ? "超时终止" : run.ok ? "运行成功" : `退出码 ${run.exit_code}`}
                          </span>
                          <span data-numeric>{run.duration_ms}ms</span>
                        </div>
                        {run.stdout && (
                          <pre className="selectable mt-1.5 whitespace-pre-wrap text-neutral-100">
                            {run.stdout}
                          </pre>
                        )}
                        {run.stderr && (
                          <pre className="selectable mt-1.5 whitespace-pre-wrap text-red-300">
                            {run.stderr}
                          </pre>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center rounded-md px-2.5 py-1 text-[12px] transition-colors",
        active ? "bg-white/10 text-white" : "text-neutral-400 hover:text-neutral-200",
      )}
    >
      {children}
    </button>
  );
}
