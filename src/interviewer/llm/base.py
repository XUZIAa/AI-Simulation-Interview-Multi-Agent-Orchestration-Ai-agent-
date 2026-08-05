from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..core.errors import ProviderError, ProviderResponseError
from ..core.providers_catalog import model_traits

logger = logging.getLogger(__name__)

Role = Literal["system", "user", "assistant"]
T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

# 结构化输出的配额下限。给太小会出现 HTTP 200 但正文为空，或 JSON 被截断在半路
_MIN_STRUCTURED_TOKENS = 1024


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
        name = model or self.model
        traits = model_traits(name)
        # 推理模型的思维链占用同一份输出配额；结构化输出另有下限，防止 JSON 被截断
        floor = traits.min_output_tokens
        if json_mode:
            floor = max(floor, _MIN_STRUCTURED_TOKENS)
        payload: dict[str, Any] = {
            "model": name,
            "messages": [m.as_payload() for m in messages],
            "max_tokens": max(max_tokens, floor),
            "stream": stream,
        }
        if traits.tunable_sampling:
            payload["temperature"] = temperature
        if json_mode and traits.json_object:
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
            choice = data["choices"][0]
            message = choice.get("message") or {}
            content = message.get("content") or ""
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ProviderResponseError(response.text[:500], provider=self.provider_key) from exc
        if not content.strip():
            self._raise_empty(choice, message)
        return content

    def _raise_empty(self, choice: dict[str, Any], message: dict[str, Any]) -> None:
        """空正文要说清到底为什么空，否则用户只看到「无法解析」无从下手。"""
        thinking = (message.get("reasoning_content") or "").strip()
        finish = choice.get("finish_reason") or ""
        if thinking or finish == "length":
            raise ProviderResponseError(
                f"模型「{self.model}」只输出了思维链就用尽了配额，正文为空。"
                "推理模型的思维链与正文共享 max_tokens，请改用非推理模型（如 deepseek-chat）",
                provider=self.provider_key,
            )
        raise ProviderResponseError(
            f"模型「{self.model}」返回了空内容（finish_reason={finish or '未知'}）",
            provider=self.provider_key,
        )

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
        if not model_traits(self.model).json_object:
            # 没有 response_format 强约束时，用提示词把格式要求兜住
            convo.append(user("只输出一个合法 JSON 对象，不要任何解释文字，不要代码围栏。"))
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
                    *convo,
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


@dataclass(slots=True)
class ProbeResult:
    ok: bool
    detail: str
    latency_ms: int = 0


_STATUS_HINT: dict[int, str] = {
    400: "请求被拒绝，通常是模型名不被该平台接受",
    401: "API Key 无效或已失效",
    402: "账户余额不足",
    403: "该 Key 没有此模型的访问权限，可能需要先开通",
    404: "模型不存在，或接口地址不对",
    429: "请求过于频繁，或额度已用尽",
}


async def probe_chat(
    *,
    provider_key: str,
    base_url: str,
    api_key: str,
    model: str,
    timeout: float = 20.0,
) -> ProbeResult:
    """用一次最小请求探测 Key 与模型能否真正跑通。

    把 HTTP 状态码翻译成人话，让用户能分清是 Key 的问题还是别的问题。
    """
    if not api_key.strip():
        return ProbeResult(False, "还没填 API Key")
    if not model.strip():
        return ProbeResult(False, "还没选模型")

    client = ChatClient(
        provider_key=provider_key,
        base_url=base_url,
        api_key=api_key.strip(),
        model=model.strip(),
        timeout=timeout,
    )
    started = time.perf_counter()
    try:
        await client.complete([user("hi")], max_tokens=8, temperature=0.0)
        cost = int((time.perf_counter() - started) * 1000)
        return ProbeResult(True, f"连通正常，往返 {cost} ms", cost)
    except ProviderError as exc:
        body = (exc.detail or "").strip().replace("\n", " ")
        if exc.status is None:
            tail = f"：{body[:110]}" if body else ""
            return ProbeResult(False, f"连不上服务器，检查网络或代理{tail}")
        hint = _STATUS_HINT.get(exc.status)
        if hint is None:
            hint = (
                f"服务端错误 {exc.status}，稍后再试"
                if exc.status >= 500
                else f"请求失败 {exc.status}"
            )
        # 400/404 要带上服务端原话，否则不知道到底哪里不对
        if exc.status in (400, 404) and body:
            return ProbeResult(False, f"{hint}｜{body[:110]}")
        return ProbeResult(False, hint)
    except Exception as exc:  # 探测不该把异常抛给 UI
        return ProbeResult(False, f"{exc.__class__.__name__}: {str(exc)[:120]}")
    finally:
        await client.aclose()
