"""Composants d'affichage partagés entre la vue manager et la vue commercial."""

from __future__ import annotations

from datetime import date, timedelta
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import api

STATUS_LABELS = {
    "on_track": "Dans le rythme",
    "early": "Début de semaine",
    "watch": "À surveiller",
    "at_risk": "En retard",
}
HEALTH_LABELS = {"ok": "Sain", "at_risk": "À risque", "stale": "Dormant"}
FLAG_LABELS = {
    "no_recent_activity": "Sans activité récente",
    "stuck_in_stage": "Bloqué dans l'étape",
    "close_date_passed": "Date de closing dépassée",
    "no_next_step": "Pas de prochaine étape",
    "next_step_overdue": "Prochaine étape en retard",
}
SEVERITY_LABELS = {"high": "Priorité haute", "medium": "À traiter", "info": "Info", "positive": "Bonne nouvelle"}
SOURCE_LABELS = {
    "outbound": "Prospection",
    "inbound": "Entrant",
    "referral": "Recommandation",
    "event": "Événement",
    "partner": "Partenaire",
}
SEGMENT_LABELS = {"smb": "PME", "mid_market": "ETI", "enterprise": "Grand compte"}
ACTION_KINDS = {
    "nudge": "Nudge",
    "one_to_one": "Point 1:1",
    "call_shadowing": "Écoute d'appels",
    "training": "Micro-training",
    "recognition": "Reconnaissance",
}
POINT_LABELS = {
    "calls": "Appel",
    "emails": "Email",
    "linkedin": "Message LinkedIn",
    "conversations": "Conversation (décroché ou réponse)",
    "meetings_booked": "RDV obtenu",
    "opportunities_created": "Opportunité créée",
    "won_deals": "Deal gagné",
}
METRIC_ORDER = [
    "accounts_touched",
    "calls",
    "emails",
    "linkedin",
    "meetings_booked",
    "opportunities_created",
    "pipeline_created",
]


def eur(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}".replace(",", "\u202f") + "\u00a0€"


def pct(value: float | None, digits: int = 0) -> str:
    return "-" if value is None else f"{value:.{digits}f}%"


def badge(text: str, tone: str) -> str:
    return f'<span class="cl-badge cl-badge-{tone}">{escape(text)}</span>'


def status_badge(status: str) -> str:
    tone = {"on_track": "good", "early": "neutral", "watch": "warn", "at_risk": "bad"}.get(status, "neutral")
    return badge(STATUS_LABELS.get(status, status), tone)


def health_badge(health: str) -> str:
    tone = {"ok": "good", "at_risk": "warn", "stale": "bad"}.get(health, "neutral")
    return badge(HEALTH_LABELS.get(health, health), tone)


def alert_card(alert: dict, key: str, token: str, can_act: bool) -> None:
    tone = {"high": "bad", "medium": "warn", "info": "neutral", "positive": "good"}.get(alert["severity"], "neutral")
    with st.container(border=True):
        st.markdown(
            f"{badge(SEVERITY_LABELS.get(alert['severity'], alert['severity']), tone)} "
            f'<span class="cl-alert-title">{escape(alert["title"])}</span>',
            unsafe_allow_html=True,
        )
        if alert.get("detail"):
            st.caption(alert["detail"])
        st.markdown(f"**Action suggérée :** {alert['suggested_action']}")
        if can_act and alert.get("user_ref"):
            kind_label = ACTION_KINDS.get(alert.get("suggested_kind", "nudge"), "Nudge")
            if st.button(f"Créer l'action ({kind_label})", key=f"alert_{key}"):
                ok, err = api.send(
                    token,
                    "POST",
                    "/coach/actions",
                    {
                        "user_ref": alert["user_ref"],
                        "kind": alert.get("suggested_kind", "nudge"),
                        "title": alert["title"][:250],
                        "note": alert["suggested_action"],
                        "related_metric": alert.get("metric"),
                        "due_on": (date.today() + timedelta(days=3)).isoformat(),
                    },
                )
                if ok:
                    st.toast("Action de coaching créée", icon=None)
                    st.rerun()
                else:
                    st.error(err)


