"""Deterministic, order-independent matching of finite real answer sets."""

from dataclasses import asdict, dataclass, replace

from app.core.comparator import ComparisonContext, Reason, ScalarRoute, Verdict, compare_scalars
from app.core.numbers import parse_scalar


@dataclass(frozen=True)
class SetRoute:
    values: tuple | None = None
    unit: str | None = None
    absolute_errors: tuple | None = None
    execution_error: str | None = None


@dataclass(frozen=True)
class SetComparisonResult:
    verdict: Verdict
    reason: Reason
    detail: str
    context: ComparisonContext
    evidence: dict | None = None

    def to_dict(self):
        return asdict(self)


def _matching(edges, size):
    """Augmenting paths avoid the incomplete matches produced by greedy pairing."""
    assigned = {}

    def augment(left, seen):
        for right in edges[left]:
            if right in seen:
                continue
            seen.add(right)
            if right not in assigned or augment(assigned[right], seen):
                assigned[right] = left
                return True
        return False

    for left in range(size):
        if not augment(left, set()):
            return None
    return sorted((left, right) for right, left in assigned.items())


def compare_sets(route_a, route_b, *, tolerance, context):
    def result(verdict, reason, detail, evidence=None):
        return SetComparisonResult(verdict, reason, detail, context, evidence)

    # Reuse the scalar gates for execution, units, independence, and sanity,
    # including their hard-failure priority. Values/errors are checked below.
    gate = compare_scalars(
        ScalarRoute(0, route_a.unit, 0, route_a.execution_error),
        ScalarRoute(0, route_b.unit, 0, route_b.execution_error),
        tolerance=tolerance, context=context,
    )
    if gate.verdict != Verdict.VERIFIED:
        return result(gate.verdict, gate.reason, gate.detail)
    cleaned = []
    try:
        for route in (route_a, route_b):
            if not isinstance(route.values, tuple) or len(route.values) > 16:
                raise ValueError('Bounded real sets are required.')
            if not isinstance(route.absolute_errors, tuple) or len(route.values) != len(route.absolute_errors):
                return result(Verdict.UNVERIFIED, Reason.MISSING_ERROR_ESTIMATE, 'Each set element needs an executed error bound.')
            unique = {}
            for raw_value, raw_error in zip(route.values, route.absolute_errors):
                value, error = parse_scalar(raw_value), parse_scalar(raw_error)
                if error < 0:
                    return result(Verdict.UNVERIFIED, Reason.INVALID_ERROR_ESTIMATE, 'A set element has a negative error bound.')
                # Exact duplicate representations describe one set element.
                # Keep the largest error; never merge merely nearby numbers.
                if value not in unique or error > unique[value][2]:
                    unique[value] = (raw_value, raw_error, error)
            cleaned.append(tuple((value, error) for value, error, _ in unique.values()))
    except (ValueError, TypeError):
        return result(Verdict.UNVERIFIED, Reason.UNSUPPORTED_VALUE, 'Only finite real decimal sets with finite errors are supported.')
    a, b = cleaned
    base = {'answer_shape': 'set', 'route_a_count': len(a), 'route_b_count': len(b), 'matched_pairs': []}
    if len(a) != len(b):
        return result(Verdict.CONFLICT, Reason.SET_CARDINALITY_MISMATCH, 'Distinct answer counts disagree.', base)
    comparisons = {}
    tight_edges, loose_edges = [], []
    pair_context = replace(context, corrected_after_conflict=False)
    for i, (value_a, error_a) in enumerate(a):
        tight, loose = [], []
        for j, (value_b, error_b) in enumerate(b):
            pair = compare_scalars(
                ScalarRoute(value_a, route_a.unit, error_a),
                ScalarRoute(value_b, route_b.unit, error_b),
                tolerance=tolerance, context=pair_context,
            )
            comparisons[i, j] = pair
            if pair.verdict == Verdict.VERIFIED:
                tight.append(j)
                loose.append(j)
            elif pair.verdict == Verdict.VERIFIED_WITH_DEVIATION or pair.reason == Reason.DEVIATION_CAUSE_MISSING:
                loose.append(j)
        tight_edges.append(tight)
        loose_edges.append(loose)
    match = _matching(tight_edges, len(a))
    verdict, reason = Verdict.VERIFIED, Reason.TIGHT_AGREEMENT
    if match is None:
        match = _matching(loose_edges, len(a))
        if match is None:
            # Retain pairwise evidence even when no complete bijection exists.
            base['pairwise_comparisons'] = [
                {'route_a_index': i, 'route_b_index': j, **pair.to_dict()}
                for (i, j), pair in comparisons.items()]
            reason = Reason.CORRECTION_REQUIRES_TIGHT if context.corrected_after_conflict else Reason.NUMERIC_DISAGREEMENT
            return result(Verdict.CONFLICT, reason, 'No complete one-to-one answer match meets the required tolerance.', base)
        verdict, reason = Verdict.VERIFIED_WITH_DEVIATION, Reason.LOOSE_AGREEMENT
    base['matched_pairs'] = [{'route_a_index': i, 'route_b_index': j, **comparisons[i, j].to_dict()}
                             for i, j in match]
    if verdict == Verdict.VERIFIED_WITH_DEVIATION:
        if context.corrected_after_conflict:
            return result(Verdict.CONFLICT, Reason.CORRECTION_REQUIRES_TIGHT, 'A corrected answer set must match within tight limits.', base)
        if not context.deviation_cause or not context.deviation_cause.strip():
            return result(Verdict.UNVERIFIED, Reason.DEVIATION_CAUSE_MISSING, 'Loose set agreement needs a documented likely cause.', base)
    return result(verdict, reason, 'All distinct real answers match one-to-one; order does not affect the verdict.', base)
