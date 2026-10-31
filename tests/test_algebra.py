"""Executed symbolic and numerical roots, completeness, and blind repair."""

from fractions import Fraction
import json
import unittest

from app.core.execution import execute_preparation
from tests.root_fixtures import RootsClient, numeric, ready, symbolic


class AlgebraTests(unittest.TestCase):
    def solve(self, expression='x**2 - 3*x + 2', brackets=((0, 1.5), (1.5, 3))):
        return execute_preparation(RootsClient([symbolic(expression)], [numeric(expression, brackets)]), ready(expression))

    def test_two_actual_methods_verify_a_complete_root_set(self):
        report = self.solve()
        self.assertEqual(report['status'], 'VERIFIED', report['routes'])
        self.assertEqual({Fraction(value) for value in report['final_answer']['values']}, {1, 2})
        self.assertEqual(report['final_answer']['source_route'], 'A')
        for route in report['routes'].values():
            self.assertTrue(route['method_evidence']['output_matches_solver'])
            self.assertEqual(route['method_evidence']['covered_real_root_count'], 2)
        json.dumps(report, allow_nan=False)

    def test_reversing_output_order_has_no_effect(self):
        code = symbolic().replace('for root in roots]', 'for root in roots[::-1]]')
        report = execute_preparation(RootsClient([code]), ready())
        self.assertEqual(report['status'], 'VERIFIED', report['routes'])
        self.assertEqual(report['final_answer']['values'], ['2', '1'])

    def test_repeated_root_is_one_answer_and_multiplicity_is_audited(self):
        expression = '(x - 1)**2 * (x + 2)'
        report = self.solve(expression, ((0, 1), (-3, -1)))
        self.assertEqual(report['status'], 'VERIFIED', report['routes'])
        self.assertEqual({Fraction(value) for value in report['final_answer']['values']}, {-2, 1})
        multiplicities = [item['multiplicity'] for item in report['routes']['A']['method_evidence']['root_receipts']]
        self.assertEqual(sorted(multiplicities), [1, 2])

    def test_irrational_roots_use_audited_decimal_encoding_bounds(self):
        report = self.solve('x**2 - 2', ((-2, 0), (0, 2)))
        self.assertEqual(report['status'], 'VERIFIED', report['routes'])
        self.assertTrue(all(Fraction(error) > 0 for error in report['routes']['A']['result']['absolute_errors']))
        self.assertIn('sqrt(2)', str(report['routes']['A']['method_evidence']['root_receipts']))

    def test_missing_numeric_root_and_duplicate_calls_cannot_verify(self):
        for brackets, marker in ((((0, 1.5),), 'ROOT_SET_INCOMPLETE'),
                                 (((0, 1.5), (0, 1.5)), 'AMBIGUOUS_OR_DUPLICATE_ROOT')):
            report = execute_preparation(RootsClient(numeric_codes=[numeric(brackets=brackets)]), ready(), max_corrections=0)
            self.assertEqual(report['status'], 'UNVERIFIED')
            self.assertIn(marker, report['routes']['B']['error'])

    def test_omitting_a_symbolic_root_from_output_cannot_verify(self):
        code = symbolic().replace('for root in roots]', 'for root in roots[:1]]')
        report = execute_preparation(RootsClient([code]), ready(), max_corrections=0)
        self.assertEqual(report['status'], 'UNVERIFIED')
        self.assertIn('ROOT_SET_INCOMPLETE', report['routes']['A']['error'])

    def test_wrong_polynomial_or_numerical_function_cannot_verify(self):
        for client, label, marker in (
            (RootsClient([symbolic('x**2 - 4')]), 'A', 'ROOT_EXPRESSION_MISMATCH'),
            (RootsClient(numeric_codes=[numeric('x**2 - 4')]), 'B', 'ROOT_FUNCTION_MISMATCH'),
        ):
            report = execute_preparation(client, ready(), max_corrections=0)
            self.assertEqual(report['status'], 'UNVERIFIED')
            self.assertIn(marker, report['routes'][label]['error'])

    def test_wrong_units_are_hard_conflict(self):
        report = execute_preparation(RootsClient([symbolic().replace("'dimensionless'", "'meter'")]), ready(), max_corrections=0)
        self.assertEqual(report['status'], 'CONFLICT', report['comparison'])
        self.assertEqual(report['comparison']['reason'], 'UNIT_MISMATCH')

    def test_hardcoded_answers_and_replaced_solver_output_are_rejected(self):
        codes = ["import pint\nu=pint.UnitRegistry()\nresult={'quantities':[u.Quantity(1,'dimensionless'),u.Quantity(2,'dimensionless')]}",
                 symbolic().replace('u.Quantity(root,', 'u.Quantity(root + 1,')]
        for code in codes:
            report = execute_preparation(RootsClient([code]), ready(), max_corrections=0)
            self.assertEqual(report['status'], 'UNVERIFIED')

    def test_complex_domain_and_nonpolynomial_problem_stop_before_generation(self):
        for saved in (ready(domain='complex'), ready('1/x'), ready('x**7'), ready('0')):
            client = RootsClient()
            report = execute_preparation(client, saved)
            self.assertEqual(report['status'], 'UNVERIFIED')
            self.assertEqual(client.requests, [])

    def test_no_real_roots_do_not_claim_numeric_verification_without_execution(self):
        report = execute_preparation(RootsClient([symbolic('x**2 + 1')], [numeric('x**2 + 1', ())]), ready('x**2 + 1'), max_corrections=0)
        self.assertEqual(report['status'], 'UNVERIFIED')
        self.assertIn('REQUIRED_SOLVER_NOT_EXECUTED', report['routes']['B']['error'])

    def test_nearby_roots_that_share_an_error_neighborhood_are_ambiguous(self):
        expression = '(x - 1)*(x - 1.0000000000001)'
        # Exact rational coefficients for the symbolic route, original decimal
        # syntax for the independent numerical route.
        exact = symbolic(expression.replace('1.0000000000001', "sp.Rational('1.0000000000001')"))
        report = execute_preparation(RootsClient([exact], [numeric(expression, ((0, 1), (1, 2)))]), ready(expression), max_corrections=0)
        self.assertEqual(report['status'], 'UNVERIFIED')
        self.assertIn('AMBIGUOUS_OR_DUPLICATE_ROOT', report['routes']['B']['error'])

    def test_ordinary_runtime_failure_uses_existing_blind_correction(self):
        client = RootsClient(['missing_name\n' + symbolic(), symbolic()])
        report = execute_preparation(client, ready())
        self.assertEqual(report['status'], 'VERIFIED', report['routes'])
        self.assertEqual(report['route_executions'], 3)
        self.assertEqual(report['self_correction'], 'CORRECTED')
        self.assertTrue(report['final_answer']['corrected_after_conflict'])

    def test_missing_root_repair_gets_only_fixed_coverage_guidance(self):
        client = RootsClient(numeric_codes=[numeric(brackets=((0, 1.5),)), numeric()])
        report = execute_preparation(client, ready())
        self.assertEqual(report['status'], 'VERIFIED', report['comparison'])
        entry = report['correction_history'][0]
        self.assertEqual(entry['repair_reason_code'], 'ROOT_COVERAGE')
        self.assertEqual(entry['repaired_route'], 'B')
        self.assertIsNone(entry['arbiter'])
        payload = json.loads(entry['generation']['request']['messages'][1]['content'])
        self.assertEqual(set(payload), {'interpreted_problem', 'method', 'repair_reason_code'})
        self.assertEqual(report['route_executions'], 3)

    def test_inflated_numerical_tolerance_is_rejected(self):
        code = numeric().replace('xtol=1e-12', 'xtol=1e-4')
        report = execute_preparation(RootsClient(numeric_codes=[code]), ready(), max_corrections=0)
        self.assertEqual(report['status'], 'UNVERIFIED')
        self.assertIn('UNSUPPORTED_ROOT_SOLVER_CALL', report['routes']['B']['error'])


if __name__ == '__main__':
    unittest.main()
