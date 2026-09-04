#!/usr/bin/env python3
"""MCP stdio proxy for token-authenticated localhost game runtime adapters."""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MCP_PROTOCOL_VERSION = "2025-03-26"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url,
            code,
            "Runtime redirects are not allowed.",
            headers,
            fp,
        )


_RUNTIME_OPENER = urllib.request.build_opener(_NoRedirectHandler())


@dataclass(frozen=True)
class ToolRoute:
    name: str
    description: str
    command: str
    input_schema: dict[str, Any]


class ToolArgumentValidationError(ValueError):
    """MCP Tool 인자가 게시된 입력 Schema와 일치하지 않을 때 발생합니다."""


def _matches_json_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        return isinstance(value, float) and math.isfinite(value)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    raise ToolArgumentValidationError(f"Unsupported schema type: {expected_type}")


_SCHEMA_KEYS = {
    "$id",
    "$schema",
    "additionalProperties",
    "anyOf",
    "default",
    "deprecated",
    "description",
    "enum",
    "examples",
    "exclusiveMaximum",
    "exclusiveMinimum",
    "items",
    "maxItems",
    "maxLength",
    "maximum",
    "minItems",
    "minLength",
    "minimum",
    "properties",
    "readOnly",
    "required",
    "title",
    "type",
    "writeOnly",
}


def _validate_schema_definition(schema: dict[str, Any], path: str) -> None:
    if not isinstance(schema, dict):
        raise ValueError(f"{path} must be a JSON Schema object.")

    unknown_keys = sorted(set(schema) - _SCHEMA_KEYS)
    if unknown_keys:
        raise ValueError(
            f"{path} uses unsupported schema keyword(s): {', '.join(unknown_keys)}"
        )

    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = (
            expected_type
            if isinstance(expected_type, list)
            else [expected_type]
        )
        allowed_types = {
            "array",
            "boolean",
            "integer",
            "null",
            "number",
            "object",
            "string",
        }
        if (
            not expected_types
            or not all(isinstance(item, str) for item in expected_types)
            or not set(expected_types).issubset(allowed_types)
        ):
            raise ValueError(f"{path}.type is not supported.")

    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            raise ValueError(f"{path}.properties must be an object.")
        for name, child_schema in properties.items():
            _validate_schema_definition(child_schema, f"{path}.properties.{name}")

    items = schema.get("items")
    if items is not None:
        _validate_schema_definition(items, f"{path}.items")

    required = schema.get("required")
    if required is not None and (
        not isinstance(required, list)
        or not all(isinstance(item, str) for item in required)
    ):
        raise ValueError(f"{path}.required must be an array of strings.")

    additional_properties = schema.get("additionalProperties")
    if (
        additional_properties is not None
        and not isinstance(additional_properties, (bool, dict))
    ):
        raise ValueError(
            f"{path}.additionalProperties must be a boolean or schema object."
        )
    if isinstance(additional_properties, dict):
        _validate_schema_definition(
            additional_properties,
            f"{path}.additionalProperties",
        )

    any_of = schema.get("anyOf")
    if any_of is not None:
        if not isinstance(any_of, list) or not any_of:
            raise ValueError(f"{path}.anyOf must be a non-empty array.")
        for index, child_schema in enumerate(any_of):
            _validate_schema_definition(
                child_schema,
                f"{path}.anyOf[{index}]",
            )

    enum = schema.get("enum")
    if enum is not None and not isinstance(enum, list):
        raise ValueError(f"{path}.enum must be an array.")


