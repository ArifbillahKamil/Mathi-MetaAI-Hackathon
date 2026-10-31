"""Trusted receipts for ideal constant-speed vertical lifting work."""

from decimal import Decimal, ROUND_CEILING, localcontext
from fractions import Fraction
import math
import warnings

import pint


class MethodCheckError(ValueError):
    pass


UNITS = pint.UnitRegistry(non_int_type=Fraction)
BASE_UNITS = {'mass': 'kg', 'gravity': 'm/s**2', 'height_change': 'm'}


def number(value):
    text = str(value)
    if len(text) > 256:
        raise MethodCheckError('NUMBER_TOO_LARGE')
    decimal = Decimal(text)
    if not decimal.is_finite() or abs(decimal.adjusted()) > 100 or abs(decimal.as_tuple().exponent) > 100:
        raise MethodCheckError('UNSUPPORTED_NUMBER')
    return Fraction(decimal)


def normalize(parameters):
    values = {}
    for name, unit in BASE_UNITS.items():
        raw = number(parameters[name])
        source = UNITS.Unit(parameters[name + '_unit'])
        zero = UNITS.Quantity(Fraction(0), source).to(unit).magnitude
        factor = UNITS.Quantity(Fraction(1), source).to(unit).magnitude
        if zero != 0 or not isinstance(factor, (int, Fraction)):
            raise MethodCheckError('UNSUPPORTED_UNIT_CONVERSION')
        values[name] = raw * factor
        if not math.isfinite(float(values[name])) or abs(values[name]) > 10**100:
            raise MethodCheckError('UNSUPPORTED_NUMBER')
    if values['mass'] < 0 or values['gravity'] <= 0:
        raise MethodCheckError('INVALID_PHYSICAL_INPUT')
    return values


def decimal_result(value):
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
        self.inputs = normalize(parameters)
        original_registry = pint.UnitRegistry

        def exact_registry():
            return original_registry(non_int_type=Fraction)

        # Trusted worker configuration; generated code still gets no registry
        # constructor arguments and cannot select unit-definition files.
        pint.UnitRegistry = exact_registry
        self.calls, self.evaluations = 0, 0
        self.value = self.error = None
        self.validated = False
        if self.method == 'energy_balance':
            import sympy as sp
            original = sp.expand
            mass, gravity, height = sp.symbols('mass gravity height_change')
            expected = mass * gravity * height

            def expand(expression, *args, **kwargs):
                self.calls += 1
                if self.calls != 1 or args or kwargs or not isinstance(expression, sp.Expr):
                    raise MethodCheckError('UNSUPPORTED_ENERGY_CALL')
                if {symbol.name for symbol in expression.free_symbols} != {'mass', 'gravity', 'height_change'}:
                    raise MethodCheckError('ENERGY_EXPRESSION_MISMATCH')
                canonical = expression.xreplace({symbol: sp.Symbol(symbol.name) for symbol in expression.free_symbols})
                if sp.Poly(canonical, mass, gravity, height).as_dict() != sp.Poly(expected, mass, gravity, height).as_dict():
                    raise MethodCheckError('ENERGY_EXPRESSION_MISMATCH')
                evaluated = original(expression)
                substitutions = {symbol: sp.Rational(self.inputs[symbol.name].numerator, self.inputs[symbol.name].denominator)
                                 for symbol in evaluated.free_symbols}
                answer = evaluated.subs(substitutions)
                if answer.is_Rational is not True:
                    raise MethodCheckError('EXACT_RESULT_NOT_RATIONAL')
                self.value = Fraction(int(answer.p), int(answer.q))
                self.error = Fraction(0)
                self.wire_value, self.wire_error = decimal_result(self.value)
                return evaluated

            sp.expand = expand
        elif self.method == 'force_balance':
            import scipy.integrate as integration
            original = integration.quad
            weight = float(self.inputs['mass']) * float(self.inputs['gravity'])
            height = float(self.inputs['height_change'])

            def quad(function, a, b, *args, **kwargs):
                self.calls += 1
                if self.calls != 1 or args or set(kwargs) - {'epsabs', 'epsrel', 'limit'}:
                    raise MethodCheckError('UNSUPPORTED_QUADRATURE_CALL')
                if a != 0 or b != height:
                    raise MethodCheckError('INTEGRATION_BOUNDS_MISMATCH')

                def checked(position):
                    value = function(position)
                    if isinstance(value, bool) or not math.isfinite(value) or value != weight:
                        raise MethodCheckError('INTEGRAND_FORCE_MISMATCH')
                    self.evaluations += 1
                    return value

                with warnings.catch_warnings(record=True) as captured:
                    warnings.simplefilter('always')
                    value, error = original(checked, a, b, **kwargs)
                if captured or not math.isfinite(value) or not math.isfinite(error) or error < 0:
                    raise MethodCheckError('QUADRATURE_WARNING_OR_NONFINITE')
                self.value, self.error = number(value), number(error)
                self.wire_value, self.wire_error = str(value), str(error)
                exact_work = self.inputs['mass'] * self.inputs['gravity'] * self.inputs['height_change']
                represented_work = Fraction.from_float(weight) * Fraction.from_float(height)
                self.input_error = abs(exact_work - represented_work)
                return value, error

            integration.quad = quad
        else:
            raise MethodCheckError('UNSUPPORTED_METHOD')

    def allow_import(self, name):
        return name in ({'pint', 'sympy'} if self.method == 'energy_balance' else {'pint', 'sympy', 'scipy.integrate'})

    def finalize(self, quantity, error):
        if self.calls != 1 or self.value is None:
            raise MethodCheckError('REQUIRED_SOLVER_NOT_EXECUTED')
        self.reported_unit = str(quantity.units)
        compatible = quantity.check('[mass] * [length] ** 2 / [time] ** 2')
        if compatible:
            factor = UNITS.Quantity(Fraction(1), self.reported_unit).to('joule').magnitude
            if not isinstance(factor, (int, Fraction)):
                raise MethodCheckError('UNSUPPORTED_UNIT_CONVERSION')
        else:
            factor = Fraction(1)
        actual = Fraction(str(quantity.magnitude)) * factor
        actual_error = Fraction(str(error.magnitude)) * factor if error is not None else None
        if actual != self.value:
            raise MethodCheckError('OUTPUT_NOT_SOLVER_RESULT')
        if actual_error != self.error:
            raise MethodCheckError('ERROR_NOT_SOLVER_ESTIMATE')
        self.validated = True
        unit = 'joule' if compatible else self.reported_unit
        wire_error = self.wire_error
        if self.method == 'force_balance':
            # Keep solver and proven input-representation errors separate in audit.
            with localcontext() as context:
                context.prec = 100
                context.rounding = ROUND_CEILING
                total = self.error + self.input_error
                wire_error = str(Decimal(total.numerator) / Decimal(total.denominator))
        return {'value': self.wire_value, 'unit': unit, 'absolute_error': wire_error}

    def snapshot(self):
        return {
            'method': self.method, 'solver_calls': self.calls,
            'checked_function_evaluations': self.evaluations,
            'output_matches_solver': self.validated,
            'reported_unit': getattr(self, 'reported_unit', None),
            'registry_numerical_type': 'fractions.Fraction',
            'solver_absolute_error': str(self.error) if self.error is not None else None,
            'input_representation_error_bound': str(getattr(self, 'input_error', Fraction(0))),
            'error_source': ('exact_rational_with_decimal_conversion_bound' if self.method == 'energy_balance'
                             else 'scipy_quad_estimate_plus_input_representation_bound'),
        }


def create(parameters):
    return Controller(parameters)
