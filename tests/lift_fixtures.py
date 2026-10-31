"""Ideal-lift model fixtures, never live API evidence."""

import json
from tests.preparation_fixtures import client_for, plan_payload, problem_payload
from app.core.preparation import prepare
from tests.test_route_execution import CodeClient

TEXT = ('Find the work by the lifting force for an ideal vertical lift at constant speed with no losses. '
        'Mass=5000 g, height change=200 cm, constant gravity=981 cm/s**2. Return joules.')


def problem(**changes):
    payload = dict(problem_class='engineering', task='work_energy',
                           interpretation='Find the work by the ideal constant-speed vertical lifting force.',
                           expression='vertical_lift_constant_speed', variables=[], unknowns=['work'],
                           expected_unit='joule', givens=[
                               {'name': 'mass', 'value': '5000', 'unit': 'g'},
                               {'name': 'gravity', 'value': '981', 'unit': 'cm/s**2'},
                               {'name': 'height_change', 'value': '200', 'unit': 'cm'},
                           ])
    payload.update(changes)
    return problem_payload(**payload)


def plan(**changes):
    return plan_payload(problem_class='engineering', expected_unit=changes.pop('expected_unit', 'joule'),
                        method_a=changes.pop('method_a', 'energy_balance'), method_b=changes.pop('method_b', 'force_balance'),
                        independence_rationale='Potential-energy change versus numerical work integral of lifting force.',
                        sanity_checks=changes.pop('sanity_checks', []), **changes)


def ready(**changes):
    payload = problem(**changes)
    return prepare(client_for(payload, payload, plan(expected_unit=payload['expected_unit'])), TEXT)


INPUTS = """import pint
import sympy as sp
u = pint.UnitRegistry()
mass_quantity = u.Quantity(sp.Rational('5000'), 'g').to('kg')
gravity_quantity = u.Quantity(sp.Rational('981'), 'cm/s**2').to('m/s**2')
height_quantity = u.Quantity(sp.Rational('200'), 'cm').to('m')
"""
ENERGY = INPUTS + """mass, gravity, height_change = sp.symbols('mass gravity height_change')
delta_potential = sp.expand(mass * gravity * height_change)
value = delta_potential.subs({mass: mass_quantity.magnitude, gravity: gravity_quantity.magnitude, height_change: height_quantity.magnitude})
result = {'quantity': u.Quantity(value, 'joule'), 'absolute_error': u.Quantity(sp.Integer(0), 'joule')}
"""
FORCE = INPUTS + """from scipy.integrate import quad
weight = float(mass_quantity.magnitude) * float(gravity_quantity.magnitude)
value, error = quad(lambda position: weight, 0, float(height_quantity.magnitude))
result = {'quantity': u.Quantity(value, 'joule'), 'absolute_error': u.Quantity(error, 'joule')}
"""


class LiftClient(CodeClient):
    def __init__(self, energy=None, force=None):
        super().__init__()
        self.codes = {'energy_balance': list(energy or [ENERGY]), 'force_balance': list(force or [FORCE])}
        self.planner = plan()
