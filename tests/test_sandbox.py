"""Execution tests for the local development backend and its pre-check."""

import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from app.sandbox import ExecutionLimits, ExecutionStatus, run_code
from app.sandbox.guard import check_code
from app.sandbox.local import _child_environment


QUANTITY = "from pint import UnitRegistry\nu = UnitRegistry()\n"
VALID = QUANTITY + "result = {'quantity': u.Quantity(10, 'newton'), 'absolute_error': u.Quantity(0, 'newton')}\n"


class CodePolicyTests(unittest.TestCase):
    def test_ordinary_mathematical_code_is_allowed(self):
        for code in (
            VALID,
            "from scipy.integrate import quad\nvalue, error = quad(lambda x: x*x, 0, 1)",
            "import numpy as np\nanswer = np.linalg.solve(np.array([[2]]), np.array([4]))",
            "import sympy as sp\nx = sp.Symbol('x')\ny = sp.integrate(x**2, (x, 0, 1))",
        ):
            with self.subTest(code=code):
                self.assertTrue(check_code(code).allowed)

    def test_dangerous_imports_and_members_are_rejected(self):
        for code in (
            "import os", "import subprocess", "import sys", "import socket",
            "from pathlib import Path", "from numpy import load", "from scipy import io",
            "from sympy import sympify", "from sympy import lambdify", "from math import *",
            "from .math import sqrt",
        ):
            with self.subTest(code=code):
                self.assertFalse(check_code(code).allowed)

    def test_file_execution_and_introspection_access_is_rejected(self):
        for code in (
            "open('.env')", "eval('1')", "exec('1')", "__import__('os')",
            "globals()", "getattr(1, 'real')", "(1).__class__", "print.__self__",
            "import numpy as np\nnp.load('secret.npy')",
            "import numpy as np\nnp.array([1]).tofile('output')",
            "import numpy as np\nnp.ctypeslib.load_library('x', '.')",
            "import numpy as np\nnp.linalg.test()",
            "import sympy as sp\nsp.sympify('1')",
            "from pint import UnitRegistry\nu = UnitRegistry('private_definitions.txt')",
            "from pint import UnitRegistry as Registry\nu = Registry('private_definitions.txt')",
        ):
            with self.subTest(code=code):
                self.assertFalse(check_code(code).allowed)

    def test_dynamic_call_and_syntax_escape_hatches_are_rejected(self):
        for code in (
            "functions[0]()", "(lambda: 1)()", "class Escape: pass",
            "with thing: pass", "try:\n    pass\nexcept Exception:\n    pass",
            "global answer", "def solve(__builtins__): pass", "@print\ndef solve(): pass",
        ):
            with self.subTest(code=code):
                self.assertFalse(check_code(code).allowed)

    def test_invalid_or_oversized_source_is_rejected(self):
        for code in (None, "", " ", "def (", "return 1"):
            with self.subTest(code=code):
                self.assertFalse(check_code(code).allowed)
        self.assertEqual(check_code("x = 1", max_source_bytes=3).reason, "SOURCE_TOO_LARGE")


