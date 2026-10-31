"""Real execution receipts reject invented results, errors, and wrong problems."""

from fractions import Fraction
from types import SimpleNamespace
import unittest

from app.modules.drivers.polynomial import MethodCheckError, Polynomial, rational_decimal
from app.sandbox import ExecutionStatus, run_code
from app.sandbox.contracts import VerificationSpec
from tests.route_fixtures import NUMERIC, PRELUDE, SYMBOLIC


def verification(method, expression='x**2', upper='3'):
    return VerificationSpec('polynomial', tuple({
        'method': method, 'expression': expression, 'variable': 'x', 'lower': '0', 'upper': upper,
    }.items()))


class PolynomialParserTests(unittest.TestCase):
    def test_rational_polynomial_is_parsed_without_eval(self):
        self.assertEqual(Polynomial('(x + 1)**2 / 3', 'x').terms, {
            2: Fraction(1, 3), 1: Fraction(2, 3), 0: Fraction(1, 3),
        })

    def test_calls_attributes_unknown_variables_and_nonpolynomial_inputs_are_rejected(self):
        for expression in ("__import__('os')", 'x.real', 'y + 1', 'sin(x)', '1/x', 'x**-1', 'x**101'):
            with self.subTest(expression=expression), self.assertRaises((MethodCheckError, SyntaxError)):
                Polynomial(expression, 'x')

    def test_decimal_conversion_error_is_computed_and_rounded_up(self):
        value, error = rational_decimal(Fraction(1, 3))
        self.assertGreater(Fraction(error), 0)
        self.assertGreaterEqual(Fraction(error), abs(Fraction(1, 3) - Fraction(value)))
        self.assertEqual(rational_decimal(Fraction(9)), ('9', '0'))

    def test_widely_separated_error_estimates_keep_an_exact_comparator_cap(self):
        from app.modules.calculus import tolerance
        from app.core.comparator import CheckEvidence, CheckStatus, ComparisonContext, ScalarRoute, compare_scalars
        configured = tolerance({
            'A': SimpleNamespace(result={'absolute_error': '1e-1000'}),
            'B': SimpleNamespace(result={'absolute_error': '1e-13'}),
        })
        result = compare_scalars(
            ScalarRoute(9, 'dimensionless', '1e-1000'), ScalarRoute(9, 'dimensionless', '1e-13'),
            tolerance=configured,
            context=ComparisonContext('dimensionless', CheckEvidence('fixture', CheckStatus.PASS, 'Test fixture'), ()),
        )
        self.assertEqual(Fraction(result.evidence.tight_limit), Fraction(1, 10**1000) + Fraction(1, 10**13))


