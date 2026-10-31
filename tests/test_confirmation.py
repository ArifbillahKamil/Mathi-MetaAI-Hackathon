"""Regression coverage for saved unit-null intake and explicit confirmation."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.core.intake import IntakeStatus, intake, select_interpretation
from app.core.preparation import confirm_preparation, prepare
from app.llm.meta import MetaSettings
from app.prepare import main
from tests.preparation_fixtures import TEXT, client_for, plan_payload, problem_payload


def saved_unit_null_report():
    # Matches the owner-reported failure: both parses agree, but unit is null.
    first = problem_payload(expected_unit=None)
    second = problem_payload(expected_unit=None, interpretation='Compute the definite integral of x**2 from 0 to 3.')
    return prepare(client_for(first, second), TEXT)


class ConfirmationTests(unittest.TestCase):
    def test_unit_null_report_names_the_actual_missing_field(self):
        record = saved_unit_null_report()
        self.assertEqual(record['status'], 'NEEDS_CONFIRMATION')
        self.assertEqual(record['intake']['mismatched_fields'], [])
        self.assertEqual(record['intake']['confirmation_reasons'], ['MISSING_EXPECTED_UNIT'])
        self.assertIsNone(record['planning'])

    def test_pure_math_null_is_not_silently_changed_to_dimensionless(self):
        record = saved_unit_null_report()
        self.assertIsNone(record['intake']['candidates'][0]['expected_unit'])
        self.assertIsNone(record['intake']['confirmed'])

    def test_physical_missing_units_still_require_confirmation(self):
        payload = problem_payload(problem_class='engineering', task='work_energy', expected_unit=None)
        record = prepare(client_for(payload, payload), 'Find work from the supplied physical quantities.')
        self.assertEqual(record['status'], 'NEEDS_CONFIRMATION')
        self.assertIn('MISSING_EXPECTED_UNIT', record['intake']['confirmation_reasons'])
        self.assertIsNone(record['planning'])

    def test_explicit_missing_unit_is_recorded_as_user_information(self):
        payload = problem_payload(expected_unit=None)
        pending = intake(client_for(payload, payload), TEXT)
        confirmed = select_interpretation(pending, 1, expected_unit=' dimensionless ')
        self.assertEqual(confirmed.problem.expected_unit, 'dimensionless')
        self.assertEqual(confirmed.to_dict()['user_expected_unit'], 'dimensionless')
        self.assertEqual(confirmed.to_dict()['origin'], 'user_confirmed')
        self.assertIsNone(pending.candidates[0].expected_unit)

    def test_saved_report_continues_at_planner_without_repeating_intake(self):
        saved = saved_unit_null_report()
        client = client_for(plan_payload())
        resumed = confirm_preparation(client, saved, 1, expected_unit='dimensionless')
        self.assertEqual(resumed['status'], 'READY_FOR_ROUTES')
        self.assertEqual(client.complete.call_count, 1)
        request = client.complete.call_args.args[0]
        self.assertIn('confirmed_problem', json.loads(request.messages[1].content))
        self.assertEqual(resumed['route_executions'], 0)
        self.assertNotIn('verdict', resumed)

    def test_original_candidates_responses_and_source_report_are_preserved(self):
        saved = saved_unit_null_report()
        snapshot = deepcopy(saved)
        resumed = confirm_preparation(client_for(plan_payload()), saved, 1, expected_unit='dimensionless')
        self.assertEqual(saved, snapshot)
        self.assertEqual(resumed['intake']['attempts'], saved['intake']['attempts'])
        self.assertEqual(resumed['intake']['candidates'], saved['intake']['candidates'])
        self.assertIsNone(resumed['intake']['candidates'][0]['expected_unit'])
        self.assertEqual(resumed['intake']['confirmed']['problem']['expected_unit'], 'dimensionless')
        self.assertEqual(resumed['intake']['confirmation']['choice'], 1)
        self.assertEqual(resumed['intake']['confirmation_reasons'], [])
        self.assertEqual(resumed['intake']['confirmation']['prior_confirmation_reasons'], ['MISSING_EXPECTED_UNIT'])

    def test_selection_without_missing_unit_information_still_stops(self):
        client = Mock()
        with self.assertRaises(ValueError):
            confirm_preparation(client, saved_unit_null_report(), 1)
        client.complete.assert_not_called()

    def test_supplied_unit_cannot_override_a_conflicting_existing_unit(self):
        saved = prepare(client_for(problem_payload(), problem_payload(expression='x**3')), TEXT)
        client = Mock()
        with self.assertRaises(ValueError):
            confirm_preparation(client, saved, 1, expected_unit='kg')
        client.complete.assert_not_called()

    def test_other_uncertainties_are_not_cleared_by_unit_confirmation(self):
        payload = problem_payload(expected_unit=None, uncertainties=['Missing upper integration bound.'])
        saved = prepare(client_for(payload, payload), TEXT)
        client = Mock()
        with self.assertRaises(ValueError):
            confirm_preparation(client, saved, 1, expected_unit='dimensionless')
        client.complete.assert_not_called()

    def test_second_complete_candidate_can_be_explicitly_selected(self):
        saved = prepare(client_for(problem_payload(), problem_payload(expression='x**3')), TEXT)
        resumed = confirm_preparation(client_for(plan_payload()), saved, 2)
        self.assertEqual(resumed['intake']['confirmed']['problem']['expression'], 'x**3')
        self.assertEqual(resumed['intake']['confirmation']['choice'], 2)

    def test_invalid_report_claims_never_reach_planner(self):
        base = saved_unit_null_report()
        cases = []
        for changes in (
            {'stage': 'SOLVED'}, {'status': 'READY_FOR_ROUTES'},
            {'route_executions': 1}, {'route_executions': False}, {'planning': {}},
        ):
            amended = deepcopy(base)
            amended.update(changes)
            cases.append(amended)
        for field, value in (('confirmed', {}), ('raw_input', ''), ('candidates', [])):
            amended = deepcopy(base)
            amended['intake'][field] = value
            cases.append(amended)
        for saved in cases:
            client = Mock()
            with self.subTest(saved=saved), self.assertRaises(ValueError):
                confirm_preparation(client, saved, 1, expected_unit='dimensionless')
            client.complete.assert_not_called()

    def test_selected_candidate_schema_cannot_inject_a_verdict(self):
        saved = saved_unit_null_report()
        saved['intake']['candidates'][0]['verdict'] = 'VERIFIED'
        client = Mock()
        with self.assertRaises(ValueError):
            confirm_preparation(client, saved, 1, expected_unit='dimensionless')
        client.complete.assert_not_called()

    def test_invalid_choices_or_units_never_reach_planner(self):
        saved = saved_unit_null_report()
        for choice, unit in ((True, 'dimensionless'), (0, 'dimensionless'), (1.0, 'dimensionless'), (1, ''), (1, ' '), (1, 'm'*257)):
            client = Mock()
            with self.subTest(choice=choice, unit=unit), self.assertRaises(ValueError):
                confirm_preparation(client, saved, choice, expected_unit=unit)
            client.complete.assert_not_called()


class ConfirmationCLITests(unittest.TestCase):
    def test_cli_confirms_saved_report_and_preserves_original_file(self):
        saved = saved_unit_null_report()
        client = client_for(plan_payload())
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'input.json'
            output = Path(folder) / 'confirmed.json'
            source.write_text(json.dumps(saved), encoding='utf-8')
            with patch('app.prepare.MetaSettings.from_dotenv', return_value=MetaSettings('fixture-token')):
                with patch('app.prepare.MetaClient', return_value=client), redirect_stdout(io.StringIO()) as stream:
                    status = main(['--confirm-report', str(source), '--choice', '1', '--expected-unit', 'dimensionless', '--output', str(output)])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(source.read_text(encoding='utf-8')), saved)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['status'], 'READY_FOR_ROUTES')
            self.assertNotIn('fixture-token', stream.getvalue())
            self.assertEqual(client.complete.call_count, 1)

    def test_missing_explicit_choice_is_a_cli_error(self):
        with patch('app.prepare.MetaClient') as constructor:
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as captured:
                main(['--confirm-report', 'unused.json', '--expected-unit', 'dimensionless'])
        self.assertEqual(captured.exception.code, 2)
        constructor.assert_not_called()

    def test_text_and_saved_report_cannot_be_combined(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main([TEXT, '--confirm-report', 'unused.json', '--choice', '1'])

    def test_duplicate_json_keys_in_saved_report_are_rejected(self):
        client = Mock()
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'duplicate.json'
            source.write_text('{"stage":"a","stage":"PREPARATION_ONLY"}', encoding='utf-8')
            with patch('app.prepare.MetaSettings.from_dotenv', return_value=MetaSettings('fixture-token')):
                with patch('app.prepare.MetaClient', return_value=client), redirect_stdout(io.StringIO()) as stream:
                    status = main(['--confirm-report', str(source), '--choice', '1'])
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(stream.getvalue())['status'], 'INVALID_CONFIGURATION_OR_INPUT')
        client.complete.assert_not_called()


if __name__ == '__main__':
    unittest.main()
