from __future__ import annotations

import json
import logging
import threading
from typing import Any

import keyring
from keyring.errors import KeyringError, PasswordDeleteError
from pydantic import BaseModel, Field, ValidationError, field_validator

from .errors import ConfigError, CredentialMissingError
from .paths import data_root
from .providers_catalog import (
    CHAT_PROVIDERS,
    DEFAULT_ROLE_BINDINGS,
    REALTIME_PROVIDERS,
    ChatProvider,
    CustomEndpoint,
    RealtimeProvider,
    RoleBinding,
)

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "Interviewer.AI"
CONFIG_FILE = data_root() / "config.json"


class AudioSettings(BaseModel):
    input_device: str = ""
    output_device: str = ""
    input_gain: float = Field(default=1.0, ge=0.2, le=4.0)
    # 阈值偏高会导致服务端听不到说话；宁可略灵敏，配合语义打断过滤附和声
    vad_threshold: float = Field(default=0.28, ge=0.05, le=0.95)
    silence_duration_ms: int = Field(default=620, ge=200, le=2000)
    prefix_padding_ms: int = Field(default=300, ge=0, le=1000)
    semantic_vad: bool = True
    auto_gain: bool = True
    # 上次学到的自动增益。同一台机器的麦克风增益需求稳定，记下来省去下次爬坡。
    # 这是运行时学习值，历史值越界只能钳制、绝不能让整份配置验证失败
    learned_gain: float = 1.0

    @field_validator("learned_gain", mode="before")
    @classmethod
    def _clamp_learned_gain(cls, value: Any) -> float:
        try:
            return min(8.0, max(0.5, float(value)))
        except (TypeError, ValueError):
            return 1.0
    # 起播蓄水水位。太小会断续，太大则短回复会卡在缓冲里等，听感像前半句丢了
    playback_buffer_ms: int = Field(default=240, ge=60, le=900)


class RealtimeSettings(BaseModel):
    provider: str = "qwen_omni"
    model: str = ""
    voice: str = ""
    temperature: float = Field(default=0.85, ge=0.1, le=1.5)

    def catalog(self) -> RealtimeProvider:
        try:
            return REALTIME_PROVIDERS[self.provider]
        except KeyError as exc:
            raise ConfigError(f"未知的实时语音供应商: {self.provider}") from exc

    def resolved_model(self) -> str:
        return self.model or self.catalog().default_model

    def resolved_voice(self) -> str:
        return self.voice or self.catalog().default_voice


class OrchestrationSettings(BaseModel):
    reanchor_every_turns: int = Field(default=4, ge=1, le=20)
    max_follow_up_depth: int = Field(default=3, ge=1, le=6)
    director_timeout_ms: int = Field(default=9000, ge=2000, le=30000)
    guard_timeout_ms: int = Field(default=2500, ge=800, le=10000)
    interrupt_budget_per_phase: int = Field(default=2, ge=0, le=10)
    verbose_seconds_before_interrupt: float = Field(default=42.0, ge=10.0, le=180.0)
    # 候选人停止说话后等多久算一个回合结束
    turn_gap_ms: int = Field(default=850, ge=300, le=3000)
    planned_minutes: int = Field(default=30, ge=10, le=45)


class FeatureSettings(BaseModel):
    camera_enabled: bool = True
    copilot_enabled: bool = True
    coding_round_enabled: bool = False
    save_audio: bool = True


class AppSettings(BaseModel):
    roles: dict[str, RoleBinding] = Field(default_factory=lambda: dict(DEFAULT_ROLE_BINDINGS))
    realtime: RealtimeSettings = Field(default_factory=RealtimeSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    orchestration: OrchestrationSettings = Field(default_factory=OrchestrationSettings)
    features: FeatureSettings = Field(default_factory=FeatureSettings)
    custom_chat: CustomEndpoint = Field(default_factory=CustomEndpoint)
    active_profile_name: str = "我"

    def binding_for(self, role: str) -> RoleBinding:
        binding = self.roles.get(role) or DEFAULT_ROLE_BINDINGS.get(role)
        if binding is None:
            raise ConfigError(f"未知的模型角色: {role}")
        return binding

    def chat_catalog(self, role: str) -> ChatProvider:
        binding = self.binding_for(role)
        try:
            catalog = CHAT_PROVIDERS[binding.provider]
        except KeyError as exc:
            raise ConfigError(f"未知的模型供应商: {binding.provider}") from exc
        if binding.provider == "custom":
            return catalog.model_copy(
                update={
                    "base_url": self.custom_chat.base_url or catalog.base_url,
                    "models": tuple(self.custom_chat.models),
                }
            )
        return catalog

    def chat_model(self, role: str) -> str:
        return self.binding_for(role).model or self.chat_catalog(role).default_model


class ConfigStore:
    """配置读写的唯一入口。明文配置落 JSON，密钥进系统凭据库。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._settings = self._load()

    @property
    def settings(self) -> AppSettings:
        return self._settings

    def _load(self) -> AppSettings:
        """配置读不出来绝不能挡住启动：坏文件挪去 .broken 备份，回到默认值继续跑。"""
        if not CONFIG_FILE.exists():
            return AppSettings()
        try:
            raw: dict[str, Any] = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return AppSettings.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            logger.warning("配置文件不可用，已回退默认值: %s", exc)
            self._quarantine()
            return AppSettings()

    @staticmethod
    def _quarantine() -> None:
        backup = CONFIG_FILE.with_suffix(".json.broken")
        try:
            backup.unlink(missing_ok=True)
            CONFIG_FILE.replace(backup)
        except OSError:
            logger.warning("无法备份损坏的配置文件: %s", CONFIG_FILE)

    def save(self, settings: AppSettings | None = None) -> None:
        with self._lock:
            if settings is not None:
                self._settings = settings
            payload = self._settings.model_dump(mode="json")
            tmp = CONFIG_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(CONFIG_FILE)

    def update(self, **changes: Any) -> AppSettings:
        with self._lock:
            merged = self._settings.model_copy(update=changes)
            self.save(merged)
            return merged

    def set_api_key(self, provider_key: str, api_key: str) -> None:
        try:
            if api_key:
                keyring.set_password(KEYRING_SERVICE, provider_key, api_key)
            else:
                keyring.delete_password(KEYRING_SERVICE, provider_key)
        except PasswordDeleteError:
            return
        except KeyringError as exc:
            raise ConfigError("系统凭据库不可用，无法保存 API Key") from exc

    def get_api_key(self, provider_key: str) -> str:
        try:
            return keyring.get_password(KEYRING_SERVICE, provider_key) or ""
        except KeyringError as exc:
            raise ConfigError("系统凭据库不可用，无法读取 API Key") from exc

    def require_api_key(self, provider_key: str) -> str:
        key = self.get_api_key(provider_key)
        if not key:
            label = CHAT_PROVIDERS.get(provider_key) or REALTIME_PROVIDERS.get(provider_key)
            name = label.label if label else provider_key
            raise CredentialMissingError(user_message=f"「{name}」尚未配置 API Key，请前往设置填写")
        return key

    def configured_providers(self) -> set[str]:
        keys = set(CHAT_PROVIDERS) | set(REALTIME_PROVIDERS)
        return {k for k in keys if self.get_api_key(k)}


_store: ConfigStore | None = None


def config_store() -> ConfigStore:
    global _store
    if _store is None:
        _store = ConfigStore()
    return _store


def settings() -> AppSettings:
    return config_store().settings
