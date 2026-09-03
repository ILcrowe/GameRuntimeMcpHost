#!/usr/bin/env python3
"""Persistent Codex CLI app-server session adapter for game runtime agents."""

from __future__ import annotations

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
        self.rpc: JsonRpcStdioClient | None = None
        self.thread_id = ""
        self.utility_thread_ids: dict[str, str] = {}
        self.descriptor = ProviderSessionDescriptor(self.state_root / "provider_sessions.json")
        self.memory_stream = AppendOnlyConversationStream(
            self.state_root / "memory-stream" / "external-gm.jsonl"
        )

    @property
    def session_id(self) -> str:
        return self.thread_id

    def _common_thread_params(self, model: str, reasoning_effort: str) -> dict[str, Any]:
        return {
            "model": model,
            "cwd": str(self.workspace),
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "config": {"model_reasoning_effort": reasoning_effort},
        }

    def start(self, model: str, reasoning_effort: str) -> None:
        if self.rpc is not None and self.rpc.is_running and self.thread_id:
            return
        if self.rpc is not None:
            self.rpc.close()
        self.utility_thread_ids.clear()
        self.rpc = JsonRpcStdioClient(
            [self.command, "app-server", "--listen", "stdio://"],
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

        common = self._common_thread_params(model, reasoning_effort)
        stored = self.descriptor.read_id(self.provider_name)
        if stored:
            try:
                response = self.rpc.request(
                    "thread/resume",
                    {"threadId": stored, **common},
                    timeout=30,
                )
                self.thread_id = str((response.get("thread") or {}).get("id") or stored)
            except (RpcError, TimeoutError, RuntimeError):
                self.thread_id = ""

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
        existing = self.utility_thread_ids.get(utility_key)
        if existing:
            return existing
        assert self.rpc is not None
        response = self.rpc.request(
            "thread/start",
            self._common_thread_params(model, reasoning_effort),
            timeout=30,
        )
        thread_id = str((response.get("thread") or {}).get("id") or "").strip()
        if not thread_id:
            raise RuntimeError("Codex app-server did not return a utility thread id")
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

        def on_message(message: dict[str, Any]) -> None:
            method = str(message.get("method") or "")
            params = message.get("params") or {}
            if method == "item/agentMessage/delta":
                delta = params.get("delta")
                if delta:
                    assistant_parts.append(str(delta))
            elif method == "item/completed":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage" and item.get("text"):
                    assistant_parts.clear()
                    assistant_parts.append(str(item.get("text")))

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
        if not turn_id:
            raise RuntimeError("Codex turn/start did not return a turn id")

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
        self.start(model, reasoning_effort)
        return self._generate_on_thread(
            self.thread_id,
            prompt,
            output_schema=output_schema,
            model=model,
            reasoning_effort=reasoning_effort,
            event_type="turn",
        )

    def generate_utility(
        self,
        channel: str,
        prompt: str,
        *,
        output_schema: dict[str, Any],
        model: str,
        reasoning_effort: str,
    ) -> dict[str, Any]:
        thread_id = self._get_utility_thread(
            channel,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        return self._generate_on_thread(
            thread_id,
            prompt,
            output_schema=output_schema,
            model=model,
            reasoning_effort=reasoning_effort,
            event_type="utility-turn",
            channel=channel,
        )

    def close(self) -> None:
        self.utility_thread_ids.clear()
        try:
            self.memory_stream.close()
        finally:
            if self.rpc is not None:
                self.rpc.close()
                self.rpc = None
