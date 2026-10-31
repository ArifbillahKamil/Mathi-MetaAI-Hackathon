"""Stateless Meta Chat Completions client using the Python standard library.

Verified against https://dev.meta.ai/docs/protocols/chat-completions and
https://dev.meta.ai/docs/structured-output on 2026-10-31. No automatic retries.
"""

from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import shlex
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.core.independence import BlindRequest


ENDPOINT = "https://api.meta.ai/v1/chat/completions"
STANDARD_MODELS = {"muse-spark-1.3", "muse-spark-1.2", "muse-spark-1.1"}
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class MetaAPIError(RuntimeError):
    """Safe error codes; HTTP bodies and credentials are never interpolated."""

    def __init__(self, code: str, *, status: int | None = None):
        self.code, self.status = code, status
        super().__init__(f"{code}" + (f" (HTTP {status})" if status else ""))


@dataclass(frozen=True)
class MetaSettings:
    api_key: str = field(repr=False)
    model: str = "muse-spark-1.3"
    timeout_seconds: float = 45.0

    def __post_init__(self):
        if not isinstance(self.api_key, str) or not self.api_key.strip() or any(c.isspace() for c in self.api_key):
            raise ValueError("META_API_KEY must contain a nonempty credential without whitespace.")
        if self.model not in STANDARD_MODELS:
            raise ValueError("Select a documented Standard-mode Muse Spark model.")
        if isinstance(self.timeout_seconds, bool) or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("API timeout must be finite and positive.")

    @classmethod
    def from_dotenv(cls, path: str | Path | None = None):
        """Load selected settings without putting secrets in os.environ.

        Accept simple KEY=value lines with quotes/comments; no interpolation or
        command execution. Environment settings override dotenv settings.
        """
        path = Path(path) if path is not None else Path(__file__).resolve().parents[2] / ".env"
        allowed = {"META_API_KEY", "MODEL_API_KEY", "META_MODEL"}
        values = {}
        if path.is_file():
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                name, separator, value = line.partition("=")
                name = name.strip()
                if separator and name in allowed:
                    try:
                        parts = shlex.split(value, comments=True, posix=True)
                    except ValueError:
                        raise ValueError(f"Invalid dotenv syntax for {name}.") from None
                    if len(parts) > 1:
                        raise ValueError(f"Invalid dotenv value for {name}.")
                    values[name] = parts[0] if parts else ""
        key = (os.environ.get("META_API_KEY") or os.environ.get("MODEL_API_KEY")
               or values.get("META_API_KEY") or values.get("MODEL_API_KEY"))
        if not key:
            raise ValueError("Set META_API_KEY in .env or the environment.")
        model = os.environ.get("META_MODEL") or values.get("META_MODEL") or "muse-spark-1.3"
        return cls(api_key=key, model=model)


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    usage: dict[str, int]
    request_hash: str
    response_id: str | None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class MetaClient:
    def __init__(self, settings: MetaSettings):
        self.settings = settings

    def complete(
        self, request: BlindRequest, *, max_completion_tokens: int = 2048,
        reasoning_effort: str = "low", schema: dict | None = None,
        schema_name: str = "mathi_output",
        timeout_seconds: float | None = None,
    ) -> Completion:
        if isinstance(max_completion_tokens, bool) or not isinstance(max_completion_tokens, int) or max_completion_tokens <= 0:
            raise ValueError("Completion token limit must be a positive integer.")
        if reasoning_effort not in {"minimal", "low", "medium", "high", "xhigh"}:
            raise ValueError("Unsupported reasoning effort.")
        if timeout_seconds is not None and (
            isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0
        ):
            raise ValueError("Request timeout must be finite and positive.")
        if not isinstance(request, BlindRequest) or not request.messages:
            raise ValueError("A nonempty fresh request is required.")
        if any(message.role not in {"system", "user"} or not isinstance(message.content, str) for message in request.messages):
            raise ValueError("Fresh requests must contain only system/user text messages.")
        payload = {
            "model": self.settings.model,
            **request.to_dict(),
            "max_completion_tokens": max_completion_tokens,
            "reasoning_effort": reasoning_effort,
            "stream": False,
        }
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            }
        # No headers or credentials enter the fingerprint or audit payload.
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False).encode("utf-8")
        raw = self._post(encoded) if timeout_seconds is None else self._post(encoded, timeout_seconds=timeout_seconds)
        try:
            choice = raw["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise MetaAPIError("INCOMPLETE_COMPLETION")
            message = choice["message"]
            if message.get("refusal"):
                raise MetaAPIError("MODEL_REFUSAL")
            text = message["content"]
            if message.get("tool_calls") or not isinstance(text, str) or not text.strip():
                raise MetaAPIError("UNEXPECTED_COMPLETION")
            usage = raw.get("usage", {})
            if not isinstance(usage, dict):
                raise ValueError("Invalid usage data.")
            counts = {}
            for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(name)
                if value is not None:
                    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                        raise ValueError("Invalid usage count.")
                    counts[name] = value
            return Completion(text, raw.get("model", self.settings.model), counts,
                              sha256(encoded).hexdigest(), raw.get("id"))
        except (KeyError, IndexError, TypeError, ValueError):
            raise MetaAPIError("INVALID_API_RESPONSE") from None

    def _post(self, encoded: bytes, *, timeout_seconds: float | None = None) -> dict:
        request = Request(ENDPOINT, data=encoded, method="POST", headers={
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json", "Accept": "application/json",
        })
        try:
            timeout = min(self.settings.timeout_seconds, timeout_seconds) if timeout_seconds is not None else self.settings.timeout_seconds
            with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise MetaAPIError("API_RESPONSE_TOO_LARGE")
            parsed = json.loads(body)
            if not isinstance(parsed, dict):
                raise MetaAPIError("INVALID_API_RESPONSE")
            return parsed
        except HTTPError as exc:
            status = exc.code
            exc.close()
            raise MetaAPIError("META_HTTP_ERROR", status=status) from None
        except (URLError, TimeoutError, OSError):
            raise MetaAPIError("META_CONNECTION_FAILED") from None
        except (ValueError, UnicodeError):
            raise MetaAPIError("INVALID_API_RESPONSE") from None
