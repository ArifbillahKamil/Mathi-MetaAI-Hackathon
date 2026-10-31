"""Bounded univariate polynomial real-root sets."""

from decimal import Decimal, ROUND_CEILING, localcontext

from app.core.config import ScalarTolerance
from app.core.evidence import CheckEvidence, CheckStatus
from app.core.independence import Method
from app.core.numbers import parse_scalar
from app.core.problem import AnswerShape, Domain, ProblemClass, Task
from app.modules.drivers.polynomial import Polynomial
from app.sandbox.contracts import VerificationSpec

CONTRACT = (
    "Return only GeneratedRoute JSON containing self-contained Python code. Find all distinct real roots "
    "of the confirmed polynomial equal to zero. Treat repeated roots as one set element. "
    "Create Pint UnitRegistry() with no arguments. Assign result={'quantities': "
    "[u.Quantity(root, 'dimensionless') for root in roots]}, using your variable names. "
    "For symbolic_elimination import sympy, construct the original expression with exact Integer/Rational "
    "arithmetic, create the confirmed variable with Symbol(name, real=True), and call sympy.solve(expression, "
    "symbol) exactly once with no other arguments. Keep exact returned roots; do not cast to float. "
    "For numerical_root_finding import brentq from scipy.optimize and construct a Python function for "
    "the original polynomial, without algebraic expansion or refactoring. Independently choose brackets "
    "and execute brentq(function, lower, upper, xtol=1e-12, rtol=1e-14) for every distinct real root. "
    "An even-multiplicity root can be a bracket endpoint. Use returned roots unchanged. A scan or sign "
    "change alone does not establish completeness. Do not use symbolic solving in the numerical route. "
    "If unable to bracket every root, report only executed results; do not fabricate missing roots. "
    "Imports: pint and sympy for symbolic_elimination; pint, math, scipy.optimize for numerical_root_finding. "
    "No eval, sympify, parse_expr, lambdify, file/network access, reflection, exception handlers, module "
    "mutation, or another solver. Never hard-code or round the solver outputs or invent error bounds."
)


def supports(problem):
    return problem.problem_class == ProblemClass.ALGEBRA and problem.task == Task.ROOTS


def plan(confirmed, planned):
    problem = confirmed.problem
    if (not supports(problem) or problem.answer_shape != AnswerShape.SET or problem.domain != Domain.REAL
            or problem.expected_unit != 'dimensionless' or len(problem.variables) != 1 or problem.givens
            or problem.unknowns != ('roots',) or problem.expression is None):
        raise ValueError('Only all real roots of one dimensionless polynomial are currently supported.')
    polynomial = Polynomial(problem.expression, problem.variables[0])
    if not polynomial.terms or not 1 <= max(polynomial.terms) <= 6:
        raise ValueError('A nonconstant polynomial of degree at most six is required.')
    if any(max(value.numerator.bit_length(), value.denominator.bit_length()) > 512 for value in polynomial.terms.values()):
        raise ValueError('Polynomial coefficients exceed the supported complexity.')
    if {planned.method_a, planned.method_b} != {Method.SYMBOLIC_ELIMINATION, Method.NUMERICAL_ROOT_FINDING}:
        raise ValueError('Root sets require symbolic elimination and numerical root finding.')


def _route(problem, method):
    return VerificationSpec('roots', tuple({'method': method.value, 'expression': problem.expression,
                                           'variable': problem.variables[0]}.items()))


def route_a(confirmed, planned):
    return _route(confirmed.problem, planned.method_a)


def route_b(confirmed, planned):
    return _route(confirmed.problem, planned.method_b)


def sanity_checks(planned, executions):
    checks = []
    for label, execution in executions.items():
        for bound in planned.sanity_checks:
            if execution.result is None:
                checks.append(CheckEvidence(f'{bound.name}_{label}', CheckStatus.NOT_RUN, 'No executed root set.'))
                continue
            raw = execution.result
            for index, value in enumerate(raw['values']):
                number = parse_scalar(value)
                low = parse_scalar(bound.lower) if bound.lower is not None else None
                high = parse_scalar(bound.upper) if bound.upper is not None else None
                passed = (low is None or number >= low) and (high is None or number <= high)
                checks.append(CheckEvidence(f'{bound.name}_{label}_{index}', CheckStatus.PASS if passed else CheckStatus.FAIL,
                                            f'Observed root {value}; lower={bound.lower}, upper={bound.upper}.'))
    return tuple(checks)


def tolerance(executions):
    errors = []
    for execution in executions.values():
        if execution.result is None:
            return ScalarTolerance(0, 0, 0, 0)
        errors.extend(execution.result['absolute_errors'])
    with localcontext() as context:
        context.prec = 128
        context.rounding = ROUND_CEILING
        # A broad configuration ceiling; Comparator caps each match using only
        # the two particular roots' executed errors, not the global sum.
        maximum = str(sum((Decimal(error) for error in errors), Decimal(0)))
    return ScalarTolerance(maximum, 0, maximum, 0)
