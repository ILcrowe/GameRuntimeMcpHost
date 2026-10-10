"""Long-lived Grok ACP transport with save-scoped conversation continuity."""

from __future__ import annotations

import json
import time
import shutil
import hashlib
import os
import subprocess
from pathlib import Path
from urllib.parse import quote

from game_runtime_agent_session import JsonRpcStdioClient, extract_json_object, ProviderSessionDescriptor, AppendOnlyConversationStream, remaining_request_timeout
from game_runtime_grok_session import (GrokHeadlessSession, GrokConsentDenied,
    story_runtime_profile, story_runtime_environment, verify_story_runtime_inventory)


class GrokPersistentSession(GrokHeadlessSession):
    """Keep one child process alive; retain the primary conversation across turns."""

    def __init__(self, *args, **kwargs):
        transport_root = kwargs.pop("transport_root", None)
        super().__init__(*args, **kwargs)
        if transport_root is not None and kwargs.get("workspace") is None:
            transport_root = Path(transport_root).resolve()
            self.workspace = transport_root / "grok-workspace"
            self.workspace.mkdir(parents=True, exist_ok=True)
            self.legacy_runtime_grok_home = transport_root / "grok-runtime-home"
        if "logger" not in kwargs:
            self.logger = lambda message: print(f"[Grok ACP] {message}", flush=True)
        self.rpc = None
        self.loaded_session_ids = set()
        self.session_model_options = {}
        self.last_requested_model = ""
        self.last_confirmed_model = ""
        self.last_confirmed_reasoning_effort = ""
        self.request_deadline_unix_ms = None
        self.request_wait_check = None
        self._active_prompt_session = None
        self.runtime_profile = story_runtime_profile(self.system_prompt)
        self.profile_path = self.workspace / "story-runtime-agent.md"
        self.private_user_home = self.workspace / "story-user-home"
        self.runtime_inventory = None
        self.native_profile_evidence = {}

    def _prepare_runtime_environment(self):
        self.consent.require_setup(expected_scope=str(self.state_root))
        return story_runtime_environment(self.runtime_grok_home, self.private_user_home)

    def prepare_runtime_profile(self):
        self.consent.require_setup(expected_scope=str(self.state_root))
        if not self.runtime_grok_home.is_dir() or not self.workspace.is_dir():
            raise ValueError("기존 Grok 인증 폴더와 게임 전용 작업 폴더가 필요합니다.")
        allowed = {self.profile_path.name, self.private_user_home.name}
        if any(entry.name not in allowed or entry.is_symlink() for entry in self.workspace.iterdir()):
            raise ValueError("Grok 작업 폴더에는 전용 실행 설정 외의 파일을 넣을 수 없습니다.")
        self.private_user_home.mkdir(exist_ok=True)
        profile = self.runtime_profile
        text = "---\n" + "\n".join(f"{key}: {json.dumps(value)}" for key, value in profile.items()
                                     if key != "promptBody") + "\n---\n" + profile["promptBody"] + "\n"
        if self.profile_path.exists() and self.profile_path.read_text(encoding="utf-8") != text:
            raise ValueError("Grok 전용 에이전트 설정이 변경됐습니다. 새 연결 전에 확인하세요.")
        if not self.profile_path.exists():
            self.profile_path.write_text(text, encoding="utf-8")
        completed = subprocess.run([self.command, "--no-auto-update", "--cwd", str(self.workspace), "inspect", "--json"],
            cwd=self.workspace, env=self._prepare_runtime_environment(), capture_output=True,
            text=True, encoding="utf-8", timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if completed.returncode:
            raise RuntimeError("Grok 전용 실행 설정 점검에 실패했습니다. 진단 원문은 내보내지 않았습니다.")
        try:
            inventory = verify_story_runtime_inventory(json.loads(completed.stdout))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Grok 점검 결과를 해석하지 못했습니다.") from exc
        self.consent.bind_runtime_profile(self.state_root, hashlib.sha256(text.encode("utf-8")).hexdigest())
        self.runtime_inventory = inventory
        return {**inventory, "runtimeSkillDiscoveryEnabled": False, "runtimeDefaultToolsInjected": False,
                "runtimeLocalToolCount": 0, "profileSha256": self.consent.runtime_profile_digest,
                "osSandboxVerified": False, "automaticCredentialCopy": False, "authenticationRequests": 0}

    def _verify_native_profile(self, session_id, *, require_tools=False):
        # Inspect only this approved native conversation, never auth.json or
        # another provider session. Unsupported/ignored profile fields fail closed.
        if not session_id or Path(session_id).name != session_id:
            raise RuntimeError("Grok 대화 ID를 확인할 수 없습니다.")
        folder = self.runtime_grok_home / "sessions" / quote(str(self.workspace), safe="") / session_id
        try:
            tool_path = folder / "tool_definitions.json"
            # Grok writes this artifact only when sampling. A fresh session has
            # its native profile and prompt already, but no tool artifact yet.
            tools = json.loads(tool_path.read_text(encoding="utf-8")) if tool_path.exists() else None
            if require_tools and tools is None:
                raise ValueError("Grok did not persist its sampled tool definitions.")
            prompt = (folder / "system_prompt.txt").read_text(encoding="utf-8").strip()
            summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError("Grok의 실제 대화 실행 설정을 확인하지 못했습니다. 요청을 중단했습니다.") from exc
        profiles = []
        def collect(value):
            if isinstance(value, dict):
                if value.get("name") == "storyllm-runtime" and "discoverSkills" in value:
                    profiles.append(value)
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
        collect(summary)
        if (tools is not None and (not isinstance(tools, list) or tools)) or prompt != self.system_prompt or len(profiles) != 1:
            raise RuntimeError("Grok의 실제 도구·지시 제한이 적용되지 않았습니다. 모델 요청을 차단했습니다.")
        profile = profiles[0]
        if any(profile.get(key) is not False for key in ("discoverSkills", "inheritSkills", "agentsMd", "injectDefaultTools")):
            raise RuntimeError("Grok의 실제 스킬 제한이 적용되지 않았습니다. 모델 요청을 차단했습니다.")
        expected = self.runtime_profile
        exact_keys = ("skills", "promptMode", "promptBody", "mcpServers", "mcpInheritance", "maxTurns", "disallowedTools")
        configured_tools = (profile.get("toolConfig") or {}).get("tools")
        if (any(profile.get(key) != expected[key] for key in exact_keys)
            or not isinstance(configured_tools, list) or len(configured_tools) != 1
            or configured_tools[0].get("id") != "GrokBuild:read_file"
            or any(value is not None for key, value in configured_tools[0].items() if key != "id")):
            raise RuntimeError("Grok의 실제 도구 제한 설정이 적용되지 않았습니다. 모델 요청을 차단했습니다.")
        self.native_profile_evidence[session_id] = {"nativeToolDefinitionCount": 0 if tools is not None else None,
            "sampledToolDefinitionsVerified": tools is not None,
            "nativeSkillDiscoveryEnabled": False, "nativePromptMatches": True}

    def _require_start_consent(self, *, expected_scope=None):
        self.consent.require_start(expected_scope=str(self.state_root) if expected_scope is None else expected_scope,
                                   transport="acp")

    def _rpc_request(self, method, params=None, **kwargs):
        if method == "authenticate":
            raise PermissionError("이 전송기는 인증을 자동으로 요청하지 않습니다.")
        self._require_start_consent()
        if method == "session/prompt":
            self._verify_native_profile((params or {}).get("sessionId"))
        previous_check = kwargs.get("wait_check")

        def check_consent():
            self._require_start_consent()
            if previous_check is not None:
                previous_check()

        kwargs["wait_check"] = check_consent
        result = self.rpc.request(method, params, **kwargs)
        if method == "session/prompt":
            self._verify_native_profile((params or {}).get("sessionId"), require_tools=True)
        return result

    def _request_timeout(self, maximum):
        return remaining_request_timeout(self.request_deadline_unix_ms, maximum)

    def _migrate_saved_session(self, scope_root, session_id):
        """Copy only the selected legacy conversation; never overwrite a newer copy."""
        if not session_id or Path(session_id).name != session_id or "/" in session_id or "\\" in session_id:
            raise RuntimeError("Invalid saved Grok session ID.")
        destination = self.runtime_grok_home / "sessions" / quote(str(self.workspace), safe="") / session_id
        if destination.exists():
            return
        legacy = Path(scope_root) / "grok-runtime-home" / "sessions"
        matches = [p for p in legacy.glob(f"*/{session_id}") if p.is_dir()] if legacy.exists() else []
        if len(matches) > 1:
            raise RuntimeError("Multiple legacy copies of the saved Grok session exist.")
        if matches:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(matches[0], destination)
            self.logger(f"Preserved legacy conversation in shared runtime home: {session_id}")

    def switch_scope(self, scope_root):
        """Select another story without terminating the connected ACP process."""
        root = Path(scope_root).resolve()
        if root == self.state_root:
            return
        self.consent.require_setup(expected_scope=str(root))
        self.start()
        self._require_start_consent(expected_scope=str(root))
        descriptor = ProviderSessionDescriptor(root / "provider_sessions.json")
        session_id = descriptor.read_id(self.provider_name)
        if session_id and session_id not in self.loaded_session_ids:
            self._migrate_saved_session(root, session_id)
            loaded = self._rpc_request("session/load", {"sessionId": session_id,
                "cwd": str(self.workspace), "mcpServers": [], "_meta": {"agentProfile": self.runtime_profile}}, timeout=self._request_timeout(30))
            self._capture_model_options(session_id, loaded)
            self._verify_native_profile(session_id)
        if not session_id:
            session_id = self._new_session()
            descriptor.write_id(self.provider_name, session_id)
        stream = AppendOnlyConversationStream(root / "memory-stream" / "external-gm.jsonl")
        self.memory_stream.close()
        self.memory_stream = stream
        self.state_root = root
        self.descriptor = descriptor
        self.grok_session_id = session_id
        self.loaded_session_ids.add(session_id)
        self.utility_session_ids.clear()
        self.logger(f"Story selected pid={self.rpc.process.pid} session={session_id}")

    def start(self):
        if self.rpc is not None and self.rpc.is_running:
            return
        self.prepare_runtime_profile()
        self._require_start_consent()
        if self.rpc is not None:
            self.rpc.close()
        self.utility_session_ids.clear()
        self.loaded_session_ids.clear()
        self.session_model_options.clear()
        command = [self.command, "--no-auto-update", "--disable-web-search", "agent", "--no-leader", "--agent-profile", str(self.profile_path)]
        if self.model:
            command.extend(["--model", self.model])
        command.append("stdio")
        self.rpc = JsonRpcStdioClient(
            command, cwd=self.workspace, env=self._prepare_runtime_environment(),
            include_jsonrpc=True, name="grok-acp",
        )
        try:
            self.rpc.start()
            init = self._rpc_request("initialize", {
                "protocolVersion": 1,
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
                "_meta": {"clientType": "storyllm-master", "clientVersion": "1",
                          "startupHints": {"nonInteractive": True, "skipGitStatus": True, "skipProjectLayout": True},
                          "systemPromptOverride": self.system_prompt},
            }, timeout=self._request_timeout(30))
            # authMethods 광고만으로 인증을 요청하지 않습니다. 이 단계의 자동 authenticate는 제거됐습니다.
            if self.grok_session_id:
                self._migrate_saved_session(self.state_root, self.grok_session_id)
                # Never silently replace a saved story with an empty conversation.
                if not (init.get("agentCapabilities") or {}).get("loadSession"):
                    raise RuntimeError("Grok cannot restore the saved story session.")
                loaded = self._rpc_request("session/load", {"sessionId": self.grok_session_id,
                    "cwd": str(self.workspace), "mcpServers": [], "_meta": {"agentProfile": self.runtime_profile}}, timeout=self._request_timeout(30))
                self._capture_model_options(self.grok_session_id, loaded)
                self._verify_native_profile(self.grok_session_id)
            else:
                self.grok_session_id = self._new_session()
                self.descriptor.write_id(self.provider_name, self.grok_session_id)
            self.logger(f"ACP ready pid={self.rpc.process.pid} session={self.grok_session_id}")
            self.loaded_session_ids.add(self.grok_session_id)
        except Exception:
            self.rpc.close()
            self.rpc = None
            raise

    def _new_session(self):
        result = self._rpc_request("session/new", {"cwd": str(self.workspace), "mcpServers": [],
            "_meta": {"agentProfile": self.runtime_profile}}, timeout=self._request_timeout(30))
        session_id = str(result.get("sessionId") or "")
        if not session_id:
            raise RuntimeError("Grok returned no session ID.")
        self._verify_native_profile(session_id)
        self._capture_model_options(session_id, result)
        return session_id

    def _capture_model_options(self, session_id, result):
        legacy = result.get("models")
        if "configOptions" not in result and isinstance(legacy, dict):
            self.session_model_options[session_id] = {
                "id": "model", "currentValue": legacy.get("currentModelId"),
                "transport": "session/set_model",
            }
            return
        if "configOptions" not in result:
            # Missing confirmation is not a capability revocation. Retain the
            # advertised selector, but discard its now potentially stale value.
            previous = self.session_model_options.get(session_id)
            if previous is not None:
                self.session_model_options[session_id] = {**previous, "currentValue": None}
            return
        self.session_model_options[session_id] = next(
            (option for option in (result.get("configOptions") or [])
             if option.get("id") == "model" or option.get("category") == "model"), None)

    def _apply_model(self, session_id, model):
        requested = str(model or self.model or "").strip()
        self.last_requested_model = requested
        option = self.session_model_options.get(session_id)
        current = (option or {}).get("currentValue")
        if isinstance(current, dict):
            current = current.get("value")
        self.last_confirmed_model = current if isinstance(current, str) else ""
        if not requested or requested == self.last_confirmed_model:
            return
        # A cached session model is not confirmation of this change request.
        self.last_confirmed_model = ""
        if not option:
            raise RuntimeError("Grok does not advertise in-session model selection. Update Grok Build or select provider default; the saved conversation was preserved.")
        # Do not allow-list locally: the provider validates newly released/custom IDs.
        if option.get("transport") == "session/set_model":
            result = self._rpc_request("session/set_model", {
                "sessionId": session_id, "modelId": requested,
            }, timeout=self._request_timeout(30))
            model_result = (result.get("_meta") or {}).get("model") or {}
            if isinstance(model_result, dict) and model_result.get("Err"):
                raise RuntimeError("Grok model change failed: " + str(model_result["Err"]))
            reported = model_result.get("Ok") if isinstance(model_result, dict) else None
            self.session_model_options[session_id] = {**option, "currentValue": reported}
        else:
            result = self._rpc_request("session/set_config_option", {
                "sessionId": session_id, "configId": option.get("id") or "model",
                "value": {"value": requested},
            }, timeout=self._request_timeout(30))
            self._capture_model_options(session_id, result)
        confirmed = (self.session_model_options.get(session_id) or {}).get("currentValue")
        if isinstance(confirmed, dict):
            confirmed = confirmed.get("value")
        self.last_confirmed_model = confirmed if isinstance(confirmed, str) else ""
        if self.last_confirmed_model and self.last_confirmed_model != requested:
            raise RuntimeError(f"Grok model mismatch: requested {requested}, reported {self.last_confirmed_model}.")

    def _apply_reasoning_effort(self, session_id, effort):
        self.last_confirmed_reasoning_effort = ""
        requested = str(effort or self.reasoning_effort or "").strip()
        if not requested:
            return

        def read_settings():
            loaded = self._rpc_request("session/load", {
                "sessionId": session_id, "cwd": str(self.workspace), "mcpServers": [],
            }, timeout=self._request_timeout(30))
            models = loaded.get("models") or {}
            current = models.get("currentModelId")
            meta = next((m.get("_meta") or {} for m in models.get("availableModels", [])
                         if m.get("modelId") == current), {})
            return current, meta

        current, meta = read_settings()
        if requested == "default":
            requested = next((item.get("value") for item in meta.get("reasoningEfforts", [])
                              if item.get("default") is True), "")
        supported = {item.get("value") for item in meta.get("reasoningEfforts", [])}
        if not current or not meta.get("supportsReasoningEffort") or requested not in supported:
            raise RuntimeError("Grok does not advertise the requested reasoning effort for this session.")
        if meta.get("reasoningEffort") != requested:
            result = self._rpc_request("session/set_model", {
                "sessionId": session_id, "modelId": current,
                "_meta": {"reasoningEffort": requested},
            }, timeout=self._request_timeout(30))
            error = ((result.get("_meta") or {}).get("model") or {}).get("Err")
            if error:
                raise RuntimeError("Grok reasoning effort change failed: " + str(error))
            confirmed_model, meta = read_settings()
            if confirmed_model != current or meta.get("reasoningEffort") != requested:
                raise RuntimeError("Grok did not confirm the requested model and reasoning effort.")
        self.last_confirmed_reasoning_effort = requested

    def _generate(self, prompt, output_schema, channel="", model=None, reasoning_effort=None):
        self.consent.require_setup(expected_scope=str(self.state_root))
        self.last_requested_model = str(model or self.model or "").strip()
        self.last_confirmed_model = ""
        self.last_confirmed_reasoning_effort = ""
        self.start()
        self._require_start_consent()
        if channel and channel not in self.utility_session_ids:
            self.utility_session_ids[channel] = self._new_session()
        session_id = self.utility_session_ids[channel] if channel else self.grok_session_id
        self._apply_model(session_id, model)
        self._apply_reasoning_effort(session_id, reasoning_effort)
        chunks = []

        def receive(message):
            params = message.get("params") or {}
            if message.get("method") != "session/update" or params.get("sessionId") != session_id:
                return
            update = params.get("update") or {}
            if update.get("sessionUpdate") == "agent_message_chunk":
                content = update.get("content") or {}
                if content.get("text"):
                    chunks.append(content["text"])

        started = time.monotonic()
        self.logger(f"ACP request pid={self.rpc.process.pid} session={session_id} channel={channel or 'story'}")
        try:
            self._active_prompt_session = session_id
            result = self._rpc_request("session/prompt", {"sessionId": session_id,
                # The game already selects bounded context. ACP's default large-input
                # offload can drop its middle when this client cannot write/read files.
                "_meta": {"verbatim": True},
                "prompt": [{"type": "text", "text": prompt + "\nReturn only a JSON object matching this schema:\n" + json.dumps(output_schema, ensure_ascii=False)}]},
                timeout=self._request_timeout(self.timeout_seconds), notification_handler=receive,
                wait_check=self.request_wait_check)
            if result.get("stopReason") != "end_turn":
                raise RuntimeError(f"Grok did not complete its response: {result.get('stopReason')}")
            generated = extract_json_object("".join(chunks))
        except GrokConsentDenied:
            # 취소된 새 요청은 수락하지 않으며 기존 프로세스와 공급자 세션 기록은 보존합니다.
            if self._active_prompt_session is not None:
                self.rpc.notify("session/cancel", {"sessionId": self._active_prompt_session})
            raise
        except Exception:
            # Cancel before accepting another request on a potentially active turn.
            try:
                self.rpc.notify("session/cancel", {"sessionId": session_id})
            finally:
                self.rpc.close()
                self.rpc = None
            raise
        finally:
            self._active_prompt_session = None
        elapsed = round(time.monotonic() - started, 3)
        self.memory_stream.append("utility-turn" if channel else "turn", provider="grok", session_id=session_id,
            payload={"user": prompt, "assistant": generated, "channel": channel, "elapsedSeconds": elapsed})
        self.logger(f"Grok response received · {elapsed}s · session={session_id}")
        return generated

    def generate(self, prompt, *, output_schema, **kwargs):
        return self._generate(prompt, output_schema, model=kwargs.get("model"),
                              reasoning_effort=kwargs.get("reasoning_effort"))

    def generate_utility(self, channel, prompt, *, output_schema, **kwargs):
        return self._generate(prompt, output_schema, channel or "utility", model=kwargs.get("model"),
                              reasoning_effort=kwargs.get("reasoning_effort"))

    def close(self):
        if self.rpc is not None:
            self.rpc.close()
            self.rpc = None
        super().close()
