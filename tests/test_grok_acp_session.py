import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from game_runtime_grok_acp_session import GrokPersistentSession


class FakeRpc:
    instances = []

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
            return {"authMethods": [{"id": "cached_token"}], "agentCapabilities": {"loadSession": True}}
        if method == "session/new":
            return {"sessionId": "session-" + str(len(self.calls))}
        if method == "session/prompt":
            kwargs["notification_handler"]({"method": "session/update", "params": {
                "sessionId": params["sessionId"], "update": {"sessionUpdate": "agent_message_chunk",
                "content": {"text": '{"answer":"ok"}'}}}})
            return {"stopReason": "end_turn"}
        return {}


class PersistentSessionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
