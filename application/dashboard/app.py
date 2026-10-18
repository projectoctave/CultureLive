"""Dashboard CultureLive — login org / sales + stats anonymisées."""

import os

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

from dashboard.branding import (
    BRAND_COLORS,
    apply_figure_style,
    brand_header,
    inject_theme,
    kpi_row,
    section_title,
)

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

st.set_page_config(
    page_title="Culturelive — Pilotage commercial",
    page_icon="https://cdn.prod.website-files.com/67d1567005182f6c898c2f12/67e6979c64984f6cca2adce1_logo_brandmark_culturelive_ai_fav_icon.jpg",
    layout="wide",
)
inject_theme()


def auth_headers() -> dict[str, str]:
    token = st.session_state.get("access_token")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def login_form() -> None:
    brand_header(
        title="Culturelive",
        tagline="Booster votre pipe — mesurez l'activité commerciale de vos équipes.",
    )
    _, center, _ = st.columns([1, 1.1, 1])
    with center:
        with st.container(border=True):
            st.markdown("### Connexion")
            st.caption("Compte entreprise : vue équipe · Compte sales : vue individuelle")
            with st.form("login"):
                login = st.text_input("Identifiant")
                password = st.text_input("Mot de passe", type="password")
                submitted = st.form_submit_button("Se connecter", use_container_width=True)
                if submitted:
                    try:
                        r = requests.post(
                            f"{BACKEND_URL}/auth/dashboard/login",
                            json={"login": login, "password": password},
                            timeout=30,
                        )
                        r.raise_for_status()
                        data = r.json()
                        st.session_state["access_token"] = data["access_token"]
                        st.session_state["role"] = data["role"]
                        st.session_state["organization_ref"] = data["organization_ref"]
                        st.session_state["user_ref"] = data.get("user_ref")
                        st.session_state["display_name"] = data.get("display_name")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Échec connexion : {exc}")


@st.cache_data(ttl=60)
def fetch_overview(token: str):
    r = requests.get(
        f"{BACKEND_URL}/stats/overview",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=60)
def fetch_meetings(token: str, org: str | None, user: str | None):
    params: dict[str, str] = {}
    if org:
        params["organization_ref"] = org
    if user:
        params["user_ref"] = user
    r = requests.get(
        f"{BACKEND_URL}/stats/meetings",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


if "access_token" not in st.session_state:
    login_form()
    st.stop()

token = st.session_state["access_token"]
role = st.session_state.get("role", "")
org_ref = st.session_state.get("organization_ref", "")
user_ref = st.session_state.get("user_ref")
display_name = st.session_state.get("display_name") or org_ref

tagline = (
    f"Connecté · {display_name} · vue individuelle"
    if role == "sales_user"
    else f"Connecté · {display_name} · vue équipe"
)
brand_header(title="Pilotage des rendez-vous", tagline=tagline)

_, logout_col = st.columns([6, 1])
with logout_col:
    if st.button("Déconnexion", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

try:
    overview = fetch_overview(token)
except Exception as exc:
    st.error(f"Backend indisponible : {exc}")
    st.stop()

total_meetings = sum(o.get("meetings", 0) for o in overview.get("by_organization", []))
total_users = len(overview.get("by_user", []))
total_categories = len(overview.get("by_category", []))
kpi_row(
    [
        ("Meetings classifiés", total_meetings),
        ("Commerciaux actifs", total_users),
        ("Typologies", total_categories),
    ]
)

col1, col2 = st.columns(2)

with col1:
    section_title("Par entreprise")
    df_org = pd.DataFrame(overview.get("by_organization", []))
    if df_org.empty:
        st.info("Aucune donnée pour le moment.")
    else:
        fig = px.bar(
            df_org,
            x="organization_ref",
            y="meetings",
            title="Volume par organisation",
            color_discrete_sequence=["#201568"],
        )
        apply_figure_style(fig)
        st.plotly_chart(fig, use_container_width=True)

with col2:
    section_title("Par commercial")
    df_user = pd.DataFrame(overview.get("by_user", []))
    if df_user.empty:
        st.info("Aucune donnée pour le moment.")
    else:
        fig = px.bar(
            df_user,
            x="user_ref",
            y="meetings",
            title="Volume par utilisateur",
            color_discrete_sequence=["#f1572c"],
        )
        apply_figure_style(fig)
        st.plotly_chart(fig, use_container_width=True)

section_title("Typologie sales")
df_cat = pd.DataFrame(overview.get("by_category", []))
if not df_cat.empty:
    fig = px.pie(
        df_cat,
        names="label",
        values="count",
        title="Répartition des types de rendez-vous",
        color_discrete_sequence=px.colors.qualitative.Safe,
    )
    apply_figure_style(fig)
    fig.update_traces(textposition="inside", textinfo="percent+label")
    st.plotly_chart(fig, use_container_width=True)

section_title("Détail des meetings")
users = [u["user_ref"] for u in overview.get("by_user", [])]
if role == "org_admin":
    sel_user = st.selectbox("Filtrer un commercial", options=["(tous)"] + users)
    filter_user = None if sel_user == "(tous)" else sel_user
else:
    filter_user = user_ref
    st.info(f"Vue restreinte à votre activité ({user_ref}).")

meetings = fetch_meetings(token, org_ref if role == "org_admin" else org_ref, filter_user)
st.dataframe(pd.DataFrame(meetings), use_container_width=True, hide_index=True)
