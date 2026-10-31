"""Real answer-set matching, failure gates, and correction strictness."""

import unittest
from app.core.comparator import CheckEvidence, CheckStatus, ComparisonContext
from app.core.config import ScalarTolerance
from app.core.set_comparator import SetRoute, compare_sets

CONTEXT = ComparisonContext('dimensionless', CheckEvidence('fixture', CheckStatus.PASS, 'Fixture independent runs.'), ())
POLICY = ScalarTolerance('0.01', 0, '0.1', 0)


def route(values, errors=None, unit='dimensionless'):
    return SetRoute(tuple(values), unit, tuple(errors if errors is not None else ['0.01'] * len(values)))


class SetComparatorTests(unittest.TestCase):
    def compare(self, a, b, context=CONTEXT):
        return compare_sets(a, b, tolerance=POLICY, context=context)

    def test_order_and_exact_duplicates_do_not_change_sets(self):
        result = self.compare(route(['2', '1', '1']), route(['1', '2']))
        self.assertEqual(result.verdict, 'VERIFIED')
        self.assertEqual(len(result.evidence['matched_pairs']), 2)

    def test_one_to_one_matching_uses_augmenting_paths_instead_of_greedy(self):
        result = self.compare(route(['0.01', '0']), route(['0.005', '0.02']))
        self.assertEqual(result.verdict, 'VERIFIED')

    def test_a_missing_root_or_extra_root_is_conflict(self):
        result = self.compare(route(['1', '2']), route(['1']))
        self.assertEqual(result.reason, 'SET_CARDINALITY_MISMATCH')

    def test_nearby_distinct_roots_are_not_deduplicated(self):
        self.assertEqual(self.compare(route(['1', '1.000001']), route(['1'])).verdict, 'CONFLICT')

    def test_different_sets_conflict_despite_passing_sanity(self):
        self.assertEqual(self.compare(route(['1', '2']), route(['1', '3'])).verdict, 'CONFLICT')

    def test_wrong_dimension_is_hard_conflict_even_for_empty_sets(self):
        self.assertEqual(self.compare(route([], unit='m'), route([])).reason, 'UNIT_MISMATCH')

    def test_nan_infinity_complex_and_missing_errors_cannot_verify(self):
        for a in (route(['nan']), route(['inf']), route([complex(1, 1)]), SetRoute(('1',), 'dimensionless')):
            self.assertEqual(self.compare(a, route(['1'])).verdict, 'UNVERIFIED')

    def test_missing_evidence_and_failed_execution_cannot_verify_empty_sets(self):
        self.assertEqual(self.compare(route([]), route([]), ComparisonContext('dimensionless')).verdict, 'UNVERIFIED')
        failed = SetRoute(execution_error='TIMEOUT')
        self.assertEqual(self.compare(failed, route([])).reason, 'ROUTE_FAILED')

    def test_tolerance_is_capped_by_each_pairs_method_errors(self):
        self.assertEqual(self.compare(route(['1'], ['1e-12']), route(['1.0001'], ['0'])).verdict, 'CONFLICT')

    def test_large_decimal_exponents_preserve_the_original_bounded_encoding(self):
        self.assertEqual(self.compare(route(['1e1000'], ['1e-1000']), route(['1e1000'], ['0'])).verdict, 'VERIFIED')

    def test_loose_agreement_requires_cause_and_corrections_require_tight(self):
        from dataclasses import replace
        a, b = route(['1'], ['0.1']), route(['1.05'], ['0'])
        self.assertEqual(self.compare(a, b).verdict, 'UNVERIFIED')
        context = replace(CONTEXT, deviation_cause='Deliberate lower precision fixture.')
        self.assertEqual(self.compare(a, b, context).verdict, 'VERIFIED_WITH_DEVIATION')
        self.assertEqual(self.compare(a, b, replace(context, corrected_after_conflict=True)).verdict, 'CONFLICT')


if __name__ == '__main__':
    unittest.main()
