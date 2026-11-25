"""Export services: 4-sheet Excel (FT-26), UTF-8-SIG CSV, and Cisco IOS config (FT-29)."""

from __future__ import annotations

import csv
import io
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from core.models import Finding, MethodComparison, Plan, PlanMetrics
from strings import format_float, format_int, get_strings


def export_csv(plan: Plan, lang: str = "kk") -> bytes:
    """Export addressing plan table to UTF-8 with BOM CSV (Section 6.1)."""
    t = get_strings(lang)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            t["col.department"],
            t["col.vlan"],
            t["col.subnet"],
            t["col.prefix"],
            t["col.mask"],
            t["col.first_ip"],
            t["col.last_ip"],
            t["col.broadcast"],
            t["col.gateway"],
            t["col.capacity"],
            t["col.planned"],
            t["col.free_slots"],
            t["col.status"],
        ]
    )
    for s in plan.subnets:
        writer.writerow(
            [
                s.department,
                "" if s.vlan_id is None else s.vlan_id,
                str(s.network),
                f"/{s.network.prefixlen}",
                str(s.network.netmask),
                str(s.first_host),
                str(s.last_host),
                str(s.network.broadcast_address),
                str(s.gateway),
                s.capacity,
                s.planned_hosts,
                s.free_slots,
                t["status.allocated"],
            ]
        )
    for u in plan.unallocated:
        reason = t["plan.reason_space"] if u.reason_code == "space" else t["plan.reason_block"]
        writer.writerow(
            [
                u.department.name,
                "" if u.department.vlan_id is None else u.department.vlan_id,
                "—",
                f"/{u.required_prefix}",
                "—",
                "—",
                "—",
                "—",
                "—",
                0,
                u.planned_hosts,
                0,
                f"{t['status.unallocated']}: {reason}",
            ]
        )
    return buf.getvalue().encode("utf-8-sig")


