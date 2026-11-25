"""Plotly visualizations for Smart IP Planner (FT-12, FT-13, FT-14)."""

from __future__ import annotations

import ipaddress
from typing import Callable

import plotly.graph_objects as go

from core.models import PlanResult

SUBNET_PALETTE = [
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


def build_address_space_map(plan: PlanResult, t: Callable[[str], str]) -> go.Figure:
    """Horizontal stacked bar representing subnets, reserves, and free blocks in address order (FT-12)."""
    segments: list[tuple[int, int, str, str, str, str]] = []

    for idx, a in enumerate(plan.allocations):
        net = ipaddress.IPv4Network(a.subnet_cidr, strict=True)
        color = SUBNET_PALETTE[idx % len(SUBNET_PALETTE)]
        segments.append(
            (
                int(net.network_address),
                net.num_addresses,
                a.department,
                a.subnet_cidr,
                color,
                f"<b>{a.department}</b><br>{a.subnet_cidr} ({net.num_addresses} IP)<br>"
                f"{t('col_gateway')}: {a.gateway_ip}<br>"
                f"{t('col_planned')}: {a.planned_hosts} / {a.capacity}",
            )
        )

    for res in plan.valid_reserves:
        rnet = ipaddress.IPv4Network(res.cidr, strict=True)
        label = res.note or t("type_manual_reserve")
        segments.append(
            (
                int(rnet.network_address),
                rnet.num_addresses,
                f"{t('type_manual_reserve')}: {res.cidr}",
                res.cidr,
                "#f59e0b",
                f"<b>{t('type_manual_reserve')}</b><br>{res.cidr} ({rnet.num_addresses} IP)<br>{label}",
            )
        )

    for cidr in plan.free_blocks:
        fnet = ipaddress.IPv4Network(cidr, strict=True)
        segments.append(
            (
                int(fnet.network_address),
                fnet.num_addresses,
                f"{t('type_free_block')}: {cidr}",
                cidr,
                "#cbd5e1",
                f"<b>{t('type_free_block')}</b><br>{cidr} ({fnet.num_addresses} IP)",
            )
        )

    segments.sort(key=lambda item: item[0])

    fig = go.Figure()
    pool_size = max(plan.metrics.pool_size, 1)
    for _start, size, name, cidr, color, hover in segments:
        pct = size / pool_size * 100.0
        text_label = f"{cidr}" if pct >= 7.5 else ""
        text_color = "#1e293b" if color == "#cbd5e1" else "#ffffff"
        fig.add_trace(
            go.Bar(
                x=[size],
                y=[plan.config.base_cidr],
                name=name,
                orientation="h",
                marker=dict(color=color, line=dict(color="#ffffff", width=1.2)),
                text=[text_label],
                textposition="inside",
                insidetextanchor="middle",
                textfont=dict(color=text_color, size=11),
                hovertemplate=hover + "<extra></extra>",
            )
        )

    fig.update_layout(
        barmode="stack",
        height=200,
        margin=dict(l=16, r=16, t=24, b=36),
        xaxis=dict(title="IP", showgrid=True, gridcolor="#e2e8f0"),
        yaxis=dict(title="", showticklabels=True),
        legend=dict(orientation="h", yanchor="top", y=-0.35, xanchor="left", x=0),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def build_hosts_vs_capacity_chart(plan: PlanResult, t: Callable[[str], str]) -> go.Figure:
    """Grouped bar chart comparing current devices, planned devices, and subnet capacity (FT-13)."""
    depts = [a.department for a in plan.allocations]
    current = [a.current_hosts for a in plan.allocations]
    planned = [a.planned_hosts for a in plan.allocations]
    capacity = [a.capacity for a in plan.allocations]

    fig = go.Figure()
    fig.add_trace(go.Bar(name=t("col_hosts"), x=depts, y=current, marker_color="#0d9488"))
    fig.add_trace(go.Bar(name=t("col_planned"), x=depts, y=planned, marker_color="#2563eb"))
    fig.add_trace(go.Bar(name=t("col_capacity"), x=depts, y=capacity, marker_color="#94a3b8"))

    fig.update_layout(
        barmode="group",
        height=340,
        margin=dict(l=20, r=20, t=20, b=40),
        yaxis=dict(title="IP", gridcolor="#e2e8f0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def build_method_comparison_chart(plan: PlanResult, t: Callable[[str], str]) -> go.Figure:
    """Bar chart comparing VLSM vs FLSM required addresses and minimum pool size (FT-14)."""
    comp = plan.comparison
    fig = go.Figure()
    if comp is None:
        return fig

    fig.add_trace(
        go.Bar(
            name="VLSM",
            x=[t("comp_vlsm_required").replace("VLSM ", ""), t("comp_vlsm_min_pool").replace("VLSM ", "")],
            y=[comp.vlsm_required_addresses, comp.vlsm_min_pool_size],
            marker_color="#2563eb",
            text=[str(comp.vlsm_required_addresses), f"{comp.vlsm_min_pool_size} (/{comp.vlsm_min_pool_prefix})"],
            textposition="auto",
        )
    )
    fig.add_trace(
        go.Bar(
            name="FLSM",
            x=[t("comp_vlsm_required").replace("VLSM ", ""), t("comp_vlsm_min_pool").replace("VLSM ", "")],
            y=[comp.flsm_required_addresses, comp.flsm_min_pool_size],
            marker_color="#f97316",
            text=[str(comp.flsm_required_addresses), f"{comp.flsm_min_pool_size} (/{comp.flsm_min_pool_prefix})"],
            textposition="auto",
        )
    )

    fig.update_layout(
        barmode="group",
        height=300,
        margin=dict(l=20, r=20, t=24, b=30),
        yaxis=dict(title="IP", gridcolor="#e2e8f0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig
