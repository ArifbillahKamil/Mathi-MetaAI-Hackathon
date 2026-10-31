"""Trusted receipts for finite, univariate, rational-coefficient integrals.

Loaded by file path in the isolated worker. Never eval/sympify input text.
"""

import ast
from decimal import Decimal, ROUND_CEILING, localcontext
from fractions import Fraction
import math
import warnings


class MethodCheckError(ValueError):
    pass


def decimal_fraction(value):
    text = str(value)
    if len(text) > 256:
        raise MethodCheckError("NUMBER_TOO_LARGE")
    number = Decimal(text)
    if not number.is_finite() or abs(number.as_tuple().exponent) > 1000 or abs(number.adjusted()) > 1000:
        raise MethodCheckError("NONFINITE_OR_UNSUPPORTED_NUMBER")
    return Fraction(number)


class Polynomial:
    def __init__(self, expression, variable):
        if not variable.isidentifier() or variable.startswith('_'):
            raise MethodCheckError("UNSUPPORTED_VARIABLE")
        self.expression, self.variable = expression, variable
        self.tree = ast.parse(expression, mode='eval').body
        if len(list(ast.walk(self.tree))) > 256:
            raise MethodCheckError("EXPRESSION_TOO_COMPLEX")
        self.terms = self.polynomial(self.tree)

    def bounded(self, terms):
        terms = {power: value for power, value in terms.items() if value}
        if any(power > 100 or value.numerator.bit_length() > 16384 or value.denominator.bit_length() > 16384 for power, value in terms.items()):
            raise MethodCheckError("POLYNOMIAL_TOO_COMPLEX")
        return terms

    def add(self, a, b, sign=1):
        out = dict(a)
        for power, value in b.items():
            out[power] = out.get(power, Fraction(0)) + sign * value
        return self.bounded(out)

    def multiply(self, a, b):
        out = {}
        for p, x in a.items():
            for q, y in b.items():
                out[p + q] = out.get(p + q, Fraction(0)) + x * y
        return self.bounded(out)

    def literal(self, node):
        if not isinstance(node, ast.Constant) or isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise MethodCheckError("UNSUPPORTED_POLYNOMIAL_SYNTAX")
        return decimal_fraction(ast.get_source_segment(self.expression, node).replace('_', ''))

    def polynomial(self, node):
        if isinstance(node, ast.Constant):
            return self.bounded({0: self.literal(node)})
        if isinstance(node, ast.Name) and node.id == self.variable:
            return {1: Fraction(1)}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            sign = -1 if isinstance(node.op, ast.USub) else 1
            return {power: sign * value for power, value in self.polynomial(node.operand).items()}
        if isinstance(node, ast.BinOp):
            a = self.polynomial(node.left)
            if isinstance(node.op, ast.Pow):
                exponent = self.literal(node.right)
                if exponent.denominator != 1 or not 0 <= exponent <= 100:
                    raise MethodCheckError("UNSUPPORTED_POLYNOMIAL_POWER")
                out = {0: Fraction(1)}
                for _ in range(int(exponent)):
                    out = self.multiply(out, a)
                return out
            b = self.polynomial(node.right)
            if isinstance(node.op, ast.Add):
                return self.add(a, b)
            if isinstance(node.op, ast.Sub):
                return self.add(a, b, -1)
            if isinstance(node.op, ast.Mult):
                return self.multiply(a, b)
            if isinstance(node.op, ast.Div) and set(b) == {0} and b[0]:
                return self.bounded({power: value / b[0] for power, value in a.items()})
        raise MethodCheckError("UNSUPPORTED_POLYNOMIAL_SYNTAX")

    def numeric(self, node, x):
        if isinstance(node, ast.Constant):
            return float(self.literal(node))
        if isinstance(node, ast.Name):
            return x
        if isinstance(node, ast.UnaryOp):
            value = self.numeric(node.operand, x)
            return -value if isinstance(node.op, ast.USub) else value
        a = self.numeric(node.left, x)
        if isinstance(node.op, ast.Pow):
            return a ** int(self.literal(node.right))
        b = self.numeric(node.right, x)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        return a / b


def rational_decimal(value):
    """Return a rounded decimal and a computed, upward-rounded error bound."""
    with localcontext() as context:
        context.prec = 50
        approximation = Decimal(value.numerator) / Decimal(value.denominator)
        difference = abs(value - Fraction(approximation))
        context.rounding = ROUND_CEILING
        error = Decimal(difference.numerator) / Decimal(difference.denominator)
    return str(approximation), str(error)


