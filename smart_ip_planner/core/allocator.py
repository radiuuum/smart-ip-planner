"""VLSM / FLSM allocation engine, free-space management, and metrics (Sections 3.2-3.5)."""

from __future__ import annotations

import ipaddress
from typing import Iterable, Optional

from core.calculator import (
    ValidationError,
    capacity_for_prefix,
    min_power_of_two,
    parse_reserve_network,
    planned_hosts,
    prefix_for,
    prefix_for_block_size,
    validate_base_network,
)
from core.models import (
    AllocationMethod,
    DepartmentInput,
    GatewayPolicy,
    MethodComparison,
    PlanMetrics,
    PlanResult,
    PlannerConfig,
    ReserveInput,
    SubnetAllocation,
    UnallocatedDepartment,
)


def prepare_free_space(
    base: ipaddress.IPv4Network,
    reserves: Iterable[ReserveInput],
) -> tuple[list[ipaddress.IPv4Network], list[ReserveInput], list[tuple[ReserveInput, str]], int]:
    """Prepare sorted free blocks by excluding valid reserves inside base (Section 3.2).

    Returns:
        (free_blocks, valid_reserves, invalid_reserves_with_reason, unique_reserved_ips_in_pool)
    """
    free: list[ipaddress.IPv4Network] = [base]
    valid_reserves: list[ReserveInput] = []
    invalid_reserves: list[tuple[ReserveInput, str]] = []
    valid_reserve_nets: list[ipaddress.IPv4Network] = []

    for res in reserves:
        if not res.cidr.strip():
            continue
        try:
            rnet = parse_reserve_network(res.cidr)
        except ValidationError as exc:
            invalid_reserves.append((res, exc.code))
            continue

        if not rnet.subnet_of(base):
            invalid_reserves.append((res, "outside_base"))
            continue

        valid_reserves.append(res)
        valid_reserve_nets.append(rnet)

        next_free: list[ipaddress.IPv4Network] = []
        for block in free:
            if not block.overlaps(rnet):
                next_free.append(block)
            elif block.subnet_of(rnet):
                # Block lies entirely inside the reserve -> drop it
                continue
            else:
                # Reserve lies inside block -> exclude it
                next_free.extend(block.address_exclude(rnet))
        free = sorted(next_free, key=lambda n: (int(n.network_address), n.prefixlen))

    collapsed_reserves = list(ipaddress.collapse_addresses(valid_reserve_nets)) if valid_reserve_nets else []
    unique_reserved_ips = sum(r.num_addresses for r in collapsed_reserves)
    return free, valid_reserves, invalid_reserves, unique_reserved_ips


def build_allocation(
    dept: DepartmentInput,
    chosen: ipaddress.IPv4Network,
    h_plan: int,
    gateway_policy: GatewayPolicy,
) -> SubnetAllocation:
    """Create a SubnetAllocation record with gateway and usable host range."""
    first_usable = chosen.network_address + 1
    last_usable = chosen.broadcast_address - 1
    if gateway_policy == "last":
        gateway_ip = last_usable
        host_start = first_usable
        host_end = last_usable - 1
    else:
        gateway_ip = first_usable
        host_start = first_usable + 1
        host_end = last_usable

    cap = capacity_for_prefix(chosen.prefixlen)
    free_hosts = cap - h_plan

    return SubnetAllocation(
        department=dept.name,
        vlan_id=dept.vlan_id,
        subnet_cidr=str(chosen),
        network_address=str(chosen.network_address),
        prefix=chosen.prefixlen,
        netmask=str(chosen.netmask),
        first_host_ip=str(host_start),
        last_host_ip=str(host_end),
        broadcast_address=str(chosen.broadcast_address),
        gateway_ip=str(gateway_ip),
        block_size=chosen.num_addresses,
        capacity=cap,
        current_hosts=dept.hosts,
        growth_reserve_pct=dept.growth_reserve_pct,
        planned_hosts=h_plan,
        free_hosts=free_hosts,
        status="allocated",
    )


def _dept_sort_key(item: tuple[DepartmentInput, int, int]) -> tuple[int, int, int, str]:
    """Deterministic sorting key (prefix, VLAN ID, name) per Section 3.3 & FT-09."""
    dept, _h_plan, req_prefix = item
    vlan_missing = 1 if dept.vlan_id is None else 0
    vlan_val = 0 if dept.vlan_id is None else dept.vlan_id
    return (req_prefix, vlan_missing, vlan_val, dept.name.lower())


