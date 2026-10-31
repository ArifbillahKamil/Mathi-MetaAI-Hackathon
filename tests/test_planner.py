"""Deterministic planning gates; mock completions never compute answers."""

import json
import unittest
from unittest.mock import Mock

from app.core.independence import build_blind_requests
from app.core.planner import METHOD_PAIRS, PlanSpec, PlanningStatus, plan_problem
from app.core.structured import parse_record
from app.llm.meta import MetaAPIError
from tests.preparation_fixtures import client_for, confirmed, plan_payload


class PlannerTests(unittest.TestCase):
    def test_valid_plan_can_feed_blind_request_builder(self):
        result = plan_problem(client_for(plan_payload()), confirmed())
        self.assertEqual(result.status, PlanningStatus.PLANNED)
        a, b = build_blind_requests('Confirmed fixture problem.', result.plan.as_route_plan())
        self.assertNotEqual(a.messages[1], b.messages[1])

    def test_same_method_requests_replanning_then_accepts_distinct_pair(self):
        client = client_for(plan_payload(method_b='symbolic_integration'), plan_payload())
        result = plan_problem(client, confirmed())
        self.assertEqual(result.status, PlanningStatus.PLANNED)
        self.assertEqual(len(result.attempts), 2)
        self.assertEqual(result.attempts[0].error, 'SAME_METHOD')

    def test_repeated_rejection_stops_at_budget(self):
        bad = plan_payload(method_b='symbolic_integration')
        client = client_for(bad, bad)
        result = plan_problem(client, confirmed())
        self.assertEqual(result.status, PlanningStatus.UNVERIFIED)
        self.assertEqual(result.reason, 'PLAN_REJECTED')
        self.assertIsNone(result.plan)
        self.assertEqual(client.complete.call_count, 2)

    def test_class_units_and_method_pair_must_match_confirmed_problem(self):
        cases = (
            ({'problem_class': 'algebra'}, 'PLAN_CLASS_MISMATCH'),
            ({'expected_unit': 'm'}, 'PLAN_UNIT_MISMATCH'),
            ({'method_a': 'lu_factorization', 'method_b': 'svd_solve'}, 'METHOD_PAIR_NOT_SUPPORTED'),
            ({'sanity_checks': [{'name': 'bound', 'lower': '0', 'upper': None, 'unit': 'm'}]}, 'SANITY_UNIT_MISMATCH'),
        )
        for changes, reason in cases:
            with self.subTest(reason=reason):
                result = plan_problem(client_for(plan_payload(**changes)), confirmed(), max_attempts=1)
                self.assertEqual(result.status, PlanningStatus.UNVERIFIED)
                self.assertEqual(result.attempts[0].error, reason)

    def test_answer_code_or_verdict_fields_are_not_accepted(self):
        for field in ('answer', 'code', 'verdict', 'execution_contract'):
            with self.subTest(field=field):
                result = plan_problem(client_for(plan_payload(**{field: 'untrusted'})), confirmed(), max_attempts=1)
                self.assertEqual(result.attempts[0].error, 'INVALID_STRUCTURED_OUTPUT')

    def test_malformed_json_can_be_replanned(self):
        result = plan_problem(client_for('not-json', plan_payload()), confirmed())
        self.assertEqual(result.status, PlanningStatus.PLANNED)
        self.assertEqual(result.attempts[0].error, 'INVALID_STRUCTURED_OUTPUT')

    def test_transport_failure_does_not_trigger_automatic_retry(self):
        client = client_for(MetaAPIError('META_CONNECTION_FAILED'))
        result = plan_problem(client, confirmed())
        self.assertEqual(result.status, PlanningStatus.UNVERIFIED)
        self.assertEqual(result.reason, 'PLANNER_CALL_FAILED')
        self.assertEqual(client.complete.call_count, 1)

    def test_replan_receives_only_reason_code_not_failed_output(self):
        bad = plan_payload(method_b='symbolic_integration', independence_rationale='PRIVATE_FAILED_PLAN_SENTINEL')
        client = client_for(bad, plan_payload())
        plan_problem(client, confirmed())
        second = client.complete.call_args_list[1].args[0]
        payload = json.loads(second.messages[1].content)
        self.assertEqual(payload['replan_reason_code'], 'SAME_METHOD')
        self.assertNotIn('PRIVATE_FAILED_PLAN_SENTINEL', json.dumps(second.to_dict()))
        self.assertEqual(len(second.messages), 2)

    def test_missing_intake_confirmation_never_calls_planner(self):
        client = Mock()
        with self.assertRaises(ValueError):
            plan_problem(client, None)
        client.complete.assert_not_called()

    def test_attempt_budget_is_validated(self):
        client = Mock()
        for limit in (0, 4, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                plan_problem(client, confirmed(), max_attempts=limit)
        client.complete.assert_not_called()

    def test_unsupported_plan_has_reason_and_no_execution_directives(self):
        payload = plan_payload(supported=False, method_a=None, method_b=None,
                               independence_rationale=None, sanity_checks=[],
                               unsupported_reason='No justified pair for this case.')
        result = plan_problem(client_for(payload), confirmed())
        self.assertEqual(result.status, PlanningStatus.UNSUPPORTED)
        with self.assertRaises(ValueError):
            result.plan.as_route_plan()

    def test_task_outside_catalog_cannot_get_supported_plan(self):
        result = plan_problem(client_for(plan_payload()), confirmed(task='other'), max_attempts=1)
        self.assertEqual(result.attempts[0].error, 'METHOD_PAIR_NOT_SUPPORTED')

    def test_different_task_families_accept_their_own_pair(self):
        cases = {
            'indefinite_integral': 'calculus', 'roots': 'algebra',
            'linear_system': 'linear_algebra', 'initial_value_ode': 'ode',
            'work_energy': 'engineering',
        }
        for task, problem_class in cases.items():
            with self.subTest(task=task):
                problem = confirmed(task=task, problem_class=problem_class)
                methods = sorted(method.value for method in METHOD_PAIRS[problem.problem.task])
                payload = plan_payload(problem_class=problem_class, method_a=methods[0], method_b=methods[1])
                self.assertEqual(plan_problem(client_for(payload), problem).status, PlanningStatus.PLANNED)

    def test_rationale_remains_audit_only_for_generated_route_requests(self):
        result = plan_problem(client_for(plan_payload(independence_rationale='AUDIT_ONLY_SENTINEL')), confirmed())
        for request in build_blind_requests('fixture', result.plan.as_route_plan()):
            self.assertNotIn('AUDIT_ONLY_SENTINEL', json.dumps(request.to_dict()))


class PlanSchemaTests(unittest.TestCase):
    def test_invalid_bounds_cannot_be_used(self):
        for lower, upper in ((None, None), ('2', '1'), ('NaN', None), ('0', 'Infinity')):
            payload = plan_payload(sanity_checks=[{'name': 'bounds', 'lower': lower, 'upper': upper, 'unit': 'dimensionless'}])
            with self.subTest(lower=lower, upper=upper), self.assertRaises(ValueError):
                parse_record(json.dumps(payload), PlanSpec)

    def test_duplicate_sanity_names_or_incomplete_supported_plan_are_rejected(self):
        duplicate = plan_payload()
        duplicate['sanity_checks'] *= 2
        for payload in (duplicate, plan_payload(method_a=None), plan_payload(independence_rationale=None)):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_record(json.dumps(payload), PlanSpec)

    def test_schema_matches_strict_object_requirements(self):
        schema = PlanSpec.model_json_schema()
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(set(schema['properties']), set(schema['required']))
        bounds = schema['$defs']['BoundSpec']
        self.assertFalse(bounds['additionalProperties'])
        self.assertEqual(set(bounds['properties']), set(bounds['required']))


if __name__ == '__main__':
    unittest.main()
