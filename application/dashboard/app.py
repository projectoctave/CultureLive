"""Dashboard CultureLive : pilotage de la prospection et du pipe (manager) et ma semaine (commercial)."""

import os

import requests
import streamlit as st

from dashboard import manager_view, sales_view
from dashboard.branding import brand_header, inject_theme

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
                submitted = st.form_submit_button("Se connecter", width="stretch")
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


if "access_token" not in st.session_state:
    login_form()
    st.stop()

token = st.session_state["access_token"]
role = st.session_state.get("role", "")
display_name = st.session_state.get("display_name") or st.session_state.get("organization_ref", "")
is_sales = role == "sales_user"

brand_header(
    title="Ma semaine de chasse" if is_sales else "Pilotage commercial",
    tagline=f"Connecté · {display_name} · " + ("vue individuelle" if is_sales else "vue manager"),
)

_, logout_col = st.columns([6, 1])
with logout_col:
    if st.button("Déconnexion", width="stretch"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

try:
    (sales_view if is_sales else manager_view).render(token)
except requests.HTTPError as exc:
    if exc.response is not None and exc.response.status_code == 401:
        st.warning("Session expirée, reconnectez-vous.")
        for key in list(st.session_state.keys()):
            del st.session_state[key]
    else:
        st.error(f"Erreur du backend : {exc}")
except requests.RequestException as exc:
    st.error(f"Backend indisponible : {exc}")
