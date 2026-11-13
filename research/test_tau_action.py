from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from research.tau_copilot import WireAction, main, parse_action


class ActionTests(unittest.TestCase):
    def test_exact_message_and_tool_actions(self) -> None:
        message = parse_action('{"kind":"message","content":"Hello"}', {"lookup"})
        self.assertEqual(message["kind"], "message")
        if message["kind"] == "message":
            self.assertEqual(message["content"], "Hello")
        tool = parse_action('{"kind":"tool","name":"lookup","arguments":{"id":"a"}}', {"lookup"})
        self.assertEqual(tool["kind"], "tool")
        if tool["kind"] == "tool":
            self.assertEqual(tool["name"], "lookup")

    def test_invalid_and_mixed_actions_are_rejected(self) -> None:
        for value in (
            "[]",
            '{"kind":"message","content":""}',
            '{"kind":"message","content":"Hello","name":"lookup"}',
            '{"kind":"tool","name":"delete_any_file","arguments":{}}',
            '{"kind":"tool","name":"lookup","arguments":[]}',
            '{"kind":"tool","name":["lookup"],"arguments":{}}',
            '{"kind":"finish"}',
        ):
            with self.assertRaises(ValueError):
                parse_action(value, {"lookup"})

    def test_typed_wire_contract_normalizes_native_tool_arguments(self) -> None:
        action = WireAction(kind="tool", content="", name="lookup", arguments_json='{"id":"a"}')
        normalized = action.native({"lookup"})
        self.assertEqual(normalized["kind"], "tool")
        if normalized["kind"] == "tool":
            self.assertEqual(normalized["arguments"], {"id": "a"})
        with self.assertRaises(ValueError):
            WireAction(kind="message", content="Hello", name="lookup", arguments_json="{}").native(
                {"lookup"}
            )

    def test_incomplete_pilot_has_a_failing_cli_exit_status(self) -> None:
        with patch("sys.argv", ["tau_copilot", "--output", "unused.json"]):
            with patch("research.tau_copilot.run", new=AsyncMock(return_value=1)):
                self.assertEqual(main(), 1)


if __name__ == "__main__":
    unittest.main()
