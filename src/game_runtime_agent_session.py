#!/usr/bin/env python3
"""Provider-neutral subprocess/session primitives for game runtime agent bridges."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable


class RpcError(RuntimeError):
    """JSON-RPC error returned by an external provider process."""

    def __init__(self, method: str, error: Any):
        self.method = method
        self.error = error
        if isinstance(error, dict):
            code = error.get("code", "rpc_error")
            message = error.get("message", json.dumps(error, ensure_ascii=False))
            super().__init__(f"{method} failed ({code}): {message}")
        else:
            super().__init__(f"{method} failed: {error}")


def windows_process_command(command: list[str]) -> list[str]:
    """Wrap cmd/bat executables so subprocess invocation works on Windows."""
    if not command:
        raise ValueError("command is empty")
    executable = command[0]
    suffix = Path(executable).suffix.lower()
    if os.name == "nt" and suffix in {".cmd", ".bat"}:
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", *command]
    return command


class JsonRpcStdioClient:
    """Synchronous JSON-RPC-over-stdio client backed by one long-lived process."""

    def __init__(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        include_jsonrpc: bool,
        name: str,
    ):
        self.command = windows_process_command(command)
        self.cwd = Path(cwd).resolve() if cwd is not None else None
        self.env = env
        self.include_jsonrpc = include_jsonrpc
        self.name = name
        self.process: subprocess.Popen[str] | None = None
        self._messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr_tail: deque[str] = deque(maxlen=40)
        self._request_id = 0
        self._write_lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._closed = False

    @property
    def is_running(self) -> bool:
        process = self.process
        return process is not None and process.poll() is None

    @property
    def stderr_tail(self) -> str:
        return "\n".join(self._stderr_tail)

    def start(self) -> None:
        if self.is_running:
            return
        merged_env = os.environ.copy()
        if self.env:
            merged_env.update(self.env)
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            self.command,
            cwd=str(self.cwd) if self.cwd is not None else None,
            env=merged_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        self._closed = False
        self._reader_thread = threading.Thread(
            target=self._read_stdout,
            name=f"{self.name}-stdout",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            name=f"{self.name}-stderr",
            daemon=True,
        )
        self._reader_thread.start()
        self._stderr_thread.start()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self.process
        self.process = None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.terminate()
            process.wait(timeout=2.0)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.stdout and process.stdout.close()
            process.stderr and process.stderr.close()
        except OSError:
            pass

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"method": method}
        if self.include_jsonrpc:
            payload["jsonrpc"] = "2.0"
        if params is not None:
            payload["params"] = params
        self._write(payload)

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
        notification_handler: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if not self.is_running:
            self.start()
        self._request_id += 1
        request_id = self._request_id
        payload: dict[str, Any] = {"id": request_id, "method": method}
        if self.include_jsonrpc:
            payload["jsonrpc"] = "2.0"
        if params is not None:
            payload["params"] = params
        self._write(payload)

        deadline = time.monotonic() + max(0.1, timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"{self.name} {method} timed out")
            message = self._next_message(remaining)
            if message.get("id") == request_id and (
                "result" in message or "error" in message
            ):
                if message.get("error") is not None:
                    raise RpcError(method, message.get("error"))
                result = message.get("result")
                return result if isinstance(result, dict) else {"value": result}
            self._handle_unsolicited(message, notification_handler)

    def wait_for_notification(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        timeout: float,
        notification_handler: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.1, timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"{self.name} notification wait timed out")
            message = self._next_message(remaining)
            if predicate(message):
                if notification_handler:
                    notification_handler(message)
                return message
            self._handle_unsolicited(message, notification_handler)

    def _next_message(self, timeout: float) -> dict[str, Any]:
        process = self.process
        if process is not None and process.poll() is not None and self._messages.empty():
            detail = self.stderr_tail
            raise RuntimeError(
                f"{self.name} exited with code {process.returncode}"
                + (f": {detail[-1200:]}" if detail else "")
            )
        try:
            return self._messages.get(timeout=max(0.01, timeout))
        except queue.Empty as exc:
            process = self.process
            if process is not None and process.poll() is not None:
                detail = self.stderr_tail
                raise RuntimeError(
                    f"{self.name} exited with code {process.returncode}"
                    + (f": {detail[-1200:]}" if detail else "")
                ) from exc
            raise TimeoutError(f"{self.name} produced no JSON-RPC message") from exc

    def _handle_unsolicited(
        self,
        message: dict[str, Any],
        notification_handler: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        # Provider integrations are narrative/runtime workers. They must never block
        # on shell, file, or user-input approvals requested by coding-agent protocols.
        if "method" in message and "id" in message:
            method = str(message.get("method") or "")
            response: dict[str, Any] = {"id": message.get("id")}
            if self.include_jsonrpc:
                response["jsonrpc"] = "2.0"
            if method == "session/request_permission":
                options = (message.get("params") or {}).get("options") or []
                reject_option = next(
                    (
                        option
                        for option in options
                        if isinstance(option, dict)
                        and str(option.get("kind") or "").startswith("reject")
                    ),
                    None,
                )
                outcome = (
                    {
                        "outcome": "selected",
                        "optionId": str(reject_option.get("optionId")),
                    }
                    if reject_option and reject_option.get("optionId")
                    else {"outcome": "cancelled"}
                )
                response["result"] = {"outcome": outcome}
            elif method.endswith("requestApproval"):
                response["result"] = {"decision": "decline"}
            elif method == "item/tool/requestUserInput":
                response["result"] = {"answers": {}}
            else:
                response["error"] = {
                    "code": -32601,
                    "message": "Game runtime external agent does not service this request",
                }
            self._write(response)
            return
        if notification_handler:
            notification_handler(message)

    def _write(self, payload: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.stdin is None or process.poll() is not None:
            raise RuntimeError(f"{self.name} stdin is unavailable")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            process.stdin.write(encoded + "\n")
            process.stdin.flush()

    def _read_stdout(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            text = line.strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                self._stderr_tail.append(f"[stdout] {text}")
                continue
            if isinstance(message, dict):
                self._messages.put(message)

    def _read_stderr(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            text = line.rstrip()
            if text:
                self._stderr_tail.append(text)


class AppendOnlyConversationStream:
    """Open-once, line-buffered provider-independent JSONL memory/audit stream."""

    def __init__(self, path: Path, tail_capacity: int = 128):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("a", encoding="utf-8", buffering=1)
        self._tail: deque[dict[str, Any]] = deque(maxlen=max(8, tail_capacity))
        self._lock = threading.Lock()

    def append(
        self,
        event_type: str,
        *,
        provider: str,
        session_id: str,
        payload: dict[str, Any],
    ) -> None:
        record = {
            "atUnixMs": int(time.time() * 1000),
            "type": event_type,
            "provider": provider,
            "providerSessionId": session_id,
            "payload": payload,
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._stream.write(line + "\n")
            self._stream.flush()
            self._tail.append(record)

    def tail(self, count: int = 32) -> list[dict[str, Any]]:
        with self._lock:
            take = max(1, min(len(self._tail), count))
            return list(self._tail)[-take:]

    def close(self) -> None:
        with self._lock:
            if self._stream.closed:
                return
            self._stream.flush()
            self._stream.close()


class ProviderSessionDescriptor:
    """Small provider-session ID registry stored beside a save/run scope."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read_id(self, provider: str) -> str:
        try:
            if not self.path.exists():
                return ""
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            value = (data.get(provider) or {}).get("sessionId", "")
            return str(value or "").strip()
        except (OSError, ValueError, TypeError):
            return ""

    def write_id(self, provider: str, session_id: str) -> None:
        data: dict[str, Any] = {}
        try:
            if self.path.exists():
                loaded = json.loads(self.path.read_text(encoding="utf-8-sig"))
                if isinstance(loaded, dict):
                    data = loaded
        except (OSError, ValueError, TypeError):
            data = {}
        data[provider] = {
            "sessionId": session_id,
            "updatedAtUnixMs": int(time.time() * 1000),
        }
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the outermost JSON object from provider text output."""
    value = (text or "").strip()
    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end < start:
        raise ValueError("agent response does not contain a JSON object")
    parsed = json.loads(value[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("agent response JSON must be an object")
    return parsed