def _fill_level(fill_pct: float, config: PlannerConfig) -> str:
    if fill_pct > config.threshold_critical:
        return "critical"
    if fill_pct > config.threshold_high:
        return "high"
    if fill_pct > config.threshold_moderate:
        return "moderate"
    return "sufficient"


def compute_metrics(
    base: ipaddress.IPv4Network,
    allocations: list[SubnetAllocation],
    free_blocks: list[ipaddress.IPv4Network],
    reserved_in_pool: int,
    config: PlannerConfig,
) -> PlanMetrics:
    """Compute all metrics from Section 3.5."""
    pool_size = base.num_addresses
    allocated_addresses = sum(a.block_size for a in allocations)
    pool_fill_pct = ((allocated_addresses + reserved_in_pool) / pool_size) * 100.0 if pool_size else 0.0

    total_current_hosts = sum(a.current_hosts for a in allocations)
    total_capacity = sum(a.capacity for a in allocations)
    subnet_utilization_pct = (total_current_hosts / total_capacity) * 100.0 if total_capacity else 0.0

    collapsed_free = list(ipaddress.collapse_addresses(free_blocks)) if free_blocks else []
    total_free = sum(b.num_addresses for b in collapsed_free)
    if collapsed_free:
        largest_net = max(collapsed_free, key=lambda b: (b.num_addresses, -int(b.network_address)))
        largest_free = largest_net.num_addresses
        largest_free_cidr: Optional[str] = str(largest_net)
    else:
        largest_free = 0
        largest_free_cidr = None

    fragmentation_index = 0.0 if total_free == 0 else 1.0 - (largest_free / total_free)

    return PlanMetrics(
        pool_size=pool_size,
        allocated_addresses=allocated_addresses,
        reserved_addresses_in_pool=reserved_in_pool,
        pool_fill_pct=round(pool_fill_pct, 2),
        pool_fill_level=_fill_level(pool_fill_pct, config),
        subnet_utilization_pct=round(subnet_utilization_pct, 2),
        total_free_addresses=total_free,
        largest_free_block=largest_free,
        largest_free_cidr=largest_free_cidr,
        free_block_count=len(collapsed_free),
        fragmentation_index=round(fragmentation_index, 4),
    )


def _run_single_method(
    base: ipaddress.IPv4Network,
    departments: list[DepartmentInput],
    reserves: list[ReserveInput],
    config: PlannerConfig,
    method: AllocationMethod,
) -> PlanResult:
    free, valid_reserves, invalid_reserves, reserved_in_pool = prepare_free_space(base, reserves)

    prepared: list[tuple[DepartmentInput, int, int]] = []
    unallocated: list[UnallocatedDepartment] = []

    for dept in departments:
        if not dept.name.strip():
            continue
        try:
            h_plan = planned_hosts(dept.hosts, dept.growth_reserve_pct)
            req_prefix = prefix_for(h_plan)
            prepared.append((dept, h_plan, req_prefix))
        except ValidationError as exc:
            unallocated.append(
                UnallocatedDepartment(
                    department=dept.name,
                    vlan_id=dept.vlan_id,
                    current_hosts=dept.hosts,
                    growth_reserve_pct=dept.growth_reserve_pct,
                    planned_hosts=max(dept.hosts, 0),
                    required_prefix=30,
                    required_block_size=0,
                    reason_code="invalid_requirement",
                    reason_detail=str(exc),
                )
            )

    if method == "FLSM" and prepared:
        flsm_prefix = min(item[2] for item in prepared)
        prepared = [(dept, h_plan, flsm_prefix) for dept, h_plan, _ in prepared]

    prepared.sort(key=_dept_sort_key)

    allocations: list[SubnetAllocation] = []

    for dept, h_plan, req_prefix in prepared:
        req_size = 1 << (32 - req_prefix)
        chosen_idx: Optional[int] = None
        for idx, block in enumerate(free):
            if block.prefixlen <= req_prefix:
                chosen_idx = idx
                break

        if chosen_idx is None:
            total_free = sum(b.num_addresses for b in free)
            if total_free < req_size:
                reason_code = "insufficient_space"
                reason_detail = (
                    f"Required block /{req_prefix} ({req_size} IPs) exceeds total remaining free space ({total_free} IPs)"
                )
            else:
                reason_code = "no_contiguous_block"
                reason_detail = (
                    f"Total free space is {total_free} IPs, but no contiguous /{req_prefix} ({req_size} IPs) block is available"
                )
            unallocated.append(
                UnallocatedDepartment(
                    department=dept.name,
                    vlan_id=dept.vlan_id,
                    current_hosts=dept.hosts,
                    growth_reserve_pct=dept.growth_reserve_pct,
                    planned_hosts=h_plan,
                    required_prefix=req_prefix,
                    required_block_size=req_size,
                    reason_code=reason_code,
                    reason_detail=reason_detail,
                )
            )
            continue

        block = free.pop(chosen_idx)
        chosen = next(block.subnets(new_prefix=req_prefix))
        if block != chosen:
            free.extend(block.address_exclude(chosen))
            free.sort(key=lambda n: (int(n.network_address), n.prefixlen))

        allocations.append(build_allocation(dept, chosen, h_plan, config.gateway_policy))

    collapsed_free = list(ipaddress.collapse_addresses(free)) if free else []
    metrics = compute_metrics(base, allocations, collapsed_free, reserved_in_pool, config)
    is_complete = len(unallocated) == 0

    return PlanResult(
        config=PlannerConfig(
            base_cidr=str(base),
            method=method,
            gateway_policy=config.gateway_policy,
            default_reserve_pct=config.default_reserve_pct,
            threshold_moderate=config.threshold_moderate,
            threshold_high=config.threshold_high,
            threshold_critical=config.threshold_critical,
        ),
        allocations=allocations,
        unallocated=unallocated,
        free_blocks=[str(b) for b in collapsed_free],
        valid_reserves=valid_reserves,
        invalid_reserves=invalid_reserves,
        is_complete=is_complete,
        metrics=metrics,
        comparison=None,
    )


