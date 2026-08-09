import { openUrl } from "@tauri-apps/plugin-opener";
import { ArrowLeft, Copy, GitFork, Mail } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

const REPO = "https://github.com/XUZIAa/AI-Simulation-Interview-Multi-Agent-Orchestration-Ai-agent-";
const EMAIL = "pursue_everything@163.com";

interface Props {
  onBack: () => void;
}

export function AboutView({ onBack }: Props) {
  const copy = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(`${label}已复制`);
    } catch {
      toast.error("复制失败，可以手动选中");
    }
  };

  return (
    <div className="grid-paper h-full overflow-y-auto">
      <div className="mx-auto max-w-[1180px] px-7 pt-7 pb-16">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2">
          <ArrowLeft />
          返回设置
        </Button>

        <div className="mt-8 grid gap-10 md:grid-cols-[minmax(0,320px)_minmax(0,1fr)] md:gap-14">
          <div>
            <h1 className="text-[clamp(2.75rem,6vw,4.5rem)] leading-[0.95] font-semibold tracking-[-0.04em]">
              关于
              <br />
              这个项目
            </h1>
          </div>

          <div className="selectable max-w-[62ch] space-y-7 text-[14px] leading-[1.85]">
            <div className="space-y-3">
              <button
                type="button"
                onClick={() => void openUrl(REPO)}
                className="group flex max-w-full items-center gap-2 text-left"
              >
                <GitFork className="size-4 shrink-0" />
                <span className="text-primary min-w-0 truncate font-medium group-hover:underline">
                  {REPO}
                </span>
              </button>
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={() => void copy(REPO, "仓库地址")}>
                  <Copy />
                  复制仓库地址
                </Button>
                <Button variant="outline" size="sm" onClick={() => void copy(EMAIL, "邮箱")}>
                  <Mail />
                  {EMAIL}
                </Button>
              </div>
            </div>

            <p>
              我是一个正在找工作的计算机科学与技术专业的学生。找工作的时候想找一个开源的、能真正陪我练口语面试的软件，
              翻了很久没找到，于是自己写了一个。
            </p>

            <p>
              有任何问题，欢迎联系我的邮箱{" "}
              <button
                type="button"
                onClick={() => void copy(EMAIL, "邮箱")}
                className="text-primary font-medium hover:underline"
              >
                {EMAIL}
              </button>
              。
            </p>

            <p>
              <span className="text-foreground font-semibold">完全免费使用，免费开源，代码全部开源。</span>{" "}
              没有任何付费点，也不打算加。
            </p>

            <div className="space-y-7">
              <p>
                面试官说话的节奏和追问深度由一套确定性的状态机推进，模型只负责给回答质量打分，
                该往下深挖还是换个领域由规则算出来，这样不容易跑偏。语音为实时链路。
              </p>
              <p>
                做了人格守卫，防止面试官聊到后面忘了自己是谁；代码环节放在独立子进程里跑，
                有超时保护，不会把主程序拖死。所有数据都在你自己的电脑上。
              </p>
            </div>

            <div className="border-primary/25 bg-primary/[0.04] space-y-3 rounded-xl border-l-2 py-4 pr-5 pl-5">
              <p className="text-foreground font-semibold">我有一个愿望</p>
              <p>
                希望大家愿意分享自己的面经，用来一起加强这个 agent。你帮助我，我帮助你，
                最后我们都能拿到一个 offer。
              </p>
              <p className="text-muted-foreground text-[13px]">
                这是后期想做的事，现在还没开始。
              </p>
            </div>

            <p>
              目前已经格式化并加入了几万条公开面经，其中所有隐私信息和公司信息都已去除。
              不过现在只覆盖了后端开发和 agent 开发两个方向。如果真的有人用起来，
              我会认真考虑上面那个想法。
            </p>

            <div className="space-y-3 border-t pt-8">
              <p className="text-[16px] leading-[1.9] italic">
                最后，找工作是一场孤独的修行，希望这个小工具能陪你走过一段难熬日子。
              </p>
              <p className="text-[16px] leading-[1.9] italic">
                祝你在下一次真实面试中，对答如流，拿下心仪的 Offer！
              </p>
              <p className="text-[16px] leading-[1.9] italic">
                「长风破浪会有时，直挂云帆济沧海。」
              </p>
              <p className="text-muted-foreground text-[13px] italic">—— 唐 · 李白《行路难》</p>
            </div>

            <p className="text-muted-foreground border-t pt-7 text-[13px]">
              这个项目的很多代码由 Claude Opus 协助完成，在此致谢。
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
