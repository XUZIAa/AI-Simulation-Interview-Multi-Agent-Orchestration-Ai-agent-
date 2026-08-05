from __future__ import annotations

import re
from typing import Any

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
