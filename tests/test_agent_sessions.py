from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from game_runtime_agent_session import JsonRpcStdioClient, ProviderSessionDescriptor
from game_runtime_grok_session import GrokHeadlessSession


class _CapturingRpcClient(JsonRpcStdioClient):
    def __init__(self):
        super().__init__(["fake"], include_jsonrpc=True, name="test-rpc")
        self.writes = []

    def _write(self, payload):
        self.writes.append(payload)


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _QueueRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class AgentSessionPrimitiveTests(unittest.TestCase):
    def test_acp_permission_request_is_rejected(self):
        client = _CapturingRpcClient()
        client._handle_unsolicited(
            {
                "jsonrpc": "2.0",
                "id": 44,
                "method": "session/request_permission",
                "params": {
                    "options": [
                        {"optionId": "allow", "kind": "allow_once"},
                        {"optionId": "reject", "kind": "reject_once"},
                    ]
                },
            },
            None,
        )
        self.assertEqual(client.writes[0]["result"]["outcome"]["optionId"], "reject")

    def test_provider_descriptor_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            descriptor = ProviderSessionDescriptor(Path(temp) / "provider_sessions.json")
            descriptor.write_id("grok", "session-a")
            self.assertEqual(descriptor.read_id("grok"), "session-a")


class GrokHeadlessSessionTests(unittest.TestCase):
    schema = {
        "type": "object",
        "properties": {"narration": {"type": "string"}},
        "required": ["narration"],
        "additionalProperties": False,
    }

    @staticmethod
    def _success(session_id, narration):
        return _Completed(
            stdout=json.dumps(
                {
                    "text": json.dumps({"narration": narration}),
                    "structuredOutput": {"narration": narration},
                    "stopReason": "end_turn",
                    "sessionId": session_id,
                    "requestId": "request-1",
                },
                ensure_ascii=False,
            )
        )

    def test_primary_session_is_persisted_and_resumed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_home = root / "source-grok"
            source_home.mkdir()
            (source_home / "auth.json").write_text("{}", encoding="utf-8")
            runner = _QueueRunner(
                [
                    self._success("session-a", "first"),
                    self._success("session-a", "second"),
                ]
            )
            session = GrokHeadlessSession(
                root / "state",
                command="grok",
                source_grok_home=source_home,
                process_runner=runner,
                logger=lambda _: None,
            )

            try:
                self.assertEqual(
                    session.generate("one", output_schema=self.schema)["narration"],
                    "first",
                )
                self.assertEqual(
                    session.generate("two", output_schema=self.schema)["narration"],
                    "second",
                )

                first_command = runner.calls[0][0]
                second_command = runner.calls[1][0]
                self.assertNotIn("--resume", first_command)
                self.assertIn("--resume", second_command)
                resume_index = second_command.index("--resume")
                self.assertEqual(second_command[resume_index + 1], "session-a")
                self.assertIn("--json-schema", first_command)
                self.assertEqual(
                    ProviderSessionDescriptor(
                        root / "state" / "provider_sessions.json"
                    ).read_id("grok"),
                    "session-a",
                )
                child_env = runner.calls[0][1]["env"]
                self.assertEqual(
                    Path(child_env["GROK_HOME"]).resolve(),
                    (root / "state" / "grok-runtime-home").resolve(),
                )
                self.assertTrue(
                    (root / "state" / "grok-runtime-home" / "auth.json").exists()
                )
            finally:
                session.close()

    def test_missing_resumed_session_retries_as_new(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / "state"
            ProviderSessionDescriptor(state / "provider_sessions.json").write_id(
                "grok", "missing-session"
            )
            runner = _QueueRunner(
                [
                    _Completed(
                        returncode=1,
                        stdout=json.dumps(
                            {
                                "type": "error",
                                "message": "Couldn't start session: Path not found.",
                            }
                        ),
                    ),
                    self._success("replacement-session", "recovered"),
                ]
            )
            session = GrokHeadlessSession(
                state,
                command="grok",
                source_grok_home=root / "source-grok",
                process_runner=runner,
                logger=lambda _: None,
            )

            try:
                result = session.generate("recover", output_schema=self.schema)
                self.assertEqual(result["narration"], "recovered")
                self.assertIn("--resume", runner.calls[0][0])
                self.assertNotIn("--resume", runner.calls[1][0])
                self.assertEqual(session.session_id, "replacement-session")
            finally:
                session.close()

    def test_utility_channel_does_not_replace_primary_descriptor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner = _QueueRunner(
                [
                    self._success("primary", "main"),
                    self._success("utility", "diag"),
                ]
            )
            session = GrokHeadlessSession(
                root / "state",
                command="grok",
                source_grok_home=root / "source-grok",
                process_runner=runner,
                logger=lambda _: None,
            )

            try:
                session.generate("main", output_schema=self.schema)
                session.generate_utility("settings", "diag", output_schema=self.schema)
                self.assertEqual(session.session_id, "primary")
                self.assertEqual(
                    ProviderSessionDescriptor(
                        root / "state" / "provider_sessions.json"
                    ).read_id("grok"),
                    "primary",
                )
            finally:
                session.close()


if __name__ == "__main__":
    unittest.main()