def attainment_bars(rep: dict, metrics: dict[str, str]) -> None:
    """Une barre de progression par indicateur hebdomadaire : réalisé / objectif."""
    for key in METRIC_ORDER:
        target = rep["targets"].get(key)
        if not target:
            continue
        actual = rep["actuals"].get(key, 0)
        ratio = actual / target if target else 0
        value = eur(actual) + " / " + eur(target) if key == "pipeline_created" else f"{actual:.0f} / {target:.0f}"
        st.markdown(
            f'<div class="cl-bar-row"><span>{escape(metrics.get(key, key))}</span><span>{value}</span></div>',
            unsafe_allow_html=True,
        )
        st.progress(min(ratio, 1.0))


def hunting_gauge(value: float, title: str) -> go.Figure:
    color = "#2e9e6b" if value >= 90 else ("#f18c51" if value >= 60 else "#d64545")
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=value,
            number={"suffix": "%", "font": {"size": 34}},
            title={"text": title, "font": {"size": 14}},
            gauge={
                "axis": {"range": [0, 120]},
                "bar": {"color": color},
                "steps": [
                    {"range": [0, 60], "color": "#fbe6e6"},
                    {"range": [60, 90], "color": "#fdeedd"},
                    {"range": [90, 120], "color": "#e3f4ec"},
                ],
                "threshold": {"line": {"color": "#201568", "width": 3}, "value": 100},
            },
        )
    )
    fig.update_layout(height=230, margin=dict(l=20, r=20, t=50, b=10))
    return fig


def leaderboard_frame(board: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Rang": row["rank"],
                "Commercial": row["alias"] + (" (moi)" if row.get("is_me") else ""),
                "Points semaine": row["points_week"],
                "Points 30 j": row["points_30d"],
                "Série (sem.)": row["streak_weeks"],
                "Indice de chasse": row["hunting_index"],
                "Badges": " · ".join(row["badges"]),
            }
            for row in board
        ]
    )


def challenge_card(challenge: dict) -> None:
    with st.container(border=True):
        head = f"**{challenge['name']}**"
        status = "terminé" if challenge["status"] != "active" else f"{challenge['days_left']} j restants"
        st.markdown(f"{head} · {challenge['metric_label']} · {status} · +{challenge['reward_points']} pts")
        if challenge.get("description"):
            st.caption(challenge["description"])
        target = challenge["target"]
        fmt = eur if challenge["metric"] == "pipeline_created" else (lambda v: f"{v:.0f}")
        if challenge["scope"] == "team":
            total = challenge["team_value"]
            st.progress(min(total / target, 1.0) if target else 0.0)
            st.caption(f"Équipe : {fmt(total)} / {fmt(target)}")
        else:
            for row in sorted(challenge["progress"], key=lambda r: -r["value"]):
                label = row["alias"] + (" (moi)" if row.get("is_me") else "")
                st.progress(
                    min(row["value"] / target, 1.0) if target else 0.0,
                    text=f"{label} : {fmt(row['value'])} / {fmt(target)}",
                )


def deals_frame(deals: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Commercial": d["alias"],
                "Opportunité": d["name"],
                "Étape": d["stage_label"],
                "Montant": d["amount"],
                "Pondéré": d["weighted"],
                "Jours sans activité": d["days_since_activity"],
                "Jours dans l'étape": d["days_in_stage"],
                "Closing prévu": d["expected_close_date"],
                "Prochaine étape": d["next_step"] or "(aucune)",
                "Échéance": d["next_step_due"],
                "Santé": HEALTH_LABELS.get(d["health"], d["health"]),
                "Alertes": ", ".join(FLAG_LABELS.get(f, f) for f in d["flags"]),
            }
            for d in deals
        ]
    )


EUR_COLUMN = st.column_config.NumberColumn(format="%d €")
