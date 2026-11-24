from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from test_application import ScriptedModel, facts_output

from afterevidence.app_evaluation import RecordedModel
from afterevidence.application import Application
from afterevidence.ollama import Ollama, OllamaError
from afterevidence.store import Store
from afterevidence.web import create_server


class WebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.model = ScriptedModel()
        self.app = Application(Store(Path(self.directory.name) / "web.sqlite3"), self.model)
        self.server = create_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = build_opener(ProxyHandler({}))
        self.token = self.request("/api/status")[1]["csrf_token"]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.directory.cleanup()

    def request(
        self,
        path: str,
        method: str = "GET",
        data: object = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object]]:
        body = None if data is None else json.dumps(data).encode()
        request = Request(
            self.base + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            response = self.opener.open(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            status = response.status
            if not isinstance(status, int):
                self.fail("Expected an HTTP response with an integer status code.")
            return status, json.loads(response.read())

    def test_ui_assets_and_content_policy(self) -> None:
        for path, content_type in (
            ("/", "text/html"),
            ("/app.js", "text/javascript"),
            ("/style.css", "text/css"),
        ):
            with self.opener.open(self.base + path, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(content_type, response.headers["Content-Type"])
                self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
                self.assertTrue(response.read())

    def test_mutations_require_token_and_same_origin(self) -> None:
        body = {"pack": "project", "subject": "Atlas", "text": "Morgan owns Atlas."}
        self.assertEqual(self.request("/api/episodes", "POST", body)[0], 403)
        self.assertEqual(
            self.request(
                "/api/episodes",
                "POST",
                body,
                {
                    "X-AfterEvidence-Token": str(self.token),
                    "Origin": "https://unrelated.example",
                },
            )[0],
            403,
        )
        self.assertEqual(self.app.store.snapshot("project").episodes, ())

    def test_rejected_post_bodies_are_consumed_before_connection_close(self) -> None:
        for _ in range(5):
            status, body = self.request(
                "/api/episodes",
                "POST",
                {
                    "pack": "project",
                    "subject": "Atlas",
                    "text": "x" * 2000,
                },
            )
            self.assertEqual(status, 403)
            self.assertIn("token", str(body["error"]))
        self.assertEqual(self.app.store.snapshot("project").episodes, ())

    def test_host_rebinding_and_path_traversal_are_rejected(self) -> None:
        self.assertEqual(self.request("/api/state", headers={"Host": "unrelated.example"})[0], 403)
        self.assertEqual(self.request("/../pyproject.toml")[0], 404)
        self.assertEqual(self.request("/api/state?pack=unknown")[0], 400)

    def test_full_api_wake_and_delete(self) -> None:
        self.model.responses.append(
            facts_output(
                "project",
                [
                    {
                        "relation": "owner",
                        "value": "Morgan",
                        "quote": "Morgan owns Atlas.",
                        "operation": "assert",
                        "confidence": 0.9,
                    },
                ],
            )
        )
        headers = {"X-AfterEvidence-Token": str(self.token)}
        status, created = self.request(
            "/api/episodes",
            "POST",
            {
                "pack": "project",
                "subject": "Atlas",
                "text": "Morgan owns Atlas.",
            },
            headers,
        )
        self.assertEqual(status, 201)
        episode_id = created["episode_id"]
        self.assertEqual(
            self.request(f"/api/episodes/{episode_id}", "DELETE", headers=headers)[0], 200
        )
        self.assertEqual(
            self.request(f"/api/episodes/{episode_id}", "DELETE", headers=headers)[0], 200
        )
        self.assertNotIn("Morgan", json.dumps(self.request("/api/state")[1]))

    def test_review_api_excludes_model_claim_but_preserves_source(self) -> None:
        self.model.responses.append(
            facts_output(
                "project",
                [
                    {
                        "relation": "owner",
                        "value": "Morgan",
                        "quote": "Morgan owns Atlas.",
                        "operation": "assert",
                        "confidence": 0.9,
                    }
                ],
            )
        )
        headers = {"X-AfterEvidence-Token": str(self.token)}
        self.request(
            "/api/episodes",
            "POST",
            {
                "pack": "project",
                "subject": "Atlas",
                "text": "Morgan owns Atlas.",
            },
            headers,
        )
        claim = self.app.store.snapshot("project").facts("Atlas")[0]
        status, response = self.request(
            f"/api/claims/{claim.id}/review", "POST", {"reject": True}, headers
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["status"], "rejected")
        self.assertEqual(self.app.store.snapshot("project").facts("Atlas"), ())
        self.assertEqual(self.app.store.snapshot("project").episodes[0].status, "active")

    def test_bad_json_and_missing_source_are_explicit_errors(self) -> None:
        self.assertEqual(
            self.request(
                "/api/episodes",
                "POST",
                [],
                {
                    "X-AfterEvidence-Token": str(self.token),
                },
            )[0],
            400,
        )
        self.assertEqual(
            self.request(
                "/api/episodes/missing",
                "DELETE",
                headers={
                    "X-AfterEvidence-Token": str(self.token),
                },
            )[0],
            404,
        )


class OllamaProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mode = "valid"
        self.requests: list[dict[str, object]] = []
        test = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = {"models": [{"name": "local-test", "size": 1, "digest": "test-digest"}]}
                if test.mode == "cloud":
                    body["models"][0]["remote_host"] = "https://example.com"
                payload = json.dumps(body).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:
                test.requests.append(
                    json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                )
                body = {
                    "message": {"content": '{"ok":true}'},
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 5,
                    "eval_count": 3,
                }
                if test.mode == "truncated":
                    body["done_reason"] = "length"
                elif test.mode == "malformed":
                    body["message"] = {"content": "not-json"}
                payload = json.dumps(body).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.client = Ollama("local-test", f"http://127.0.0.1:{self.server.server_port}", timeout=5)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def test_local_structured_output_and_metrics(self) -> None:
        reply = self.client.complete("Extract data.", "Example", {"type": "object"})
        self.assertEqual(reply.data, {"ok": True})
        self.assertEqual(reply.prompt_tokens, 5)
        self.assertFalse(self.requests[0]["think"])
        self.assertFalse(self.requests[0]["stream"])
        self.assertNotIn("data", reply.metrics())

    def test_truncation_and_invalid_output_are_not_successes(self) -> None:
        for mode in ("truncated", "malformed"):
            self.mode = mode
            with self.assertRaises((OllamaError, ValueError)):
                self.client.complete("Extract.", "Example", {"type": "object"})

    def test_no_cloud_models_no_downloads_and_bounded_input(self) -> None:
        self.mode = "cloud"
        with self.assertRaises(OllamaError):
            self.client.complete("Extract.", "Example", {"type": "object"})
        self.assertEqual(self.requests, [])
        self.mode = "valid"
        with self.assertRaises(ValueError):
            self.client.complete("Extract.", "a" * 10000, {"type": "object"})
        self.assertEqual(self.requests, [])

    def test_synthetic_journal_flushes_started_and_completed_requests(self) -> None:
        journal = io.StringIO()
        model = RecordedModel(self.client, journal)
        model.complete("Extract.", "Example", {"type": "object"})
        entries = [json.loads(line) for line in journal.getvalue().splitlines()]
        self.assertEqual([entry["status"] for entry in entries], ["started", "completed"])
        self.assertEqual(len(model.records), 1)
        self.assertEqual(entries[0]["options"]["presence_penalty"], 0)
        self.assertEqual(entries[0]["options"]["num_ctx"], 4096)

    def test_synthetic_journal_preserves_failed_request(self) -> None:
        self.mode = "truncated"
        journal = io.StringIO()
        model = RecordedModel(self.client, journal)
        with self.assertRaises(OllamaError):
            model.complete("Extract.", "Example", {"type": "object"})
        entries = [json.loads(line) for line in journal.getvalue().splitlines()]
        self.assertEqual([entry["status"] for entry in entries], ["started", "failed"])
        self.assertIn("output budget", entries[-1]["error"])


if __name__ == "__main__":
    unittest.main()
