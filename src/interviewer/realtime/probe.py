from __future__ import annotations

import json
import time
from urllib.parse import urlencode

import websockets
from websockets.asyncio.client import connect

from ..core.providers_catalog import RealtimeProvider
from ..llm.base import ProbeResult

_HANDSHAKE_TIMEOUT = 15.0


async def probe_realtime(
    *,
    provider: RealtimeProvider,
    api_key: str,
    model: str,
) -> ProbeResult:
    """只做握手探测：连上并等 session.created，不开麦克风、不发音频。

    能区分「Key 无效」和「账号没开通该实时模型」——后者在 omni 系列上很常见。
    """
    if not api_key.strip():
        return ProbeResult(False, "还没填 API Key")
    if not model.strip():
        return ProbeResult(False, "还没选实时语音模型")

    url = f"{provider.ws_url}?{urlencode({'model': model.strip()})}"
    started = time.perf_counter()
    try:
        async with connect(
            url,
            additional_headers={"Authorization": f"Bearer {api_key.strip()}"},
            open_timeout=_HANDSHAKE_TIMEOUT,
            close_timeout=3,
        ) as ws:
            raw = await ws.recv()
            cost = int((time.perf_counter() - started) * 1000)
            event = json.loads(raw) if isinstance(raw, str) else {}
            kind = event.get("type", "")
            if kind == "session.created":
                return ProbeResult(True, f"实时语音可用，握手 {cost} ms", cost)
            if kind == "error":
                detail = (event.get("error") or {}).get("message") or "服务端返回错误"
                return ProbeResult(False, f"握手被拒：{detail[:120]}")
            return ProbeResult(True, f"已连通（首帧 {kind or '未知'}），握手 {cost} ms", cost)
    except websockets.exceptions.InvalidStatus as exc:
        code = exc.response.status_code
        if code in (401, 403):
            return ProbeResult(False, "API Key 无效，或账号未开通该实时语音模型")
        if code == 404:
            return ProbeResult(False, f"实时模型不存在：{model}")
        if code == 429:
            return ProbeResult(False, "请求过于频繁，或额度已用尽")
        return ProbeResult(False, f"握手失败 HTTP {code}")
    except TimeoutError:
        return ProbeResult(False, "握手超时，检查网络或代理")
    except (OSError, websockets.exceptions.WebSocketException) as exc:
        return ProbeResult(False, f"连不上实时语音服务：{str(exc)[:120]}")
    except Exception as exc:
        return ProbeResult(False, f"{exc.__class__.__name__}: {str(exc)[:120]}")
