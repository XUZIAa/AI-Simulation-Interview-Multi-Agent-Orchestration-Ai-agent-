from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..core.errors import ProviderError, ProviderResponseError

logger = logging.getLogger(__name__)

Role = Literal["system", "user", "assistant"]
T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


@dataclass(slots=True)
class ChatMessage:
    role: Role
    content: str

    def as_payload(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


def system(content: str) -> ChatMessage:
    return ChatMessage("system", content)


def user(content: str) -> ChatMessage:
    return ChatMessage("user", content)


def assistant(content: str) -> ChatMessage:
    return ChatMessage("assistant", content)


def extract_json(text: str) -> Any:
    """模型经常给带围栏或带前后缀的 JSON，这里做一次强解析。"""
    raw = text.strip()
    match = _FENCE.search(raw)
    if match:
        raw = match.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = min((i for i in (raw.find("{"), raw.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ProviderResponseError(f"响应中没有 JSON: {text[:200]}")
    for end in range(len(raw), start, -1):
        chunk = raw[start:end]
        if chunk[-1] not in "}]":
            continue
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            continue
    raise ProviderResponseError(f"JSON 解析失败: {text[:200]}")


class ChatClient:
    """OpenAI 兼容协议客户端。国内主流平台均遵循该协议，换模型只换 base_url + model。"""

    def __init__(
        self,
        *,
        provider_key: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
    ) -> None:
        self.provider_key = provider_key
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout, connect=10.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _payload(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        stream: bool,
        model: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": [m.as_payload() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.6,
        max_tokens: int = 2048,
        json_mode: bool = False,
        model: str | None = None,
    ) -> str:
        payload = self._payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            stream=False,
            model=model,
        )
        try:
            response = await self._client.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(str(exc), provider=self.provider_key) from exc
        if response.status_code >= 400:
            raise ProviderError(
                response.text[:500], status=response.status_code, provider=self.provider_key
            )
        try:
            data = response.json()
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ProviderResponseError(response.text[:500], provider=self.provider_key) from exc

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.6,
        max_tokens: int = 2048,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        payload = self._payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=False,
            stream=True,
            model=model,
        )
        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise ProviderError(
                        body.decode("utf-8", "ignore")[:500],
                        status=response.status_code,
                        provider=self.provider_key,
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if not chunk or chunk == "[DONE]":
                        continue
                    try:
                        delta = json.loads(chunk)["choices"][0].get("delta", {})
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    piece = delta.get("content")
                    if piece:
                        yield piece
        except httpx.HTTPError as exc:
            raise ProviderError(str(exc), provider=self.provider_key) from exc

    async def structured(
        self,
        messages: Sequence[ChatMessage],
        schema: type[T],
        *,
        temperature: float = 0.3,
        max_tokens: int = 3072,
        retries: int = 1,
    ) -> T:
        """要求模型按 schema 输出。解析失败会带着错误信息重问一次。"""
        convo = list(messages)
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            text = await self.complete(
                convo, temperature=temperature, max_tokens=max_tokens, json_mode=True
            )
            try:
                return schema.model_validate(extract_json(text))
            except (ProviderResponseError, ValidationError) as exc:
                last_error = exc
                logger.warning("结构化输出解析失败(第 %d 次): %s", attempt + 1, str(exc)[:300])
                if attempt >= retries:
                    break
                convo = [
                    *messages,
                    assistant(text[:2000]),
                    user(
                        "上面的输出不符合要求，解析报错：\n"
                        f"{str(exc)[:600]}\n"
                        "请只输出一个合法 JSON 对象，不要任何解释文字和代码围栏。"
                    ),
                ]
        raise ProviderResponseError(str(last_error), provider=self.provider_key)


def schema_hint(schema: type[BaseModel]) -> str:
    """把 pydantic schema 压成提示词里的字段说明。"""
    return json.dumps(schema.model_json_schema(), ensure_ascii=False, separators=(",", ":"))
