"""Charte visuelle Culturelive (alignée sur culture-live.com)."""

from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

LOGO_URL = (
    "https://cdn.prod.website-files.com/67d1567005182f6c898c2f12/"
    "6a28039edcc2e27cad53a3eb_Logo%20Culturelive.png"
)

BRAND_COLORS = [
    "#f1572c",  # peach — accent principal
    "#201568",  # grape
    "#3322a7",  # grape light
    "#f18c51",  # melon
    "#dcd8fc",  # gylcine
    "#545455",  # neutral
]

PLOTLY_LAYOUT = dict(
    font=dict(family="Manrope, Outfit, sans-serif", color="#191053", size=13),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="#fafafb",
    colorway=BRAND_COLORS,
    title=dict(font=dict(family="Outfit, sans-serif", size=16, color="#191053")),
    margin=dict(l=24, r=16, t=48, b=24),
    xaxis=dict(
        gridcolor="rgba(25, 16, 83, 0.08)",
        linecolor="rgba(25, 16, 83, 0.12)",
        zerolinecolor="rgba(25, 16, 83, 0.08)",
    ),
    yaxis=dict(
        gridcolor="rgba(25, 16, 83, 0.08)",
        linecolor="rgba(25, 16, 83, 0.12)",
        zerolinecolor="rgba(25, 16, 83, 0.08)",
    ),
    legend=dict(bgcolor="rgba(255,255,255,0.8)", bordercolor="rgba(25,16,83,0.1)"),
)

_CSS_PATH = Path(__file__).with_name("styles.css")


def inject_theme() -> None:
    css = _CSS_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    pio.templates["culturelive"] = go.layout.Template(layout=PLOTLY_LAYOUT)
    pio.templates.default = "culturelive"


def brand_header(*, title: str, tagline: str) -> None:
    st.markdown(
        f"""
        <div class="cl-brand-bar">
          <div class="cl-brand-left">
            <img src="{LOGO_URL}" alt="Culturelive" />
            <div>
              <p class="cl-brand-title">{title}</p>
              <p class="cl-brand-tagline">{tagline}</p>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_title(text: str) -> None:
    st.markdown(f'<p class="cl-section-title">{text}</p>', unsafe_allow_html=True)


def kpi_row(items: list[tuple[str, str | int]]) -> None:
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items, strict=True):
        with col:
            st.metric(label=label, value=value)


def apply_figure_style(fig) -> None:
    fig.update_layout(template="culturelive")
    if hasattr(fig, "update_traces"):
        fig.update_traces(marker_line_width=0)
