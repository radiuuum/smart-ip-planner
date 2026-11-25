"""Section 6.3: IP-жоспарлау view (inputs, VLSM/FLSM calculation, 13-column plan table, space map)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from core.allocator import allocate_plan
from core.analytics import compare_methods, compute_metrics
from core.diagnostics import run_diagnostics
from core.sizing import validate_inputs
from services.storage import ProjectStorage, load_demo_projects
from strings import get_strings
from ui.charts import address_space_map


def _df_to_departments(df: pd.DataFrame, default_reserve: int) -> list[dict]:
    rows: list[dict] = []
    if df is None or df.empty:
        return rows
    for _, r in df.iterrows():
        name = str(r.get("name", "") or "").strip()
        raw_hosts = r.get("hosts")
        raw_vlan = r.get("vlan_id")
        raw_res = r.get("reserve_pct")
        if not name and pd.isna(raw_hosts):
            continue
        vlan = None
        if pd.notna(raw_vlan) and str(raw_vlan).strip() != "":
            try:
                vlan = int(float(raw_vlan))
            except (ValueError, TypeError):
                vlan = raw_vlan
        hosts = raw_hosts if pd.notna(raw_hosts) else 0
        reserve = int(float(raw_res)) if pd.notna(raw_res) else int(default_reserve)
        rows.append(
            {
                "name": name,
                "vlan_id": vlan,
                "hosts": hosts,
                "reserve_pct": reserve,
            }
        )
    return rows


def _df_to_reserves(df: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    if df is None or df.empty:
        return rows
    for _, r in df.iterrows():
        net = str(r.get("network", "") or "").strip()
        if not net:
            continue
        rows.append({"network": net, "note": str(r.get("note", "") or "").strip()})
    return rows


def recompute_session_plan(lang: str = "kk") -> bool:
    """Validate inputs (NET-001) and compute plan, metrics, comparison, and diagnostics."""
    proj = st.session_state["project"]
    base_net, depts, reserves, net001_errors = validate_inputs(
        proj.get("base", ""),
        proj.get("departments", []),
        proj.get("reserved", []),
        lang=lang,
    )
    st.session_state["input_errors"] = net001_errors
    if net001_errors or base_net is None:
        st.session_state["plan"] = None
        st.session_state["metrics"] = None
        st.session_state["comparison"] = None
        st.session_state["findings"] = net001_errors
        return False

    plan = allocate_plan(
        base=base_net,
        departments=depts,
        reserved=reserves,
        method=proj.get("method", "VLSM"),
        gateway_policy=proj.get("gateway_policy", "first"),
    )
    st.session_state["plan"] = plan
    st.session_state["metrics"] = compute_metrics(plan)
    st.session_state["comparison"] = compare_methods(
        base=base_net,
        departments=depts,
        reserved=reserves,
        gateway_policy=proj.get("gateway_policy", "first"),
    )
    st.session_state["findings"] = run_diagnostics(plan, lang=lang)
    st.session_state["proposal_preview"] = None
    return True


def render_planner_view(storage: ProjectStorage, lang: str = "kk") -> None:
    """Render the IP-жоспарлау page (Section 6.3)."""
    t = get_strings(lang)
    proj = st.session_state["project"]
    ver = st.session_state.get("editor_version", 0)

    # Top bar: Demo loader & Save button
    demos = load_demo_projects()
    demo_names = [d["name"] for d in demos]
    top1, top2, top3 = st.columns([2.2, 1.2, 1.0])
    with top1:
        selected_demo = st.selectbox(
            t["btn.load_demo"],
            options=demo_names,
            label_visibility="collapsed",
        )
    with top2:
        if st.button(t["btn.load_demo"], use_container_width=True):
            chosen = next(d for d in demos if d["name"] == selected_demo)
            st.session_state["project"] = {
                "name": chosen["name"],
                "base": chosen["base"],
                "method": chosen["method"],
                "gateway_policy": chosen["gateway_policy"],
                "default_reserve": chosen["default_reserve"],
                "departments": [dict(x) for x in chosen["departments"]],
                "reserved": [dict(x) for x in chosen["reserved"]],
            }
            st.session_state["current_project_id"] = None
            st.session_state["editor_version"] = ver + 1
            recompute_session_plan(lang=lang)
            st.rerun()
    with top3:
        if st.button(t["btn.save"], use_container_width=True):
            try:
                pid = storage.save_project(
                    st.session_state["project"],
                    project_id=st.session_state.get("current_project_id"),
                )
                st.session_state["current_project_id"] = pid
                st.success(t["pr.saved"])
            except ValueError:
                st.error(t["pr.name_taken"])

    # Form fields (Section 6.3)
    c1, c2, c3, c4, c5 = st.columns([1.6, 1.4, 1.0, 1.4, 1.0])
    with c1:
        name_val = st.text_input(
            t["planner.project_name"],
            value=proj.get("name", ""),
            key=f"in_name_{ver}",
        )
    with c2:
        base_val = st.text_input(
            t["planner.base_network"],
            value=proj.get("base", "192.168.1.0/24"),
            key=f"in_base_{ver}",
        )
    with c3:
        method_val = st.selectbox(
            t["planner.method"],
            options=["VLSM", "FLSM"],
            index=0 if proj.get("method", "VLSM") == "VLSM" else 1,
            key=f"in_method_{ver}",
        )
    with c4:
        gw_val = st.selectbox(
            t["planner.gateway_policy"],
            options=["first", "last"],
            index=0 if proj.get("gateway_policy", "first") == "first" else 1,
            format_func=lambda x: t["planner.gw_first"] if x == "first" else t["planner.gw_last"],
            key=f"in_gw_{ver}",
        )
    with c5:
        def_res_val = st.number_input(
            t["planner.default_reserve"],
            min_value=0,
            max_value=100,
            value=int(proj.get("default_reserve", 20)),
            step=5,
            key=f"in_defres_{ver}",
        )

    # Inline NET-001 errors near input fields (Section 6.7)
    for err in st.session_state.get("input_errors", []):
        st.error(f"**{err.code}**: {err.message} — {err.recommendation}")

    # Two editable tables (st.data_editor)
    col_d, col_r = st.columns([1.65, 1.0])
    with col_d:
        st.subheader(t["planner.departments"])
        dept_df = pd.DataFrame(
            proj.get("departments")
            if proj.get("departments")
            else [{"name": "", "vlan_id": None, "hosts": 10, "reserve_pct": int(def_res_val)}]
        )
        edited_depts = st.data_editor(
            dept_df,
            num_rows="dynamic",
            use_container_width=True,
            key=f"ed_depts_{ver}",
            column_config={
                "name": st.column_config.TextColumn(t["col.department"]),
                "vlan_id": st.column_config.NumberColumn(t["col.vlan"], step=1),
                "hosts": st.column_config.NumberColumn(t["col.devices"], step=1, default=10),
                "reserve_pct": st.column_config.NumberColumn(
                    t["col.reserve"], min_value=0, max_value=100, step=5, default=int(def_res_val)
                ),
            },
        )
    with col_r:
        st.subheader(t["planner.reserved_blocks"])
        res_df = pd.DataFrame(
            proj.get("reserved")
            if proj.get("reserved")
            else pd.DataFrame(columns=["network", "note"])
        )
        edited_res = st.data_editor(
            res_df,
            num_rows="dynamic",
            use_container_width=True,
            key=f"ed_res_{ver}",
            column_config={
                "network": st.column_config.TextColumn(t["col.network"]),
                "note": st.column_config.TextColumn(t["col.note"]),
            },
        )

    if st.button(t["btn.calculate"], type="primary", use_container_width=False):
        st.session_state["project"] = {
            "name": name_val.strip() or t["pr.new"],
            "base": base_val.strip(),
            "method": method_val,
            "gateway_policy": gw_val,
            "default_reserve": int(def_res_val),
            "departments": _df_to_departments(edited_depts, int(def_res_val)),
            "reserved": _df_to_reserves(edited_res),
        }
        recompute_session_plan(lang=lang)
        st.rerun()

    st.divider()
    plan = st.session_state.get("plan")
    if plan is None:
        if not st.session_state.get("input_errors"):
            st.info(t["empty.no_plan"])
        return

    # Status message (Section 6.3 & FT-08)
    if plan.is_complete:
        st.success(t["plan.ok"])
    else:
        st.error(t["plan.incomplete"])

    # 13-column plan table (FT-10)
    st.subheader(t["plan.title"])
    rows = []
    for s in plan.subnets:
        rows.append(
            {
                t["col.department"]: s.department,
                t["col.vlan"]: "" if s.vlan_id is None else str(s.vlan_id),
                t["col.subnet"]: str(s.network),
                t["col.prefix"]: f"/{s.network.prefixlen}",
                t["col.mask"]: str(s.network.netmask),
                t["col.first_ip"]: str(s.first_host),
                t["col.last_ip"]: str(s.last_host),
                t["col.broadcast"]: str(s.network.broadcast_address),
                t["col.gateway"]: str(s.gateway),
                t["col.capacity"]: s.capacity,
                t["col.planned"]: s.planned_hosts,
                t["col.free_slots"]: s.free_slots,
                t["col.status"]: t["status.allocated"],
            }
        )
    for u in plan.unallocated:
        reason = t["plan.reason_space"] if u.reason_code == "space" else t["plan.reason_block"]
        rows.append(
            {
                t["col.department"]: u.department.name,
                t["col.vlan"]: "" if u.department.vlan_id is None else str(u.department.vlan_id),
                t["col.subnet"]: "—",
                t["col.prefix"]: f"/{u.required_prefix}",
                t["col.mask"]: "—",
                t["col.first_ip"]: "—",
                t["col.last_ip"]: "—",
                t["col.broadcast"]: "—",
                t["col.gateway"]: "—",
                t["col.capacity"]: 0,
                t["col.planned"]: u.planned_hosts,
                t["col.free_slots"]: 0,
                t["col.status"]: f"{t['status.unallocated']} ({reason})",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.subheader(t["map.title"])
    st.plotly_chart(address_space_map(plan, lang=lang), use_container_width=True)