def plan_network(
    config: PlannerConfig,
    departments: list[DepartmentInput],
    reserves: Optional[list[ReserveInput]] = None,
    include_comparison: bool = True,
) -> PlanResult:
    """Main entry point: validate base network, run selected method, and auto-compare VLSM vs FLSM."""
    base = validate_base_network(config.base_cidr)
    reserves_list = list(reserves or [])

    if not include_comparison:
        return _run_single_method(base, departments, reserves_list, config, config.method)

    vlsm_plan = _run_single_method(base, departments, reserves_list, config, "VLSM")
    flsm_plan = _run_single_method(base, departments, reserves_list, config, "FLSM")

    # Compute theoretical total required addresses for VLSM and FLSM across all valid departments
    req_sizes_vlsm: list[int] = []
    for dept in departments:
        if not dept.name.strip():
            continue
        try:
            h_plan = planned_hosts(dept.hosts, dept.growth_reserve_pct)
            req_prefix = prefix_for(h_plan)
            req_sizes_vlsm.append(1 << (32 - req_prefix))
        except ValidationError:
            continue

    a_vlsm = sum(req_sizes_vlsm)
    a_flsm = (max(req_sizes_vlsm) * len(req_sizes_vlsm)) if req_sizes_vlsm else 0
    savings_pct = ((a_flsm - a_vlsm) / a_flsm * 100.0) if a_flsm > 0 else 0.0

    vlsm_min_pool = min_power_of_two(a_vlsm) if a_vlsm > 0 else 4
    flsm_min_pool = min_power_of_two(a_flsm) if a_flsm > 0 else 4

    comparison = MethodComparison(
        vlsm_required_addresses=a_vlsm,
        flsm_required_addresses=a_flsm,
        vlsm_min_pool_size=vlsm_min_pool,
        vlsm_min_pool_prefix=prefix_for_block_size(vlsm_min_pool),
        flsm_min_pool_size=flsm_min_pool,
        flsm_min_pool_prefix=prefix_for_block_size(flsm_min_pool),
        vlsm_savings_pct=round(savings_pct, 2),
        vlsm_allocated_count=len(vlsm_plan.allocations),
        flsm_allocated_count=len(flsm_plan.allocations),
        vlsm_complete=vlsm_plan.is_complete,
        flsm_complete=flsm_plan.is_complete,
        vlsm_pool_fill_pct=vlsm_plan.metrics.pool_fill_pct,
        flsm_pool_fill_pct=flsm_plan.metrics.pool_fill_pct,
        vlsm_utilization_pct=vlsm_plan.metrics.subnet_utilization_pct,
        flsm_utilization_pct=flsm_plan.metrics.subnet_utilization_pct,
    )

    primary = vlsm_plan if config.method == "VLSM" else flsm_plan
    return PlanResult(
        config=primary.config,
        allocations=primary.allocations,
        unallocated=primary.unallocated,
        free_blocks=primary.free_blocks,
        valid_reserves=primary.valid_reserves,
        invalid_reserves=primary.invalid_reserves,
        is_complete=primary.is_complete,
        metrics=primary.metrics,
        comparison=comparison,
    )
