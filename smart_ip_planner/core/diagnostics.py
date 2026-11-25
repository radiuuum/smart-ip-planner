"""Diagnostic rules registry NET-001..NET-010 (Section 4 & Appendix B)."""

from __future__ import annotations

import ipaddress
from collections import defaultdict
from typing import Callable

from core.analytics import compute_metrics
from core.models import Finding, Plan, ReservedBlock, Subnet
from core.sizing import capacity_for_prefix, min_power_of_two, prefix_for, prefix_for_size
from strings import format_float, format_int, get_strings

SEVERITY_ORDER = {"ERROR": 0, "WARNING": 1, "INFO": 2, "SUCCESS": 3}


def _suggest_free_block(
    base: ipaddress.IPv4Network,
    occupied: list[ipaddress.IPv4Network],
    req_prefix: int,
) -> str:
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
    for blk in free:
        if blk.prefixlen <= req_prefix:
            return str(next(blk.subnets(new_prefix=req_prefix)))
    return "—"


def check_net002_overlaps(plan: Plan, lang: str = "kk") -> list[Finding]:
    """NET-002 (ERROR): Overlapping subnets."""
    t = get_strings(lang)
    findings: list[Finding] = []
    occupied = [s.network for s in plan.subnets] + [r.network for r in plan.reserved]
    for i in range(len(plan.subnets)):
        for j in range(i + 1, len(plan.subnets)):
            s1, s2 = plan.subnets[i], plan.subnets[j]
            if s1.network.overlaps(s2.network):
                suggest = _suggest_free_block(plan.base, occupied, s2.network.prefixlen)
                findings.append(
                    Finding(
                        code="NET-002",
                        level="ERROR",
                        message=t["diag.net002.msg"].format(a=str(s1.network), b=str(s2.network)),
                        affected=[s1.department, s2.department],
                        recommendation=t["diag.net002.rec"].format(suggest=suggest),
                    )
                )
    return findings


def check_net003_bounds_and_reserves(plan: Plan, lang: str = "kk") -> list[Finding]:
    """NET-003 (ERROR): Subnet outside base network, overlapping reserve, or reserve outside base."""
    t = get_strings(lang)
    findings: list[Finding] = []
    occupied = [s.network for s in plan.subnets] + [r.network for r in plan.reserved]

    for s in plan.subnets:
        if not s.network.subnet_of(plan.base):
            suggest = _suggest_free_block(plan.base, occupied, s.network.prefixlen)
            findings.append(
                Finding(
                    code="NET-003",
                    level="ERROR",
                    message=t["diag.net003.outside_msg"].format(net=str(s.network)),
                    affected=[s.department],
                    recommendation=t["diag.net003.rec"].format(suggest=suggest),
                )
            )
            continue
        for res in plan.reserved:
            if s.network.overlaps(res.network):
                suggest = _suggest_free_block(plan.base, occupied, s.network.prefixlen)
                findings.append(
                    Finding(
                        code="NET-003",
                        level="ERROR",
                        message=t["diag.net003.reserve_msg"].format(net=str(s.network), res=str(res.network)),
                        affected=[s.department],
                        recommendation=t["diag.net003.rec"].format(suggest=suggest),
                    )
                )

    for out_res in plan.out_of_base_reserves:
        findings.append(
            Finding(
                code="NET-003",
                level="ERROR",
                message=t["diag.net003.outside_msg"].format(net=str(out_res.network)),
                affected=[out_res.note or str(out_res.network)],
                recommendation=t["diag.net003.rec"].format(suggest=str(plan.base)),
            )
        )

    return findings


def check_net004_duplicate_vlans(plan: Plan, lang: str = "kk") -> list[Finding]:
    """NET-004 (ERROR): Duplicate VLAN ID across departments."""
    t = get_strings(lang)
    vlan_map: dict[int, list[str]] = defaultdict(list)
    for s in plan.subnets:
        if s.vlan_id is not None:
            vlan_map[s.vlan_id].append(s.department)
    for u in plan.unallocated:
        if u.department.vlan_id is not None:
            vlan_map[u.department.vlan_id].append(u.department.name)

    findings: list[Finding] = []
    for vlan, depts in sorted(vlan_map.items()):
        if len(depts) > 1:
            findings.append(
                Finding(
                    code="NET-004",
                    level="ERROR",
                    message=t["diag.net004.msg"].format(vlan=vlan, depts=", ".join(depts)),
                    affected=depts,
                    recommendation=t["diag.net004.rec"],
                )
            )
    return findings


