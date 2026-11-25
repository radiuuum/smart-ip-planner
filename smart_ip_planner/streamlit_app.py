"""Smart IP Planner — Streamlit Web Application (Streamlit Cloud & Local OS ready)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from core.allocator import plan_network
from core.autofix import preview_scenario_a_expand_base, preview_scenario_b_add_department
from core.calculator import ValidationError
from core.cisco import generate_cisco_config
from core.demos import get_demo_projects
from core.diagnostics import diagnose_auto_plan, diagnose_manual_network, summarize_severities
from core.growth import simulate_growth
from core.models import DepartmentInput, ManualSubnetEntry, PlannerConfig, ReserveInput
from i18n.translations import format_finding, get_translator
from storage.db import ProjectRepository
from storage.exporter import (
    export_plan_csv,
    export_plan_excel,
    export_project_json,
    import_project_json,
)
from ui.charts import (
    build_address_space_map,
    build_hosts_vs_capacity_chart,
    build_method_comparison_chart,
)
from ui.styles import CUSTOM_CSS

st.set_page_config(
    page_title="Smart IP Planner",
    page_icon="🌐",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


@st.cache_resource
def get_repo() -> ProjectRepository:
    repo = ProjectRepository()
    repo.seed_demos_if_empty()
    return repo


def _parse_departments_df(df: pd.DataFrame, default_reserve: int) -> list[DepartmentInput]:
    departments: list[DepartmentInput] = []
    if df is None or df.empty:
        return departments
    for _, row in df.iterrows():
        name = str(row.get("name", "") or "").strip()
        if not name:
            continue
        raw_vlan = row.get("vlan_id")
        vlan_id = None
        if pd.notna(raw_vlan) and str(raw_vlan).strip() != "":
            try:
                vlan_id = int(float(raw_vlan))
            except (ValueError, TypeError):
                vlan_id = None
        raw_hosts = row.get("hosts", 1)
        hosts = int(float(raw_hosts)) if pd.notna(raw_hosts) else 1
        raw_res = row.get("growth_reserve_pct", default_reserve)
        reserve = int(float(raw_res)) if pd.notna(raw_res) else default_reserve
        departments.append(
            DepartmentInput(
                name=name,
                vlan_id=vlan_id,
                hosts=max(1, hosts),
                growth_reserve_pct=max(0, min(100, reserve)),
            )
        )
    return departments


def _parse_reserves_df(df: pd.DataFrame) -> list[ReserveInput]:
    reserves: list[ReserveInput] = []
    if df is None or df.empty:
        return reserves
    for _, row in df.iterrows():
        cidr = str(row.get("cidr", "") or "").strip()
        if not cidr:
            continue
        note = str(row.get("note", "") or "").strip()
        reserves.append(ReserveInput(cidr=cidr, note=note))
    return reserves


def main() -> None:
    repo = get_repo()

    if "lang" not in st.session_state:
        st.session_state["lang"] = "kk"
    if "preview_a" not in st.session_state:
        st.session_state["preview_a"] = None
    if "preview_b" not in st.session_state:
        st.session_state["preview_b"] = None

    # --- Sidebar: Language, SQLite Projects, JSON Import/Export ---
    with st.sidebar:
        lang_choice = st.radio(
            "Тіл / Язык",
            options=["kk", "ru"],
            format_func=lambda c: "Қазақша" if c == "kk" else "Русский",
            index=0 if st.session_state["lang"] == "kk" else 1,
            horizontal=True,
        )
        st.session_state["lang"] = lang_choice
        t = get_translator(lang_choice)

        st.divider()
        st.subheader(t("sidebar_projects"))

        projects = repo.list_projects()
        if not projects:
            repo.seed_demos_if_empty()
            projects = repo.list_projects()

        project_map = {p.id: p for p in projects}
        project_ids = [p.id for p in projects]

        if "active_project_id" not in st.session_state or st.session_state["active_project_id"] not in project_map:
            st.session_state["active_project_id"] = project_ids[0]

        selected_id = st.selectbox(
            t("select_project"),
            options=project_ids,
            index=project_ids.index(st.session_state["active_project_id"]),
            format_func=lambda pid: project_map[pid].name,
        )
        if selected_id != st.session_state["active_project_id"]:
            st.session_state["active_project_id"] = selected_id
            st.session_state["preview_a"] = None
            st.session_state["preview_b"] = None
            st.rerun()

        active_proj = project_map[selected_id]

        col_sb1, col_sb2 = st.columns(2)
        with col_sb1:
            if st.button(t("btn_new_project"), use_container_width=True):
                new_id = repo.create_project(
                    name=f"{t('btn_new_project')} #{len(projects) + 1}",
                    config=PlannerConfig(base_cidr="192.168.0.0/22", method="VLSM", gateway_policy="first", default_reserve_pct=20),
                    departments=[
                        DepartmentInput(name="IT", vlan_id=10, hosts=25, growth_reserve_pct=20),
                        DepartmentInput(name="Office", vlan_id=20, hosts=50, growth_reserve_pct=20),
                    ],
                    reserves=[],
                )
                st.session_state["active_project_id"] = new_id
                st.rerun()
        with col_sb2:
            if st.button(t("btn_copy_project"), use_container_width=True):
                copied_id = repo.copy_project(active_proj.id)
                if copied_id:
                    st.session_state["active_project_id"] = copied_id
                    st.rerun()

        with st.expander(t("btn_rename_project")):
            new_title = st.text_input(t("rename_placeholder"), value=active_proj.name, key=f"ren_{active_proj.id}")
            if st.button(t("btn_rename_project"), key=f"ren_btn_{active_proj.id}", use_container_width=True):
                if repo.rename_project(active_proj.id, new_title):
                    st.rerun()

        col_sb3, col_sb4 = st.columns(2)
        with col_sb3:
            if st.button(t("btn_delete_project"), use_container_width=True, disabled=len(projects) <= 1):
                repo.delete_project(active_proj.id)
                st.session_state.pop("active_project_id", None)
                st.rerun()
        with col_sb4:
            if st.button(t("btn_reset_demos"), use_container_width=True):
                for demo in get_demo_projects():
                    repo.create_project(
                        name=demo["name"],
                        description=demo["description"],
                        config=demo["config"],
                        departments=demo["departments"],
                        reserves=demo["reserves"],
                    )
                st.rerun()

        st.divider()
        st.subheader(t("json_section"))
        json_str = export_project_json(
            active_proj.name,
            active_proj.description,
            active_proj.config,
            active_proj.departments,
            active_proj.reserves,
        )
        st.download_button(
            label=t("btn_export_json"),
            data=json_str.encode("utf-8"),
            file_name=f"project_{active_proj.id}.json",
            mime="application/json",
            use_container_width=True,
        )
        uploaded = st.file_uploader(t("upload_json"), type=["json"], key="json_uploader")
        if uploaded is not None:
            try:
                imp_name, imp_desc, imp_cfg, imp_depts, imp_res = import_project_json(
                    uploaded.getvalue().decode("utf-8")
                )
                imp_id = repo.create_project(
                    name=imp_name,
                    description=imp_desc,
                    config=imp_cfg,
                    departments=imp_depts,
                    reserves=imp_res,
                )
                st.session_state["active_project_id"] = imp_id
                st.success(t("import_success"))
                st.rerun()
            except Exception as exc:
                st.error(f"{t('import_error')}: {exc}")

    # --- Header ---
    st.title(f"🌐 {t('app_title')}")
    st.caption(t("app_subtitle"))
    if active_proj.description:
        st.info(f"**{active_proj.name}** — {active_proj.description}")

    # --- Tabs ---
    tab_plan, tab_analytics, tab_diag, tab_autofix, tab_export = st.tabs(
        [
            t("tab_planner"),
            t("tab_analytics"),
            t("tab_diagnostics"),
            t("tab_autofix"),
            t("tab_export"),
        ]
    )

    # --- Compute current saved plan ---
    base_valid = True
    plan = None
    try:
        plan = plan_network(active_proj.config, active_proj.departments, active_proj.reserves, include_comparison=True)
    except ValidationError:
        base_valid = False

    findings = diagnose_auto_plan(plan, active_proj.departments) if plan is not None else []

    # =========================================================================
    # TAB 1: PLANNER (FT-01..FT-10)
    # =========================================================================
    with tab_plan:
        c1, c2, c3, c4 = st.columns([2, 1.2, 1.4, 1.2])
        with c1:
            base_cidr_in = st.text_input(
                t("base_cidr_label"),
                value=active_proj.config.base_cidr,
                key=f"base_{active_proj.id}",
            )
        with c2:
            method_in = st.selectbox(
                t("method_label"),
                options=["VLSM", "FLSM"],
                index=0 if active_proj.config.method == "VLSM" else 1,
                key=f"method_{active_proj.id}",
            )
        with c3:
            gw_in = st.selectbox(
                t("gateway_label"),
                options=["first", "last"],
                index=0 if active_proj.config.gateway_policy == "first" else 1,
                format_func=lambda x: t("gateway_first") if x == "first" else t("gateway_last"),
                key=f"gw_{active_proj.id}",
            )
        with c4:
            def_res_in = st.number_input(
                t("default_reserve_label"),
                min_value=0,
                max_value=100,
                value=int(active_proj.config.default_reserve_pct),
                step=5,
                key=f"defres_{active_proj.id}",
            )

        col_ed1, col_ed2 = st.columns([1.65, 1])
        with col_ed1:
            st.subheader(t("departments_header"))
            st.caption(t("departments_hint"))
            dept_df_init = pd.DataFrame(
                [d.to_dict() for d in active_proj.departments]
                if active_proj.departments
                else [{"name": "", "vlan_id": None, "hosts": 10, "growth_reserve_pct": int(def_res_in)}]
            )
            edited_depts_df = st.data_editor(
                dept_df_init,
                num_rows="dynamic",
                use_container_width=True,
                key=f"depts_ed_{active_proj.id}",
                column_config={
                    "name": st.column_config.TextColumn(t("col_department"), required=True),
                    "vlan_id": st.column_config.NumberColumn(t("col_vlan"), min_value=1, max_value=4094, step=1),
                    "hosts": st.column_config.NumberColumn(t("col_hosts"), min_value=1, max_value=16000000, step=1, default=10),
                    "growth_reserve_pct": st.column_config.NumberColumn(
                        t("col_reserve_pct"), min_value=0, max_value=100, step=5, default=int(def_res_in)
                    ),
                },
            )

        with col_ed2:
            st.subheader(t("reserves_header"))
            st.caption(t("reserves_hint"))
            res_df_init = pd.DataFrame(
                [r.to_dict() for r in active_proj.reserves]
                if active_proj.reserves
                else pd.DataFrame(columns=["cidr", "note"])
            )
            edited_res_df = st.data_editor(
                res_df_init,
                num_rows="dynamic",
                use_container_width=True,
                key=f"res_ed_{active_proj.id}",
                column_config={
                    "cidr": st.column_config.TextColumn(t("col_cidr")),
                    "note": st.column_config.TextColumn(t("col_note")),
                },
            )

        if st.button(f"💾 {t('btn_save_recalc')}", type="primary"):
            new_cfg = PlannerConfig(
                base_cidr=base_cidr_in.strip(),
                method=method_in,
                gateway_policy=gw_in,
                default_reserve_pct=int(def_res_in),
            )
            new_depts = _parse_departments_df(edited_depts_df, int(def_res_in))
            new_reserves = _parse_reserves_df(edited_res_df)
            try:
                plan_network(new_cfg, new_depts, new_reserves, include_comparison=False)
                repo.update_project(active_proj.id, new_cfg, new_depts, new_reserves)
                st.session_state["preview_a"] = None
                st.session_state["preview_b"] = None
                st.rerun()
            except ValidationError:
                st.error(t("err_invalid_base"))

        st.divider()
        if not base_valid or plan is None:
            st.error(t("err_invalid_base"))
        else:
            if plan.is_complete:
                st.success(f"✅ {t('plan_complete_banner')}")
            else:
                st.error(f"⚠️ {t('plan_incomplete_banner')}")

            plan_rows = [
                {
                    t("col_department"): a.department,
                    t("col_vlan"): "" if a.vlan_id is None else str(a.vlan_id),
                    t("col_subnet"): a.subnet_cidr,
                    t("col_prefix"): f"/{a.prefix}",
                    t("col_mask"): a.netmask,
                    t("col_first_ip"): a.first_host_ip,
                    t("col_last_ip"): a.last_host_ip,
                    t("col_broadcast"): a.broadcast_address,
                    t("col_gateway"): a.gateway_ip,
                    t("col_capacity"): a.capacity,
                    t("col_planned"): a.planned_hosts,
                    t("col_free"): a.free_hosts,
                    t("col_status"): t("status_allocated"),
                }
                for a in plan.allocations
            ]
            if plan_rows:
                st.dataframe(pd.DataFrame(plan_rows), use_container_width=True, hide_index=True)

            if plan.unallocated:
                st.subheader(t("unallocated_header"))
                unalloc_rows = [
                    {
                        t("col_department"): u.department,
                        t("col_vlan"): "" if u.vlan_id is None else str(u.vlan_id),
                        t("col_planned"): u.planned_hosts,
                        t("col_prefix"): f"/{u.required_prefix}",
                        t("col_status"): t("status_unallocated"),
                        t("col_reason"): t(f"reason_{u.reason_code}"),
                    }
                    for u in plan.unallocated
                ]
                st.dataframe(pd.DataFrame(unalloc_rows), use_container_width=True, hide_index=True)

    # =========================================================================
    # TAB 2: ANALYTICS (FT-11..FT-14)
    # =========================================================================
    with tab_analytics:
        if plan is None:
            st.error(t("err_invalid_base"))
        else:
            m = plan.metrics
            k1, k2, k3, k4 = st.columns(4)
            k1.metric(t("metric_pool_size"), f"{m.pool_size:,}")
            k2.metric(t("metric_allocated"), f"{m.allocated_addresses:,}")
            k3.metric(t("metric_pool_fill"), f"{m.pool_fill_pct:.2f}%", help=t(f"fill_{m.pool_fill_level}"))
            k4.metric(t("metric_utilization"), f"{m.subnet_utilization_pct:.2f}%")

            k5, k6, k7, k8 = st.columns(4)
            k5.metric(t("metric_reserved"), f"{m.reserved_addresses_in_pool:,}")
            k6.metric(t("metric_largest_free"), f"{m.largest_free_block:,}", delta=m.largest_free_cidr or "—", delta_color="off")
            k7.metric(t("metric_free_blocks"), str(m.free_block_count))
            k8.metric(t("metric_fragmentation"), f"{m.fragmentation_index:.4f}")

            st.subheader(t("chart_space_map"))
            st.plotly_chart(build_address_space_map(plan, t), use_container_width=True)

            col_ch1, col_ch2 = st.columns(2)
            with col_ch1:
                st.subheader(t("chart_hosts_capacity"))
                if plan.allocations:
                    st.plotly_chart(build_hosts_vs_capacity_chart(plan, t), use_container_width=True)
            with col_ch2:
                st.subheader(t("chart_comparison"))
                if plan.comparison:
                    c = plan.comparison
                    st.plotly_chart(build_method_comparison_chart(plan, t), use_container_width=True)
                    comp_df = pd.DataFrame(
                        [
                            {t("col_metric"): t("comp_vlsm_required"), t("col_value"): str(c.vlsm_required_addresses)},
                            {t("col_metric"): t("comp_flsm_required"), t("col_value"): str(c.flsm_required_addresses)},
                            {t("col_metric"): t("comp_vlsm_min_pool"), t("col_value"): f"{c.vlsm_min_pool_size} (/{c.vlsm_min_pool_prefix})"},
                            {t("col_metric"): t("comp_flsm_min_pool"), t("col_value"): f"{c.flsm_min_pool_size} (/{c.flsm_min_pool_prefix})"},
                            {t("col_metric"): t("comp_savings"), t("col_value"): f"{c.vlsm_savings_pct:.2f}%"},
                        ]
                    )
                    st.dataframe(comp_df, use_container_width=True, hide_index=True)

    # =========================================================================
    # TAB 3: DIAGNOSTICS (FT-15..FT-17)
    # =========================================================================
    with tab_diag:
        diag_mode = st.radio(
            t("diag_mode_label"),
            options=["auto", "manual"],
            format_func=lambda x: t("diag_mode_auto") if x == "auto" else t("diag_mode_manual"),
            horizontal=True,
        )

        active_findings = findings
        if diag_mode == "manual":
            st.caption(t("diag_manual_hint"))
            manual_base = st.text_input(t("base_cidr_label"), value=active_proj.config.base_cidr, key="manual_base")
            default_manual = (
                [
                    {
                        "department": a.department,
                        "subnet_cidr": a.subnet_cidr,
                        "hosts": a.current_hosts,
                        "vlan_id": a.vlan_id,
                        "gateway_ip": a.gateway_ip,
                    }
                    for a in plan.allocations
                ]
                if plan and plan.allocations
                else [{"department": "Dept-1", "subnet_cidr": "192.168.0.0/26", "hosts": 50, "vlan_id": 10, "gateway_ip": "192.168.0.1"}]
            )
            manual_df = st.data_editor(
                pd.DataFrame(default_manual),
                num_rows="dynamic",
                use_container_width=True,
                key="manual_diag_editor",
            )
            entries: list[ManualSubnetEntry] = []
            for _, r in manual_df.iterrows():
                if not str(r.get("subnet_cidr", "") or "").strip():
                    continue
                raw_v = r.get("vlan_id")
                vid = int(float(raw_v)) if pd.notna(raw_v) and str(raw_v).strip() != "" else None
                entries.append(
                    ManualSubnetEntry(
                        department=str(r.get("department", "") or "").strip() or "Unnamed",
                        subnet_cidr=str(r.get("subnet_cidr", "") or "").strip(),
                        hosts=int(float(r.get("hosts", 1))) if pd.notna(r.get("hosts")) else 1,
                        vlan_id=vid,
                        gateway_ip=str(r.get("gateway_ip", "") or "").strip(),
                    )
                )
            active_findings = diagnose_manual_network(manual_base, entries, active_proj.reserves)

        counts = summarize_severities(active_findings)
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("ERROR", counts["ERROR"])
        s2.metric("WARNING", counts["WARNING"])
        s3.metric("INFO", counts["INFO"])
        s4.metric("SUCCESS", counts["SUCCESS"])

        for f in active_findings:
            title, msg, rec = format_finding(f, lang_choice)
            affected_str = ", ".join(f.affected_departments) if f.affected_departments else "—"
            st.markdown(
                f"""
                <div class="sip-card">
                    <span class="sip-badge sip-{f.severity}">{f.code} · {f.severity}</span>
                    <span class="sip-card-title" style="margin-left:8px;">{title}</span>
                    <div class="sip-card-meta"><b>{t('col_message')}:</b> {msg}</div>
                    <div class="sip-card-meta"><b>{t('col_affected')}:</b> {affected_str}</div>
                    <div class="sip-card-meta"><b>{t('col_recommendation')}:</b> {rec}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # =========================================================================
    # TAB 4: AUTO-FIX & GROWTH MODELING (FT-18..FT-23)
    # =========================================================================
    with tab_autofix:
        if plan is None:
            st.error(t("err_invalid_base"))
        else:
            st.subheader(t("autofix_header"))
            col_a, col_b = st.columns(2)

            # Scenario A
            with col_a:
                st.markdown(f"#### {t('scenario_a_title')}")
                st.caption(t("scenario_a_desc"))
                if st.button(t("btn_preview_a"), use_container_width=True):
                    st.session_state["preview_a"] = preview_scenario_a_expand_base(
                        active_proj.config, active_proj.departments, active_proj.reserves
                    )

                prev_a = st.session_state.get("preview_a")
                if prev_a is not None:
                    st.info(t("preview_notice"))
                    if prev_a.success and prev_a.preview_plan is not None:
                        st.success(
                            t("autofix_a_success").format(
                                old_base=prev_a.old_base_cidr, new_base=prev_a.new_base_cidr
                            )
                        )
                        if st.button(t("btn_apply_a"), type="primary", use_container_width=True):
                            updated_cfg = PlannerConfig(
                                base_cidr=prev_a.new_base_cidr,
                                method=active_proj.config.method,
                                gateway_policy=active_proj.config.gateway_policy,
                                default_reserve_pct=active_proj.config.default_reserve_pct,
                            )
                            repo.update_project(active_proj.id, updated_cfg, active_proj.departments, active_proj.reserves)
                            st.session_state["preview_a"] = None
                            st.success(t("applied_success"))
                            st.rerun()
                    else:
                        st.error(t("autofix_a_failed"))

            # Scenario B
            with col_b:
                st.markdown(f"#### {t('scenario_b_title')}")
                st.caption(t("scenario_b_desc"))
                b_name = st.text_input(t("new_dept_name"), value="Жаңа филиал", key="b_name")
                b_c1, b_c2, b_c3 = st.columns(3)
                with b_c1:
                    b_vlan_raw = st.number_input(t("new_dept_vlan"), min_value=0, max_value=4094, value=99, step=1, key="b_vlan")
                with b_c2:
                    b_hosts = st.number_input(t("new_dept_hosts"), min_value=1, max_value=100000, value=20, step=1, key="b_hosts")
                with b_c3:
                    b_res = st.number_input(
                        t("new_dept_reserve"), min_value=0, max_value=100, value=active_proj.config.default_reserve_pct, step=5, key="b_res"
                    )

                new_dept_obj = DepartmentInput(
                    name=b_name.strip() or "New Dept",
                    vlan_id=None if b_vlan_raw == 0 else int(b_vlan_raw),
                    hosts=int(b_hosts),
                    growth_reserve_pct=int(b_res),
                )
                if st.button(t("btn_preview_b"), use_container_width=True):
                    st.session_state["preview_b"] = (
                        preview_scenario_b_add_department(plan, new_dept_obj, active_proj.reserves),
                        new_dept_obj,
                    )

                prev_b_pair = st.session_state.get("preview_b")
                if prev_b_pair is not None:
                    prev_b, pending_dept = prev_b_pair
                    st.info(t("preview_notice"))
                    if prev_b.success and prev_b.added_allocation is not None:
                        st.success(
                            t("autofix_b_success").format(
                                dept=pending_dept.name,
                                cidr=prev_b.added_allocation.subnet_cidr,
                                unchanged=prev_b.unchanged_count,
                            )
                        )
                        if st.button(t("btn_apply_b"), type="primary", use_container_width=True):
                            updated_depts = list(active_proj.departments) + [pending_dept]
                            repo.update_project(active_proj.id, active_proj.config, updated_depts, active_proj.reserves)
                            st.session_state["preview_b"] = None
                            st.success(t("applied_success"))
                            st.rerun()
                    else:
                        st.error(
                            t("autofix_b_failed").format(
                                prefix=prev_b.details.get("required_prefix", "?"),
                                size=prev_b.details.get("required_size", "?"),
                            )
                        )

            # Growth Modeling (FT-21..FT-23)
            st.divider()
            st.subheader(t("growth_header"))
            if not plan.allocations:
                st.warning(t("plan_incomplete_banner"))
            else:
                g_mode = st.radio(
                    t("growth_mode_label"),
                    options=["uniform", "custom"],
                    format_func=lambda x: t("growth_mode_uniform") if x == "uniform" else t("growth_mode_custom"),
                    horizontal=True,
                )
                if g_mode == "uniform":
                    g_pct = st.slider(t("growth_pct_slider"), min_value=0, max_value=300, value=50, step=10)
                    sim = simulate_growth(plan, active_proj.reserves, uniform_growth_pct=g_pct)
                else:
                    custom_df_init = pd.DataFrame(
                        [
                            {
                                "department": a.department,
                                "current_hosts": a.current_hosts,
                                "projected_hosts": int(round(a.current_hosts * 1.5)),
                            }
                            for a in plan.allocations
                        ]
                    )
                    edited_growth = st.data_editor(
                        custom_df_init,
                        use_container_width=True,
                        hide_index=True,
                        disabled=["department", "current_hosts"],
                        key=f"growth_ed_{active_proj.id}",
                    )
                    custom_map = {
                        str(r["department"]): max(1, int(float(r["projected_hosts"])))
                        for _, r in edited_growth.iterrows()
                    }
                    sim = simulate_growth(plan, active_proj.reserves, custom_hosts=custom_map)

                g1, g2, g3, g4 = st.columns(4)
                g1.metric(t("renum_subnets"), sim.subnets_renumbered)
                g2.metric(t("renum_devices"), sim.devices_renumbered)
                g3.metric(t("verdict_sufficient"), sim.counts_by_verdict["sufficient"])
                g4.metric(
                    t("verdict_full_replan"),
                    sim.counts_by_verdict["full_replan"],
                )

                sim_rows = [
                    {
                        t("col_department"): item.department,
                        t("col_current_subnet"): item.current_subnet,
                        t("col_capacity"): item.current_capacity,
                        t("col_hosts"): item.current_hosts,
                        t("col_projected_hosts"): item.projected_hosts,
                        t("col_verdict"): t(f"verdict_{item.verdict}"),
                        t("col_proposed_subnet"): item.proposed_subnet or "—",
                        t("col_devices_renum"): item.devices_renumbered,
                    }
                    for item in sim.items
                ]
                st.dataframe(pd.DataFrame(sim_rows), use_container_width=True, hide_index=True)

    # =========================================================================
    # TAB 5: EXPORT & CISCO IOS GENERATOR (FT-25, FT-26, FT-29)
    # =========================================================================
    with tab_export:
        if plan is None:
            st.error(t("err_invalid_base"))
        else:
            st.subheader(t("export_header"))
            e1, e2 = st.columns(2)
            with e1:
                excel_bytes = export_plan_excel(
                    project_name=active_proj.name,
                    plan=plan,
                    findings=findings,
                    t=t,
                    format_finding=lambda f: format_finding(f, lang_choice),
                )
                st.download_button(
                    label=f"📊 {t('btn_download_excel')}",
                    data=excel_bytes,
                    file_name=f"smart_ip_plan_{active_proj.id}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            with e2:
                csv_bytes = export_plan_csv(plan, t)
                st.download_button(
                    label=f"📄 {t('btn_download_csv')}",
                    data=csv_bytes,
                    file_name=f"smart_ip_plan_{active_proj.id}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

            st.divider()
            st.subheader(t("cisco_header"))
            cc1, cc2 = st.columns([2, 1])
            with cc1:
                cisco_host = st.text_input(t("cisco_hostname"), value="CORE-SW1")
            with cc2:
                cisco_dhcp = st.checkbox(t("cisco_dhcp"), value=True)

            cisco_cfg = generate_cisco_config(plan, hostname=cisco_host, include_dhcp=cisco_dhcp)
            st.code(cisco_cfg, language="text")
            st.download_button(
                label=f"⬇️ {t('btn_download_cisco')}",
                data=cisco_cfg.encode("utf-8"),
                file_name=f"cisco_{active_proj.id}.txt",
                mime="text/plain",
            )


if __name__ == "__main__":
    main()
