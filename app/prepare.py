"""Live intake/planning command; does not execute generated route code."""

import argparse
import json
from pathlib import Path

from app.llm.meta import MetaClient, MetaSettings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Parse a problem twice and plan independent methods; no solving yet.")
    parser.add_argument("problem", nargs="?", help="Plain text, mathematical notation, or quantities with units.")
    parser.add_argument("--confirm-report", type=Path, help="Resume a saved report after reviewing its interpretations.")
    parser.add_argument("--choice", type=int, choices=(1, 2), help="Explicitly select saved interpretation 1 or 2.")
    parser.add_argument("--expected-unit", help="Explicitly supply a missing expected unit for the selected interpretation.")
    parser.add_argument("--output", type=Path, help="Optional JSON audit path; use artifacts/ for local reports.")
    args = parser.parse_args(argv)
    if (args.problem is None) == (args.confirm_report is None):
        parser.error("Provide either problem text or --confirm-report.")
    if args.confirm_report is not None and args.choice is None:
        parser.error("Review the report and specify --choice 1 or --choice 2.")
    if args.confirm_report is None and (args.choice is not None or args.expected_unit is not None):
        parser.error("--choice and --expected-unit require --confirm-report.")
    try:
        from app.core.preparation import confirm_preparation, prepare
        from app.core.structured import parse_json
    except ModuleNotFoundError as exc:
        if exc.name != "pydantic":
            raise
        print(json.dumps({"status": "SETUP_REQUIRED", "message": "Run python -m pip install -r requirements.txt"}))
        return 1
    try:
        client = MetaClient(MetaSettings.from_dotenv())
        if args.confirm_report is not None:
            if args.confirm_report.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("Saved preparation report is too large.")
            saved = parse_json(args.confirm_report.read_text(encoding="utf-8-sig"), max_characters=2 * 1024 * 1024)
            record = confirm_preparation(client, saved, args.choice, expected_unit=args.expected_unit)
        else:
            record = prepare(client, args.problem)
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "INVALID_CONFIGURATION_OR_INPUT", "error": str(exc)}))
        return 1
    encoded = json.dumps(record, indent=2, allow_nan=False)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded)
    if record["status"] == "READY_FOR_ROUTES":
        return 0
    return 2 if record["status"] == "NEEDS_CONFIRMATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
