import unittest
from pathlib import Path
from unittest.mock import Mock

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from game_runtime_mcp_host import (
    McpHost,
    ToolArgumentValidationError,
    validate_tool_arguments,
)


VALIDATION_MANIFEST = {
    "serverName": "validation-test",
    "tools": [
        {
            "name": "move",
            "description": "move",
            "command": "player.move",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "targetX": {"type": "number", "minimum": -10, "maximum": 10},
                    "targetZ": {"type": "number"},
                },
                "required": ["targetX", "targetZ"],
                "additionalProperties": False,
            },
        },
        {
            "name": "interact",
            "description": "interact",
            "command": "player.interact",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "targetId": {"type": "string", "minLength": 1},
                    "targetName": {"type": "string", "minLength": 1},
                },
                "anyOf": [
                    {"required": ["targetId"]},
                    {"required": ["targetName"]},
                ],
                "additionalProperties": False,
            },
        },
    ],
}


class ToolArgumentValidationTests(unittest.TestCase):
    def test_valid_nested_schema_subset(self):
        schema = {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["auto", "manual"]},
                "participants": {
                    "type": "array",
                    "minItems": 2,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "minLength": 1},
                            "weight": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "maximum": 1,
                            },
                        },
                        "required": ["id"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["mode", "participants"],
            "additionalProperties": False,
        }

        validate_tool_arguments(
            {
                "mode": "auto",
                "participants": [
                    {"id": "a", "weight": 0.5},
                    {"id": "b"},
                ],
            },
            schema,
        )

    def test_boolean_is_not_accepted_as_integer(self):
        with self.assertRaisesRegex(
            ToolArgumentValidationError,
            "must be integer",
        ):
            validate_tool_arguments(True, {"type": "integer"})

    def test_non_finite_number_is_rejected(self):
        with self.assertRaisesRegex(
            ToolArgumentValidationError,
            "must be number",
        ):
            validate_tool_arguments(float("nan"), {"type": "number"})

    def test_array_minimum_and_nested_unknown_property_are_enforced(self):
        schema = {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": False,
            },
        }

        with self.assertRaisesRegex(ToolArgumentValidationError, "at least 2 items"):
            validate_tool_arguments([{"id": "a"}], schema)

        with self.assertRaisesRegex(ToolArgumentValidationError, "not an allowed"):
            validate_tool_arguments(
                [{"id": "a"}, {"id": "b", "extra": True}],
                schema,
            )

    def test_any_of_requires_one_declared_target(self):
        schema = VALIDATION_MANIFEST["tools"][1]["inputSchema"]

        with self.assertRaisesRegex(
            ToolArgumentValidationError,
            "at least one allowed shape",
        ):
            validate_tool_arguments({}, schema)

        validate_tool_arguments({"targetId": "target-1"}, schema)
        validate_tool_arguments({"targetName": "Door"}, schema)

    def test_manifest_rejects_an_unsupported_schema_keyword(self):
        manifest = {
            "tools": [
                {
                    "name": "patterned",
                    "description": "patterned",
                    "command": "test.patterned",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "value": {
                                "type": "string",
                                "pattern": "^[a-z]+$",
                            }
                        },
                    },
                }
            ]
        }

        with self.assertRaisesRegex(ValueError, "unsupported schema keyword"):
            McpHost(Mock(), manifest)


class McpHostArgumentValidationTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.call.return_value = {"ok": True, "result": {}}
        self.host = McpHost(self.client, VALIDATION_MANIFEST)

    def call(self, name, arguments):
        return self.host.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )

    def test_missing_required_argument_is_rejected_before_runtime(self):
        result = self.call("move", {"targetX": 1})

        self.assertEqual(result["error"]["code"], -32602)
        self.assertIn("targetZ is required", result["error"]["message"])
        self.client.call.assert_not_called()

    def test_unknown_argument_is_rejected_before_runtime(self):
        result = self.call(
            "move",
            {"targetX": 1, "targetZ": 2, "teleport": True},
        )

        self.assertEqual(result["error"]["code"], -32602)
        self.assertIn("teleport is not an allowed", result["error"]["message"])
        self.client.call.assert_not_called()

    def test_number_bounds_are_enforced_before_runtime(self):
        result = self.call("move", {"targetX": 99, "targetZ": 2})

        self.assertEqual(result["error"]["code"], -32602)
        self.assertIn("less than or equal to 10", result["error"]["message"])
        self.client.call.assert_not_called()

    def test_valid_arguments_are_forwarded_without_rewriting(self):
        arguments = {"targetX": 1.25, "targetZ": -2}
        result = self.call("move", arguments)

        self.assertFalse(result["result"]["isError"])
        self.client.call.assert_called_once_with("player.move", arguments)


if __name__ == "__main__":
    unittest.main()
