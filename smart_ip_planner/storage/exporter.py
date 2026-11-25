"""JSON import/export (FT-25), Excel 4-sheet export, and CSV export (FT-26)."""

from __future__ import annotations

import csv
import io
import json
from typing import Callable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from core.models import (
    DepartmentInput,
    DiagnosticFinding,
    PlanResult,
    PlannerConfig,
    ReserveInput,
)


def export_project_json(
    name: str,
    description: str,
    config: PlannerConfig,
    departments: list[DepartmentInput],
    reserves: list[ReserveInput],
) -> str:
    """Serialize a full project definition to formatted UTF-8 JSON (FT-25)."""
    payload = {
        "schema_version": "1.0",
        "name": name,
        "description": description,
        "config": config.to_dict(),
        "departments": [d.to_dict() for d in departments],
        "reserves": [r.to_dict() for r in reserves],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def import_project_json(raw_json: str) -> tuple[str, str, PlannerConfig, list[DepartmentInput], list[ReserveInput]]:
    """Deserialize and validate a project JSON payload (FT-25)."""
    data = json.loads(raw_json)
    if not isinstance(data, dict) or "config" not in data or "departments" not in data:
        raise ValueError("Invalid project JSON: missing 'config' or 'departments'")

    name = str(data.get("name", "Импортталған жоба")).strip() or "Импортталған жоба"
    description = str(data.get("description", "")).strip()
    config = PlannerConfig.from_dict(data["config"])
    departments = [DepartmentInput.from_dict(d) for d in data.get("departments", [])]
    reserves = [ReserveInput.from_dict(r) for r in data.get("reserves", [])]
    return name, description, config, departments, reserves


def export_plan_csv(plan: PlanResult, t: Callable[[str], str]) -> bytes:
    """Export the addressing plan table to UTF-8 with BOM CSV (opens cleanly in Excel on macOS/Windows)."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            t("col_department"),
            t("col_vlan"),
            t("col_subnet"),
            t("col_prefix"),
            t("col_mask"),
            t("col_first_ip"),
            t("col_last_ip"),
            t("col_broadcast"),
            t("col_gateway"),
            t("col_capacity"),
            t("col_planned"),
            t("col_free"),
            t("col_status"),
        ]
    )

    for a in plan.allocations:
        writer.writerow(
            [
                a.department,
                "" if a.vlan_id is None else a.vlan_id,
                a.subnet_cidr,
                f"/{a.prefix}",
                a.netmask,
                a.first_host_ip,
                a.last_host_ip,
                a.broadcast_address,
                a.gateway_ip,
                a.capacity,
                a.planned_hosts,
                a.free_hosts,
                t("status_allocated"),
            ]
        )

    for u in plan.unallocated:
        writer.writerow(
            [
                u.department,
                "" if u.vlan_id is None else u.vlan_id,
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
                f"{t('status_unallocated')}: {u.reason_detail}",
            ]
        )

    return output.getvalue().encode("utf-8-sig")


def _style_sheet(ws, header_row: int = 1) -> None:
    """Apply clean corporate styling and auto-fit column widths."""
    header_fill = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    body_font = Font(name="Calibri", size=10, color="1F2937")
    zebra_fill = PatternFill(start_color="F3F6FA", end_color="F3F6FA", fill_type="solid")
    thin_side = Side(border_style="thin", color="D1D5DB")
    border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    for col_idx in range(1, ws.max_column + 1):
        cell = ws.cell(row=header_row, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    for row_idx in range(header_row + 1, ws.max_row + 1):
        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = body_font
            cell.border = border
            if (row_idx - header_row) % 2 == 0 and cell.fill.fill_type is None:
                cell.fill = zebra_fill
            if isinstance(cell.value, (int, float)):
                cell.alignment = Alignment(horizontal="right", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

    for col_idx in range(1, ws.max_column + 1):
        max_len = 0
        for row_idx in range(1, ws.max_row + 1):
            val = ws.cell(row=row_idx, column=col_idx).value
            if val is not None:
                max_len = max(max_len, len(str(val)))
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max(max_len + 4, 12), 48)

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)


def export_plan_excel(
    project_name: str,
    plan: PlanResult,
    findings: list[DiagnosticFinding],
    t: Callable[[str], str],
    format_finding: Callable[[DiagnosticFinding], tuple[str, str, str]],
) -> bytes:
    """Export complete addressing plan to a 4-sheet Excel workbook (FT-26)."""
    wb = Workbook()

    # Sheet 1: Addressing Plan
    ws1 = wb.active
    ws1.title = t("sheet_plan")[:31]
    ws1.append(
        [
            t("col_department"),
            t("col_vlan"),
            t("col_subnet"),
            t("col_prefix"),
            t("col_mask"),
            t("col_first_ip"),
            t("col_last_ip"),
            t("col_broadcast"),
            t("col_gateway"),
            t("col_capacity"),
            t("col_planned"),
            t("col_free"),
            t("col_status"),
        ]
    )
    for a in plan.allocations:
        ws1.append(
            [
                a.department,
                "" if a.vlan_id is None else a.vlan_id,
                a.subnet_cidr,
                f"/{a.prefix}",
                a.netmask,
                a.first_host_ip,
                a.last_host_ip,
                a.broadcast_address,
                a.gateway_ip,
                a.capacity,
                a.planned_hosts,
                a.free_hosts,
                t("status_allocated"),
            ]
        )
    for u in plan.unallocated:
        ws1.append(
            [
                u.department,
                "" if u.vlan_id is None else u.vlan_id,
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
                f"{t('status_unallocated')}: {u.reason_detail}",
            ]
        )
    _style_sheet(ws1)

    # Sheet 2: Analytics & VLSM vs FLSM Comparison
    ws2 = wb.create_sheet(title=t("sheet_analytics")[:31])
    ws2.append([t("col_metric"), t("col_value")])
    m = plan.metrics
    ws2.append([t("project_name_label"), project_name])
    ws2.append([t("base_cidr_label"), plan.config.base_cidr])
    ws2.append([t("method_label"), plan.config.method])
    ws2.append([t("metric_pool_size"), m.pool_size])
    ws2.append([t("metric_allocated"), m.allocated_addresses])
    ws2.append([t("metric_reserved"), m.reserved_addresses_in_pool])
    ws2.append([t("metric_pool_fill"), f"{m.pool_fill_pct:.2f}%"])
    ws2.append([t("metric_utilization"), f"{m.subnet_utilization_pct:.2f}%"])
    ws2.append([t("metric_largest_free"), f"{m.largest_free_block} ({m.largest_free_cidr or '—'})"])
    ws2.append([t("metric_free_blocks"), m.free_block_count])
    ws2.append([t("metric_fragmentation"), f"{m.fragmentation_index:.4f}"])
    if plan.comparison:
        c = plan.comparison
        ws2.append(["—", "—"])
        ws2.append([t("comp_vlsm_required"), c.vlsm_required_addresses])
        ws2.append([t("comp_flsm_required"), c.flsm_required_addresses])
        ws2.append([t("comp_vlsm_min_pool"), f"{c.vlsm_min_pool_size} (/{c.vlsm_min_pool_prefix})"])
        ws2.append([t("comp_flsm_min_pool"), f"{c.flsm_min_pool_size} (/{c.flsm_min_pool_prefix})"])
        ws2.append([t("comp_savings"), f"{c.vlsm_savings_pct:.2f}%"])
    _style_sheet(ws2)

    # Sheet 3: Diagnostics (NET-001..NET-010)
    ws3 = wb.create_sheet(title=t("sheet_diagnostics")[:31])
    ws3.append([t("col_code"), t("col_severity"), t("col_message"), t("col_affected"), t("col_recommendation")])
    sev_colors = {
        "ERROR": "FEE2E2",
        "WARNING": "FEF3C7",
        "INFO": "DBEAFE",
        "SUCCESS": "DCFCE7",
    }
    for f in findings:
        _title, msg, rec = format_finding(f)
        ws3.append([f.code, f.severity, msg, ", ".join(f.affected_departments) or "—", rec])
        row_num = ws3.max_row
        fill_hex = sev_colors.get(f.severity)
        if fill_hex:
            ws3.cell(row=row_num, column=2).fill = PatternFill(
                start_color=fill_hex, end_color=fill_hex, fill_type="solid"
            )
    _style_sheet(ws3)

    # Sheet 4: Free Blocks & Manual Reserves
    ws4 = wb.create_sheet(title=t("sheet_free_reserves")[:31])
    ws4.append([t("col_block_type"), "CIDR", t("col_note")])
    for cidr in plan.free_blocks:
        ws4.append([t("type_free_block"), cidr, t("note_available_free")])
    for res in plan.valid_reserves:
        ws4.append([t("type_manual_reserve"), res.cidr, res.note or "—"])
    for res, reason in plan.invalid_reserves:
        ws4.append([t("type_invalid_reserve"), res.cidr, f"{res.note} ({reason})".strip()])
    _style_sheet(ws4)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
