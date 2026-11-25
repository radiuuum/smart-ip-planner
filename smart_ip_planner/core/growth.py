"""Network growth modeling, per-department verdicts, and renumbering cost (FT-21..FT-23)."""

from __future__ import annotations

import ipaddress

from core.calculator import planned_hosts, prefix_for, validate_base_network
from core.models import (
    GrowthItemResult,
    GrowthSimulationResult,
    GrowthVerdict,
    PlanResult,
    ReserveInput,
)


def _subtract_network(
    free: list[ipaddress.IPv4Network],
    taken: ipaddress.IPv4Network,
) -> list[ipaddress.IPv4Network]:
    updated: list[ipaddress.IPv4Network] = []
    for block in free:
        if not block.overlaps(taken):
            updated.append(block)
        elif block.subnet_of(taken):
            continue
        else:
            updated.extend(block.address_exclude(taken))
    return sorted(updated, key=lambda n: (int(n.network_address), n.prefixlen))


def simulate_growth(
    plan: PlanResult,
    reserves: list[ReserveInput],
    uniform_growth_pct: int | None = None,
    custom_hosts: dict[str, int] | None = None,
) -> GrowthSimulationResult:
    """Evaluate impact of network growth on each allocated department (FT-21..FT-23)."""
    base = validate_base_network(plan.config.base_cidr)

    # Track currently occupied networks (allocations + valid reserves)
    alloc_nets = {
        a.department: ipaddress.IPv4Network(a.subnet_cidr, strict=True)
        for a in plan.allocations
    }
    reserve_nets: list[ipaddress.IPv4Network] = []
    for r in reserves:
        if not r.cidr.strip():
            continue
        try:
            rn = ipaddress.IPv4Network(r.cidr.strip(), strict=True)
            if rn.subnet_of(base):
                reserve_nets.append(rn)
        except ValueError:
            continue

    remaining_free = sorted(
        (ipaddress.IPv4Network(cidr, strict=True) for cidr in plan.free_blocks),
        key=lambda n: (int(n.network_address), n.prefixlen),
    )

    items: list[GrowthItemResult] = []
    counts: dict[str, int] = {
        "sufficient": 0,
        "expand_in_place": 0,
        "relocate": 0,
        "full_replan": 0,
    }

    for alloc in plan.allocations:
        if custom_hosts is not None and alloc.department in custom_hosts:
            projected = max(1, int(custom_hosts[alloc.department]))
        else:
            pct = int(uniform_growth_pct or 0)
            projected = planned_hosts(alloc.current_hosts, pct)

        req_prefix = prefix_for(projected)
        cur_net = alloc_nets[alloc.department]

        # 1. Sufficient: fits inside current capacity
        if projected <= alloc.capacity:
            verdict: GrowthVerdict = "sufficient"
            proposed: str | None = alloc.subnet_cidr
            dev_renum = 0
        else:
            # 2. Try expand in place: supernet(new_prefix=req_prefix) stays inside base
            #    and does not overlap any other allocation or reserve
            can_expand = False
            candidate_super: ipaddress.IPv4Network | None = None
            if req_prefix >= base.prefixlen:
                supernet = cur_net.supernet(new_prefix=req_prefix)
                if supernet.subnet_of(base):
                    conflict = False
                    for other_name, other_net in alloc_nets.items():
                        if other_name != alloc.department and supernet.overlaps(other_net):
                            conflict = True
                            break
                    if not conflict:
                        for rn in reserve_nets:
                            if supernet.overlaps(rn):
                                conflict = True
                                break
                    if not conflict:
                        can_expand = True
                        candidate_super = supernet

            if can_expand and candidate_super is not None:
                verdict = "expand_in_place"
                proposed = str(candidate_super)
                # Update state so subsequent departments see the expanded block
                alloc_nets[alloc.department] = candidate_super
                remaining_free = _subtract_network(remaining_free, candidate_super)
                dev_renum = 0  # Existing IPs stay valid; only subnet mask widens
            else:
                # 3. Try relocate into an existing free block
                chosen_idx = None
                for idx, block in enumerate(remaining_free):
                    if block.prefixlen <= req_prefix:
                        chosen_idx = idx
                        break

                if chosen_idx is not None:
                    block = remaining_free.pop(chosen_idx)
                    chosen = next(block.subnets(new_prefix=req_prefix))
                    if block != chosen:
                        remaining_free.extend(block.address_exclude(chosen))
                    # Old subnet becomes free after relocation
                    remaining_free.append(cur_net)
                    remaining_free = list(ipaddress.collapse_addresses(remaining_free))
                    alloc_nets[alloc.department] = chosen

                    verdict = "relocate"
                    proposed = str(chosen)
                    dev_renum = alloc.current_hosts
                else:
                    # 4. Full replanning required
                    verdict = "full_replan"
                    proposed = None
                    dev_renum = alloc.current_hosts

        counts[verdict] += 1
        items.append(
            GrowthItemResult(
                department=alloc.department,
                vlan_id=alloc.vlan_id,
                current_subnet=alloc.subnet_cidr,
                current_capacity=alloc.capacity,
                current_hosts=alloc.current_hosts,
                projected_hosts=projected,
                required_prefix=req_prefix,
                verdict=verdict,
                proposed_subnet=proposed,
                devices_renumbered=dev_renum,
            )
        )

    full_replan_required = counts["full_replan"] > 0
    if full_replan_required:
        subnets_renumbered = len(plan.allocations)
        devices_renumbered = sum(a.current_hosts for a in plan.allocations)
    else:
        subnets_renumbered = sum(1 for item in items if item.verdict == "relocate")
        devices_renumbered = sum(item.devices_renumbered for item in items)

    return GrowthSimulationResult(
        items=items,
        subnets_renumbered=subnets_renumbered,
        devices_renumbered=devices_renumbered,
        full_replan_required=full_replan_required,
        counts_by_verdict=counts,
    )
