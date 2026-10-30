"""Behavior tests; synthetic tolerances here are not production calibration."""

from dataclasses import replace
from fractions import Fraction
import json
import unittest

from app.core.comparator import (
    CheckEvidence, CheckStatus, ComparisonContext, Reason, ScalarRoute,
    Verdict, compare_scalars,
)
from app.core.config import ScalarTolerance
from app.core.numbers import parse_scalar


PASSED = CheckEvidence("independence", CheckStatus.PASS, "Test fixture; no real guard has run.")
BASE_CONTEXT = ComparisonContext("dimensionless", PASSED, ())
TEST_TOLERANCE = ScalarTolerance("0.001", 0, "0.01", 0)


def route(value=1, unit="dimensionless", error="0.1", **kwargs):
    return ScalarRoute(value, unit, error, **kwargs)


def compare(a=None, b=None, *, context=BASE_CONTEXT, tolerance=TEST_TOLERANCE):
    return compare_scalars(a or route(), b or route(), context=context, tolerance=tolerance)


class ScalarComparisonTests(unittest.TestCase):
    def test_tight_agreement(self):
        result = compare(b=route("1.0005"))
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.reason, Reason.TIGHT_AGREEMENT)
        self.assertEqual(Fraction(result.evidence.absolute_difference), Fraction(1, 2000))

    def test_tight_boundary_is_inclusive(self):
        self.assertEqual(compare(b=route("1.001")).verdict, Verdict.VERIFIED)

    def test_loose_agreement_requires_documented_cause(self):
        context = replace(BASE_CONTEXT, deviation_cause="Observed step-size sensitivity in an executed solver check.")
        result = compare(b=route("1.005"), context=context)
        self.assertEqual(result.verdict, Verdict.VERIFIED_WITH_DEVIATION)
        self.assertEqual(result.reason, Reason.LOOSE_AGREEMENT)
        self.assertEqual(result.context.deviation_cause, context.deviation_cause)

    def test_loose_boundary_is_inclusive(self):
        context = replace(BASE_CONTEXT, deviation_cause="Solver discretization.")
        self.assertEqual(compare(b=route("1.01"), context=context).verdict, Verdict.VERIFIED_WITH_DEVIATION)

    def test_loose_agreement_without_cause_is_unverified(self):
        for cause in (None, "", "  "):
            with self.subTest(cause=cause):
                result = compare(b=route("1.005"), context=replace(BASE_CONTEXT, deviation_cause=cause))
                self.assertEqual(result.verdict, Verdict.UNVERIFIED)
                self.assertEqual(result.reason, Reason.DEVIATION_CAUSE_MISSING)
                self.assertIsNotNone(result.evidence)

    def test_disagreement(self):
        result = compare(b=route("1.02"))
        self.assertEqual(result.verdict, Verdict.CONFLICT)
        self.assertEqual(result.reason, Reason.NUMERIC_DISAGREEMENT)

    def test_comparison_is_symmetric(self):
        tolerance = ScalarTolerance(0, "0.01", 0, "0.02")
        forward = compare(route(100), route(101), tolerance=tolerance)
        backward = compare(route(101), route(100), tolerance=tolerance)
        self.assertEqual(forward.verdict, backward.verdict)
        self.assertEqual(forward.evidence.relative_difference, backward.evidence.relative_difference)

    def test_absolute_and_relative_tolerances_add(self):
        tolerance = ScalarTolerance("0.1", "0.001", "0.2", "0.002")
        result = compare(route(100, error=1), route("100.15", error=1), tolerance=tolerance)
        self.assertEqual(result.verdict, Verdict.VERIFIED)

    def test_zero_has_defined_relative_difference(self):
        result = compare(route(0, error=0), route(0, error=0))
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.evidence.relative_difference, "0")

    def test_near_zero_uses_absolute_limit(self):
        result = compare(route(0), route("0.0001"))
        self.assertEqual(result.verdict, Verdict.VERIFIED)

    def test_negative_values_compare_by_magnitude(self):
        result = compare(route(-10), route("-10.0005"))
        self.assertEqual(result.verdict, Verdict.VERIFIED)

    def test_opposite_signs_conflict(self):
        self.assertEqual(compare(route(-1), route(1)).verdict, Verdict.CONFLICT)

    def test_solver_error_caps_both_limits(self):
        tolerance = ScalarTolerance("0.1", 0, "0.2", 0)
        result = compare(route(1, error="1e-10"), route("1.0001", error="1e-10"), tolerance=tolerance)
        self.assertEqual(result.verdict, Verdict.CONFLICT)
        self.assertEqual(Fraction(result.evidence.error_budget), Fraction(2, 10**10))
        self.assertEqual(result.evidence.tight_limit, result.evidence.error_budget)
        self.assertEqual(result.evidence.loose_limit, result.evidence.error_budget)

    def test_zero_error_demands_exact_numeric_equality(self):
        result = compare(route(1, error=0), route("1.00000000000000001", error=0))
        self.assertEqual(result.verdict, Verdict.CONFLICT)

    def test_large_adjacent_integers_do_not_collapse_to_one_float(self):
        result = compare(route(10**30, error=0), route(10**30 + 1, error=0))
        self.assertEqual(result.verdict, Verdict.CONFLICT)
        self.assertEqual(result.evidence.absolute_difference, "1")

    def test_small_difference_survives_unit_conversion(self):
        context = replace(BASE_CONTEXT, expected_unit="m")
        result = compare(route(1, "m", 0), route("100.00000000000001", "cm", 0), context=context)
        self.assertEqual(result.verdict, Verdict.CONFLICT)
        self.assertEqual(Fraction(result.evidence.absolute_difference), Fraction(1, 10**16))

    def test_equivalent_units_agree(self):
        context = replace(BASE_CONTEXT, expected_unit="m/s")
        result = compare(route(10, "m/s", 0), route(36, "km/hour", 0), context=context)
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.evidence.route_a, result.evidence.route_b)

    def test_compound_units_agree(self):
        context = replace(BASE_CONTEXT, expected_unit="newton")
        result = compare(route(10, "newton", 0), route(10, "kg*m/s**2", 0), context=context)
        self.assertEqual(result.verdict, Verdict.VERIFIED)

    def test_unit_conversion_scales_error_estimate(self):
        context = replace(BASE_CONTEXT, expected_unit="m")
        result = compare(route(1, "m", 0), route("100.001", "cm", "0.0001"), context=context)
        self.assertEqual(result.verdict, Verdict.CONFLICT)
        self.assertEqual(Fraction(result.evidence.error_budget), Fraction(1, 10**6))

    def test_agreeing_wrong_dimensions_conflict(self):
        context = ComparisonContext(expected_unit="joule")
        result = compare(route(5, "kg"), route(5, "kg"), context=context)
        self.assertEqual(result.verdict, Verdict.CONFLICT)
        self.assertEqual(result.reason, Reason.UNIT_MISMATCH)

    def test_one_wrong_dimension_conflicts(self):
        context = replace(BASE_CONTEXT, expected_unit="m")
        result = compare(route(1, "m"), route(1, "s"), context=context)
        self.assertEqual(result.reason, Reason.UNIT_MISMATCH)

    def test_missing_units_are_not_assumed_dimensionless(self):
        for a, context in ((route(unit=None), BASE_CONTEXT), (route(), replace(BASE_CONTEXT, expected_unit=None))):
            with self.subTest(a=a, context=context):
                result = compare(a=a, context=context)
                self.assertEqual(result.verdict, Verdict.UNVERIFIED)
                self.assertEqual(result.reason, Reason.UNIT_CHECK_UNAVAILABLE)

    def test_unknown_unit_does_not_crash(self):
        result = compare(a=route(unit="imaginary_mathi_unit"))
        self.assertEqual(result.reason, Reason.UNIT_CHECK_UNAVAILABLE)

    def test_malformed_units_do_not_crash(self):
        for unit in ("m**", "m/(", "m + s", "2*m", "1/0*m"):
            with self.subTest(unit=unit):
                result = compare(a=route(unit=unit))
                self.assertEqual(result.verdict, Verdict.UNVERIFIED)
                self.assertEqual(result.reason, Reason.UNIT_CHECK_UNAVAILABLE)

    def test_fractional_unit_powers_are_explicitly_unsupported(self):
        for source, expected in (("cm**0.5", "m**0.5"), ("mm**0.5*m**0.5", "m")):
            with self.subTest(source=source):
                context = replace(BASE_CONTEXT, expected_unit=expected)
                result = compare(route(10, source), route(1, expected), context=context)
                self.assertEqual(result.verdict, Verdict.UNVERIFIED)
                self.assertEqual(result.reason, Reason.UNSUPPORTED_UNIT_CONVERSION)

    def test_offset_conversion_is_explicitly_unsupported(self):
        context = replace(BASE_CONTEXT, expected_unit="kelvin")
        result = compare(route(0, "degC"), route("273.15", "kelvin"), context=context)
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertEqual(result.reason, Reason.UNSUPPORTED_UNIT_CONVERSION)

    def test_missing_result(self):
        result = compare(a=route(value=None))
        self.assertEqual(result.reason, Reason.MISSING_RESULT)

    def test_failed_execution_is_unverified(self):
        for failed in (route(execution_error="timeout"), route(execution_error="")):
            with self.subTest(failed=failed):
                result = compare(a=failed)
                self.assertEqual(result.verdict, Verdict.UNVERIFIED)
                self.assertEqual(result.reason, Reason.ROUTE_FAILED)

    def test_nonfinite_numbers_never_verify_even_if_equal(self):
        for value in (float("nan"), float("inf"), -float("inf"), "NaN", "Infinity"):
            with self.subTest(value=value):
                result = compare(route(value), route(value))
                self.assertEqual(result.verdict, Verdict.UNVERIFIED)
                self.assertEqual(result.reason, Reason.NONFINITE_VALUE)
                json.dumps(result.to_dict(), allow_nan=False)

    def test_complex_booleans_and_other_shapes_are_explicitly_unsupported(self):
        for value in (1 + 0j, True, [1], {"x": 1}, "sqrt(2)", "1/3", "1e1001"):
            with self.subTest(value=value):
                result = compare(route(value), route(value))
                self.assertEqual(result.verdict, Verdict.UNVERIFIED)
                self.assertEqual(result.reason, Reason.UNSUPPORTED_VALUE)

    def test_missing_or_failed_independence_never_verifies(self):
        for independence in (None, replace(PASSED, status=CheckStatus.FAIL), replace(PASSED, status=CheckStatus.NOT_RUN)):
            with self.subTest(independence=independence):
                result = compare(context=replace(BASE_CONTEXT, independence=independence))
                self.assertEqual(result.verdict, Verdict.UNVERIFIED)
                self.assertEqual(result.reason, Reason.INDEPENDENCE_NOT_ESTABLISHED)

    def test_missing_or_incomplete_sanity_checks_never_verify(self):
        pending = CheckEvidence("nonnegative_mass", CheckStatus.NOT_RUN, "Check timed out.")
        for checks in (None, (pending,)):
            with self.subTest(checks=checks):
                result = compare(context=replace(BASE_CONTEXT, sanity_checks=checks))
                self.assertEqual(result.verdict, Verdict.UNVERIFIED)
                self.assertEqual(result.reason, Reason.SANITY_NOT_RUN)

    def test_failed_sanity_check_lowers_agreement_to_conflict(self):
        failed = CheckEvidence("probability_bounds", CheckStatus.FAIL, "Probability exceeds 1.")
        result = compare(route(2), route(2), context=replace(BASE_CONTEXT, sanity_checks=(failed,)))
        self.assertEqual(result.verdict, Verdict.CONFLICT)
        self.assertEqual(result.reason, Reason.SANITY_FAILED)

    def test_passing_sanity_cannot_raise_disagreement(self):
        passed = CheckEvidence("positive", CheckStatus.PASS, "Both values are positive.")
        result = compare(b=route(2), context=replace(BASE_CONTEXT, sanity_checks=(passed,)))
        self.assertEqual(result.verdict, Verdict.CONFLICT)

    def test_missing_error_estimate_even_when_results_equal(self):
        result = compare(a=route(error=None))
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertEqual(result.reason, Reason.MISSING_ERROR_ESTIMATE)

    def test_invalid_error_estimates(self):
        for error in (-1, "NaN", "Infinity", True, "unknown"):
            with self.subTest(error=error):
                result = compare(a=route(error=error))
                self.assertEqual(result.verdict, Verdict.UNVERIFIED)
                self.assertEqual(result.reason, Reason.INVALID_ERROR_ESTIMATE)

    def test_correction_requires_tight_agreement(self):
        context = replace(BASE_CONTEXT, corrected_after_conflict=True, deviation_cause="Solver step size.")
        result = compare(b=route("1.005"), context=context)
        self.assertEqual(result.verdict, Verdict.CONFLICT)
        self.assertEqual(result.reason, Reason.CORRECTION_REQUIRES_TIGHT)

    def test_corrected_tight_agreement_records_correction(self):
        result = compare(context=replace(BASE_CONTEXT, corrected_after_conflict=True))
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertTrue(result.context.corrected_after_conflict)

    def test_audit_result_serializes_with_exact_evidence(self):
        result = compare(b=route("1.0005"))
        record = json.loads(json.dumps(result.to_dict(), allow_nan=False))
        self.assertEqual(record["verdict"], "VERIFIED")
        self.assertEqual(record["reason"], "TIGHT_AGREEMENT")
        self.assertEqual(record["context"]["independence"]["detail"], PASSED.detail)
        self.assertEqual(record["evidence"]["absolute_difference"], "1/2000")


class ToleranceConfigurationTests(unittest.TestCase):
    def test_invalid_or_negative_tolerances_are_rejected(self):
        for value in (-1, "NaN", "Infinity", True, "bad"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ScalarTolerance(value, 0, 1, 0)

    def test_loose_must_not_be_stricter_than_tight(self):
        for values in ((2, 0, 1, 0), (0, 2, 0, 1)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                ScalarTolerance(*values)

    def test_zero_tolerances_are_valid(self):
        self.assertEqual(ScalarTolerance(0, 0, 0, 0).fractions(), (0, 0, 0, 0))

    def test_tolerances_have_no_implicit_defaults(self):
        with self.assertRaises(TypeError):
            ScalarTolerance()


class NumericInputTests(unittest.TestCase):
    def test_decimal_string_keeps_more_than_float_precision(self):
        self.assertEqual(parse_scalar("1.00000000000000001"), Fraction(100000000000000001, 10**17))

    def test_float_uses_its_serialized_decimal_value(self):
        self.assertEqual(parse_scalar(0.1), Fraction(1, 10))

    def test_input_size_and_exponent_are_bounded(self):
        for value in ("1" * 257, "1e-1001", "1e1001", "not a number"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_scalar(value)


if __name__ == "__main__":
    unittest.main()
