"""Vue commercial : ma semaine, mes comptes à appeler, mes deals, mes défis."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import api
from dashboard.branding import kpi_row, section_title
from dashboard.widgets import (
    alert_card,
    attainment_bars,
    challenge_card,
    deals_frame,
    eur,
    hunting_gauge,
    leaderboard_frame,
    status_badge,
)

OUTCOMES = {
    "no_response": "Pas de réponse",
    "conversation": "Conversation",
    "meeting_booked": "RDV obtenu",
    "not_interested": "Pas intéressé",
}
CHANNELS = {"call": "Appel", "email": "Email", "linkedin": "LinkedIn"}


def render(token: str) -> None:
    summary = api.get(token, "/coach/summary")
    tabs = st.tabs(["Ma semaine", "Mes comptes et deals", "Défis et classement", "Rendez-vous"])
    with tabs[0]:
        my_week(token, summary)
    with tabs[1]:
        my_pipeline(token)
    with tabs[2]:
        my_engagement(token)
    with tabs[3]:
        from dashboard.meetings_view import render as render_meetings

        render_meetings(token, manager=False)


def my_week(token: str, summary: dict) -> None:
    if not summary["reps"]:
        st.info("Pas encore de données d'activité.")
        return
    rep = summary["reps"][0]
    week = summary["week"]
    st.caption(f"Semaine du {week['start']} au {week['end']} · {week['progress'] * 100:.0f}% de la semaine écoulée")

    left, right = st.columns([1, 2])
    with left:
        st.plotly_chart(hunting_gauge(rep["hunting_index"], "Mon indice de chasse"), width="stretch")
        st.markdown(status_badge(rep["status"]), unsafe_allow_html=True)
        st.caption(f"Série en cours : {rep['streak_weeks']} semaine(s) au-dessus de 90%")
    with right:
        section_title("Mes objectifs de la semaine")
        attainment_bars(rep, summary["metrics"])

    pipe = rep["pipeline"]
    kpi_row(
        [
            ("RDV planifiés (7 j)", rep["meetings_next_7d"]),
            ("Pipe ouvert", eur(pipe["open_amount"])),
            ("Gagné ce trimestre", eur(pipe["won_qtd"])),
            ("Reste à faire", eur(pipe["gap"])),
            ("Couverture du pipe", f"{pipe['coverage']:.1f}x" if pipe["coverage"] is not None else "-"),
        ]
    )

    col1, col2 = st.columns(2)
    with col1:
        section_title("Mes points d'attention")
        alerts = [a for a in summary["alerts"] if a["code"] != "all_good"]
        if not alerts:
            st.success("Rien à signaler : continue sur ce rythme.")
        for i, alert in enumerate(alerts):
            alert_card(alert, f"me_{i}", token, can_act=False)
    with col2:
        section_title("Mes actions de coaching")
        actions = api.get(token, "/coach/actions", (("status", "open"),))
        if not actions:
            st.info("Aucune action en attente.")
        for action in actions:
            with st.container(border=True):
                st.markdown(f"**{action['kind_label']}** · échéance {action['due_on'] or 'non fixée'}")
                st.markdown(action["title"])
                if action["note"]:
                    st.caption(action["note"])
                if st.button("Marquer comme faite", key=f"done_{action['id']}"):
                    api.send(token, "PATCH", f"/coach/actions/{action['id']}", {"status": "done"})
                    st.rerun()

    log_activity(token)


def log_activity(token: str) -> None:
    accounts = api.get(token, "/coach/accounts", (("stale_days", 1), ("limit", 200)))["items"]
    with st.expander("Saisir une action de prospection"):
        with st.form("log_activity"):
            c1, c2, c3 = st.columns(3)
            channel = c1.selectbox("Canal", list(CHANNELS), format_func=lambda k: CHANNELS[k])
            outcome = c2.selectbox("Résultat", list(OUTCOMES), format_func=lambda k: OUTCOMES[k])
            labels = {"": "(sans compte)"} | {a["ref"]: f"{a['name']} (tier {a['tier']})" for a in accounts}
            account = c3.selectbox("Compte", list(labels), format_func=lambda k: labels[k])
            if st.form_submit_button("Enregistrer"):
                ok, err = api.send(
                    token,
                    "POST",
                    "/coach/activities",
                    {"type": channel, "outcome": outcome, "account_ref": account or None},
                )
                if ok:
                    st.success("Action enregistrée")
                    st.rerun()
                else:
                    st.error(err)


def my_pipeline(token: str) -> None:
    col1, col2 = st.columns([2, 3])
    with col1:
        section_title("Comptes tier A à attaquer")
        stale = st.slider("Sans contact depuis (jours)", 7, 60, 14, key="my_stale_days")
        items = api.get(token, "/coach/accounts", (("stale_days", stale), ("limit", 25)))["items"]
        if not items:
            st.success("Tous tes comptes prioritaires ont été touchés récemment.")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Compte": a["name"],
                            "Secteur": a["industry"],
                            "Tier": a["tier"],
                            "Dernier contact": "Jamais" if a["never_touched"] else f"il y a {a['days_since_touch']} j",
                        }
                        for a in items
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
    with col2:
        section_title("Mes deals à relancer")
        data = api.get(token, "/coach/pipeline")
        deals = [d for d in data["deals"] if d["health"] != "ok"]
        st.caption(f"{data['open']['count']} deals ouverts pour {eur(data['open']['amount'])}.")
        if not deals:
            st.success("Tous tes deals sont à jour.")
        else:
            st.dataframe(
                deals_frame(deals).drop(columns=["Commercial"]),
                width="stretch",
                hide_index=True,
                column_config={
                    "Montant": st.column_config.NumberColumn(format="%d €"),
                    "Pondéré": st.column_config.NumberColumn(format="%d €"),
                },
            )


def my_engagement(token: str) -> None:
    data = api.get(token, "/coach/engagement")
    me = next((r for r in data["leaderboard"] if r.get("is_me")), None)
    if me:
        kpi_row(
            [
                ("Mon rang", f"{me['rank']} / {len(data['leaderboard'])}"),
                ("Points cette semaine", me["points_week"]),
                ("Points 30 jours", me["points_30d"]),
                ("Mes badges", len(me["badges"])),
            ]
        )
        if me["badges"]:
            st.markdown(" · ".join(me["badges"]))
    col1, col2 = st.columns([3, 2])
    with col1:
        section_title("Classement de l'équipe")
        st.dataframe(leaderboard_frame(data["leaderboard"]), width="stretch", hide_index=True)
    with col2:
        section_title("Défis en cours")
        for challenge in data["challenges"]:
            challenge_card(challenge)
