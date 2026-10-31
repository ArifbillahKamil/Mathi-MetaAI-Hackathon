"""Compare executed real scalars; never derive a verdict from LLM prose.

This component consumes prerequisite evidence. It does not execute routes,
prove their independence, or generate sanity checks. Missing evidence cannot
produce a verified verdict. Symbolic and non-scalar answers are not supported.
"""

from dataclasses import asdict, dataclass
from enum import Enum
from fractions import Fraction
from tokenize import TokenError

from pint import UnitRegistry
from pint.errors import PintError
from pint.util import to_units_container

from app.core.config import ScalarTolerance
from app.core.evidence import CheckEvidence, CheckStatus
from app.core.numbers import NonFiniteValue, Scalar, parse_scalar

_UNITS = UnitRegistry(non_int_type=Fraction)


class Verdict(str, Enum):
    VERIFIED = "VERIFIED"
    VERIFIED_WITH_DEVIATION = "VERIFIED_WITH_DEVIATION"
    CONFLICT = "CONFLICT"
    UNVERIFIED = "UNVERIFIED"


class Reason(str, Enum):
    SET_CARDINALITY_MISMATCH = "SET_CARDINALITY_MISMATCH"
    EXECUTION_MODULE_UNSUPPORTED = "EXECUTION_MODULE_UNSUPPORTED"
    ROUTE_GENERATION_FAILED = "ROUTE_GENERATION_FAILED"
    INDEPENDENCE_REJECTED = "INDEPENDENCE_REJECTED"
    TIGHT_AGREEMENT = "TIGHT_AGREEMENT"
    LOOSE_AGREEMENT = "LOOSE_AGREEMENT"
    NUMERIC_DISAGREEMENT = "NUMERIC_DISAGREEMENT"
    CORRECTION_REQUIRES_TIGHT = "CORRECTION_REQUIRES_TIGHT"
    ROUTE_FAILED = "ROUTE_FAILED"
    MISSING_RESULT = "MISSING_RESULT"
    UNSUPPORTED_VALUE = "UNSUPPORTED_VALUE"
    NONFINITE_VALUE = "NONFINITE_VALUE"
    UNIT_CHECK_UNAVAILABLE = "UNIT_CHECK_UNAVAILABLE"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    UNSUPPORTED_UNIT_CONVERSION = "UNSUPPORTED_UNIT_CONVERSION"
    INDEPENDENCE_NOT_ESTABLISHED = "INDEPENDENCE_NOT_ESTABLISHED"
    SANITY_NOT_RUN = "SANITY_NOT_RUN"
    SANITY_FAILED = "SANITY_FAILED"
    MISSING_ERROR_ESTIMATE = "MISSING_ERROR_ESTIMATE"
    INVALID_ERROR_ESTIMATE = "INVALID_ERROR_ESTIMATE"
    DEVIATION_CAUSE_MISSING = "DEVIATION_CAUSE_MISSING"


@dataclass(frozen=True)
class ScalarRoute:
    """Wire-level result of one execution; absolute_error uses the route unit.

    `absolute_error` must come from executed method evidence, not an LLM guess.
    Exact numeric computations may explicitly report zero. Missing units are
    never inferred to be dimensionless; use the string "dimensionless".
    """

    value: Scalar | None = None
    unit: str | None = None
    absolute_error: Scalar | None = None
    execution_error: str | None = None


@dataclass(frozen=True)
class ComparisonContext:
    expected_unit: str | None
    independence: CheckEvidence | None = None
    # None means not run; an empty tuple explicitly means no bounds apply.
    sanity_checks: tuple[CheckEvidence, ...] | None = None
    corrected_after_conflict: bool = False
    deviation_cause: str | None = None


@dataclass(frozen=True)
class NumericEvidence:
    """Exact rational strings, in the expected unit unless dimensionless."""

    unit: str
    route_a: str
    route_b: str
    absolute_difference: str
    relative_difference: str
    error_budget: str
    tight_limit: str
    loose_limit: str


@dataclass(frozen=True)
class ComparisonResult:
    verdict: Verdict
    reason: Reason
    detail: str
    context: ComparisonContext
    evidence: NumericEvidence | None = None

    def to_dict(self) -> dict:
        """Return JSON-safe data, including prerequisite evidence."""
        return asdict(self)


