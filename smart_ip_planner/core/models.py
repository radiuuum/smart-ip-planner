"""Domain data models for Smart IP Planner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

AllocationMethod = Literal["VLSM", "FLSM"]
GatewayPolicy = Literal["first", "last"]
SeverityLevel = Literal["ERROR", "WARNING", "INFO", "SUCCESS"]
GrowthVerdict = Literal["sufficient", "expand_in_place", "relocate", "full_replan"]


@dataclass(frozen=True)
class DepartmentInput:
    """Single department / VLAN requirement."""

    name: str
    hosts: int
    growth_reserve_pct: int = 20
    vlan_id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "vlan_id": self.vlan_id,
            "hosts": int(self.hosts),
            "growth_reserve_pct": int(self.growth_reserve_pct),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DepartmentInput":
        raw_vlan = data.get("vlan_id")
        vlan_id = None if raw_vlan in (None, "", "None") else int(raw_vlan)
        return cls(
            name=str(data.get("name", "")).strip(),
            hosts=int(data.get("hosts", 1)),
            growth_reserve_pct=int(data.get("growth_reserve_pct", 0)),
            vlan_id=vlan_id,
        )


@dataclass(frozen=True)
class ReserveInput:
    """Manual CIDR reservation inside (or checked against) the base network."""

    cidr: str
    note: str = ""

    def to_dict(self) -> dict:
        return {"cidr": self.cidr.strip(), "note": self.note.strip()}

    @classmethod
    def from_dict(cls, data: dict) -> "ReserveInput":
        return cls(
            cidr=str(data.get("cidr", "")).strip(),
            note=str(data.get("note", "")).strip(),
        )


@dataclass(frozen=True)
class PlannerConfig:
    """Global planning configuration."""

    base_cidr: str
    method: AllocationMethod = "VLSM"
    gateway_policy: GatewayPolicy = "first"
    default_reserve_pct: int = 20
    threshold_moderate: float = 70.0
    threshold_high: float = 85.0
    threshold_critical: float = 95.0

    def to_dict(self) -> dict:
        return {
            "base_cidr": self.base_cidr.strip(),
            "method": self.method,
            "gateway_policy": self.gateway_policy,
            "default_reserve_pct": int(self.default_reserve_pct),
            "threshold_moderate": float(self.threshold_moderate),
            "threshold_high": float(self.threshold_high),
            "threshold_critical": float(self.threshold_critical),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlannerConfig":
        return cls(
            base_cidr=str(data.get("base_cidr", "192.168.0.0/22")).strip(),
            method="FLSM" if str(data.get("method", "VLSM")).upper() == "FLSM" else "VLSM",
            gateway_policy="last" if str(data.get("gateway_policy", "first")).lower() == "last" else "first",
            default_reserve_pct=int(data.get("default_reserve_pct", 20)),
            threshold_moderate=float(data.get("threshold_moderate", 70.0)),
            threshold_high=float(data.get("threshold_high", 85.0)),
            threshold_critical=float(data.get("threshold_critical", 95.0)),
        )


@dataclass(frozen=True)
class SubnetAllocation:
    """Successfully allocated subnet for a department."""

    department: str
    vlan_id: Optional[int]
    subnet_cidr: str
    network_address: str
    prefix: int
    netmask: str
    first_host_ip: str
    last_host_ip: str
    broadcast_address: str
    gateway_ip: str
    block_size: int
    capacity: int
    current_hosts: int
    growth_reserve_pct: int
    planned_hosts: int
    free_hosts: int
    status: str = "allocated"


@dataclass(frozen=True)
class UnallocatedDepartment:
    """Department that could not be allocated."""

    department: str
    vlan_id: Optional[int]
    current_hosts: int
    growth_reserve_pct: int
    planned_hosts: int
    required_prefix: int
    required_block_size: int
    reason_code: Literal["insufficient_space", "no_contiguous_block", "invalid_requirement"]
    reason_detail: str


@dataclass(frozen=True)
class PlanMetrics:
    """Quantitative metrics defined in section 3.5."""

    pool_size: int
    allocated_addresses: int
    reserved_addresses_in_pool: int
    pool_fill_pct: float
    pool_fill_level: Literal["sufficient", "moderate", "high", "critical"]
    subnet_utilization_pct: float
    total_free_addresses: int
    largest_free_block: int
    largest_free_cidr: Optional[str]
    free_block_count: int
    fragmentation_index: float


@dataclass(frozen=True)
class MethodComparison:
    """Automatic VLSM vs FLSM comparison (FT-14)."""

    vlsm_required_addresses: int
    flsm_required_addresses: int
    vlsm_min_pool_size: int
    vlsm_min_pool_prefix: int
    flsm_min_pool_size: int
    flsm_min_pool_prefix: int
    vlsm_savings_pct: float
    vlsm_allocated_count: int
    flsm_allocated_count: int
    vlsm_complete: bool
    flsm_complete: bool
    vlsm_pool_fill_pct: float
    flsm_pool_fill_pct: float
    vlsm_utilization_pct: float
    flsm_utilization_pct: float


@dataclass(frozen=True)
class PlanResult:
    """Complete result of an allocation run."""

    config: PlannerConfig
    allocations: list[SubnetAllocation]
    unallocated: list[UnallocatedDepartment]
    free_blocks: list[str]
    valid_reserves: list[ReserveInput]
    invalid_reserves: list[tuple[ReserveInput, str]]
    is_complete: bool
    metrics: PlanMetrics
    comparison: Optional[MethodComparison] = None


@dataclass(frozen=True)
class DiagnosticFinding:
    """Single rule finding from NET-001..NET-010."""

    code: str
    severity: SeverityLevel
    title_key: str
    message_key: str
    recommendation_key: str
    affected_departments: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ManualSubnetEntry:
    """Existing subnet entry for manual network audit mode (FT-16)."""

    department: str
    subnet_cidr: str
    hosts: int
    vlan_id: Optional[int] = None
    gateway_ip: str = ""


@dataclass(frozen=True)
class AutoFixPreview:
    """Preview for Scenario A or Scenario B before user confirmation (FT-18..FT-20)."""

    scenario: Literal["A_expand_base", "B_add_department"]
    success: bool
    summary_key: str
    old_base_cidr: str
    new_base_cidr: str
    preview_plan: Optional[PlanResult]
    added_allocation: Optional[SubnetAllocation] = None
    unchanged_count: int = 0
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GrowthItemResult:
    """Growth impact verdict for a single department (FT-22)."""

    department: str
    vlan_id: Optional[int]
    current_subnet: str
    current_capacity: int
    current_hosts: int
    projected_hosts: int
    required_prefix: int
    verdict: GrowthVerdict
    proposed_subnet: Optional[str]
    devices_renumbered: int


@dataclass(frozen=True)
class GrowthSimulationResult:
    """Overall growth modeling report (FT-21..FT-23)."""

    items: list[GrowthItemResult]
    subnets_renumbered: int
    devices_renumbered: int
    full_replan_required: bool
    counts_by_verdict: dict[str, int]
