"""Standard-library-only repair vocabulary and fixed blind-fix instructions."""

from enum import Enum


class RepairReason(str, Enum):
    RUNTIME_ERROR = "RUNTIME_ERROR"
    TIMEOUT = "TIMEOUT"
    POLICY_REJECTED = "POLICY_REJECTED"
    WRONG_INTEGRAND = "WRONG_INTEGRAND"
    WRONG_BOUNDS = "WRONG_BOUNDS"
    WRONG_RESULT = "WRONG_RESULT"
    ERROR_ESTIMATE = "ERROR_ESTIMATE"
    UNIT_ERROR = "UNIT_ERROR"
    SOLVER_NOT_EXECUTED = "SOLVER_NOT_EXECUTED"
    NUMERICAL_ACCURACY = "NUMERICAL_ACCURACY"
    ROOT_COVERAGE = "ROOT_COVERAGE"
    WRONG_EXPRESSION = "WRONG_EXPRESSION"
    UNKNOWN = "UNKNOWN"


GUIDANCE = {
    RepairReason.RUNTIME_ERROR: "Rewrite from the original problem and assigned method to fix runtime errors. Define all names and follow the execution contract.",
    RepairReason.TIMEOUT: "Rewrite from the original problem and assigned method to avoid unbounded work. Use the prescribed solver without unbounded loops.",
    RepairReason.POLICY_REJECTED: "Rewrite using only permitted imports, ordinary public names, and the execution contract. Avoid unsupported syntax and reflection.",
    RepairReason.WRONG_INTEGRAND: "Construct exactly the original problem's integrand. Preserve its variables, coefficients, and arithmetic.",
    RepairReason.WRONG_BOUNDS: "Use exactly the bounds and integration variable stated in the original problem.",
    RepairReason.WRONG_RESULT: "Return the actual result of the assigned solver without rounding, hard-coded values, or replacement.",
    RepairReason.ERROR_ESTIMATE: "Return the assigned solver's actual error estimate unchanged. For exact symbolic results use the prescribed exact-result contract.",
    RepairReason.UNIT_ERROR: "Use Pint quantities with the expected dimension and unit from the original problem. Preserve the solver's computed magnitude and actual error estimate.",
    RepairReason.SOLVER_NOT_EXECUTED: "Execute the prescribed solver exactly as required by the method contract; do not replace it with an asserted answer.",
    RepairReason.NUMERICAL_ACCURACY: "Recompute from the original problem using the assigned method. Improve solver accuracy settings if applicable and preserve its actual error estimate.",
    RepairReason.ROOT_COVERAGE: "Compute every distinct real root of the original polynomial with the assigned solver. Use distinct brackets for numerical roots, including endpoints for even-multiplicity roots when justified. Return each solver output once; do not fabricate missing roots or merge nearby roots.",
    RepairReason.WRONG_EXPRESSION: "Construct exactly the expression in the original problem, preserving its variables, coefficients, powers, and arithmetic. Use only the assigned method.",
    RepairReason.UNKNOWN: "No safe blind repair is available.",
}


def guidance(reason: RepairReason) -> str:
    if not isinstance(reason, RepairReason):
        raise ValueError("Repair instructions require a controlled reason code.")
    return "Blind repair: " + GUIDANCE[reason] + " Do not guess another route's answer or force agreement."
