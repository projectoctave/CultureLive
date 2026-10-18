"""Vue manager : tour de contrôle, prospection, pipeline, motivation, coaching."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dashboard import api
from dashboard.branding import BRAND_COLORS, apply_figure_style, kpi_row, section_title
from dashboard.widgets import (
    ACTION_KINDS,
    FLAG_LABELS,
    HEALTH_LABELS,
    METRIC_ORDER,
    POINT_LABELS,
    SEGMENT_LABELS,
    SEVERITY_LABELS,
    SOURCE_LABELS,
    STATUS_LABELS,
    alert_card,
    challenge_card,
    deals_frame,
    eur,
    leaderboard_frame,
    pct,
)

PEACH, GRAPE, GRAPE_LIGHT, MELON = BRAND_COLORS[0], BRAND_COLORS[1], BRAND_COLORS[2], BRAND_COLORS[3]


def render(token: str) -> None:
    summary = api.get(token, "/coach/summary")
    tabs = st.tabs(["Tour de contrôle", "Prospection", "Pipeline", "Motivation", "Coaching", "Rendez-vous"])
    with tabs[0]:
        control_tower(token, summary)
    with tabs[1]:
        prospecting(token, summary)
    with tabs[2]:
        pipeline(token, summary)
    with tabs[3]:
        motivation(token, summary)
    with tabs[4]:
        coaching(token, summary)
    with tabs[5]:
        from dashboard.meetings_view import render as render_meetings

        render_meetings(token, manager=True)


def _week_caption(summary: dict) -> str:
    week = summary["week"]
    return f"Semaine du {week['start']} au {week['end']} · {week['progress'] * 100:.0f}% de la semaine écoulée"


def control_tower(token: str, summary: dict) -> None:
    team, pipe = summary["team"], summary["pipeline"]["team"]
    st.caption(_week_caption(summary))
    coverage = pipe.get("coverage")
    kpi_row(
        [
            ("Indice de chasse équipe", pct(team["hunting_index"])),
            ("Dans le rythme", f"{team['reps_on_track']} / {team['reps_total']}"),
            ("En retard", team["reps_at_risk"]),
            ("Couverture du pipe", f"{coverage:.1f}x" if coverage is not None else "-"),
            ("RDV planifiés (7 j)", team["meetings_next_7d"]),
        ]
    )
    st.caption(
        "L'indice de chasse pondère comptes prospectés, appels, emails, LinkedIn, RDV obtenus et opportunités "
        "créées face aux objectifs hebdomadaires (100% = objectifs atteints)."
    )

    left, right = st.columns([3, 2])
    with left:
        section_title("Alertes et actions à mener")
        alerts = summary["alerts"]
        severities = [s for s in SEVERITY_LABELS if any(a["severity"] == s for a in alerts)]
        picked = st.multiselect(
            "Filtrer par niveau",
            options=severities,
            default=[s for s in severities if s != "info"],
            format_func=lambda s: SEVERITY_LABELS[s],
        )
        shown = [a for a in alerts if a["severity"] in picked]
        if not shown:
            st.info("Aucune alerte pour ce filtre.")
        for i, alert in enumerate(shown):
            alert_card(alert, f"{i}_{alert['code']}_{alert.get('user_ref')}", token, can_act=True)
    with right:
        section_title("Indice de chasse par semaine")
        weekly = pd.DataFrame(summary["weekly"])
        if not weekly.empty:
            fig = px.line(weekly, x="week_start", y="hunting_index", color="alias", markers=True)
            fig.add_hline(y=100, line_dash="dot", line_color=GRAPE, annotation_text="Objectif")
            fig.update_layout(yaxis_title="Indice", xaxis_title=None, legend_title=None, height=380)
            apply_figure_style(fig)
            st.plotly_chart(fig, width="stretch")

    section_title("Équipe cette semaine : réalisé contre objectif")
    metrics = summary["metrics"]
    rows = []
    for rep in summary["reps"]:
        row = {
            "Commercial": rep["alias"],
            "Statut": STATUS_LABELS.get(rep["status"], rep["status"]),
            "Indice": rep["hunting_index"],
            "Rythme": rep["pace_index"],
            "Série (sem.)": rep["streak_weeks"],
        }
        for key in METRIC_ORDER:
            row[metrics[key]] = rep["attainment"].get(key)
        rows.append(row)
    frame = pd.DataFrame(rows)
    pct_cols = {
        col: st.column_config.ProgressColumn(col, format="%d%%", min_value=0, max_value=120)
        for col in frame.columns
        if col not in ("Commercial", "Statut", "Série (sem.)")
    }
    st.dataframe(frame, width="stretch", hide_index=True, column_config=pct_cols)


def prospecting(token: str, summary: dict) -> None:
    st.caption("Mesure de l'effort de conquête : volume, qualité, couverture des comptes prioritaires.")
    weekly = pd.DataFrame(summary["weekly"])
    reps = summary["reps"]

    col1, col2 = st.columns(2)
    with col1:
        section_title("Volume d'activité par semaine")
        if not weekly.empty:
            by_week = weekly.groupby("week_start")[["calls", "emails", "linkedin"]].sum().reset_index()
            melted = by_week.melt("week_start", var_name="Canal", value_name="Actions")
            melted["Canal"] = melted["Canal"].map({"calls": "Appels", "emails": "Emails", "linkedin": "LinkedIn"})
            fig = px.bar(
                melted, x="week_start", y="Actions", color="Canal", color_discrete_sequence=[PEACH, GRAPE, MELON]
            )
            fig.update_layout(xaxis_title=None, legend_title=None, height=340)
            apply_figure_style(fig)
            st.plotly_chart(fig, width="stretch")
    with col2:
        section_title("RDV obtenus et opportunités créées")
        if not weekly.empty:
            by_week = weekly.groupby("week_start")[["meetings_booked", "opportunities_created"]].sum().reset_index()
            fig = go.Figure()
            fig.add_bar(x=by_week["week_start"], y=by_week["meetings_booked"], name="RDV obtenus", marker_color=PEACH)
            fig.add_scatter(
                x=by_week["week_start"],
                y=by_week["opportunities_created"],
                name="Opportunités créées",
                mode="lines+markers",
                line=dict(color=GRAPE, width=3),
            )
            fig.update_layout(height=340, legend_title=None)
            apply_figure_style(fig)
            st.plotly_chart(fig, width="stretch")

    col1, col2 = st.columns(2)
    with col1:
        section_title("Entonnoir de conquête (12 semaines)")
        funnel = summary["funnel"]
        choice = st.selectbox("Périmètre", ["Équipe"] + [r["alias"] for r in reps], key="funnel_scope")
        steps = funnel["team"]
        if choice != "Équipe":
            ref = next(r["user_ref"] for r in reps if r["alias"] == choice)
            steps = funnel["by_user"].get(ref, steps)
        fig = go.Figure(
            go.Funnel(
                y=[s["label"] for s in steps],
                x=[s["count"] for s in steps],
                textinfo="value+percent previous",
                marker={"color": [GRAPE, GRAPE_LIGHT, "#6a5bd1", MELON, PEACH, "#2e9e6b"]},
            )
        )
        fig.update_layout(height=380)
        apply_figure_style(fig)
        st.plotly_chart(fig, width="stretch")
    with col2:
        section_title("Où se fait le gain de productivité ?")
        ratios = pd.DataFrame(
            [
                {
                    "Commercial": r["alias"],
                    "Taux de contact appels": r["ratios"]["call_connect_rate"],
                    "Actions par RDV": r["ratios"]["touches_per_meeting"],
                    "RDV 4 sem.": r["ratios"]["meetings_booked_4w"],
                    "RDV vers opportunité": r["ratios"]["meeting_to_opportunity"],
                    "Comptes tier A touchés (30 j)": r["tier_a_coverage_30d"],
                }
                for r in reps
            ]
        )
        st.dataframe(
            ratios,
            width="stretch",
            hide_index=True,
            column_config={
                "Taux de contact appels": st.column_config.NumberColumn(format="%.1f%%"),
                "RDV vers opportunité": st.column_config.NumberColumn(format="%.0f%%"),
                "Comptes tier A touchés (30 j)": st.column_config.ProgressColumn(
                    format="%d%%", min_value=0, max_value=100
                ),
            },
        )
        st.caption(
            "Beaucoup d'actions par RDV : problème de ciblage ou de message. Faible taux de contact : travailler les "
            "horaires et le script d'accroche. Peu de RDV vers opportunité : revoir la qualification."
        )
        section_title("Répartition du temps en rendez-vous (4 semaines)")
        alloc = pd.DataFrame(
            [
                {
                    "Commercial": r["alias"],
                    "Prospection / vente": r["time_allocation"]["selling"],
                    "Clients (farming)": r["time_allocation"]["farming"],
                    "Interne": r["time_allocation"]["internal"],
                }
                for r in reps
            ]
        ).melt("Commercial", var_name="Type", value_name="Heures")
        fig = px.bar(
            alloc,
            y="Commercial",
            x="Heures",
            color="Type",
            orientation="h",
            barmode="stack",
            color_discrete_sequence=[PEACH, GRAPE, "#c9c4f2"],
        )
        fig.update_layout(height=300, legend_title=None, yaxis_title=None)
        apply_figure_style(fig)
        st.plotly_chart(fig, width="stretch")

    section_title("Comptes à attaquer : tier A sans contact récent")
    stale_days = st.slider("Sans contact depuis (jours)", 7, 60, 14, key="whitespace_days")
    accounts = api.get(token, "/coach/accounts", (("stale_days", stale_days), ("limit", 200)))["items"]
    frame = pd.DataFrame(accounts)
    if frame.empty:
        st.success("Tous les comptes prioritaires ont été touchés récemment.")
        return
    options = ["(tous)"] + sorted(frame["alias"].unique())
    owner = st.selectbox("Commercial", options, key="whitespace_owner")
    if owner != "(tous)":
        frame = frame[frame["alias"] == owner]
    frame = frame.assign(
        segment=frame["segment"].map(SEGMENT_LABELS),
        source=frame["source"].map(SOURCE_LABELS).fillna(frame["source"]),
        statut=frame.apply(
            lambda r: (
                "Jamais contacté" if r["never_touched"] else f"Dernier contact il y a {int(r['days_since_touch'])} j"
            ),
            axis=1,
        ),
    )
    st.dataframe(
        frame[["alias", "name", "industry", "segment", "tier", "source", "statut"]].rename(
            columns={
                "alias": "Commercial",
                "name": "Compte",
                "industry": "Secteur",
                "segment": "Segment",
                "tier": "Tier",
                "source": "Origine",
                "statut": "Statut",
            }
        ),
        width="stretch",
        hide_index=True,
    )


def pipeline(token: str, summary: dict) -> None:
    data = api.get(token, "/coach/pipeline")
    team, opened, winloss = data["team"], data["open"], data["win_loss"]
    quarter = data["quarter"]
    st.caption(
        f"Trimestre du {quarter['start']} au {quarter['end']} · {quarter['days_left']} jours restants · "
        f"cible de couverture {team['coverage_target']:.0f}x le reste à faire"
    )
    kpi_row(
        [
            ("Quota trimestre", eur(team["quarter_quota"])),
            ("Gagné à date", eur(team["won_qtd"])),
            ("Reste à faire", eur(team["gap"])),
            ("Pipe ouvert (trimestre)", eur(team["open_in_quarter"])),
            ("Couverture", f"{team['coverage']:.1f}x" if team["coverage"] is not None else "-"),
        ]
    )
    if team["pipeline_needed"] > 0:
        st.warning(
            f"Il manque environ {eur(team['pipeline_needed'])} de pipe qualifié à closer ce trimestre pour atteindre "
            f"{team['coverage_target']:.0f}x le reste à faire. Ce pipe se crée par la prospection d'aujourd'hui."
        )
    else:
        st.success("La couverture du pipe est au niveau cible.")

    col1, col2 = st.columns(2)
    with col1:
        section_title("Pipe par étape")
        stages = pd.DataFrame(data["by_stage"])
        fig = go.Figure()
        fig.add_bar(x=stages["label"], y=stages["amount"], name="Montant", marker_color=GRAPE)
        fig.add_bar(x=stages["label"], y=stages["weighted"], name="Pondéré", marker_color=PEACH)
        fig.update_layout(barmode="group", height=340, legend_title=None)
        apply_figure_style(fig)
        st.plotly_chart(fig, width="stretch")
    with col2:
        section_title("Couverture par commercial")
        reps = pd.DataFrame(data["by_rep"])
        if not reps.empty:
            reps["coverage"] = reps["coverage"].fillna(0)
            colors = [PEACH if c < team["coverage_target"] else "#2e9e6b" for c in reps["coverage"]]
            fig = go.Figure(go.Bar(x=reps["alias"], y=reps["coverage"], marker_color=colors))
            fig.add_hline(y=team["coverage_target"], line_dash="dot", line_color=GRAPE, annotation_text="Cible")
            fig.update_layout(height=340, yaxis_title="x le reste à faire")
            apply_figure_style(fig)
            st.plotly_chart(fig, width="stretch")

    section_title("Quota par commercial")
    if data["by_rep"]:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Commercial": r["alias"],
                        "Quota": r["quarter_quota"],
                        "Gagné": r["won_qtd"],
                        "Reste à faire": r["gap"],
                        "Pipe trimestre": r["open_in_quarter"],
                        "Couverture": r["coverage"],
                        "Deals dormants": r["stale_count"],
                        "Montant dormant": r["stale_amount"],
                        "Sans prochaine étape": r["next_step_issues"],
                    }
                    for r in data["by_rep"]
                ]
            ),
            width="stretch",
            hide_index=True,
            column_config={
                "Quota": st.column_config.NumberColumn(format="%d €"),
                "Gagné": st.column_config.NumberColumn(format="%d €"),
                "Reste à faire": st.column_config.NumberColumn(format="%d €"),
                "Pipe trimestre": st.column_config.NumberColumn(format="%d €"),
                "Montant dormant": st.column_config.NumberColumn(format="%d €"),
                "Couverture": st.column_config.NumberColumn(format="%.1fx"),
            },
        )

    section_title("Deals à reprendre en main")
    st.caption(
        f"{opened['count']} deals ouverts pour {eur(opened['amount'])} (pondéré {eur(opened['weighted'])}). "
        f"{opened['stale_count']} dormants pour {eur(opened['stale_amount'])}."
    )
    f1, f2, f3 = st.columns(3)
    health = f1.multiselect(
        "Santé", options=list(HEALTH_LABELS), default=["stale", "at_risk"], format_func=lambda h: HEALTH_LABELS[h]
    )
    owners = f2.multiselect("Commercial", options=sorted({d["alias"] for d in data["deals"]}))
    flags = f3.multiselect("Alerte", options=list(FLAG_LABELS), format_func=lambda f: FLAG_LABELS[f])
    deals = [
        d
        for d in data["deals"]
        if d["health"] in health
        and (not owners or d["alias"] in owners)
        and (not flags or any(f in d["flags"] for f in flags))
    ]
    if deals:
        st.dataframe(
            deals_frame(deals),
            width="stretch",
            hide_index=True,
            column_config={
                "Montant": st.column_config.NumberColumn(format="%d €"),
                "Pondéré": st.column_config.NumberColumn(format="%d €"),
            },
        )
    else:
        st.success("Aucun deal ne correspond à ces critères.")

    col1, col2 = st.columns(2)
    with col1:
        section_title(f"Gagné / perdu ({winloss['window_days']} jours)")
        kpi_row(
            [
                ("Taux de réussite", pct(winloss["win_rate"], 1)),
                ("Deal moyen", eur(winloss["avg_deal"])),
                ("Cycle moyen", f"{winloss['avg_cycle_days']:.0f} j" if winloss["avg_cycle_days"] else "-"),
            ]
        )
        reasons = pd.DataFrame(winloss["lost_reasons"])
        if not reasons.empty:
            fig = px.bar(reasons, x="count", y="label", orientation="h", color_discrete_sequence=[PEACH])
            fig.update_layout(height=300, yaxis_title=None, xaxis_title="Deals perdus", yaxis={"autorange": "reversed"})
            apply_figure_style(fig)
            st.plotly_chart(fig, width="stretch")
    with col2:
        section_title("Conversion entre étapes")
        conv = pd.DataFrame(data["stage_conversion"])
        if not conv.empty:
            conv["Transition"] = conv["from_label"] + " vers " + conv["to_label"]
            fig = px.bar(conv, x="Transition", y="rate", color_discrete_sequence=[GRAPE])
            fig.update_layout(height=340, yaxis_title="% de passage", xaxis_title=None)
            apply_figure_style(fig)
            st.plotly_chart(fig, width="stretch")


def motivation(token: str, summary: dict) -> None:
    data = api.get(token, "/coach/engagement")
    col1, col2 = st.columns([3, 2])
    with col1:
        section_title("Classement : l'effort qui compte")
        st.dataframe(
            leaderboard_frame(data["leaderboard"]),
            width="stretch",
            hide_index=True,
            column_config={
                "Indice de chasse": st.column_config.ProgressColumn(format="%d%%", min_value=0, max_value=120),
            },
        )
        st.caption(
            "Les points récompensent les résultats de prospection (RDV, opportunités, deals) plus que le simple "
            "volume. Pseudonymes uniquement : aucune donnée nominative."
        )
    with col2:
        section_title("Barème de points")
        st.dataframe(
            pd.DataFrame([{"Action": POINT_LABELS.get(k, k), "Points": v} for k, v in data["points_rules"].items()]),
            width="stretch",
            hide_index=True,
        )

    section_title("Challenges")
    challenges = data["challenges"]
    if not challenges:
        st.info("Aucun challenge en cours.")
    for i in range(0, len(challenges), 2):
        cols = st.columns(2)
        for col, ch in zip(cols, challenges[i : i + 2], strict=False):
            with col:
                challenge_card(ch)

    with st.expander("Lancer un nouveau challenge"):
        with st.form("new_challenge"):
            name = st.text_input("Nom", placeholder="Sprint comptes tier A")
            description = st.text_area("Description", height=70)
            c1, c2, c3 = st.columns(3)
            metric = c1.selectbox(
                "Indicateur",
                options=[
                    "calls",
                    "accounts_touched",
                    "conversations",
                    "meetings_booked",
                    "opportunities_created",
                    "pipeline_created",
                    "won_deals",
                ],
                format_func=lambda m: {
                    "calls": "Appels",
                    "accounts_touched": "Comptes prospectés",
                    "conversations": "Conversations",
                    "meetings_booked": "RDV obtenus",
                    "opportunities_created": "Opportunités créées",
                    "pipeline_created": "Pipe généré (€)",
                    "won_deals": "Deals gagnés",
                }[m],
            )
            scope = c2.selectbox(
                "Portée", ["individual", "team"], format_func=lambda s: "Individuel" if s == "individual" else "Équipe"
            )
            target = c3.number_input("Objectif", min_value=1.0, value=10.0, step=1.0)
            d1, d2, d3 = st.columns(3)
            starts = d1.date_input("Début", value=date.today())
            ends = d2.date_input("Fin", value=date.today() + timedelta(days=14))
            reward = d3.number_input("Points offerts", min_value=0, value=100, step=10)
            if st.form_submit_button("Créer le challenge"):
                ok, err = api.send(
                    token,
                    "POST",
                    "/coach/challenges",
                    {
                        "name": name,
                        "description": description or None,
                        "metric": metric,
                        "scope": scope,
                        "target_value": target,
                        "starts_on": starts.isoformat(),
                        "ends_on": ends.isoformat(),
                        "reward_points": int(reward),
                    },
                )
                if ok:
                    st.rerun()
                else:
                    st.error(err)


def coaching(token: str, summary: dict) -> None:
    reps = summary["reps"]
    aliases = {r["user_ref"]: r["alias"] for r in reps}
    left, right = st.columns([3, 2])

    with left:
        section_title("Plan de coaching")
        who = st.selectbox("Commercial", ["(tous)"] + list(aliases.values()), key="coach_filter")
        params = ()
        if who != "(tous)":
            ref = next(k for k, v in aliases.items() if v == who)
            params = (("user_ref", ref),)
        actions = api.get(token, "/coach/actions", params + (("status", "open"),))
        if not actions:
            st.info("Aucune action ouverte.")
        for action in actions:
            overdue = action["due_on"] and action["due_on"] < date.today().isoformat()
            with st.container(border=True):
                st.markdown(
                    f"**{action['kind_label']}** · {action['alias']} · "
                    f"échéance {action['due_on'] or 'non fixée'}" + (" · **en retard**" if overdue else "")
                )
                st.markdown(action["title"])
                if action["note"]:
                    st.caption(action["note"])
                c1, c2, _ = st.columns([1, 1, 3])
                if c1.button("Terminée", key=f"done_{action['id']}"):
                    api.send(token, "PATCH", f"/coach/actions/{action['id']}", {"status": "done"})
                    st.rerun()
                if c2.button("Ignorer", key=f"skip_{action['id']}"):
                    api.send(token, "PATCH", f"/coach/actions/{action['id']}", {"status": "dismissed"})
                    st.rerun()

        with st.expander("Nouvelle action de coaching"):
            with st.form("new_action"):
                c1, c2 = st.columns(2)
                rep = c1.selectbox("Commercial", list(aliases.values()), key="new_action_rep")
                kind = c2.selectbox("Type", list(ACTION_KINDS), format_func=lambda k: ACTION_KINDS[k])
                title = st.text_input("Titre")
                note = st.text_area("Consigne", height=70)
                due = st.date_input("Échéance", value=date.today() + timedelta(days=3))
                if st.form_submit_button("Créer l'action"):
                    ref = next(k for k, v in aliases.items() if v == rep)
                    ok, err = api.send(
                        token,
                        "POST",
                        "/coach/actions",
                        {
                            "user_ref": ref,
                            "kind": kind,
                            "title": title,
                            "note": note or None,
                            "due_on": due.isoformat(),
                        },
                    )
                    if ok:
                        st.rerun()
                    else:
                        st.error(err)

    with right:
        section_title("Objectifs hebdomadaires")
        st.caption("Les objectifs individuels remplacent les objectifs par défaut de l'équipe.")
        scope = st.selectbox("Périmètre", ["Défaut équipe"] + list(aliases.values()), key="target_scope")
        current = reps[0]["targets"] if reps else {}
        if scope != "Défaut équipe":
            current = next(r for r in reps if r["alias"] == scope)["targets"]
        labels = summary["metrics"]
        with st.form("targets"):
            values = {}
            for key in METRIC_ORDER:
                values[key] = st.number_input(
                    labels[key], min_value=0.0, value=float(current.get(key, 0)), step=1.0, key=f"t_{scope}_{key}"
                )
            if st.form_submit_button("Enregistrer les objectifs"):
                ref = None if scope == "Défaut équipe" else next(k for k, v in aliases.items() if v == scope)
                errors = []
                for key, value in values.items():
                    ok, err = api.send(
                        token,
                        "PUT",
                        "/coach/targets",
                        {"user_ref": ref, "metric": key, "period": "week", "target_value": value},
                    )
                    if not ok:
                        errors.append(err)
                if errors:
                    st.error(errors[0])
                else:
                    st.success("Objectifs enregistrés")
                    st.rerun()
