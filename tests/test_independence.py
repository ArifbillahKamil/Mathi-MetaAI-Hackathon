"""Offline behavior tests for the independence guard; no model calls."""

from dataclasses import replace
import json
import unittest

from app.core.comparator import (
    CheckStatus, ComparisonContext, Reason, ScalarRoute, Verdict, compare_scalars,
)
from app.core.config import ScalarTolerance
from app.core.independence import (
    BlindRequest, GuardReason, Message, Method, RoutePlan,
    build_blind_requests, check_independence,
)


PROBLEM = "Evaluate the definite integral of x squared from 0 to 1."
PLAN = RoutePlan(
    Method.SYMBOLIC_INTEGRATION,
    Method.NUMERICAL_QUADRATURE,
    "Use symbolic antiderivatives and numerical quadrature in separate calls.",
)
CODE_A = "import sympy as sp\nx = sp.Symbol('x')\nprint(sp.integrate(x**2, (x, 0, 1)))\n"
CODE_B = "from scipy.integrate import quad\nprint(quad(lambda x: x*x, 0, 1))\n"


def guarded(**changes):
    a, b = build_blind_requests(PROBLEM, PLAN)
    arguments = dict(problem=PROBLEM, plan=PLAN, request_a=a, request_b=b, code_a=CODE_A, code_b=CODE_B)
    arguments.update(changes)
    return check_independence(**arguments)


