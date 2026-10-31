"""Offline generation mocks plus real isolated execution and comparison."""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from app.core.execution import execute_preparation as _execute_preparation, restore_preparation
from app.core.preparation import prepare
from app.execute import main
from app.llm.meta import Completion, MetaAPIError, MetaSettings
from tests.preparation_fixtures import TEXT, client_for, plan_payload, problem_payload
from tests.route_fixtures import NUMERIC, SYMBOLIC


def execute_preparation(*args, **kwargs):
    # This suite covers the single-pass workflow; correction has separate tests.
    kwargs.setdefault('max_corrections', 0)
    return _execute_preparation(*args, **kwargs)


def ready_report(**problem_changes):
    payload = problem_payload(**problem_changes)
    planned = plan_payload(method_a='numerical_quadrature', method_b='symbolic_integration')
    return prepare(client_for(payload, payload, planned), TEXT)


class CodeClient:
    def __init__(self, *, numeric=None, symbolic=None, planner=None):
        self.codes = {
            'numerical_quadrature': list(numeric or [NUMERIC]),
            'symbolic_integration': list(symbolic or [SYMBOLIC]),
        }
        self.planner = planner or plan_payload(method_a='numerical_quadrature', method_b='symbolic_integration')
        self.requests = []
        self.lock = threading.Lock()

    def complete(self, request, **options):
        payload = json.loads(request.messages[1].content)
        with self.lock:
            self.requests.append((request.to_dict(), dict(options)))
            if options['schema_name'] == 'PlanSpec':
                output = self.planner
            else:
                queue = self.codes[payload['method']]
                code = queue.pop(0) if len(queue) > 1 else queue[0]
                if isinstance(code, Exception):
                    raise code
                output = {'code': code}
        return Completion(json.dumps(output), 'offline-fixture-model', {'total_tokens': 10}, 'fixture-hash', 'fixture-id')


