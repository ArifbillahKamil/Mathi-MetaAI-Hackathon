"""Dimension-aware engineering contracts and actual sandbox executions."""

from fractions import Fraction
import unittest

from app.core.execution import execute_preparation, restore_preparation
from app.modules import engineering, select_module
from app.sandbox import run_code, ExecutionStatus
from tests.lift_fixtures import ENERGY, FORCE, LiftClient, ready


def spec(method, saved=None):
    confirmed, planned = restore_preparation(saved or ready())
    return engineering._route(confirmed.problem, method)


class EngineeringTests(unittest.TestCase):
    def test_missing_gravity_or_added_motion_assumptions_stop_before_planning(self):
        from tests.lift_fixtures import problem, TEXT
        from tests.preparation_fixtures import client_for
        from app.core.preparation import prepare
        for changes in ({'uncertainties': ['Gravity was not supplied.']},
                        {'assumptions': ['Assume constant speed and no losses.']}):
            payload = problem(**changes)
            client = client_for(payload, payload)
            result = prepare(client, TEXT)
            self.assertEqual(result['status'], 'NEEDS_CONFIRMATION')
            self.assertIsNone(result['planning'])
            self.assertEqual(client.complete.call_count, 2)

    def test_module_selects_existing_method_pair_without_new_core_task(self):
        confirmed, planned = restore_preparation(ready())
        self.assertIs(select_module(confirmed.problem), engineering)
        self.assertIsNone(engineering.plan(confirmed, planned))
        self.assertEqual(engineering.route_a(confirmed, planned).driver, 'lift')

    def test_exact_energy_route_uses_original_mixed_units(self):
        from app.core.independence import Method
        result = run_code(ENERGY, verification=spec(Method.ENERGY_BALANCE))
        self.assertEqual(result.status, ExecutionStatus.SUCCESS, result.to_dict())
        self.assertEqual(Fraction(result.result['value']), Fraction('98.1'))
        self.assertEqual(result.result['unit'], 'joule')
        self.assertEqual(result.result['absolute_error'], '0')

    def test_force_route_integrates_correct_force_and_keeps_solver_error(self):
        from app.core.independence import Method
        result = run_code(FORCE, verification=spec(Method.FORCE_BALANCE))
        self.assertEqual(result.status, ExecutionStatus.SUCCESS, result.to_dict())
        self.assertEqual(result.method_evidence['solver_calls'], 1)
        self.assertGreater(result.method_evidence['checked_function_evaluations'], 0)
        self.assertGreater(Fraction(result.method_evidence['solver_absolute_error']), 0)

    def test_full_blind_workflow_returns_verified_energy_with_two_real_methods(self):
        client = LiftClient()
        report = execute_preparation(client, ready())
        self.assertEqual(report['status'], 'VERIFIED', report['comparison'])
        self.assertEqual(report['route_executions'], 2)
        self.assertEqual(report['self_correction'], 'NOT_NEEDED')
        self.assertEqual(len(client.requests), 2)
        self.assertEqual(Fraction(report['final_answer']['value']), Fraction('98.1'))
        self.assertEqual(report['final_answer']['source_route'], 'A')

    def test_wrong_dimension_is_conflict_even_when_both_numbers_match(self):
        report = execute_preparation(LiftClient(energy=[ENERGY.replace("'joule'", "'meter'")]), ready(), max_corrections=0)
        self.assertEqual(report['status'], 'CONFLICT', report['comparison'])
        self.assertEqual(report['comparison']['reason'], 'UNIT_MISMATCH')
        self.assertIsNone(report['final_answer'])

    def test_hardcoded_answer_without_method_cannot_be_verified(self):
        bad = "import pint\nu=pint.UnitRegistry()\nresult={'quantity':u.Quantity(98.1,'joule'),'absolute_error':u.Quantity(0,'joule')}"
        report = execute_preparation(LiftClient(energy=[bad]), ready(), max_corrections=0)
        self.assertEqual(report['status'], 'UNVERIFIED')
        self.assertIn('REQUIRED_SOLVER_NOT_EXECUTED', report['routes']['A']['error'])

    def test_wrong_energy_formula_and_wrong_gravity_cannot_agree(self):
        for code in (ENERGY.replace('mass * gravity * height_change', 'mass * gravity * height_change * 2'),
                     ENERGY.replace("Rational('981')", "Rational('980')")):
            report = execute_preparation(LiftClient(energy=[code]), ready(), max_corrections=0)
            self.assertEqual(report['status'], 'UNVERIFIED', report)

    def test_force_must_use_original_force_bounds_and_error(self):
        for code, marker in (
            (FORCE.replace('lambda position: weight', 'lambda position: weight * 2'), 'INTEGRAND_FORCE_MISMATCH'),
            (FORCE.replace('0, float(height_quantity.magnitude)', '1, float(height_quantity.magnitude)'), 'INTEGRATION_BOUNDS_MISMATCH'),
            (FORCE.replace('u.Quantity(error,', 'u.Quantity(1,'), 'ERROR_NOT_SOLVER_ESTIMATE'),
        ):
            report = execute_preparation(LiftClient(force=[code]), ready(), max_corrections=0)
            self.assertEqual(report['status'], 'UNVERIFIED', report)
            self.assertIn(marker, report['routes']['B']['error'])

    def test_missing_gravity_wrong_units_and_unsupported_model_fail_before_model_calls(self):
        cases = [ready(expression='inclined_plane'), ready(expected_unit='meter'), ready(expected_unit='made_up_unit')]
        for field, value in (('mass', '-1'), ('gravity', '0')):
            saved = ready()
            for candidate in saved['intake']['candidates'] + [saved['intake']['confirmed']['problem']]:
                next(item for item in candidate['givens'] if item['name'] == field)['value'] = value
            cases.append(saved)
        original = ready()['intake']['confirmed']['problem']['givens']
        cases.append(ready(givens=[item for item in original if item['name'] != 'gravity']))
        wrong = [dict(item, unit='second') if item['name'] == 'mass' else item for item in original]
        cases.append(ready(givens=wrong))
        for case in cases:
            client = LiftClient()
            report = execute_preparation(client, case)
            self.assertEqual(report['status'], 'UNVERIFIED')
            self.assertEqual(client.requests, [])

    def test_lowering_and_zero_displacement_have_correct_signed_work(self):
        for height, expected in (('-200', '-98.1'), ('0', '0')):
            saved = ready()
            givens = saved['intake']['confirmed']['problem']['givens']
            for item in givens:
                if item['name'] == 'height_change':
                    item['value'] = height
            prepared = ready(givens=givens)
            client = LiftClient(energy=[ENERGY.replace("Rational('200')", f"Rational('{height}')")],
                                force=[FORCE.replace("Rational('200')", f"Rational('{height}')")])
            report = execute_preparation(client, prepared)
            self.assertEqual(report['status'], 'VERIFIED', report['comparison'])
            self.assertEqual(Fraction(report['final_answer']['value']), Fraction(expected))

    def test_scaled_output_requires_conversion_and_expected_kilojoules_compare_correctly(self):
        valid = ENERGY.replace("u.Quantity(value, 'joule')", "u.Quantity(value, 'joule').to('kilojoule')")
        valid = valid.replace("u.Quantity(sp.Integer(0), 'joule')", "u.Quantity(sp.Integer(0), 'kilojoule')")
        report = execute_preparation(LiftClient(energy=[valid]), ready(expected_unit='kilojoule'))
        self.assertEqual(report['status'], 'VERIFIED', report['comparison'])
        self.assertEqual(Fraction(report['comparison']['evidence']['route_a']), Fraction('0.0981'))
        invalid = ENERGY.replace("'joule'", "'kilojoule'")
        report = execute_preparation(LiftClient(energy=[invalid]), ready(), max_corrections=0)
        self.assertEqual(report['status'], 'UNVERIFIED')
        self.assertIn('OUTPUT_NOT_SOLVER_RESULT', report['routes']['A']['error'])

    def test_justified_bound_converts_units_and_failed_bound_only_lowers_verdict(self):
        for upper, verdict in (('0.1', 'VERIFIED'), ('0.09', 'CONFLICT')):
            saved = ready(expected_unit='kilojoule')
            saved['planning']['plan']['sanity_checks'] = [
                {'name': 'energy_bound', 'lower': '0', 'upper': upper, 'unit': 'kilojoule'}]
            report = execute_preparation(LiftClient(), saved, max_corrections=0)
            self.assertEqual(report['status'], verdict, report['comparison'])

    def test_engineering_blind_fix_uses_existing_correction_pipeline(self):
        client = LiftClient(energy=['missing_name\n' + ENERGY, ENERGY])
        report = execute_preparation(client, ready())
        self.assertEqual(report['status'], 'VERIFIED', report['comparison'])
        self.assertEqual(report['self_correction'], 'CORRECTED')
        self.assertEqual(report['route_executions'], 3)
        self.assertTrue(report['final_answer']['corrected_after_conflict'])

    def test_numerical_input_representation_has_its_own_audited_bound(self):
        report = execute_preparation(LiftClient(), ready())
        receipt = report['routes']['B']['method_evidence']
        self.assertGreater(Fraction(receipt['input_representation_error_bound']), 0)
        total = Fraction(report['routes']['B']['result']['absolute_error'])
        self.assertGreaterEqual(total, Fraction(receipt['solver_absolute_error']) + Fraction(receipt['input_representation_error_bound']))


if __name__ == '__main__':
    unittest.main()
