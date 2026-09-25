#!/usr/bin/env python3
"""Persistent Codex CLI app-server session adapter for game runtime agents."""

from __future__ import annotations

import copy
import re
import shutil
from pathlib import Path
from typing import Any

from game_runtime_agent_session import (
    AppendOnlyConversationStream,
    JsonRpcStdioClient,
    ProviderSessionDescriptor,
    RpcError,
    extract_json_object,
)


class CodexPersistentSession:
    """One Codex app-server process with a persistent primary thread.

    Utility requests use separate in-process threads so diagnostics and parsers do
    not contaminate the primary conversation. The caller owns prompt construction,
    output schemas, and game-authority validation.
    """

    provider_name = "codex"

    def __init__(
        self,
        state_root: Path,
        *,
        timeout_seconds: int = 105,
        command: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        client_name: str = "game-runtime-agent",
        client_title: str = "Game Runtime External Agent",
        base_instructions: str | None = None,
        thread_config: dict[str, Any] | None = None,
        disable_mcp_servers: bool = False,
        stateless_utility_channels: tuple[str, ...] = (),
    ):
        self.state_root = Path(state_root).resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.workspace = self.state_root / "codex-workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = max(10, timeout_seconds)
        self.command = command or shutil.which("codex.cmd") or shutil.which("codex")
        if not self.command:
            raise FileNotFoundError("Codex CLI was not found. Verify `codex --version`.")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.client_name = client_name
        self.client_title = client_title
        self.base_instructions = base_instructions
        self.thread_config = copy.deepcopy(thread_config or {})
        self.disable_mcp_servers = disable_mcp_servers
        self.stateless_utility_channels = frozenset(
            channel.strip().lower() for channel in stateless_utility_channels
        )
        self.disabled_mcp_server_names: list[str] = []
        self.rpc: JsonRpcStdioClient | None = None
        self.thread_id = ""
        self.last_requested_model = ""
        self.last_confirmed_model = ""
        self.last_completed_turn_id = ""
        self.utility_thread_ids: dict[str, str] = {}
        # Optional display observer of primary-thread public text. Never reasoning.
        self.on_primary_text = None
        self.descriptor = ProviderSessionDescriptor(self.state_root / "provider_sessions.json")
        self.memory_stream = AppendOnlyConversationStream(
            self.state_root / "memory-stream" / "external-gm.jsonl"
        )

    @property
    def session_id(self) -> str:
        return self.thread_id

    def _common_thread_params(self, model: str, reasoning_effort: str) -> dict[str, Any]:
        config = copy.deepcopy(self.thread_config)
        for name in self.disabled_mcp_server_names:
            config["mcp_servers." + name + ".enabled"] = False
        config["model_reasoning_effort"] = reasoning_effort
        params = {
            "model": model,
            "cwd": str(self.workspace),
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "config": config,
        }
        if self.base_instructions is not None:
            params["baseInstructions"] = self.base_instructions
        return params

    def start(self, model: str, reasoning_effort: str) -> None:
        if self.rpc is not None and self.rpc.is_running and self.thread_id:
            return
        if self.rpc is not None:
            self.rpc.close()
        self.thread_id = ""
        self.utility_thread_ids.clear()
        command = [self.command, "app-server", "--listen", "stdio://"]
        if self.disable_mcp_servers:
            command += ["-c", "features.plugins=false", "-c", "features.apps=false"]
        self.rpc = JsonRpcStdioClient(
            command,
            cwd=self.workspace,
            include_jsonrpc=False,
            name="codex-app-server",
        )
        self.rpc.start()
        self.rpc.request(
            "initialize",
            {
                "clientInfo": {
                    "name": self.client_name,
                    "title": self.client_title,
                    "version": "0.1.0",
                }
            },
            timeout=20,
        )
        self.rpc.notify("initialized", {})
        self.disabled_mcp_server_names = []
        if self.disable_mcp_servers:
            configuration = self.rpc.request("config/read", {
                "cwd": str(self.workspace), "includeLayers": False,
            }, timeout=20)
            servers = (configuration.get("config") or {}).get("mcp_servers") or {}
            if not isinstance(servers, dict):
                raise RuntimeError("Codex MCP configuration could not be isolated")
            self.disabled_mcp_server_names = list(servers)
            if any(not re.fullmatch(r"[A-Za-z0-9_-]+", name) for name in self.disabled_mcp_server_names):
                raise RuntimeError("Codex MCP isolation requires simple server identifiers")
            # Process-level services also consult the startup config. A thread
            # override alone does not isolate app-server's MCP status/tool pool.
            if self.disabled_mcp_server_names:
                self.rpc.close()
                for name in self.disabled_mcp_server_names:
                    command += ["-c", "mcp_servers." + name + ".enabled=false"]
                self.rpc = JsonRpcStdioClient(command, cwd=self.workspace,
                    include_jsonrpc=False, name="codex-app-server")
                self.rpc.start()
                self.rpc.request("initialize", {"clientInfo": {
                    "name": self.client_name, "title": self.client_title, "version": "0.1.0",
                }}, timeout=20)
                self.rpc.notify("initialized", {})

        common = self._common_thread_params(model, reasoning_effort)
        stored = self.descriptor.read_id(self.provider_name)
        if stored:
            try:
                response = self.rpc.request(
                    "thread/resume",
                    {"threadId": stored, **common},
                    timeout=30,
                )
                resumed_id = str((response.get("thread") or {}).get("id") or stored)
                if resumed_id != stored:
                    raise RuntimeError("Codex resumed a different thread; stored story session was preserved")
                self.thread_id = resumed_id
            except (RpcError, TimeoutError, RuntimeError):
                self.thread_id = ""
                self.rpc.close()
                self.rpc = None
                # A failed resume is not permission to replace the saved story.
                # Surface the original failure and allow a later retry of its ID.
                raise

        if not self.thread_id:
            response = self.rpc.request("thread/start", common, timeout=30)
            self.thread_id = str((response.get("thread") or {}).get("id") or "").strip()
            if not self.thread_id:
                raise RuntimeError("Codex app-server did not return a thread id")
        self.descriptor.write_id(self.provider_name, self.thread_id)

    def _get_utility_thread(
        self,
        channel: str,
        *,
        model: str,
        reasoning_effort: str,
    ) -> str:
        self.start(model, reasoning_effort)
        utility_key = (channel or "utility").strip().lower() or "utility"
        stateless = utility_key in self.stateless_utility_channels
        existing = None if stateless else self.utility_thread_ids.get(utility_key)
        if existing:
            return existing
        assert self.rpc is not None
        response = self.rpc.request(
            "thread/start",
            {**self._common_thread_params(model, reasoning_effort),
             **({"ephemeral": True} if stateless else {})},
            timeout=30,
        )
        thread_id = str((response.get("thread") or {}).get("id") or "").strip()
        if not thread_id:
            raise RuntimeError("Codex app-server did not return a utility thread id")
        if not stateless:
            self.utility_thread_ids[utility_key] = thread_id
        return thread_id

    def _generate_on_thread(
        self,
        thread_id: str,
        prompt: str,
        *,
        output_schema: dict[str, Any],
        model: str,
        reasoning_effort: str,
        event_type: str,
        channel: str = "",
    ) -> dict[str, Any]:
        assert self.rpc is not None
        assistant_parts: list[str] = []
        turn_id = ""
        early_messages: list[dict[str, Any]] = []

        def on_message(message: dict[str, Any]) -> None:
            method = str(message.get("method") or "")
            params = message.get("params") or {}
            if params.get("threadId") and params["threadId"] != thread_id:
                return
            if method not in ("item/agentMessage/delta", "item/completed"):
                return
            if not turn_id:
                # turn/start can deliver notifications before its reply. Resolve
                # identity before publishing text left over from a cancelled turn.
                early_messages.append(message)
                return
            if params.get("turnId") and params["turnId"] != turn_id:
                return
            changed = False
            if method == "item/agentMessage/delta":
                delta = params.get("delta")
                if delta:
                    assistant_parts.append(str(delta))
                    changed = True
            elif method == "item/completed":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage" and item.get("text"):
                    assistant_parts.clear()
                    assistant_parts.append(str(item.get("text")))
                    changed = True
            if changed and not channel and self.on_primary_text is not None:
                try:
                    self.on_primary_text("".join(assistant_parts))
                except Exception:
                    # Display observers must not invalidate the authoritative result.
                    pass

        response = self.rpc.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt}],
                "model": model,
                "effort": reasoning_effort,
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
                "outputSchema": output_schema,
            },
            timeout=30,
            notification_handler=on_message,
        )
        turn_id = str((response.get("turn") or {}).get("id") or "")
        reported_model = (response.get("turn") or {}).get("model")
        if isinstance(reported_model, str):
            self.last_confirmed_model = reported_model
        if not turn_id:
            raise RuntimeError("Codex turn/start did not return a turn id")
        for message in early_messages:
            on_message(message)
        early_messages.clear()

        try:
            completed = self.rpc.wait_for_notification(
                lambda message: message.get("method") == "turn/completed"
                and str(((message.get("params") or {}).get("turn") or {}).get("id") or "") == turn_id,
                timeout=self.timeout_seconds,
                notification_handler=on_message,
            )
        except TimeoutError:
            try:
                self.rpc.request(
                    "turn/interrupt",
                    {"threadId": thread_id, "turnId": turn_id},
                    timeout=5,
                )
            except (RpcError, TimeoutError, RuntimeError):
                pass
            raise

        turn = (completed.get("params") or {}).get("turn") or {}
        if isinstance(turn.get("model"), str):
            self.last_confirmed_model = turn["model"]
        status = str(turn.get("status") or "")
        if status != "completed":
            error = turn.get("error") or {}
            detail = error.get("message") if isinstance(error, dict) else error
            raise RuntimeError(
                f"Codex turn ended with status {status or 'unknown'}"
                + (f": {detail}" if detail else "")
            )

        text = "".join(assistant_parts).strip()
        result = extract_json_object(text)
        if not channel:
            self.last_completed_turn_id = turn_id
        payload: dict[str, Any] = {
            "user": prompt,
            "assistant": result,
            "turnId": turn_id,
        }
        if channel:
            payload["channel"] = channel
        self.memory_stream.append(
            event_type,
            provider=self.provider_name,
            session_id=thread_id,
            payload=payload,
        )
        return result

    def generate(
        self,
        prompt: str,
        *,
        output_schema: dict[str, Any],
        model: str,
        reasoning_effort: str,
    ) -> dict[str, Any]:
        self.last_requested_model = model
        self.last_confirmed_model = ""
        self.start(model, reasoning_effort)
        return self._generate_on_thread(
            self.thread_id,
            prompt,
            output_schema=output_schema,
            model=model,
            reasoning_effort=reasoning_effort,
            event_type="turn",
        )

    def fork_primary_through(self, source_thread_id: str, last_turn_id: str,
                             *, model: str, reasoning_effort: str) -> str:
        """Restore a game checkpoint without deleting its later, abandoned branch."""
        if not source_thread_id or not last_turn_id:
            raise ValueError("A saved thread and completed turn are required")
        self.start(model, reasoning_effort)
        response = self.rpc.request("thread/fork", {
            "threadId": source_thread_id, "lastTurnId": last_turn_id,
            "excludeTurns": True, **self._common_thread_params(model, reasoning_effort),
        }, timeout=30)
        fork_id = str((response.get("thread") or {}).get("id") or "")
        if not fork_id or fork_id == source_thread_id:
            raise RuntimeError("Codex checkpoint fork did not return a new thread")
        self.descriptor.write_id(self.provider_name, fork_id)
        self.thread_id = fork_id
        self.last_completed_turn_id = last_turn_id
        self.utility_thread_ids.clear()
        return fork_id

    def generate_utility(
        self,
        channel: str,
        prompt: str,
        *,
        output_schema: dict[str, Any],
        model: str,
        reasoning_effort: str,
    ) -> dict[str, Any]:
        self.last_requested_model = model
        self.last_confirmed_model = ""
        thread_id = self._get_utility_thread(
            channel,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        try:
            return self._generate_on_thread(
                thread_id,
                prompt,
                output_schema=output_schema,
                model=model,
                reasoning_effort=reasoning_effort,
                event_type="utility-turn",
                channel=channel,
            )
        finally:
            utility_key = (channel or "utility").strip().lower() or "utility"
            if utility_key in self.stateless_utility_channels and self.rpc is not None:
                # Unsubscribe even on timeout/invalid output; app-server unloads
                # after its inactivity grace period. The public request/result
                # remains in our append-only audit log, never the story checkpoint.
                try:
                    self.rpc.request("thread/unsubscribe", {"threadId": thread_id}, timeout=5)
                except (RpcError, TimeoutError, RuntimeError):
                    # Cleanup must not hide the original inference result/error.
                    pass

    def close(self) -> None:
        self.utility_thread_ids.clear()
        try:
            self.memory_stream.close()
        finally:
            if self.rpc is not None:
                self.rpc.close()
                self.rpc = None
