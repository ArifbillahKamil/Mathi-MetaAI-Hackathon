"""Blind route generation, audited execution, and deterministic comparison."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
import math
import time

from app.core.comparator import ComparisonContext, ComparisonResult, Reason, Verdict, compare_scalars
from app.core.config import ScalarTolerance
from app.core.independence import build_blind_requests, check_independence
from app.core.intake import ConfirmationOrigin, ConfirmedProblem, IntakeResult, IntakeStatus, _signature, select_interpretation
from app.core.planner import PlanSpec, PlanningStatus, plan_problem, validate_plan
from app.core.problem import Problem, StrictRecord
from app.core.structured import request_record
from app.core.repairs import RepairReason
from app.core.report import select_answer_route
from app.core.self_correction import classify_failure, diagnose
from app.modules import select_module
from app.sandbox import run_code


class GeneratedRoute(StrictRecord):
    code: str


def _compare(module, problem, planned, executed, guard, *, corrected=False):
    checks = module.sanity_checks(planned, executed)
    try:
        tolerance = module.tolerance(executed)
    except (ValueError, ArithmeticError):
        tolerance = ScalarTolerance(0, 0, 0, 0)
    context = ComparisonContext(problem.expected_unit, guard.as_check_evidence(), checks,
                                corrected_after_conflict=corrected)
    if problem.answer_shape.value == 'set':
        from app.core.set_comparator import SetRoute, compare_sets
        def as_set(execution):
            if execution.error is not None or execution.result is None:
                return SetRoute(execution_error=f'{execution.status.value}: {execution.error}')
            raw = execution.result
            return SetRoute(tuple(raw['values']), raw['unit'], tuple(raw['absolute_errors']))
        return compare_sets(as_set(executed['A']), as_set(executed['B']), tolerance=tolerance, context=context)
    return compare_scalars(
        executed['A'].as_scalar_route(), executed['B'].as_scalar_route(), tolerance=tolerance,
        context=context,
    )


def _correct(
    client, report, confirmed, planned, module, route_plan, requests, codes,
    specifications, executed, guard, compared, *, timeout, max_corrections, time_budget,
):
    solved = (Verdict.VERIFIED, Verdict.VERIFIED_WITH_DEVIATION)
    if compared.verdict in solved:
        report['self_correction'] = 'NOT_NEEDED'
        return executed, guard, compared
    if not max_corrections:
        report['self_correction'] = 'DISABLED'
        return executed, guard, compared
    started = time.perf_counter()
    deadline = started + time_budget
    report['self_correction'] = 'EXHAUSTED'
    for number in range(1, max_corrections + 1):
        decision = classify_failure(compared, executed)
        if decision.action == 'STOP':
            report['self_correction'] = 'STOPPED_UNVERIFIABLE_CHECK'
            break
        entry = {
            'attempt': number, 'classification': decision.to_dict(),
            'before_comparison': compared.to_dict(),
            'before_routes': {label: value.to_dict() for label, value in executed.items()},
            'arbiter': None, 'generation': None, 'independence': None,
            'repaired_route': None, 'repair_execution': None, 'after_comparison': None,
        }
        report['correction_history'].append(entry)

        def stop(outcome):
            entry['outcome'] = outcome
            entry['elapsed_seconds'] = time.perf_counter() - started
            report['self_correction'] = outcome

        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            stop('TIME_BUDGET_EXCEEDED')
            break
        label, repair = decision.route, decision.repair
        if decision.action == 'DIAGNOSE':
            diagnosis, attempt = diagnose(
                client, confirmed, planned, executed, compared, attempt=number, timeout_seconds=remaining,
            )
            entry['arbiter'] = attempt.to_dict()
            if diagnosis is None:
                stop('DIAGNOSIS_FAILED')
                break
            if diagnosis.suspected_route not in ('A', 'B') or diagnosis.bug == RepairReason.UNKNOWN:
                # Never relax an LLM-specified sanity bound to manufacture a pass.
                stop('STOPPED_UNCERTAIN_DIAGNOSIS')
                break
            label, repair = diagnosis.suspected_route, diagnosis.bug
        entry['repaired_route'] = label
        entry['repair_reason_code'] = repair.value
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            stop('TIME_BUDGET_EXCEEDED')
            break
        repair_plan = replace(route_plan, **{f'repair_{label.lower()}': repair})
        fresh_pair = build_blind_requests(confirmed.problem.model_dump_json(), repair_plan)
        index = 0 if label == 'A' else 1
        # Only the Problem, own method, and fixed enum-guidance reach this call.
        # Arbiter explanation, peer code/results, and prior history stay in audit.
        generated, attempt = request_record(
            client, fresh_pair[index], GeneratedRoute, stage=f'route_{label}_blind_fix_{number}',
            timeout_seconds=remaining,
        )
        entry['generation'] = attempt.to_dict()
        if generated is None:
            stop('REPAIR_GENERATION_FAILED')
            break
        fresh_codes = list(codes)
        fresh_codes[index] = generated.code
        new_guard = check_independence(
            problem=confirmed.problem.model_dump_json(), plan=repair_plan,
            request_a=fresh_pair[0], request_b=fresh_pair[1],
            code_a=fresh_codes[0], code_b=fresh_codes[1],
        )
        entry['independence'] = new_guard.to_dict()
        if not new_guard.accepted:
            entry['requires_fresh_replan'] = True
            stop('REPAIR_GUARD_REJECTED')
            break
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            stop('TIME_BUDGET_EXCEEDED')
            break
        repaired = run_code(generated.code, min(timeout, remaining), verification=specifications[index])
        executed = dict(executed)
        executed[label] = repaired
        report['route_executions'] += 1
        entry['repair_execution'] = repaired.to_dict()
        requests, codes, route_plan, guard = fresh_pair, fresh_codes, repair_plan, new_guard
        compared = _compare(module, confirmed.problem, planned, executed, guard, corrected=True)
        entry['after_comparison'] = compared.to_dict()
        entry['outcome'] = compared.verdict.value
        entry['elapsed_seconds'] = time.perf_counter() - started
        if compared.verdict in solved:
            report['self_correction'] = 'CORRECTED'
            break
    report['correction_elapsed_seconds'] = time.perf_counter() - started
    return executed, guard, compared


def restore_preparation(saved):
    if not isinstance(saved, dict) or (
        saved.get('stage') != 'PREPARATION_ONLY' or saved.get('status') != 'READY_FOR_ROUTES'
        or type(saved.get('route_executions')) is not int or saved['route_executions'] != 0
    ):
        raise ValueError('A ready, unexecuted preparation report is required.')
    source, planning = saved.get('intake'), saved.get('planning')
    if not isinstance(source, dict) or not isinstance(planning, dict) or planning.get('status') != 'PLANNED':
        raise ValueError('Confirmed intake and a validated plan are required.')
    raw, chosen = source.get('raw_input'), source.get('confirmed')
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 16384 or not isinstance(chosen, dict):
        raise ValueError('Invalid saved intake.')
    problem = Problem.model_validate_json(json.dumps(chosen.get('problem'), allow_nan=False), strict=True)
    confirmed = ConfirmedProblem(problem, chosen.get('input_hash'), ConfirmationOrigin(chosen.get('origin')),
                                 user_expected_unit=chosen.get('user_expected_unit'))
    if confirmed.input_hash != sha256(raw.encode('utf-8')).hexdigest():
        raise ValueError('Saved input hash does not match its input text.')
    candidates = source.get('candidates')
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise ValueError('Both original candidate slots must be retained.')
    candidates = tuple(Problem.model_validate_json(json.dumps(item), strict=True) if item is not None else None for item in candidates)
    if confirmed.origin == ConfirmationOrigin.USER_CONFIRMED:
        action = source.get('confirmation')
        if source.get('status') != 'USER_CONFIRMED' or not isinstance(action, dict):
            raise ValueError('User confirmation record is missing.')
        pending = IntakeResult(raw, IntakeStatus.NEEDS_CONFIRMATION, 'SAVED', candidates, (), (), None)
        restored = select_interpretation(pending, action.get('choice'), expected_unit=action.get('expected_unit'))
        if restored.to_dict() != confirmed.to_dict():
            raise ValueError('Saved confirmation does not match its selected interpretation.')
    else:
        if source.get('status') != 'AGREED' or any(item is None for item in candidates):
            raise ValueError('Dual-parse confirmation is incomplete.')
        if _signature(candidates[0]) != _signature(candidates[1]) or problem != candidates[0]:
            raise ValueError('Saved interpretations do not agree.')
    planned = PlanSpec.model_validate_json(json.dumps(planning.get('plan'), allow_nan=False), strict=True)
    if not planned.supported or validate_plan(planned, confirmed) is not None:
        raise ValueError('Saved plan is incompatible with the confirmed problem.')
    return confirmed, planned


def execute_preparation(
    client, saved, *, timeout=15.0, max_guard_replans=1,
    max_corrections=2, correction_time_budget=90.0,
):
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Execution timeout must be finite and positive.')
    if type(max_guard_replans) is not int or max_guard_replans not in (0, 1):
        raise ValueError('Guard replans must be zero or one.')
    if type(max_corrections) is not int or not 0 <= max_corrections <= 2:
        raise ValueError('Correction attempts must be between zero and two.')
    if isinstance(correction_time_budget, bool) or not isinstance(correction_time_budget, (int, float)) or not math.isfinite(correction_time_budget) or correction_time_budget <= 0:
        raise ValueError('Correction time budget must be finite and positive.')
    confirmed, planned = restore_preparation(saved)
    problem = confirmed.problem
    report = {
        'stage': 'EXECUTED_REPORT', 'status': 'UNVERIFIED',
        'preparation': saved, 'interpreted_problem': problem.model_dump(mode='json'),
        'plan': planned.model_dump(mode='json'), 'generation_batches': [], 'replanning': [],
        'routes': {}, 'route_executions': 0, 'comparison': None, 'final_answer': None,
        'correction_history': [], 'self_correction': 'NOT_ATTEMPTED',
        'correction_limits': {'max_attempts': max_corrections, 'time_budget_seconds': correction_time_budget},
        'backend': 'local-development',
        'limitations': 'Local memory/network isolation is not enforced. Saved preparation is editable local input, not authenticated model evidence.',
    }

    def stop(reason, detail):
        report['comparison'] = ComparisonResult(
            Verdict.UNVERIFIED, reason, detail, ComparisonContext(problem.expected_unit),
        ).to_dict()
        return report

    module = select_module(problem)
    if module is None:
        return stop(Reason.EXECUTION_MODULE_UNSUPPORTED, 'No execution module is available for this problem.')
    for batch_index in range(max_guard_replans + 1):
        try:
            module.plan(confirmed, planned)
        except (ValueError, SyntaxError, ArithmeticError):
            return stop(Reason.EXECUTION_MODULE_UNSUPPORTED, 'No supported execution contract for this problem form, units, or method pair.')
        route_plan = replace(planned.as_route_plan(), execution_contract=module.CONTRACT)
        problem_json = problem.model_dump_json()
        requests = build_blind_requests(problem_json, route_plan)
        # Both conversations exist before either call, and both completions are
        # collected before any route is executed. No cross-route data is sent.
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(request_record, client, request, GeneratedRoute,
                                   stage=f'route_{label}_generation_batch_{batch_index+1}')
                       for label, request in zip(('A', 'B'), requests)]
            generated = [future.result() for future in futures]
        batch = {'plan': planned.model_dump(mode='json'),
                 'attempts': {label: attempt.to_dict() for label, (_, attempt) in zip(('A', 'B'), generated)},
                 'independence': None}
        report['generation_batches'].append(batch)
        if any(parsed is None for parsed, _ in generated):
            return stop(Reason.ROUTE_GENERATION_FAILED, 'Both independent code generations must succeed.')
        codes = [parsed.code for parsed, _ in generated]
        guard = check_independence(problem=problem_json, plan=route_plan, request_a=requests[0], request_b=requests[1],
                                   code_a=codes[0], code_b=codes[1])
        batch['independence'] = guard.to_dict()
        if guard.accepted:
            break
        if batch_index == max_guard_replans:
            return stop(Reason.INDEPENDENCE_REJECTED, 'Independence guard rejected generated routes within the planning budget.')
        replanned = plan_problem(client, confirmed, max_attempts=1, independence_feedback=guard.reason)
        report['replanning'].append(replanned.to_dict())
        if replanned.status != PlanningStatus.PLANNED:
            return stop(Reason.INDEPENDENCE_REJECTED, 'Planner could not supply a valid replacement plan.')
        planned = replanned.plan
        report['plan'] = planned.model_dump(mode='json')

    specifications = [module.route_a(confirmed, planned), module.route_b(confirmed, planned)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run_code, code, timeout, verification=spec) for code, spec in zip(codes, specifications)]
        executed = {label: future.result() for label, future in zip(('A', 'B'), futures)}
    report['route_executions'] = 2
    compared = _compare(module, problem, planned, executed, guard)
    executed, guard, compared = _correct(
        client, report, confirmed, planned, module, route_plan, requests, codes,
        specifications, executed, guard, compared,
        timeout=timeout, max_corrections=max_corrections, time_budget=correction_time_budget,
    )
    report['routes'] = {
        label: {'method': method.value, 'verification': spec.to_dict(), **execution.to_dict()}
        for label, method, spec, execution in zip(('A', 'B'), (planned.method_a, planned.method_b), specifications, executed.values())
    }
    report['status'] = compared.verdict.value
    report['comparison'] = compared.to_dict()
    if compared.verdict in (Verdict.VERIFIED, Verdict.VERIFIED_WITH_DEVIATION):
        label = select_answer_route(executed, problem.expected_unit)
        value = executed[label].result
        payload = {'values': value['values'], 'answer_shape': 'set'} if 'values' in value else {'value': value['value']}
        report['final_answer'] = {**payload, 'unit': value['unit'],
                                  'source_route': label, 'verdict': compared.verdict.value,
                                  'corrected_after_conflict': compared.context.corrected_after_conflict}
    return report