class RouteExecutionTests(unittest.TestCase):
    def test_two_blind_generations_feed_actual_solvers_and_verified_comparison(self):
        client = CodeClient()
        report = execute_preparation(client, ready_report())
        self.assertEqual(report['status'], 'VERIFIED', report['comparison'])
        self.assertEqual(report['route_executions'], 2)
        self.assertEqual(report['final_answer']['value'], '9')
        self.assertEqual(report['final_answer']['source_route'], 'B')
        self.assertEqual(len(client.requests), 2)
        for route in report['routes'].values():
            self.assertTrue(route['method_evidence']['output_matches_solver'])
            self.assertEqual(route['method_evidence']['solver_calls'], 1)
        json.dumps(report, allow_nan=False)

    def test_both_generations_are_complete_before_execution_and_outputs_never_leak(self):
        private = SYMBOLIC + '\n# PRIVATE_ROUTE_OUTPUT_SENTINEL\n'
        client = CodeClient(symbolic=[private])
        from app.sandbox import run_code

        def checked_run(*args, **kwargs):
            self.assertEqual(len(client.requests), 2)
            return run_code(*args, **kwargs)

        with patch('app.core.execution.run_code', side_effect=checked_run):
            report = execute_preparation(client, ready_report())
        self.assertEqual(report['status'], 'VERIFIED')
        for request, options in client.requests:
            self.assertNotIn('PRIVATE_ROUTE_OUTPUT_SENTINEL', json.dumps(request))
            self.assertEqual(len(request['messages']), 2)
            self.assertEqual(options['max_completion_tokens'], 2048)

    def test_fabricated_error_estimate_cannot_produce_verified(self):
        code = NUMERIC.replace('u.Quantity(error,', 'u.Quantity(0.1,')
        report = execute_preparation(CodeClient(numeric=[code]), ready_report())
        self.assertEqual(report['status'], 'UNVERIFIED')
        self.assertIn('ERROR_NOT_SOLVER_ESTIMATE', report['routes']['A']['error'])
        self.assertIsNone(report['final_answer'])

    def test_matching_numbers_with_wrong_dimension_are_a_hard_conflict(self):
        report = execute_preparation(CodeClient(numeric=[NUMERIC.replace("'dimensionless'", "'m'")]), ready_report())
        self.assertEqual(report['status'], 'CONFLICT', report)
        self.assertEqual(report['comparison']['reason'], 'UNIT_MISMATCH')
        self.assertIsNone(report['final_answer'])

    def test_both_routes_using_wrong_dimensionless_scale_cannot_verify(self):
        client = CodeClient(numeric=[NUMERIC.replace("'dimensionless'", "'percent'")],
                            symbolic=[SYMBOLIC.replace("'dimensionless'", "'percent'")])
        report = execute_preparation(client, ready_report())
        self.assertEqual(report['status'], 'UNVERIFIED')
        self.assertIsNone(report['final_answer'])

    def test_failed_sanity_bound_lowers_correct_agreement(self):
        saved = ready_report()
        saved['planning']['plan']['sanity_checks'][0]['upper'] = '1'
        report = execute_preparation(CodeClient(), saved)
        self.assertEqual(report['status'], 'CONFLICT')
        self.assertEqual(report['comparison']['reason'], 'SANITY_FAILED')

    def test_generation_failure_prevents_any_execution(self):
        client = CodeClient(numeric=[MetaAPIError('META_CONNECTION_FAILED')])
        with patch('app.core.execution.run_code') as run:
            report = execute_preparation(client, ready_report())
        self.assertEqual(report['status'], 'UNVERIFIED')
        self.assertEqual(report['comparison']['reason'], 'ROUTE_GENERATION_FAILED')
        self.assertEqual(report['route_executions'], 0)
        run.assert_not_called()

    def test_guard_rejection_requests_one_reason_only_replan(self):
        duplicate = NUMERIC + '\n# PRIVATE_FAILED_GENERATION\n'
        client = CodeClient(numeric=[duplicate, NUMERIC], symbolic=[duplicate, SYMBOLIC])
        report = execute_preparation(client, ready_report())
        self.assertEqual(report['status'], 'VERIFIED', report)
        self.assertEqual(len(report['generation_batches']), 2)
        self.assertEqual(len(report['replanning']), 1)
        self.assertEqual(len(client.requests), 5)
        planner_requests = [request for request, options in client.requests if options['schema_name'] == 'PlanSpec']
        payload = json.loads(planner_requests[0]['messages'][1]['content'])
        self.assertEqual(payload['replan_reason_code'], 'SAME_CODE')
        for request, _ in client.requests:
            self.assertNotIn('PRIVATE_FAILED_GENERATION', json.dumps(request))

    def test_exhausted_guard_budget_never_executes(self):
        client = CodeClient(symbolic=[NUMERIC])
        with patch('app.core.execution.run_code') as run:
            report = execute_preparation(client, ready_report())
        self.assertEqual(report['status'], 'UNVERIFIED')
        self.assertEqual(report['comparison']['reason'], 'INDEPENDENCE_REJECTED')
        self.assertEqual(len(client.requests), 5)
        run.assert_not_called()

    def test_unsupported_shape_or_expression_stops_before_api_calls(self):
        for changes in ({'answer_shape': 'symbolic'}, {'expression': 'sin(x)'}):
            with self.subTest(changes=changes):
                client = CodeClient()
                report = execute_preparation(client, ready_report(**changes))
                self.assertEqual(report['comparison']['reason'], 'EXECUTION_MODULE_UNSUPPORTED')
                self.assertEqual(client.requests, [])

    def test_saved_preparation_claims_are_revalidated(self):
        original = ready_report()
        for field, value in (('status', 'NEEDS_CONFIRMATION'), ('route_executions', 1)):
            bad = deepcopy(original)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                restore_preparation(bad)
        bad = deepcopy(original)
        bad['intake']['confirmed']['input_hash'] = 'wrong'
        with self.assertRaises(ValueError):
            restore_preparation(bad)
        bad = deepcopy(original)
        bad['intake']['candidates'][1]['expression'] = 'x**3'
        with self.assertRaises(ValueError):
            restore_preparation(bad)

    def test_invalid_limits_do_not_spend_model_calls(self):
        for kwargs in ({'timeout': 0}, {'timeout': float('nan')}, {'max_guard_replans': 2}, {'max_guard_replans': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                execute_preparation(CodeClient(), ready_report(), **kwargs)


class ExecuteCLITests(unittest.TestCase):
    def test_cli_saves_audited_report(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'ready.json', Path(folder) / 'result.json'
            source.write_text(json.dumps(ready_report()), encoding='utf-8')
            with patch('app.execute.MetaSettings.from_dotenv', return_value=MetaSettings('fixture-token')):
                with patch('app.execute.MetaClient', return_value=CodeClient()), redirect_stdout(io.StringIO()) as stream:
                    status = main([str(source), '--output', str(target)])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['status'], 'VERIFIED')
            self.assertNotIn('fixture-token', stream.getvalue())

    def test_cli_handles_missing_runtime_packages(self):
        result = subprocess.run([sys.executable, '-S', '-m', 'app.execute', 'unused.json'],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['status'], 'SETUP_REQUIRED')
        self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
