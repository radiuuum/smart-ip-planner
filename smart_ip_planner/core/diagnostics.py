"""Diagnostic rules registry NET-001..NET-010 (FT-15, FT-16, FT-17)."""

from __future__ import annotations

import ipaddress
from collections import Counter

from core.calculator import ValidationError, capacity_for_prefix, validate_base_network
from core.models import (
    DepartmentInput,
    DiagnosticFinding,
    ManualSubnetEntry,
    PlanResult,
    ReserveInput,
)


def summarize_severities(findings: list[DiagnosticFinding]) -> dict[str, int]:
    """Count findings across ERROR, WARNING, INFO, SUCCESS (FT-17)."""
    counts = {"ERROR": 0, "WARNING": 0, "INFO": 0, "SUCCESS": 0}
    for f in findings:
        if f.severity in counts:
            counts[f.severity] += 1
    return counts


def diagnose_auto_plan(
    plan: PlanResult,
    departments: list[DepartmentInput],
) -> list[DiagnosticFinding]:
    """Run NET-001..NET-010 diagnostics on an automatically generated plan."""
    findings: list[DiagnosticFinding] = []

    # NET-001: Pool overflow / unallocated departments
    if plan.unallocated:
        findings.append(
            DiagnosticFinding(
                code="NET-001",
                severity="ERROR",
                title_key="diag_net001_title",
                message_key="diag_net001_auto_msg",
                recommendation_key="diag_net001_rec",
                affected_departments=[u.department for u in plan.unallocated],
                params={"count": len(plan.unallocated), "base": plan.config.base_cidr},
            )
        )

    # NET-002: Check for overlapping reserves or any accidental subnet overlap
    reserve_nets: list[tuple[ReserveInput, ipaddress.IPv4Network]] = []
    for r in plan.valid_reserves:
        reserve_nets.append((r, ipaddress.IPv4Network(r.cidr, strict=True)))
    overlap_pairs: list[str] = []
    for i in range(len(reserve_nets)):
        for j in range(i + 1, len(reserve_nets)):
            if reserve_nets[i][1].overlaps(reserve_nets[j][1]):
                overlap_pairs.append(f"{reserve_nets[i][0].cidr} ↔ {reserve_nets[j][0].cidr}")
    if overlap_pairs:
        findings.append(
            DiagnosticFinding(
                code="NET-002",
                severity="WARNING",
                title_key="diag_net002_title",
                message_key="diag_net002_reserve_msg",
                recommendation_key="diag_net002_rec",
                affected_departments=overlap_pairs,
                params={"pairs": ", ".join(overlap_pairs)},
            )
        )

    # NET-003: Manual reserves outside base network or invalid CIDR (Section 3.2)
    if plan.invalid_reserves:
        affected = [f"{r.cidr} ({reason})" for r, reason in plan.invalid_reserves]
        findings.append(
            DiagnosticFinding(
                code="NET-003",
                severity="WARNING",
                title_key="diag_net003_title",
                message_key="diag_net003_msg",
                recommendation_key="diag_net003_rec",
                affected_departments=affected,
                params={"count": len(plan.invalid_reserves), "base": plan.config.base_cidr},
            )
        )

    # NET-004: Capacity deficit (e.g., invalid requirement or planned_hosts > capacity)
    deficit_depts = [
        a.department for a in plan.allocations if a.capacity < a.planned_hosts or a.capacity < a.current_hosts
    ]
    if deficit_depts:
        findings.append(
            DiagnosticFinding(
                code="NET-004",
                severity="ERROR",
                title_key="diag_net004_title",
                message_key="diag_net004_msg",
                recommendation_key="diag_net004_rec",
                affected_departments=deficit_depts,
                params={"count": len(deficit_depts)},
            )
        )

    # NET-005: Duplicate VLAN IDs, out-of-range VLAN IDs (1..4094), or duplicate department names
    vlan_counts = Counter(d.vlan_id for d in departments if d.vlan_id is not None)
    dup_vlans = [v for v, c in vlan_counts.items() if c > 1]
    bad_vlans = [d.department if hasattr(d, "department") else d.name for d in departments if d.vlan_id is not None and not (1 <= d.vlan_id <= 4094)]
    name_counts = Counter(d.name.strip().lower() for d in departments if d.name.strip())
    dup_names = [n for n, c in name_counts.items() if c > 1]
    if dup_vlans or bad_vlans or dup_names:
        affected_005: list[str] = []
        for d in departments:
            if (d.vlan_id in dup_vlans) or (d.vlan_id is not None and not (1 <= d.vlan_id <= 4094)) or (d.name.strip().lower() in dup_names):
                affected_005.append(d.name)
        findings.append(
            DiagnosticFinding(
                code="NET-005",
                severity="ERROR",
                title_key="diag_net005_title",
                message_key="diag_net005_msg",
                recommendation_key="diag_net005_rec",
                affected_departments=affected_005,
                params={"dup_vlans": dup_vlans, "dup_names": dup_names},
            )
        )

    # NET-006: High or critical base pool fill (Section 3.5 thresholds)
    fill = plan.metrics.pool_fill_pct
    if fill > plan.config.threshold_critical:
        findings.append(
            DiagnosticFinding(
                code="NET-006",
                severity="ERROR",
                title_key="diag_net006_title",
                message_key="diag_net006_critical_msg",
                recommendation_key="diag_net006_rec",
                affected_departments=[],
                params={"fill": fill, "threshold": plan.config.threshold_critical},
            )
        )
    elif fill > plan.config.threshold_high:
        findings.append(
            DiagnosticFinding(
                code="NET-006",
                severity="WARNING",
                title_key="diag_net006_title",
                message_key="diag_net006_high_msg",
                recommendation_key="diag_net006_rec",
                affected_departments=[],
                params={"fill": fill, "threshold": plan.config.threshold_high},
            )
        )

    # NET-007: High free-space fragmentation
    if plan.metrics.free_block_count > 1 and plan.metrics.fragmentation_index >= 0.5:
        findings.append(
            DiagnosticFinding(
                code="NET-007",
                severity="WARNING",
                title_key="diag_net007_title",
                message_key="diag_net007_msg",
                recommendation_key="diag_net007_rec",
                affected_departments=[],
                params={
                    "frag": round(plan.metrics.fragmentation_index, 2),
                    "blocks": plan.metrics.free_block_count,
                },
            )
        )

    # NET-008: FLSM overhead or low subnet utilization (< 35%)
    if plan.config.method == "FLSM" and plan.comparison and plan.comparison.vlsm_savings_pct >= 20.0:
        findings.append(
            DiagnosticFinding(
                code="NET-008",
                severity="WARNING",
                title_key="diag_net008_title",
                message_key="diag_net008_flsm_msg",
                recommendation_key="diag_net008_rec",
                affected_departments=[],
                params={"savings": plan.comparison.vlsm_savings_pct},
            )
        )
    elif plan.allocations and plan.metrics.subnet_utilization_pct < 35.0:
        findings.append(
            DiagnosticFinding(
                code="NET-008",
                severity="INFO",
                title_key="diag_net008_title",
                message_key="diag_net008_util_msg",
                recommendation_key="diag_net008_rec",
                affected_departments=[],
                params={"util": plan.metrics.subnet_utilization_pct},
            )
        )

    # NET-009: Zero growth reserve or tight subnets (free_hosts <= 2)
    tight_depts = [
        a.department
        for a in plan.allocations
        if a.growth_reserve_pct == 0 or a.free_hosts <= 2
    ]
    if tight_depts:
        findings.append(
            DiagnosticFinding(
                code="NET-009",
                severity="INFO",
                title_key="diag_net009_title",
                message_key="diag_net009_msg",
                recommendation_key="diag_net009_rec",
                affected_departments=tight_depts,
                params={"count": len(tight_depts)},
            )
        )

    # NET-010: Success if no ERROR findings
    has_errors = any(f.severity == "ERROR" for f in findings)
    if not has_errors and plan.allocations:
        findings.append(
            DiagnosticFinding(
                code="NET-010",
                severity="SUCCESS",
                title_key="diag_net010_title",
                message_key="diag_net010_msg",
                recommendation_key="diag_net010_rec",
                affected_departments=[],
                params={"count": len(plan.allocations)},
            )
        )

    return findings


