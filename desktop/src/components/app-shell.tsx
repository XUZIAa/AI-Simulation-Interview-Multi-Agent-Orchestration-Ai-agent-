import { Moon, Settings, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import { TitleBar } from "@/components/title-bar";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { NAV_GROUPS, PAGES, type PageId } from "@/lib/pages";
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
      <TitleBar dark={immersive} />
      <div className="flex min-h-0 flex-1">
      {!immersive && (
        <aside
          data-print="hide"
          className="bg-card flex w-[232px] shrink-0 flex-col border-r"
        >
          <div className="flex shrink-0 items-center gap-3 px-4 pt-5 pb-2">
            {/* logo 图自带文字，小尺寸下会糊成一团，这里裁掉只留徽章，
                文字交给真排版。白底在浅色侧边栏上无缝，深色下则成为刻意的白徽章。 */}
            <span className="relative size-11 shrink-0 overflow-hidden rounded-lg bg-white">
              <img
                src="/logo.png"
                alt=""
                className="absolute top-0 left-1/2 w-[126%] max-w-none -translate-x-1/2"
              />
            </span>
            <span className="text-[16.5px] font-semibold tracking-tight">AI 面试助手</span>
          </div>

          <nav className="min-h-0 flex-1 overflow-y-auto px-3 pt-4 pb-3">
            {NAV_GROUPS.map((group, gi) => (
              <div key={group.label ?? `g${gi}`} className={gi > 0 ? "mt-5" : undefined}>
                {group.label && (
                  <p className="text-muted-foreground/70 mb-2 px-2.5 text-[11px] font-semibold tracking-[0.09em]">
                    {group.label}
                  </p>
                )}
                <div className="space-y-0.5">
                  {group.items.map((id) => {
                    const meta = PAGES[id];
                    const active = page === id;
                    return (
                      <button
                        key={id}
                        type="button"
                        onClick={() => onNavigate(id)}
                        className={cn(
                          "relative flex h-10 w-full items-center gap-2.5 rounded-lg px-2.5 text-[14.5px] transition-colors duration-150 ease-out",
                          active
                            ? "bg-primary/[0.07] text-primary font-medium"
                            : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                        )}
                      >
                        {active && (
                          <span className="bg-primary absolute top-1/2 -left-1 h-4 w-[3px] -translate-y-1/2 rounded-r-full" />
                        )}
                        <meta.icon className="size-[17px] shrink-0" />
                        {meta.title}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </nav>

          <div className="flex shrink-0 items-center gap-1 border-t p-3">
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="min-w-0 flex-1 cursor-default px-1.5">
                  <div className="flex items-center gap-1.5">
                    <span
                      className={cn(
                        "size-1.5 shrink-0 rounded-full",
                        connected ? "bg-success" : "bg-destructive animate-pulse",
                      )}
                    />
                    <span className="truncate text-xs font-medium">
                      {connected ? "已连接本机" : "连接断开"}
                    </span>
                  </div>
                  <p className="text-muted-foreground mt-0.5 truncate text-[11px]">
                    数据留在这台机器
                  </p>
                </div>
              </TooltipTrigger>
              <TooltipContent side="top">
                {connected
                  ? "后端在本机运行，没有任何数据外传"
                  : "与本机后端的连接已断开"}
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8 shrink-0"
                  onClick={() => setMode(nextMode(mode))}
                  aria-label="切换主题"
                >
                  {mode === "dark" ? <Moon /> : <Sun />}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top">{THEME_LABEL[mode]}</TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant={page === "settings" ? "secondary" : "ghost"}
                  size="icon"
                  className="size-8 shrink-0"
                  onClick={() => onNavigate("settings")}
                  aria-label="设置"
                >
                  <Settings />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top">设置</TooltipContent>
            </Tooltip>
          </div>
        </aside>
      )}

      <main data-print="flow" className="min-w-0 flex-1 overflow-hidden">
        {children}
      </main>
      </div>
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
