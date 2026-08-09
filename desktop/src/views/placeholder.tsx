import { Hammer } from "lucide-react";

import { EmptyState, PageContainer } from "@/components/page-container";
import { PAGES, type PageId } from "@/lib/pages";

/** 尚未迁移的页面。逐页替换掉它，而不是一次性铺开。 */
export function PlaceholderView({ page }: { page: PageId }) {
  const meta = PAGES[page];
  return (
    <PageContainer title={meta.title} description="这一页正在迁移到新界面">
      <EmptyState
        icon={Hammer}
        title="尚未迁移"
        hint="后端能力已就绪，界面按复杂度从低到高逐页替换。"
      />
    </PageContainer>
  );
}
