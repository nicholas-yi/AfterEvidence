from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .application import Application
from .ollama import OllamaError
from .store import StateChanged
from .validation import object_value, text_value

LOGGER = logging.getLogger("afterevidence.web")
STATIC = Path(__file__).parent / "static"


def create_server(application: Application, port: int = 8765) -> ThreadingHTTPServer:
    if not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535.")
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        server_version = "AfterEvidence/0.2"
        request_body = b""

        def log_message(self, format: str, *args: object) -> None:
            LOGGER.info(format, *args)

        def _headers(self, status: int, content_type: str, size: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()

        def _json(self, value: object, status: int = 200) -> None:
            payload = json.dumps(value, ensure_ascii=True).encode()
            self._headers(status, "application/json; charset=utf-8", len(payload))
            self.wfile.write(payload)

        def _authorize(self, write: bool) -> None:
            hosts = {f"127.0.0.1:{server.server_port}", f"localhost:{server.server_port}"}
            if self.headers.get("Host") not in hosts:
                raise PermissionError("Use the local application address shown in the terminal.")
            origin = self.headers.get("Origin")
            if origin is not None and origin not in {"http://" + host for host in hosts}:
                raise PermissionError("Cross-origin requests are not allowed.")
            if write and not secrets.compare_digest(
                self.headers.get("X-AfterEvidence-Token", ""), token
            ):
                raise PermissionError("Missing or invalid local request token. Reload the page.")

        def _body(self) -> dict[str, object]:
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Use Content-Type: application/json.")
            if not self.request_body:
                raise ValueError("JSON request body must be between 1 and 32768 bytes.")
            value: object = json.loads(self.request_body)
            return object_value(value, "Request")

        def _read_body(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 32768:
                raise ValueError("Request body must not exceed 32768 bytes.")
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
            path = parsed.path
            write = self.command != "GET"
            self._authorize(write)
            if self.command == "GET":
                if path == "/api/status":
                    self._json({**application.status(), "csrf_token": token})
                elif path == "/api/state":
                    query = parse_qs(parsed.query)
                    pack = query.get("pack", ["project"])[0]
                    self._json(application.state(pack))
                elif path in {"/", "/app.js", "/style.css"}:
                    name = "index.html" if path == "/" else path[1:]
                    payload = (STATIC / name).read_bytes()
                    mime = {
                        "index.html": "text/html",
                        "app.js": "text/javascript",
                        "style.css": "text/css",
                    }[name]
                    self._headers(200, mime + "; charset=utf-8", len(payload))
                    self.wfile.write(payload)
                else:
                    raise LookupError("Route does not exist.")
                return
            parts = path.strip("/").split("/")
            if (
                len(parts) == 4
                and parts[:2] == ["api", "claims"]
                and parts[3] == "review"
                and self.command == "POST"
            ):
                body = self._body()
                reject = body.get("reject")
                if not isinstance(reject, bool):
                    raise ValueError("Review action requires reject=true or false.")
                status = application.store.review_claim(parts[2], reject)
                self._json({"status": status, "source_preserved": True})
                return
            if len(parts) >= 3 and parts[:2] == ["api", "episodes"]:
                episode_id = text_value(parts[2], "Episode ID", 80)
                if self.command == "DELETE" and len(parts) == 3:
                    episode = application.store.episode(episode_id)
                    application.store.remove_episode(episode_id)
                    self._json({"status": "deleted", "pack": episode.pack})
                elif self.command == "PATCH" and len(parts) == 3:
                    body = self._body()
                    self._json(
                        application.correct(
                            episode_id, text_value(body.get("text"), "Replacement note")
                        )
                    )
                elif self.command == "POST" and len(parts) == 4 and parts[3] == "extract":
                    self._json(application.extract(episode_id))
                else:
                    raise LookupError("Episode operation does not exist.")
                return
            if self.command != "POST":
                raise LookupError("Route does not exist.")
            body = self._body()
            pack = text_value(body.get("pack"), "Scenario pack", 40)
            if path == "/api/episodes":
                self._json(
                    application.wake(
                        pack,
                        text_value(body.get("subject"), "Subject", 100),
                        text_value(body.get("text"), "Note"),
                        text_value(body.get("title", "Observation"), "Title", 160),
                        text_value(body.get("session", "notes"), "Session", 100),
                    ),
                    201,
                )
            elif path == "/api/sleep":
                self._json(application.sleep(pack, text_value(body.get("subject"), "Subject", 100)))
            elif path == "/api/ask":
                self._json(
                    application.ask(
                        pack,
                        text_value(body.get("subject"), "Subject", 100),
                        text_value(body.get("question"), "Question", 1000),
                        text_value(body.get("mode", "repaired"), "Mode", 30),
                    )
                )
            elif path == "/api/sessions/delete":
                application.store.remove_session(
                    pack, text_value(body.get("session"), "Session", 100)
                )
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

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
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
