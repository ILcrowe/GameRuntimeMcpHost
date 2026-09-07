"""Long-lived Grok ACP transport with save-scoped conversation continuity."""

from __future__ import annotations

import json
import time
import shutil
from pathlib import Path
from urllib.parse import quote

from game_runtime_agent_session import JsonRpcStdioClient, extract_json_object, ProviderSessionDescriptor, AppendOnlyConversationStream
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
            self.rpc.request("session/load", {"sessionId": session_id,
                "cwd": str(self.workspace), "mcpServers": []}, timeout=30)
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
            }, timeout=30)
            methods = {m.get("id") for m in init.get("authMethods", [])}
            if "cached_token" not in methods:
                raise RuntimeError("Grok cached-token authentication unavailable; login is required.")
            self.rpc.request("authenticate", {"methodId": "cached_token", "_meta": {"headless": True}}, timeout=30)
            if self.grok_session_id:
                self._migrate_saved_session(self.state_root, self.grok_session_id)
                # Never silently replace a saved story with an empty conversation.
                if not (init.get("agentCapabilities") or {}).get("loadSession"):
                    raise RuntimeError("Grok cannot restore the saved story session.")
                self.rpc.request("session/load", {"sessionId": self.grok_session_id,
                    "cwd": str(self.workspace), "mcpServers": []}, timeout=30)
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
        result = self.rpc.request("session/new", {"cwd": str(self.workspace), "mcpServers": []}, timeout=30)
        session_id = str(result.get("sessionId") or "")
        if not session_id:
            raise RuntimeError("Grok returned no session ID.")
        return session_id

    def _generate(self, prompt, output_schema, channel=""):
        self.start()
        if channel and channel not in self.utility_session_ids:
            self.utility_session_ids[channel] = self._new_session()
        session_id = self.utility_session_ids[channel] if channel else self.grok_session_id
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
                "prompt": [{"type": "text", "text": prompt + "\nReturn only a JSON object matching this schema:\n" + json.dumps(output_schema, ensure_ascii=False)}]},
                timeout=self.timeout_seconds, notification_handler=receive)
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
        return self._generate(prompt, output_schema)

    def generate_utility(self, channel, prompt, *, output_schema, **kwargs):
        return self._generate(prompt, output_schema, channel or "utility")

    def close(self):
        if self.rpc is not None:
            self.rpc.close()
            self.rpc = None
        super().close()
