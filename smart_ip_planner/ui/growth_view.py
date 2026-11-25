"""Section 6.6: Кеңейту және жобалар view (growth simulator, SQLite projects, Excel/CSV/JSON/Cisco)."""

from __future__ import annotations

import ipaddress

import pandas as pd
import streamlit as st

from core.growth import simulate_growth
from core.models import ReservedBlock
from services.exporter import export_cisco_config, export_csv, export_excel
from services.storage import ProjectStorage, export_project_json, import_project_json
from strings import format_int, get_strings
from ui.planner_view import recompute_session_plan


def render_growth_and_projects_view(storage: ProjectStorage, lang: str = "kk") -> None:
    """Render Кеңейту және жобалар page (Section 6.6)."""
    t = get_strings(lang)
    plan = st.session_state.get("plan")
    metrics = st.session_state.get("metrics")
    comp = st.session_state.get("comparison")
    findings = st.session_state.get("findings", [])

    # 1. Growth Simulator (Section 5.5 & 6.6)
    st.subheader(t["gr.mode"])
    if plan is None or not plan.subnets:
        st.info(t["empty.no_plan"])
    else:
        reserves = [
            ReservedBlock(network=ipaddress.IPv4Network(r["network"], strict=True), note=r.get("note", ""))
            for r in st.session_state["project"].get("reserved", [])
            if r.get("network")
        ]
        mode = st.radio(
            t["gr.mode"],
            options=["all", "each"],
            format_func=lambda x: t["gr.mode_all"] if x == "all" else t["gr.mode_each"],
            horizontal=True,
            label_visibility="collapsed",
        )
        if mode == "all":
            pct = st.slider(t["gr.percent"], min_value=0, max_value=200, value=50, step=10)
            report = simulate_growth(plan, reserves, growth_pct=pct, lang=lang)
        else:
            init_g = pd.DataFrame(
                [
                    {"department": s.department, "now": s.hosts, "will": int(round(s.hosts * 1.5))}
                    for s in plan.subnets
                ]
            )
            ed_g = st.data_editor(
                init_g,
                use_container_width=True,
                hide_index=True,
                disabled=["department", "now"],
                column_config={
                    "department": st.column_config.TextColumn(t["col.department"]),
                    "now": st.column_config.NumberColumn(t["gr.now"]),
                    "will": st.column_config.NumberColumn(t["gr.will"], min_value=1, step=1),
                },
            )
            custom_map = {str(r["department"]): max(1, int(float(r["will"]))) for _, r in ed_g.iterrows()}
            report = simulate_growth(plan, reserves, custom_hosts=custom_map, lang=lang)

        g1, g2, g3, g4 = st.columns(4)
        g1.metric(t["gr.need_expand"], f"{report.need_expand_count} / {report.total_count}")
        g2.metric(t["gr.deficit"], format_int(report.total_deficit))
        g3.metric(t["gr.changed_subnets"], str(report.diff.changed_count))
        g4.metric(t["gr.affected_devices"], format_int(report.diff.affected_devices))

        st.caption(
            f"{t['gr.msg_summary'].format(n=report.need_expand_count, m=report.total_count)} "
            f"· {t['gr.renum_cost']}: {report.diff.changed_count} / {format_int(report.diff.affected_devices)}"
        )

        verdict_labels = {
            "ok": t["gr.ok"],
            "inplace": t["gr.inplace"],
            "move": t["gr.move"],
            "replan": t["gr.replan"],
        }
        table_rows = [
            {
                t["col.department"]: r.department,
                t["gr.now"]: r.current_hosts,
                t["gr.will"]: r.new_hosts,
                t["col.capacity"]: r.capacity,
                t["col.status"]: verdict_labels[r.verdict],
                t["col.subnet"]: str(r.proposed_network) if r.proposed_network else "—",
                t["gr.verdict"]: r.message,
            }
            for r in report.rows
        ]
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    # 2. Export & Import (Excel 4 sheets, CSV, JSON, Cisco)
    st.divider()
    st.subheader(t["pr.export_title"])
    e1, e2, e3 = st.columns(3)
    with e1:
        if plan is not None and metrics is not None and comp is not None:
            xlsx_data = export_excel(plan, metrics, comp, findings, lang=lang)
            st.download_button(
                t["pr.export_excel"],
                data=xlsx_data,
                file_name="smart_ip_plan.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
    with e2:
        if plan is not None:
            csv_data = export_csv(plan, lang=lang)
            st.download_button(
                t["pr.export_csv"],
                data=csv_data,
                file_name="smart_ip_plan.csv",
                mime="text/csv",
                use_container_width=True,
            )
    with e3:
        json_text = export_project_json(st.session_state["project"])
        st.download_button(
            t["pr.export_json"],
            data=json_text.encode("utf-8"),
            file_name="project.json",
            mime="application/json",
            use_container_width=True,
        )

    uploaded = st.file_uploader(t["pr.import_json"], type=["json"], key="json_imp_growth")
    if uploaded is not None:
        try:
            imported = import_project_json(uploaded.getvalue().decode("utf-8"))
            st.session_state["project"] = imported
            st.session_state["current_project_id"] = None
            st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
            recompute_session_plan(lang=lang)
            st.success(t["pr.saved"])
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    # Bonus FT-29: Cisco IOS config
    if plan is not None and plan.subnets:
        with st.expander(t["pr.export_cisco"]):
            host_in = st.text_input(t["pr.cisco_hostname"], value="CORE-SW1")
            cfg_txt = export_cisco_config(plan, hostname=host_in)
            st.code(cfg_txt, language="text")
            st.download_button(
                t["pr.export_cisco"],
                data=cfg_txt.encode("utf-8"),
                file_name="cisco_config.txt",
                mime="text/plain",
            )

    # 3. Saved Projects Management (SQLite — Section 6.6 & 7.3)
    st.divider()
    st.subheader(t["pr.title"])
    if st.button(t["pr.new"]):
        st.session_state["project"] = {
            "name": t["pr.new"],
            "base": "192.168.1.0/24",
            "method": "VLSM",
            "gateway_policy": "first",
            "default_reserve": 20,
            "departments": [{"name": "IT", "vlan_id": 10, "hosts": 20, "reserve_pct": 20}],
            "reserved": [],
        }
        st.session_state["current_project_id"] = None
        st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
        recompute_session_plan(lang=lang)
        st.rerun()

    projects = storage.list_projects()
    if not projects:
        st.info(t["pr.empty"])
        return

    for p in projects:
        pid = p["id"]
        with st.container(border=True):
            r1, r2, r3, r4, r5 = st.columns([2.4, 0.8, 0.8, 1.4, 1.0])
            with r1:
                st.markdown(f"**{p['name']}**")
                st.caption(f"{t['pr.updated']}: {p['updated_at']} · {p['data'].get('base', '')}")
            with r2:
                if st.button(t["btn.open"], key=f"open_{pid}", use_container_width=True):
                    st.session_state["project"] = dict(p["data"])
                    st.session_state["current_project_id"] = pid
                    st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
                    recompute_session_plan(lang=lang)
                    st.rerun()
            with r3:
                if st.button(t["btn.copy"], key=f"copy_{pid}", use_container_width=True):
                    storage.copy_project(pid)
                    st.rerun()
            with r4:
                new_nm = st.text_input(
                    t["btn.rename"],
                    value=p["name"],
                    key=f"ren_in_{pid}",
                    label_visibility="collapsed",
                )
                if st.button(t["btn.rename"], key=f"ren_btn_{pid}", use_container_width=True):
                    try:
                        storage.rename_project(pid, new_nm)
                        if st.session_state.get("current_project_id") == pid:
                            st.session_state["project"]["name"] = new_nm.strip()
                        st.rerun()
                    except ValueError:
                        st.error(t["pr.name_taken"])
            with r5:
                confirm_del = st.checkbox(t["pr.confirm_delete"], key=f"del_chk_{pid}")
                if st.button(t["btn.delete"], key=f"del_btn_{pid}", disabled=not confirm_del, use_container_width=True):
                    storage.delete_project(pid)
                    if st.session_state.get("current_project_id") == pid:
                        st.session_state["current_project_id"] = None
                    st.rerun()
