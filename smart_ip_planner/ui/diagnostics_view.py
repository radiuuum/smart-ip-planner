"""Section 6.4: Желіні диагностикалау view (counters, findings, manual check, Scenario A/B preview)."""

from __future__ import annotations

import ipaddress

import pandas as pd
import streamlit as st

from core.diagnostics import count_by_level, diagnose_manual_network
from core.models import Department, ReservedBlock
from core.proposals import propose_scenario_a, propose_scenario_b
from strings import format_int, get_strings
from ui.planner_view import recompute_session_plan

BADGE_STYLES = {
    "ERROR": "background:#fee2e2;color:#991b1b;border:1px solid #fca5a5;",
    "WARNING": "background:#fef3c7;color:#92400e;border:1px solid #fcd34d;",
    "INFO": "background:#dbeafe;color:#1e40af;border:1px solid #93c5fd;",
    "SUCCESS": "background:#dcfce7;color:#166534;border:1px solid #86efac;",
}


def _render_findings(findings, lang: str) -> None:
    t = get_strings(lang)
    counts = count_by_level(findings)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(t["dg.errors"], counts["ERROR"])
    c2.metric(t["dg.warnings"], counts["WARNING"])
    c3.metric(t["dg.info"], counts["INFO"])
    c4.metric(t["dg.success"], counts["SUCCESS"])

    for f in findings:
        style = BADGE_STYLES.get(f.level, "")
        level_text = t[f"level.{f.level.lower()}"]
        affected = ", ".join(f.affected) if f.affected else "—"
        st.markdown(
            f"""
            <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px 16px;margin-bottom:8px;">
                <span style="{style}padding:2px 10px;border-radius:999px;font-size:0.78rem;font-weight:600;">
                    {f.code} · {level_text}
                </span>
                <div style="margin-top:6px;font-size:0.95rem;color:#0f172a;">{f.message}</div>
                <div style="margin-top:4px;font-size:0.85rem;color:#475569;">
                    <b>{t['dg.affected']}:</b> {affected}
                </div>
                <div style="margin-top:2px;font-size:0.85rem;color:#475569;">
                    <b>{t['dg.recommendation']}:</b> {f.recommendation}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_diagnostics_view(lang: str = "kk") -> None:
    """Render Желіні диагностикалау page (Section 6.4)."""
    t = get_strings(lang)
    plan = st.session_state.get("plan")
    findings = st.session_state.get("findings", [])

    if plan is None and not findings:
        st.info(t["empty.no_plan"])
    else:
        _render_findings(findings, lang)

    # Auto-fix proposals: Scenario A and Scenario B with preview (Section 5.1-5.3 & 6.4)
    if plan is not None:
        st.divider()
        st.subheader(t["dg.preview"])
        st.caption(t["dg.apply_hint"])

        proj = st.session_state["project"]
        depts = [Department.from_dict(d) for d in proj.get("departments", [])]
        reserves = [
            ReservedBlock(network=ipaddress.IPv4Network(r["network"], strict=True), note=r.get("note", ""))
            for r in proj.get("reserved", [])
            if r.get("network")
        ]

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"**{t['dg.scenario_a']}**")
            if st.button(t["dg.preview_btn_a"], use_container_width=True):
                st.session_state["proposal_preview"] = propose_scenario_a(plan, depts, reserves)

        with col_b:
            st.markdown(f"**{t['dg.scenario_b']}**")
            b1, b2 = st.columns(2)
            with b1:
                new_name = st.text_input(t["col.department"], value="Жаңа бөлім", key="sc_b_name")
                new_hosts = st.number_input(t["col.devices"], min_value=1, max_value=100000, value=20, step=1, key="sc_b_hosts")
            with b2:
                new_vlan = st.number_input(t["col.vlan"], min_value=0, max_value=4094, value=90, step=1, key="sc_b_vlan")
                new_res = st.number_input(
                    t["col.reserve"], min_value=0, max_value=100, value=int(proj.get("default_reserve", 20)), step=5, key="sc_b_res"
                )
            if st.button(t["dg.preview_btn_b"], use_container_width=True):
                new_dept = Department(
                    name=new_name.strip() or "Жаңа бөлім",
                    vlan_id=None if new_vlan == 0 else int(new_vlan),
                    hosts=int(new_hosts),
                    reserve_pct=int(new_res),
                )
                st.session_state["proposal_preview"] = (
                    propose_scenario_b(plan, new_dept, reserves, lang=lang),
                    new_dept,
                )

        # Render active preview with Қолдану / Бас тарту buttons
        preview_obj = st.session_state.get("proposal_preview")
        if preview_obj is not None:
            if isinstance(preview_obj, tuple):
                preview, new_dept = preview_obj
            else:
                preview, new_dept = preview_obj, None

            st.info(t["dg.apply_hint"])
            if preview.scenario == "A":
                if preview.success and preview.new_plan is not None:
                    st.warning(t["dg.check_adjacent"])
                    st.success(
                        t["dg.before_after"].format(
                            old=str(preview.old_base),
                            old_size=format_int(preview.old_base.num_addresses),
                            new=str(preview.new_base),
                            new_size=format_int(preview.new_base.num_addresses),
                        )
                    )
                    ap1, ap2 = st.columns(2)
                    with ap1:
                        if st.button(t["btn.apply"], type="primary", use_container_width=True, key="apply_a"):
                            st.session_state["project"]["base"] = str(preview.new_base)
                            st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
                            st.session_state["proposal_preview"] = None
                            recompute_session_plan(lang=lang)
                            st.rerun()
                    with ap2:
                        if st.button(t["btn.cancel"], use_container_width=True, key="cancel_a"):
                            st.session_state["proposal_preview"] = None
                            st.rerun()
                else:
                    st.error(t["plan.incomplete"])
            else:
                if preview.success and preview.added_subnet is not None and new_dept is not None:
                    st.success(
                        t["dg.added_ok"].format(
                            dept=new_dept.name,
                            net=str(preview.added_subnet.network),
                            count=len(plan.subnets),
                        )
                    )
                    ap1, ap2 = st.columns(2)
                    with ap1:
                        if st.button(t["btn.apply"], type="primary", use_container_width=True, key="apply_b"):
                            st.session_state["project"]["departments"].append(new_dept.to_dict())
                            st.session_state["plan"] = preview.new_plan
                            st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
                            st.session_state["proposal_preview"] = None
                            recompute_session_plan(lang=lang)
                            st.rerun()
                    with ap2:
                        if st.button(t["btn.cancel"], use_container_width=True, key="cancel_b"):
                            st.session_state["proposal_preview"] = None
                            st.rerun()
                else:
                    st.error(t["dg.added_fail"])
                    if preview.findings:
                        _render_findings(preview.findings, lang)

    # Manual check of existing network (Section 6.4 & FT-16)
    st.divider()
    st.subheader(t["dg.manual_title"])
    st.caption(t["dg.manual_hint"])
    manual_base = st.text_input(
        t["planner.base_network"],
        value=st.session_state["project"].get("base", "192.168.1.0/24"),
        key="manual_check_base",
    )
    init_rows = (
        [
            {
                "department": s.department,
                "vlan_id": s.vlan_id,
                "subnet": str(s.network),
                "gateway": str(s.gateway),
                "hosts": s.hosts,
            }
            for s in plan.subnets
        ]
        if plan and plan.subnets
        else [
            {"department": "IT", "vlan_id": 10, "subnet": "192.168.1.0/26", "gateway": "192.168.1.1", "hosts": 40},
            {"department": "Office", "vlan_id": 20, "subnet": "192.168.1.32/27", "gateway": "192.168.1.33", "hosts": 20},
        ]
    )
    manual_df = st.data_editor(
        pd.DataFrame(init_rows),
        num_rows="dynamic",
        use_container_width=True,
        key="manual_check_df",
        column_config={
            "department": st.column_config.TextColumn(t["col.department"]),
            "vlan_id": st.column_config.NumberColumn(t["col.vlan"], step=1),
            "subnet": st.column_config.TextColumn(t["col.subnet"]),
            "gateway": st.column_config.TextColumn(t["col.gateway"]),
            "hosts": st.column_config.NumberColumn(t["col.devices"], step=1),
        },
    )
    if st.button(t["dg.run"], type="primary"):
        rows_list = manual_df.to_dict(orient="records")
        manual_findings = diagnose_manual_network(manual_base, rows_list, lang=lang)
        _render_findings(manual_findings, lang)