class LocalExecutionTests(unittest.TestCase):
    def test_real_process_returns_unit_aware_scalar_and_audit(self):
        executed = run_code("print('running')\n" + VALID)
        self.assertEqual(executed.status, ExecutionStatus.SUCCESS, executed.to_dict())
        self.assertEqual(executed.stdout, "running\n")
        self.assertEqual(executed.result, {"value": "10", "unit": "newton", "absolute_error": "0"})
        self.assertEqual(executed.as_scalar_route().value, "10")
        self.assertEqual(executed.code, "print('running')\n" + VALID)
        json.dumps(executed.to_dict(), allow_nan=False)

    def test_symbolic_library_runs_in_child(self):
        code = QUANTITY + (
            "import sympy as sp\nx = sp.Symbol('x')\n"
            "value = sp.integrate(x**2, (x, 0, 3))\n"
            "result = {'quantity': u.Quantity(int(value), 'dimensionless'), "
            "'absolute_error': u.Quantity(0, 'dimensionless')}"
        )
        executed = run_code(code)
        self.assertEqual(executed.status, ExecutionStatus.SUCCESS, executed.to_dict())
        self.assertEqual(executed.result['value'], "9")

    def test_numeric_solver_returns_its_executed_error_estimate(self):
        code = QUANTITY + (
            "from scipy.integrate import quad\nvalue, error = quad(lambda x: x*x, 0, 3)\n"
            "result = {'quantity': u.Quantity(value, 'dimensionless'), "
            "'absolute_error': u.Quantity(error, 'dimensionless')}"
        )
        executed = run_code(code)
        self.assertEqual(executed.status, ExecutionStatus.SUCCESS, executed.to_dict())
        self.assertAlmostEqual(float(executed.result['value']), 9)
        self.assertGreater(float(executed.result['absolute_error']), 0)

    def test_rejected_code_never_starts_process(self):
        with patch('app.sandbox.local.subprocess.Popen') as launch:
            executed = run_code("import os\nprint(os.environ)")
        self.assertEqual(executed.status, ExecutionStatus.REJECTED)
        launch.assert_not_called()

    def test_secrets_are_not_inherited_and_temporary_folder_is_cleaned(self):
        with patch.dict(os.environ, {"META_API_KEY": "test-secret", "UNEXPECTED_SECRET": "another-secret"}):
            with patch('app.sandbox.local.subprocess.Popen', wraps=subprocess.Popen) as launch:
                executed = run_code(VALID)
        self.assertEqual(executed.status, ExecutionStatus.SUCCESS, executed.to_dict())
        parameters = launch.call_args.kwargs
        self.assertNotIn("META_API_KEY", parameters['env'])
        self.assertNotIn("UNEXPECTED_SECRET", parameters['env'])
        self.assertNotEqual(Path(parameters['cwd']), Path.cwd())
        self.assertFalse(Path(parameters['cwd']).exists())
        self.assertIn('-I', launch.call_args.args[0])

    def test_environment_is_built_from_an_allowlist(self):
        self.assertLessEqual(set(_child_environment()), {
            'SystemRoot', 'WINDIR', 'TEMP', 'TMP',
            'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
        })

    def test_timeout_kills_process_and_cleans_folder(self):
        with patch('app.sandbox.local.subprocess.Popen', wraps=subprocess.Popen) as launch:
            executed = run_code("while True:\n    pass", timeout=1)
        self.assertEqual(executed.status, ExecutionStatus.TIMEOUT)
        self.assertFalse(Path(launch.call_args.kwargs['cwd']).exists())
        self.assertIsNotNone(executed.as_scalar_route().execution_error)

    def test_runtime_error_is_distinct_from_rejection(self):
        executed = run_code("answer = 1 / 0")
        self.assertEqual(executed.status, ExecutionStatus.RUNTIME_ERROR)
        self.assertIn("ZeroDivisionError", executed.error)

    def test_output_limit_is_enforced(self):
        executed = run_code("while True:\n    print('x' * 1000)", limits=ExecutionLimits(max_output_bytes=1024))
        self.assertEqual(executed.status, ExecutionStatus.OUTPUT_LIMIT, executed.to_dict())
        self.assertIsNone(executed.result)

    def test_missing_or_unitless_result_does_not_succeed(self):
        for code in ("print(1)", "result = {'quantity': 1, 'absolute_error': 0}"):
            with self.subTest(code=code):
                executed = run_code(code)
                self.assertEqual(executed.status, ExecutionStatus.RUNTIME_ERROR)

    def test_missing_error_estimate_is_preserved_as_missing(self):
        code = QUANTITY + "result = {'quantity': u.Quantity(1, 'm'), 'absolute_error': None}"
        executed = run_code(code)
        self.assertEqual(executed.status, ExecutionStatus.SUCCESS, executed.to_dict())
        self.assertIsNone(executed.as_scalar_route().absolute_error)

    def test_state_does_not_pass_to_next_execution(self):
        first = run_code("private_value = 42\n" + VALID)
        second = run_code("print(private_value)\n" + VALID)
        self.assertEqual(first.status, ExecutionStatus.SUCCESS, first.to_dict())
        self.assertEqual(second.status, ExecutionStatus.RUNTIME_ERROR)
        self.assertIn("NameError", second.error)

    def test_invalid_limits_and_timeouts_raise(self):
        for timeout in (0, -1, float('inf'), float('nan'), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                run_code(VALID, timeout=timeout)
        for limit in (0, -1, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                ExecutionLimits(max_output_bytes=limit)


if __name__ == '__main__':
    unittest.main()
