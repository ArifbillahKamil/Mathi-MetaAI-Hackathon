"""Curated code samples for offline route-generation and method-receipt tests."""

PRELUDE = "from pint import UnitRegistry\nu = UnitRegistry()\n"
NUMERIC = PRELUDE + (
    "from scipy.integrate import quad\nvalue, error = quad(lambda x: x**2, 0, 3)\n"
    "result = {'quantity': u.Quantity(value, 'dimensionless'), 'absolute_error': u.Quantity(error, 'dimensionless')}\n"
)
SYMBOLIC = PRELUDE + (
    "import sympy as sp\nx = sp.Symbol('x')\nvalue = sp.integrate(x**2, (x, 0, 3))\n"
    "result = {'quantity': u.Quantity(value, 'dimensionless'), 'absolute_error': u.Quantity(0, 'dimensionless')}\n"
)
