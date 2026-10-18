"""Vocabulaire métier du pilotage commercial (prospection, pipeline, coaching)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

ACTIVITY_TYPES = ("call", "email", "linkedin")
OUTCOMES = ("no_response", "conversation", "meeting_booked", "not_interested")
CONVERSATION_OUTCOMES = ("conversation", "meeting_booked", "not_interested")

ACCOUNT_KINDS = ("prospect", "customer")
ACCOUNT_STATUSES = ("active", "disqualified")
ACCOUNT_TIERS = ("A", "B", "C")
ACCOUNT_SEGMENTS = ("smb", "mid_market", "enterprise")
LEAD_SOURCES = ("outbound", "inbound", "referral", "event", "partner")

OPEN_STAGES = ("qualified", "discovery", "proposal", "negotiation")
STAGE_WON = "won"
STAGE_LOST = "lost"
ALL_STAGES = (*OPEN_STAGES, STAGE_WON, STAGE_LOST)

STAGE_LABELS = {
    "qualified": "Qualifié",
    "discovery": "Découverte",
    "proposal": "Proposition",
    "negotiation": "Négociation",
    "won": "Gagné",
    "lost": "Perdu",
}
STAGE_PROBABILITY = {
    "qualified": 0.10,
    "discovery": 0.25,
    "proposal": 0.50,
    "negotiation": 0.75,
    "won": 1.0,
    "lost": 0.0,
}
STAGE_STALE_DAYS = {"qualified": 14, "discovery": 14, "proposal": 21, "negotiation": 21}
STALE_ACTIVITY_DAYS = 14

LOST_REASONS = {
    "no_budget": "Pas de budget",
    "competitor": "Concurrent retenu",
    "no_decision": "Pas de décision (statu quo)",
    "bad_timing": "Mauvais timing",
    "no_champion": "Pas de sponsor interne",
}

COACHING_KINDS = {
    "nudge": "Nudge",
    "one_to_one": "Point 1:1",
    "call_shadowing": "Écoute d'appels",
    "training": "Micro-training",
    "recognition": "Reconnaissance",
}
COACHING_STATUSES = ("open", "done", "dismissed")

# Indicateurs hebdomadaires suivis (clé -> libellé, poids dans l'indice de chasse).
HUNTING_METRICS: dict[str, dict] = {
    "accounts_touched": {"label": "Comptes prospectés", "weight": 0.20},
    "calls": {"label": "Appels", "weight": 0.15},
    "emails": {"label": "Emails", "weight": 0.10},
    "linkedin": {"label": "Messages LinkedIn", "weight": 0.05},
    "meetings_booked": {"label": "RDV obtenus", "weight": 0.30},
    "opportunities_created": {"label": "Opportunités créées", "weight": 0.20},
}
ATTAINMENT_CAP = 1.2

# Autres indicateurs ciblables (hors indice de chasse).
OTHER_TARGET_METRICS = {
    "pipeline_created": {"label": "Pipe généré (€)", "period": "week"},
    "revenue_won": {"label": "CA gagné (€)", "period": "quarter"},
}

DEFAULT_WEEKLY_TARGETS = {
    "accounts_touched": 25,
    "calls": 40,
    "emails": 40,
    "linkedin": 20,
    "meetings_booked": 4,
    "opportunities_created": 2,
    "pipeline_created": 30000,
}
DEFAULT_QUARTER_QUOTA = 120000
PIPELINE_COVERAGE_TARGET = 3.0

POINTS = {
    "calls": 1,
    "emails": 1,
    "linkedin": 1,
    "conversations": 3,
    "meetings_booked": 15,
    "opportunities_created": 30,
    "won_deals": 60,
}

CHALLENGE_METRICS = {
    "calls": "Appels",
    "accounts_touched": "Comptes prospectés",
    "conversations": "Conversations",
    "meetings_booked": "RDV obtenus",
    "opportunities_created": "Opportunités créées",
    "pipeline_created": "Pipe généré (€)",
    "won_deals": "Deals gagnés",
}

HUNTING_MEETING_CATEGORIES = ("discovery_call", "demo", "negotiation")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def week_start(value: datetime | date) -> date:
    d = value.date() if isinstance(value, datetime) else value
    return d - timedelta(days=d.weekday())


def week_progress(as_of: datetime) -> float:
    """Part de la semaine de travail écoulée (0.2 minimum, 1.0 le week-end)."""
    weekday = as_of.weekday()
    if weekday >= 5:
        return 1.0
    return min(1.0, max(0.2, (weekday + as_of.hour / 24) / 5))


def quarter_bounds(value: date) -> tuple[date, date]:
    first_month = 3 * ((value.month - 1) // 3) + 1
    start = date(value.year, first_month, 1)
    end_month = first_month + 3
    end = date(value.year + (end_month > 12), (end_month - 1) % 12 + 1, 1) - timedelta(days=1)
    return start, end
