"""Domain models strictly following Section 7.2 of the TZ."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Literal, Optional

MethodType = Literal["VLSM", "FLSM"]
GatewayPolicy = Literal["first", "last"]
SeverityLevel = Literal["ERROR", "WARNING", "INFO", "SUCCESS"]
GrowthVerdict = Literal["ok", "inplace", "move", "replan"]


@dataclass(frozen=True)
class Department:
    """Department requirement (Section 7.2)."""

    name: str
    vlan_id: Optional[int]
    hosts: int
    reserve_pct: int = 20

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "vlan_id": self.vlan_id,
            "hosts": int(self.hosts),
            "reserve_pct": int(self.reserve_pct),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Department":
        raw_vlan = data.get("vlan_id")
        vlan_id = None if raw_vlan in (None, "", "None") else int(raw_vlan)
        return cls(
            name=str(data.get("name", "")).strip(),
            vlan_id=vlan_id,
            hosts=int(data.get("hosts", 0)),
            reserve_pct=int(data.get("reserve_pct", 0)),
        )


@dataclass(frozen=True)
class ReservedBlock:
    """Manual reserved CIDR block (Section 7.2)."""

    network: ipaddress.IPv4Network
    note: str = ""

    def to_dict(self) -> dict:
        return {"network": str(self.network), "note": self.note}


@dataclass(frozen=True)
class Subnet:
    """Allocated subnet record (Section 7.2)."""

    department: str
    network: ipaddress.IPv4Network
    gateway: ipaddress.IPv4Address
    planned_hosts: int
    capacity: int
    vlan_id: Optional[int] = None
    hosts: int = 0
    reserve_pct: int = 0

    @property
    def first_host(self) -> ipaddress.IPv4Address:
        first_usable = self.network.network_address + 1
        return first_usable + 1 if self.gateway == first_usable else first_usable

    @property
    def last_host(self) -> ipaddress.IPv4Address:
        last_usable = self.network.broadcast_address - 1
        return last_usable - 1 if self.gateway == last_usable else last_usable

    @property
    def free_slots(self) -> int:
        return self.capacity - self.planned_hosts


@dataclass(frozen=True)
class UnallocatedItem:
    """Unallocated department with reason code."""

    department: Department
    planned_hosts: int
    required_prefix: int
    required_size: int
    reason_code: Literal["space", "block"]


@dataclass(frozen=True)
class Plan:
    """Addressing plan output (Section 7.2)."""

    base: ipaddress.IPv4Network
    method: MethodType
    subnets: list[Subnet]
    unallocated: list[UnallocatedItem]
    reserved: list[ReservedBlock]
    free_blocks: list[ipaddress.IPv4Network] = field(default_factory=list)
    out_of_base_reserves: list[ReservedBlock] = field(default_factory=list)
    gateway_policy: GatewayPolicy = "first"

    @property
    def is_complete(self) -> bool:
        return len(self.unallocated) == 0


@dataclass(frozen=True)
class Finding:
    """Diagnostic finding (Section 4.1 & 7.2)."""

    code: str
    level: SeverityLevel
    message: str
    affected: list[str]
    recommendation: str


@dataclass(frozen=True)
class PlanMetrics:
    """Metrics from Section 3.5."""

    pool_size: int
    allocated: int
    reserved_in_pool: int
    free_outside: int
    fill_pct: float
    fill_level: Literal["sufficient", "moderate", "high", "critical"]
    utilization_pct: float
    largest_free_size: int
    largest_free_network: Optional[ipaddress.IPv4Network]
    free_blocks_count: int
    fragmentation_index: float


@dataclass(frozen=True)
class MethodComparison:
    """Automatic VLSM vs FLSM comparison (Section 3.5 & FT-14)."""

    a_vlsm: int
    a_flsm: int
    savings_addresses: int
    savings_pct: float
    vlsm_min_pool_size: int
    vlsm_min_pool_prefix: int
    flsm_min_pool_size: int
    flsm_min_pool_prefix: int
    vlsm_complete: bool
    flsm_complete: bool


@dataclass(frozen=True)
class PlanDiff:
    """Plan diff result from Section 5.4."""

    changed_subnets: list[tuple[str, str, str]]  # (department, old_cidr, new_cidr)
    affected_devices: int

    @property
    def changed_count(self) -> int:
        return len(self.changed_subnets)


@dataclass(frozen=True)
class ProposalPreview:
    """Preview for Scenario A or Scenario B (Section 5.1-5.3)."""

    scenario: Literal["A", "B"]
    success: bool
    old_base: ipaddress.IPv4Network
    new_base: ipaddress.IPv4Network
    new_plan: Optional[Plan]
    diff: Optional[PlanDiff]
    added_subnet: Optional[Subnet] = None
    findings: list[Finding] = field(default_factory=list)


@dataclass(frozen=True)
class GrowthRow:
    """Growth verdict for one department (Section 5.5)."""

    department: str
    vlan_id: Optional[int]
    current_network: ipaddress.IPv4Network
    current_hosts: int
    new_hosts: int
    capacity: int
    deficit: int
    verdict: GrowthVerdict
    proposed_network: Optional[ipaddress.IPv4Network]
    message: str


@dataclass(frozen=True)
class GrowthReport:
    """Complete growth modeling result (Section 5.5)."""

    rows: list[GrowthRow]
    need_expand_count: int
    total_count: int
    total_deficit: int
    diff: PlanDiff
    full_replan_needed: bool
    new_plan: Optional[Plan]
