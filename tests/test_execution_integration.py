"""Exercise two real independent processes through deterministic comparison."""

from fractions import Fraction
import json
import unittest

from app.demo import run_demo


class ExecutedPairTests(unittest.TestCase):
    def test_executed_symbolic_and_numeric_routes_produce_auditable_agreement(self):
        record = run_demo()
        self.assertEqual(record['run_kind'], 'offline_component_demo')
        self.assertEqual(record['code_origin'], 'curated_fixture_not_model_generated')
        self.assertEqual(record['model_requests_sent'], 0)
        self.assertEqual(record['routes']['A']['status'], 'SUCCESS')
        self.assertEqual(record['routes']['B']['status'], 'SUCCESS')
        self.assertEqual(record['comparison']['verdict'], 'VERIFIED')
        self.assertEqual(Fraction(record['comparison']['evidence']['route_a']), 9)
        difference = Fraction(record['comparison']['evidence']['absolute_difference'])
        limit = Fraction(record['comparison']['evidence']['tight_limit'])
        self.assertLessEqual(difference, limit)
        self.assertNotEqual(record['independence']['code_a_hash'], record['independence']['code_b_hash'])
        json.dumps(record, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
