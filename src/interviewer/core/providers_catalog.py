from __future__ import annotations

import re

from pydantic import BaseModel, Field


class ChatProvider(BaseModel):
    """OpenAI 兼容的文本模型接入点。换模型只改这里的一行。"""

    key: str
    label: str
    base_url: str
    default_model: str
    models: tuple[str, ...]
    console_url: str
    supports_json_object: bool = True


class ModelTraits(BaseModel):
    """模型能力差异。

    同一供应商下不同模型能力可能完全不同（deepseek-chat 与 deepseek-reasoner），
    所以能力必须按模型名判定，不能挂在供应商上。
    """

    reasoning: bool = False
    json_object: bool = True  # 能否可靠使用 response_format=json_object
    min_output_tokens: int = 0  # 输出配额下限
    tunable_sampling: bool = True  # 是否接受 temperature / top_p


# 推理模型的思维链与正文共享输出配额，配额给小了会返回 200 但正文为空；
# 且思考模式下 JSON 常落进思维链字段，response_format 不可靠。
_REASONING_TRAITS = ModelTraits(
    reasoning=True,
    json_object=False,
    min_output_tokens=16384,
    tunable_sampling=False,
)

# r1 / o1 / o3 要按独立片段匹配，避免 model-o1x 这类误判
_REASONING_RE = re.compile(
    r"reasoner|reasoning|thinking|qwq"
    r"|(?:^|[^a-z0-9])r1(?:$|[^a-z0-9])"
    r"|(?:^|[^a-z0-9])o[13](?:$|[^a-z0-9])"
)


def model_traits(model: str) -> ModelTraits:
    if _REASONING_RE.search(model.strip().lower()):
        return _REASONING_TRAITS
    return ModelTraits()


class RealtimeProvider(BaseModel):
    """端到端实时语音接入点，协议为 OpenAI Realtime 事件风格。"""

    key: str
    label: str
    credential_key: str  # 与文本模型共用同一份 API Key 时指向后者
    ws_url: str
    default_model: str
    models: tuple[str, ...]
    voices: tuple[str, ...]
    default_voice: str
    console_url: str
    input_sample_rate: int = 16000
    output_sample_rate: int = 24000
    audio_format: str = "pcm16"
    supports_semantic_vad: bool = True


CHAT_PROVIDERS: dict[str, ChatProvider] = {
    p.key: p
    for p in (
        ChatProvider(
            key="deepseek",
            label="DeepSeek",
            base_url="https://api.deepseek.com/v1",
            default_model="deepseek-chat",
            models=("deepseek-chat", "deepseek-reasoner"),
            console_url="https://platform.deepseek.com/api_keys",
        ),
        ChatProvider(
            key="dashscope",
            label="阿里云百炼 / 通义千问",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            default_model="qwen-plus",
            models=("qwen-plus", "qwen-flash", "qwen-max", "qwen3-max"),
            console_url="https://bailian.console.aliyun.com/?apiKey=1",
        ),
        ChatProvider(
            key="moonshot",
            label="月之暗面 Kimi",
            base_url="https://api.moonshot.cn/v1",
            default_model="kimi-k2-turbo-preview",
            models=("kimi-k2-turbo-preview", "kimi-k2-0905-preview", "moonshot-v1-128k"),
            console_url="https://platform.moonshot.cn/console/api-keys",
        ),
        ChatProvider(
            key="zhipu",
            label="智谱 GLM",
            base_url="https://open.bigmodel.cn/api/paas/v4",
            default_model="glm-4.6",
            models=("glm-4.6", "glm-4.5-air", "glm-4-flash"),
            console_url="https://bigmodel.cn/usercenter/apikeys",
        ),
        ChatProvider(
            key="volcengine",
            label="火山引擎 豆包",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            default_model="doubao-seed-1-6-250615",
            models=("doubao-seed-1-6-250615", "doubao-1-5-pro-32k-250115"),
            console_url="https://console.volcengine.com/ark",
        ),
        ChatProvider(
            key="minimax",
            label="MiniMax",
            base_url="https://api.minimax.chat/v1",
            default_model="MiniMax-M2",
            models=("MiniMax-M2", "abab6.5s-chat"),
            console_url="https://platform.minimaxi.com/user-center/basic-information",
        ),
        ChatProvider(
            key="stepfun",
            label="阶跃星辰 Step",
            base_url="https://api.stepfun.com/v1",
            default_model="step-2-mini",
            models=("step-2-mini", "step-2-16k", "step-1-8k"),
            console_url="https://platform.stepfun.com/interface-key",
        ),
        ChatProvider(
            key="custom",
            label="自定义 OpenAI 兼容端点",
            base_url="http://127.0.0.1:11434/v1",
            default_model="qwen3:14b",
            models=(),
            console_url="",
        ),
    )
}

