"""Bounded local execution backend; development only, not OS isolation."""

from dataclasses import asdict, dataclass
from enum import Enum
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from app.core.comparator import ScalarRoute
from app.sandbox.guard import check_code
from app.sandbox.contracts import VerificationSpec


class ExecutionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    REJECTED = "REJECTED"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    TIMEOUT = "TIMEOUT"
    OUTPUT_LIMIT = "OUTPUT_LIMIT"
    INVALID_RESULT = "INVALID_RESULT"


@dataclass(frozen=True)
class ExecutionLimits:
    max_output_bytes: int = 65536
    max_source_bytes: int = 32768

    def __post_init__(self):
        for value in (self.max_output_bytes, self.max_source_bytes):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("Execution size limits must be positive integers.")


@dataclass(frozen=True)
class ExecutionResult:
    status: ExecutionStatus
    code: str
    stdout: str
    stderr: str
    error: str | None
    result: dict | None
    elapsed_seconds: float
    limits: ExecutionLimits
    timeout_seconds: float
    backend: str = "local-development"
    method_evidence: dict | None = None

    def to_dict(self):
        return asdict(self)

    def as_scalar_route(self) -> ScalarRoute:
        if self.status != ExecutionStatus.SUCCESS:
            return ScalarRoute(execution_error=f"{self.status.value}: {self.error}")
        return ScalarRoute(**self.result)


def _child_environment() -> dict[str, str]:
    # Construct, rather than copy and redact, so future secret names are excluded.
    result = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "TEMP", "TMP") if key in os.environ}
    result.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    return result


def run_code(
    code: str, timeout: float = 10.0, limits: ExecutionLimits | None = None,
    *, verification: VerificationSpec | None = None,
) -> ExecutionResult:
    """Execute pre-checked code with a deadline and a shared stdout/stderr cap.

    Local execution has no enforced memory limit or network isolation. Never
    expose this backend as a public multi-tenant code-execution service.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be finite and positive.")
    limits = limits if limits is not None else ExecutionLimits()
    started = time.monotonic()

    def finish(status, *, stdout="", stderr="", error=None, result=None, method_evidence=None):
        return ExecutionResult(status, code, stdout, stderr, error, result,
                               time.monotonic() - started, limits, timeout, method_evidence=method_evidence)

    checked = check_code(code, max_source_bytes=limits.max_source_bytes)
    if not checked.allowed:
        return finish(ExecutionStatus.REJECTED, error=checked.reason)
    payload = json.dumps({"code": code, **asdict(limits),
                          "verification": verification.to_dict() if verification else None}).encode("utf-8")
    worker = Path(__file__).with_name("worker.py").resolve()
    with tempfile.TemporaryDirectory(prefix="mathi-route-") as workdir:
        try:
            process = subprocess.Popen(
                [sys.executable, "-I", "-B", str(worker)], cwd=workdir,
                env=_child_environment(), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except OSError:
            return finish(ExecutionStatus.RUNTIME_ERROR, error="PROCESS_START_FAILED")
        streams = [bytearray(), bytearray()]
        lock = threading.Lock()
        exceeded = threading.Event()

        def drain(stream, target):
            try:
                while chunk := stream.read(4096):
                    with lock:
                        available = max(0, limits.max_output_bytes - sum(map(len, streams)))
                        target.extend(chunk[:available])
                        if len(chunk) > available:
                            exceeded.set()
                    if exceeded.is_set():
                        process.kill()
                        break
            finally:
                stream.close()

        readers = [threading.Thread(target=drain, args=(stream, target), daemon=True)
                   for stream, target in zip((process.stdout, process.stderr), streams)]
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            process.stdin.write(payload)
            process.stdin.close()
            process.wait(timeout=max(0.001, timeout - (time.monotonic() - started)))
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.wait()
        except (BrokenPipeError, OSError):
            process.kill()
            process.wait()
        finally:
            if not process.stdin.closed:
                process.stdin.close()
            for reader in readers:
                reader.join()
        raw_stdout, raw_stderr = [bytes(value).decode("utf-8", errors="replace") for value in streams]
        if timed_out:
            return finish(ExecutionStatus.TIMEOUT, error="EXECUTION_TIMEOUT", stderr=raw_stderr)
        if exceeded.is_set():
            return finish(ExecutionStatus.OUTPUT_LIMIT, error="OUTPUT_LIMIT_EXCEEDED", stderr=raw_stderr)
        if process.returncode != 0:
            return finish(ExecutionStatus.RUNTIME_ERROR, error="WORKER_FAILED", stderr=raw_stderr)
        try:
            record = json.loads(raw_stdout)
            status = ExecutionStatus(record["status"])
            if status == ExecutionStatus.SUCCESS:
                value = record["result"]
                collection = isinstance(value, dict) and set(value) == {'values', 'unit', 'absolute_errors', 'answer_shape'}
                if collection:
                    if (value['answer_shape'] != 'set' or not isinstance(value['unit'], str)
                            or not isinstance(value['values'], list) or not isinstance(value['absolute_errors'], list)
                            or len(value['values']) > 16 or len(value['values']) != len(value['absolute_errors'])
                            or any(not isinstance(item, str) for item in value['values'] + value['absolute_errors'])):
                        raise ValueError('Invalid worker answer set.')
                elif not isinstance(value, dict) or set(value) != {"value", "unit", "absolute_error"}:
                    raise ValueError("Invalid worker result.")
                elif not isinstance(value["value"], str) or not isinstance(value["unit"], str):
                    raise ValueError("Invalid worker scalar.")
                elif value["absolute_error"] is not None and not isinstance(value["absolute_error"], str):
                    raise ValueError("Invalid worker error estimate.")
            return finish(status, stdout=record.get("stdout", ""), stderr=record.get("stderr", "") + raw_stderr,
                          error=record.get("error"), result=record.get("result"), method_evidence=record.get("method_evidence"))
        except (ValueError, TypeError, KeyError):
            return finish(ExecutionStatus.INVALID_RESULT, error="INVALID_WORKER_RESPONSE", stderr=raw_stderr)
