from __future__ import annotations


class InterviewerError(Exception):
    """应用内所有异常的根，便于 UI 层统一拦截展示。"""

    user_message: str = "发生未知错误"

    def __init__(self, detail: str = "", *, user_message: str | None = None) -> None:
        self.detail = detail
        if user_message:
            self.user_message = user_message
        super().__init__(detail or self.user_message)


class ConfigError(InterviewerError):
    user_message = "配置不完整或不合法"


class CredentialMissingError(ConfigError):
    user_message = "尚未配置 API Key，请前往「设置」填写"


class ProviderError(InterviewerError):
    user_message = "模型服务调用失败"

    def __init__(self, detail: str = "", *, status: int | None = None, provider: str = "") -> None:
        self.status = status
        self.provider = provider
        super().__init__(detail)


class ProviderResponseError(ProviderError):
    user_message = "模型返回内容无法解析"


class RealtimeError(InterviewerError):
    user_message = "实时语音链路异常"


class RealtimeClosedError(RealtimeError):
    user_message = "实时语音连接已断开"


class AudioDeviceError(InterviewerError):
    user_message = "音频设备不可用，请检查麦克风与扬声器"


class ResumeParseError(InterviewerError):
    user_message = "简历解析失败，请确认文件格式为 PDF / DOCX / TXT"


class StateTransitionError(InterviewerError):
    user_message = "当前阶段不允许该操作"


class InterviewBusyError(InterviewerError):
    user_message = "已有面试正在进行，请先结束当前面试再开始新的一场"
