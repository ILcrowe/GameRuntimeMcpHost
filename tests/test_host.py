import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from game_runtime_mcp_host import McpHost, RuntimeClient


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


if __name__ == "__main__":
    unittest.main()
