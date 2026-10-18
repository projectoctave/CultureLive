"""Règles de coaching : transforme les indicateurs en alertes actionnables pour le manager."""

from __future__ import annotations

from typing import Any

from backend import domain as d

SEVERITY_ORDER = {"high": 0, "medium": 1, "positive": 2, "info": 3}


def _eur(value: float) -> str:
    return f"{value:,.0f} €".replace(",", " ")


def _gaps(rep: dict, progress: float, limit: int = 3) -> str:
    items = []
    for key in d.HUNTING_METRICS:
        target = rep["targets"].get(key, 0)
        actual = rep["actuals"].get(key, 0) or 0
        expected = target * progress
        if target and actual < expected:
            items.append((expected - actual, d.HUNTING_METRICS[key]["label"], int(actual), int(target)))
    items.sort(reverse=True)
    return ", ".join(f"{label} {actual}/{target}" for _, label, actual, target in items[:limit])


def build_alerts(summary: dict[str, Any]) -> list[dict[str, Any]]:
    progress = summary["week"]["progress"]
    reps = summary["reps"]
    team = summary["team"]
    pipe_team = summary["pipeline"]["team"]
    alerts: list[dict[str, Any]] = []

    team_touches = [r["ratios"]["touches_per_meeting"] for r in reps if r["ratios"]["touches_per_meeting"]]
    team_touch_avg = sum(team_touches) / len(team_touches) if team_touches else None

    def add(
        rep: dict | None,
        severity: str,
        code: str,
        title: str,
        detail: str,
        action: str,
        kind: str,
        metric: str | None = None,
    ):
        alerts.append(
            {
                "severity": severity,
                "code": code,
                "user_ref": rep["user_ref"] if rep else None,
                "alias": rep["alias"] if rep else "Équipe",
                "title": title,
                "detail": detail,
                "suggested_action": action,
                "suggested_kind": kind,
                "metric": metric,
            }
        )

    coverage = pipe_team.get("coverage")
    if len(reps) > 1 and coverage is not None and coverage < pipe_team["coverage_target"]:
        add(
            None,
            "high" if coverage < 2 else "medium",
            "team_pipeline_coverage",
            f"Couverture du pipe à {coverage:.1f}x (cible {pipe_team['coverage_target']:.0f}x)",
            f"Il manque environ {_eur(pipe_team['pipeline_needed'])} de pipe qualifié pour sécuriser le trimestre "
            f"(reste à faire : {_eur(pipe_team['gap'])}).",
            "Lancer un sprint de prospection ciblée sur les comptes tier A et fixer un objectif de pipe par commercial.",
            "nudge",
            "pipeline_created",
        )

    for rep in reps:
        alias = rep["alias"]
        ratios = rep["ratios"]
        pace = rep["pace_index"]
        att = rep["attainment"]

        if progress >= 0.4 and rep["status"] in ("watch", "at_risk"):
            severity = "high" if rep["status"] == "at_risk" else "medium"
            add(
                rep,
                severity,
                "low_activity",
                f"{alias} est à {pace:.0f}% du rythme de prospection",
                f"Écarts de la semaine : {_gaps(rep, progress) or 'rythme global en retrait'}.",
                "Bloquer deux créneaux de 'power hour' d'appels avant jeudi et faire un point 1:1 de 15 minutes.",
                "one_to_one",
                "hunting_index",
            )

        calls_ratio = (att.get("calls") or 0) / 100 / progress
        accounts_ratio = (att.get("accounts_touched") or 0) / 100 / progress
        if progress >= 0.4 and accounts_ratio < 0.6 and calls_ratio >= 0.8:
            add(
                rep,
                "medium",
                "same_accounts",
                f"{alias} tourne sur les mêmes comptes",
                f"Volume d'appels correct ({att.get('calls')}% de l'objectif) mais seulement {rep['actuals']['accounts_touched']:.0f} "
                f"comptes différents prospectés (objectif {rep['targets']['accounts_touched']:.0f}).",
                "Sortir une liste de 25 nouveaux comptes tier A/B et la dérouler en priorité.",
                "nudge",
                "accounts_touched",
            )

        last2, prev4 = rep["trend"]["last_2_weeks"], rep["trend"]["previous_4_weeks"]
        if last2 is not None and prev4 and prev4 >= 70 and last2 < prev4 * 0.7:
            drop = (1 - last2 / prev4) * 100
            add(
                rep,
                "high" if drop >= 45 else "medium",
                "declining",
                f"Décrochage de {alias} : -{drop:.0f}% d'activité sur 2 semaines",
                f"Indice de chasse {last2:.0f} contre {prev4:.0f} sur les 4 semaines précédentes.",
                "Faire un point 1:1 d'écoute (blocage personnel, motivation, deals perdus ?) avant de parler chiffres.",
                "one_to_one",
                "hunting_index",
            )

        rate = ratios["call_connect_rate"]
        if rate is not None and rate < 8:
            add(
                rep,
                "medium",
                "low_connect_rate",
                f"Taux de contact au téléphone faible pour {alias} ({rate:.0f}%)",
                f"Sur {ratios['touches_4w']} actions des 4 dernières semaines, peu d'appels aboutissent à une conversation.",
                "Revoir les horaires d'appel et la qualité des listes, puis écouter 3 appels ensemble.",
                "call_shadowing",
                "calls",
            )

        tpm = ratios["touches_per_meeting"]
        if tpm and team_touch_avg and tpm > max(35, team_touch_avg * 1.5) and ratios["touches_4w"] >= 100:
            add(
                rep,
                "medium",
                "low_meeting_yield",
                f"{alias} a besoin de {tpm:.0f} actions pour décrocher 1 RDV (équipe : {team_touch_avg:.0f})",
                "Beaucoup d'activité mais peu de transformation : accroche, ciblage ou qualité des messages à revoir.",
                "Micro-training sur l'accroche d'appel et relecture croisée de 5 emails.",
                "training",
                "meetings_booked",
            )
        elif ratios["touches_4w"] >= 100 and ratios["meetings_booked_4w"] == 0:
            add(
                rep,
                "high",
                "no_meeting",
                f"{alias} n'a obtenu aucun RDV en 4 semaines malgré {ratios['touches_4w']} actions",
                "L'activité ne se convertit pas du tout.",
                "Écoute d'appels et revue du ciblage cette semaine.",
                "call_shadowing",
                "meetings_booked",
            )

        share = rep["time_allocation"]["farming_share"]
        if share is not None and share >= 55 and rep["hunting_index"] < 80:
            add(
                rep,
                "medium",
                "farming_drift",
                f"{alias} consacre {share:.0f}% de son temps de RDV à la base clients",
                "Le temps calendrier part sur le portefeuille existant au détriment de la conquête.",
                "Fixer un quota de temps de chasse (ex. 2 demi-journées bloquées) et déléguer le suivi client.",
                "nudge",
                "accounts_touched",
            )

        cov = rep["pipeline"]["coverage"]
        if cov is not None and rep["pipeline"]["gap"] and cov < 2:
            add(
                rep,
                "high" if cov < 1 else "medium",
                "low_coverage",
                f"Pipe insuffisant pour {alias} : {cov:.1f}x le reste à faire",
                f"Reste à faire {_eur(rep['pipeline']['gap'])} sur le trimestre pour {_eur(rep['pipeline']['open_amount'] or 0)} de pipe ouvert.",
                "Objectif de création de pipe sur 3 semaines et revue des comptes tier A sans opportunité.",
                "one_to_one",
                "pipeline_created",
            )

        if rep["pipeline"]["stale_count"] and (
            rep["pipeline"]["stale_count"] >= 2 or (rep["pipeline"]["stale_amount"] or 0) >= 30000
        ):
            add(
                rep,
                "medium",
                "stale_deals",
                f"{rep['pipeline']['stale_count']} deal(s) de {alias} sans mouvement ({_eur(rep['pipeline']['stale_amount'] or 0)})",
                "Aucune activité récente ou étape bloquée depuis trop longtemps.",
                "Pipeline review : relancer, requalifier ou clôturer les deals dormants.",
                "one_to_one",
                None,
            )

        if rep["pipeline"]["next_step_issues"] >= 2:
            add(
                rep,
                "info",
                "next_steps",
                f"{rep['pipeline']['next_step_issues']} deals de {alias} sans prochaine étape à jour",
                "Un deal sans prochaine étape datée est un deal qui glisse.",
                "Exiger une prochaine étape datée sur chaque opportunité avant la prochaine review.",
                "nudge",
                None,
            )

        if progress >= 0.6 and rep["meetings_next_7d"] < 2:
            add(
                rep,
                "medium",
                "empty_agenda",
                f"Agenda prospect quasi vide pour {alias} ({rep['meetings_next_7d']} RDV dans les 7 jours)",
                "Pas de RDV planifiés = pas de pipe dans 2 semaines.",
                "Session de prise de RDV dédiée demain matin.",
                "nudge",
                "meetings_booked",
            )

        a_cov = rep["tier_a_coverage_30d"]
        if a_cov is not None and rep["tier_a_total"] >= 5 and a_cov < 50:
            add(
                rep,
                "medium",
                "tier_a_neglected",
                f"Seuls {a_cov:.0f}% des comptes tier A de {alias} ont été touchés ce mois",
                f"{rep['tier_a_total']} comptes prioritaires dans le portefeuille.",
                "Prioriser le tier A dans la liste d'appel de la semaine.",
                "nudge",
                "accounts_touched",
            )

        if rep["streak_weeks"] >= 3 or rep["hunting_index"] >= 110:
            streak = rep["streak_weeks"]
            add(
                rep,
                "positive",
                "recognition",
                f"À féliciter : {alias}"
                + (f" ({streak} semaines au-dessus de 90%)" if streak >= 3 else " (objectifs dépassés)"),
                "La régularité est le meilleur prédicteur de pipe. Une reconnaissance publique renforce l'habitude.",
                "Féliciter en réunion d'équipe et demander à partager sa routine de prospection.",
                "recognition",
                "hunting_index",
            )
        elif last2 is not None and prev4 and prev4 > 0 and last2 > prev4 * 1.15 and last2 >= 50:
            add(
                rep,
                "positive",
                "ramping_up",
                f"{alias} progresse : +{(last2 / prev4 - 1) * 100:.0f}% d'activité",
                f"Indice de chasse {last2:.0f} contre {prev4:.0f} précédemment.",
                "Encourager et fixer le prochain palier avec lui/elle.",
                "recognition",
                "hunting_index",
            )

    alerts.sort(key=lambda a: (SEVERITY_ORDER[a["severity"]], a["alias"]))
    if not alerts and team["reps_total"]:
        alerts.append(
            {
                "severity": "info",
                "code": "all_good",
                "user_ref": None,
                "alias": "Équipe",
                "title": "Aucune alerte : l'équipe est dans le rythme",
                "detail": "",
                "suggested_action": "Profiter de la semaine pour travailler la qualité (écoutes d'appels, partage de bonnes pratiques).",
                "suggested_kind": "nudge",
                "metric": None,
            }
        )
    return alerts
