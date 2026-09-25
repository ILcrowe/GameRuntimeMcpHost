"""Long-lived Grok ACP transport with save-scoped conversation continuity."""

from __future__ import annotations

import json
import time
import shutil
from pathlib import Path
from urllib.parse import quote

from game_runtime_agent_session import JsonRpcStdioClient, extract_json_object, ProviderSessionDescriptor, AppendOnlyConversationStream, remaining_request_timeout
from game_runtime_grok_session import GrokHeadlessSession


class GrokPersistentSession(GrokHeadlessSession):
    """Keep one child process alive; retain the primary conversation across turns."""

    def __init__(self, *args, **kwargs):
        transport_root = kwargs.pop("transport_root", None)
        super().__init__(*args, **kwargs)
        if transport_root is not None:
            transport_root = Path(transport_root).resolve()
            self.workspace = transport_root / "grok-workspace"
            self.workspace.mkdir(parents=True, exist_ok=True)
            self.runtime_grok_home = transport_root / "grok-runtime-home"
        if "logger" not in kwargs:
            self.logger = lambda message: print(f"[Grok ACP] {message}", flush=True)
        self.rpc = None
        self.loaded_session_ids = set()
        self.session_model_options = {}
        self.last_requested_model = ""
        self.last_confirmed_model = ""
        self.request_deadline_unix_ms = None
        self.request_wait_check = None

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
        self.start()
        descriptor = ProviderSessionDescriptor(root / "provider_sessions.json")
        session_id = descriptor.read_id(self.provider_name)
        if session_id and session_id not in self.loaded_session_ids:
            self._migrate_saved_session(root, session_id)
            loaded = self.rpc.request("session/load", {"sessionId": session_id,
                "cwd": str(self.workspace), "mcpServers": []}, timeout=self._request_timeout(30))
            self._capture_model_options(session_id, loaded)
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
        if self.rpc is not None:
            self.rpc.close()
        self.utility_session_ids.clear()
        self.loaded_session_ids.clear()
        self.session_model_options.clear()
        command = [self.command, "--no-auto-update", "agent", "--no-leader"]
        if self.model:
            command.extend(["--model", self.model])
        command.append("stdio")
        self.rpc = JsonRpcStdioClient(
            command, cwd=self.workspace, env=self._prepare_runtime_environment(),
            include_jsonrpc=True, name="grok-acp",
        )
        try:
            self.rpc.start()
            init = self.rpc.request("initialize", {
                "protocolVersion": 1,
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
                "_meta": {"clientType": "storyllm-master", "clientVersion": "1",
                          "startupHints": {"nonInteractive": True, "skipGitStatus": True, "skipProjectLayout": True},
                          "systemPromptOverride": self.system_prompt},
            }, timeout=self._request_timeout(30))
            methods = {m.get("id") for m in init.get("authMethods", [])}
            if "cached_token" in methods:
                auth_method = "cached_token"
            elif "grok.com" in methods:
                # Grok CLI 1.0.13 exposes the current OAuth-backed method under this
                # ID. An already authenticated CLI completes it without a separate
                # game-owned credential, while an unauthenticated CLI reports the
                # login requirement below.
                auth_method = "grok.com"
            else:
                available = ", ".join(sorted(method for method in methods if method)) or "none"
                raise RuntimeError(f"Grok exposes no supported authentication method (available: {available}).")
            try:
                self.rpc.request("authenticate", {"methodId": auth_method, "_meta": {"headless": True}}, timeout=self._request_timeout(30))
            except TimeoutError:
                raise
            except Exception as exc:
                if auth_method == "grok.com":
                    raise RuntimeError(
                        "Grok CLI authentication is required or expired. "
                        "Sign in on this machine with `grok login --oauth` (or `grok login --device-auth`), "
                        "then reconnect from the game.") from exc
                raise
            if self.grok_session_id:
                self._migrate_saved_session(self.state_root, self.grok_session_id)
                # Never silently replace a saved story with an empty conversation.
                if not (init.get("agentCapabilities") or {}).get("loadSession"):
                    raise RuntimeError("Grok cannot restore the saved story session.")
                loaded = self.rpc.request("session/load", {"sessionId": self.grok_session_id,
                    "cwd": str(self.workspace), "mcpServers": []}, timeout=self._request_timeout(30))
                self._capture_model_options(self.grok_session_id, loaded)
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
        result = self.rpc.request("session/new", {"cwd": str(self.workspace), "mcpServers": []}, timeout=self._request_timeout(30))
        session_id = str(result.get("sessionId") or "")
        if not session_id:
            raise RuntimeError("Grok returned no session ID.")
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
            result = self.rpc.request("session/set_model", {
                "sessionId": session_id, "modelId": requested,
            }, timeout=self._request_timeout(30))
            model_result = (result.get("_meta") or {}).get("model") or {}
            if isinstance(model_result, dict) and model_result.get("Err"):
                raise RuntimeError("Grok model change failed: " + str(model_result["Err"]))
            reported = model_result.get("Ok") if isinstance(model_result, dict) else None
            self.session_model_options[session_id] = {**option, "currentValue": reported}
        else:
            result = self.rpc.request("session/set_config_option", {
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

    def _generate(self, prompt, output_schema, channel="", model=None):
        self.last_requested_model = str(model or self.model or "").strip()
        self.last_confirmed_model = ""
        self.start()
        if channel and channel not in self.utility_session_ids:
            self.utility_session_ids[channel] = self._new_session()
        session_id = self.utility_session_ids[channel] if channel else self.grok_session_id
        self._apply_model(session_id, model)
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
            result = self.rpc.request("session/prompt", {"sessionId": session_id,
                # The game already selects bounded context. ACP's default large-input
                # offload can drop its middle when this client cannot write/read files.
                "_meta": {"verbatim": True},
                "prompt": [{"type": "text", "text": prompt + "\nReturn only a JSON object matching this schema:\n" + json.dumps(output_schema, ensure_ascii=False)}]},
                timeout=self._request_timeout(self.timeout_seconds), notification_handler=receive,
                wait_check=self.request_wait_check)
            if result.get("stopReason") != "end_turn":
                raise RuntimeError(f"Grok did not complete its response: {result.get('stopReason')}")
            generated = extract_json_object("".join(chunks))
        except Exception:
            # Cancel before accepting another request on a potentially active turn.
            try:
                self.rpc.notify("session/cancel", {"sessionId": session_id})
            finally:
                self.rpc.close()
                self.rpc = None
            raise
        elapsed = round(time.monotonic() - started, 3)
        self.memory_stream.append("utility-turn" if channel else "turn", provider="grok", session_id=session_id,
            payload={"user": prompt, "assistant": generated, "channel": channel, "elapsedSeconds": elapsed})
        self.logger(f"Grok response received · {elapsed}s · session={session_id}")
        return generated

    def generate(self, prompt, *, output_schema, **kwargs):
        return self._generate(prompt, output_schema, model=kwargs.get("model"))

    def generate_utility(self, channel, prompt, *, output_schema, **kwargs):
        return self._generate(prompt, output_schema, channel or "utility", model=kwargs.get("model"))

    def close(self):
        if self.rpc is not None:
            self.rpc.close()
            self.rpc = None
        super().close()
