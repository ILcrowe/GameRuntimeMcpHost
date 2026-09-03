#!/usr/bin/env python3
"""Persistent Grok Build headless-session adapter for game runtime agents."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from game_runtime_agent_session import (
    AppendOnlyConversationStream,
    ProviderSessionDescriptor,
    extract_json_object,
    windows_process_command,
)


DEFAULT_SYSTEM_PROMPT = (
    "You are a non-interactive game runtime response engine. "
    "Do not inspect repositories, read or write files, run terminal commands, browse, "
    "use MCP/tools, or ask the user for approval/input. Treat the supplied prompt as "
    "the complete task and context. Follow its structured-output contract exactly."
)

ISOLATED_GROK_CONFIG = """[compat.claude]\nmcps = false\n\n[compat.cursor]\nmcps = false\n\n[subagents]\nenabled = false\n"""

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class GrokHeadlessSession:
    """Resume Grok Build conversations through its supported headless CLI.

    Each request launches a bounded `grok -p --output-format json` process. The
    provider's returned session ID is persisted and passed back with `--resume` on
    the next primary turn. Utility channels use separate in-memory session IDs.

    The caller owns prompt construction, output schemas, and game-authority checks.
    """

    provider_name = "grok"

    def __init__(
        self,
        state_root: Path,
        *,
        timeout_seconds: int = 150,
        command: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        source_grok_home: Path | None = None,
        process_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        logger: Callable[[str], None] | None = None,
    ):
        self.state_root = Path(state_root).resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.workspace = self.state_root / "grok-workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.runtime_grok_home = self.state_root / "grok-runtime-home"
        configured_source = os.environ.get("GAME_RUNTIME_GROK_SOURCE_HOME")
        self.source_grok_home = Path(
            source_grok_home
            if source_grok_home is not None
            else configured_source or Path.home() / ".grok"
        ).expanduser().resolve()
        self.timeout_seconds = max(10, int(timeout_seconds))
        self.command = command or shutil.which("grok.cmd") or shutil.which("grok")
        if not self.command:
            raise FileNotFoundError("Grok Build CLI was not found. Verify `grok version`.")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.system_prompt = system_prompt.strip() or DEFAULT_SYSTEM_PROMPT
        self.process_runner = process_runner or subprocess.run
        self.logger = logger or (lambda message: print(f"[Grok Headless] {message}", flush=True))
        self.descriptor = ProviderSessionDescriptor(self.state_root / "provider_sessions.json")
        self.memory_stream = AppendOnlyConversationStream(
            self.state_root / "memory-stream" / "external-gm.jsonl"
        )
        self.grok_session_id = self.descriptor.read_id(self.provider_name)
        self.utility_session_ids: dict[str, str] = {}

    @property
    def session_id(self) -> str:
        return self.grok_session_id

    def _prepare_runtime_environment(self) -> dict[str, str]:
        self.runtime_grok_home.mkdir(parents=True, exist_ok=True)
        (self.runtime_grok_home / "config.toml").write_text(
            ISOLATED_GROK_CONFIG,
            encoding="utf-8",
        )

        source_auth = self.source_grok_home / "auth.json"
        runtime_auth = self.runtime_grok_home / "auth.json"
        if source_auth.exists() and source_auth.resolve() != runtime_auth.resolve():
            should_copy = not runtime_auth.exists()
            if not should_copy:
                try:
                    should_copy = source_auth.stat().st_mtime_ns > runtime_auth.stat().st_mtime_ns
                except OSError:
                    should_copy = False
            if should_copy:
                shutil.copy2(source_auth, runtime_auth)
                self.logger("copied cached Grok authentication into the isolated runtime home")

        child_env = os.environ.copy()
        child_env.update(
            {
                "GROK_HOME": str(self.runtime_grok_home),
                "GROK_CLAUDE_MCPS_ENABLED": "0",
                "GROK_CURSOR_MCPS_ENABLED": "0",
                "GROK_MEMORY": "0",
                "GROK_SUBAGENTS": "0",
                "GROK_AGENT_DASHBOARD": "0",
            }
        )
        return child_env

    def _build_command(
        self,
        prompt: str,
        output_schema: dict[str, Any],
        *,
        session_id: str = "",
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> list[str]:
        schema_json = json.dumps(output_schema, ensure_ascii=False, separators=(",", ":"))
        command = [
            self.command,
            "--no-auto-update",
            "--cwd",
            str(self.workspace),
            "--output-format",
            "json",
            "--json-schema",
            schema_json,
            "--system-prompt-override",
            self.system_prompt,
            "--verbatim",
            "--no-plan",
            "--no-subagents",
            "--no-ask-user",
            "--no-memory",
            "--disable-web-search",
            "--no-wait-for-background",
            "--max-turns",
            "1",
            "--deny",
            "Bash",
            "--deny",
            "Read",
            "--deny",
            "Grep",
            "--deny",
            "Edit",
            "--deny",
            "Write",
            "--deny",
            "WebFetch",
            "--deny",
            "MCPTool",
        ]
        effective_model = model or self.model
        if effective_model:
            command.extend(["--model", effective_model])
        effective_effort = reasoning_effort or self.reasoning_effort
        if effective_effort:
            command.extend(["--reasoning-effort", effective_effort])
        if session_id:
            command.extend(["--resume", session_id])
        command.extend(["-p", prompt])
        return windows_process_command(command)

    @staticmethod
    def _clean_diagnostic(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        return _ANSI_ESCAPE.sub("", str(value)).strip()

    @staticmethod
    def _is_missing_resume_error(exc: BaseException) -> bool:
        text = str(exc).casefold()
        markers = (
            "path not found",
            "session not found",
            "unknown session",
            "does not exist",
            "couldn't start session",
            "could not start session",
            "failed to resume",
        )
        return any(marker in text for marker in markers)

    def _invoke(
        self,
        prompt: str,
        output_schema: dict[str, Any],
        *,
        session_id: str = "",
        model: str | None = None,
        reasoning_effort: str | None = None,
        channel: str = "",
    ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        mode = f"resume={session_id}" if session_id else "new-session"
        label = channel or "primary"
        self.logger(f"request start channel={label} {mode} chars={len(prompt)}")
        command = self._build_command(
            prompt,
            output_schema,
            session_id=session_id,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        try:
            completed = self.process_runner(
                command,
                cwd=str(self.workspace),
                env=self._prepare_runtime_environment(),
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
        except subprocess.TimeoutExpired as exc:
            detail = self._clean_diagnostic(exc.stderr or exc.stdout)
            raise TimeoutError(
                f"Grok headless request timed out after {self.timeout_seconds}s"
                + (f": {detail[-1200:]}" if detail else "")
            ) from exc

        stdout = self._clean_diagnostic(completed.stdout)
        stderr = self._clean_diagnostic(completed.stderr)
        payload: dict[str, Any] | None = None
        if stdout:
            try:
                parsed = json.loads(stdout)
                if isinstance(parsed, dict):
                    payload = parsed
            except json.JSONDecodeError:
                payload = None

        if completed.returncode != 0:
            provider_message = ""
            if payload:
                provider_message = str(payload.get("message") or payload.get("error") or "")
            detail = provider_message or stderr or stdout or "no diagnostic output"
            raise RuntimeError(
                f"Grok headless exited with {completed.returncode}: {detail[-1200:]}"
            )
        if payload is None:
            raise ValueError(
                "Grok headless stdout was not a JSON object"
                + (f": {stdout[-1200:]}" if stdout else "")
            )
        if payload.get("type") == "error":
            raise RuntimeError(str(payload.get("message") or "Grok headless returned an error"))

        provider_session_id = str(payload.get("sessionId") or "").strip()
        if not provider_session_id:
            raise ValueError("Grok headless response did not include sessionId")

        structured = payload.get("structuredOutput")
        if isinstance(structured, dict):
            result = structured
        else:
            text = payload.get("text")
            if isinstance(text, dict):
                result = text
            else:
                result = extract_json_object(str(text or ""))

        self.logger(
            f"request complete channel={label} session={provider_session_id} "
            f"stopReason={payload.get('stopReason', '')}"
        )
        return result, provider_session_id, payload

    def _invoke_with_resume_recovery(
        self,
        prompt: str,
        output_schema: dict[str, Any],
        *,
        session_id: str = "",
        model: str | None = None,
        reasoning_effort: str | None = None,
        channel: str = "",
    ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        try:
            return self._invoke(
                prompt,
                output_schema,
                session_id=session_id,
                model=model,
                reasoning_effort=reasoning_effort,
                channel=channel,
            )
        except RuntimeError as exc:
            if not session_id or not self._is_missing_resume_error(exc):
                raise
            self.logger(
                f"stored session could not be resumed; starting a new session: {exc}"
            )
            return self._invoke(
                prompt,
                output_schema,
                model=model,
                reasoning_effort=reasoning_effort,
                channel=channel,
            )

    @staticmethod
    def _audit_metadata(payload: dict[str, Any]) -> dict[str, Any]:
        allowed = (
            "stopReason",
            "sessionId",
            "requestId",
            "usage",
            "num_turns",
            "modelUsage",
            "total_cost_usd",
            "total_cost_usd_ticks",
            "cost_is_partial",
            "usage_is_incomplete",
        )
        return {key: payload[key] for key in allowed if key in payload}

    def generate(
        self,
        prompt: str,
        *,
        output_schema: dict[str, Any],
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        result, session_id, metadata = self._invoke_with_resume_recovery(
            prompt,
            output_schema,
            session_id=self.grok_session_id,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        self.grok_session_id = session_id
        self.descriptor.write_id(self.provider_name, session_id)
        self.memory_stream.append(
            "turn",
            provider=self.provider_name,
            session_id=session_id,
            payload={
                "user": prompt,
                "assistant": result,
                "providerResult": self._audit_metadata(metadata),
            },
        )
        return result

    def generate_utility(
        self,
        channel: str,
        prompt: str,
        *,
        output_schema: dict[str, Any],
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        utility_key = (channel or "utility").strip().lower() or "utility"
        existing = self.utility_session_ids.get(utility_key, "")
        result, session_id, metadata = self._invoke_with_resume_recovery(
            prompt,
            output_schema,
            session_id=existing,
            model=model,
            reasoning_effort=reasoning_effort,
            channel=utility_key,
        )
        self.utility_session_ids[utility_key] = session_id
        self.memory_stream.append(
            "utility-turn",
            provider=self.provider_name,
            session_id=session_id,
            payload={
                "channel": utility_key,
                "user": prompt,
                "assistant": result,
                "providerResult": self._audit_metadata(metadata),
            },
        )
        return result

    def close(self) -> None:
        self.utility_session_ids.clear()
        self.memory_stream.close()


ResumableGrokSession = GrokHeadlessSession
