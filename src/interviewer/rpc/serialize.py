from __future__ import annotations

import dataclasses
import enum
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_PRIMITIVES = (str, int, float, bool, type(None))


def to_json(value: Any) -> Any:
    """把后端对象转成可 JSON 化的结构。

    不能用 dataclasses.asdict：仓储层的 dataclass 都嵌套了 pydantic 模型
    （StoredResume.profile、StoredMistake.item 等），asdict 会把它们当普通
    对象递归，产出 datetime、Enum 这类 json 无法直接编码的值。
    """
    # 枚举必须先判：StrEnum 同时是 str，落到下面的原始类型分支就会原样返回
    # 枚举实例本身。StrEnum 侥幸能被 json 正确编码，换成别的基类就是错值。
    if isinstance(value, enum.Enum):
        return to_json(value.value)
    if isinstance(value, _PRIMITIVES):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_json(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        # 枚举做键时必须落成字符串，否则 json 编码直接失败
        return {_key(k): to_json(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_json(v) for v in value]
    if isinstance(value, bytes):
        raise TypeError("二进制不走 JSON 通道，音频与文件应使用专用路径")
    raise TypeError(f"无法序列化的类型: {type(value)!r}")


def _key(key: Any) -> str:
    if isinstance(key, enum.Enum):
        return str(key.value)
    return str(key)
