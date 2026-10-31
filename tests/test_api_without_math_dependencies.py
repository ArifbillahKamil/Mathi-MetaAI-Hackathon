"""API connectivity checks must work without installed math packages."""

from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class APIWithoutMathDependenciesTests(unittest.TestCase):
    def run_without_site_packages(self, program):
        # -S excludes site-packages: no Pint, NumPy, SymPy, SciPy, or SDK.
        return subprocess.run(
            [sys.executable, '-S', '-c', program], cwd=ROOT,
            capture_output=True, text=True, timeout=10,
        )

    def test_api_check_imports_without_any_math_packages(self):
        completed = self.run_without_site_packages(
            "import sys; import app.llm.check; "
            "assert not any(name in sys.modules for name in ('pint', 'numpy', 'sympy', 'scipy')); "
            "print('IMPORT_OK')"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), 'IMPORT_OK')

    def test_connectivity_command_runs_with_mocked_transport_without_site_packages(self):
        program = '''
from unittest.mock import patch
from app.llm.check import main
from app.llm.meta import Completion, MetaClient, MetaSettings
completion = Completion('ready', 'muse-spark-1.3', {'total_tokens': 1}, 'fixture-hash', None)
with patch.object(MetaSettings, 'from_dotenv', return_value=MetaSettings('fixture-token')):
    with patch.object(MetaClient, 'complete', return_value=completion):
        raise SystemExit(main())
'''
        completed = self.run_without_site_packages(program)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('"status": "CONNECTED"', completed.stdout)
        self.assertNotIn('fixture-token', completed.stdout)


if __name__ == '__main__':
    unittest.main()
