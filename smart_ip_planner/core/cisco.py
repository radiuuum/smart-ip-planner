"""Bonus FT-29: Cisco IOS configuration generator (VLAN, SVI, Gateways, DHCP)."""

from __future__ import annotations

import re

from core.models import PlanResult


def _safe_cisco_name(name: str) -> str:
    """Convert department name to a clean ASCII-safe Cisco identifier."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip())
    cleaned = cleaned.strip("_")
    return cleaned[:32] if cleaned else "VLAN_SEG"


def generate_cisco_config(
    plan: PlanResult,
    hostname: str = "CORE-SW1",
    include_dhcp: bool = True,
) -> str:
    """Generate Cisco IOS VLAN, SVI, gateway, and optional DHCP pool configuration."""
    lines: list[str] = [
        "! =========================================================",
        f"! Smart IP Planner - Cisco IOS Configuration ({plan.config.method})",
        f"! Base Network: {plan.config.base_cidr}",
        f"! Gateway Policy: {plan.config.gateway_policy}",
        "! =========================================================",
        "enable",
        "configure terminal",
        f"hostname {_safe_cisco_name(hostname)}",
        "ip routing",
        "!",
    ]

    auto_vlan = 100
    used_vlans = {a.vlan_id for a in plan.allocations if a.vlan_id is not None}

    vlan_assignments: list[tuple[int, object]] = []
    for alloc in plan.allocations:
        if alloc.vlan_id is not None:
            vid = alloc.vlan_id
        else:
            while auto_vlan in used_vlans:
                auto_vlan += 10
            vid = auto_vlan
            used_vlans.add(vid)
        vlan_assignments.append((vid, alloc))

    # 1. VLAN definitions
    lines.append("! --- 1. VLAN Definitions ---")
    for vid, alloc in vlan_assignments:
        lines.append(f"vlan {vid}")
        lines.append(f" name {_safe_cisco_name(alloc.department)}")
        lines.append("!")

    # 2. SVI (Layer 3 interfaces & gateways)
    lines.append("! --- 2. SVI Interfaces (Gateways) ---")
    for vid, alloc in vlan_assignments:
        lines.append(f"interface Vlan{vid}")
        lines.append(f" description {alloc.department} ({alloc.subnet_cidr})")
        lines.append(f" ip address {alloc.gateway_ip} {alloc.netmask}")
        lines.append(" no shutdown")
        lines.append("!")

    # 3. Optional DHCP pools
    if include_dhcp:
        lines.append("! --- 3. DHCP Pools ---")
        for vid, alloc in vlan_assignments:
            lines.append(f"ip dhcp excluded-address {alloc.gateway_ip}")
        lines.append("!")
        for vid, alloc in vlan_assignments:
            pool_name = f"POOL_VLAN{vid}_{_safe_cisco_name(alloc.department)[:16]}"
            lines.append(f"ip dhcp pool {pool_name}")
            lines.append(f" network {alloc.network_address} {alloc.netmask}")
            lines.append(f" default-router {alloc.gateway_ip}")
            lines.append(" dns-server 8.8.8.8 1.1.1.1")
            lines.append("!")

    lines.append("end")
    lines.append("write memory")
    return "\n".join(lines)
