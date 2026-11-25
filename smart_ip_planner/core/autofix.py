"""Auto-fix scenarios A (expand base network) and B (non-disruptive department add) (FT-18..FT-20)."""

from __future__ import annotations

import ipaddress

from core.allocator import build_allocation, compute_metrics, plan_network, prepare_free_space
from core.calculator import MIN_BASE_PREFIX, planned_hosts, prefix_for, validate_base_network
from core.models import (
    AutoFixPreview,
    DepartmentInput,
    PlanResult,
    PlannerConfig,
    ReserveInput,
)


def preview_scenario_a_expand_base(
    config: PlannerConfig,
    departments: list[DepartmentInput],
    reserves: list[ReserveInput],
) -> AutoFixPreview:
    """Scenario A: find the smallest supernet of base_cidr that fits all departments + reserves."""
    base = validate_base_network(config.base_cidr)

    for candidate_prefix in range(base.prefixlen - 1, MIN_BASE_PREFIX - 1, -1):
        expanded = base.supernet(new_prefix=candidate_prefix)
        candidate_cfg = PlannerConfig(
            base_cidr=str(expanded),
            method=config.method,
            gateway_policy=config.gateway_policy,
            default_reserve_pct=config.default_reserve_pct,
            threshold_moderate=config.threshold_moderate,
            threshold_high=config.threshold_high,
            threshold_critical=config.threshold_critical,
        )
        candidate_plan = plan_network(candidate_cfg, departments, reserves, include_comparison=True)
        if candidate_plan.is_complete:
            return AutoFixPreview(
                scenario="A_expand_base",
                success=True,
                summary_key="autofix_a_success",
                old_base_cidr=str(base),
                new_base_cidr=str(expanded),
                preview_plan=candidate_plan,
                details={
                    "old_prefix": base.prefixlen,
                    "new_prefix": expanded.prefixlen,
                    "old_pool": base.num_addresses,
                    "new_pool": expanded.num_addresses,
                },
            )

    return AutoFixPreview(
        scenario="A_expand_base",
        success=False,
        summary_key="autofix_a_failed",
        old_base_cidr=str(base),
        new_base_cidr=str(base),
        preview_plan=None,
        details={"min_prefix": MIN_BASE_PREFIX},
    )


def preview_scenario_b_add_department(
    saved_plan: PlanResult,
    new_department: DepartmentInput,
    reserves: list[ReserveInput],
) -> AutoFixPreview:
    """Scenario B: place a new department into remaining free space without altering existing allocations."""
    base = validate_base_network(saved_plan.config.base_cidr)
    h_plan = planned_hosts(new_department.hosts, new_department.growth_reserve_pct)
    req_prefix = prefix_for(h_plan)
    req_size = 1 << (32 - req_prefix)

    # Start from remaining free blocks of the saved plan
    free_blocks = sorted(
        (ipaddress.IPv4Network(cidr, strict=True) for cidr in saved_plan.free_blocks),
        key=lambda n: (int(n.network_address), n.prefixlen),
    )

    chosen_idx = None
    for idx, block in enumerate(free_blocks):
        if block.prefixlen <= req_prefix:
            chosen_idx = idx
            break

    if chosen_idx is None:
        return AutoFixPreview(
            scenario="B_add_department",
            success=False,
            summary_key="autofix_b_failed",
            old_base_cidr=str(base),
            new_base_cidr=str(base),
            preview_plan=None,
            unchanged_count=len(saved_plan.allocations),
            details={
                "department": new_department.name,
                "required_prefix": req_prefix,
                "required_size": req_size,
                "largest_free": saved_plan.metrics.largest_free_block,
            },
        )

    block = free_blocks.pop(chosen_idx)
    chosen = next(block.subnets(new_prefix=req_prefix))
    if block != chosen:
        free_blocks.extend(block.address_exclude(chosen))
        free_blocks.sort(key=lambda n: (int(n.network_address), n.prefixlen))

    added_alloc = build_allocation(new_department, chosen, h_plan, saved_plan.config.gateway_policy)
    new_allocations = list(saved_plan.allocations) + [added_alloc]

    _, valid_reserves, invalid_reserves, reserved_in_pool = prepare_free_space(base, reserves)
    collapsed_free = list(ipaddress.collapse_addresses(free_blocks)) if free_blocks else []
    new_metrics = compute_metrics(base, new_allocations, collapsed_free, reserved_in_pool, saved_plan.config)

    preview_plan = PlanResult(
        config=saved_plan.config,
        allocations=new_allocations,
        unallocated=list(saved_plan.unallocated),
        free_blocks=[str(b) for b in collapsed_free],
        valid_reserves=valid_reserves,
        invalid_reserves=invalid_reserves,
        is_complete=(len(saved_plan.unallocated) == 0),
        metrics=new_metrics,
        comparison=saved_plan.comparison,
    )

    return AutoFixPreview(
        scenario="B_add_department",
        success=True,
        summary_key="autofix_b_success",
        old_base_cidr=str(base),
        new_base_cidr=str(base),
        preview_plan=preview_plan,
        added_allocation=added_alloc,
        unchanged_count=len(saved_plan.allocations),
        details={
            "department": new_department.name,
            "assigned_cidr": added_alloc.subnet_cidr,
            "unchanged": len(saved_plan.allocations),
        },
    )
