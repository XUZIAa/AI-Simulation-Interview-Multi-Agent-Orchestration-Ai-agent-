from __future__ import annotations

from typing import Any, Final

# ---- 客户端发出的事件 ----
SESSION_UPDATE: Final = "session.update"
AUDIO_APPEND: Final = "input_audio_buffer.append"
AUDIO_COMMIT: Final = "input_audio_buffer.commit"
AUDIO_CLEAR: Final = "input_audio_buffer.clear"
ITEM_CREATE: Final = "conversation.item.create"
RESPONSE_CREATE: Final = "response.create"
RESPONSE_CANCEL: Final = "response.cancel"

# ---- 服务端推送的事件 ----
SESSION_CREATED: Final = "session.created"
SESSION_UPDATED: Final = "session.updated"
SPEECH_STARTED: Final = "input_audio_buffer.speech_started"
SPEECH_STOPPED: Final = "input_audio_buffer.speech_stopped"
AUDIO_COMMITTED: Final = "input_audio_buffer.committed"
INPUT_TRANSCRIPT_DELTA: Final = "conversation.item.input_audio_transcription.delta"
INPUT_TRANSCRIPT_DONE: Final = "conversation.item.input_audio_transcription.completed"
INPUT_TRANSCRIPT_FAILED: Final = "conversation.item.input_audio_transcription.failed"
RESPONSE_CREATED: Final = "response.created"
RESPONSE_OUTPUT_ITEM_ADDED: Final = "response.output_item.added"
RESPONSE_AUDIO_DELTA: Final = "response.audio.delta"
RESPONSE_AUDIO_DONE: Final = "response.audio.done"
RESPONSE_TRANSCRIPT_DELTA: Final = "response.audio_transcript.delta"
RESPONSE_TRANSCRIPT_DONE: Final = "response.audio_transcript.done"
RESPONSE_TEXT_DELTA: Final = "response.text.delta"
RESPONSE_TEXT_DONE: Final = "response.text.done"
RESPONSE_DONE: Final = "response.done"
RATE_LIMITS: Final = "rate_limits.updated"
ERROR: Final = "error"


def session_update(
    *,
    instructions: str,
    voice: str,
    audio_format: str,
    temperature: float,
    semantic_vad: bool,
    vad_threshold: float,
    silence_duration_ms: int,
    prefix_padding_ms: int,
    # 音频输出的 token 消耗远高于纯文本，上限给紧了会让面试官说半句就被掐掉
    max_output_tokens: int = 4096,
) -> dict[str, Any]:
    """会话配置。instructions 是人格锚点，每次重锚都整体重发。"""
    # create_response=False 是关键：服务端只做断句，发言权由导演授予
    turn_detection: dict[str, Any] = (
        {"type": "semantic_vad", "create_response": False}
        if semantic_vad
        else {
            "type": "server_vad",
            "threshold": vad_threshold,
            "silence_duration_ms": silence_duration_ms,
            "prefix_padding_ms": prefix_padding_ms,
            "create_response": False,
        }
    )
    return {
        "type": SESSION_UPDATE,
        "session": {
            "modalities": ["text", "audio"],
            "voice": voice,
            "instructions": instructions,
            "input_audio_format": audio_format,
            "output_audio_format": audio_format,
            "turn_detection": turn_detection,
            "temperature": temperature,
            "max_response_output_tokens": max_output_tokens,
        },
    }


def audio_append(audio_b64: str) -> dict[str, Any]:
    return {"type": AUDIO_APPEND, "audio": audio_b64}


def system_note(text: str) -> dict[str, Any]:
    """以 user 身份注入的导演指令。realtime 侧无 system 角色的会话项，用带标记的 user 项承载。"""
    return {
        "type": ITEM_CREATE,
        "item": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": text}],
        },
    }


def assistant_note(text: str) -> dict[str, Any]:
    """把面试官已经说过的话补回上下文，用于打断后对齐。"""
    return {
        "type": ITEM_CREATE,
        "item": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def response_create(*, audio: bool = True) -> dict[str, Any]:
    modalities = ["text", "audio"] if audio else ["text"]
    return {"type": RESPONSE_CREATE, "response": {"modalities": modalities}}


def response_cancel() -> dict[str, Any]:
    return {"type": RESPONSE_CANCEL}
