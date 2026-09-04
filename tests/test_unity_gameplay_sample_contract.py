from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ROOT = ROOT / "examples" / "unity-gameplay"
MANIFEST = SAMPLE_ROOT / "game-runtime.tools.json"
BRIDGE = SAMPLE_ROOT / "Runtime" / "GameRuntimeMcpBridge.cs"
HANDLER = SAMPLE_ROOT / "Runtime" / "SampleGamePlayActionHandler.cs"


class UnityGameplaySampleContractTests(unittest.TestCase):
    def test_manifest_maps_the_fixed_gameplay_surface(self):
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        tools = payload["tools"]

        self.assertEqual(
            [(tool["name"], tool["command"]) for tool in tools],
            [
                ("runtime_status", "runtime.status"),
                ("get_game_state", "game.get_state"),
                ("get_surroundings", "game.get_surroundings"),
                ("player_move_to", "player.move_to"),
                ("player_interact", "player.interact"),
                ("send_in_game_chat", "chat.send"),
            ],
        )

    def test_every_tool_is_closed_to_unknown_arguments(self):
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

        for tool in payload["tools"]:
            with self.subTest(tool=tool["name"]):
                self.assertFalse(tool["inputSchema"]["additionalProperties"])

    def test_mutation_schemas_require_their_minimum_inputs(self):
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        by_name = {tool["name"]: tool for tool in payload["tools"]}

        self.assertEqual(
            by_name["player_move_to"]["inputSchema"]["required"],
            ["targetX", "targetZ"],
        )
        self.assertEqual(
            by_name["send_in_game_chat"]["inputSchema"]["required"],
            ["message"],
        )

        interaction = by_name["player_interact"]["inputSchema"]
        self.assertEqual(
            interaction["anyOf"],
            [
                {"required": ["targetId"]},
                {"required": ["targetName"]},
            ],
        )

    def test_bridge_matches_host_rpc_envelope_and_avoids_thread_abort(self):
        source = BRIDGE.read_text(encoding="utf-8")

        self.assertIn("public int protocol;", source)
        self.assertIn("public string command;", source)
        self.assertIn('"runtime.status"', source)
        self.assertIn("ResultReply(handler(requestJson))", source)
        self.assertIn("ErrorReply", source)
        self.assertNotIn("Thread.Abort", source)
        self.assertNotIn("[SerializeField] private string sessionToken", source)

    def test_handler_registers_every_manifest_command(self):
        source = HANDLER.read_text(encoding="utf-8")

        for command in (
            '"game.get_state"',
            '"game.get_surroundings"',
            '"player.move_to"',
            '"player.interact"',
            '"chat.send"',
        ):
            with self.subTest(command=command):
                self.assertIn(command, source)

        self.assertNotIn("airport", source.lower())
        self.assertIn("Vector3.MoveTowards", source)
        self.assertIn("IGameRuntimeMcpInteractable", source)


if __name__ == "__main__":
    unittest.main()
