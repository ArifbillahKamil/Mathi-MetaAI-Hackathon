"""Schema validation and audit records shared by intake and planning."""

from dataclasses import dataclass
import json
from typing import TypeVar

from pydantic import BaseModel

from app.core.independence import BlindRequest
from app.llm.meta import Completion, MetaAPIError, MetaClient

Record = TypeVar("Record", bound=BaseModel)


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate JSON key.")
        result[name] = value
    return result


def _reject_nonfinite(value):
    raise ValueError("Nonfinite JSON number.")


def parse_json(text: str, *, max_characters: int = 65536):
    if not isinstance(text, str) or len(text) > max_characters:
        raise ValueError("Structured response exceeds the supported size.")
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_nonfinite)


def parse_record(text: str, record_type: type[Record]) -> Record:
    data = parse_json(text)
    return record_type.model_validate_json(json.dumps(data, allow_nan=False), strict=True)


@dataclass(frozen=True)
class ModelAttempt:
    stage: str
    request: BlindRequest
    completion: Completion | None
    parsed: BaseModel | None
    error: str | None

    def to_dict(self):
        return {
            "stage": self.stage, "request": self.request.to_dict(),
            "request_fingerprint": self.request.fingerprint,
            "transport_request_hash": self.completion.request_hash if self.completion else None,
            "response_id": self.completion.response_id if self.completion else None,
            "model": self.completion.model if self.completion else None,
            "usage": dict(self.completion.usage) if self.completion else {},
            "raw_response": self.completion.text if self.completion else None,
            "parsed": self.parsed.model_dump(mode="json") if self.parsed else None,
            "error": self.error,
        }


def request_record(
    client: MetaClient, request: BlindRequest, record_type: type[Record], *, stage: str,
    timeout_seconds: float | None = None,
) -> tuple[Record | None, ModelAttempt]:
    completion = None
    try:
        options = {'timeout_seconds': timeout_seconds} if timeout_seconds is not None else {}
        completion = client.complete(
            request, schema=record_type.model_json_schema(), schema_name=record_type.__name__,
            max_completion_tokens=2048, reasoning_effort="low",
            **options,
        )
        parsed = parse_record(completion.text, record_type)
        return parsed, ModelAttempt(stage, request, completion, parsed, None)
    except MetaAPIError as exc:
        error = exc.code + (f":HTTP_{exc.status}" if exc.status is not None else "")
    except (ValueError, RecursionError):
        error = "INVALID_STRUCTURED_OUTPUT"
    return None, ModelAttempt(stage, request, completion, None, error)
