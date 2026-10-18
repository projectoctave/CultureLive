"""Dashboard CultureLive — stats anonymisées par organization_ref / user_ref."""

import os

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
API_KEY = os.getenv("DASHBOARD_API_KEY", "")

st.set_page_config(page_title="CultureLive Dashboard", layout="wide")
st.title("CultureLive — Sales meetings")
st.caption("Statistiques anonymisées (identifiants org / user, sans PII).")

if not API_KEY:
    st.error("Configurez DASHBOARD_API_KEY pour accéder aux statistiques.")
    st.stop()

headers = {"X-API-Key": API_KEY}


@st.cache_data(ttl=60)
def fetch_overview():
    r = requests.get(f"{BACKEND_URL}/stats/overview", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=60)
def fetch_meetings(org: str | None, user: str | None):
    params = {}
    if org:
        params["organization_ref"] = org
    if user:
        params["user_ref"] = user
    r = requests.get(f"{BACKEND_URL}/stats/meetings", headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


try:
    overview = fetch_overview()
except Exception as exc:
    st.error(f"Backend indisponible: {exc}")
    st.stop()

col1, col2 = st.columns(2)

with col1:
    st.subheader("Par entreprise (anonymisé)")
    df_org = pd.DataFrame(overview.get("by_organization", []))
    if df_org.empty:
        st.info("Aucune donnée.")
    else:
        fig = px.bar(df_org, x="organization_ref", y="meetings", title="Meetings par org")
        st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Par utilisateur (anonymisé)")
    df_user = pd.DataFrame(overview.get("by_user", []))
    if df_user.empty:
        st.info("Aucune donnée.")
    else:
        fig = px.bar(df_user, x="user_ref", y="meetings", title="Meetings par user")
        st.plotly_chart(fig, use_container_width=True)

st.subheader("Répartition typologie sales")
df_cat = pd.DataFrame(overview.get("by_category", []))
if not df_cat.empty:
    fig_cat = px.pie(df_cat, names="label", values="count")
    st.plotly_chart(fig_cat, use_container_width=True)

st.subheader("Filtrer la liste des meetings")
orgs = [o["organization_ref"] for o in overview.get("by_organization", [])]
users = [u["user_ref"] for u in overview.get("by_user", [])]
sel_org = st.selectbox("Organisation", options=["(toutes)"] + orgs)
sel_user = st.selectbox("Utilisateur", options=["(tous)"] + users)

meetings = fetch_meetings(
    None if sel_org == "(toutes)" else sel_org,
    None if sel_user == "(tous)" else sel_user,
)
st.dataframe(pd.DataFrame(meetings), use_container_width=True)
