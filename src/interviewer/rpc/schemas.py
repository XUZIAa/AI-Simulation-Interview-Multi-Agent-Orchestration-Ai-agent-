from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.types import CompanyTier, JobLevel
from ..domain.persona import PersonaContract


class TaskBody(BaseModel):
    """长任务的公共字段。

    出题、解析简历都要几十秒，进度不可能塞进 HTTP 响应。前端生成 task_id，
    后端把 on_progress 转成 task_progress 事件按这个 id 回推。
    """

    task_id: str = Field(default="", max_length=64)


class StartInterviewBody(BaseModel):
    """只传 session_id：InterviewState 有 37 个字段且内含整份题库，
    让它在前后端往返一遍纯属浪费，后端自己从库里取更可靠。"""

    session_id: int


class StopInterviewBody(BaseModel):
    aborted: bool = False


class MuteBody(BaseModel):
    muted: bool


class HintBody(BaseModel):
    auto: bool = False


class SubmitCodeBody(BaseModel):
    language: str = Field(min_length=1, max_length=40)
    source: str


class BuildSessionBody(TaskBody):
    persona: PersonaContract
    resume_id: int | None = None
    job_id: int | None = None
    tier: CompanyTier
    level: JobLevel
    minutes: int = Field(ge=5, le=120)
    coding_enabled: bool = False


class IngestPathBody(TaskBody):
    """Tauri 的文件对话框返回真实路径，无需上传文件本体。"""

    path: str = Field(min_length=1)


class IngestJobTextBody(TaskBody):
    raw: str = Field(min_length=1)


class SynthesizeJobBody(TaskBody):
    title: str = Field(min_length=1, max_length=120)
    tier: CompanyTier
    level: JobLevel
    extra: str = ""


class DiagnoseBody(TaskBody):
    resume_id: int
    job_id: int
    refresh: bool = False


class GenerateReviewBody(BaseModel):
    session_id: int


class SetMasteredBody(BaseModel):
    mistake_id: int
    mastered: bool


class UniqueNameBody(BaseModel):
    base: str = Field(min_length=1, max_length=60)


class ApiKeyBody(BaseModel):
    provider_key: str = Field(min_length=1, max_length=60)
    api_key: str


class ProbeBody(BaseModel):
    """探测某个供应商的密钥与模型是否真的能用。

    密钥留空则用已保存的那份，这样用户不必为了测试重新粘一遍。
    """

    provider_key: str = Field(min_length=1, max_length=60)
    model: str = Field(default="", max_length=120)
    api_key: str = ""
    realtime: bool = False


class ProbeOutcome(BaseModel):
    ok: bool
    detail: str
    latency_ms: int = 0


class ModelOption(BaseModel):
    value: str
    label: str


class ProviderOption(BaseModel):
    key: str
    label: str
    credential_key: str
    console_url: str
    default_model: str
    models: list[str]
    voices: list[ModelOption] = Field(default_factory=list)


class RoleOption(BaseModel):
    key: str
    label: str


class Catalog(BaseModel):
    """供应商目录。前端据此渲染下拉，不必把这些常量抄一遍。"""

    chat: list[ProviderOption]
    realtime: list[ProviderOption]
    roles: list[RoleOption]


class AudioDeviceOption(BaseModel):
    name: str
    index: int


class AudioDevices(BaseModel):
    inputs: list[AudioDeviceOption]
    outputs: list[AudioDeviceOption]


class MistakeCounts(BaseModel):
    pending: int
    mastered: int


class StopResult(BaseModel):
    """不回传完整 InterviewState，前端要的只是收尾去哪。"""

    session_id: int | None = None
    reviewable: bool = False
    elapsed_ms: int = 0


class Ok(BaseModel):
    ok: bool = True


class ServerInfo(BaseModel):
    name: str
    version: str
    event_names: list[str]
    subscribers: int