def _validate_json_value(value: Any, schema: dict[str, Any], path: str) -> None:
    if not isinstance(schema, dict):
        raise ToolArgumentValidationError(f"{path} schema must be an object.")

    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = (
            list(expected_type)
            if isinstance(expected_type, list)
            else [expected_type]
        )
        if not expected_types or not all(isinstance(item, str) for item in expected_types):
            raise ToolArgumentValidationError(f"{path} has an invalid schema type.")
        if not any(_matches_json_type(value, item) for item in expected_types):
            expected_text = " or ".join(expected_types)
            raise ToolArgumentValidationError(
                f"{path} must be {expected_text}; got {type(value).__name__}."
            )

    if "enum" in schema and value not in schema["enum"]:
        raise ToolArgumentValidationError(
            f"{path} must be one of {schema['enum']!r}."
        )

    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        if minimum_length is not None and len(value) < int(minimum_length):
            raise ToolArgumentValidationError(
                f"{path} must contain at least {minimum_length} characters."
            )
        maximum_length = schema.get("maxLength")
        if maximum_length is not None and len(value) > int(maximum_length):
            raise ToolArgumentValidationError(
                f"{path} must contain at most {maximum_length} characters."
            )

    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (isinstance(value, int) or math.isfinite(value))
    ):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            raise ToolArgumentValidationError(
                f"{path} must be greater than or equal to {minimum}."
            )
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            raise ToolArgumentValidationError(
                f"{path} must be less than or equal to {maximum}."
            )
        exclusive_minimum = schema.get("exclusiveMinimum")
        if exclusive_minimum is not None and value <= exclusive_minimum:
            raise ToolArgumentValidationError(
                f"{path} must be greater than {exclusive_minimum}."
            )
        exclusive_maximum = schema.get("exclusiveMaximum")
        if exclusive_maximum is not None and value >= exclusive_maximum:
            raise ToolArgumentValidationError(
                f"{path} must be less than {exclusive_maximum}."
            )

    if isinstance(value, dict):
        required = schema.get("required", [])
        if not isinstance(required, list):
            raise ToolArgumentValidationError(f"{path}.required must be an array.")
        for name in required:
            if name not in value:
                raise ToolArgumentValidationError(f"{path}.{name} is required.")

        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ToolArgumentValidationError(f"{path}.properties must be an object.")

        additional_properties = schema.get("additionalProperties", True)
        for name, child in value.items():
            child_path = f"{path}.{name}"
            child_schema = properties.get(name)
            if child_schema is not None:
                _validate_json_value(child, child_schema, child_path)
                continue
            if additional_properties is False:
                raise ToolArgumentValidationError(
                    f"{child_path} is not an allowed argument."
                )
            if isinstance(additional_properties, dict):
                _validate_json_value(child, additional_properties, child_path)

    if isinstance(value, list):
        minimum_items = schema.get("minItems")
        if minimum_items is not None and len(value) < int(minimum_items):
            raise ToolArgumentValidationError(
                f"{path} must contain at least {minimum_items} items."
            )
        maximum_items = schema.get("maxItems")
        if maximum_items is not None and len(value) > int(maximum_items):
            raise ToolArgumentValidationError(
                f"{path} must contain at most {maximum_items} items."
            )
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_json_value(item, item_schema, f"{path}[{index}]")

    any_of = schema.get("anyOf")
    if any_of is not None:
        if not isinstance(any_of, list) or not any_of:
            raise ToolArgumentValidationError(f"{path}.anyOf must be a non-empty array.")
        branch_errors: list[str] = []
        for branch in any_of:
            try:
                _validate_json_value(value, branch, path)
                break
            except ToolArgumentValidationError as exc:
                branch_errors.append(str(exc))
        else:
            detail = " | ".join(branch_errors[:3])
            raise ToolArgumentValidationError(
                f"{path} must match at least one allowed shape: {detail}"
            )


def validate_tool_arguments(
    arguments: dict[str, Any], input_schema: dict[str, Any]
) -> None:
    """현재 Manifest가 사용하는 의존성 없는 JSON Schema 부분집합을 검사합니다."""

    _validate_json_value(arguments, input_schema, "arguments")


