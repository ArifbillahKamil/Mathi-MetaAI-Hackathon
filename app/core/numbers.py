"""Bounded decimal input parsing without binary floating-point arithmetic."""

from decimal import Decimal, InvalidOperation
from fractions import Fraction

Scalar = int | float | str


class NonFiniteValue(ValueError):
    """NaN and infinity cannot provide finite comparison evidence."""


def parse_scalar(value: Scalar) -> Fraction:
    """Interpret JSON numbers by their decimal representation.

    Decimal strings preserve solver precision; booleans, complex numbers,
    expressions, and excessively large representations are not supported.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("Expected a real number or a decimal string.")
    text = str(value)
    if len(text) > 256:
        raise ValueError("Scalar representations must not exceed 256 characters.")
    try:
        decimal = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("Expected a decimal number, not an expression.") from exc
    if not decimal.is_finite():
        raise NonFiniteValue("NaN and infinity are not supported.")
    if abs(decimal.as_tuple().exponent) > 1000 or abs(decimal.adjusted()) > 1000:
        raise ValueError("Scalar exponents must be between -1000 and 1000.")
    return Fraction(decimal)
