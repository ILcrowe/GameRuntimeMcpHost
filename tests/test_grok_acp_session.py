import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from game_runtime_grok_acp_session import GrokPersistentSession


class FakeRpc:
    instances = []
    auth_methods = [{"id": "cached_token"}]

    def __init__(self, *args, **kwargs):
        self.is_running = False
        self.process = type("Process", (), {"pid": 123})()
        self.calls = []
        self.instances.append(self)

    def start(self):
        self.is_running = True

    def close(self):
        self.is_running = False

    def notify(self, *args):
        pass

    def request(self, method, params, **kwargs):
        self.calls.append((method, params))
        if method == "initialize":
            return {"authMethods": self.auth_methods, "agentCapabilities": {"loadSession": True}}
        if method == "session/new":
            return {"sessionId": "session-" + str(len(self.calls))}
        if method == "session/prompt":
            kwargs["notification_handler"]({"method": "session/update", "params": {
                "sessionId": params["sessionId"], "update": {"sessionUpdate": "agent_message_chunk",
                "content": {"text": '{"answer":"ok"}'}}}})
            return {"stopReason": "end_turn"}
        return {}


class PersistentSessionTests(unittest.TestCase):
    @patch("game_runtime_grok_acp_session.JsonRpcStdioClient", FakeRpc)
    def test_game_closed_wait_cancels_and_discards_transport(self):
        with tempfile.TemporaryDirectory() as root:
            session = GrokPersistentSession(Path(root), command="fake", source_grok_home=Path(root), logger=lambda _: None)
            session.start()
            rpc = session.rpc
            original = rpc.request
            notifications = []
            rpc.notify = lambda method, params: notifications.append((method, params))
            def request(method, params, **kwargs):
                if method == "session/prompt":
                    kwargs["wait_check"]()
                return original(method, params, **kwargs)
            rpc.request = request
            def cancelled():
                raise RuntimeError("game cancelled")
            session.request_wait_check = cancelled
            with self.assertRaisesRegex(RuntimeError, "game cancelled"):
                session.generate("one", output_schema={})
            self.assertEqual(notifications, [("session/cancel", {"sessionId": session.session_id})])
            self.assertIsNone(session.rpc)
            self.assertFalse(rpc.is_running)
            session.request_wait_check = None
            self.assertEqual(session.generate("next", output_schema={}), {"answer": "ok"})
            session.close()

    def setUp(self):
        FakeRpc.instances.clear()
        FakeRpc.auth_methods = [{"id": "cached_token"}]

    @patch("game_runtime_grok_acp_session.JsonRpcStdioClient", FakeRpc)
    def test_provider_wait_uses_remaining_game_deadline_and_skips_expired_prompt(self):
        with tempfile.TemporaryDirectory() as root, patch("game_runtime_agent_session.time.time", return_value=1000):
            session = GrokPersistentSession(Path(root), command="fake", source_grok_home=Path(root), logger=lambda _: None)
            session.start()
            session.request_deadline_unix_ms = 1006000
            rpc = session.rpc
            original = rpc.request
            waits = []
            def request(method, params, **kwargs):
                waits.append(kwargs["timeout"])
                return original(method, params, **kwargs)
            rpc.request = request
            session.generate("one", output_schema={})
            self.assertEqual(waits, [5.5])
            session.request_deadline_unix_ms = 999000
            with self.assertRaisesRegex(TimeoutError, "deadline elapsed"):
                session.generate("expired", output_schema={})
            self.assertEqual(waits, [5.5], "Expired work must not issue another prompt.")
            session.close()

    @patch("game_runtime_grok_acp_session.JsonRpcStdioClient", FakeRpc)
    def test_model_change_keeps_story_and_forwards_unknown_id(self):
        with tempfile.TemporaryDirectory() as root:
            session = GrokPersistentSession(Path(root), command="fake", source_grok_home=Path(root), logger=lambda _: None)
            session.start()
            story = session.session_id
            rpc = session.rpc
            session._capture_model_options(story, {"configOptions": [{"id": "model", "currentValue": "old"}]})
            original_request = rpc.request
            def request(method, params, **kwargs):
                if method == "session/set_config_option":
                    rpc.calls.append((method, params))
                    return {"configOptions": [{"id": "model", "currentValue": params["value"]["value"]}]}
                return original_request(method, params, **kwargs)
            rpc.request = request
            session.generate("one", output_schema={"type": "object"}, model="unlisted-new-model")
            session.generate("two", output_schema={"type": "object"}, model="unlisted-new-model")
            self.assertIs(session.rpc, rpc)
            self.assertEqual(session.session_id, story)
            changes = [p for m, p in rpc.calls if m == "session/set_config_option"]
            self.assertEqual(changes, [{"sessionId": story, "configId": "model", "value": {"value": "unlisted-new-model"}}])
            self.assertEqual(session.last_confirmed_model, "unlisted-new-model")
            session.close()

    @patch("game_runtime_grok_acp_session.JsonRpcStdioClient", FakeRpc)
    def test_missing_model_confirmation_retains_selector_without_claiming_applied_model(self):
        with tempfile.TemporaryDirectory() as root:
            session = GrokPersistentSession(Path(root), command="fake", source_grok_home=Path(root), logger=lambda _: None)
            session.start()
            story = session.session_id
            rpc = session.rpc
            session._capture_model_options(story, {"configOptions": [{"id": "model", "currentValue": "old"}]})
            session.generate("one", output_schema={}, model="custom-id")
            self.assertEqual(session.last_requested_model, "custom-id")
            self.assertEqual(session.last_confirmed_model, "")
            session.generate("two", output_schema={}, model="another-id")
            self.assertEqual(session.last_confirmed_model, "")
            self.assertIs(session.rpc, rpc)
            self.assertEqual(session.session_id, story)
            changes = [p["value"]["value"] for m, p in rpc.calls if m == "session/set_config_option"]
            self.assertEqual(changes, ["custom-id", "another-id"])
            session.close()

    @patch("game_runtime_grok_acp_session.JsonRpcStdioClient", FakeRpc)
    def test_legacy_model_contract_keeps_session_and_forwards_unlisted_id(self):
        with tempfile.TemporaryDirectory() as root:
            session = GrokPersistentSession(Path(root), command="fake", source_grok_home=Path(root), logger=lambda _: None)
            session.start()
            story = session.session_id
            rpc = session.rpc
            session._capture_model_options(story, {"models": {"currentModelId": "grok-4.7", "availableModels": []}})
            original = rpc.request
            def request(method, params, **kwargs):
                if method == "session/set_model":
                    rpc.calls.append((method, params))
                    return {"_meta": {"model": {"Ok": params["modelId"]}}}
                return original(method, params, **kwargs)
            rpc.request = request
            session.generate("one", output_schema={}, model="future-model")
            session.generate("two", output_schema={}, model="future-model")
            self.assertEqual(session.last_confirmed_model, "future-model")
            self.assertEqual(session.session_id, story)
            self.assertIs(session.rpc, rpc)
            self.assertEqual([p for m, p in rpc.calls if m == "session/set_model"],
                             [{"sessionId": story, "modelId": "future-model"}])
            def reject(method, params, **kwargs):
                if method == "session/set_model":
                    raise RuntimeError("session/set_model failed (-32602): Invalid params")
                return original(method, params, **kwargs)
            rpc.request = reject
            with self.assertRaisesRegex(RuntimeError, "Invalid params"):
                session.generate("bad", output_schema={}, model="invalid-id")
            self.assertEqual(session.last_confirmed_model, "")
            self.assertEqual(session.session_id, story)
            session.generate("restored", output_schema={}, model="future-model")
            self.assertEqual(session.last_confirmed_model, "future-model")
            session.close()

    @patch("game_runtime_grok_acp_session.JsonRpcStdioClient", FakeRpc)
    def test_unsupported_selection_does_not_send_prompt_or_replace_story(self):
        with tempfile.TemporaryDirectory() as root:
            session = GrokPersistentSession(Path(root), command="fake", source_grok_home=Path(root), logger=lambda _: None)
            session.start()
            story = session.session_id
            with self.assertRaisesRegex(RuntimeError, "does not advertise"):
                session.generate("one", output_schema={}, model="unlisted")
            self.assertEqual(session.session_id, story)
            self.assertFalse(any(m == "session/prompt" for m, _ in session.rpc.calls))
            session.generate("default", output_schema={})
            session.close()

    def test_legacy_conversation_is_copied_without_overwriting_shared_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = root / "story" / "grok-runtime-home" / "sessions" / "old-workspace" / "saved-id"
            old.mkdir(parents=True)
            (old / "chat_history.jsonl").write_text("old story", encoding="utf-8")
            session = GrokPersistentSession(root / "story", transport_root=root / "connection",
                command="fake", source_grok_home=root, logger=lambda _: None)
            session._migrate_saved_session(root / "story", "saved-id")
            copies = list((session.runtime_grok_home / "sessions").glob("*/saved-id/chat_history.jsonl"))
            self.assertEqual(len(copies), 1)
            self.assertEqual(copies[0].read_text(), "old story")
            copies[0].write_text("newer story", encoding="utf-8")
            session._migrate_saved_session(root / "story", "saved-id")
            self.assertEqual(copies[0].read_text(), "newer story")
            self.assertEqual((old / "chat_history.jsonl").read_text(), "old story")
            session.close()

    @patch("game_runtime_grok_acp_session.JsonRpcStdioClient", FakeRpc)
    def test_process_and_story_survive_multiple_turns_and_utility(self):
        FakeRpc.instances.clear()
        with tempfile.TemporaryDirectory() as root:
            session = GrokPersistentSession(Path(root), command="fake", source_grok_home=Path(root), logger=lambda _: None)
            schema = {"type": "object"}
            session.generate("one", output_schema=schema)
            story = session.session_id
            session.generate_utility("diagnostic", "ping", output_schema=schema)
            session.generate("two", output_schema=schema)
            self.assertEqual(len(FakeRpc.instances), 1)
            prompts = [p for m, p in session.rpc.calls if m == "session/prompt"]
            self.assertEqual(prompts[0]["sessionId"], story)
            self.assertEqual(prompts[2]["sessionId"], story)
            self.assertNotEqual(prompts[1]["sessionId"], story)
            rpc = session.rpc
            session.switch_scope(Path(root) / "story-b")
            other_story = session.session_id
            self.assertNotEqual(other_story, story)
            self.assertIs(session.rpc, rpc)
            session.switch_scope(Path(root))
            self.assertEqual(session.session_id, story)
            self.assertIs(session.rpc, rpc)
            self.assertEqual(len(FakeRpc.instances), 1)
            session.close()
            restored = GrokPersistentSession(Path(root), command="fake", source_grok_home=Path(root), logger=lambda _: None)
            restored.start()
            self.assertEqual(restored.session_id, story)
            self.assertTrue(any(m == "session/load" for m, _ in restored.rpc.calls))
            self.assertFalse(any(m == "session/new" for m, _ in restored.rpc.calls))
            restored.close()

    @patch("game_runtime_grok_acp_session.JsonRpcStdioClient", FakeRpc)
    def test_current_grok_oauth_method_is_used_when_cached_token_is_not_advertised(self):
        FakeRpc.auth_methods = [{"id": "grok.com"}]
        with tempfile.TemporaryDirectory() as root:
            session = GrokPersistentSession(Path(root), command="fake", source_grok_home=Path(root), logger=lambda _: None)
            session.start()
            auth_calls = [params for method, params in session.rpc.calls if method == "authenticate"]
            self.assertEqual(auth_calls, [{"methodId": "grok.com", "_meta": {"headless": True}}])
            session.close()


if __name__ == "__main__":
    unittest.main()
