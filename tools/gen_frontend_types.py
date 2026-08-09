"""生成前端类型：接口 schema 与事件载荷。

手写接口定义迟早和后端错位，尤其 InterviewState 有 37 个字段。这里直接从后端
取真相：OpenAPI 交给 openapi-typescript 处理，事件从 dataclass 反射生成。
"""

from __future__ import annotations

import dataclasses
import enum
import inspect
import json
import subprocess
import sys
import typing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from interviewer.app.context import AppContext  # noqa: E402
from interviewer.core import events as ev  # noqa: E402
from interviewer.rpc.hub import event_name  # noqa: E402
from interviewer.rpc.server import create_app  # noqa: E402

OUT_DIR = ROOT / "desktop" / "src" / "lib"
SPEC_PATH = OUT_DIR / "api-spec.json"
SCHEMA_TS = OUT_DIR / "api-schema.d.ts"
EVENTS_TS = OUT_DIR / "event-types.ts"

_TS_PRIMITIVES = {
    "str": "string",
    "int": "number",
    "float": "number",
    "bool": "boolean",
    "NoneType": "null",
}


def tighten_response_models(spec: dict) -> int:
    """把响应模型的字段一律标为必填。

    pydantic 里带默认值的字段在 JSON Schema 中不是 required，生成的 TS 因此
    全是可选，读一个 settings.realtime 都要判空。但 FastAPI 序列化响应时会输出
    全部字段，可选是失真的。请求体不动——那里的可选是真的可选。
    """
    schemas = spec.get("components", {}).get("schemas", {})
    fixed = 0
    for name, schema in schemas.items():
        if name.endswith("Body"):
            continue
        props = schema.get("properties")
        if not props or schema.get("type") != "object":
            continue
        if set(schema.get("required", [])) == set(props):
            continue
        schema["required"] = list(props)
        fixed += 1
    return fixed


def dump_spec() -> tuple[int, int]:
    """取 OpenAPI。用 TestClient 免得为了导出 schema 真去开端口。"""
    app = create_app(AppContext(), "schema-export")
    spec = TestClient(app).get("/openapi.json").json()
    fixed = tighten_response_models(spec)
    SPEC_PATH.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(spec.get("paths", {})), fixed


def ts_type(annotation: typing.Any) -> str:
    if annotation is type(None):
        return "null"
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if origin is typing.Union or str(origin) == "<class 'types.UnionType'>":
        return " | ".join(dict.fromkeys(ts_type(a) for a in args))
    if origin in (list, set, frozenset, tuple):
        inner = ts_type(args[0]) if args else "unknown"
        return f"{inner}[]"
    if origin is dict:
        key = ts_type(args[0]) if args else "string"
        val = ts_type(args[1]) if len(args) > 1 else "unknown"
        # 枚举做键时前端拿到的是字符串字面量联合
        prefix = "" if key == "string" else f"[key in {key}]?"
        return f"{{ {prefix or '[key: string]'}: {val} }}" if prefix else f"Record<string, {val}>"

    if inspect.isclass(annotation):
        if issubclass(annotation, enum.Enum):
            return " | ".join(f'"{m.value}"' for m in annotation)
        if annotation.__name__ in _TS_PRIMITIVES:
            return _TS_PRIMITIVES[annotation.__name__]
        if dataclasses.is_dataclass(annotation) or hasattr(annotation, "model_fields"):
            return annotation.__name__
    name = getattr(annotation, "__name__", str(annotation))
    return _TS_PRIMITIVES.get(name, "unknown")


def gen_events() -> int:
    types = [
        obj
        for obj in vars(ev).values()
        if inspect.isclass(obj)
        and dataclasses.is_dataclass(obj)
        and issubclass(obj, ev.Event)
        and obj is not ev.Event
    ]
    lines = [
        "// 由 tools/gen_frontend_types.py 生成，请勿手改。",
        "// 事件载荷来自后端 core/events.py 的 dataclass 定义。",
        "",
    ]
    for cls in sorted(types, key=lambda c: c.__name__):
        hints = typing.get_type_hints(cls)
        lines.append(f"export interface {cls.__name__} {{")
        for field in dataclasses.fields(cls):
            lines.append(f"  {field.name}: {ts_type(hints.get(field.name, field.type))};")
        lines.append("}")
        lines.append("")

    lines.append("/** 事件名到载荷的映射，供 onEvent 做类型推断。 */")
    lines.append("export interface EventMap {")
    for cls in sorted(types, key=lambda c: c.__name__):
        lines.append(f"  {event_name(cls)}: {cls.__name__};")
    lines.append("  task_progress: TaskProgress;")
    lines.append("}")
    lines.append("")
    lines.append("/** 长任务进度。它不来自事件总线，由接口层按 task_id 回推。 */")
    lines.append("export interface TaskProgress {")
    lines.append("  task_id: string;")
    lines.append("  stage: string;")
    lines.append("  percent: number;")
    lines.append("}")
    lines.append("")
    lines.append("export type EventName = keyof EventMap;")
    lines.append("")

    EVENTS_TS.write_text("\n".join(lines), encoding="utf-8")
    return len(types)


def gen_schema() -> None:
    """交给 openapi-typescript 转换。

    工作目录固定在 desktop 并用相对路径：项目路径含中文，绝对路径传给 npx
    会在编码转换上出错。
    """
    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    rel_spec = SPEC_PATH.relative_to(ROOT / "desktop").as_posix()
    rel_out = SCHEMA_TS.relative_to(ROOT / "desktop").as_posix()
    subprocess.run(
        [npx, "openapi-typescript", rel_spec, "-o", rel_out],
        cwd=ROOT / "desktop",
        check=True,
    )


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths, fixed = dump_spec()
    print(f"接口路径 {paths} 条，收紧 {fixed} 个响应模型 -> {SPEC_PATH.name}")
    count = gen_events()
    print(f"事件类型 {count} 个 -> {EVENTS_TS.name}")
    gen_schema()
    print(f"接口类型 -> {SCHEMA_TS.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
