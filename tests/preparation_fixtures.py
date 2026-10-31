"""Schema-valid fixture payloads; not live model results."""

from unittest.mock import Mock
import json

from app.core.intake import ConfirmationOrigin, ConfirmedProblem
from app.core.problem import Problem
from app.core.structured import parse_record
from app.llm.meta import Completion

TEXT = 'Evaluate the integral of x squared from 0 to 3.'


def problem_payload(**changes):
    result = {
        'interpretation': 'Integrate x**2 from 0 to 3.', 'problem_class': 'calculus',
        'task': 'definite_integral', 'expression': 'x**2', 'variables': ['x'],
        'givens': [
            {'name': 'lower_bound', 'value': '0', 'unit': 'dimensionless'},
            {'name': 'upper_bound', 'value': '3', 'unit': 'dimensionless'},
        ],
        'unknowns': ['integral'], 'expected_unit': 'dimensionless', 'answer_shape': 'scalar',
        'domain': 'real', 'assumptions': [], 'uncertainties': [],
    }
    result.update(changes)
    return result


def confirmed(**changes):
    problem = parse_record(json.dumps(problem_payload(**changes)), Problem)
    return ConfirmedProblem(problem, 'fixture-input-hash', ConfirmationOrigin.DUAL_PARSE_AGREEMENT)


def plan_payload(**changes):
    result = {
        'supported': True, 'problem_class': 'calculus', 'expected_unit': 'dimensionless',
        'method_a': 'symbolic_integration', 'method_b': 'numerical_quadrature',
        'independence_rationale': 'Symbolic antiderivative versus adaptive quadrature.',
        'sanity_checks': [{'name': 'nonnegative_integral', 'lower': '0', 'upper': None, 'unit': 'dimensionless'}],
        'unsupported_reason': None,
    }
    result.update(changes)
    return result


def client_for(*outputs):
    client = Mock()
    client.complete.side_effect = [
        item if isinstance(item, Exception) else Completion(
            item if isinstance(item, str) else json.dumps(item), 'fixture-model',
            {'total_tokens': 10}, 'fixture-request-hash', 'fixture-response-id',
        ) for item in outputs
    ]
    return client
