/** 枚举的中文名，取自后端 core/types.py 的 label 定义。
 *  那是 Python property，不会进 JSON，所以前端自备一份。 */

export const SCORE_DIMENSION: Record<string, string> = {
  tech_depth: "技术深度",
  expression: "逻辑表达",
  resilience: "抗压能力",
  value_fit: "价值观匹配",
  coding: "编码能力",
  collaboration: "沟通协作",
};

export const GAP_SEVERITY: Record<string, string> = {
  blocker: "致命缺口",
  major: "重点缺口",
  minor: "次要缺口",
};

export const SESSION_STATUS: Record<string, string> = {
  draft: "未开始",
  running: "进行中",
  // 强退的面试会被认领成这个状态，对用户是「还没出复盘」而非正在生成
  reviewing: "待复盘",
  completed: "已完成",
  aborted: "已中止",
};

export const COMPANY_TIER: Record<string, string> = {
  big_tech: "互联网大厂",
  mid_tech: "中型科技公司",
  startup: "创业公司",
  manufacturing: "制造业 / 工业软件",
  state_owned: "国企 / 事业单位",
  foreign: "外企 / 跨国研发中心",
  finance: "银行 / 券商 / 金融科技",
  outsource: "外包 / 乙方交付",
};

export const JOB_LEVEL: Record<string, string> = {
  intern: "实习 / 应届",
  junior: "初级（1-3 年）",
  mid: "中级（3-5 年）",
  senior: "高级（5-8 年）",
  expert: "专家 / 架构（8 年以上）",
};

export const INTERVIEW_PHASE: Record<string, string> = {
  warmup: "开场破冰",
  resume_deep_dive: "简历深挖",
  tech_depth: "技术深度",
  behavioral: "行为面试",
  coding: "编码环节",
  stress: "压力测试",
  candidate_qa: "候选人提问",
  closing: "面试收尾",
  finished: "已结束",
};

export const TURN_INTENT: Record<string, string> = {
  ask_new: "提出新问题",
  follow_up: "顺着回答追问",
  star_probe: "引导补全 STAR",
  boundary_test: "边界与极限测试",
  interrupt: "打断候选人",
  pressure: "施加压力",
  acknowledge: "简短回应",
  transition: "切换环节",
  coding_handoff: "移交编码环节",
  close: "结束面试",
};

export const ANNOTATION_KIND: Record<string, string> = {
  strength: "亮点",
  weakness: "待改进",
  filler: "冗余表达",
  off_topic: "偏离问题",
};

export const DRIFT_KIND: Record<string, string> = {
  none: "无",
  ai_self_reveal: "暴露 AI 身份",
  role_swap: "角色错位",
  refusal: "拒答",
  off_domain: "跑出领域",
  style_break: "风格断裂",
  answer_leak: "泄露答案",
};

export function labelOf(map: Record<string, string>, key: string): string {
  return map[key] ?? key;
}
