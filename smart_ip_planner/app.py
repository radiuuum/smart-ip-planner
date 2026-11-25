"""Smart IP Planner — Main Streamlit Entry Point (Sections 6.2 & 7.1)."""

from __future__ import annotations

import streamlit as st

from services.storage import ProjectStorage, load_demo_projects
from strings import get_strings
from ui.analytics_view import render_analytics_view
from ui.diagnostics_view import render_diagnostics_view
from ui.growth_view import render_growth_and_projects_view
from ui.planner_view import recompute_session_plan, render_planner_view

st.set_page_config(
    page_title="Smart IP Planner",
    page_icon="🌐",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def get_storage() -> ProjectStorage:
    return ProjectStorage()


def _init_session() -> None:
    if "lang" not in st.session_state:
        st.session_state["lang"] = "kk"
    if "editor_version" not in st.session_state:
        st.session_state["editor_version"] = 0
    if "project" not in st.session_state:
        demos = load_demo_projects()
        first = demos[0]
        st.session_state["project"] = {
            "name": first["name"],
            "base": first["base"],
            "method": first["method"],
            "gateway_policy": first["gateway_policy"],
            "default_reserve": first["default_reserve"],
            "departments": [dict(d) for d in first["departments"]],
            "reserved": [dict(r) for r in first["reserved"]],
        }
        st.session_state["current_project_id"] = None
        recompute_session_plan(lang=st.session_state["lang"])


def main() -> None:
    _init_session()
    storage = get_storage()

    with st.sidebar:
        lang = st.radio(
            "Тіл / Язык",
            options=["kk", "ru"],
            format_func=lambda x: "Қазақша" if x == "kk" else "Русский",
            index=0 if st.session_state["lang"] == "kk" else 1,
            horizontal=True,
        )
        if lang != st.session_state["lang"]:
            st.session_state["lang"] = lang
            if st.session_state.get("plan") is not None:
                recompute_session_plan(lang=lang)
            st.rerun()

        t = get_strings(lang)
        st.title(f"🌐 {t['app.title']}")
        st.caption(t["app.subtitle"])
        st.divider()

        nav_keys = ["nav.planner", "nav.diagnostics", "nav.analytics", "nav.growth"]
        section = st.sidebar.radio(
            t["nav.label"],
            options=nav_keys,
            format_func=lambda k: t[k],
            label_visibility="collapsed",
        )

    t = get_strings(st.session_state["lang"])
    st.title(t[section])

    if section == "nav.planner":
        render_planner_view(storage, lang=st.session_state["lang"])
    elif section == "nav.diagnostics":
        render_diagnostics_view(lang=st.session_state["lang"])
    elif section == "nav.analytics":
        render_analytics_view(lang=st.session_state["lang"])
    else:
        render_growth_and_projects_view(storage, lang=st.session_state["lang"])


if __name__ == "__main__":
    main()
