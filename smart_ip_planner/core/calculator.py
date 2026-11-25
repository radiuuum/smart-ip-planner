"""Exact integer subnet calculations and CIDR validation (Section 3.1 & FT-01)."""

from __future__ import annotations

import ipaddress

MIN_BASE_PREFIX = 8
MAX_BASE_PREFIX = 30
MIN_RESERVE_PCT = 0
MAX_RESERVE_PCT = 100


class ValidationError(ValueError):
    """Raised when input CIDR or parameters violate TZ constraints."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_base_network(base_cidr: str) -> ipaddress.IPv4Network:
    """Validate base IPv4 network strictly per FT-01 (/8../30, no host bits)."""
    raw = (base_cidr or "").strip()
    if not raw or "/" not in raw:
        raise ValidationError("invalid_cidr_format", f"Invalid CIDR format: '{raw}'")

    try:
        net = ipaddress.IPv4Network(raw, strict=True)
    except ValueError as exc:
        try:
            loose = ipaddress.IPv4Network(raw, strict=False)
        except ValueError:
            raise ValidationError("invalid_cidr_format", f"Invalid IPv4 CIDR: '{raw}'") from exc
        raise ValidationError(
            "host_bits_set",
            f"Address '{raw}' has host bits set; network address is '{loose}'",
        ) from exc

    if not (MIN_BASE_PREFIX <= net.prefixlen <= MAX_BASE_PREFIX):
        raise ValidationError(
            "prefix_out_of_range",
            f"Base prefix /{net.prefixlen} is outside allowed range /{MIN_BASE_PREFIX}.. /{MAX_BASE_PREFIX}",
        )
    return net


def parse_reserve_network(cidr: str) -> ipaddress.IPv4Network:
    """Parse a manual reserve strictly as an IPv4 network."""
    raw = (cidr or "").strip()
    if not raw or "/" not in raw:
        raise ValidationError("invalid_reserve_cidr", f"Invalid reserve CIDR: '{raw}'")
    try:
        return ipaddress.IPv4Network(raw, strict=True)
    except ValueError as exc:
        raise ValidationError("invalid_reserve_cidr", f"Invalid strict IPv4 reserve CIDR: '{raw}'") from exc


def planned_hosts(hosts: int, reserve_pct: int) -> int:
    """Compute ceil(hosts * (1 + reserve_pct / 100)) strictly in integers (Section 3.1)."""
    if hosts < 1:
        raise ValidationError("invalid_hosts", f"Device count must be >= 1, got {hosts}")
    if not (MIN_RESERVE_PCT <= reserve_pct <= MAX_RESERVE_PCT):
        raise ValidationError(
            "invalid_reserve_pct",
            f"Growth reserve must be between {MIN_RESERVE_PCT}% and {MAX_RESERVE_PCT}%, got {reserve_pct}%",
        )
    return (hosts * (100 + reserve_pct) + 99) // 100


def prefix_for(h_plan: int) -> int:
    """Compute CIDR prefix for h_plan devices with 3 service addresses (network, broadcast, gateway).

    Formula from Section 3.1:
        n = ceil(log2(h_plan + 3)) = (h_plan + 2).bit_length()
        CIDR = 32 - n
    Subnets /31 and /32 are never produced because h_plan >= 1 => n >= 2 => CIDR <= 30.
    """
    if h_plan < 1:
        raise ValidationError("invalid_hosts", f"Planned hosts must be >= 1, got {h_plan}")
    host_bits = (h_plan + 2).bit_length()
    prefix = 32 - host_bits
    if prefix < MIN_BASE_PREFIX:
        raise ValidationError("subnet_too_large", f"Required prefix /{prefix} exceeds IPv4 limit /{MIN_BASE_PREFIX}")
    return prefix


def capacity_for_prefix(prefix: int) -> int:
    """Usable device capacity for a LAN subnet with 3 service addresses (2^n - 3)."""
    if not (MIN_BASE_PREFIX <= prefix <= MAX_BASE_PREFIX):
        raise ValidationError("unsupported_prefix", f"Unsupported LAN prefix /{prefix}")
    return (1 << (32 - prefix)) - 3


def min_power_of_two(value: int) -> int:
    """Return smallest power of 2 >= value (minimum 4 for /30)."""
    if value <= 4:
        return 4
    return 1 << (value - 1).bit_length()


def prefix_for_block_size(block_size: int) -> int:
    """Return CIDR prefix corresponding to a power-of-two block size."""
    size = min_power_of_two(block_size)
    return 32 - (size.bit_length() - 1)
