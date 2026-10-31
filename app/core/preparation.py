"""Compose intake and planning without executing code or assigning verdicts."""

from copy import deepcopy
import json

from app.core.intake import IntakeResult, IntakeStatus, intake, select_interpretation
from app.core.planner import PlanningStatus, plan_problem
from app.core.problem import Problem
from app.llm.meta import MetaClient


def prepare(client: MetaClient, text: str) -> dict:
    interpreted = intake(client, text)
    planned = None
    status = interpreted.status.value
    if interpreted.confirmed is not None:
        planned = plan_problem(client, interpreted.confirmed)
        status = "READY_FOR_ROUTES" if planned.status == PlanningStatus.PLANNED else planned.status.value
    return {
        "stage": "PREPARATION_ONLY", "status": status,
        "intake": interpreted.to_dict(), "planning": planned.to_dict() if planned else None,
        "route_executions": 0,
    }


def confirm_preparation(
    client: MetaClient, saved: dict, choice: int, *, expected_unit: str | None = None,
) -> dict:
    """Resume only after an explicit user selection; never rerun saved prompts.

    A local report is user-editable input, not authenticated model evidence.
    Its selected candidate is revalidated, while supplied status/confirmation
    claims are never used to bypass the current confirmation checks.
    """
    if not isinstance(saved, dict) or (
        saved.get("stage") != "PREPARATION_ONLY"
        or saved.get("status") != "NEEDS_CONFIRMATION"
        or type(saved.get("route_executions")) is not int
        or saved["route_executions"] != 0
        or saved.get("planning") is not None
    ):
        raise ValueError("Select an unexecuted preparation report awaiting confirmation.")
    source = saved.get("intake")
    if not isinstance(source, dict) or source.get("status") != "NEEDS_CONFIRMATION" or source.get("confirmed") is not None:
        raise ValueError("Saved intake must await an explicit user confirmation.")
    raw_input, raw_candidates = source.get("raw_input"), source.get("candidates")
    if not isinstance(raw_input, str) or not raw_input.strip() or len(raw_input) > 16384:
        raise ValueError("Saved input is invalid.")
    if not isinstance(raw_candidates, list) or len(raw_candidates) != 2:
        raise ValueError("Saved intake must contain exactly two candidate slots.")
    candidates = tuple(
        Problem.model_validate_json(json.dumps(item, allow_nan=False), strict=True) if item is not None else None
        for item in raw_candidates
    )
    pending = IntakeResult(raw_input, IntakeStatus.NEEDS_CONFIRMATION, "SAVED_INTAKE", candidates, (), (), None)
    confirmed = select_interpretation(pending, choice, expected_unit=expected_unit)
    planned = plan_problem(client, confirmed)
    # Preserve both original candidates and raw responses. The separate
    # confirmation record states which fields came directly from the user.
    result = deepcopy(saved)
    result["intake"]["status"] = "USER_CONFIRMED"
    result["intake"]["reason"] = "USER_SELECTED_INTERPRETATION"
    result["intake"]["confirmation_reasons"] = []
    result["intake"]["confirmed"] = confirmed.to_dict()
    result["intake"]["confirmation"] = {
        "source": "explicit_user_selection", "choice": choice,
        "expected_unit": confirmed.user_expected_unit,
        "prior_status": source["status"], "prior_reason": source.get("reason"),
        "prior_confirmation_reasons": source.get("confirmation_reasons", list(pending.confirmation_reasons)),
    }
    result["planning"] = planned.to_dict()
    result["status"] = "READY_FOR_ROUTES" if planned.status == PlanningStatus.PLANNED else planned.status.value
    return result
