from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNITY_ROOT = ROOT / "examples" / "unity"
MANIFEST = UNITY_ROOT / "game-runtime.tools.json"
BRIDGE = UNITY_ROOT / "Runtime" / "GameRuntimeMcpBridge.cs"
HANDLER = UNITY_ROOT / "Runtime" / "SampleGameRuntimeHandler.cs"
INTERACTABLE = UNITY_ROOT / "Runtime" / "SampleRuntimeMcpInteractable.cs"
PLAYMODE_TEST = UNITY_ROOT / "Tests" / "GameRuntimeMcpTests.cs"


class UnitySampleContractTests(unittest.TestCase):
    def test_manifest_has_one_fixed_unified_surface(self):
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        tools = payload["tools"]

        self.assertEqual(
            [(tool["name"], tool["command"]) for tool in tools],
            [
                ("runtime_status", "runtime.status"),
                ("runtime_build_info", "runtime.build_info"),
                ("runtime_logs_read", "runtime.logs.read"),
                ("runtime_metrics_snapshot", "runtime.metrics.snapshot"),
                ("runtime_capture_screenshot", "runtime.capture_screenshot"),
                ("get_game_state", "game.get_state"),
                ("get_surroundings", "game.get_surroundings"),
                ("player_move_to", "player.move_to"),
                ("player_interact", "player.interact"),
                ("send_in_game_chat", "chat.send"),
            ],
        )

        for tool in tools:
            with self.subTest(tool=tool["name"]):
                self.assertFalse(tool["inputSchema"]["additionalProperties"])

    def test_mutation_schema_requires_minimum_inputs(self):
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
        self.assertEqual(
            by_name["player_interact"]["inputSchema"]["anyOf"],
            [
                {"required": ["targetId"]},
                {"required": ["targetName"]},
            ],
        )

        logs = by_name["runtime_logs_read"]["inputSchema"]["properties"]
        self.assertEqual(logs["sinceSequence"]["minimum"], 0)
        self.assertEqual(logs["limit"]["minimum"], 1)
        self.assertEqual(logs["limit"]["maximum"], 200)

    def test_bridge_is_single_transport_registry_and_diagnostics_surface(self):
        source = BRIDGE.read_text(encoding="utf-8")

        for text in (
            "public sealed class GameRuntimeMcpBridge",
            "public bool RegisterAll(",
            "public int UnregisterAll(",
            'private const string RuntimeStatusCommand = "runtime.status";',
            'private const string RuntimeBuildInfoCommand = "runtime.build_info";',
            'private const string RuntimeLogsReadCommand = "runtime.logs.read";',
            'private const string RuntimeMetricsSnapshotCommand = "runtime.metrics.snapshot";',
            'private const string RuntimeCaptureScreenshotCommand = "runtime.capture_screenshot";',
            "Application.logMessageReceivedThreaded",
            "Profiler.GetTotalAllocatedMemoryLong",
            "ScreenCapture.CaptureScreenshot",
            "main_thread_timeout_not_started",
            "main_thread_timeout_unknown",
        ):
            with self.subTest(text=text):
                self.assertIn(text, source)

        self.assertNotIn("Thread.Abort", source)
        self.assertNotIn("UnityRuntimeDiagnosticsProvider", source)
        self.assertNotIn("[SerializeField] private string sessionToken", source)

    def test_game_handler_uses_owner_registration_and_real_actions(self):
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

        self.assertIn("bridge.RegisterAll(", source)
        self.assertIn("bridge.UnregisterAll(this)", source)
        self.assertIn("Vector3.MoveTowards", source)
        self.assertIn("Physics.OverlapSphere", source)
        self.assertIn("IGameRuntimeMcpInteractable", source)
        self.assertNotIn("airport", source.lower())

    def test_public_sample_types_have_korean_summary_comments(self):
        source_by_type = {
            "GameRuntimeMcpBridge": BRIDGE.read_text(encoding="utf-8"),
            "SampleGameRuntimeHandler": HANDLER.read_text(encoding="utf-8"),
            "IGameRuntimeMcpInteractable": INTERACTABLE.read_text(encoding="utf-8"),
            "SampleRuntimeMcpInteractable": INTERACTABLE.read_text(encoding="utf-8"),
            "GameRuntimeMcpTests": PLAYMODE_TEST.read_text(encoding="utf-8"),
        }

        korean = re.compile(r"[가-힣]")

        for type_name, source in source_by_type.items():
            index = source.index(type_name)
            prefix = source[max(0, index - 600):index]
            with self.subTest(type=type_name):
                self.assertIn("/// <summary>", prefix)
                self.assertRegex(prefix, korean)

    def test_legacy_duplicate_unity_samples_are_removed(self):
        self.assertFalse((ROOT / "examples" / "unity-gameplay").exists())
        self.assertFalse(
            (UNITY_ROOT / "Runtime" / "UnityRuntimeMcpSampleBridge.cs").exists()
        )
        self.assertFalse(
            (UNITY_ROOT / "Runtime" / "UnityRuntimeDiagnosticsProvider.cs").exists()
        )
        self.assertFalse(
            (UNITY_ROOT / "unity-runtime-sample.tools.json").exists()
        )
        self.assertFalse(
            (ROOT / "tests" / "test_runtime_diagnostics_contract.py").exists()
        )
        self.assertFalse(
            (ROOT / "tests" / "test_unity_gameplay_sample_contract.py").exists()
        )

    def test_docs_use_noun_style_for_ab_test_heading(self):
        docs = [
            ROOT / "README.ko.md",
            UNITY_ROOT / "README.ko.md",
        ]

        for path in docs:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertIn("## A/B 테스트", text)
                self.assertNotIn("A/B 테스트하겠습니다", text)


if __name__ == "__main__":
    unittest.main()