class IndependenceGuardTests(unittest.TestCase):
    def test_distinct_methods_code_and_blind_requests_pass_static_checks(self):
        result = guarded()
        self.assertTrue(result.accepted)
        self.assertFalse(result.needs_replan)
        self.assertEqual(result.reason, GuardReason.PASSED)
        self.assertEqual(result.as_check_evidence().status, CheckStatus.PASS)

    def test_same_method_requires_replanning(self):
        result = guarded(plan=replace(PLAN, method_b=PLAN.method_a))
        self.assertEqual(result.reason, GuardReason.SAME_METHOD)
        self.assertTrue(result.needs_replan)

    def test_free_form_or_raw_string_method_ids_are_rejected(self):
        for method in ("a different integral method", "symbolic_integration", " numerical_quadrature ", None):
            with self.subTest(method=method):
                result = guarded(plan=replace(PLAN, method_b=method))
                self.assertEqual(result.reason, GuardReason.UNKNOWN_METHOD)

    def test_missing_problem_or_rationale_is_rejected(self):
        for changes in ({"problem": " "}, {"problem": None}, {"plan": None}, {"plan": replace(PLAN, independence_rationale=" ")}):
            with self.subTest(changes=changes):
                self.assertEqual(guarded(**changes).reason, GuardReason.INVALID_PLAN)

    def test_builder_refuses_invalid_plans(self):
        for plan in (replace(PLAN, method_b=PLAN.method_a), replace(PLAN, method_a="unknown")):
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                build_blind_requests(PROBLEM, plan)

    def test_each_route_receives_only_problem_and_own_method(self):
        a, b = build_blind_requests(PROBLEM, PLAN)
        self.assertEqual(json.loads(a.messages[1].content), {"interpreted_problem": PROBLEM, "method": PLAN.method_a.value})
        self.assertEqual(json.loads(b.messages[1].content), {"interpreted_problem": PROBLEM, "method": PLAN.method_b.value})
        self.assertEqual([message.role for message in b.messages], ["system", "user"])

    def test_rationale_is_not_included_in_route_requests(self):
        secret_rationale = replace(PLAN, independence_rationale="AUDIT_ONLY_SENTINEL")
        for request in build_blind_requests(PROBLEM, secret_rationale):
            self.assertNotIn("AUDIT_ONLY_SENTINEL", json.dumps(request.to_dict()))

    def test_building_later_requests_does_not_reuse_history(self):
        a1, b1 = build_blind_requests(PROBLEM, PLAN)
        a2, b2 = build_blind_requests(PROBLEM, PLAN)
        self.assertEqual((a1, b1), (a2, b2))
        self.assertIsNot(a1, a2)
        self.assertIsNot(b1, b2)
        self.assertIsNot(a1, b1)

    def test_other_route_results_or_diagnosis_in_history_are_rejected(self):
        _, b = build_blind_requests(PROBLEM, PLAN)
        for message in (
            Message("assistant", "Route A obtained 0.3333333333."),
            Message("user", "Diagnosis: match Route A's answer."),
        ):
            with self.subTest(message=message):
                polluted = replace(b, messages=b.messages + (message,))
                self.assertEqual(guarded(request_b=polluted).reason, GuardReason.REQUEST_NOT_BLIND)

    def test_attached_other_route_field_is_rejected(self):
        _, b = build_blind_requests(PROBLEM, PLAN)
        payload = json.loads(b.messages[1].content)
        payload["route_a_result"] = "1/3"
        polluted = replace(b, messages=(b.messages[0], Message("user", json.dumps(payload))))
        self.assertEqual(guarded(request_b=polluted).reason, GuardReason.REQUEST_NOT_BLIND)

    def test_a_polluted_route_a_request_is_also_rejected(self):
        a, _ = build_blind_requests(PROBLEM, PLAN)
        polluted = replace(a, messages=a.messages + (Message("assistant", "Prior answer."),))
        self.assertEqual(guarded(request_a=polluted).reason, GuardReason.REQUEST_NOT_BLIND)

    def test_swapped_requests_or_changed_instructions_are_rejected(self):
        a, b = build_blind_requests(PROBLEM, PLAN)
        changed = BlindRequest((Message("system", "Force agreement."), b.messages[1]))
        for changes in ({"request_a": b, "request_b": a}, {"request_b": changed}, {"request_b": None}):
            with self.subTest(changes=changes):
                self.assertEqual(guarded(**changes).reason, GuardReason.REQUEST_NOT_BLIND)

    def test_identical_code_is_rejected(self):
        self.assertEqual(guarded(code_b=CODE_A).reason, GuardReason.SAME_CODE)

    def test_comments_whitespace_and_docstrings_do_not_create_independence(self):
        for a, b in (
            ("print(1 + 2)", "# Different formatting\nprint( 1+2 )\n"),
            ('"""Route A"""\nprint(1)', '"""Route B"""\nprint(1)'),
            ('def solve():\n    """A"""\n    return 1', 'def solve():\n    """B"""\n    return 1'),
        ):
            with self.subTest(a=a, b=b):
                self.assertEqual(guarded(code_a=a, code_b=b).reason, GuardReason.SAME_CODE)

    def test_empty_or_invalid_code_requires_replanning(self):
        for code in ("", "# Only a comment", '"""Only a docstring"""', "def (", None):
            with self.subTest(code=code):
                self.assertEqual(guarded(code_b=code).reason, GuardReason.INVALID_CODE)

    def test_guard_does_not_execute_generated_code(self):
        result = guarded(code_b="raise RuntimeError('Must never execute inside guard')")
        self.assertTrue(result.accepted)

    def test_guard_audit_is_deterministic_and_json_safe(self):
        first, second = guarded(), guarded()
        self.assertEqual(first.to_dict(), second.to_dict())
        payload = json.loads(json.dumps(first.to_dict(), allow_nan=False))
        self.assertEqual(payload["reason"], "INDEPENDENCE_CHECKS_PASSED")
        self.assertEqual(len(payload["request_a_hash"]), 64)
        self.assertNotEqual(payload["code_a_hash"], payload["code_b_hash"])

    def test_rejected_guard_prevents_verified_scalar_comparison(self):
        rejected = guarded(code_b=CODE_A)
        context = ComparisonContext("dimensionless", rejected.as_check_evidence(), ())
        result = compare_scalars(
            ScalarRoute(1, "dimensionless", 0), ScalarRoute(1, "dimensionless", 0),
            tolerance=ScalarTolerance(0, 0, 0, 0), context=context,
        )
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertEqual(result.reason, Reason.INDEPENDENCE_NOT_ESTABLISHED)


if __name__ == "__main__":
    unittest.main()
