"""Free-space preparation, VLSM (First-Fit Decreasing), and FLSM allocation (Sections 3.2-3.4)."""

from __future__ import annotations

import ipaddress
from typing import Iterable, Optional

from core.models import (
    Department,
    GatewayPolicy,
    MethodType,
    Plan,
    ReservedBlock,
    Subnet,
    UnallocatedItem,
)
from core.sizing import capacity_for_prefix, planned_hosts, prefix_for


def prepare_free_blocks(
    base: ipaddress.IPv4Network,
    reserved: Iterable[ReservedBlock],
) -> tuple[list[ipaddress.IPv4Network], list[ReservedBlock], list[ReservedBlock]]:
    """Exclude manual reserves from base network (Section 3.2).

    Returns:
        (sorted_free_blocks, in_base_reserves, out_of_base_reserves)
    """
    free: list[ipaddress.IPv4Network] = [base]
    in_base: list[ReservedBlock] = []
    out_of_base: list[ReservedBlock] = []

    for res in reserved:
        rnet = res.network
        if not rnet.subnet_of(base):
            out_of_base.append(res)
            continue

        in_base.append(res)
        next_free: list[ipaddress.IPv4Network] = []
        for block in free:
            if not block.overlaps(rnet):
                next_free.append(block)
            elif block.subnet_of(rnet):
                continue
            else:
                next_free.extend(block.address_exclude(rnet))
        free = sorted(next_free, key=lambda n: (int(n.network_address), n.prefixlen))

    return free, in_base, out_of_base


def _make_subnet(
    dept: Department,
    chosen: ipaddress.IPv4Network,
    h_plan: int,
    gateway_policy: GatewayPolicy,
) -> Subnet:
    first_usable = chosen.network_address + 1
    last_usable = chosen.broadcast_address - 1
    gateway = last_usable if gateway_policy == "last" else first_usable
    return Subnet(
        department=dept.name,
        network=chosen,
        gateway=gateway,
        planned_hosts=h_plan,
        capacity=capacity_for_prefix(chosen.prefixlen),
        vlan_id=dept.vlan_id,
        hosts=dept.hosts,
        reserve_pct=dept.reserve_pct,
    )


def _sort_key(item: tuple[Department, int, int]) -> tuple[int, int, int, str]:
    """Deterministic key (prefix, VLAN ID, name) per Section 3.3 & FT-09."""
    dept, _h_plan, pref = item
    vlan_present = 1 if dept.vlan_id is None else 0
    vlan_val = 0 if dept.vlan_id is None else dept.vlan_id
    return (pref, vlan_present, vlan_val, dept.name.lower())


def _allocate(
    base: ipaddress.IPv4Network,
    departments: list[Department],
    reserved: list[ReservedBlock],
    method: MethodType,
    gateway_policy: GatewayPolicy = "first",
    extra_blocked: Optional[list[ipaddress.IPv4Network]] = None,
) -> Plan:
    all_blocked = list(reserved)
    if extra_blocked:
        all_blocked.extend(ReservedBlock(network=n, note="blocked") for n in extra_blocked)

    free, in_base_all, out_of_base_all = prepare_free_blocks(base, all_blocked)
    # Keep only user-specified reserves in Plan.reserved and Plan.out_of_base_reserves
    in_base_user = [r for r in reserved if r.network.subnet_of(base)]
    out_of_base_user = [r for r in reserved if not r.network.subnet_of(base)]

    reqs: list[tuple[Department, int, int]] = []
    for dept in departments:
        h_plan = planned_hosts(dept.hosts, dept.reserve_pct)
        pref = prefix_for(h_plan)
        reqs.append((dept, h_plan, pref))

    if method == "FLSM" and reqs:
        flsm_pref = min(r[2] for r in reqs)
        reqs = [(d, hp, flsm_pref) for d, hp, _ in reqs]

    reqs.sort(key=_sort_key)

    subnets: list[Subnet] = []
    unallocated: list[UnallocatedItem] = []

    for dept, h_plan, req_pref in reqs:
        req_size = 1 << (32 - req_pref)
        chosen_idx: Optional[int] = None
        for idx, block in enumerate(free):
            if block.prefixlen <= req_pref:
                chosen_idx = idx
                break

        if chosen_idx is None:
            total_free = sum(b.num_addresses for b in free)
            reason = "space" if total_free < req_size else "block"
            unallocated.append(
                UnallocatedItem(
                    department=dept,
                    planned_hosts=h_plan,
                    required_prefix=req_pref,
                    required_size=req_size,
                    reason_code=reason,
                )
            )
            continue

        block = free.pop(chosen_idx)
        chosen = next(block.subnets(new_prefix=req_pref))
        if block != chosen:
            free.extend(block.address_exclude(chosen))
            free.sort(key=lambda n: (int(n.network_address), n.prefixlen))

        subnets.append(_make_subnet(dept, chosen, h_plan, gateway_policy))

    collapsed_free = list(ipaddress.collapse_addresses(free)) if free else []
    return Plan(
        base=base,
        method=method,
        subnets=subnets,
        unallocated=unallocated,
        reserved=in_base_user,
        free_blocks=collapsed_free,
        out_of_base_reserves=out_of_base_user,
        gateway_policy=gateway_policy,
    )


def plan_vlsm(
    base: ipaddress.IPv4Network,
    departments: list[Department],
    reserved: Optional[list[ReservedBlock]] = None,
    gateway_policy: GatewayPolicy = "first",
    extra_blocked: Optional[list[ipaddress.IPv4Network]] = None,
) -> Plan:
    """Allocate subnets using VLSM First-Fit Decreasing (Section 3.3)."""
    return _allocate(base, departments, list(reserved or []), "VLSM", gateway_policy, extra_blocked)


def plan_flsm(
    base: ipaddress.IPv4Network,
    departments: list[Department],
    reserved: Optional[list[ReservedBlock]] = None,
    gateway_policy: GatewayPolicy = "first",
    extra_blocked: Optional[list[ipaddress.IPv4Network]] = None,
) -> Plan:
    """Allocate subnets using FLSM with uniform largest prefix (Section 3.4)."""
    return _allocate(base, departments, list(reserved or []), "FLSM", gateway_policy, extra_blocked)


def allocate_plan(
    base: ipaddress.IPv4Network,
    departments: list[Department],
    reserved: Optional[list[ReservedBlock]] = None,
    method: MethodType = "VLSM",
    gateway_policy: GatewayPolicy = "first",
) -> Plan:
    """Dispatch allocation to VLSM or FLSM."""
    if method == "FLSM":
        return plan_flsm(base, departments, reserved, gateway_policy)
    return plan_vlsm(base, departments, reserved, gateway_policy)