class RuntimeClient:
    def __init__(self, session_file: Path):
        self.session_file = session_file
        self.session_mtime_ns: int | None = None
        self.endpoint = ""
        self.token = ""
        self.token_header = ""
        self._reload_session()

    def _reload_session(self) -> None:
        session = load_json(self.session_file)
        endpoint = str(session["endpoint"])
        parsed = urllib.parse.urlparse(endpoint)
        host = parsed.hostname
        if host is None or not ipaddress.ip_address(host).is_loopback:
            raise ValueError("Runtime endpoint must use a numeric loopback address.")

        rpc_path = str(session.get("rpcPath", "/rpc"))
        self.endpoint = endpoint.rstrip("/") + "/" + rpc_path.lstrip("/")
        self.token = str(session["token"])
        self.token_header = str(session.get("tokenHeader", "X-Game-Runtime-Token"))
        self.session_mtime_ns = self.session_file.stat().st_mtime_ns

    def _reload_session_if_changed(self) -> None:
        current_mtime_ns = self.session_file.stat().st_mtime_ns
        if current_mtime_ns != self.session_mtime_ns:
            self._reload_session()

    def call(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._reload_session_if_changed()
        body = json.dumps(
            {"protocol": 1, "command": command, "payload": payload},
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                self.token_header: self.token,
            },
            method="POST",
        )
        with _RUNTIME_OPENER.open(request, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))


class DiscoveringRuntimeClient:
    def __init__(
        self,
        local_low_root: Path,
        session_name: str,
        product: str | None,
        instance_id: str | None = None,
        role: str | None = None,
    ):
        self.local_low_root = local_low_root
        self.session_name = session_name
        self.product = product
        self.instance_id = instance_id
        self.role = role
        self.session_file: Path | None = None
        self.client: RuntimeClient | None = None

    def call(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        session_file = discover_session_file(
            self.local_low_root,
            self.session_name,
            self.product,
            self.instance_id,
            self.role,
        )
        if self.client is None or session_file != self.session_file:
            self.session_file = session_file
            self.client = RuntimeClient(session_file)
        return self.client.call(command, payload)


class McpHost:
    def __init__(self, client: RuntimeClient, manifest: dict[str, Any]):
        self.client = client
        self.server_name = str(manifest.get("serverName", "game-runtime-mcp"))
        self.server_version = str(manifest.get("serverVersion", "0.1.0"))
        self.routes = self._parse_routes(manifest)

    @staticmethod
    def _parse_routes(manifest: dict[str, Any]) -> dict[str, ToolRoute]:
        routes: dict[str, ToolRoute] = {}
        for item in manifest.get("tools", []):
            input_schema = item["inputSchema"]
            if not isinstance(input_schema, dict):
                raise ValueError(f"Tool inputSchema must be an object: {item['name']}")
            _validate_schema_definition(
                input_schema,
                f"tools[{item['name']}].inputSchema",
            )
            route = ToolRoute(
                name=str(item["name"]),
                description=str(item["description"]),
                command=str(item["command"]),
                input_schema=input_schema,
            )
            if route.name in routes:
                raise ValueError(f"Duplicate tool name: {route.name}")
            routes[route.name] = route
        if not routes:
            raise ValueError("Tool manifest must define at least one tool.")
        return routes

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        request_id = message.get("id")
        method = message.get("method")
        if method == "initialize":
            return rpc_response(
                request_id,
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": self.server_name,
                        "version": self.server_version,
                    },
                },
            )
        if method == "ping":
            return rpc_response(request_id, {})
        if method == "tools/list":
            return rpc_response(
                request_id,
                {
                    "tools": [
                        {
                            "name": route.name,
                            "description": route.description,
                            "inputSchema": route.input_schema,
                        }
                        for route in self.routes.values()
                    ]
                },
            )
        if method == "tools/call":
            params = message.get("params", {})
            if not isinstance(params, dict):
                return rpc_response(
                    request_id,
                    error={"code": -32602, "message": "Tool call params must be an object."},
                )
            name = params.get("name")
            route = self.routes.get(name)
            if route is None:
                return rpc_response(
                    request_id,
                    error={"code": -32602, "message": f"Unknown tool: {name}"},
                )

            arguments = params.get("arguments", {})
            if arguments is None:
                arguments = {}
            if not isinstance(arguments, dict):
                return rpc_response(
                    request_id,
                    error={
                        "code": -32602,
                        "message": f"Arguments for tool '{name}' must be an object.",
                    },
                )
            try:
                validate_tool_arguments(arguments, route.input_schema)
            except ToolArgumentValidationError as exc:
                return rpc_response(
                    request_id,
                    error={
                        "code": -32602,
                        "message": f"Invalid arguments for tool '{name}': {exc}",
                    },
                )

            try:
                runtime_result = self.client.call(route.command, dict(arguments))
                return rpc_response(
                    request_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(runtime_result, ensure_ascii=False),
                            }
                        ],
                        "isError": not bool(runtime_result.get("ok", False)),
                    },
                )
            except (OSError, urllib.error.URLError, ValueError) as exc:
                return rpc_response(
                    request_id,
                    {
                        "content": [
                            {"type": "text", "text": f"Runtime bridge error: {exc}"}
                        ],
                        "isError": True,
                    },
                )
        if request_id is None:
            return None
        return rpc_response(
            request_id,
            error={"code": -32601, "message": f"Method not found: {method}"},
        )


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _session_search_patterns(session_name: str) -> list[str]:
    name = Path(session_name).name
    patterns = [name]
    if any(character in name for character in "*?[]"):
        return patterns

    suffix = Path(name).suffix
    stem = name[: -len(suffix)] if suffix else name
    suffixed = f"{stem}-*{suffix}"
    if suffixed != name:
        patterns.append(suffixed)
    return patterns


