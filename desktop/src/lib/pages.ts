import {
  BookMarked,
  LayoutDashboard,
  Settings,
  Sparkles,
  TrendingUp,
  UserRoundCog,
  type LucideIcon,
} from "lucide-react";

export type PageId =
  | "dashboard"
  | "prepare"
  | "persona"
  | "mistakes"
  | "growth"
  | "settings"
  | "room"
  | "review";

interface PageMeta {
  title: string;
  icon: LucideIcon;
  /** 面试房间与复盘不进主导航：一个要独占界面，一个从别处跳入 */
  inNav: boolean;
}

export const PAGES: Record<PageId, PageMeta> = {
  dashboard: { title: "工作台", icon: LayoutDashboard, inNav: true },
  prepare: { title: "准备面试", icon: Sparkles, inNav: true },
  persona: { title: "人设工坊", icon: UserRoundCog, inNav: true },
  mistakes: { title: "错题本", icon: BookMarked, inNav: true },
  growth: { title: "成长轨迹", icon: TrendingUp, inNav: true },
  settings: { title: "设置", icon: Settings, inNav: false },
  room: { title: "面试进行中", icon: Sparkles, inNav: false },
  review: { title: "复盘报告", icon: BookMarked, inNav: false },
};

export const NAV_ORDER: PageId[] = ["dashboard", "prepare", "persona", "mistakes", "growth"];