class Controller:
    def __init__(self, parameters):
        self.method = parameters['method']
        self.poly = Polynomial(parameters['expression'], parameters['variable'])
        self.lower, self.upper = decimal_fraction(parameters['lower']), decimal_fraction(parameters['upper'])
        self.calls, self.evaluations = 0, 0
        self.value, self.error = None, None
        self.validated = False
        if self.method == 'numerical_quadrature':
            import scipy.integrate as integration
            original = integration.quad

            def quad(function, a, b, *args, **kwargs):
                self.calls += 1
                if self.calls != 1 or args or set(kwargs) - {'epsabs', 'epsrel', 'limit'}:
                    raise MethodCheckError("UNSUPPORTED_QUADRATURE_CALL")
                if decimal_fraction(a) != self.lower or decimal_fraction(b) != self.upper:
                    raise MethodCheckError("INTEGRATION_BOUNDS_MISMATCH")

                def checked(x):
                    actual = function(x)
                    expected = self.poly.numeric(self.poly.tree, x)
                    if isinstance(actual, bool) or not math.isfinite(actual) or actual != expected:
                        raise MethodCheckError("INTEGRAND_SAMPLE_MISMATCH")
                    self.evaluations += 1
                    return actual

                with warnings.catch_warnings(record=True) as captured:
                    warnings.simplefilter('always')
                    value, error = original(checked, a, b, **kwargs)
                if captured or not math.isfinite(value) or not math.isfinite(error) or error < 0:
                    raise MethodCheckError("QUADRATURE_WARNING_OR_NONFINITE")
                self.value, self.error = decimal_fraction(value), decimal_fraction(error)
                self.wire_value, self.wire_error = str(value), str(error)
                return value, error

            integration.quad = quad
        elif self.method == 'symbolic_integration':
            import sympy as sp
            original = sp.integrate
            expected_symbol = sp.Symbol(self.poly.variable, real=True)
            expected_terms = {(power,): sp.Rational(value.numerator, value.denominator) for power, value in self.poly.terms.items()}

            def integrate(expression, *limits, **kwargs):
                self.calls += 1
                if self.calls != 1 or kwargs or len(limits) != 1 or len(limits[0]) != 3:
                    raise MethodCheckError("UNSUPPORTED_SYMBOLIC_CALL")
                symbol, a, b = limits[0]
                if not isinstance(symbol, sp.Symbol) or symbol.name != self.poly.variable:
                    raise MethodCheckError("INTEGRATION_VARIABLE_MISMATCH")
                if Fraction(str(a)) != self.lower or Fraction(str(b)) != self.upper:
                    raise MethodCheckError("INTEGRATION_BOUNDS_MISMATCH")
                if isinstance(expression, int) and not isinstance(expression, bool):
                    expression = sp.Integer(expression)
                if not isinstance(expression, sp.Expr) or any(item.name != self.poly.variable for item in expression.free_symbols):
                    raise MethodCheckError("INTEGRAND_EXPRESSION_MISMATCH")
                canonical = expression.xreplace({item: expected_symbol for item in expression.free_symbols})
                if sp.Poly(canonical, expected_symbol).as_dict() != expected_terms:
                    raise MethodCheckError("INTEGRAND_EXPRESSION_MISMATCH")
                value = original(expression, *limits)
                if not value.is_Rational or value.is_finite is not True:
                    raise MethodCheckError("EXACT_RESULT_NOT_RATIONAL")
                self.value, self.error = Fraction(int(value.p), int(value.q)), Fraction(0)
                self.wire_value, self.wire_error = rational_decimal(self.value)
                return value

            sp.integrate = integrate
        else:
            raise MethodCheckError("UNSUPPORTED_METHOD")

    def allow_import(self, name):
        allowed = {'pint', 'math'}
        allowed |= {'scipy.integrate', 'numpy'} if self.method == 'numerical_quadrature' else {'sympy'}
        return name in allowed

    def finalize(self, quantity, error):
        if self.calls != 1 or self.value is None:
            raise MethodCheckError("REQUIRED_SOLVER_NOT_EXECUTED")
        self.reported_unit = str(quantity.units)
        # A shared wrong scale (e.g. both routes labeling 9 as percent) must
        # not pass simply because Pint considers both units dimensionless.
        if quantity.dimensionless:
            quantity = quantity.to('dimensionless')
            if error is not None:
                error = error.to('dimensionless')
        if Fraction(str(quantity.magnitude)) != self.value:
            raise MethodCheckError("OUTPUT_NOT_SOLVER_RESULT")
        if error is None or Fraction(str(error.magnitude)) != self.error:
            raise MethodCheckError("ERROR_NOT_SOLVER_ESTIMATE")
        self.validated = True
        return {'value': self.wire_value, 'unit': str(quantity.units), 'absolute_error': self.wire_error}

    def snapshot(self):
        return {
            'method': self.method, 'solver_calls': self.calls,
            'checked_function_evaluations': self.evaluations,
            'output_matches_solver': self.validated,
            'reported_unit': getattr(self, 'reported_unit', None),
            'error_source': 'scipy_quad_estimate' if self.method == 'numerical_quadrature' else 'exact_rational_with_decimal_conversion_bound',
        }


def create(parameters):
    return Controller(parameters)
