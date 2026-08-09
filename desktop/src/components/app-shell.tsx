import { Moon, Settings, Sun, Target } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { NAV_ORDER, PAGES, type PageId } from "@/lib/pages";
import { type ThemeMode, applyTheme, readTheme, watchSystemTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

interface Props {
  page: PageId;
  onNavigate: (page: PageId) => void;
  connected: boolean;
  children: React.ReactNode;
}

export function AppShell({ page, onNavigate, connected, children }: Props) {
  const [mode, setMode] = useState<ThemeMode>(readTheme);

  useEffect(() => {
    applyTheme(mode);
    return watchSystemTheme(() => applyTheme("system"));
  }, [mode]);

  // 面试进行中独占界面：此时任何导航都是干扰
  const immersive = page === "room";

  return (
    <div className="bg-background flex h-full flex-col">
      {!immersive && (
        <header
          data-print="hide"
          className="bg-background/85 flex h-14 shrink-0 items-center gap-1 border-b px-4 backdrop-blur"
        >
          <div className="mr-4 flex items-center gap-2.5 pl-1">
            <div className="bg-primary flex size-7 items-center justify-center rounded-lg">
              <Target className="text-primary-foreground size-4" strokeWidth={2.4} />
            </div>
            <span className="text-[15px] font-semibold tracking-tight">AI 模拟面试</span>
          </div>

          <nav className="flex items-center gap-0.5">
            {NAV_ORDER.map((id) => {
              const meta = PAGES[id];
              const active = page === id;
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => onNavigate(id)}
                  className={cn(
                    "relative flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                    active
                      ? "text-foreground bg-accent"
                      : "text-muted-foreground hover:text-foreground hover:bg-accent/60",
                  )}
                >
                  <meta.icon className="size-4" />
                  {meta.title}
                </button>
              );
            })}
          </nav>

          <div className="flex-1" />

          <ConnectionDot connected={connected} />

          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setMode(nextMode(mode))}
                aria-label="切换主题"
              >
                {mode === "dark" ? <Moon /> : <Sun />}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{THEME_LABEL[mode]}</TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={page === "settings" ? "secondary" : "ghost"}
                size="icon"
                onClick={() => onNavigate("settings")}
                aria-label="设置"
              >
                <Settings />
              </Button>
            </TooltipTrigger>
            <TooltipContent>设置</TooltipContent>
          </Tooltip>
        </header>
      )}

      <main data-print="flow" className="min-h-0 flex-1 overflow-hidden">
        {children}
      </main>
    </div>
  );
}

const THEME_LABEL: Record<ThemeMode, string> = {
  light: "浅色（点击切换到深色）",
  dark: "深色（点击跟随系统）",
  system: "跟随系统（点击切换到浅色）",
};

function nextMode(mode: ThemeMode): ThemeMode {
  if (mode === "light") return "dark";
  if (mode === "dark") return "system";
  return "light";
}

function ConnectionDot({ connected }: { connected: boolean }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="mr-1 flex items-center gap-1.5 px-2">
          <span
            className={cn(
              "size-2 rounded-full",
              connected ? "bg-success" : "bg-destructive animate-pulse",
            )}
          />
          <span className="text-muted-foreground text-xs">{connected ? "本地" : "断开"}</span>
        </div>
      </TooltipTrigger>
      <TooltipContent>
        {connected ? "已连接本机后端，数据全部留在这台机器" : "与本机后端的连接已断开"}
      </TooltipContent>
    </Tooltip>
  );
}
