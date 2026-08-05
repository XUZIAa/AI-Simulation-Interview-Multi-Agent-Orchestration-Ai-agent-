from __future__ import annotations

import re
import types
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, model_validator

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def as_text(value: Any, *, sep: str = " · ") -> str:
    """把模型给出的任意形态压成一行文本。

    同一个字段，模型可能给字符串、对象、也可能给对象列表
    （教育经历尤其常见），schema 声明得再准也拦不住。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return ""
    if isinstance(value, int | float):
        return f"{value:g}"
    if isinstance(value, dict):
        # 跳过嵌套容器，避免把课程清单之类整段拼进来
        parts = [as_text(v) for v in value.values() if not isinstance(v, dict | list | tuple)]
        return sep.join(p for p in parts if p)
    if isinstance(value, list | tuple):
        parts = [as_text(v, sep=sep) for v in value]
        return "；".join(p for p in parts if p)
    return str(value).strip()


def as_text_list(value: Any) -> list[str]:
    """把任意形态压成字符串列表，去空但保持顺序。"""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, dict):
        text = as_text(value)
        return [text] if text else []
    if isinstance(value, list | tuple):
        out: list[str] = []
        for item in value:
            text = as_text(item)
            if text:
                out.append(text)
        return out
    text = as_text(value)
    return [text] if text else []


def as_number(value: Any) -> float:
    """从任意形态里取出数字，"3 年经验" 这类也能拿到 3。"""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        match = _NUMBER.search(value)
        return float(match.group()) if match else 0.0
    if isinstance(value, list | tuple):
        for item in value:
            found = as_number(item)
            if found:
                return found
    return 0.0


def as_object_list(value: Any) -> list[dict[str, Any]]:
    """把任意形态归一成对象列表，字符串元素折成 {"name": ...}。"""
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        text = value.strip()
        return [{"name": text}] if text else []
    if isinstance(value, list | tuple):
        out: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                out.append(item)
            else:
                text = as_text(item)
                if text:
                    out.append({"name": text})
        return out
    return []


class LooseModel(BaseModel):
    """接受模型输出形态差异的 schema 基类。

    LLM 对同一字段可能给字符串、对象或对象列表，键名也常换
    （skill 写成 requirement）。子类只声明字段类型即可，
    这里按注解自动归一化；键名差异用 Field(validation_alias=...) 兼容。
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for name, field in cls.model_fields.items():
            keys = [name, *_alias_keys(field)]
            key = next((k for k in keys if k in out), None)
            if key is None:
                continue
            out[key] = _coerce_value(field.annotation, out[key])
        return out


def _alias_keys(field: Any) -> list[str]:
    alias = getattr(field, "validation_alias", None)
    if alias is None:
        return []
    if isinstance(alias, str):
        return [alias]
    choices = getattr(alias, "choices", None)
    return [c for c in choices if isinstance(c, str)] if choices else []


def _coerce_value(annotation: Any, value: Any) -> Any:
    origin = get_origin(annotation)
    if origin in (types.UnionType, Union):
        args = get_args(annotation)
        # 可选字段的 null 必须保持原样：把它变成 0 会被当成真选了 id=0
        if value is None and type(None) in args:
            return None
        inner = [a for a in args if a is not type(None)]
        return _coerce_value(inner[0], value) if len(inner) == 1 else value
    if annotation is bool:
        return value
    if annotation is str:
        return as_text(value)
    if annotation is int:
        return int(as_number(value))
    if annotation is float:
        return as_number(value)
    if origin in (list, tuple):
        args = get_args(annotation)
        inner = args[0] if args else None
        if inner is str:
            return as_text_list(value)
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            return as_object_list(value)
        return value
    return value