def diagnose_manual_network(
    base_cidr: str,
    entries: list[ManualSubnetEntry],
    reserves: list[ReserveInput] | None = None,
) -> list[DiagnosticFinding]:
    """Audit an existing manually entered network against NET-001..NET-010 (FT-16)."""
    findings: list[DiagnosticFinding] = []
    reserves = reserves or []

    try:
        base = validate_base_network(base_cidr)
    except ValidationError as exc:
        return [
            DiagnosticFinding(
                code="NET-001",
                severity="ERROR",
                title_key="diag_net001_title",
                message_key="diag_net001_invalid_base_msg",
                recommendation_key="diag_net001_rec",
                affected_departments=[],
                params={"base": base_cidr, "detail": str(exc)},
            )
        ]

    parsed_entries: list[tuple[ManualSubnetEntry, ipaddress.IPv4Network]] = []
    outside_base: list[str] = []
    unsupported_or_deficit: list[str] = []
    tight_depts: list[str] = []
    bad_gateways: list[str] = []

    for entry in entries:
        if not entry.department.strip() and not entry.subnet_cidr.strip():
            continue
        try:
            net = ipaddress.IPv4Network(entry.subnet_cidr.strip(), strict=True)
        except ValueError:
            outside_base.append(f"{entry.department} ({entry.subnet_cidr})")
            continue

        parsed_entries.append((entry, net))
        if not net.subnet_of(base):
            outside_base.append(entry.department)

        if net.prefixlen > 30 or net.prefixlen < 8:
            unsupported_or_deficit.append(f"{entry.department} (/{net.prefixlen})")
        else:
            cap = capacity_for_prefix(net.prefixlen)
            if entry.hosts > cap:
                unsupported_or_deficit.append(f"{entry.department} ({entry.hosts}/{cap})")
            elif cap - entry.hosts <= 2:
                tight_depts.append(entry.department)

        if entry.gateway_ip.strip():
            try:
                gw = ipaddress.IPv4Address(entry.gateway_ip.strip())
                if gw not in net or gw == net.network_address or gw == net.broadcast_address:
                    bad_gateways.append(f"{entry.department} ({entry.gateway_ip})")
            except ValueError:
                bad_gateways.append(f"{entry.department} ({entry.gateway_ip})")

    # NET-001: Subnets outside base or invalid CIDR
    if outside_base:
        findings.append(
            DiagnosticFinding(
                code="NET-001",
                severity="ERROR",
                title_key="diag_net001_title",
                message_key="diag_net001_manual_msg",
                recommendation_key="diag_net001_rec",
                affected_departments=outside_base,
                params={"count": len(outside_base), "base": str(base)},
            )
        )

    # NET-002: Overlapping subnets or subnet overlapping a valid reserve
    overlaps: list[str] = []
    for i in range(len(parsed_entries)):
        for j in range(i + 1, len(parsed_entries)):
            e1, n1 = parsed_entries[i]
            e2, n2 = parsed_entries[j]
            if n1.overlaps(n2):
                overlaps.append(f"{e1.department} ({n1}) ↔ {e2.department} ({n2})")

    # Check reserves
    invalid_res: list[str] = []
    valid_res_nets: list[tuple[ReserveInput, ipaddress.IPv4Network]] = []
    for r in reserves:
        if not r.cidr.strip():
            continue
        try:
            rnet = ipaddress.IPv4Network(r.cidr.strip(), strict=True)
            if not rnet.subnet_of(base):
                invalid_res.append(r.cidr)
            else:
                valid_res_nets.append((r, rnet))
                for e, n in parsed_entries:
                    if n.overlaps(rnet):
                        overlaps.append(f"{e.department} ({n}) ↔ Reserve ({rnet})")
        except ValueError:
            invalid_res.append(r.cidr)

    if overlaps:
        findings.append(
            DiagnosticFinding(
                code="NET-002",
                severity="ERROR",
                title_key="diag_net002_title",
                message_key="diag_net002_manual_msg",
                recommendation_key="diag_net002_rec",
                affected_departments=overlaps,
                params={"count": len(overlaps)},
            )
        )

    # NET-003: Invalid or out-of-base reserves
    if invalid_res:
        findings.append(
            DiagnosticFinding(
                code="NET-003",
                severity="WARNING",
                title_key="diag_net003_title",
                message_key="diag_net003_msg",
                recommendation_key="diag_net003_rec",
                affected_departments=invalid_res,
                params={"count": len(invalid_res), "base": str(base)},
            )
        )

    # NET-004: Insufficient capacity, /31-/32, or invalid gateway
    if unsupported_or_deficit or bad_gateways:
        findings.append(
            DiagnosticFinding(
                code="NET-004",
                severity="ERROR",
                title_key="diag_net004_title",
                message_key="diag_net004_manual_msg",
                recommendation_key="diag_net004_rec",
                affected_departments=unsupported_or_deficit + bad_gateways,
                params={"count": len(unsupported_or_deficit) + len(bad_gateways)},
            )
        )

    # NET-005: Duplicate or invalid VLAN IDs
    vlan_counts = Counter(e.vlan_id for e, _ in parsed_entries if e.vlan_id is not None)
    dup_vlans = [v for v, c in vlan_counts.items() if c > 1]
    bad_vlans = [e.department for e, _ in parsed_entries if e.vlan_id is not None and not (1 <= e.vlan_id <= 4094)]
    if dup_vlans or bad_vlans:
        affected = [e.department for e, _ in parsed_entries if e.vlan_id in dup_vlans or e.department in bad_vlans]
        findings.append(
            DiagnosticFinding(
                code="NET-005",
                severity="ERROR",
                title_key="diag_net005_title",
                message_key="diag_net005_msg",
                recommendation_key="diag_net005_rec",
                affected_departments=affected,
                params={"dup_vlans": dup_vlans},
            )
        )

    # NET-006: Pool fill check
    in_base_nets = [n for _, n in parsed_entries if n.subnet_of(base)] + [rn for _, rn in valid_res_nets]
    collapsed_used = list(ipaddress.collapse_addresses(in_base_nets)) if in_base_nets else []
    used_ips = sum(n.num_addresses for n in collapsed_used)
    fill_pct = round((used_ips / base.num_addresses) * 100.0, 2) if base.num_addresses else 0.0
    if fill_pct > 95.0:
        findings.append(
            DiagnosticFinding(
                code="NET-006",
                severity="ERROR",
                title_key="diag_net006_title",
                message_key="diag_net006_critical_msg",
                recommendation_key="diag_net006_rec",
                params={"fill": fill_pct, "threshold": 95.0},
            )
        )
    elif fill_pct > 85.0:
        findings.append(
            DiagnosticFinding(
                code="NET-006",
                severity="WARNING",
                title_key="diag_net006_title",
                message_key="diag_net006_high_msg",
                recommendation_key="diag_net006_rec",
                params={"fill": fill_pct, "threshold": 85.0},
            )
        )

    # NET-009: Tight subnets
    if tight_depts:
        findings.append(
            DiagnosticFinding(
                code="NET-009",
                severity="INFO",
                title_key="diag_net009_title",
                message_key="diag_net009_msg",
                recommendation_key="diag_net009_rec",
                affected_departments=tight_depts,
                params={"count": len(tight_depts)},
            )
        )

    # NET-010: Clean manual audit
    if not any(f.severity == "ERROR" for f in findings) and parsed_entries:
        findings.append(
            DiagnosticFinding(
                code="NET-010",
                severity="SUCCESS",
                title_key="diag_net010_title",
                message_key="diag_net010_msg",
                recommendation_key="diag_net010_rec",
                params={"count": len(parsed_entries)},
            )
        )

    return findings
