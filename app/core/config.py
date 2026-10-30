"""Explicit tolerance configuration; no uncalibrated production defaults."""

from dataclasses import dataclass
from fractions import Fraction

from app.core.numbers import Scalar, parse_scalar


@dataclass(frozen=True)
class ScalarTolerance:
    """Absolute tolerances use the expected unit; relative ones are unitless.

    Callers must supply values calibrated for the problem and method. Both
    thresholds are additionally capped by the sum of route error estimates.
    """

    tight_absolute: Scalar
    tight_relative: Scalar
    loose_absolute: Scalar
    loose_relative: Scalar

    def __post_init__(self) -> None:
        tight_abs, tight_rel, loose_abs, loose_rel = self.fractions()
        if min(tight_abs, tight_rel, loose_abs, loose_rel) < 0:
            raise ValueError("Tolerances must be non-negative.")
        if loose_abs < tight_abs or loose_rel < tight_rel:
            raise ValueError("Loose tolerances must not be tighter than tight ones.")

    def fractions(self) -> tuple[Fraction, Fraction, Fraction, Fraction]:
        return tuple(parse_scalar(value) for value in (
            self.tight_absolute, self.tight_relative,
            self.loose_absolute, self.loose_relative,
        ))
