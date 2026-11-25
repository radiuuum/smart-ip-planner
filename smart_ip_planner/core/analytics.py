"""Network metrics and automatic VLSM vs FLSM comparison (Section 3.5 & FT-11..FT-14)."""

from __future__ import annotations

import ipaddress

from core.allocator import plan_flsm, plan_vlsm
from core.models import Department, MethodComparison, Plan, PlanMetrics, ReservedBlock
from core.sizing import min_power_of_two, planned_hosts, prefix_for, prefix_for_size


def fill_level_for(
    fill_pct: float,
    moderate: float = 70.0,
    high: float = 85.0,
    critical: float = 95.0,
) -> str:
    """Classify base pool fill percentage using configurable thresholds (Section 3.5)."""
    if fill_pct > critical:
        return "critical"
    if fill_pct > high:
        return "high"
    if fill_pct > moderate:
        return "moderate"
    return "sufficient"


def compute_metrics(
    plan: Plan,
    moderate: float = 70.0,
    high: float = 85.0,
    critical: float = 95.0,
) -> PlanMetrics:
    """Compute all quantitative metrics defined in Section 3.5."""
    pool_size = plan.base.num_addresses
    allocated = sum(s.network.num_addresses for s in plan.subnets)

    collapsed_res = (
        list(ipaddress.collapse_addresses([r.network for r in plan.reserved]))
        if plan.reserved
        else []
    )
    reserved_in_pool = sum(r.num_addresses for r in collapsed_res)

    fill_pct = ((allocated + reserved_in_pool) / pool_size) * 100.0 if pool_size else 0.0

    total_hosts = sum(s.hosts for s in plan.subnets)
    total_cap = sum(s.capacity for s in plan.subnets)
    utilization_pct = (total_hosts / total_cap) * 100.0 if total_cap else 0.0

    collapsed_free = (
        list(ipaddress.collapse_addresses(plan.free_blocks))
        if plan.free_blocks
        else []
    )
    free_outside = sum(b.num_addresses for b in collapsed_free)
    if collapsed_free:
        largest = max(collapsed_free, key=lambda b: (b.num_addresses, -int(b.network_address)))
        largest_size = largest.num_addresses
    else:
        largest = None
        largest_size = 0

    frag_index = 0.0 if free_outside == 0 else 1.0 - (largest_size / free_outside)

    return PlanMetrics(
        pool_size=pool_size,
        allocated=allocated,
        reserved_in_pool=reserved_in_pool,
        free_outside=free_outside,
        fill_pct=round(fill_pct, 2),
        fill_level=fill_level_for(fill_pct, moderate, high, critical),
        utilization_pct=round(utilization_pct, 2),
        largest_free_size=largest_size,
        largest_free_network=largest,
        free_blocks_count=len(collapsed_free),
        fragmentation_index=round(frag_index, 4),
    )


def compare_methods(
    base: ipaddress.IPv4Network,
    departments: list[Department],
    reserved: list[ReservedBlock] | None = None,
    gateway_policy: str = "first",
) -> MethodComparison:
    """Automatically compare VLSM vs FLSM on the same project inputs (Section 3.5 & FT-14)."""
    res_list = list(reserved or [])
    vlsm_plan = plan_vlsm(base, departments, res_list, gateway_policy=gateway_policy)
    flsm_plan = plan_flsm(base, departments, res_list, gateway_policy=gateway_policy)

    sizes_vlsm = [
        1 << (32 - prefix_for(planned_hosts(d.hosts, d.reserve_pct)))
        for d in departments
    ]
    a_vlsm = sum(sizes_vlsm)
    a_flsm = (max(sizes_vlsm) * len(sizes_vlsm)) if sizes_vlsm else 0
    savings_addresses = a_flsm - a_vlsm
    savings_pct = (savings_addresses / a_flsm) * 100.0 if a_flsm > 0 else 0.0

    vlsm_min_pool = min_power_of_two(a_vlsm) if a_vlsm > 0 else 4
    flsm_min_pool = min_power_of_two(a_flsm) if a_flsm > 0 else 4

    return MethodComparison(
        a_vlsm=a_vlsm,
        a_flsm=a_flsm,
        savings_addresses=savings_addresses,
        savings_pct=round(savings_pct, 2),
        vlsm_min_pool_size=vlsm_min_pool,
        vlsm_min_pool_prefix=prefix_for_size(vlsm_min_pool),
        flsm_min_pool_size=flsm_min_pool,
        flsm_min_pool_prefix=prefix_for_size(flsm_min_pool),
        vlsm_complete=vlsm_plan.is_complete,
        flsm_complete=flsm_plan.is_complete,
    )
