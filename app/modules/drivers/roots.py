"""Trusted real-root receipts and completeness checks, independent of peer output."""

from decimal import Decimal, ROUND_CEILING, localcontext
from fractions import Fraction
import importlib.util
import math
from pathlib import Path

import sympy as sp

_spec = importlib.util.spec_from_file_location('mathi_root_polynomial', Path(__file__).with_name('polynomial.py'))
_parser = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_parser)


class MethodCheckError(ValueError):
    pass


def decimal_up(value):
    with localcontext() as context:
        context.prec = 100
        context.rounding = ROUND_CEILING
        return str(Decimal(value.numerator) / Decimal(value.denominator))


class Controller:
    def __init__(self, parameters):
        self.method = parameters['method']
        self.source = _parser.Polynomial(parameters['expression'], parameters['variable'])
        if not self.source.terms or not 1 <= max(self.source.terms) <= 6:
            raise MethodCheckError('UNSUPPORTED_ROOT_POLYNOMIAL')
        self.symbol = sp.Symbol(parameters['variable'], real=True)
        self.poly = sp.Poly.from_dict({(power,): sp.Rational(value.numerator, value.denominator)
                                       for power, value in self.source.terms.items()}, self.symbol)
        # Audit-only exact real-root isolation proves coverage and distinguishes
        # roots. These intervals are never included in either model request.
        self.intervals = self.poly.intervals(eps=sp.Rational(1, 10**60))
        self.calls, self.evaluations = 0, 0
        self.records, self.receipts = [], []
        self.validated = False
        if self.method == 'symbolic_elimination':
            original = sp.solve

            def solve(expression, symbol, *args, **kwargs):
                self.calls += 1
                if self.calls != 1 or args or kwargs or not isinstance(symbol, sp.Symbol) or symbol.name != self.symbol.name or symbol.is_real is not True:
                    raise MethodCheckError('UNSUPPORTED_SYMBOLIC_ROOT_CALL')
                if not isinstance(expression, sp.Expr) or expression.free_symbols - {symbol}:
                    raise MethodCheckError('ROOT_EXPRESSION_MISMATCH')
                actual = sp.Poly(expression.xreplace({symbol: self.symbol}), self.symbol)
                if actual.as_dict() != self.poly.as_dict():
                    raise MethodCheckError('ROOT_EXPRESSION_MISMATCH')
                roots = original(expression, symbol)
                if not isinstance(roots, list):
                    raise MethodCheckError('UNSUPPORTED_SYMBOLIC_ROOT_RESULT')
                used = set()
                for root in roots:
                    if root.is_real is not True or root.is_finite is not True or root.has(sp.Float):
                        raise MethodCheckError('NONEXACT_OR_NONREAL_ROOT')
                    if sp.simplify(self.poly.as_expr().subs(self.symbol, root)) != 0:
                        raise MethodCheckError('ROOT_RESIDUAL_NOT_ZERO')
                    matches = [index for index, ((a, b), _) in enumerate(self.intervals)
                               if (root - a).is_nonnegative is True and (b - root).is_nonnegative is True]
                    if len(matches) != 1 or matches[0] in used:
                        raise MethodCheckError('AMBIGUOUS_OR_DUPLICATE_ROOT')
                    index = matches[0]
                    used.add(index)
                    (a, b), multiplicity = self.intervals[index]
                    if root.is_Rational:
                        text, error = _parser.rational_decimal(Fraction(int(root.p), int(root.q)))
                    else:
                        text = str(root.evalf(50))
                        point = Fraction(text)
                        error = decimal_up(max(abs(point - Fraction(a)), abs(point - Fraction(b))))
                    self.records.append({'root': root, 'value': text, 'error': error, 'interval': index})
                    self.receipts.append({'exact_value': str(root), 'multiplicity': multiplicity,
                                          'encoding_absolute_error_bound': error})
                if len(used) != len(self.intervals):
                    raise MethodCheckError('ROOT_SET_INCOMPLETE')
                return roots

            sp.solve = solve
        elif self.method == 'numerical_root_finding':
            import scipy.optimize as optimization
            original = optimization.brentq

            def brentq(function, a, b, *args, **kwargs):
                self.calls += 1
                if (self.calls > 6 or args or set(kwargs) - {'xtol', 'rtol', 'maxiter'}
                        or kwargs.get('xtol') != 1e-12 or kwargs.get('rtol') != 1e-14
                        or not math.isfinite(a) or not math.isfinite(b) or a >= b):
                    raise MethodCheckError('UNSUPPORTED_ROOT_SOLVER_CALL')
                maxiter = kwargs.get('maxiter', 100)
                if type(maxiter) is not int or not 1 <= maxiter <= 1000:
                    raise MethodCheckError('UNSUPPORTED_ROOT_SOLVER_CALL')

                def checked(point):
                    actual = function(point)
                    expected = self.source.numeric(self.source.tree, point)
                    if isinstance(actual, bool) or not math.isfinite(actual) or actual != expected:
                        raise MethodCheckError('ROOT_FUNCTION_MISMATCH')
                    self.evaluations += 1
                    return actual

                root, info = original(checked, a, b, full_output=True, disp=False, **kwargs)
                if not info.converged or not math.isfinite(root):
                    raise MethodCheckError('ROOT_SOLVER_NOT_CONVERGED')
                value = _parser.decimal_fraction(root)
                binary = Fraction.from_float(root)
                # Documented Brent termination criterion plus the exact binary
                # to decimal representation difference. No arbitrary floor.
                bound = Fraction('1e-12') + Fraction('1e-14') * abs(binary) + abs(binary - value)
                matches = [index for index, ((lo, hi), _) in enumerate(self.intervals)
                           if value - bound <= Fraction(lo) and Fraction(hi) <= value + bound]
                if len(matches) != 1 or any(record['interval'] == matches[0] for record in self.records):
                    raise MethodCheckError('AMBIGUOUS_OR_DUPLICATE_ROOT')
                error = decimal_up(bound)
                self.records.append({'root': value, 'value': str(root), 'error': error, 'interval': matches[0]})
                self.receipts.append({'bracket': [str(a), str(b)], 'converged': True,
                                      'xtol': '1e-12', 'rtol': '1e-14', 'absolute_error_bound': error})
                return root

            optimization.brentq = brentq
        else:
            raise MethodCheckError('UNSUPPORTED_METHOD')

    def allow_import(self, name):
        return name in ({'pint', 'sympy'} if self.method == 'symbolic_elimination' else {'pint', 'math', 'scipy.optimize'})

    def finalize_collection(self, quantities):
        if self.calls < 1:
            raise MethodCheckError('REQUIRED_SOLVER_NOT_EXECUTED')
        if len(self.records) != len(self.intervals) or len(quantities) != len(self.records):
            raise MethodCheckError('ROOT_SET_INCOMPLETE')
        units = {str(quantity.units) for quantity in quantities}
        if len(units) > 1:
            raise MethodCheckError('MIXED_ROOT_UNITS')
        common = next(iter(units), 'dimensionless')
        normalized = [quantity.to('dimensionless') if quantity.dimensionless else quantity for quantity in quantities]
        if quantities and all(quantity.dimensionless for quantity in quantities):
            common = 'dimensionless'
        unused = list(self.records)
        ordered = []
        for quantity in normalized:
            value = quantity.magnitude
            if self.method == 'symbolic_elimination':
                matches = [record for record in unused if sp.simplify(value - record['root']) == 0]
            else:
                matches = [record for record in unused if _parser.decimal_fraction(value) == record['root']]
            if len(matches) != 1:
                raise MethodCheckError('OUTPUT_NOT_SOLVER_RESULT')
            record = matches[0]
            unused.remove(record)
            ordered.append(record)
        self.validated = True
        return {'values': [record['value'] for record in ordered], 'unit': common,
                'absolute_errors': [record['error'] for record in ordered], 'answer_shape': 'set'}

    def snapshot(self):
        return {'method': self.method, 'solver_calls': self.calls,
                'checked_function_evaluations': self.evaluations, 'output_matches_solver': self.validated,
                'distinct_real_root_count': len(self.intervals),
                'covered_real_root_count': len({record['interval'] for record in self.records}),
                'coverage_check': 'exact_real_root_isolation_from_original_polynomial',
                'root_receipts': self.receipts,
                'error_source': ('exact_root_encoding_bound' if self.method == 'symbolic_elimination'
                                 else 'brentq_termination_bound_and_decimal_conversion')}


def create(parameters):
    return Controller(parameters)
