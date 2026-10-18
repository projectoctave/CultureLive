"""Rendez-vous classifiés depuis le calendrier (typologie des meetings)."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard import api
from dashboard.branding import BRAND_COLORS, apply_figure_style, kpi_row, section_title


def render(token: str, manager: bool) -> None:
    overview = api.get(token, "/stats/overview")
    total_meetings = sum(o.get("meetings", 0) for o in overview.get("by_organization", []))
    kpi_row(
        [
            ("Meetings classifiés", total_meetings),
            ("Commerciaux actifs", len(overview.get("by_user", []))),
            ("Typologies", len(overview.get("by_category", []))),
        ]
    )

    col1, col2 = st.columns(2)
    with col1:
        section_title("Par commercial")
        df_user = pd.DataFrame(overview.get("by_user", []))
        if df_user.empty:
            st.info("Aucune donnée pour le moment.")
        else:
            fig = px.bar(df_user, x="user_ref", y="meetings", color_discrete_sequence=[BRAND_COLORS[0]])
            fig.update_layout(xaxis_title=None, yaxis_title="Meetings")
            apply_figure_style(fig)
            st.plotly_chart(fig, width="stretch")
    with col2:
        section_title("Typologie sales")
        df_cat = pd.DataFrame(overview.get("by_category", []))
        if not df_cat.empty:
            fig = px.pie(df_cat, names="label", values="count", color_discrete_sequence=BRAND_COLORS)
            apply_figure_style(fig)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, width="stretch")

    section_title("Détail des meetings")
    org_ref = st.session_state.get("organization_ref")
    params: list[tuple[str, str]] = [("organization_ref", org_ref)] if org_ref else []
    if manager:
        users = [u["user_ref"] for u in overview.get("by_user", [])]
        selected = st.selectbox("Filtrer un commercial", options=["(tous)"] + users)
        if selected != "(tous)":
            params.append(("user_ref", selected))
    elif st.session_state.get("user_ref"):
        params.append(("user_ref", st.session_state["user_ref"]))
    meetings = api.get(token, "/stats/meetings", tuple(params))
    st.dataframe(pd.DataFrame(meetings), width="stretch", hide_index=True)
