import { getCurrentWindow } from "@tauri-apps/api/window";
import { Minus, Square, Copy as Squares, X } from "lucide-react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

/** 自绘标题栏。系统边框已关掉，所以拖动、最大化、关闭都得自己接。
 *  拖拽只认带 data-tauri-drag-region 的元素，按钮不带这个属性，
 *  所以点按钮不会误触发拖窗口。 */
export function TitleBar({ dark }: { dark?: boolean }) {
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    const win = getCurrentWindow();
    let alive = true;
    const sync = async () => {
      const next = await win.isMaximized().catch(() => false);
      if (alive) setMaximized(next);
    };
    void sync();
    const off = win.onResized(() => void sync());
    return () => {
      alive = false;
      void off.then((fn) => fn());
    };
  }, []);

  const win = getCurrentWindow();

  return (
    <header
      data-tauri-drag-region
      data-print="hide"
      className={cn(
        "flex h-8 shrink-0 items-center justify-between border-b pl-4 select-none",
        dark ? "border-white/10 bg-neutral-900" : "bg-card",
      )}
    >
      <span
        data-tauri-drag-region
        className={cn("text-[11.5px]", dark ? "text-neutral-500" : "text-muted-foreground/70")}
      >
        AI 面试助手
      </span>

      <div className="flex items-center gap-2 pr-3.5">
        <Dot
          tone="amber"
          label="最小化"
          onClick={() => void win.minimize()}
          icon={<Minus strokeWidth={3} />}
        />
        <Dot
          tone="green"
          label={maximized ? "还原窗口" : "最大化"}
          onClick={() => void win.toggleMaximize()}
          icon={maximized ? <Squares strokeWidth={3} /> : <Square strokeWidth={3} />}
        />
        <Dot
          tone="red"
          label="关闭"
          onClick={() => void win.close()}
          icon={<X strokeWidth={3} />}
        />
      </div>
    </header>
  );
}

const TONE = {
  amber: "bg-[#e6b64c] hover:bg-[#f0c05a]",
  green: "bg-[#57c05a] hover:bg-[#62cf66]",
  red: "bg-[#e0655c] hover:bg-[#ee7268]",
} as const;

function Dot({
  tone,
  label,
  onClick,
  icon,
}: {
  tone: keyof typeof TONE;
  label: string;
  onClick: () => void;
  icon: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={cn(
        "group flex size-[13px] items-center justify-center rounded-full transition-colors duration-150",
        // 图标只在悬停时浮现，静态时保持三个干净的色点
        "[&>svg]:size-2 [&>svg]:opacity-0 [&>svg]:transition-opacity hover:[&>svg]:opacity-70",
        TONE[tone],
      )}
    >
      <span className="text-black/75">{icon}</span>
    </button>
  );
}
