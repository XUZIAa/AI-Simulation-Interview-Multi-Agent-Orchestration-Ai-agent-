import { cn } from "@/lib/utils";

interface Props {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  /** 宽版用于表单与图表密集的页面 */
  wide?: boolean;
}

/** 页面统一骨架：标题区固定，内容区独立滚动。
 *  整页塞进一个滚动容器会让标题在首屏被裁掉。 */
export function PageContainer({ title, description, actions, children, wide }: Props) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-start justify-between gap-4 px-8 pt-7 pb-5">
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold tracking-tight">{title}</h1>
          {description && (
            <p className="text-muted-foreground mt-1 truncate text-sm">{description}</p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* 上限放宽到 1600px：这类仪表盘在宽屏上留白过多会显得空 */}
        <div className={cn("mx-auto px-8 pb-10", wide ? "max-w-[1600px]" : "max-w-6xl")}>
          {children}
        </div>
      </div>
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  hint,
  action,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  hint?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <div className="bg-muted flex size-11 items-center justify-center rounded-xl">
        <Icon className="text-muted-foreground size-5" />
      </div>
      <div>
        <p className="text-sm font-medium">{title}</p>
        {hint && <p className="text-muted-foreground mt-1 text-sm">{hint}</p>}
      </div>
      {action}
    </div>
  );
}
