"""Execute a saved preparation using two blind Meta generations, locally."""

import argparse
import json
from pathlib import Path

from app.llm.meta import MetaClient, MetaSettings


def main(argv=None):
    parser = argparse.ArgumentParser(description='Generate and execute independent routes from a ready preparation report.')
    parser.add_argument('preparation', type=Path)
    parser.add_argument('--output', type=Path, help='Optional JSON audit output, preferably in artifacts/.')
    parser.add_argument('--timeout', type=float, default=15.0, help='Seconds per local route process.')
    parser.add_argument('--max-corrections', type=int, choices=(0, 1, 2), default=2, help='Maximum blind correction attempts; zero disables them.')
    parser.add_argument('--correction-time-budget', type=float, default=90.0, help='Seconds available for the correction phase.')
    args = parser.parse_args(argv)
    try:
        from app.core.execution import execute_preparation
        from app.core.structured import parse_json
    except ModuleNotFoundError as exc:
        if exc.name not in {'pydantic', 'pint', 'numpy', 'sympy', 'scipy'}:
            raise
        print(json.dumps({'status': 'SETUP_REQUIRED', 'message': 'Run python -m pip install -r requirements.txt'}))
        return 1
    try:
        if args.preparation.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('Preparation report is too large.')
        saved = parse_json(args.preparation.read_text(encoding='utf-8-sig'), max_characters=2*1024*1024)
        report = execute_preparation(
            MetaClient(MetaSettings.from_dotenv()), saved, timeout=args.timeout,
            max_corrections=args.max_corrections, correction_time_budget=args.correction_time_budget,
        )
        encoded = json.dumps(report, indent=2, allow_nan=False)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding='utf-8')
        print(encoded)
        return 0 if report['status'] in ('VERIFIED', 'VERIFIED_WITH_DEVIATION') else 2
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'INVALID_CONFIGURATION_OR_INPUT', 'error': str(exc)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
