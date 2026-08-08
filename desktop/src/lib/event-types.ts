// 由 tools/gen_frontend_types.py 生成，请勿手改。
// 事件载荷来自后端 core/events.py 的 dataclass 定义。

export interface AudioLevel {
  candidate: number;
  interviewer: number;
}

export interface CodeSubmitted {
  language: string;
  source: string;
}

export interface CopilotHint {
  keywords: string[];
  outline: string[];
  caution: string;
}

export interface DirectorDecided {
  intent: "ask_new" | "follow_up" | "star_probe" | "boundary_test" | "interrupt" | "pressure" | "acknowledge" | "transition" | "coding_handoff" | "close";
  brief: string;
  target_skill: string;
  follow_up_depth: number;
}

export interface DriftDetected {
  kind: "none" | "ai_self_reveal" | "role_swap" | "refusal" | "off_domain" | "style_break" | "answer_leak";
  excerpt: string;
  repaired: boolean;
}

export interface ElapsedTick {
  elapsed_ms: number;
  remaining_ms: number;
}

export interface EngineFailure {
  user_message: string;
  detail: string;
  fatal: boolean;
}

export interface InterruptionFired {
  by_interviewer: boolean;
  reason: string;
}

export interface InterviewerSpeaking {
  speaking: boolean;
}

export interface LiveAnnotation {
  turn_id: number;
  kind: "strength" | "weakness" | "filler" | "off_topic";
  comment: string;
}

export interface LiveScoreUpdated {
  scores: { [key in "tech_depth" | "expression" | "resilience" | "value_fit" | "coding" | "collaboration"]?: number };
}

export interface PhaseChanged {
  phase: "warmup" | "resume_deep_dive" | "tech_depth" | "behavioral" | "coding" | "stress" | "candidate_qa" | "closing" | "finished";
  reason: string;
}

export interface ProsodySnapshot {
  words_per_minute: number;
  filler_ratio: number;
  pause_ratio: number;
  longest_pause_ms: number;
}

export interface RealtimeStateChanged {
  connected: boolean;
  reason: string;
}

export interface ReanchorPerformed {
  turn_index: number;
  trigger: string;
}

export interface ReviewProgress {
  stage: string;
  percent: number;
  detail: string;
}

export interface SpeechActivity {
  speaking: boolean;
}

export interface StarProgress {
  present: "situation" | "task" | "action" | "result"[];
  missing: "situation" | "task" | "action" | "result"[];
  is_behavioral: boolean;
}

export interface TranscriptCommitted {
  turn_id: number;
  speaker: string;
  text: string;
  started_at_ms: number;
  duration_ms: number;
}

export interface TranscriptDelta {
  speaker: string;
  text: string;
}

/** 事件名到载荷的映射，供 onEvent 做类型推断。 */
export interface EventMap {
  audio_level: AudioLevel;
  code_submitted: CodeSubmitted;
  copilot_hint: CopilotHint;
  director_decided: DirectorDecided;
  drift_detected: DriftDetected;
  elapsed_tick: ElapsedTick;
  engine_failure: EngineFailure;
  interruption_fired: InterruptionFired;
  interviewer_speaking: InterviewerSpeaking;
  live_annotation: LiveAnnotation;
  live_score_updated: LiveScoreUpdated;
  phase_changed: PhaseChanged;
  prosody_snapshot: ProsodySnapshot;
  realtime_state_changed: RealtimeStateChanged;
  reanchor_performed: ReanchorPerformed;
  review_progress: ReviewProgress;
  speech_activity: SpeechActivity;
  star_progress: StarProgress;
  transcript_committed: TranscriptCommitted;
  transcript_delta: TranscriptDelta;
  task_progress: TaskProgress;
}

/** 长任务进度。它不来自事件总线，由接口层按 task_id 回推。 */
export interface TaskProgress {
  task_id: string;
  stage: string;
  percent: number;
}

export type EventName = keyof EventMap;
