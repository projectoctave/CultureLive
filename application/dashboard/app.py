"""Dashboard CultureLive — login org / sales + stats anonymisées."""

import os

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="CultureLive Dashboard", layout="wide")


def auth_headers() -> dict[str, str]:
    token = st.session_state.get("access_token")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def login_form() -> None:
    st.title("CultureLive — Connexion")
    st.caption("Compte entreprise : vue équipe · Compte sales : vue individuelle")
    with st.form("login"):
        login = st.text_input("Login")
        password = st.text_input("Mot de passe", type="password")
        submitted = st.form_submit_button("Se connecter")
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

col_h, col_logout = st.columns([5, 1])
with col_h:
    st.title("CultureLive — Sales meetings")
    st.caption(
        f"Connecté · rôle `{role}` · org `{org_ref}`"
        + (f" · user `{user_ref}`" if user_ref else " · vue équipe")
    )
    if display_name:
        st.markdown(f"**{display_name}**")
with col_logout:
    if st.button("Déconnexion"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

try:
    overview = fetch_overview(token)
except Exception as exc:
    st.error(f"Backend indisponible : {exc}")
    st.stop()

col1, col2 = st.columns(2)

with col1:
    st.subheader("Par entreprise (anonymisé)")
    df_org = pd.DataFrame(overview.get("by_organization", []))
    if df_org.empty:
        st.info("Aucune donnée.")
    else:
        st.plotly_chart(
            px.bar(df_org, x="organization_ref", y="meetings", title="Meetings par org"),
            use_container_width=True,
        )

with col2:
    st.subheader("Par utilisateur (anonymisé)")
    df_user = pd.DataFrame(overview.get("by_user", []))
    if df_user.empty:
        st.info("Aucune donnée.")
    else:
        st.plotly_chart(
            px.bar(df_user, x="user_ref", y="meetings", title="Meetings par user"),
            use_container_width=True,
        )

st.subheader("Répartition typologie sales")
df_cat = pd.DataFrame(overview.get("by_category", []))
if not df_cat.empty:
    st.plotly_chart(px.pie(df_cat, names="label", values="count"), use_container_width=True)

st.subheader("Liste des meetings")
users = [u["user_ref"] for u in overview.get("by_user", [])]
if role == "org_admin":
    sel_user = st.selectbox("Filtrer un sales", options=["(tous)"] + users)
    filter_user = None if sel_user == "(tous)" else sel_user
else:
    filter_user = user_ref
    st.info(f"Vue individuelle : `{user_ref}`")

meetings = fetch_meetings(token, org_ref if role == "org_admin" else org_ref, filter_user)
st.dataframe(pd.DataFrame(meetings), use_container_width=True)
