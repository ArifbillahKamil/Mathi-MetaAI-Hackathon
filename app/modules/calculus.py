"""First calculus execution capability: finite dimensionless polynomials."""

from decimal import Decimal, ROUND_CEILING, localcontext
from fractions import Fraction

from pint import UnitRegistry

from app.core.config import ScalarTolerance
from app.core.evidence import CheckEvidence, CheckStatus
from app.core.independence import Method
from app.core.numbers import parse_scalar
from app.core.problem import AnswerShape, Domain, ProblemClass, Task
from app.modules.drivers.polynomial import Polynomial
from app.sandbox.contracts import VerificationSpec

_UNITS = UnitRegistry(non_int_type=Fraction)
CONTRACT = (
    "Return only the GeneratedRoute JSON schema with one code string, no Markdown. "
    "Write self-contained Python. Use Pint UnitRegistry() with no arguments. "
    "Assign result={'quantity': u.Quantity(value, 'dimensionless'), "
    "'absolute_error': u.Quantity(error, 'dimensionless')}, using your registry variable's name. "
    "Do not round, hard-code, or replace the solver result or its error. "
    "For numerical_quadrature import quad from scipy.integrate, implement the confirmed integrand "
    "as a Python function/lambda, and call quad(function, lower_bound, upper_bound) exactly once. "
    "Use both returned value and returned error unchanged. Imports may be math, pint, numpy, scipy.integrate. "
    "For symbolic_integration import sympy, construct the confirmed expression using Symbol/Integer/Rational "
    "and arithmetic, and call sympy.integrate(expression, (symbol, lower_bound, upper_bound)) exactly once. "
    "Keep its exact rational result as the quantity magnitude; do not cast it to float. "
    "Use an exact zero method error for the exact symbolic result. Imports may be math, pint, sympy. "
    "Use Rational for decimal coefficients or bounds in symbolic code. "
    "Never use sympify, parse_expr, lambdify, eval, exec, file/network access, reflective attributes, "
    "exception handlers, or module-attribute assignment. Do not use another mathematical solver."
)


def supports(problem):
    return problem.problem_class == ProblemClass.CALCULUS and problem.task == Task.DEFINITE_INTEGRAL


def plan(confirmed, planned):
    problem = confirmed.problem
    if not supports(problem) or problem.domain != Domain.REAL or problem.answer_shape != AnswerShape.SCALAR:
        raise ValueError("Only real scalar definite integrals are currently executable.")
    if problem.expected_unit != 'dimensionless' or len(problem.variables) != 1 or problem.expression is None:
        raise ValueError("This first module requires one variable and a dimensionless expected result.")
    givens = {item.name: item for item in problem.givens}
    if not {'lower_bound', 'upper_bound'} <= set(givens):
        raise ValueError("Finite lower_bound and upper_bound givens are required.")
    for key in ('lower_bound', 'upper_bound'):
        if givens[key].unit != 'dimensionless':
            raise ValueError("This module requires dimensionless bounds.")
        parse_scalar(givens[key].value)
    Polynomial(problem.expression, problem.variables[0])
    if {planned.method_a, planned.method_b} != {Method.SYMBOLIC_INTEGRATION, Method.NUMERICAL_QUADRATURE}:
        raise ValueError("This module requires exact integration and numerical quadrature.")


def _route(problem, method):
    givens = {item.name: item.value for item in problem.givens}
    return VerificationSpec('polynomial', tuple({
        'method': method.value, 'expression': problem.expression,
        'variable': problem.variables[0], 'lower': givens['lower_bound'], 'upper': givens['upper_bound'],
    }.items()))


def route_a(confirmed, planned):
    return _route(confirmed.problem, planned.method_a)


def route_b(confirmed, planned):
    return _route(confirmed.problem, planned.method_b)


def sanity_checks(planned, executions):
    checks = []
    for label, executed in executions.items():
        for bound in planned.sanity_checks:
            name = f"{bound.name}_route_{label}"
            if executed.result is None:
                checks.append(CheckEvidence(name, CheckStatus.NOT_RUN, 'No successful route result.'))
                continue
            try:
                raw = executed.result
                value = _UNITS.Quantity(parse_scalar(raw['value']), raw['unit']).to(bound.unit).magnitude
                lower = parse_scalar(bound.lower) if bound.lower is not None else None
                upper = parse_scalar(bound.upper) if bound.upper is not None else None
                passed = (lower is None or value >= lower) and (upper is None or value <= upper)
                detail = f"Observed {value} {bound.unit}; lower={bound.lower}, upper={bound.upper}."
                checks.append(CheckEvidence(name, CheckStatus.PASS if passed else CheckStatus.FAIL, detail))
            except (ValueError, TypeError, ArithmeticError):
                checks.append(CheckEvidence(name, CheckStatus.NOT_RUN, 'Result could not be checked in the expected unit.'))
    return tuple(checks)


def tolerance(executions):
    errors = []
    for executed in executions.values():
        raw = executed.result['absolute_error'] if executed.result else None
        if raw is None:
            return ScalarTolerance(0, 0, 0, 0)
        parse_scalar(raw)
        errors.append(Decimal(raw))
    # Keep the configuration encoding bounded even for widely separated error
    # exponents. Round upward; Comparator still caps this with the exact sum.
    with localcontext() as context:
        context.prec = 128
        context.rounding = ROUND_CEILING
        budget = str(sum(errors, Decimal(0)))
    return ScalarTolerance(budget, 0, budget, 0)
