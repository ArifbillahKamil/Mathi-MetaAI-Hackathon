"""Ideal vertical lifting: potential energy versus integrated lifting force."""

from fractions import Fraction
from app.core.independence import Method
from pint.errors import PintError
from tokenize import TokenError
from app.core.problem import AnswerShape, Domain, ProblemClass, Task
from app.modules.calculus import sanity_checks, tolerance
from app.modules.drivers.lift import BASE_UNITS, UNITS, normalize
from app.sandbox.contracts import VerificationSpec

CONTRACT = (
    "Return only GeneratedRoute JSON with a code string. Compute work by the lifting force for "
    "the confirmed ideal constant-speed vertical motion, with constant gravity and no losses. "
    "Use only pint, sympy, and (for force_balance only) scipy.integrate. "
    "Create u=pint.UnitRegistry() with no arguments; the worker supplies exact unit conversions. "
    "Create every given quantity from sympy.Rational(original_value_string) and its original unit, "
    "then convert mass to kg, gravity to m/s**2, and height_change to m. "
    "For energy_balance create symbols named exactly mass, gravity, height_change. "
    "Call sympy.expand(mass*gravity*height_change) exactly once for the potential-energy change. "
    "Substitute the converted exact quantity magnitudes into that returned symbolic expression. "
    "Use the exact rational evaluated result without float conversion, and exact zero method error. "
    "For force_balance compute weight=float(mass_quantity.magnitude)*float(gravity_quantity.magnitude) "
    "from the converted quantities; integrate lambda position: weight with scipy.integrate.quad "
    "exactly once from 0 to float(height_quantity.magnitude). Return both solver outputs unchanged. "
    "Assign result={'quantity': u.Quantity(value, 'joule'), 'absolute_error': u.Quantity(error, 'joule')}. "
    "Do not replace, round, or hard-code the computed result or solver error. Do not use another solver. "
    "No eval, sympify, parse_expr, lambdify, file/network access, reflection, exception handlers, "
    "or module-attribute assignment."
)


def supports(problem):
    return problem.problem_class == ProblemClass.ENGINEERING and problem.task == Task.WORK_ENERGY


def _parameters(problem):
    givens = {given.name: given for given in problem.givens}
    if set(givens) != set(BASE_UNITS):
        raise ValueError('Ideal lifting requires exactly mass, gravity, and height_change with explicit units.')
    return {key: value for name, given in givens.items()
            for key, value in ((name, given.value), (name + '_unit', given.unit))}


def plan(confirmed, planned):
    problem = confirmed.problem
    if (not supports(problem) or problem.answer_shape != AnswerShape.SCALAR or problem.domain != Domain.REAL
            or problem.expression != 'vertical_lift_constant_speed' or problem.unknowns != ('work',) or problem.variables):
        raise ValueError('Only work by an ideal constant-speed vertical lifting force is supported.')
    if {planned.method_a, planned.method_b} != {Method.ENERGY_BALANCE, Method.FORCE_BALANCE}:
        raise ValueError('Ideal lifting requires energy_balance and force_balance.')
    try:
        factor = UNITS.Quantity(1, problem.expected_unit).to('joule').magnitude
        zero = UNITS.Quantity(0, problem.expected_unit).to('joule').magnitude
        if not isinstance(factor, (int, Fraction)) or factor <= 0 or zero != 0:
            raise ValueError('The expected result must use an energy unit.')
        normalize(_parameters(problem))
    except (PintError, TypeError, LookupError, TokenError, SyntaxError, ArithmeticError) as exc:
        raise ValueError('Givens and expected result require compatible physical units.') from exc


def _route(problem, method):
    return VerificationSpec('lift', tuple({'method': method.value, **_parameters(problem)}.items()))


def route_a(confirmed, planned):
    return _route(confirmed.problem, planned.method_a)


def route_b(confirmed, planned):
    return _route(confirmed.problem, planned.method_b)
