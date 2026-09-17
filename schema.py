from __future__ import annotations

import json
import re
from typing import Any

WEBAPP_ID_RE = re.compile(r"(\d{10,})")
PATH_ID_RE = re.compile(
    r"(?:ai-detail|workflow|ai-app|quick-ai-app|app)/(\d{10,})",
    re.IGNORECASE,
)

TYPE_TOKENS = {
    "STRING",
    "TEXT",
    "INT",
    "INTEGER",
    "FLOAT",
    "NUMBER",
    "BOOLEAN",
    "BOOL",
    "LIST",
    "IMAGE",
    "AUDIO",
    "VIDEO",
    "FILE",
    "ZIP",
}

FILE_TYPES = {"IMAGE", "AUDIO", "VIDEO", "FILE", "ZIP"}
HIDDEN_FIELD_NAMES = {"seed", "control_after_generate", "noise_seed"}


class SchemaError(ValueError):
    pass


def extract_webapp_id(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise SchemaError("请输入 webappId 或 RunningHub 链接")
    path_match = PATH_ID_RE.search(text)
    if path_match:
        return path_match.group(1)
    id_match = WEBAPP_ID_RE.search(text)
    if not id_match:
        raise SchemaError(f"无法从输入中解析 webappId：{text}")
    return id_match.group(1)


def _as_json(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
    return value


def _option(value: str, label: str | None = None, description: str = "") -> dict[str, str]:
    return {
        "value": str(value),
        "label": str(label or value),
        "description": description or "",
    }


def _normalize_options(items: list[Any]) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for item in items:
        if item in (None, "", "keep_this_dic"):
            continue
        if isinstance(item, dict):
            if "index" in item or "name" in item:
                value = item.get("index") or item.get("name")
                label = item.get("name") or item.get("index")
                options.append(_option(str(value), str(label), str(item.get("description") or "")))
            continue
        options.append(_option(str(item)))
    return options


def parse_field_data(field_data: Any) -> dict[str, Any]:
    raw = field_data
    parsed = _as_json(field_data)
    extra: dict[str, Any] = {}
    options: list[dict[str, str]] = []

    if parsed is None:
        return {"options": [], "extra": {}, "raw": raw}

    if isinstance(parsed, dict):
        return {"options": [], "extra": parsed, "raw": raw}

    if isinstance(parsed, str):
        parts = [part.strip() for part in parsed.split(",") if part.strip()]
        return {"options": [_option(part) for part in parts], "extra": {}, "raw": raw}

    if not isinstance(parsed, list):
        return {"options": [_option(str(parsed))], "extra": {}, "raw": raw}

    if parsed and isinstance(parsed[0], str) and parsed[0].upper() in TYPE_TOKENS:
        for item in parsed[1:]:
            if isinstance(item, dict):
                extra.update(item)
        return {"options": [], "extra": extra, "raw": raw}

    if parsed and isinstance(parsed[0], list):
        options = _normalize_options(parsed[0])
        for item in parsed[1:]:
            if isinstance(item, dict):
                extra.update(item)
        return {"options": options, "extra": extra, "raw": raw}

    options = _normalize_options(parsed)
    return {"options": options, "extra": extra, "raw": raw}


def widget_for(field_type: str, extra: dict[str, Any] | None = None) -> str:
    kind = (field_type or "STRING").upper()
    extra = extra or {}
    if kind in FILE_TYPES:
        return "file"
    if kind == "LIST":
        return "select"
    if kind in {"INT", "INTEGER", "NUMBER", "FLOAT"}:
        return "number"
    if kind in {"BOOLEAN", "BOOL"}:
        return "checkbox"
    if extra.get("multiline") or kind in {"STRING", "TEXT"}:
        return "textarea"
    return "text"


def default_hidden(field_name: str) -> bool:
    return (field_name or "").lower() in HIDDEN_FIELD_NAMES


def default_required(field_type: str) -> bool:
    return (field_type or "").upper() in FILE_TYPES


def field_key(node_id: Any, field_name: str) -> str:
    return f"{node_id}::{field_name}"


def normalize_node(node: dict[str, Any], sort_order: int = 0) -> dict[str, Any]:
    field_type = str(node.get("fieldType") or "STRING").upper()
    field_name = str(node.get("fieldName") or "")
    parsed = parse_field_data(node.get("fieldData"))
    extra = parsed.get("extra") or {}
    return {
        "node_id": str(node.get("nodeId") or ""),
        "node_name": str(node.get("nodeName") or ""),
        "field_name": field_name,
        "field_type": field_type,
        "field_value": "" if node.get("fieldValue") is None else str(node.get("fieldValue")),
        "field_data": stringify_field_data(node.get("fieldData")),
        "description": str(node.get("description") or ""),
        "description_en": str(node.get("descriptionEn") or ""),
        "display_label": str(node.get("description") or field_name),
        "hidden": 1 if default_hidden(field_name) else 0,
        "required": 1 if default_required(field_type) else 0,
        "sort_order": sort_order,
        "widget": widget_for(field_type, extra),
        "options": parsed.get("options") or [],
        "extra": extra,
        "accept": accept_for(field_type),
    }


def accept_for(field_type: str) -> str:
    kind = (field_type or "").upper()
    return {
        "IMAGE": "image/*",
        "AUDIO": "audio/*",
        "VIDEO": "video/*",
        "ZIP": ".zip,application/zip",
        "FILE": "*/*",
    }.get(kind, "")


def cover_from_schema(data: dict[str, Any]) -> str:
    cover = data.get("coverUrl") or data.get("cover") or ""
    if cover:
        return str(cover)
    covers = data.get("covers") or []
    if covers and isinstance(covers[0], dict):
        return str(covers[0].get("url") or covers[0].get("thumbnailUrl") or "")
    return ""


def app_name_from_schema(data: dict[str, Any], fallback: str) -> str:
    return str(data.get("webappName") or data.get("appName") or fallback)


def stringify_field_data(field_data: Any) -> str:
    if field_data is None:
        return ""
    if isinstance(field_data, str):
        return field_data
    return json.dumps(field_data, ensure_ascii=False)


def build_submit_nodes(fields: list[dict[str, Any]], values: dict[str, Any]) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    missing: list[str] = []
    for field in fields:
        key = field_key(field["node_id"], field["field_name"])
        if field.get("hidden"):
            value = field.get("field_value")
        else:
            value = values.get(key, field.get("field_value"))
        if value is None:
            value = ""
        if isinstance(value, bool):
            value = "true" if value else "false"
        else:
            value = str(value).strip()
        if not value:
            if field.get("required") and not field.get("hidden"):
                missing.append(field.get("display_label") or field.get("field_name") or key)
            continue
        payload.append(
            {
                "nodeId": str(field["node_id"]),
                "fieldName": str(field["field_name"]),
                "fieldValue": value,
            }
        )
    if missing:
        raise SchemaError("请填写必填参数：" + "、".join(missing))
    return payload
