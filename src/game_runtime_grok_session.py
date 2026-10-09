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

CONSENT_SCHEMA = "story-grok-session-consent/v1"


class GrokConsentDenied(PermissionError):
    """설정·인증·자식 프로세스에 접근하기 전에 반환하는 연결 거절입니다."""

    def __init__(self, report):
        self.report = report
        super().__init__(report["status"])


class GrokSessionConsent:
    """한 세션의 동의만 메모리에 보관하며 접근 격리 증명으로 사용하지 않습니다."""

    def __init__(self, decision="pending", scope=""):
        self.scope = str(scope)
        self.set_decision(decision)

    def set_decision(self, decision):
        if decision not in {"pending", "approved", "denied", "cancelled"}:
            raise ValueError("지원하지 않는 세션 동의 상태입니다.")
        self.decision = decision

    def evaluate(self, *, expected_scope=None, transport="acp"):
        if self.decision == "denied":
            reason, status = "consent_denied", "이 세션 요청을 거절했습니다. 연결·로그인·모델 요청을 시작하지 않습니다."
        elif self.decision == "cancelled":
            reason, status = "consent_cancelled", "이 세션 동의를 취소했습니다. 새 요청을 차단하고 기존 연결과 대화 기록을 유지합니다."
        elif self.decision != "approved" or not self.scope.strip():
            reason, status = "consent_required", "이 세션 요청에 대한 명시적 동의가 필요합니다. 연결·로그인·모델 요청을 시작하지 않았습니다."
        elif expected_scope is not None and self.scope != str(expected_scope):
            reason, status = "consent_scope_mismatch", "동의한 세션과 요청한 세션이 다릅니다. 새 요청을 차단했습니다."
        else:
            # CLI 내부 접근을 강제하는 경계가 없어 동의만으로 시작을 허용하지 않습니다.
            reason, status = "cli_access_isolation_unverified", "동의는 확인됐지만 파일·로컬 도구·네트워크 제한을 검증하지 못해 연결을 차단했습니다."
        return {"schema": "story-grok-session-consent-check/v1", "consentSchema": CONSENT_SCHEMA,
                "scope": self.scope, "decision": self.decision, "reason": reason, "status": status,
                "launchAllowed": False, "configurationAccessStarted": False,
                "credentialAccessStarted": False, "enforcedClientPermissionCallbacks": transport == "acp",
                "cliAccessIsolationVerified": False, "modelRequests": 0, "authenticationRequests": 0}

    def require_start(self, *, expected_scope=None, transport="acp"):
        report = self.evaluate(expected_scope=expected_scope, transport=transport)
        if not report["launchAllowed"]:
            raise GrokConsentDenied(report)

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
        workspace: Path | None = None,
        consent: GrokSessionConsent | None = None,
        process_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        logger: Callable[[str], None] | None = None,
    ):
        self.state_root = Path(state_root).resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.workspace = Path(workspace).expanduser().resolve() if workspace is not None else self.state_root / "grok-workspace"
        if workspace is None:
            self.workspace.mkdir(parents=True, exist_ok=True)
        self.legacy_runtime_grok_home = self.state_root / "grok-runtime-home"
        configured_source = os.environ.get("GAME_RUNTIME_GROK_SOURCE_HOME")
        self.source_grok_home = Path(
            source_grok_home
            if source_grok_home is not None
            else configured_source or os.environ.get("GROK_HOME") or Path.home() / ".grok"
        ).expanduser().resolve()
        self.runtime_grok_home = self.source_grok_home
        self.consent = consent if consent is not None else GrokSessionConsent(scope=str(self.state_root))
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
        self._require_start_consent()
        # 기존 폴더를 선택하기만 하며 설정과 자격증명 파일은 읽거나 쓰지 않습니다.
        if not self.runtime_grok_home.is_dir() or not self.workspace.is_dir():
            raise ValueError("기존 Grok 설정 폴더와 작업 폴더가 필요합니다.")
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

    def _require_start_consent(self, *, expected_scope=None):
        self.consent.require_start(expected_scope=str(self.state_root) if expected_scope is None else expected_scope,
                                   transport="headless")

    def set_consent(self, decision):
        # 동의 취소는 공급자 세션 ID와 저장된 대화·기존 프로세스를 지우지 않습니다.
        self.consent.set_decision(decision)

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
        self._require_start_consent()
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
