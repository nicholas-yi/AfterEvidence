from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from research.harness.tau_copilot import (
    ActionEnvelope,
    WireAction,
    WireCommand,
    main,
    parse_action,
    parse_recorded_action,
)


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
        with (
            patch("sys.argv", ["tau_copilot", "--output", "unused.json"]),
            patch("research.harness.tau_copilot.run", new=AsyncMock(return_value=1)),
        ):
            self.assertEqual(main(), 1)

    def test_action_envelope_schema_separates_message_and_tool_fields(self) -> None:
        schema = ActionEnvelope.model_json_schema()
        self.assertEqual(len(schema["properties"]["action"]["anyOf"]), 2)
        message = ActionEnvelope.model_validate_json(
            '{"action":{"kind":"message","content":"Hello"}}'
        ).native({"lookup"})
        self.assertEqual(message, {"kind": "message", "content": "Hello"})
        with self.assertRaises(ValueError):
            ActionEnvelope.model_validate_json(
                '{"action":{"kind":"message","content":"Hello","name":"placeholder"}}'
            )
        tool = ActionEnvelope.model_validate_json(
            '{"action":{"kind":"tool","name":"lookup","arguments_json":"{\\"id\\":\\"a\\"}"}}'
        ).native({"lookup"})
        self.assertEqual(tool, {"kind": "tool", "name": "lookup", "arguments": {"id": "a"}})

    def test_recorded_action_decoder_preserves_journal_versions(self) -> None:
        expected = {"kind": "message", "content": "Hello"}
        self.assertEqual(
            parse_recorded_action(
                '{"kind":"message","content":"Hello","name":"","arguments_json":"{}"}', set()
            ),
            expected,
        )
        self.assertEqual(
            parse_recorded_action('{"action":{"kind":"message","content":"Hello"}}', set()),
            expected,
        )
        self.assertEqual(
            parse_recorded_action(
                '{"kind":"message","value":"Hello","arguments_json":"{}"}', set()
            ),
            expected,
        )

    def test_wire_command_has_no_unused_placeholder_or_empty_message_field(self) -> None:
        schema = WireCommand.model_json_schema()
        self.assertNotIn("$defs", schema)
        self.assertEqual(schema["properties"]["value"]["minLength"], 1)
        self.assertEqual(
            WireCommand(kind="message", value="Hello", arguments_json="{}").native({"lookup"}),
            {"kind": "message", "content": "Hello"},
        )
        self.assertEqual(
            WireCommand(kind="tool", value="lookup", arguments_json='{"id":"a"}').native(
                {"lookup"}
            ),
            {"kind": "tool", "name": "lookup", "arguments": {"id": "a"}},
        )
        for value in ("", " ", "\n"):
            with self.assertRaises(ValueError):
                WireCommand(kind="message", value=value, arguments_json="{}")
        with self.assertRaises(ValueError):
            WireCommand(kind="message", value="Hello", arguments_json='{"id":"a"}').native(
                {"lookup"}
            )


if __name__ == "__main__":
    unittest.main()
