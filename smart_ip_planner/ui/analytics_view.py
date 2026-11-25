"""Section 6.5: Желіні талдау view (metrics cards, Plotly charts, VLSM vs FLSM comparison)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from strings import format_float, format_int, format_pct, get_strings
from ui.charts import (
    address_space_map,
    devices_vs_capacity_chart,
    vlsm_flsm_comparison_chart,
)


def render_analytics_view(lang: str = "kk") -> None:
    """Render Желіні талдау page (Section 6.5)."""
    t = get_strings(lang)
    plan = st.session_state.get("plan")
    metrics = st.session_state.get("metrics")
    comp = st.session_state.get("comparison")

    if plan is None or metrics is None or comp is None:
        st.info(t["empty.no_plan"])
        return

    # Metric cards (Section 6.5)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(t["an.pool_size"], format_int(metrics.pool_size))
    m2.metric(t["an.allocated"], format_int(metrics.allocated))
    m3.metric(
        t["an.fill"],
        format_pct(metrics.fill_pct, 2),
        delta=t[f"an.level.{metrics.fill_level}"],
        delta_color="off",
    )
    m4.metric(t["an.utilization"], format_pct(metrics.utilization_pct, 1))

    m5, m6, m7, m8 = st.columns(4)
    m5.metric(t["an.free_outside"], format_int(metrics.free_outside))
    m6.metric(
        t["an.largest_free"],
        format_int(metrics.largest_free_size),
        delta=str(metrics.largest_free_network) if metrics.largest_free_network else "—",
        delta_color="off",
    )
    m7.metric(t["an.free_blocks"], str(metrics.free_blocks_count))
    m8.metric(t["an.frag_index"], format_float(metrics.fragmentation_index, 3))

    # Address space map
    st.subheader(t["map.title"])
    st.plotly_chart(address_space_map(plan, lang=lang), use_container_width=True)

    # Devices vs Capacity & VLSM vs FLSM
    c1, c2 = st.columns(2)
    with c1:
        st.subheader(t["an.chart_devices"])
        if plan.subnets:
            st.plotly_chart(devices_vs_capacity_chart(plan, lang=lang), use_container_width=True)
    with c2:
        st.subheader(t["an.compare"])
        st.plotly_chart(vlsm_flsm_comparison_chart(comp, lang=lang), use_container_width=True)
        if comp.savings_addresses > 0:
            st.info(t["an.recommend_vlsm"])

        comp_df = pd.DataFrame(
            [
                {t["an.metric"]: t["an.savings"], t["an.value"]: format_int(comp.savings_addresses)},
                {t["an.metric"]: t["an.reduction"], t["an.value"]: format_pct(comp.savings_pct, 2)},
                {
                    t["an.metric"]: f"{t['an.min_pool']} (VLSM)",
                    t["an.value"]: f"{format_int(comp.vlsm_min_pool_size)} (/{comp.vlsm_min_pool_prefix})",
                },
                {
                    t["an.metric"]: f"{t['an.min_pool']} (FLSM)",
                    t["an.value"]: f"{format_int(comp.flsm_min_pool_size)} (/{comp.flsm_min_pool_prefix})",
                },
            ]
        )
        st.dataframe(comp_df, use_container_width=True, hide_index=True)