class MethodReceiptTests(unittest.TestCase):
    def test_real_quad_call_produces_validated_receipt(self):
        result = run_code(NUMERIC, verification=verification('numerical_quadrature'))
        self.assertEqual(result.status, ExecutionStatus.SUCCESS, result.to_dict())
        self.assertTrue(result.method_evidence['output_matches_solver'])
        self.assertGreater(result.method_evidence['checked_function_evaluations'], 0)
        self.assertEqual(result.method_evidence['error_source'], 'scipy_quad_estimate')

    def test_real_symbolic_call_produces_exact_result_receipt(self):
        result = run_code(SYMBOLIC, verification=verification('symbolic_integration'))
        self.assertEqual(result.status, ExecutionStatus.SUCCESS, result.to_dict())
        self.assertEqual(result.result['value'], '9')
        self.assertEqual(result.result['absolute_error'], '0')
        self.assertTrue(result.method_evidence['output_matches_solver'])

    def test_constant_answer_without_solver_cannot_succeed(self):
        code = PRELUDE + "result = {'quantity': u.Quantity(9, 'dimensionless'), 'absolute_error': u.Quantity(0, 'dimensionless')}"
        result = run_code(code, verification=verification('numerical_quadrature'))
        self.assertEqual(result.status, ExecutionStatus.INVALID_RESULT, result.to_dict())
        self.assertIn('REQUIRED_SOLVER_NOT_EXECUTED', result.error)

    def test_model_cannot_replace_executed_value_or_error(self):
        for code, error in (
            (NUMERIC.replace("u.Quantity(value,", "u.Quantity(123,"), 'OUTPUT_NOT_SOLVER_RESULT'),
            (NUMERIC.replace("u.Quantity(error,", "u.Quantity(0.01,"), 'ERROR_NOT_SOLVER_ESTIMATE'),
        ):
            with self.subTest(error=error):
                result = run_code(code, verification=verification('numerical_quadrature'))
                self.assertEqual(result.status, ExecutionStatus.INVALID_RESULT, result.to_dict())
                self.assertIn(error, result.error)

    def test_wrong_bounds_or_numeric_integrand_cannot_succeed(self):
        for code, error in (
            (NUMERIC.replace('0, 3)', '0, 2)'), 'INTEGRATION_BOUNDS_MISMATCH'),
            (NUMERIC.replace('lambda x: x**2', 'lambda x: x**3'), 'INTEGRAND_SAMPLE_MISMATCH'),
        ):
            with self.subTest(error=error):
                result = run_code(code, verification=verification('numerical_quadrature'))
                self.assertEqual(result.status, ExecutionStatus.INVALID_RESULT, result.to_dict())
                self.assertIn(error, result.error)

    def test_wrong_symbolic_integrand_cannot_succeed(self):
        result = run_code(SYMBOLIC.replace('sp.integrate(x**2', 'sp.integrate(x**3'), verification=verification('symbolic_integration'))
        self.assertEqual(result.status, ExecutionStatus.INVALID_RESULT, result.to_dict())
        self.assertIn('INTEGRAND_EXPRESSION_MISMATCH', result.error)

    def test_rational_symbolic_answer_preserves_conversion_uncertainty(self):
        code = SYMBOLIC.replace('(x, 0, 3)', '(x, 0, 1)')
        result = run_code(code, verification=verification('symbolic_integration', upper='1'))
        self.assertEqual(result.status, ExecutionStatus.SUCCESS, result.to_dict())
        difference = abs(Fraction(result.result['value']) - Fraction(1, 3))
        self.assertLessEqual(difference, Fraction(result.result['absolute_error']))
        self.assertGreater(Fraction(result.result['absolute_error']), 0)

    def test_method_import_restriction_and_module_mutation_are_enforced(self):
        result = run_code('import sympy as sp\n' + NUMERIC, verification=verification('numerical_quadrature'))
        self.assertEqual(result.status, ExecutionStatus.RUNTIME_ERROR, result.to_dict())
        self.assertIn('assigned mathematical method', result.error)
        patched = run_code('import sympy as sp\nsp.integrate = lambda x: 9')
        self.assertEqual(patched.status, ExecutionStatus.REJECTED)
        self.assertEqual(patched.error, 'ATTRIBUTE_MUTATION_NOT_ALLOWED')

    def test_dimensionless_scale_cannot_change_the_solver_answer(self):
        result = run_code(NUMERIC.replace("'dimensionless'", "'percent'"), verification=verification('numerical_quadrature'))
        self.assertEqual(result.status, ExecutionStatus.INVALID_RESULT, result.to_dict())
        self.assertIn('OUTPUT_NOT_SOLVER_RESULT', result.error)

    def test_constant_zero_can_be_checked_symbolically(self):
        code = SYMBOLIC.replace('sp.integrate(x**2', 'sp.integrate(0')
        result = run_code(code, verification=verification('symbolic_integration', expression='0'))
        self.assertEqual(result.status, ExecutionStatus.SUCCESS, result.to_dict())
        self.assertEqual(result.result['value'], '0')


if __name__ == '__main__':
    unittest.main()
