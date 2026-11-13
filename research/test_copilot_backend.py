from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from copilot.generated.session_events import AssistantMessageData

from research.copilot_backend import CopilotBackend


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_isolation_request_cap_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = MagicMock()
            session = MagicMock()
            session.send_and_wait = AsyncMock(
                return_value=SimpleNamespace(
                    data=AssistantMessageData(
                        content='{"kind":"message","content":"Hello"}', message_id="test"
                    ),
                )
            )
            session.rpc.usage.get_metrics = AsyncMock(return_value={"total_nano_aiu": 1})
            session.disconnect = AsyncMock()
            session.abort = AsyncMock()
            client.create_session = AsyncMock(return_value=session)
            journal = io.StringIO()
            backend = CopilotBackend(
                client, "test-model", Path(directory), journal, request_limit=1
            )
            text = await backend.complete("System instructions", "Benchmark input")
            self.assertIn("Hello", text)
            options = client.create_session.call_args.kwargs
            self.assertEqual(options["available_tools"], [])
            self.assertFalse(options["enable_config_discovery"])
            self.assertFalse(options["memory"]["enabled"])
            self.assertTrue(options["skip_custom_instructions"])
            self.assertFalse(options["enable_skills"])
            self.assertEqual(options["session_limits"]["max_ai_credits"], 30)
            self.assertTrue(Path(options["working_directory"]).is_absolute())
            session.disconnect.assert_awaited_once()
            with self.assertRaises(RuntimeError):
                await backend.complete("System", "Must not run")
            self.assertEqual(client.create_session.call_count, 1)
            events = [json.loads(line)["event"] for line in journal.getvalue().splitlines()]
            self.assertEqual(
                events,
                [
                    "copilot-request-started",
                    "copilot-response-received",
                    "copilot-request-completed",
                ],
            )

    async def test_missing_reply_is_explicit_and_session_closes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = MagicMock()
            session = MagicMock()
            session.send_and_wait = AsyncMock(return_value=None)
            session.disconnect = AsyncMock()
            session.abort = AsyncMock()
            client.create_session = AsyncMock(return_value=session)
            backend = CopilotBackend(
                client, "test-model", Path(directory), io.StringIO(), request_limit=1
            )
            with self.assertRaisesRegex(RuntimeError, "final assistant message"):
                await backend.complete("System", "Input")
            session.disconnect.assert_awaited_once()

    async def test_timeout_aborts_generation_instead_of_only_stopping_wait(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = MagicMock()
            session = MagicMock()
            session.send_and_wait = AsyncMock(side_effect=TimeoutError("timeout"))
            session.abort = AsyncMock()
            session.disconnect = AsyncMock()
            client.create_session = AsyncMock(return_value=session)
            journal = io.StringIO()
            backend = CopilotBackend(
                client, "test-model", Path(directory), journal, request_limit=1
            )
            with self.assertRaises(TimeoutError):
                await backend.complete("System", "Input")
            session.abort.assert_awaited_once()
            session.disconnect.assert_awaited_once()
            self.assertIn("copilot-request-aborted", journal.getvalue())


if __name__ == "__main__":
    unittest.main()
