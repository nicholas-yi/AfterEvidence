from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlsplit

from .application import Application
from .ollama import OllamaError
from .store import StateChanged
from .validation import object_value, text_value

LOGGER = logging.getLogger("afterevidence.web")
STATIC = Path(__file__).parent / "static"


MIME = {"index.html": "text/html", "app.js": "text/javascript", "style.css": "text/css"}
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
)
MAX_BODY = 32768


class LocalHandler(BaseHTTPRequestHandler):
    """The local workspace API and its static files; one subclass per server holds its state."""

    server_version = "AfterEvidence/0.2"
    request_body = b""
    application: Application
    token: str

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.info(format, *args)

    def _headers(self, status: int, content_type: str, size: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()

    def _json(self, value: object, status: int = 200) -> None:
        payload = json.dumps(value, ensure_ascii=True).encode()
        self._headers(status, "application/json; charset=utf-8", len(payload))
        self.wfile.write(payload)

    def _authorize(self, write: bool) -> None:
        port = cast(HTTPServer, self.server).server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in hosts:
            raise PermissionError("Use the local application address shown in the terminal.")
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {"http://" + host for host in hosts}:
            raise PermissionError("Cross-origin requests are not allowed.")
        if write and not secrets.compare_digest(
            self.headers.get("X-AfterEvidence-Token", ""), self.token
        ):
            raise PermissionError("Missing or invalid local request token. Reload the page.")

    def _body(self) -> dict[str, object]:
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Use Content-Type: application/json.")
        if not self.request_body:
            raise ValueError(f"JSON request body must be between 1 and {MAX_BODY} bytes.")
        value: object = json.loads(self.request_body)
        return object_value(value, "Request")

    def _read_body(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 <= length <= MAX_BODY:
            raise ValueError(f"Request body must not exceed {MAX_BODY} bytes.")
        previous = self.connection.gettimeout()
        self.connection.settimeout(5)
        try:
            self.request_body = self.rfile.read(length)
        finally:
            self.connection.settimeout(previous)
        if len(self.request_body) != length:
            raise ValueError("Request body was incomplete.")

    def _route(self) -> None:
        parsed = urlsplit(self.path)
        self._authorize(write=self.command != "GET")
        if self.command == "GET":
            self._get(parsed.path, parsed.query)
            return
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "claims"] and parts[3] == "review":
            if self.command != "POST":
                raise LookupError("Route does not exist.")
            self._review(parts[2])
        elif len(parts) >= 3 and parts[:2] == ["api", "episodes"]:
            self._episode(text_value(parts[2], "Episode ID", 80), parts[3:])
        elif self.command == "POST":
            self._action(parsed.path)
        else:
            raise LookupError("Route does not exist.")

    def _get(self, path: str, query: str) -> None:
        if path == "/api/status":
            self._json({**self.application.status(), "csrf_token": self.token})
        elif path == "/api/state":
            self._json(self.application.state(parse_qs(query).get("pack", ["project"])[0]))
        elif path in {"/", "/app.js", "/style.css"}:
            name = "index.html" if path == "/" else path[1:]
            payload = (STATIC / name).read_bytes()
            self._headers(200, MIME[name] + "; charset=utf-8", len(payload))
            self.wfile.write(payload)
        else:
            raise LookupError("Route does not exist.")

    def _review(self, claim_id: str) -> None:
        reject = self._body().get("reject")
        if not isinstance(reject, bool):
            raise ValueError("Review action requires reject=true or false.")
        status = self.application.store.review_claim(claim_id, reject)
        self._json({"status": status, "source_preserved": True})

    def _episode(self, episode_id: str, rest: list[str]) -> None:
        store = self.application.store
        if self.command == "DELETE" and not rest:
            episode = store.episode(episode_id)
            store.remove_episode(episode_id)
            self._json({"status": "deleted", "pack": episode.pack})
        elif self.command == "PATCH" and not rest:
            text = text_value(self._body().get("text"), "Replacement note")
            self._json(self.application.correct(episode_id, text))
        elif self.command == "POST" and rest == ["extract"]:
            self._json(self.application.extract(episode_id))
        else:
            raise LookupError("Episode operation does not exist.")

    def _action(self, path: str) -> None:
        body, app = self._body(), self.application
        pack = text_value(body.get("pack"), "Scenario pack", 40)

        def field(name: str, label: str, limit: int, default: str | None = None) -> str:
            return text_value(body.get(name, default) if default else body.get(name), label, limit)

        if path == "/api/episodes":
            note = text_value(body.get("text"), "Note")
            subject = field("subject", "Subject", 100)
            title = field("title", "Title", 160, "Observation")
            self._json(
                app.wake(pack, subject, note, title, field("session", "Session", 100, "notes")),
                201,
            )
        elif path == "/api/sleep":
            self._json(app.sleep(pack, field("subject", "Subject", 100)))
        elif path == "/api/ask":
            subject, question = (
                field("subject", "Subject", 100),
                field("question", "Question", 1000),
            )
            self._json(app.ask(pack, subject, question, field("mode", "Mode", 30, "repaired")))
        elif path == "/api/sessions/delete":
            app.store.remove_session(pack, field("session", "Session", 100))
            self._json({"status": "deleted", "pack": pack})
        else:
            raise LookupError("Route does not exist.")

    def _handle(self) -> None:
        try:
            self._read_body()
            self._route()
        except PermissionError as error:
            self._json({"error": str(error)}, 403)
        except StateChanged as error:
            self._json({"error": str(error), "retryable": True}, 409)
        except OllamaError as error:
            LOGGER.warning("Local model operation failed: %s", error)
            self._json({"error": str(error), "retryable": True}, 502)
        except LookupError as error:
            self._json({"error": str(error)}, 404)
        except (ValueError, UnicodeDecodeError) as error:
            self._json({"error": str(error)}, 400)
        except TimeoutError:
            self._json({"error": "Request body timed out."}, 408)
        except sqlite3.Error:
            LOGGER.exception("Application database operation failed")
            self._json({"error": "Local database operation failed. See the server log."}, 500)
        except (BrokenPipeError, ConnectionResetError):
            LOGGER.info("Browser disconnected during a local operation.")

    do_GET = _handle
    do_POST = _handle
    do_PATCH = _handle
    do_DELETE = _handle

    def do_OPTIONS(self) -> None:
        self._json({"error": "Cross-origin preflight is not supported."}, 405)


def create_server(application: Application, port: int = 8765) -> ThreadingHTTPServer:
    if not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535.")
    handler = type(
        "Handler",
        (LocalHandler,),
        {"application": application, "token": secrets.token_urlsafe(32)},
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def serve(application: Application, port: int = 8765) -> None:
    server = create_server(application, port)
    LOGGER.info(
        "AfterEvidence: http://127.0.0.1:%s (local only; Ctrl+C to stop)", server.server_port
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Stopping the local application.")
    finally:
        server.server_close()