def _style_worksheet(ws) -> None:
    header_fill = PatternFill(start_color="1E3A5F", end_color="1E3A5F", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    body_font = Font(name="Calibri", size=10, color="111827")
    zebra = PatternFill(start_color="F3F6FA", end_color="F3F6FA", fill_type="solid")
    side = Side(border_style="thin", color="D1D5DB")
    border = Border(left=side, right=side, top=side, bottom=side)

    for col in range(1, ws.max_column + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    for r in range(2, ws.max_row + 1):
        for col in range(1, ws.max_column + 1):
            cell = ws.cell(row=r, column=col)
            cell.font = body_font
            cell.border = border
            if r % 2 == 0 and cell.fill.fill_type is None:
                cell.fill = zebra
            if isinstance(cell.value, (int, float)):
                cell.alignment = Alignment(horizontal="right", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

    for col in range(1, ws.max_column + 1):
        max_len = max(
            (len(str(ws.cell(row=r, column=col).value or "")) for r in range(1, ws.max_row + 1)),
            default=10,
        )
        ws.column_dimensions[get_column_letter(col)].width = min(max(max_len + 4, 12), 48)

    ws.freeze_panes = "A2"


def export_excel(
    plan: Plan,
    metrics: PlanMetrics,
    comparison: MethodComparison,
    findings: list[Finding],
    lang: str = "kk",
) -> bytes:
    """Export plan to 4-sheet Excel workbook: Жоспар, Талдау, Диагностика, Салыстыру (Appendix A.5)."""
    t = get_strings(lang)
    wb = Workbook()

    # Sheet 1: Жоспар
    ws1 = wb.active
    ws1.title = t["xl.sheet_plan"]
    ws1.append(
        [
            t["col.department"],
            t["col.vlan"],
            t["col.subnet"],
            t["col.prefix"],
            t["col.mask"],
            t["col.first_ip"],
            t["col.last_ip"],
            t["col.broadcast"],
            t["col.gateway"],
            t["col.capacity"],
            t["col.planned"],
            t["col.free_slots"],
            t["col.status"],
        ]
    )
    for s in plan.subnets:
        ws1.append(
            [
                s.department,
                "" if s.vlan_id is None else s.vlan_id,
                str(s.network),
                f"/{s.network.prefixlen}",
                str(s.network.netmask),
                str(s.first_host),
                str(s.last_host),
                str(s.network.broadcast_address),
                str(s.gateway),
                s.capacity,
                s.planned_hosts,
                s.free_slots,
                t["status.allocated"],
            ]
        )
    for u in plan.unallocated:
        reason = t["plan.reason_space"] if u.reason_code == "space" else t["plan.reason_block"]
        ws1.append(
            [
                u.department.name,
                "" if u.department.vlan_id is None else u.department.vlan_id,
                "—",
                f"/{u.required_prefix}",
                "—",
                "—",
                "—",
                "—",
                "—",
                0,
                u.planned_hosts,
                0,
                f"{t['status.unallocated']}: {reason}",
            ]
        )
    _style_worksheet(ws1)

    # Sheet 2: Талдау
    ws2 = wb.create_sheet(title=t["xl.sheet_analytics"])
    ws2.append([t["an.metric"], t["an.value"]])
    ws2.append([t["planner.base_network"], str(plan.base)])
    ws2.append([t["planner.method"], plan.method])
    ws2.append([t["an.pool_size"], format_int(metrics.pool_size)])
    ws2.append([t["an.allocated"], format_int(metrics.allocated)])
    ws2.append([t["an.free_outside"], format_int(metrics.free_outside)])
    ws2.append([t["an.fill"], f"{format_float(metrics.fill_pct, 2)} % ({t[f'an.level.{metrics.fill_level}']})"])
    ws2.append([t["an.utilization"], f"{format_float(metrics.utilization_pct, 2)} %"])
    ws2.append(
        [
            t["an.largest_free"],
            f"{format_int(metrics.largest_free_size)} ({metrics.largest_free_network or '—'})",
        ]
    )
    ws2.append([t["an.free_blocks"], metrics.free_blocks_count])
    ws2.append([t["an.frag_index"], format_float(metrics.fragmentation_index, 4)])
    _style_worksheet(ws2)

    # Sheet 3: Диагностика
    ws3 = wb.create_sheet(title=t["xl.sheet_diag"])
    ws3.append(["Код", t["col.status"], t["plan.title"], t["dg.affected"], t["dg.recommendation"]])
    fills = {"ERROR": "FEE2E2", "WARNING": "FEF3C7", "INFO": "DBEAFE", "SUCCESS": "DCFCE7"}
    for f in findings:
        ws3.append([f.code, t[f"level.{f.level.lower()}"], f.message, ", ".join(f.affected) or "—", f.recommendation])
        ws3.cell(row=ws3.max_row, column=2).fill = PatternFill(
            start_color=fills.get(f.level, "FFFFFF"),
            end_color=fills.get(f.level, "FFFFFF"),
            fill_type="solid",
        )
    _style_worksheet(ws3)

    # Sheet 4: Салыстыру
    ws4 = wb.create_sheet(title=t["xl.sheet_compare"])
    ws4.append([t["an.metric"], "VLSM", "FLSM"])
    ws4.append([t["an.allocated"], format_int(comparison.a_vlsm), format_int(comparison.a_flsm)])
    ws4.append(
        [
            t["an.min_pool"],
            f"{format_int(comparison.vlsm_min_pool_size)} (/{comparison.vlsm_min_pool_prefix})",
            f"{format_int(comparison.flsm_min_pool_size)} (/{comparison.flsm_min_pool_prefix})",
        ]
    )
    ws4.append([t["an.savings"], format_int(comparison.savings_addresses), "—"])
    ws4.append([t["an.reduction"], f"{format_float(comparison.savings_pct, 2)} %", "—"])
    _style_worksheet(ws4)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _ascii_id(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_")
    return cleaned[:30] if cleaned else "SEG"


def export_cisco_config(plan: Plan, hostname: str = "CORE-SW1") -> str:
    """Generate Cisco IOS VLAN, SVI, and gateway template configuration (Bonus FT-29)."""
    lines = [
        "! Smart IP Planner — Cisco IOS Configuration",
        f"! Base network: {plan.base} | Method: {plan.method}",
        "enable",
        "configure terminal",
        f"hostname {_ascii_id(hostname)}",
        "ip routing",
        "!",
    ]
    used_vlans = {s.vlan_id for s in plan.subnets if s.vlan_id is not None}
    next_vid = 100
    pairs: list[tuple[int, object]] = []
    for s in plan.subnets:
        if s.vlan_id is not None:
            vid = s.vlan_id
        else:
            while next_vid in used_vlans:
                next_vid += 10
            vid = next_vid
            used_vlans.add(vid)
        pairs.append((vid, s))

    for vid, s in pairs:
        lines.extend([f"vlan {vid}", f" name {_ascii_id(s.department)}", "!"])

    for vid, s in pairs:
        lines.extend(
            [
                f"interface Vlan{vid}",
                f" description {s.department} ({s.network})",
                f" ip address {s.gateway} {s.network.netmask}",
                " no shutdown",
                "!",
            ]
        )

    lines.extend(["end", "write memory"])
    return "\n".join(lines)
