"""Exact integer subnet sizing and strict input validation (Section 3.1 & NET-001)."""

from __future__ import annotations

import ipaddress
from typing import Any

from core.models import Department, Finding, ReservedBlock
from strings import get_strings


def planned_hosts(h: int, r: int) -> int:
    """Compute ceil(h * (1 + r/100)) strictly in integers (Section 3.1).

    Avoids float rounding errors such as 100 * 1.1 == 110.00000000000001 -> 111.
    """
    return (h * (100 + r) + 99) // 100


def prefix_for(h_plan: int) -> int:
    """Compute CIDR prefix for h_plan devices with 3 service addresses (Section 3.1)."""
    return 32 - (h_plan + 2).bit_length()


def capacity_for_prefix(prefix: int) -> int:
    """Return usable device capacity (2^(32 - prefix) - 3) for LAN subnets /8../30."""
    return (1 << (32 - prefix)) - 3


def min_power_of_two(n: int) -> int:
    """Smallest power of 2 >= n (minimum 4 for /30)."""
    if n <= 4:
        return 4
    return 1 << (n - 1).bit_length()


def prefix_for_size(size: int) -> int:
    """Prefix corresponding to a power-of-two block size."""
    p2 = min_power_of_two(size)
    return 32 - (p2.bit_length() - 1)


def validate_inputs(
    base_str: str,
    departments_raw: list[dict[str, Any]],
    reserves_raw: list[dict[str, Any]] | None = None,
    lang: str = "kk",
) -> tuple[ipaddress.IPv4Network | None, list[Department], list[ReservedBlock], list[Finding]]:
    """Validate all inputs against NET-001 rules (Section 4.2 & Appendix B).

    If any NET-001 finding is returned, calculation MUST NOT proceed.
    """
    t = get_strings(lang)
    findings: list[Finding] = []
    base_net: ipaddress.IPv4Network | None = None

    # 1. Base network CIDR check
    raw_base = (base_str or "").strip()
    if not raw_base or "/" not in raw_base:
        findings.append(
            Finding(
                code="NET-001",
                level="ERROR",
                message=t["diag.net001.invalid_ip"],
                affected=[],
                recommendation=t["diag.net001.fix_rec"],
            )
        )
    else:
        try:
            net = ipaddress.IPv4Network(raw_base, strict=True)
            if not (8 <= net.prefixlen <= 30):
                findings.append(
                    Finding(
                        code="NET-001",
                        level="ERROR",
                        message=t["diag.net001.prefix_range"],
                        affected=[],
                        recommendation=t["diag.net001.fix_rec"],
                    )
                )
            else:
                base_net = net
        except ValueError:
            try:
                loose = ipaddress.IPv4Network(raw_base, strict=False)
                if not (8 <= loose.prefixlen <= 30):
                    findings.append(
                        Finding(
                            code="NET-001",
                            level="ERROR",
                            message=t["diag.net001.prefix_range"],
                            affected=[],
                            recommendation=t["diag.net001.fix_rec"],
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            code="NET-001",
                            level="ERROR",
                            message=t["diag.net001.host_bits"].format(given=raw_base),
                            affected=[],
                            recommendation=t["diag.net001.host_bits_rec"].format(suggest=str(loose)),
                        )
                    )
            except ValueError:
                findings.append(
                    Finding(
                        code="NET-001",
                        level="ERROR",
                        message=t["diag.net001.invalid_ip"],
                        affected=[],
                        recommendation=t["diag.net001.fix_rec"],
                    )
                )

    # 2. Departments check
    departments: list[Department] = []
    if not departments_raw:
        findings.append(
            Finding(
                code="NET-001",
                level="ERROR",
                message=t["diag.net001.empty_depts"],
                affected=[],
                recommendation=t["diag.net001.empty_depts_rec"],
            )
        )
    else:
        for row in departments_raw:
            name = str(row.get("name", "") or "").strip()
            if not name:
                findings.append(
                    Finding(
                        code="NET-001",
                        level="ERROR",
                        message=t["diag.net001.empty_name"],
                        affected=[],
                        recommendation=t["diag.net001.empty_name_rec"],
                    )
                )
                continue

            # Hosts must be positive integer
            raw_hosts = row.get("hosts")
            hosts_val: int | None = None
            if isinstance(raw_hosts, bool):
                hosts_val = None
            elif isinstance(raw_hosts, int):
                hosts_val = raw_hosts
            elif isinstance(raw_hosts, float) and raw_hosts.is_integer():
                hosts_val = int(raw_hosts)
            elif isinstance(raw_hosts, str) and raw_hosts.strip().lstrip("-").isdigit():
                hosts_val = int(raw_hosts.strip())

            if hosts_val is None or hosts_val <= 0:
                findings.append(
                    Finding(
                        code="NET-001",
                        level="ERROR",
                        message=t["diag.net001.bad_hosts"].format(dept=name),
                        affected=[name],
                        recommendation=t["diag.net001.fix_rec"],
                    )
                )
                continue

            # Reserve must be integer 0..100
            raw_res = row.get("reserve_pct", 0)
            res_val: int | None = None
            if isinstance(raw_res, bool):
                res_val = None
            elif isinstance(raw_res, int):
                res_val = raw_res
            elif isinstance(raw_res, float) and raw_res.is_integer():
                res_val = int(raw_res)
            elif isinstance(raw_res, str) and raw_res.strip().lstrip("-").isdigit():
                res_val = int(raw_res.strip())

            if res_val is None or not (0 <= res_val <= 100):
                findings.append(
                    Finding(
                        code="NET-001",
                        level="ERROR",
                        message=t["diag.net001.bad_reserve"],
                        affected=[name],
                        recommendation=t["diag.net001.fix_rec"],
                    )
                )
                continue

            # Optional VLAN ID in 1..4094
            raw_vlan = row.get("vlan_id")
            vlan_val: int | None = None
            if raw_vlan not in (None, "", "None"):
                try:
                    if isinstance(raw_vlan, float) and not raw_vlan.is_integer():
                        raise ValueError
                    vlan_val = int(raw_vlan)
                except (ValueError, TypeError):
                    vlan_val = -1
                if not (1 <= vlan_val <= 4094):
                    findings.append(
                        Finding(
                            code="NET-001",
                            level="ERROR",
                            message=t["diag.net001.bad_vlan"],
                            affected=[name],
                            recommendation=t["diag.net001.fix_rec"],
                        )
                    )
                    continue

            departments.append(
                Department(name=name, vlan_id=vlan_val, hosts=hosts_val, reserve_pct=res_val)
            )

    # 3. Reserves check
    reserves: list[ReservedBlock] = []
    for rrow in reserves_raw or []:
        rcidr = str(rrow.get("network", "") or "").strip()
        if not rcidr:
            continue
        rnote = str(rrow.get("note", "") or "").strip()
        try:
            rnet = ipaddress.IPv4Network(rcidr, strict=True)
            reserves.append(ReservedBlock(network=rnet, note=rnote))
        except ValueError:
            try:
                loose = ipaddress.IPv4Network(rcidr, strict=False)
                findings.append(
                    Finding(
                        code="NET-001",
                        level="ERROR",
                        message=t["diag.net001.host_bits"].format(given=rcidr),
                        affected=[],
                        recommendation=t["diag.net001.host_bits_rec"].format(suggest=str(loose)),
                    )
                )
            except ValueError:
                findings.append(
                    Finding(
                        code="NET-001",
                        level="ERROR",
                        message=t["diag.net001.invalid_ip"],
                        affected=[],
                        recommendation=t["diag.net001.fix_rec"],
                    )
                )

    return base_net, departments, reserves, findings
