"""Auto-fix proposals (Scenario A, Scenario B) and plan diff (Sections 5.1-5.4)."""

from __future__ import annotations

import ipaddress

from core.allocator import plan_vlsm
from core.analytics import compute_metrics
from core.diagnostics import check_net005_shortage, check_net010_fragmentation
from core.models import (
    Department,
    Plan,
    PlanDiff,
    ProposalPreview,
    ReservedBlock,
)
from core.sizing import min_power_of_two, planned_hosts, prefix_for, prefix_for_size


def diff(old: Plan, new: Plan) -> PlanDiff:
    """Compare two plans by department name (Section 5.4).

    Returns subnets whose network address changed and total current hosts affected.
    """
    old_map = {s.department: s for s in old.subnets}
    new_map = {s.department: s for s in new.subnets}

    changed: list[tuple[str, str, str]] = []
    affected_devices = 0

    for name, old_sub in old_map.items():
        new_sub = new_map.get(name)
        if new_sub is None or old_sub.network.network_address != new_sub.network.network_address:
            new_cidr = str(new_sub.network) if new_sub is not None else "—"
            changed.append((name, str(old_sub.network), new_cidr))
            affected_devices += old_sub.hosts

    return PlanDiff(changed_subnets=changed, affected_devices=affected_devices)


def propose_scenario_a(
    current_plan: Plan,
    departments: list[Department],
    reserved: list[ReservedBlock],
) -> ProposalPreview:
    """Scenario A: find minimal supernet of base that fits all departments + reserves (Section 5.2)."""
    metrics = compute_metrics(current_plan)
    sum_blocks = sum(
        1 << (32 - prefix_for(planned_hosts(d.hosts, d.reserve_pct)))
        for d in departments
    )
    required_total = sum_blocks + metrics.reserved_in_pool
    start_prefix = min(
        current_plan.base.prefixlen - 1,
        prefix_for_size(min_power_of_two(required_total)),
    )

    for p in range(start_prefix, 7, -1):
        expanded_base = current_plan.base.supernet(new_prefix=p)
        candidate = plan_vlsm(
            expanded_base,
            departments,
            reserved,
            gateway_policy=current_plan.gateway_policy,
        )
        if candidate.is_complete:
            return ProposalPreview(
                scenario="A",
                success=True,
                old_base=current_plan.base,
                new_base=expanded_base,
                new_plan=candidate,
                diff=diff(current_plan, candidate),
            )

    return ProposalPreview(
        scenario="A",
        success=False,
        old_base=current_plan.base,
        new_base=current_plan.base,
        new_plan=None,
        diff=None,
    )


def propose_scenario_b(
    saved_plan: Plan,
    new_department: Department,
    reserved: list[ReservedBlock],
    lang: str = "kk",
) -> ProposalPreview:
    """Scenario B: add a new department without altering existing subnet addresses (Section 5.3)."""
    existing_networks = [s.network for s in saved_plan.subnets]
    attempt = plan_vlsm(
        saved_plan.base,
        [new_department],
        reserved,
        gateway_policy=saved_plan.gateway_policy,
        extra_blocked=existing_networks,
    )

    if attempt.is_complete and attempt.subnets:
        added = attempt.subnets[0]
        merged_plan = Plan(
            base=saved_plan.base,
            method=saved_plan.method,
            subnets=list(saved_plan.subnets) + [added],
            unallocated=list(saved_plan.unallocated),
            reserved=list(saved_plan.reserved),
            free_blocks=attempt.free_blocks,
            out_of_base_reserves=list(saved_plan.out_of_base_reserves),
            gateway_policy=saved_plan.gateway_policy,
        )
        return ProposalPreview(
            scenario="B",
            success=True,
            old_base=saved_plan.base,
            new_base=saved_plan.base,
            new_plan=merged_plan,
            diff=diff(saved_plan, merged_plan),
            added_subnet=added,
        )

    # Not placed -> emit NET-010 or NET-005
    failed_merged = Plan(
        base=saved_plan.base,
        method=saved_plan.method,
        subnets=list(saved_plan.subnets),
        unallocated=list(saved_plan.unallocated) + list(attempt.unallocated),
        reserved=list(saved_plan.reserved),
        free_blocks=saved_plan.free_blocks,
        out_of_base_reserves=list(saved_plan.out_of_base_reserves),
        gateway_policy=saved_plan.gateway_policy,
    )
    findings = check_net010_fragmentation(failed_merged, lang) + check_net005_shortage(failed_merged, lang)
    return ProposalPreview(
        scenario="B",
        success=False,
        old_base=saved_plan.base,
        new_base=saved_plan.base,
        new_plan=None,
        diff=None,
        findings=findings,
    )
