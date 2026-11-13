from __future__ import annotations

import ipaddress
import json
import threading
import time
from dataclasses import asdict, dataclass
from hashlib import sha256
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .runner import canonical
from .validation import array_value, object_value, text_value


class OllamaError(RuntimeError):
    pass


@dataclass(frozen=True)
class Reply:
    data: dict[str, object]
    model: str
    digest: str
    input_sha256: str
    output_sha256: str
    prompt_tokens: int
    output_tokens: int
    seconds: float

    def metrics(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if key != "data"}


class Ollama:
    def __init__(
        self,
        model: str = "qwen3.5:4b",
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 300,
    ):
        parsed = urlsplit(base_url)
        hostname = parsed.hostname or ""
        try:
            loopback = hostname == "localhost" or ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            loopback = False
        if (
            parsed.scheme != "http"
            or not loopback
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Ollama must use an unauthenticated loopback HTTP address.")
        if timeout <= 0 or timeout > 600:
            raise ValueError("Ollama timeout must be between 0 and 600 seconds.")
        self.model = text_value(model, "Model", 160)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.options: dict[str, object] = {
            "temperature": 0,
            "presence_penalty": 0,
            "num_ctx": 4096,
            "num_predict": 384,
            "seed": 42,
        }
        self._opener = build_opener(ProxyHandler({}))
        self._inference = threading.Lock()

    def _request(self, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        data = None if payload is None else canonical(payload).encode()
        request = Request(
            self.base_url + path, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with self._opener.open(
                request, timeout=self.timeout if payload is not None else 5
            ) as response:
                raw = response.read(2_000_001)
        except HTTPError as error:
            raise OllamaError(
                f"Ollama returned HTTP {error.code}. Check the installed model with 'ollama list'."
            ) from error
        except TimeoutError as error:
            raise OllamaError(
                f"Local Qwen exceeded the {self.timeout:g}-second inference timeout. Shorten the request and retry."
            ) from error
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise OllamaError(
                    f"Local Qwen exceeded the {self.timeout:g}-second inference timeout."
                ) from error
            raise OllamaError(
                "Cannot connect to local Ollama. Start Ollama, then run 'ollama list'."
            ) from error
        except ConnectionError as error:
            raise OllamaError(
                "The local Ollama connection closed during inference. Check its local status and retry."
            ) from error
        if len(raw) > 2_000_000:
            raise OllamaError("Ollama response exceeded the supported size.")
        try:
            value: object = json.loads(raw)
            result = object_value(value, "Ollama response")
        except (ValueError, UnicodeDecodeError) as error:
            raise OllamaError("Ollama returned malformed JSON.") from error
        if "error" in result:
            raise OllamaError(
                "Ollama reported a model error; check its local logs and installed models."
            )
        return result

    def models(self) -> list[dict[str, object]]:
        return [
            object_value(item, "Installed model")
            for item in array_value(self._request("/api/tags").get("models"), "Installed models")
        ]

    def selected_model(self) -> dict[str, object]:
        for model in self.models():
            if model.get("name") == self.model:
                size = model.get("size")
                if (
                    not isinstance(size, (int, float))
                    or size <= 0
                    or model.get("remote_host")
                    or model.get("remote_model")
                    or "cloud" in self.model.rsplit(":", 1)[-1].casefold()
                ):
                    raise OllamaError("Only an already-installed local model is authorized.")
                return model
        raise OllamaError(
            f"Model {self.model!r} is not installed. Run 'ollama list'; no automatic downloads are performed."
        )

    def complete(self, system: str, prompt: str, schema: dict[str, object]) -> Reply:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        if len(canonical(messages).encode()) > 3000:
            raise ValueError(
                "This subject exceeds the local context budget. Split long notes or use a separate subject."
            )
        if not self._inference.acquire(timeout=self.timeout):
            raise OllamaError("The local model is busy. Wait for the current operation and retry.")
        try:
            model = self.selected_model()
            payload: dict[str, object] = {
                "model": self.model,
                "messages": messages,
                "format": schema,
                "stream": False,
                "think": False,
                "keep_alive": "5m",
                "options": dict(self.options),
            }
            started = time.monotonic()
            result = self._request("/api/chat", payload)
            if result.get("done") is not True:
                raise OllamaError("Ollama did not complete the response.")
            if result.get("done_reason") == "length":
                raise OllamaError("Ollama exhausted its output budget. Shorten the note or retry.")
            message = object_value(result.get("message"), "Model message")
            content = text_value(message.get("content"), "Model content", 20000)
            try:
                value: object = json.loads(content)
                data = object_value(value, "Structured model output")
            except ValueError as error:
                raise OllamaError("The model did not return a valid structured object.") from error
            prompt_tokens, output_tokens = result.get("prompt_eval_count"), result.get("eval_count")
            if type(prompt_tokens) is not int or type(output_tokens) is not int:
                raise OllamaError("Ollama did not return token usage.")
            return Reply(
                data,
                self.model,
                text_value(model.get("digest"), "Model digest", 160),
                sha256(canonical(payload).encode()).hexdigest(),
                sha256(content.encode()).hexdigest(),
                prompt_tokens,
                output_tokens,
                time.monotonic() - started,
            )
        finally:
            self._inference.release()
