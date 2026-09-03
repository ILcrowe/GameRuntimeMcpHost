from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import game_runtime_codex_session as module


class FakeRpc:
    instances = []

    def __init__(self, *args, **kwargs):
        self.calls = []
        self.is_running = False
        self.turn_index = 0
        self.thread_start_index = 0
        self.instances.append(self)

    def start(self):
        self.is_running = True

    def close(self):
        self.is_running = False

    def notify(self, method, params=None):
        self.calls.append((method, params))

    def request(self, method, params=None, timeout=30, notification_handler=None):
        self.calls.append((method, params))
        if method == "initialize":
            return {}
        if method == "thread/start":
            self.thread_start_index += 1
            thread_id = (
                "thr-current"
                if self.thread_start_index == 1
                else f"thr-utility-{self.thread_start_index}"
            )
            return {"thread": {"id": thread_id}}
        if method == "thread/resume":
            return {"thread": {"id": params["threadId"]}}
        if method == "turn/start":
            self.turn_index += 1
            return {"turn": {"id": f"turn-{self.turn_index}"}}
        raise AssertionError(method)

    def wait_for_notification(self, predicate, timeout, notification_handler=None):
        turn_id = f"turn-{self.turn_index}"
        response = {
            "narration": f"response {self.turn_index}",
            "firstTurn": {
                "spokenText": "",
                "innerMonologueText": "",
                "actionProposal": "",
                "presentation": {
                    "textStyleKey": "",
                    "sfxCueKey": "",
                    "expressionKey": "",
                },
            },
            "followupTurn": {
                "spokenText": "",
                "innerMonologueText": "",
                "actionProposal": "",
                "presentation": {
                    "textStyleKey": "",
                    "sfxCueKey": "",
                    "expressionKey": "",
                },
            },
            "suggestedActions": [],
        }
        if notification_handler:
            notification_handler(
                {
                    "method": "item/completed",
                    "params": {
                        "item": {
                            "type": "agentMessage",
                            "text": json.dumps(response),
                        }
                    },
                }
            )
        message = {
            "method": "turn/completed",
            "params": {"turn": {"id": turn_id, "status": "completed"}},
        }
        if not predicate(message):
            raise AssertionError("completion predicate rejected fake turn")
        return message


class CodexPersistentSessionTests(unittest.TestCase):
    def test_two_primary_turns_reuse_one_thread(self):
        FakeRpc.instances.clear()
        with tempfile.TemporaryDirectory() as temp, patch.object(
            module, "JsonRpcStdioClient", FakeRpc
        ):
            session = module.CodexPersistentSession(
                Path(temp), command="codex", timeout_seconds=30
            )
            schema = {"type": "object"}
            session.generate(
                "first",
                output_schema=schema,
                model="gpt-test",
                reasoning_effort="low",
            )
            session.generate(
                "second",
                output_schema=schema,
                model="gpt-test",
                reasoning_effort="low",
            )

            rpc = FakeRpc.instances[0]
            starts = [params for method, params in rpc.calls if method == "thread/start"]
            turns = [params for method, params in rpc.calls if method == "turn/start"]
            self.assertEqual(len(starts), 1)
            self.assertEqual(len(turns), 2)
            self.assertEqual(starts[0]["sandbox"], "read-only")
            self.assertEqual({turn["threadId"] for turn in turns}, {"thr-current"})
            self.assertEqual(turns[0]["sandboxPolicy"]["type"], "readOnly")
            self.assertFalse(turns[0]["sandboxPolicy"]["networkAccess"])
            self.assertIs(turns[0]["outputSchema"], schema)
            session.close()

    def test_utility_turn_uses_separate_thread(self):
        FakeRpc.instances.clear()
        with tempfile.TemporaryDirectory() as temp, patch.object(
            module, "JsonRpcStdioClient", FakeRpc
        ):
            session = module.CodexPersistentSession(
                Path(temp), command="codex", timeout_seconds=30
            )
            schema = {"type": "object"}
            session.generate(
                "primary-1",
                output_schema=schema,
                model="gpt-test",
                reasoning_effort="low",
            )
            primary_id = session.session_id
            session.generate_utility(
                "action-interpreter",
                "utility",
                output_schema=schema,
                model="gpt-test",
                reasoning_effort="low",
            )
            session.generate(
                "primary-2",
                output_schema=schema,
                model="gpt-test",
                reasoning_effort="low",
            )

            rpc = FakeRpc.instances[0]
            turns = [params for method, params in rpc.calls if method == "turn/start"]
            self.assertEqual(
                [turn["threadId"] for turn in turns],
                ["thr-current", "thr-utility-2", "thr-current"],
            )
            self.assertEqual(session.session_id, primary_id)
            self.assertEqual(session.descriptor.read_id("codex"), primary_id)
            session.close()

    def test_process_restart_resumes_stored_thread(self):
        FakeRpc.instances.clear()
        with tempfile.TemporaryDirectory() as temp, patch.object(
            module, "JsonRpcStdioClient", FakeRpc
        ):
            root = Path(temp)
            descriptor = module.ProviderSessionDescriptor(root / "provider_sessions.json")
            descriptor.write_id("codex", "thr-existing")
            session = module.CodexPersistentSession(
                root, command="codex", timeout_seconds=30
            )
            session.generate(
                "continue",
                output_schema={"type": "object"},
                model="gpt-test",
                reasoning_effort="low",
            )

            rpc = FakeRpc.instances[0]
            methods = [method for method, _ in rpc.calls]
            self.assertEqual(methods.count("thread/resume"), 1)
            self.assertEqual(methods.count("thread/start"), 0)
            turn = next(params for method, params in rpc.calls if method == "turn/start")
            self.assertEqual(turn["threadId"], "thr-existing")
            session.close()


if __name__ == "__main__":
    unittest.main()