def discover_session_file(
    local_low_root: Path,
    session_name: str,
    product: str | None,
    instance_id: str | None = None,
    role: str | None = None,
) -> Path:
    candidates: list[Path] = []
    seen: set[Path] = set()

    for pattern in _session_search_patterns(session_name):
        for path in local_low_root.rglob(pattern):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)

            try:
                session = load_json(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue

            if product and str(session.get("product", "")) != product:
                continue

            if instance_id:
                descriptor_instance = str(session.get("instanceId", ""))
                suffix = Path(path.name).suffix
                file_stem = path.name[: -len(suffix)] if suffix else path.name
                expected_suffix = f"-{instance_id}"
                if (
                    descriptor_instance != instance_id
                    and not file_stem.endswith(expected_suffix)
                ):
                    continue

            if role and str(session.get("role", "")) != role:
                continue

            candidates.append(path)

    if not candidates:
        filters = []
        if product:
            filters.append(f"product={product!r}")
        if instance_id:
            filters.append(f"instance={instance_id!r}")
        if role:
            filters.append(f"role={role!r}")
        filter_text = f" ({', '.join(filters)})" if filters else ""
        raise FileNotFoundError(
            f"No runtime session matching '{session_name}'{filter_text} "
            f"was found under {local_low_root}."
        )

    return max(candidates, key=lambda item: item.stat().st_mtime_ns)


def rpc_response(
    request_id: Any,
    result: Any = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message = {"jsonrpc": "2.0", "id": request_id}
    if error is None:
        message["result"] = result
    else:
        message["error"] = error
    return message


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--session-file",
        default=os.environ.get("GAME_RUNTIME_MCP_SESSION"),
    )
    parser.add_argument(
        "--session-name",
        default=os.environ.get(
            "GAME_RUNTIME_MCP_SESSION_NAME", "llm-conversation-lab-runtime-mcp.json"
        ),
    )
    parser.add_argument(
        "--session-product",
        default=os.environ.get("GAME_RUNTIME_MCP_SESSION_PRODUCT", "LLMConversationLab"),
    )
    parser.add_argument(
        "--session-instance",
        default=os.environ.get("GAME_RUNTIME_MCP_SESSION_INSTANCE"),
    )
    parser.add_argument(
        "--session-role",
        default=os.environ.get("GAME_RUNTIME_MCP_SESSION_ROLE"),
    )
    parser.add_argument(
        "--tools-file",
        default=os.environ.get("GAME_RUNTIME_MCP_TOOLS"),
        required="GAME_RUNTIME_MCP_TOOLS" not in os.environ,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = (
        RuntimeClient(Path(args.session_file).resolve())
        if args.session_file
        else DiscoveringRuntimeClient(
            Path.home() / "AppData" / "LocalLow",
            args.session_name,
            args.session_product or None,
            args.session_instance or None,
            args.session_role or None,
        )
    )
    host = McpHost(client, load_json(Path(args.tools_file).resolve()))

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            output = host.handle(json.loads(line))
        except Exception as exc:
            output = rpc_response(None, error={"code": -32603, "message": str(exc)})
        if output is not None:
            sys.stdout.write(
                json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
            sys.stdout.flush()


if __name__ == "__main__":
    main()
