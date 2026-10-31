"""Root solving fixtures; no model service is invoked."""

from tests.preparation_fixtures import client_for, plan_payload, problem_payload
from tests.test_route_execution import CodeClient
from app.core.preparation import prepare


def ready(expression='x**2 - 3*x + 2', **changes):
    data = problem_payload(interpretation=f'Find all distinct real roots of {expression} = 0.',
                           problem_class='algebra', task='roots', expression=expression,
                           variables=['x'], givens=[], unknowns=['roots'], answer_shape='set')
    data.update(changes)
    planned = plan_payload(problem_class='algebra', method_a='symbolic_elimination', method_b='numerical_root_finding',
                           expected_unit=data['expected_unit'], sanity_checks=[],
                           independence_rationale='Exact symbolic polynomial solving versus numerical bracketing.')
    return prepare(client_for(data, data, planned), f'Find all real roots of {expression}=0.')


def symbolic(expression='x**2 - 3*x + 2'):
    return f"""import sympy as sp
import pint
u = pint.UnitRegistry()
x = sp.Symbol('x', real=True)
expression = {expression}
roots = sp.solve(expression, x)
result = {{'quantities': [u.Quantity(root, 'dimensionless') for root in roots]}}
"""


def numeric(expression='x**2 - 3*x + 2', brackets=((0, 1.5), (1.5, 3))):
    return f"""from scipy.optimize import brentq
import pint
u = pint.UnitRegistry()
def function(x):
    return {expression}
brackets = {brackets!r}
roots = [brentq(function, a, b, xtol=1e-12, rtol=1e-14) for a, b in brackets]
result = {{'quantities': [u.Quantity(root, 'dimensionless') for root in roots]}}
"""


class RootsClient(CodeClient):
    def __init__(self, symbolic_codes=None, numeric_codes=None):
        super().__init__()
        self.codes = {'symbolic_elimination': list(symbolic_codes or [symbolic()]),
                      'numerical_root_finding': list(numeric_codes or [numeric()])}
