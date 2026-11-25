"""Plotly charts for Smart IP Planner (Sections 6.3 & 6.5)."""

from __future__ import annotations

import plotly.graph_objects as go

from core.models import MethodComparison, Plan
from strings import format_int, get_strings

PALETTE = [
    "#2563eb",
    "#0d9488",
    "#7c3aed",
    "#ea580c",
    "#0284c7",
    "#16a34a",
    "#db2777",
    "#4f46e5",
    "#ca8a04",
    "#0891b2",
]


def address_space_map(plan: Plan, lang: str = "kk") -> go.Figure:
    """Horizontal stacked bar: subnets, reserves, and free blocks (gray) in address order."""
    t = get_strings(lang)
    segments: list[tuple[int, int, str, str, str, str]] = []

    for idx, s in enumerate(plan.subnets):
        color = PALETTE[idx % len(PALETTE)]
        segments.append(
            (
                int(s.network.network_address),
                s.network.num_addresses,
                s.department,
                str(s.network),
                color,
                f"<b>{s.department}</b><br>{s.network} ({format_int(s.network.num_addresses)} IP)<br>"
                f"{t['col.gateway']}: {s.gateway}<br>"
                f"{t['col.planned']}: {s.planned_hosts} / {s.capacity}",
            )
        )

    for r in plan.reserved:
        label = r.note or t["map.reserved"]
        segments.append(
            (
                int(r.network.network_address),
                r.network.num_addresses,
                f"{t['map.reserved']}: {r.network}",
                str(r.network),
                "#f59e0b",
                f"<b>{t['map.reserved']}</b><br>{r.network} ({format_int(r.network.num_addresses)} IP)<br>{label}",
            )
        )

    for fblk in plan.free_blocks:
        segments.append(
            (
                int(fblk.network_address),
                fblk.num_addresses,
                f"{t['map.free']}: {fblk}",
                str(fblk),
                "#cbd5e1",
                f"<b>{t['map.free']}</b><br>{fblk} ({format_int(fblk.num_addresses)} IP)",
            )
        )

    segments.sort(key=lambda x: x[0])
    total = max(plan.base.num_addresses, 1)

    fig = go.Figure()
    for _start, size, name, cidr, color, hover in segments:
        show_text = cidr if (size / total) >= 0.08 else ""
        txt_color = "#1e293b" if color == "#cbd5e1" else "#ffffff"
        fig.add_trace(
            go.Bar(
                x=[size],
                y=[str(plan.base)],
                name=name,
                orientation="h",
                marker=dict(color=color, line=dict(color="#ffffff", width=1.2)),
                text=[show_text],
                textposition="inside",
                insidetextanchor="middle",
                textfont=dict(color=txt_color, size=11),
                hovertemplate=hover + "<extra></extra>",
            )
        )

    fig.update_layout(
        barmode="stack",
        height=190,
        margin=dict(l=16, r=16, t=20, b=40),
        xaxis=dict(title="IP", showgrid=True, gridcolor="#e2e8f0"),
        yaxis=dict(title=""),
        legend=dict(orientation="h", yanchor="top", y=-0.35, xanchor="left", x=0),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def devices_vs_capacity_chart(plan: Plan, lang: str = "kk") -> go.Figure:
    """Grouped bar chart: devices vs subnet capacity per department (Section 6.5)."""
    t = get_strings(lang)
    names = [s.department for s in plan.subnets]
    fig = go.Figure()
    fig.add_trace(go.Bar(name=t["an.devices"], x=names, y=[s.hosts for s in plan.subnets], marker_color="#0d9488"))
    fig.add_trace(go.Bar(name=t["col.planned"], x=names, y=[s.planned_hosts for s in plan.subnets], marker_color="#2563eb"))
    fig.add_trace(go.Bar(name=t["an.capacity"], x=names, y=[s.capacity for s in plan.subnets], marker_color="#94a3b8"))
    fig.update_layout(
        barmode="group",
        height=330,
        margin=dict(l=16, r=16, t=24, b=36),
        yaxis=dict(title="IP", gridcolor="#e2e8f0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def vlsm_flsm_comparison_chart(comp: MethodComparison, lang: str = "kk") -> go.Figure:
    """Comparison bar chart for VLSM vs FLSM (Section 6.5)."""
    t = get_strings(lang)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="VLSM",
            x=[t["an.allocated"], t["an.min_pool"]],
            y=[comp.a_vlsm, comp.vlsm_min_pool_size],
            marker_color="#2563eb",
            text=[format_int(comp.a_vlsm), f"{format_int(comp.vlsm_min_pool_size)} (/{comp.vlsm_min_pool_prefix})"],
            textposition="auto",
        )
    )
    fig.add_trace(
        go.Bar(
            name="FLSM",
            x=[t["an.allocated"], t["an.min_pool"]],
            y=[comp.a_flsm, comp.flsm_min_pool_size],
            marker_color="#f97316",
            text=[format_int(comp.a_flsm), f"{format_int(comp.flsm_min_pool_size)} (/{comp.flsm_min_pool_prefix})"],
            textposition="auto",
        )
    )
    fig.update_layout(
        barmode="group",
        height=300,
        margin=dict(l=16, r=16, t=24, b=30),
        yaxis=dict(title="IP", gridcolor="#e2e8f0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig
