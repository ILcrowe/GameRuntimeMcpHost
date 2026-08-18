#!/usr/bin/env python3
"""MCP stdio proxy for token-authenticated localhost game runtime adapters."""

from __future__ import annotations

import argparse
import ipaddress
import json
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
        self, local_low_root: Path, session_name: str, product: str | None
    ):
        self.local_low_root = local_low_root
        self.session_name = session_name
        self.product = product
        self.session_file: Path | None = None
        self.client: RuntimeClient | None = None

    def call(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        session_file = discover_session_file(
            self.local_low_root, self.session_name, self.product
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
            route = ToolRoute(
                name=str(item["name"]),
                description=str(item["description"]),
                command=str(item["command"]),
                input_schema=dict(item["inputSchema"]),
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
            name = params.get("name")
            route = self.routes.get(name)
            if route is None:
                return rpc_response(
                    request_id,
                    error={"code": -32602, "message": f"Unknown tool: {name}"},
                )
            try:
                runtime_result = self.client.call(
                    route.command,
                    dict(params.get("arguments", {})),
                )
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


def discover_session_file(
    local_low_root: Path, session_name: str, product: str | None
) -> Path:
    candidates: list[Path] = []
    for path in local_low_root.rglob(session_name):
        try:
            session = load_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if product and str(session.get("product", "")) != product:
            continue
        candidates.append(path)
    if not candidates:
        raise FileNotFoundError(
            f"No runtime session named '{session_name}' was found under {local_low_root}."
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
