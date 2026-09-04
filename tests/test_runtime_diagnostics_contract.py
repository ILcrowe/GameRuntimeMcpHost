from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERIC_MANIFEST = ROOT / "examples" / "runtime-diagnostics.tools.json"
UNITY_MANIFEST = ROOT / "examples" / "unity" / "unity-runtime-sample.tools.json"
SKILL_ROOT = ROOT / "skills" / "game-runtime-mcp-host"

EXPECTED_DIAGNOSTIC_TOOLS = [
    "runtime_status",
    "runtime_build_info",
    "runtime_logs_read",
    "runtime_metrics_snapshot",
    "runtime_capture_screenshot",
]


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class RuntimeDiagnosticsContractTests(unittest.TestCase):
    def test_generic_manifest_has_small_fixed_diagnostic_surface(self):
        tools = load_manifest(GENERIC_MANIFEST)["tools"]
        self.assertEqual([tool["name"] for tool in tools], EXPECTED_DIAGNOSTIC_TOOLS)

    def test_unity_manifest_publishes_the_same_diagnostics(self):
        tool_names = [tool["name"] for tool in load_manifest(UNITY_MANIFEST)["tools"]]
        self.assertEqual(tool_names[: len(EXPECTED_DIAGNOSTIC_TOOLS)], EXPECTED_DIAGNOSTIC_TOOLS)
        self.assertIn("echo_message", tool_names)

    def test_log_read_is_bounded_and_incremental_in_both_manifests(self):
        for manifest_path in (GENERIC_MANIFEST, UNITY_MANIFEST):
            with self.subTest(manifest=manifest_path):
                payload = load_manifest(manifest_path)
                tool = next(
                    tool for tool in payload["tools"] if tool["name"] == "runtime_logs_read"
                )
                properties = tool["inputSchema"]["properties"]

                self.assertEqual(properties["sinceSequence"]["minimum"], 0)
                self.assertEqual(properties["limit"]["minimum"], 1)
                self.assertEqual(properties["limit"]["maximum"], 200)
                self.assertIn("includeStackTrace", properties)
                self.assertFalse(tool["inputSchema"]["additionalProperties"])

    def test_screenshot_contract_does_not_accept_arbitrary_path(self):
        for manifest_path in (GENERIC_MANIFEST, UNITY_MANIFEST):
            with self.subTest(manifest=manifest_path):
                payload = load_manifest(manifest_path)
                tool = next(
                    tool
                    for tool in payload["tools"]
                    if tool["name"] == "runtime_capture_screenshot"
                )

                self.assertNotIn("path", tool["inputSchema"]["properties"])
                self.assertFalse(tool["inputSchema"]["additionalProperties"])

    def test_low_reasoning_skill_keeps_required_references(self):
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertTrue(skill.startswith("---\nname: game-runtime-mcp-host\n"))
        self.assertIn("This skill is intentionally written for low reasoning effort.", skill)
        self.assertIn("runtime_status", skill)
        self.assertIn("runtime_build_info", skill)

        for reference_name in (
            "connection.md",
            "diagnostics.md",
            "gameplay-control.md",
            "verification.md",
        ):
            self.assertTrue((SKILL_ROOT / "references" / reference_name).is_file())
            self.assertIn(f"references/{reference_name}", skill)


if __name__ == "__main__":
    unittest.main()
