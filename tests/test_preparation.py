"""Intake gates planning; preparation never runs generated code."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.core.preparation import prepare
from app.llm.meta import MetaSettings
from app.prepare import main
from tests.preparation_fixtures import TEXT, client_for, plan_payload, problem_payload


class PreparationTests(unittest.TestCase):
    def test_agreed_problem_enters_planning_without_execution(self):
        client = client_for(problem_payload(), problem_payload(), plan_payload())
        record = prepare(client, TEXT)
        self.assertEqual(record['status'], 'READY_FOR_ROUTES')
        self.assertEqual(client.complete.call_count, 3)
        self.assertEqual(record['route_executions'], 0)
        self.assertNotIn('verdict', record)
        self.assertEqual(record['intake']['confirmed']['problem']['interpretation'], problem_payload()['interpretation'])

    def test_disagreement_never_calls_planner(self):
        client = client_for(problem_payload(), problem_payload(expression='x**3'))
        record = prepare(client, TEXT)
        self.assertEqual(record['status'], 'NEEDS_CONFIRMATION')
        self.assertIsNone(record['planning'])
        self.assertEqual(client.complete.call_count, 2)

    def test_failed_intake_does_not_plan(self):
        client = client_for('not-json', problem_payload())
        record = prepare(client, TEXT)
        self.assertEqual(record['status'], 'UNVERIFIED')
        self.assertIsNone(record['planning'])

    def test_cli_saves_json_audit_and_returns_ready(self):
        client = client_for(problem_payload(), problem_payload(), plan_payload())
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'audit.json'
            with patch('app.prepare.MetaSettings.from_dotenv', return_value=MetaSettings('fixture-token')):
                with patch('app.prepare.MetaClient', return_value=client), redirect_stdout(io.StringIO()) as stream:
                    status = main([TEXT, '--output', str(output)])
            self.assertEqual(status, 0)
            record = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(record['status'], 'READY_FOR_ROUTES')
            self.assertNotIn('fixture-token', stream.getvalue())
            self.assertEqual(len(record['intake']['attempts']), 2)

    def test_cli_confirmation_exit_code_is_explicit(self):
        client = client_for(problem_payload(), problem_payload(expression='x**3'))
        with patch('app.prepare.MetaSettings.from_dotenv', return_value=MetaSettings('fixture-token')):
            with patch('app.prepare.MetaClient', return_value=client), redirect_stdout(io.StringIO()) as stream:
                status = main([TEXT])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(stream.getvalue())['status'], 'NEEDS_CONFIRMATION')

    def test_cli_reports_setup_instead_of_traceback_when_pydantic_is_missing(self):
        completed = subprocess.run(
            [sys.executable, '-S', '-m', 'app.prepare', TEXT],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(json.loads(completed.stdout)['status'], 'SETUP_REQUIRED')
        self.assertEqual(completed.stderr, '')


if __name__ == '__main__':
    unittest.main()
