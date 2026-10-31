"""Failure classification and non-leaking repair/diagnosis request boundaries."""

from dataclasses import replace
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.core.comparator import ComparisonContext, ComparisonResult, Reason, Verdict
from app.core.independence import Method, RoutePlan, build_blind_requests, check_independence
from app.core.repairs import RepairReason
from app.core.self_correction import classify_failure, diagnose
from app.llm.meta import MetaClient, MetaSettings
from app.sandbox import ExecutionStatus
from tests.preparation_fixtures import client_for, confirmed, plan_payload
from app.core.planner import PlanSpec
from app.core.structured import parse_record


def compared(verdict=Verdict.UNVERIFIED, reason=Reason.ROUTE_FAILED):
    return ComparisonResult(verdict, reason, 'Fixture comparison.', ComparisonContext('dimensionless'))


def executions(status_a=ExecutionStatus.SUCCESS, status_b=ExecutionStatus.SUCCESS, error=None):
    return {
        'A': SimpleNamespace(status=status_a, error=error, code='print(1)', result={'value': 'PEER_NUMBER_SENTINEL'}, method_evidence=None),
        'B': SimpleNamespace(status=status_b, error=error, code='print(2)', result={'value': 'OTHER_NUMBER_SENTINEL'}, method_evidence=None),
    }


class CorrectionContractTests(unittest.TestCase):
    def test_agreement_needs_no_correction(self):
        decision = classify_failure(compared(Verdict.VERIFIED, Reason.TIGHT_AGREEMENT), executions())
        self.assertEqual(decision.action, 'NONE')

    def test_only_failed_route_is_selected_for_runtime_retry(self):
        decision = classify_failure(compared(), executions(status_b=ExecutionStatus.RUNTIME_ERROR))
        self.assertEqual(decision.action, 'RETRY_ROUTE')
        self.assertEqual(decision.route, 'B')
        self.assertEqual(decision.repair, RepairReason.RUNTIME_ERROR)

    def test_timeout_and_method_receipt_failures_get_controlled_codes(self):
        for status, error, expected in (
            (ExecutionStatus.TIMEOUT, None, RepairReason.TIMEOUT),
            (ExecutionStatus.REJECTED, 'IMPORT_NOT_ALLOWED', RepairReason.POLICY_REJECTED),
            (ExecutionStatus.INVALID_RESULT, 'MethodCheckError: ERROR_NOT_SOLVER_ESTIMATE', RepairReason.ERROR_ESTIMATE),
            (ExecutionStatus.INVALID_RESULT, 'MethodCheckError: INTEGRAND_SAMPLE_MISMATCH', RepairReason.WRONG_INTEGRAND),
            (ExecutionStatus.INVALID_RESULT, 'MethodCheckError: ROOT_SET_INCOMPLETE', RepairReason.ROOT_COVERAGE),
            (ExecutionStatus.INVALID_RESULT, 'MethodCheckError: ROOT_FUNCTION_MISMATCH', RepairReason.WRONG_EXPRESSION),
        ):
            with self.subTest(status=status, error=error):
                self.assertEqual(classify_failure(compared(), executions(status_a=status, error=error)).repair, expected)

    def test_conflicts_need_separate_diagnosis(self):
        for reason in (Reason.UNIT_MISMATCH, Reason.NUMERIC_DISAGREEMENT, Reason.SANITY_FAILED):
            with self.subTest(reason=reason):
                self.assertEqual(classify_failure(compared(Verdict.CONFLICT, reason), executions()).action, 'DIAGNOSE')

    def test_repair_reason_is_only_sent_to_its_own_route(self):
        plan = RoutePlan(Method.NUMERICAL_QUADRATURE, Method.SYMBOLIC_INTEGRATION, 'Fixture independence.')
        a, b = build_blind_requests('original problem', replace(plan, repair_a=RepairReason.ERROR_ESTIMATE))
        original_b = build_blind_requests('original problem', plan)[1]
        self.assertEqual(b, original_b)
        self.assertEqual(json.loads(a.messages[1].content)['repair_reason_code'], 'ERROR_ESTIMATE')
        self.assertNotIn('PEER_NUMBER_SENTINEL', json.dumps(a.to_dict()))

    def test_free_form_diagnosis_cannot_be_used_as_repair_reason(self):
        plan = RoutePlan(Method.NUMERICAL_QUADRATURE, Method.SYMBOLIC_INTEGRATION, 'Fixture independence.')
        with self.assertRaises(ValueError):
            build_blind_requests('problem', replace(plan, repair_b='Use the other answer: 9.12345'))

    def test_guard_rechecks_repaired_conversation(self):
        plan = RoutePlan(Method.NUMERICAL_QUADRATURE, Method.SYMBOLIC_INTEGRATION, 'Fixture independence.', repair_a=RepairReason.ERROR_ESTIMATE)
        a, b = build_blind_requests('problem', plan)
        passed = check_independence(problem='problem', plan=plan, request_a=a, request_b=b, code_a='print(1)', code_b='print(2)')
        self.assertTrue(passed.accepted)
        wrong_a = build_blind_requests('problem', replace(plan, repair_a=None))[0]
        failed = check_independence(problem='problem', plan=plan, request_a=wrong_a, request_b=b, code_a='print(1)', code_b='print(2)')
        self.assertFalse(failed.accepted)

    def test_arbiter_can_see_both_results_but_produces_only_a_typed_diagnosis(self):
        client = client_for({'suspected_route': 'A', 'bug': 'UNIT_ERROR', 'explanation': 'Other route has PEER_VALUE_123.456.'})
        plan = parse_record(json.dumps(plan_payload()), PlanSpec)
        diagnosis, attempt = diagnose(client, confirmed(), plan, executions(), compared(Verdict.CONFLICT, Reason.UNIT_MISMATCH), attempt=1, timeout_seconds=5)
        self.assertEqual(diagnosis.bug, RepairReason.UNIT_ERROR)
        payload = json.loads(client.complete.call_args.args[0].messages[1].content)
        self.assertEqual(set(payload['routes']), {'A', 'B'})
        self.assertEqual(attempt.parsed.explanation, 'Other route has PEER_VALUE_123.456.')
        self.assertEqual(client.complete.call_args.kwargs['timeout_seconds'], 5)

    def test_per_call_timeout_is_transport_only_not_an_api_payload_field(self):
        client = MetaClient(MetaSettings('fixture-token'))
        request = build_blind_requests('problem', RoutePlan(Method.NUMERICAL_QUADRATURE, Method.SYMBOLIC_INTEGRATION, 'Fixture.'))[0]
        raw = {'choices': [{'finish_reason': 'stop', 'message': {'content': 'ready'}}]}
        with patch.object(client, '_post', return_value=raw) as post:
            client.complete(request, timeout_seconds=2)
        self.assertEqual(post.call_args.kwargs['timeout_seconds'], 2)
        self.assertNotIn('timeout_seconds', json.loads(post.call_args.args[0]))
        with patch.object(client, '_post') as post:
            for timeout in (0, -1, True, float('inf')):
                with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                    client.complete(request, timeout_seconds=timeout)
            post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
