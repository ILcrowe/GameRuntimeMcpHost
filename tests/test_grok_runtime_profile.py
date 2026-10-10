import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from urllib.parse import quote
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from game_runtime_grok_session import (GrokSessionConsent, GrokConsentDenied,
    story_runtime_profile, verify_story_runtime_inventory)
from game_runtime_grok_acp_session import GrokPersistentSession


def inventory():
    return {"grokVersion": "1.0.46", "skills": [{"name": "bundled-skill"}],
        "plugins": [], "hooks": [], "projectInstructions": [], "mcpServers": [],
        "agents": [{"name": "builtin"}], "lspServers": [], "externalCompat": {"cells": [
            {"vendor": vendor, "surface": surface, "enabled": False}
            for vendor in ("claude", "cursor")
            for surface in ("skills", "rules", "agents", "mcps", "hooks", "sessions")
        ] + [{"vendor": "codex", "surface": "sessions", "enabled": False}]}}


class RuntimeProfileTests(unittest.TestCase):
    def test_approval_alone_cannot_send_a_model_request(self):
        with tempfile.TemporaryDirectory() as root:
            consent = GrokSessionConsent("approved", root)
            consent.require_setup(expected_scope=root)
            with self.assertRaises(GrokConsentDenied):
                consent.require_start(expected_scope=root)

    def test_denied_pending_and_cancelled_cannot_touch_profile_or_start_process(self):
        for decision in ("pending", "denied", "cancelled"):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as root:
                path = Path(root)
                session = GrokPersistentSession(path / "state", command="fake", source_grok_home=path,
                    consent=GrokSessionConsent(decision, str(path / "state")), logger=lambda _: None)
                with patch("game_runtime_grok_acp_session.subprocess.run") as run:
                    with self.assertRaises(GrokConsentDenied):
                        session.start()
                    run.assert_not_called()
                self.assertFalse(session.profile_path.exists())
                self.assertFalse(session.private_user_home.exists())
                session.close()

    def test_actor_scope_is_contained_and_revocation_preserves_binding(self):
        with tempfile.TemporaryDirectory() as root:
            consent = GrokSessionConsent("approved", root)
            actor = str(Path(root) / "npc-a")
            consent.bind_runtime_profile(actor, "profile-hash")
            consent.require_start(expected_scope=actor)
            with self.assertRaises(GrokConsentDenied):
                consent.require_start(expected_scope=str(Path(root).parent / "another-game"))
            consent.set_decision("cancelled")
            with self.assertRaises(GrokConsentDenied):
                consent.require_start(expected_scope=actor)
            self.assertEqual(consent.runtime_profile_digest, "profile-hash")

    def test_environment_inventory_does_not_claim_zero_discovered_skills(self):
        result = verify_story_runtime_inventory(inventory())
        self.assertEqual(result["discoveredSkills"], 1)
        self.assertEqual(result["externalComponents"], {"plugins": 0, "hooks": 0, "instructions": 0, "mcp": 0, "lsp": 0})

    def test_active_hook_plugin_mcp_instruction_or_lsp_blocks(self):
        for field in ("plugins", "hooks", "mcpServers", "projectInstructions", "lspServers"):
            with self.subTest(field=field):
                raw = inventory()
                raw[field] = [{"name": "active"}]
                with self.assertRaises(RuntimeError):
                    verify_story_runtime_inventory(raw)

    def test_missing_unknown_or_enabled_compatibility_blocks(self):
        for value in (None, True):
            raw = inventory()
            raw["externalCompat"]["cells"][0]["enabled"] = value
            with self.assertRaises(RuntimeError):
                verify_story_runtime_inventory(raw)
        raw = inventory()
        raw["externalCompat"]["cells"].pop()
        with self.assertRaises(RuntimeError):
            verify_story_runtime_inventory(raw)

    def test_workspace_files_rejected_before_native_launch(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            session = GrokPersistentSession(path / "state", command="fake", source_grok_home=path,
                consent=GrokSessionConsent("approved", str(path / "state")), logger=lambda _: None)
            (session.workspace / "private-source.cs").write_text("private", encoding="utf-8")
            with patch("game_runtime_grok_acp_session.subprocess.run") as run:
                with self.assertRaises(ValueError):
                    session.prepare_runtime_profile()
                run.assert_not_called()
            session.close()

    def test_native_readback_rejects_tools_skills_or_prompt_injection(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            session = GrokPersistentSession(path / "state", command="fake", source_grok_home=path,
                consent=GrokSessionConsent("approved", str(path / "state")), logger=lambda _: None)
            folder = path / "sessions" / quote(str(session.workspace), safe="") / "native-id"
            folder.mkdir(parents=True)
            profile = story_runtime_profile()
            def write(tools=None, prompt=None, custom_profile=None):
                (folder / "tool_definitions.json").write_text(json.dumps([] if tools is None else tools), encoding="utf-8")
                (folder / "system_prompt.txt").write_text(session.system_prompt if prompt is None else prompt, encoding="utf-8")
                (folder / "summary.json").write_text(json.dumps({"agentProfile": profile if custom_profile is None else custom_profile}), encoding="utf-8")
            write()
            session._verify_native_profile("native-id")
            self.assertEqual(session.native_profile_evidence["native-id"]["nativeToolDefinitionCount"], 0)
            for case in ("tool", "skill", "prompt", "missing-profile", "deny-list", "tool-config", "prompt-body"):
                with self.subTest(case=case):
                    invalid = copy.deepcopy(profile)
                    if case == "skill":
                        invalid["discoverSkills"] = True
                    if case == "missing-profile":
                        invalid = {}
                    if case == "deny-list":
                        invalid["disallowedTools"] = []
                    if case == "tool-config":
                        invalid["toolConfig"]["tools"] = [{"id": "GrokBuild:bash"}]
                    if case == "prompt-body":
                        invalid["promptBody"] = "foreign rules"
                    write(tools=[{"name": "read_file"}] if case == "tool" else None,
                          prompt="foreign rules" if case == "prompt" else None, custom_profile=invalid)
                    with self.assertRaises(RuntimeError):
                        session._verify_native_profile("native-id")
            session.close()

    def test_fresh_native_session_verifies_profile_before_sampling_and_tools_afterward(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            session = GrokPersistentSession(path / "state", command="fake", source_grok_home=path,
                consent=GrokSessionConsent("approved", str(path / "state")), logger=lambda _: None)
            folder = path / "sessions" / quote(str(session.workspace), safe="") / "fresh-id"
            folder.mkdir(parents=True)
            (folder / "system_prompt.txt").write_text(session.system_prompt, encoding="utf-8")
            (folder / "summary.json").write_text(json.dumps({"agentProfile": story_runtime_profile()}), encoding="utf-8")
            session._verify_native_profile("fresh-id")
            self.assertIsNone(session.native_profile_evidence["fresh-id"]["nativeToolDefinitionCount"])
            self.assertFalse(session.native_profile_evidence["fresh-id"]["sampledToolDefinitionsVerified"])
            with self.assertRaises(RuntimeError):
                session._verify_native_profile("fresh-id", require_tools=True)
            (folder / "tool_definitions.json").write_text("[]", encoding="utf-8")
            session._verify_native_profile("fresh-id", require_tools=True)
            self.assertTrue(session.native_profile_evidence["fresh-id"]["sampledToolDefinitionsVerified"])
            session.close()

    def test_prompt_response_cannot_be_returned_without_sampled_tool_evidence(self):
        for persist_tools in (False, True):
            with self.subTest(persist_tools=persist_tools), tempfile.TemporaryDirectory() as root:
                path = Path(root)
                session = GrokPersistentSession(path / "state", command="fake", source_grok_home=path,
                    consent=GrokSessionConsent("approved", str(path / "state")), logger=lambda _: None)
                session.consent.bind_runtime_profile(session.state_root, "test-profile")
                folder = path / "sessions" / quote(str(session.workspace), safe="") / "fresh-id"
                folder.mkdir(parents=True)
                (folder / "system_prompt.txt").write_text(session.system_prompt, encoding="utf-8")
                (folder / "summary.json").write_text(json.dumps({"agentProfile": story_runtime_profile()}), encoding="utf-8")
                def sampled(*args, **kwargs):
                    if persist_tools:
                        (folder / "tool_definitions.json").write_text("[]", encoding="utf-8")
                    return {"stopReason": "end_turn"}
                rpc = Mock()
                rpc.request.side_effect = sampled
                session.rpc = rpc
                if persist_tools:
                    self.assertEqual(session._rpc_request("session/prompt", {"sessionId": "fresh-id"}), {"stopReason": "end_turn"})
                else:
                    with self.assertRaises(RuntimeError):
                        session._rpc_request("session/prompt", {"sessionId": "fresh-id"})
                rpc.request.assert_called_once()
                session.close()


if __name__ == "__main__":
    unittest.main()
