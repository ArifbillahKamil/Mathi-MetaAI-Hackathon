"""Offline component demonstration with curated code, not a live model run."""

import json

from app.core.comparator import CheckEvidence, CheckStatus, ComparisonContext, compare_scalars
from app.core.config import ScalarTolerance
from app.core.independence import Method, RoutePlan, build_blind_requests, check_independence
from app.core.numbers import parse_scalar
from app.sandbox import ExecutionStatus, run_code


PROBLEM = "Evaluate the definite integral of x squared from 0 to 3. The answer is dimensionless."
PLAN = RoutePlan(
    Method.SYMBOLIC_INTEGRATION, Method.NUMERICAL_QUADRATURE,
    "An exact symbolic integral and adaptive numerical quadrature use different methods in separate processes.",
)
PRELUDE = "from pint import UnitRegistry\nu = UnitRegistry()\n"
CODE_A = PRELUDE + (
    "import sympy as sp\nx = sp.Symbol('x')\n"
    "exact = sp.integrate(x**2, (x, 0, 3))\n"
    "result = {'quantity': u.Quantity(int(exact), 'dimensionless'), "
    "'absolute_error': u.Quantity(0, 'dimensionless')}\n"
)
CODE_B = PRELUDE + (
    "from scipy.integrate import quad\nvalue, error = quad(lambda x: x*x, 0, 3)\n"
    "result = {'quantity': u.Quantity(value, 'dimensionless'), "
    "'absolute_error': u.Quantity(error, 'dimensionless')}\n"
)


def run_demo() -> dict:
    requests = build_blind_requests(PROBLEM, PLAN)
    guard = check_independence(
        problem=PROBLEM, plan=PLAN, request_a=requests[0], request_b=requests[1],
        code_a=CODE_A, code_b=CODE_B,
    )
    if not guard.accepted:
        raise RuntimeError(f"Curated demonstration rejected: {guard.reason.value}")
    # Route B's code and inputs are fixed before A executes; no A-derived input
    # is passed into either process. No model requests are sent in this demo.
    a, b = run_code(CODE_A), run_code(CODE_B)
    checks = []
    for label, executed in (("A", a), ("B", b)):
        if executed.status == ExecutionStatus.SUCCESS:
            try:
                nonnegative = parse_scalar(executed.result["value"]) >= 0
                status = CheckStatus.PASS if nonnegative else CheckStatus.FAIL
                detail = "Computed scalar is nonnegative." if nonnegative else "Computed scalar is negative."
            except ValueError:
                status, detail = CheckStatus.NOT_RUN, "Result could not be checked as a finite real scalar."
        else:
            status, detail = CheckStatus.NOT_RUN, "Route execution did not succeed."
        checks.append(CheckEvidence(f"nonnegative_integral_route_{label}", status, detail))
    # This curated numeric method supplies its own executed error estimate.
    # No arbitrary global tolerance or hard-coded agreement floor is used.
    estimate = b.result["absolute_error"] if b.status == ExecutionStatus.SUCCESS else "0"
    tolerance = ScalarTolerance(estimate or "0", 0, estimate or "0", 0)
    compared = compare_scalars(
        a.as_scalar_route(), b.as_scalar_route(), tolerance=tolerance,
        context=ComparisonContext("dimensionless", guard.as_check_evidence(), tuple(checks)),
    )
    return {
        "run_kind": "offline_component_demo",
        "code_origin": "curated_fixture_not_model_generated",
        "interpreted_problem": PROBLEM,
        "plan": {"method_a": PLAN.method_a.value, "method_b": PLAN.method_b.value,
                 "independence_rationale": PLAN.independence_rationale},
        "independence": guard.to_dict(),
        "routes": {"A": a.to_dict(), "B": b.to_dict()},
        "comparison": compared.to_dict(),
        "model_requests_sent": 0,
        "limitations": "Local development backend; no enforced memory/network isolation. Not an end-to-end Meta evaluation.",
    }


if __name__ == "__main__":
    print(json.dumps(run_demo(), indent=2, allow_nan=False))
