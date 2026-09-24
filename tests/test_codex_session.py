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
    def test_public_observer_excludes_utility_and_cannot_break_generation(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(module, "JsonRpcStdioClient", FakeRpc):
            session = module.CodexPersistentSession(Path(temp), command="codex")
            seen = []
            session.on_primary_text = seen.append
            args = dict(output_schema={"type": "object"}, model="gpt-test", reasoning_effort="low")
            session.generate("story", **args)
            self.assertEqual(len(seen), 1)
            self.assertEqual(json.loads(seen[0])["narration"], "response 1")
            session.generate_utility("action-interpreter", "check", **args)
            self.assertEqual(len(seen), 1)
            def broken_display(text):
                raise RuntimeError("display unavailable")
            session.on_primary_text = broken_display
            self.assertEqual(session.generate("story again", **args)["narration"], "response 3")
            session.close()

    def test_optional_inference_profile_applies_to_resume_and_utility_without_changing_defaults(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(module, "JsonRpcStdioClient", FakeRpc):
            original = {"skills.include_instructions": False, "model_reasoning_effort": "high"}
            session = module.CodexPersistentSession(Path(temp), command="codex",
                base_instructions="Game narrator", thread_config=original)
            original["skills.include_instructions"] = True
            session.descriptor.write_id("codex", "thr-saved-story")
            session.start("model", "low")
            session._get_utility_thread("action-interpreter", model="model", reasoning_effort="low")
            starts = [(method, params) for method, params in session.rpc.calls
                      if method in ("thread/resume", "thread/start")]
            self.assertEqual([method for method, _ in starts], ["thread/resume", "thread/start"])
            self.assertEqual(starts[0][1]["threadId"], "thr-saved-story")
            for _, params in starts:
                self.assertEqual(params["baseInstructions"], "Game narrator")
                self.assertFalse(params["config"]["skills.include_instructions"])
                self.assertEqual(params["config"]["model_reasoning_effort"], "low")
                self.assertEqual(params["sandbox"], "read-only")
            session.close()
            default = module.CodexPersistentSession(Path(temp)/"default", command="codex")
            params = default._common_thread_params("model", "low")
            self.assertNotIn("baseInstructions", params)
            self.assertEqual(params["config"], {"model_reasoning_effort": "low"})
            default.close()

    def test_failed_resume_preserves_story_and_retry_uses_same_id(self):
        for error in (
            module.RpcError("thread/resume", {"code": -32602, "message": "model unavailable"}),
            TimeoutError("resume timed out"),
            RuntimeError("connection closed"),
        ):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as temp, patch.object(
                module, "JsonRpcStdioClient", FakeRpc
            ):
                session = module.CodexPersistentSession(Path(temp), command="codex")
                session.descriptor.write_id("codex", "thr-saved-story")
                original = FakeRpc.request
                def reject_resume(rpc, method, *args, **kwargs):
                    if method == "thread/resume":
                        rpc.calls.append((method, args[0] if args else None))
                        raise error
                    return original(rpc, method, *args, **kwargs)
                with patch.object(FakeRpc, "request", reject_resume):
                    with self.assertRaises(type(error)):
                        session.start("invalid-model", "low")
                failed_rpc = FakeRpc.instances[-1]
                self.assertNotIn("thread/start", [method for method, _ in failed_rpc.calls])
                self.assertFalse(failed_rpc.is_running)
                self.assertIsNone(session.rpc)
                self.assertEqual(session.session_id, "")
                self.assertEqual(session.descriptor.read_id("codex"), "thr-saved-story")
                session.generate("retry", output_schema={}, model="valid-model", reasoning_effort="low")
                self.assertEqual(session.session_id, "thr-saved-story")
                self.assertNotIn("thread/start", [method for method, _ in session.rpc.calls])
                session.close()

    def test_resume_cannot_replace_saved_id(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(module, "JsonRpcStdioClient", FakeRpc):
            session = module.CodexPersistentSession(Path(temp), command="codex")
            session.descriptor.write_id("codex", "thr-saved-story")
            original = FakeRpc.request
            def wrong_thread(rpc, method, *args, **kwargs):
                if method == "thread/resume":
                    return {"thread": {"id": "thr-unrelated"}}
                return original(rpc, method, *args, **kwargs)
            with patch.object(FakeRpc, "request", wrong_thread):
                with self.assertRaisesRegex(RuntimeError, "different thread"):
                    session.start("model", "low")
            self.assertEqual(session.descriptor.read_id("codex"), "thr-saved-story")
            self.assertIsNone(session.rpc)
            session.close()

    def test_model_receipt_uses_turn_metadata_and_clears_previous_confirmation(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(module, "JsonRpcStdioClient", FakeRpc):
            session = module.CodexPersistentSession(Path(temp), command="codex")
            session.start("first", "low")
            original = session.rpc.request
            def request(method, *args, **kwargs):
                result = original(method, *args, **kwargs)
                if method == "turn/start":
                    result["turn"]["model"] = "reported-model"
                return result
            session.rpc.request = request
            session.generate("one", output_schema={}, model="requested-model", reasoning_effort="low")
            self.assertEqual(session.last_requested_model, "requested-model")
            self.assertEqual(session.last_confirmed_model, "reported-model")
            session.rpc.request = original
            session.generate_utility("diagnostic", "two", output_schema={}, model="new-model", reasoning_effort="low")
            self.assertEqual(session.last_requested_model, "new-model")
            self.assertEqual(session.last_confirmed_model, "")
            session.close()

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