_QWEN_VOICES: tuple[str, ...] = (
    "Cherry",
    "Serena",
    "Ethan",
    "Chelsie",
    "Nofish",
    "Jennifer",
    "Ryan",
    "Katerina",
    "Elias",
    "Tina",
)

REALTIME_PROVIDERS: dict[str, RealtimeProvider] = {
    p.key: p
    for p in (
        RealtimeProvider(
            key="qwen_omni",
            label="通义千问 Omni Realtime（百炼）",
            credential_key="dashscope",
            ws_url="wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
            default_model="qwen3-omni-flash-realtime",
            models=(
                "qwen3-omni-flash-realtime",
                "qwen3-omni-plus-realtime",
                "qwen-omni-turbo-realtime",
            ),
            voices=_QWEN_VOICES,
            default_voice="Ethan",
            console_url="https://bailian.console.aliyun.com/?apiKey=1",
            output_sample_rate=24000,
            audio_format="pcm",
        ),
        RealtimeProvider(
            key="stepaudio",
            label="阶跃星辰 StepAudio Realtime",
            credential_key="stepfun",
            ws_url="wss://api.stepfun.com/v1/realtime",
            default_model="stepaudio-2.5-realtime",
            models=("stepaudio-2.5-realtime",),
            voices=("linjiajiejie", "jilingshaonv", "wenrounanyou", "zhengjingnansheng"),
            default_voice="zhengjingnansheng",
            console_url="https://platform.stepfun.com/interface-key",
            output_sample_rate=24000,
        ),
    )
}

VOICE_LABELS: dict[str, str] = {
    "Cherry": "Cherry · 女声 明亮",
    "Serena": "Serena · 女声 沉稳",
    "Ethan": "Ethan · 男声 干练",
    "Chelsie": "Chelsie · 女声 温和",
    "Nofish": "Nofish · 男声 低沉",
    "Jennifer": "Jennifer · 女声 外企腔",
    "Ryan": "Ryan · 男声 强势",
    "Katerina": "Katerina · 女声 冷峻",
    "Elias": "Elias · 男声 儒雅",
    "Tina": "Tina · 女声 轻快",
    "linjiajiejie": "邻家姐姐 · 女声 亲和",
    "jilingshaonv": "机灵少女 · 女声 活泼",
    "wenrounanyou": "温柔男友 · 男声 温和",
    "zhengjingnansheng": "正经男声 · 男声 严肃",
}


class RoleBinding(BaseModel):
    """三类文本角色各自绑定的模型，允许分别指定以平衡成本与质量。"""

    provider: str
    model: str = ""

    def resolved_model(self) -> str:
        if self.model:
            return self.model
        return CHAT_PROVIDERS[self.provider].default_model


DEFAULT_ROLE_BINDINGS: dict[str, RoleBinding] = {
    "director": RoleBinding(provider="deepseek", model="deepseek-chat"),
    # 分析师全是结构化输出，推理模型在这个位置不可靠：思维链吃掉配额、JSON 常落进思维链字段
    "analyst": RoleBinding(provider="deepseek", model="deepseek-chat"),
    "guard": RoleBinding(provider="dashscope", model="qwen-flash"),
    "assist": RoleBinding(provider="dashscope", model="qwen-flash"),
}

ROLE_LABELS: dict[str, str] = {
    "director": "导演（面试节奏决策 / 代码追问）",
    "analyst": "分析师（简历诊断 / 复盘评分）",
    "guard": "守卫（人格漂移检测）",
    "assist": "助手（STAR 判定 / 实时提词）",
}


class CustomEndpoint(BaseModel):
    """自定义端点的用户填写值，仅在 provider = custom 时生效。"""

    base_url: str = Field(default="")
    models: list[str] = Field(default_factory=list)
