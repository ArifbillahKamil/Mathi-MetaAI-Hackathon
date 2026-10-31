"""Shared check records without mathematical or third-party dependencies."""

from dataclasses import dataclass
from enum import Enum


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True)
class CheckEvidence:
    name: str
    status: CheckStatus
    detail: str
