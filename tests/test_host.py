import json
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from game_runtime_mcp_host import (
    DiscoveringRuntimeClient,
    McpHost,
    RuntimeClient,
    _NoRedirectHandler,
    discover_session_file,
    load_json,
)


MANIFEST = {
    "serverName": "test-runtime",
    "tools": [
        {
            "name": "runtime_status",
            "description": "status",
            "command": "runtime.status",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        }
    ],
}


class RuntimeClientTests(unittest.TestCase):
    def test_runtime_redirects_are_rejected(self):
        request = urllib.request.Request(
            "http://127.0.0.1:43121/rpc",
            method="POST",
        )
        handler = _NoRedirectHandler()

        with self.assertRaises(urllib.error.HTTPError) as context:
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://example.com/collect",
            )

        self.assertEqual(302, context.exception.code)
        context.exception.close()

    def test_rejects_non_loopback_endpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "session.json"
            path.write_text(
                json.dumps(
                    {
                        "endpoint": "http://192.168.0.10:18761/",
                        "token": "secret",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "loopback"):
                RuntimeClient(path)

    def test_reloads_session_when_unity_recreates_descriptor(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "session.json"
            path.write_text(
                json.dumps(
                    {"endpoint": "http://127.0.0.1:18761/", "token": "first"}
                ),
                encoding="utf-8",
            )
            client = RuntimeClient(path)
            time.sleep(0.01)
            path.write_text(
                json.dumps(
                    {"endpoint": "http://127.0.0.1:18762/", "token": "second"}
                ),
                encoding="utf-8",
            )

            client._reload_session_if_changed()

            self.assertEqual(client.endpoint, "http://127.0.0.1:18762/rpc")
            self.assertEqual(client.token, "second")

    def test_discovers_latest_matching_lab_session_without_manual_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            older = root / "DefaultCompany" / "Other" / "llm-conversation-lab-runtime-mcp.json"
            newer = root / "DefaultCompany" / "Lab" / "llm-conversation-lab-runtime-mcp.json"
            older.parent.mkdir(parents=True)
            newer.parent.mkdir(parents=True)
            older.write_text(json.dumps({"product": "OtherLab"}), encoding="utf-8")
            time.sleep(0.01)
            newer.write_text(json.dumps({"product": "LLMConversationLab"}), encoding="utf-8")

            discovered = discover_session_file(
                root, "llm-conversation-lab-runtime-mcp.json", "LLMConversationLab"
            )

            self.assertEqual(discovered, newer)

    def test_session_descriptor_can_disappear_and_recover_without_restarting_host(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "session.json"
            path.write_text(
                json.dumps({"endpoint": "http://127.0.0.1:18761/", "token": "first"}),
                encoding="utf-8",
            )
            client = RuntimeClient(path)
            host = McpHost(client, MANIFEST)

            path.unlink()
            unavailable = host.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "runtime_status", "arguments": {}},
                }
            )
            self.assertTrue(unavailable["result"]["isError"])

            time.sleep(0.01)
            path.write_text(
                json.dumps({"endpoint": "http://127.0.0.1:18762/", "token": "second"}),
                encoding="utf-8",
            )
            client._reload_session_if_changed()

            self.assertEqual(client.endpoint, "http://127.0.0.1:18762/rpc")
            self.assertEqual(client.token, "second")

    def test_discovering_client_stays_available_when_game_starts_later(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            client = DiscoveringRuntimeClient(
                root, "storyllm-runtime-mcp.json", "StoryLLMMaster"
            )
            host = McpHost(client, MANIFEST)
            request = {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "runtime_status", "arguments": {}},
            }

            unavailable = host.handle(request)
            self.assertTrue(unavailable["result"]["isError"])

            session = root / "DefaultCompany" / "StoryLLMMaster" / "storyllm-runtime-mcp.json"
            session.parent.mkdir(parents=True)
            session.write_text(
                json.dumps(
                    {
                        "endpoint": "http://127.0.0.1:18761/",
                        "token": "runtime-token",
                        "product": "StoryLLMMaster",
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(
                RuntimeClient,
                "call",
                return_value={"ok": True, "result": {"turn": 1}},
            ):
                available = host.handle(request)

            self.assertFalse(available["result"]["isError"])


class McpHostTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.host = McpHost(self.client, MANIFEST)

    def test_lists_manifest_tools(self):
        result = self.host.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        )
        self.assertEqual(result["result"]["tools"][0]["name"], "runtime_status")

    def test_routes_tool_call_to_runtime_command(self):
        self.client.call.return_value = {"ok": True, "result": {"turn": 1}}
        result = self.host.handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "runtime_status", "arguments": {}},
            }
        )
        self.client.call.assert_called_once_with("runtime.status", {})
        self.assertFalse(result["result"]["isError"])

    def test_unknown_tool_returns_json_rpc_error(self):
        result = self.host.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "missing", "arguments": {}},
            }
        )
        self.assertEqual(result["error"]["code"], -32602)

    def test_runtime_timeout_is_bounded_error_and_host_stays_available(self):
        self.client.call.side_effect = [TimeoutError("timed out"), {"ok": True, "result": {}}]
        request = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "runtime_status", "arguments": {}},
        }

        timed_out = self.host.handle(request)
        recovered = self.host.handle(request)

        self.assertTrue(timed_out["result"]["isError"])
        self.assertFalse(recovered["result"]["isError"])

    def test_storyllmmaster_manifest_exposes_complete_turn_control_surface(self):
        manifest_path = Path(__file__).parents[1] / "examples" / "storyllmmaster.tools.json"
        routes = McpHost(self.client, load_json(manifest_path)).routes

        self.assertEqual(
            {route.command for route in routes.values() if route.command.startswith("turn.")},
            {
                "turn.list_units",
                "turn.get_pending",
                "turn.ensure",
                "turn.get_context",
                "turn.submit",
                "turn.get_result",
            },
        )


if __name__ == "__main__":
    unittest.main()
