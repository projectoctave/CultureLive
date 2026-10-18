"""Client HTTP du backend CultureLive pour le dashboard."""

from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
TIMEOUT = 30


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@st.cache_data(ttl=20, show_spinner=False)
def get(token: str, path: str, params: tuple[tuple[str, Any], ...] = ()) -> Any:
    r = requests.get(f"{BACKEND_URL}{path}", headers=_headers(token), params=dict(params), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def send(token: str, method: str, path: str, payload: dict | None = None) -> tuple[bool, str]:
    """Écriture (POST/PATCH/PUT) ; invalide le cache de lecture. Retourne (succès, message d'erreur)."""
    try:
        r = requests.request(method, f"{BACKEND_URL}{path}", headers=_headers(token), json=payload, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return False, str(exc)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        return False, str(detail)
    st.cache_data.clear()
    return True, ""
