"""Trusted module-selected execution verification settings, never model fields."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class VerificationSpec:
    driver: str
    parameters: tuple[tuple[str, str], ...]

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.driver):
            raise ValueError("Invalid trusted driver name.")
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in self.parameters):
            raise ValueError("Driver parameters must be strings.")
        if len(dict(self.parameters)) != len(self.parameters):
            raise ValueError("Duplicate driver parameters.")

    def to_dict(self):
        return {"driver": self.driver, "parameters": dict(self.parameters)}