def compare_scalars(
    route_a: ScalarRoute,
    route_b: ScalarRoute,
    *,
    tolerance: ScalarTolerance,
    context: ComparisonContext,
) -> ComparisonResult:
    """Compare finite real scalars using multiplicative unit conversions.

    A limit is min(atol + rtol * max(|A|, |B|), error_A + error_B).
    Sanity checks and independence evidence can only withhold or lower a
    verdict. A corrected answer must meet the tight limit.
    """
    def result(verdict, reason, detail, evidence=None):
        return ComparisonResult(verdict, reason, detail, context, evidence)

    unverified = Verdict.UNVERIFIED
    if route_a.execution_error is not None or route_b.execution_error is not None:
        return result(unverified, Reason.ROUTE_FAILED, "At least one route failed to execute.")
    if route_a.value is None or route_b.value is None:
        return result(unverified, Reason.MISSING_RESULT, "Both executed results are required.")
    if not all((context.expected_unit, route_a.unit, route_b.unit)):
        return result(unverified, Reason.UNIT_CHECK_UNAVAILABLE, "Expected and route units are required.")

    try:
        expected = _UNITS.Unit(context.expected_unit)
        source_units = [_UNITS.Unit(route.unit) for route in (route_a, route_b)]
    except (PintError, ValueError, TypeError, AssertionError, TokenError, SyntaxError, ArithmeticError):
        return result(unverified, Reason.UNIT_CHECK_UNAVAILABLE, "A unit could not be interpreted.")

    # Test both against the expectation, even if both routes share a wrong unit.
    if any(unit.dimensionality != expected.dimensionality for unit in source_units):
        return result(Verdict.CONFLICT, Reason.UNIT_MISMATCH, "A route has the wrong physical dimension.")
    if any(
        Fraction(power).denominator != 1
        for unit in (expected, *source_units)
        for power in to_units_container(unit).values()
    ):
        return result(unverified, Reason.UNSUPPORTED_UNIT_CONVERSION, "Fractional unit powers require separate conversion-error handling.")

    try:
        values = [parse_scalar(route.value) for route in (route_a, route_b)]
    except NonFiniteValue:
        return result(unverified, Reason.NONFINITE_VALUE, "NaN and infinity cannot establish agreement.")
    except (ValueError, TypeError):
        return result(unverified, Reason.UNSUPPORTED_VALUE, "Only finite real decimal scalars are supported.")

    # Uncertainty scales like a difference. Reject offset/log conversions until
    # explicit delta-unit handling exists, rather than treating error as a value.
    try:
        zeros = [_UNITS.Quantity(Fraction(0), unit).to(expected).magnitude for unit in source_units]
        scales = [_UNITS.Quantity(Fraction(1), unit).to(expected).magnitude for unit in source_units]
        twos = [_UNITS.Quantity(Fraction(2), unit).to(expected).magnitude for unit in source_units]
        if any(not isinstance(number, (Fraction, int)) for number in (*zeros, *scales, *twos)):
            return result(unverified, Reason.UNSUPPORTED_UNIT_CONVERSION, "Conversion requires a factor outside exact rational arithmetic.")
        if any(zero != 0 or two != 2 * scale for zero, scale, two in zip(zeros, scales, twos)):
            return result(unverified, Reason.UNSUPPORTED_UNIT_CONVERSION, "Only multiplicative unit conversions are supported.")
        values = [value * scale for value, scale in zip(values, scales)]
    except (PintError, ValueError, TypeError, ArithmeticError):
        return result(unverified, Reason.UNSUPPORTED_UNIT_CONVERSION, "Unit conversion could not produce scalar evidence.")

    if context.sanity_checks is not None and any(
        check.status == CheckStatus.FAIL for check in context.sanity_checks
    ):
        return result(Verdict.CONFLICT, Reason.SANITY_FAILED, "At least one executed sanity check failed.")
    if context.independence is None or context.independence.status != CheckStatus.PASS:
        return result(unverified, Reason.INDEPENDENCE_NOT_ESTABLISHED, "Independent execution evidence is required.")
    if context.sanity_checks is None or any(
        check.status != CheckStatus.PASS for check in context.sanity_checks
    ):
        return result(unverified, Reason.SANITY_NOT_RUN, "All applicable sanity checks must complete.")

    if route_a.absolute_error is None or route_b.absolute_error is None:
        return result(unverified, Reason.MISSING_ERROR_ESTIMATE, "Both methods must supply an absolute error estimate.")
    try:
        errors = [parse_scalar(route.absolute_error) for route in (route_a, route_b)]
        if any(error < 0 for error in errors):
            raise ValueError("Negative error estimate.")
        error_budget = sum(error * abs(scale) for error, scale in zip(errors, scales))
    except (ValueError, TypeError):
        return result(unverified, Reason.INVALID_ERROR_ESTIMATE, "Error estimates must be finite and non-negative.")

    a, b = values
    difference = abs(a - b)
    magnitude = max(abs(a), abs(b))
    relative = difference / magnitude if magnitude else Fraction(0)
    tight_abs, tight_rel, loose_abs, loose_rel = tolerance.fractions()
    tight = min(tight_abs + tight_rel * magnitude, error_budget)
    loose = min(loose_abs + loose_rel * magnitude, error_budget)
    evidence = NumericEvidence(
        str(expected), str(a), str(b), str(difference), str(relative),
        str(error_budget), str(tight), str(loose),
    )
    if difference <= tight:
        return result(Verdict.VERIFIED, Reason.TIGHT_AGREEMENT, "Results agree within the tight limit.", evidence)
    if context.corrected_after_conflict:
        return result(Verdict.CONFLICT, Reason.CORRECTION_REQUIRES_TIGHT, "A corrected result must meet the tight limit.", evidence)
    if difference <= loose:
        if not context.deviation_cause or not context.deviation_cause.strip():
            return result(unverified, Reason.DEVIATION_CAUSE_MISSING, "Loose agreement needs a documented likely cause.", evidence)
        return result(Verdict.VERIFIED_WITH_DEVIATION, Reason.LOOSE_AGREEMENT, "Results agree only within the loose limit.", evidence)
    return result(Verdict.CONFLICT, Reason.NUMERIC_DISAGREEMENT, "The difference exceeds the loose limit.", evidence)
