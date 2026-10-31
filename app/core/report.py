"""Deterministic presentation choices after a comparator verdict."""

from fractions import Fraction
from pint import UnitRegistry
from app.core.numbers import parse_scalar

_UNITS = UnitRegistry(non_int_type=Fraction)


def select_answer_route(executions, expected_unit):
    """Prefer the smaller audited error in a common unit; never set a verdict."""
    def uncertainty(label):
        result = executions[label].result
        errors = result['absolute_errors'] if 'absolute_errors' in result else [result['absolute_error']]
        return max((_UNITS.Quantity(parse_scalar(error), result['unit']).to(expected_unit).magnitude for error in errors), default=Fraction(0))

    return min(executions, key=uncertainty)