def check_net005_shortage(plan: Plan, lang: str = "kk") -> list[Finding]:
    """NET-005 (ERROR): Insufficient addresses in pool (sum of blocks > pool - reserves)."""
    t = get_strings(lang)
    metrics = compute_metrics(plan)
    have = metrics.pool_size - metrics.reserved_in_pool
    need = sum(s.network.num_addresses for s in plan.subnets) + sum(
        u.required_size for u in plan.unallocated
    )
    if need <= have:
        return []

    lack = need - have
    total_with_res = need + metrics.reserved_in_pool
    min_pool = min_power_of_two(total_with_res)
    new_prefix = max(8, min(plan.base.prefixlen - 1, prefix_for_size(min_pool)))
    new_base = plan.base.supernet(new_prefix=new_prefix)

    affected = [u.department.name for u in plan.unallocated]
    return [
        Finding(
            code="NET-005",
            level="ERROR",
            message=t["diag.net005.msg"].format(
                have=format_int(have),
                need=format_int(need),
                lack=format_int(lack),
            ),
            affected=affected,
            recommendation=t["diag.net005.rec"].format(
                new_base=str(new_base),
                size=format_int(new_base.num_addresses),
            ),
        )
    ]


def check_net006_gateways(plan: Plan, lang: str = "kk") -> list[Finding]:
    """NET-006 (ERROR): Gateway outside subnet or equals network/broadcast address."""
    t = get_strings(lang)
    findings: list[Finding] = []
    for s in plan.subnets:
        reason_key = None
        if s.gateway not in s.network:
            reason_key = "diag.net006.reason_outside"
        elif s.gateway == s.network.network_address:
            reason_key = "diag.net006.reason_network"
        elif s.gateway == s.network.broadcast_address:
            reason_key = "diag.net006.reason_broadcast"

        if reason_key:
            suggest_gw = (
                s.network.broadcast_address - 1
                if plan.gateway_policy == "last"
                else s.network.network_address + 1
            )
            findings.append(
                Finding(
                    code="NET-006",
                    level="ERROR",
                    message=t["diag.net006.msg"].format(
                        dept=s.department,
                        gw=str(s.gateway),
                        reason=t[reason_key],
                    ),
                    affected=[s.department],
                    recommendation=t["diag.net006.rec"].format(suggest=str(suggest_gw)),
                )
            )
    return findings


def check_net007_pool_fill(plan: Plan, lang: str = "kk") -> list[Finding]:
    """NET-007 (SUCCESS/INFO/WARNING): Base network fill thresholds (Section 4.2)."""
    t = get_strings(lang)
    metrics = compute_metrics(plan)
    pct = metrics.fill_pct
    level_label = t[f"an.level.{metrics.fill_level}"]
    if pct <= 70.0:
        sev = "SUCCESS"
        rec = t["diag.success.rec"]
    elif pct <= 85.0:
        sev = "INFO"
        rec = t["diag.net007.rec"]
    else:
        sev = "WARNING"
        rec = t["diag.net007.rec"]

    return [
        Finding(
            code="NET-007",
            level=sev,
            message=t["diag.net007.msg"].format(pct=format_float(pct, 1), level=level_label),
            affected=[],
            recommendation=rec,
        )
    ]


def check_net008_subnet_capacity(plan: Plan, lang: str = "kk") -> list[Finding]:
    """NET-008 (WARNING/ERROR): Free slots < 10% of capacity (WARNING) or devices > capacity (ERROR)."""
    t = get_strings(lang)
    findings: list[Finding] = []
    for s in plan.subnets:
        used = s.hosts if s.hosts > 0 else s.planned_hosts
        if used > s.capacity:
            rec_pref = prefix_for(used)
            findings.append(
                Finding(
                    code="NET-008",
                    level="ERROR",
                    message=t["diag.net008.err_msg"].format(dept=s.department, used=used, cap=s.capacity),
                    affected=[s.department],
                    recommendation=t["diag.net008.err_rec"].format(p=rec_pref),
                )
            )
        else:
            free_ratio = (s.capacity - used) / s.capacity if s.capacity > 0 else 0.0
            if free_ratio < 0.10:
                rec_pref = max(8, s.network.prefixlen - 1)
                findings.append(
                    Finding(
                        code="NET-008",
                        level="WARNING",
                        message=t["diag.net008.warn_msg"].format(dept=s.department, used=used, cap=s.capacity),
                        affected=[s.department],
                        recommendation=t["diag.net008.warn_rec"].format(p=rec_pref),
                    )
                )
    return findings


def check_net009_oversized(plan: Plan, lang: str = "kk") -> list[Finding]:
    """NET-009 (INFO): Subnet is larger than required for H_plan."""
    t = get_strings(lang)
    findings: list[Finding] = []
    for s in plan.subnets:
        needed_prefix = prefix_for(max(1, s.planned_hosts))
        if needed_prefix > s.network.prefixlen:
            findings.append(
                Finding(
                    code="NET-009",
                    level="INFO",
                    message=t["diag.net009.msg"].format(
                        dept=s.department,
                        cur=s.network.prefixlen,
                        rec=needed_prefix,
                    ),
                    affected=[s.department],
                    recommendation=t["diag.net009.rec"],
                )
            )
    return findings


