"""Blind repair orchestration with mocked models and actual solver processes."""

import json
import unittest
from unittest.mock import patch

from app.core.config import ScalarTolerance
from app.core.execution import execute_preparation
from app.llm.meta import Completion, MetaAPIError
from tests.route_fixtures import NUMERIC, SYMBOLIC
from tests.test_route_execution import CodeClient, ready_report


class CorrectionClient(CodeClient):
    def __init__(self, *, diagnoses=None, **kwargs):
        super().__init__(**kwargs)
        self.diagnoses = list(diagnoses or [{'suspected_route': 'UNKNOWN', 'bug': 'UNKNOWN', 'explanation': 'Uncertain.'}])

    def complete(self, request, **options):
        if options['schema_name'] != 'Diagnosis':
            return super().complete(request, **options)
        with self.lock:
            self.requests.append((request.to_dict(), dict(options)))
            response = self.diagnoses.pop(0) if len(self.diagnoses) > 1 else self.diagnoses[0]
        return Completion(json.dumps(response), 'offline-fixture-arbiter', {'total_tokens': 10}, 'fixture-hash', 'fixture-id')


class SelfCorrectionTests(unittest.TestCase):
    def test_already_verified_run_does_not_call_arbiter_or_repair(self):
        client = CorrectionClient()
        report = execute_preparation(client, ready_report())
        self.assertEqual(report['status'], 'VERIFIED')
        self.assertEqual(report['self_correction'], 'NOT_NEEDED')
        self.assertEqual(report['correction_history'], [])
        self.assertEqual(len(client.requests), 2)

    def test_runtime_failure_retries_only_the_failed_route(self):
        bad = 'missing_name\n' + NUMERIC
        client = CorrectionClient(numeric=[bad, NUMERIC])
        report = execute_preparation(client, ready_report())
        self.assertEqual(report['status'], 'VERIFIED', report['comparison'])
        self.assertEqual(report['self_correction'], 'CORRECTED')
        self.assertEqual(report['route_executions'], 3)
        self.assertEqual(report['routes']['B']['code'], SYMBOLIC.strip())
        entry = report['correction_history'][0]
        self.assertEqual(entry['repaired_route'], 'A')
        self.assertIsNone(entry['arbiter'])
        self.assertEqual(entry['before_routes']['A']['code'], bad.strip())
        self.assertEqual(len(client.requests), 3)
        self.assertTrue(report['final_answer']['corrected_after_conflict'])

    def test_unit_conflict_is_diagnosed_then_fixed_without_peer_answer_leakage(self):
        bad = NUMERIC.replace("'dimensionless'", "'m'")
        sentinel = 'PEER_VALUE_PRIVATE_9.87654321'
        client = CorrectionClient(numeric=[bad, NUMERIC], diagnoses=[{
            'suspected_route': 'A', 'bug': 'UNIT_ERROR', 'explanation': sentinel,
        }])
        report = execute_preparation(client, ready_report())
        self.assertEqual(report['status'], 'VERIFIED', report['comparison'])
        entry = report['correction_history'][0]
        self.assertEqual(entry['classification']['category'], 'DIMENSIONAL_CONFLICT')
        self.assertIn(sentinel, entry['arbiter']['raw_response'])
        self.assertNotIn(sentinel, json.dumps(entry['generation']['request']))
        payload = json.loads(entry['generation']['request']['messages'][1]['content'])
        self.assertEqual(set(payload), {'interpreted_problem', 'method', 'repair_reason_code'})
        self.assertEqual(payload['repair_reason_code'], 'UNIT_ERROR')
        self.assertNotIn('routes', payload)
        self.assertTrue(report['comparison']['context']['corrected_after_conflict'])
        self.assertLessEqual(client.requests[-1][1]['timeout_seconds'], 90)

    def test_two_failed_routes_are_retried_separately_within_two_attempts(self):
        client = CorrectionClient(numeric=['missing_numeric\n' + NUMERIC, NUMERIC],
                                  symbolic=['missing_symbolic\n' + SYMBOLIC, SYMBOLIC])
        report = execute_preparation(client, ready_report())
        self.assertEqual(report['status'], 'VERIFIED', report)
        self.assertEqual([entry['repaired_route'] for entry in report['correction_history']], ['A', 'B'])
        self.assertEqual(report['route_executions'], 4)
        self.assertTrue(all(entry['arbiter'] is None for entry in report['correction_history']))
        self.assertEqual(len(client.requests), 4)

    def test_unknown_or_sanity_diagnosis_cannot_relax_checks(self):
        for route in ('UNKNOWN', 'CHECKS'):
            with self.subTest(route=route):
                saved = ready_report()
                saved['planning']['plan']['sanity_checks'][0]['upper'] = '1'
                client = CorrectionClient(diagnoses=[{
                    'suspected_route': route, 'bug': 'UNKNOWN', 'explanation': 'The expectation may be wrong.',
                }])
                report = execute_preparation(client, saved)
                self.assertEqual(report['status'], 'CONFLICT')
                self.assertEqual(report['self_correction'], 'STOPPED_UNCERTAIN_DIAGNOSIS')
                self.assertEqual(report['plan']['sanity_checks'][0]['upper'], '1')
                self.assertEqual(report['route_executions'], 2)
                self.assertEqual(len(client.requests), 3)

    def test_failed_repairs_stop_at_two_without_forcing_agreement(self):
        bad = NUMERIC.replace('u.Quantity(error,', 'u.Quantity(0.1,')
        client = CorrectionClient(numeric=[bad])
        report = execute_preparation(client, ready_report())
        self.assertEqual(report['status'], 'UNVERIFIED')
        self.assertEqual(report['self_correction'], 'EXHAUSTED')
        self.assertEqual(len(report['correction_history']), 2)
        self.assertEqual(len(client.requests), 4)
        self.assertIsNone(report['final_answer'])

    def test_time_budget_can_stop_before_an_extra_model_call(self):
        client = CorrectionClient(numeric=['missing_name\n' + NUMERIC])
        report = execute_preparation(client, ready_report(), correction_time_budget=1e-12)
        self.assertEqual(report['status'], 'UNVERIFIED')
        self.assertEqual(report['self_correction'], 'TIME_BUDGET_EXCEEDED')
        self.assertEqual(len(client.requests), 2)

    def test_loose_only_match_after_correction_remains_conflict(self):
        client = CorrectionClient(numeric=[NUMERIC.replace("'dimensionless'", "'m'"), NUMERIC],
                                  diagnoses=[{'suspected_route': 'A', 'bug': 'UNIT_ERROR', 'explanation': 'Wrong unit.'}])
        # Deliberately stricter test policy than the method's ordinary policy.
        policy = ScalarTolerance('1e-16', 0, '1e-13', 0)
        with patch('app.modules.calculus.tolerance', return_value=policy):
            report = execute_preparation(client, ready_report(), max_corrections=1)
        self.assertEqual(report['status'], 'CONFLICT')
        self.assertEqual(report['comparison']['reason'], 'CORRECTION_REQUIRES_TIGHT')
        self.assertTrue(report['comparison']['context']['corrected_after_conflict'])
        self.assertIsNone(report['final_answer'])

    def test_repair_independence_rejection_does_not_execute_new_code(self):
        client = CorrectionClient(numeric=['missing_name\n' + NUMERIC, SYMBOLIC])
        report = execute_preparation(client, ready_report())
        self.assertEqual(report['status'], 'UNVERIFIED')
        self.assertEqual(report['self_correction'], 'REPAIR_GUARD_REJECTED')
        self.assertTrue(report['correction_history'][0]['requires_fresh_replan'])
        self.assertEqual(report['route_executions'], 2)

    def test_transport_failure_during_repair_is_not_retried(self):
        client = CorrectionClient(numeric=['missing_name\n' + NUMERIC, MetaAPIError('META_CONNECTION_FAILED')])
        report = execute_preparation(client, ready_report())
        self.assertEqual(report['status'], 'UNVERIFIED')
        self.assertEqual(report['self_correction'], 'REPAIR_GENERATION_FAILED')
        self.assertEqual(len(client.requests), 3)
        self.assertEqual(report['route_executions'], 2)

    def test_invalid_correction_limits_do_not_call_model(self):
        for limits in ({'max_corrections': 3}, {'max_corrections': True}, {'correction_time_budget': 0}, {'correction_time_budget': float('nan')}):
            client = CorrectionClient()
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                execute_preparation(client, ready_report(), **limits)
            self.assertEqual(client.requests, [])


if __name__ == '__main__':
    unittest.main()
