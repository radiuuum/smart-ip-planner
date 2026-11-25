"""Network growth simulator and renumbering cost calculation (Section 5.5)."""

from __future__ import annotations

import ipaddress

from core.allocator import plan_vlsm
from core.models import (
    Department,
    GrowthReport,
    GrowthRow,
    Plan,
    ReservedBlock,
    Subnet,
)
from core.proposals import diff
from core.sizing import capacity_for_prefix, planned_hosts, prefix_for
from strings import get_strings


def _compute_free_blocks(
    base: ipaddress.IPv4Network,
    occupied: list[ipaddress.IPv4Network],
) -> list[ipaddress.IPv4Network]:
    free = [base]
    for occ in occupied:
        if not occ.subnet_of(base):
            continue
        next_free: list[ipaddress.IPv4Network] = []
        for blk in free:
            if not blk.overlaps(occ):
                next_free.append(blk)
            elif blk.subnet_of(occ):
                continue
            else:
                next_free.extend(blk.address_exclude(occ))
        free = sorted(next_free, key=lambda n: (int(n.network_address), n.prefixlen))
    return list(ipaddress.collapse_addresses(free)) if free else []


def simulate_growth(
    plan: Plan,
    reserved: list[ReservedBlock],
    growth_pct: int | None = None,
    custom_hosts: dict[str, int] | None = None,
    lang: str = "kk",
) -> GrowthReport:
    """Simulate network growth strictly per Section 5.5 without modifying the original plan."""
    t = get_strings(lang)

    # 1. Calculate H_new for each allocated department (no double reserve!)
    targets: list[tuple[Subnet, int]] = []
    for sub in plan.subnets:
        if custom_hosts is not None and sub.department in custom_hosts:
            h_new = max(1, int(custom_hosts[sub.department]))
        else:
            g = int(growth_pct or 0)
            h_new = planned_hosts(sub.hosts, g)
        targets.append((sub, h_new))

    # Working copy of current network assignments
    working_nets: dict[str, ipaddress.IPv4Network] = {
        sub.department: sub.network for sub in plan.subnets
    }
    res_nets = [r.network for r in reserved if r.network.subnet_of(plan.base)]

    verdicts: dict[str, tuple[str, ipaddress.IPv4Network | None, str]] = {}
    need_expand_list: list[tuple[Subnet, int, int]] = []

    for sub, h_new in targets:
        if h_new <= sub.capacity:
            verdicts[sub.department] = ("ok", sub.network, t["gr.ok"])
        else:
            p_new = prefix_for(h_new)
            need_expand_list.append((sub, h_new, p_new))

    # Process departments needing expansion in descending order of required size (smallest prefix first)
    need_expand_list.sort(key=lambda x: (x[2], x[0].vlan_id or 10**9, x[0].department.lower()))
    full_replan_needed = False

    for sub, _h_new, p_new in need_expand_list:
        cur_net = working_nets[sub.department]

        # Check 1: Expand in place (must start at same network_address and not overlap others/reserves)
        expanded_ok = False
        if p_new >= plan.base.prefixlen:
            candidate = cur_net.supernet(new_prefix=p_new)
            if (
                candidate.network_address == cur_net.network_address
                and candidate.subnet_of(plan.base)
            ):
                others = [
                    net for name, net in working_nets.items() if name != sub.department
                ] + res_nets
                if not any(candidate.overlaps(o) for o in others):
                    working_nets[sub.department] = candidate
                    verdicts[sub.department] = (
                        "inplace",
                        candidate,
                        t["gr.msg_inplace"].format(
                            dept=sub.department, old=str(cur_net), new=str(candidate)
                        ),
                    )
                    expanded_ok = True

        if expanded_ok:
            continue

        # Check 2: Move (after releasing old subnet, check if a free block of prefix p_new exists)
        others = [
            net for name, net in working_nets.items() if name != sub.department
        ] + res_nets
        free_after_release = _compute_free_blocks(plan.base, others)
        chosen: ipaddress.IPv4Network | None = None
        for blk in free_after_release:
            if blk.prefixlen <= p_new:
                chosen = next(blk.subnets(new_prefix=p_new))
                break

        if chosen is not None:
            working_nets[sub.department] = chosen
            verdicts[sub.department] = (
                "move",
                chosen,
                t["gr.msg_move"].format(dept=sub.department, new_net=str(chosen)),
            )
        else:
            # Check 3: Full replanning needed
            full_replan_needed = True
            verdicts[sub.department] = ("replan", None, t["gr.msg_replan"])

    # Build resulting new_plan to compute diff(old, new)
    if full_replan_needed:
        new_depts = [
            Department(name=sub.department, vlan_id=sub.vlan_id, hosts=h_new, reserve_pct=0)
            for sub, h_new in targets
        ]
        new_plan = plan_vlsm(
            plan.base,
            new_depts,
            reserved,
            gateway_policy=plan.gateway_policy,
        )
        new_map = {s.department: s.network for s in new_plan.subnets}
        for sub, h_new in targets:
            if verdicts[sub.department][0] == "replan":
                verdicts[sub.department] = ("replan", new_map.get(sub.department), t["gr.msg_replan"])
    else:
        updated_subnets: list[Subnet] = []
        for sub, h_new in targets:
            net = working_nets[sub.department]
            gw = (
                net.broadcast_address - 1
                if plan.gateway_policy == "last"
                else net.network_address + 1
            )
            updated_subnets.append(
                Subnet(
                    department=sub.department,
                    network=net,
                    gateway=gw,
                    planned_hosts=h_new,
                    capacity=capacity_for_prefix(net.prefixlen),
                    vlan_id=sub.vlan_id,
                    hosts=h_new,
                    reserve_pct=0,
                )
            )
        new_plan = Plan(
            base=plan.base,
            method=plan.method,
            subnets=updated_subnets,
            unallocated=[],
            reserved=list(plan.reserved),
            free_blocks=_compute_free_blocks(
                plan.base, [s.network for s in updated_subnets] + res_nets
            ),
            gateway_policy=plan.gateway_policy,
        )

    plan_diff = diff(plan, new_plan)
    rows: list[GrowthRow] = []
    total_deficit = 0
    for sub, h_new in targets:
        v_code, prop_net, msg = verdicts[sub.department]
        deficit = max(0, h_new - sub.capacity)
        total_deficit += deficit
        rows.append(
            GrowthRow(
                department=sub.department,
                vlan_id=sub.vlan_id,
                current_network=sub.network,
                current_hosts=sub.hosts,
                new_hosts=h_new,
                capacity=sub.capacity,
                deficit=deficit,
                verdict=v_code,
                proposed_network=prop_net,
                message=msg,
            )
        )

    return GrowthReport(
        rows=rows,
        need_expand_count=len(need_expand_list),
        total_count=len(targets),
        total_deficit=total_deficit,
        diff=plan_diff,
        full_replan_needed=full_replan_needed,
        new_plan=new_plan,
    )