def check_net010_fragmentation(plan: Plan, lang: str = "kk") -> list[Finding]:
    """NET-010 (WARNING): Total free space is enough, but largest contiguous block is too small."""
    t = get_strings(lang)
    metrics = compute_metrics(plan)
    findings: list[Finding] = []
    for u in plan.unallocated:
        if u.reason_code == "block":
            findings.append(
                Finding(
                    code="NET-010",
                    level="WARNING",
                    message=t["diag.net010.msg"].format(
                        free=format_int(metrics.free_outside),
                        largest=format_int(metrics.largest_free_size),
                        need=format_int(u.required_size),
                    ),
                    affected=[u.department.name],
                    recommendation=t["diag.net010.rec"],
                )
            )
    return findings


RULE_REGISTRY: list[Callable[[Plan, str], list[Finding]]] = [
    check_net002_overlaps,
    check_net003_bounds_and_reserves,
    check_net004_duplicate_vlans,
    check_net005_shortage,
    check_net006_gateways,
    check_net007_pool_fill,
    check_net008_subnet_capacity,
    check_net009_oversized,
    check_net010_fragmentation,
]


def run_diagnostics(plan: Plan, lang: str = "kk") -> list[Finding]:
    """Execute all registered rules NET-002..NET-010 and sort ERROR -> WARNING -> INFO -> SUCCESS."""
    t = get_strings(lang)
    findings: list[Finding] = []
    for rule in RULE_REGISTRY:
        findings.extend(rule(plan, lang))

    has_err_or_warn = any(f.level in ("ERROR", "WARNING") for f in findings)
    if not has_err_or_warn:
        findings.append(
            Finding(
                code="OK",
                level="SUCCESS",
                message=t["dg.all_ok"],
                affected=[],
                recommendation=t["diag.success.rec"],
            )
        )

    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.level, 99), f.code))
    return findings


def count_by_level(findings: list[Finding]) -> dict[str, int]:
    """Count findings by ERROR, WARNING, INFO, SUCCESS (FT-17)."""
    counts = {"ERROR": 0, "WARNING": 0, "INFO": 0, "SUCCESS": 0}
    for f in findings:
        if f.level in counts:
            counts[f.level] += 1
    return counts


def diagnose_manual_network(
    base_str: str,
    manual_rows: list[dict],
    reserves: list[ReservedBlock] | None = None,
    lang: str = "kk",
) -> list[Finding]:
    """Audit a manually entered existing network (Section 4.1 & FT-16)."""
    t = get_strings(lang)
    try:
        base = ipaddress.IPv4Network(base_str.strip(), strict=True)
        if not (8 <= base.prefixlen <= 30):
            raise ValueError
    except ValueError:
        return [
            Finding(
                code="NET-001",
                level="ERROR",
                message=t["diag.net001.invalid_ip"],
                affected=[],
                recommendation=t["diag.net001.fix_rec"],
            )
        ]

    subnets: list[Subnet] = []
    input_errors: list[Finding] = []

    for row in manual_rows:
        dept = str(row.get("department", "") or "").strip()
        net_str = str(row.get("subnet", "") or "").strip()
        gw_str = str(row.get("gateway", "") or "").strip()
        if not dept and not net_str:
            continue

        try:
            net = ipaddress.IPv4Network(net_str, strict=True)
            if not (8 <= net.prefixlen <= 30):
                raise ValueError
        except ValueError:
            input_errors.append(
                Finding(
                    code="NET-001",
                    level="ERROR",
                    message=t["diag.net001.invalid_ip"],
                    affected=[dept or net_str],
                    recommendation=t["diag.net001.fix_rec"],
                )
            )
            continue

        try:
            gw = ipaddress.IPv4Address(gw_str)
        except ValueError:
            # Put an out-of-subnet placeholder so NET-006 catches invalid gateway
            gw = ipaddress.IPv4Address("0.0.0.0")

        raw_vlan = row.get("vlan_id")
        vlan_id = None
        if raw_vlan not in (None, "", "None"):
            try:
                vlan_id = int(float(raw_vlan))
            except (ValueError, TypeError):
                vlan_id = None

        hosts = int(float(row.get("hosts", 1) or 1))
        cap = capacity_for_prefix(net.prefixlen)
        subnets.append(
            Subnet(
                department=dept or str(net),
                network=net,
                gateway=gw,
                planned_hosts=hosts,
                capacity=cap,
                vlan_id=vlan_id,
                hosts=hosts,
                reserve_pct=0,
            )
        )

    if input_errors:
        return input_errors

    res_list = list(reserves or [])
    in_base_res = [r for r in res_list if r.network.subnet_of(base)]
    out_base_res = [r for r in res_list if not r.network.subnet_of(base)]

    manual_plan = Plan(
        base=base,
        method="VLSM",
        subnets=subnets,
        unallocated=[],
        reserved=in_base_res,
        free_blocks=[],
        out_of_base_reserves=out_base_res,
    )
    return run_diagnostics(manual_plan, lang=lang)
