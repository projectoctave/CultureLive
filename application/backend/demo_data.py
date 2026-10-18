"""Jeu de données fictif réaliste pour le pilotage commercial.

Chaque commercial incarne un profil type, afin que le dashboard raconte des histoires de coaching concrètes :
chasseur régulier, commercial en décrochage, junior en montée en charge, volume sans qualité, account manager
qui ne chasse plus, closer à fort panier. La simulation reconstitue 12 semaines d'activité (appels, emails,
messages LinkedIn), les RDV calendrier, les opportunités avec leur historique d'étapes, des objectifs, des
challenges et des actions de coaching.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend import domain as d
from backend.db.models import (
    Account,
    Activity,
    AppUser,
    Challenge,
    CoachingAction,
    DashboardAccount,
    MeetingClassification,
    Opportunity,
    OpportunityStageEvent,
    Organization,
    SalesTarget,
)
from backend.services.auth import DashboardRole, hash_password
from backend.services.referential import ensure_active_referential

HISTORY_WEEKS = 12
SHOW_RATE = 0.88


@dataclass(frozen=True)
class Persona:
    key: str
    description: str
    calls: float
    emails: float
    linkedin: float
    accounts: int
    call_connect: float
    email_reply: float
    linkedin_reply: float
    meeting_rate: float
    opp_rate: float
    win_rate: float
    deal_size: float
    tier_a_bias: float
    farming_activities: int = 8
    customer_hours: float = 2.0
    stale_rate: float = 0.12
    no_next_step_rate: float = 0.1
    expansion_deals: int = 1
    legacy_deals: int = 8
    trend: tuple[float, ...] = (1.0,) * HISTORY_WEEKS
    target_scale: float = 1.0
    quarter_quota: float = d.DEFAULT_QUARTER_QUOTA


def _fading() -> tuple[float, ...]:
    return (1.08, 1.1, 1.05, 1.1, 1.05, 1.0, 0.95, 0.85, 0.7, 0.55, 0.42, 0.36)


def _rising() -> tuple[float, ...]:
    return tuple(round(0.35 + 0.06 * i, 3) for i in range(HISTORY_WEEKS))


PERSONAS: dict[str, Persona] = {
    "hunter_star": Persona(
        "hunter_star",
        "Chasseur régulier : atteint ses objectifs semaine après semaine.",
        calls=46,
        emails=44,
        linkedin=22,
        accounts=27,
        call_connect=0.17,
        email_reply=0.07,
        linkedin_reply=0.12,
        meeting_rate=0.34,
        opp_rate=0.58,
        win_rate=0.36,
        deal_size=21000,
        tier_a_bias=0.7,
        stale_rate=0.06,
        expansion_deals=1,
    ),
    "steady": Persona(
        "steady",
        "Solide et régulier : un cran sous les objectifs, bonne base à faire progresser.",
        calls=40,
        emails=40,
        linkedin=18,
        accounts=23,
        call_connect=0.15,
        email_reply=0.06,
        linkedin_reply=0.1,
        meeting_rate=0.34,
        opp_rate=0.5,
        win_rate=0.3,
        deal_size=15000,
        tier_a_bias=0.55,
        stale_rate=0.14,
    ),
    "fading": Persona(
        "fading",
        "Ancien top performer en décrochage depuis 3 semaines.",
        calls=46,
        emails=44,
        linkedin=22,
        accounts=27,
        call_connect=0.16,
        email_reply=0.07,
        linkedin_reply=0.11,
        meeting_rate=0.32,
        opp_rate=0.55,
        win_rate=0.34,
        deal_size=17000,
        tier_a_bias=0.6,
        stale_rate=0.35,
        no_next_step_rate=0.3,
        trend=_fading(),
    ),
    "newbie": Persona(
        "newbie",
        "Junior en montée en charge : évite le téléphone, progresse chaque semaine.",
        calls=20,
        emails=56,
        linkedin=10,
        accounts=13,
        call_connect=0.07,
        email_reply=0.04,
        linkedin_reply=0.08,
        meeting_rate=0.28,
        opp_rate=0.4,
        win_rate=0.16,
        deal_size=11000,
        tier_a_bias=0.3,
        stale_rate=0.2,
        no_next_step_rate=0.25,
        trend=_rising(),
        target_scale=0.6,
        quarter_quota=70000,
        expansion_deals=0,
        legacy_deals=0,
    ),
    "spray": Persona(
        "spray",
        "Gros volume, peu de qualité : beaucoup d'actions, très peu de RDV.",
        calls=88,
        emails=118,
        linkedin=56,
        accounts=75,
        call_connect=0.045,
        email_reply=0.02,
        linkedin_reply=0.04,
        meeting_rate=0.14,
        opp_rate=0.3,
        win_rate=0.14,
        deal_size=9000,
        tier_a_bias=0.1,
        stale_rate=0.25,
        no_next_step_rate=0.3,
        expansion_deals=0,
        legacy_deals=6,
    ),
    "farmer": Persona(
        "farmer",
        "Account manager dans l'âme : la base clients prend tout le temps, la conquête est à l'arrêt.",
        calls=11,
        emails=14,
        linkedin=4,
        accounts=8,
        call_connect=0.2,
        email_reply=0.1,
        linkedin_reply=0.1,
        meeting_rate=0.3,
        opp_rate=0.5,
        win_rate=0.45,
        deal_size=21000,
        tier_a_bias=0.5,
        farming_activities=62,
        customer_hours=14.0,
        stale_rate=0.2,
        expansion_deals=4,
    ),
    "closer": Persona(
        "closer",
        "Closer à fort panier : moins de volume mais une transformation et des tickets élevés.",
        calls=30,
        emails=28,
        linkedin=14,
        accounts=17,
        call_connect=0.19,
        email_reply=0.09,
        linkedin_reply=0.13,
        meeting_rate=0.42,
        opp_rate=0.62,
        win_rate=0.44,
        deal_size=42000,
        tier_a_bias=0.75,
        stale_rate=0.05,
        quarter_quota=160000,
    ),
}

DEMO_ORGS = [
    {
        "public_ref": "org_nova_sales",
        "display_name": "Nova Sales (demo)",
        "admin_login": "nova_admin",
        "admin_password": "NovaAdmin!2026",
        "users": [
            ("usr_nova_alice", "Alice", "nova.alice", "NovaAlice!2026", "hunter_star"),
            ("usr_nova_bob", "Bob", "nova.bob", "NovaBob!2026", "fading"),
            ("usr_nova_chloe", "Chloé", "nova.chloe", "NovaChloe!2026", "newbie"),
            ("usr_nova_david", "David", "nova.david", "NovaDavid!2026", "farmer"),
            ("usr_nova_emma", "Emma", "nova.emma", "NovaEmma!2026", "spray"),
        ],
    },
    {
        "public_ref": "org_helios_corp",
        "display_name": "Helios Corp (demo)",
        "admin_login": "helios_admin",
        "admin_password": "HeliosAdmin!2026",
        "users": [
            ("usr_helios_dan", "Dan", "helios.dan", "HeliosDan!2026", "closer"),
            ("usr_helios_eva", "Eva", "helios.eva", "HeliosEva!2026", "steady"),
            ("usr_helios_fay", "Fay", "helios.fay", "HeliosFay!2026", "newbie"),
        ],
    },
    {
        "public_ref": "org_zephyr_b2b",
        "display_name": "Zephyr B2B (demo)",
        "admin_login": "zephyr_admin",
        "admin_password": "ZephyrAdmin!2026",
        "users": [
            ("usr_zephyr_gus", "Gus", "zephyr.gus", "ZephyrGus!2026", "steady"),
            ("usr_zephyr_hana", "Hana", "zephyr.hana", "ZephyrHana!2026", "hunter_star"),
            ("usr_zephyr_ian", "Ian", "zephyr.ian", "ZephyrIan!2026", "fading"),
        ],
    },
]

NAME_PREFIX = [
    "Alta",
    "Nexa",
    "Orion",
    "Vega",
    "Lumi",
    "Kora",
    "Zenith",
    "Atlas",
    "Cobalt",
    "Ludo",
    "Mira",
    "Novia",
    "Solis",
    "Aqua",
    "Brio",
    "Cerise",
    "Delta",
    "Eolia",
    "Flux",
    "Gaia",
    "Hexa",
    "Iris",
    "Jade",
    "Kilo",
    "Lyra",
    "Maia",
    "Nodal",
    "Opale",
    "Pivot",
    "Quartz",
    "Rhéa",
    "Sirius",
    "Tango",
    "Uni",
    "Vivo",
    "Wave",
    "Xenon",
    "Yara",
    "Zeta",
]
NAME_SUFFIX = {
    "Logiciel": ["Systems", "Software", "Cloud", "Data"],
    "Industrie": ["Industries", "Mécanique", "Fabrication"],
    "Santé": ["Santé", "Médical", "Pharma"],
    "Distribution": ["Retail", "Distribution", "Négoce"],
    "Transport & logistique": ["Logistics", "Transports", "Fret"],
    "Services financiers": ["Finance", "Assurances", "Capital"],
    "Conseil": ["Conseil", "Partners", "Advisory"],
    "Énergie": ["Énergie", "Solaire", "Renouvelables"],
}
OPP_PRODUCTS = ["Plateforme", "Licence annuelle", "Déploiement équipe", "Pack Entreprise", "Extension modules"]
NEXT_STEPS = [
    "Envoyer la proposition commerciale",
    "Planifier la démo avec la direction",
    "Relancer le décideur financier",
    "Valider le circuit de signature",
    "Organiser un POC de 2 semaines",
    "Présenter le chiffrage au comité",
]
SEGMENT_AMOUNT = {"smb": 0.6, "mid_market": 1.0, "enterprise": 1.9}


@dataclass
class _Sim:
    rng: random.Random
    now: datetime
    org: Organization
    user: AppUser
    persona: Persona
    referential_id: uuid.UUID
    labels: dict[str, str]
    prospects: list[Account] = field(default_factory=list)
    customers: list[Account] = field(default_factory=list)
    activities: list[dict] = field(default_factory=list)
    meetings: list[dict] = field(default_factory=list)
    opportunities: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    cooldown: dict[uuid.UUID, datetime] = field(default_factory=dict)
    won_accounts: set[uuid.UUID] = field(default_factory=set)
    first_touch: dict[uuid.UUID, datetime] = field(default_factory=dict)
    last_touch: dict[uuid.UUID, datetime] = field(default_factory=dict)


def _company_name(rng: random.Random, used: set[str]) -> tuple[str, str]:
    industry = rng.choice(list(NAME_SUFFIX))
    for _ in range(50):
        name = f"{rng.choice(NAME_PREFIX)} {rng.choice(NAME_SUFFIX[industry])}"
        if name not in used:
            used.add(name)
            return name, industry
    name = f"{rng.choice(NAME_PREFIX)} {rng.choice(NAME_SUFFIX[industry])} {len(used)}"
    used.add(name)
    return name, industry


def _make_accounts(sim: _Sim, used: set[str], org_slug: str) -> list[Account]:
    rng, out = sim.rng, []
    prospects = 118 if sim.persona.key != "spray" else 150
    for i in range(prospects + 14):
        is_customer = i >= prospects
        name, industry = _company_name(rng, used)
        tier = rng.choices(["A", "B", "C"], weights=[26, 44, 30])[0]
        segment = rng.choices(list(d.ACCOUNT_SEGMENTS), weights=[38, 42, 20])[0]
        account = Account(
            id=uuid.uuid4(),
            organization_id=sim.org.id,
            owner_user_id=sim.user.id,
            public_ref=f"acc_{org_slug}_{uuid.uuid4().hex[:8]}",
            name=name,
            industry=industry,
            segment=segment,
            tier="A" if is_customer else tier,
            kind="customer" if is_customer else "prospect",
            status="disqualified" if (not is_customer and rng.random() < 0.04) else "active",
            source="outbound" if not is_customer else "inbound",
            created_at=sim.now - timedelta(days=rng.randint(100, 400)),
        )
        out.append(account)
        (sim.customers if is_customer else sim.prospects).append(account)
    return out


def _work_days(monday: date, now: datetime) -> list[datetime]:
    days = []
    for offset in range(5):
        start = datetime.combine(monday + timedelta(days=offset), time(8, 0), tzinfo=timezone.utc)
        if start + timedelta(minutes=30) <= now:
            days.append(start)
    return days


def _random_time(rng: random.Random, day_start: datetime, now: datetime) -> datetime:
    end = min(day_start.replace(hour=18), now)
    span = max(int((end - day_start).total_seconds()), 60)
    return day_start + timedelta(seconds=rng.randint(0, span - 1))


def _weighted_sample(rng: random.Random, items: list[Account], weights: list[float], k: int) -> list[Account]:
    keyed = sorted(((rng.random() ** (1 / max(w, 1e-6)), a) for a, w in zip(items, weights, strict=True)), reverse=True)
    return [a for _, a in keyed[:k]]


def _add_meeting(
    sim: _Sim,
    *,
    category: str,
    title: str,
    start: datetime,
    minutes: int,
    account: Account | None,
    opp_id: uuid.UUID | None = None,
) -> dict:
    meeting = {
        "id": uuid.uuid4(),
        "google_event_id": f"demo_{uuid.uuid4().hex[:12]}",
        "calendar_id": "primary",
        "user_id": sim.user.id,
        "organization_id": sim.org.id,
        "referential_id": sim.referential_id,
        "account_id": account.id if account else None,
        "opportunity_id": opp_id,
        "title": title,
        "description": None,
        "start_at": start,
        "end_at": start + timedelta(minutes=minutes),
        "category_id": category,
        "category_label": sim.labels.get(category, category),
        "confidence": round(sim.rng.uniform(0.8, 0.97), 2),
        "rationale": "Donnée de démonstration",
        "classified_at": sim.now,
    }
    sim.meetings.append(meeting)
    return meeting


def _build_opportunity(
    sim: _Sim,
    account: Account,
    created_at: datetime,
    *,
    new_logo: bool = True,
    source: str = "outbound",
    cycle: int | None = None,
) -> None:
    rng, p, now = sim.rng, sim.persona, sim.now
    opp_id = uuid.uuid4()
    amount = max(3000.0, rng.gauss(p.deal_size, p.deal_size * 0.3)) * SEGMENT_AMOUNT.get(account.segment, 1.0)
    amount = round(amount / 500) * 500
    cycle = cycle or rng.randint(28, 90)
    will_win = rng.random() < p.win_rate
    stages = list(d.OPEN_STAGES)
    fractions = {"qualified": 0.0, "discovery": 0.12, "proposal": 0.42, "negotiation": 0.72}
    last_stage_index = len(stages) - 1 if will_win else rng.randint(0, len(stages) - 1)
    lose_fraction = min(1.0, fractions[stages[last_stage_index]] + rng.uniform(0.1, 0.3))
    end_fraction = 1.0 if will_win else lose_fraction
    ends_at = created_at + timedelta(days=cycle * end_fraction)
    expected_close = (created_at + timedelta(days=cycle)).date()

    history: list[tuple[str | None, str, datetime]] = []
    previous: str | None = None
    for stage in stages[: last_stage_index + 1]:
        when = created_at + timedelta(days=cycle * fractions[stage])
        if when > now:
            break
        history.append((previous, stage, when))
        previous = stage
    current = previous or "qualified"
    last_change = history[-1][2] if history else created_at

    closed_at: datetime | None = None
    lost_reason: str | None = None
    stage = current
    if ends_at <= now:
        closed_at = ends_at
        stage = d.STAGE_WON if will_win else d.STAGE_LOST
        history.append((current, stage, ends_at))
        last_change = ends_at
        lost_reason = None if will_win else rng.choice(list(d.LOST_REASONS))
        expected_close = ends_at.date()

    last_activity = next_step = next_due = None
    if closed_at is None:
        stale = rng.random() < p.stale_rate
        if stale:
            last_activity = max(created_at, now - timedelta(days=rng.randint(16, 40)))
            expected_close = (
                min(expected_close, (now - timedelta(days=rng.randint(1, 20))).date())
                if rng.random() < 0.5
                else expected_close
            )
        else:
            last_activity = max(created_at, now - timedelta(days=rng.uniform(0.2, 9)))
        if rng.random() >= p.no_next_step_rate:
            next_step = rng.choice(NEXT_STEPS)
            next_due = (
                (now + timedelta(days=rng.randint(1, 10))).date()
                if not stale
                else (now - timedelta(days=rng.randint(2, 15))).date()
            )
        if expected_close < now.date() and not stale:
            expected_close = (now + timedelta(days=rng.randint(7, 40))).date()
    else:
        last_activity = closed_at

    sim.opportunities.append(
        {
            "id": opp_id,
            "organization_id": sim.org.id,
            "user_id": sim.user.id,
            "account_id": account.id,
            "public_ref": f"opp_{uuid.uuid4().hex[:10]}",
            "name": f"{account.name} — {rng.choice(OPP_PRODUCTS)}",
            "stage": stage,
            "amount": Decimal(str(amount)),
            "currency": "EUR",
            "source": source,
            "is_new_logo": new_logo,
            "created_at": created_at,
            "expected_close_date": expected_close,
            "closed_at": closed_at,
            "last_stage_change_at": last_change,
            "last_activity_at": last_activity,
            "next_step": next_step,
            "next_step_due": next_due,
            "lost_reason": lost_reason,
        }
    )
    for from_stage, to_stage, when in history:
        sim.events.append(
            {
                "id": uuid.uuid4(),
                "opportunity_id": opp_id,
                "from_stage": from_stage,
                "to_stage": to_stage,
                "changed_at": when,
            }
        )

    reached = {to for _, to, _ in history}
    if "proposal" in reached or stage in ("proposal", "negotiation"):
        when = created_at + timedelta(days=cycle * 0.2)
        _add_meeting(
            sim,
            category="demo",
            title=f"Démo — {account.name}",
            start=_snap(when),
            minutes=60,
            account=account,
            opp_id=opp_id,
        )
    if "negotiation" in reached:
        when = created_at + timedelta(days=cycle * 0.73)
        _add_meeting(
            sim,
            category="negotiation",
            title=f"Négociation — {account.name}",
            start=_snap(when),
            minutes=45,
            account=account,
            opp_id=opp_id,
        )
    if stage == d.STAGE_WON:
        sim.won_accounts.add(account.id)
        sim.cooldown[account.id] = datetime.max.replace(tzinfo=timezone.utc)
    else:
        sim.cooldown[account.id] = max(
            sim.cooldown.get(account.id, created_at), created_at + timedelta(days=cycle * end_fraction + 45)
        )


def _snap(value: datetime) -> datetime:
    while value.weekday() >= 5:
        value += timedelta(days=1)
    return value.replace(hour=9 + value.minute % 8, minute=(value.minute // 15) * 15, second=0, microsecond=0)


def _outcome(sim: _Sim, kind: str, booked_this_week: set[uuid.UUID], account: Account, when: datetime) -> str:
    rng, p = sim.rng, sim.persona
    probability = {"call": p.call_connect, "email": p.email_reply, "linkedin": p.linkedin_reply}[kind]
    if rng.random() >= probability:
        return "no_response"
    roll = rng.random()
    if roll < p.meeting_rate and account.id not in booked_this_week:
        return "meeting_booked"
    if roll < p.meeting_rate + 0.22:
        return "not_interested"
    return "conversation"


def _simulate_hunting(sim: _Sim, monday: date, multiplier: float) -> None:
    rng, p, now = sim.rng, sim.persona, sim.now
    days = _work_days(monday, now)
    if not days:
        return
    scale = multiplier * rng.uniform(0.88, 1.12) * len(days) / 5
    volumes = {
        "call": round(p.calls * scale),
        "email": round(p.emails * scale),
        "linkedin": round(p.linkedin * scale),
    }
    total = sum(volumes.values())
    if not total:
        return

    week_start_dt = datetime.combine(monday, time.min, tzinfo=timezone.utc)
    pool = [
        a
        for a in sim.prospects
        if a.status == "active" and sim.cooldown.get(a.id, week_start_dt - timedelta(days=1)) < week_start_dt
    ]
    if not pool:
        return
    weights = []
    for account in pool:
        weight = (
            1.0
            + (4.0 * p.tier_a_bias if account.tier == "A" else 0.0)
            + (1.5 * p.tier_a_bias if account.tier == "B" else 0.0)
        )
        if account.id not in sim.last_touch:
            weight *= 1.8
        elif (week_start_dt - sim.last_touch[account.id]).days < 10:
            weight *= 0.35
        weights.append(weight)

    size = max(3, min(len(pool), round(p.accounts * scale)))
    working = _weighted_sample(rng, pool, weights, size)
    assignments = working[:total]
    while len(assignments) < total:
        assignments.append(rng.choice(working))
    rng.shuffle(assignments)
    kinds = [k for k, n in volumes.items() for _ in range(n)]
    rng.shuffle(kinds)

    booked: set[uuid.UUID] = set()
    for account, kind in zip(assignments, kinds, strict=False):
        when = _random_time(rng, rng.choice(days), now)
        outcome = _outcome(sim, kind, booked, account, when)
        sim.activities.append(
            {
                "id": uuid.uuid4(),
                "organization_id": sim.org.id,
                "user_id": sim.user.id,
                "account_id": account.id,
                "type": kind,
                "outcome": outcome,
                "is_hunting": True,
                "occurred_at": when,
                "duration_seconds": rng.randint(30, 420)
                if kind == "call" and outcome != "no_response"
                else (rng.randint(5, 25) if kind == "call" else None),
                "source": "crm",
            }
        )
        sim.first_touch.setdefault(account.id, when)
        sim.last_touch[account.id] = max(sim.last_touch.get(account.id, when), when)
        if outcome == "not_interested":
            sim.cooldown[account.id] = when + timedelta(days=45)
        if outcome == "meeting_booked":
            booked.add(account.id)
            _schedule_discovery(sim, account, when)


def _schedule_discovery(sim: _Sim, account: Account, booked_at: datetime) -> None:
    rng, p, now = sim.rng, sim.persona, sim.now
    start = _snap(booked_at + timedelta(days=rng.randint(2, 9), hours=rng.randint(0, 4)))
    sim.cooldown[account.id] = max(sim.cooldown.get(account.id, booked_at), booked_at + timedelta(days=21))
    if start <= now and rng.random() > SHOW_RATE:
        return
    meeting = _add_meeting(
        sim, category="discovery_call", title=f"Découverte — {account.name}", start=start, minutes=45, account=account
    )
    if start > now or rng.random() >= p.opp_rate:
        return
    created = start + timedelta(hours=rng.randint(2, 40))
    if created <= now:
        _build_opportunity(sim, account, created)
        meeting["opportunity_id"] = sim.opportunities[-1]["id"]


def _simulate_farming(sim: _Sim, monday: date, multiplier: float) -> None:
    rng, p, now = sim.rng, sim.persona, sim.now
    days = _work_days(monday, now)
    if not days or not sim.customers:
        return
    count = round(p.farming_activities * multiplier * rng.uniform(0.85, 1.15) * len(days) / 5)
    for _ in range(count):
        account = rng.choice(sim.customers)
        kind = rng.choices(["call", "email"], weights=[0.45, 0.55])[0]
        when = _random_time(rng, rng.choice(days), now)
        outcome = rng.choices(["conversation", "no_response"], weights=[0.6, 0.4])[0]
        sim.activities.append(
            {
                "id": uuid.uuid4(),
                "organization_id": sim.org.id,
                "user_id": sim.user.id,
                "account_id": account.id,
                "type": kind,
                "outcome": outcome,
                "is_hunting": False,
                "occurred_at": when,
                "duration_seconds": rng.randint(120, 900) if kind == "call" and outcome != "no_response" else None,
                "source": "crm",
            }
        )
        sim.last_touch[account.id] = max(sim.last_touch.get(account.id, when), when)

    hours = p.customer_hours * rng.uniform(0.85, 1.15) * len(days) / 5
    while hours > 0.4 and sim.customers:
        account = rng.choice(sim.customers)
        category = rng.choice(["customer_success", "customer_success", "follow_up"])
        minutes = rng.choice([45, 60, 60, 90])
        title = (
            f"Point trimestriel — {account.name}"
            if category == "customer_success"
            else f"Suivi client — {account.name}"
        )
        _add_meeting(
            sim,
            category=category,
            title=title,
            start=_random_time(rng, rng.choice(days), now).replace(second=0, microsecond=0),
            minutes=minutes,
            account=account,
        )
        hours -= minutes / 60


def _simulate_internal(sim: _Sim, monday: date, multiplier: float) -> None:
    rng, p, now = sim.rng, sim.persona, sim.now
    days = _work_days(monday, now)
    if not days:
        return
    first = days[0]
    _add_meeting(
        sim,
        category="internal",
        title="Pipeline review",
        start=first.replace(hour=9, minute=30),
        minutes=60,
        account=None,
    )
    if rng.random() < 0.5:
        _add_meeting(
            sim,
            category="internal",
            title="Point 1:1 avec le manager",
            start=days[min(2, len(days) - 1)].replace(hour=11),
            minutes=30,
            account=None,
        )
    blocks = round(p.calls / 20 * multiplier)
    for _ in range(min(blocks, len(days))):
        day = rng.choice(days)
        _add_meeting(
            sim,
            category="cold_call",
            title="Power hour — appels de prospection",
            start=day.replace(hour=rng.choice([9, 14, 16]), minute=0),
            minutes=90,
            account=None,
        )


def _simulate_inbound(sim: _Sim, monday: date) -> None:
    rng, now = sim.rng, sim.now
    if rng.random() > 0.3:
        return
    created = datetime.combine(monday, time(10, 0), tzinfo=timezone.utc) + timedelta(days=rng.randint(0, 4))
    if created > now - timedelta(hours=1):
        return
    source = rng.choice(["inbound", "referral", "event", "partner"])
    name, industry = _company_name(rng, set())
    account = Account(
        id=uuid.uuid4(),
        organization_id=sim.org.id,
        owner_user_id=sim.user.id,
        public_ref=f"acc_in_{uuid.uuid4().hex[:8]}",
        name=f"{name} (entrant)",
        industry=industry,
        segment=rng.choice(list(d.ACCOUNT_SEGMENTS)),
        tier="A",
        kind="prospect",
        status="active",
        source=source,
        created_at=created,
    )
    sim.prospects.append(account)
    sim.cooldown[account.id] = datetime.max.replace(tzinfo=timezone.utc)
    _build_opportunity(sim, account, created, source=source)


def _simulate_legacy(sim: _Sim) -> None:
    """Deals antérieurs à la fenêtre d'activité : alimentent l'historique de closing et le trimestre en cours."""
    rng, p, now = sim.rng, sim.persona, sim.now
    for _ in range(p.legacy_deals):
        account = rng.choice(sim.customers)
        created = now - timedelta(days=rng.randint(90, 230))
        _build_opportunity(sim, account, created, source=rng.choice(["outbound", "outbound", "referral"]))
    for _ in range(round(p.legacy_deals / 3)):
        account = rng.choice(sim.customers)
        created = now - timedelta(days=rng.randint(60, 95))
        _build_opportunity(sim, account, created, cycle=rng.randint(70, 115))


def _simulate_expansion(sim: _Sim) -> None:
    rng, p, now = sim.rng, sim.persona, sim.now
    for _ in range(p.expansion_deals):
        account = rng.choice(sim.customers)
        created = now - timedelta(days=rng.randint(5, 70))
        _build_opportunity(sim, account, created, new_logo=False, source="outbound")


def _simulate_rep(sim: _Sim, current_monday: date) -> None:
    for weeks_ago in range(HISTORY_WEEKS - 1, -1, -1):
        monday = current_monday - timedelta(weeks=weeks_ago)
        multiplier = sim.persona.trend[HISTORY_WEEKS - 1 - weeks_ago]
        _simulate_hunting(sim, monday, multiplier)
        _simulate_farming(sim, monday, 1.0)
        _simulate_internal(sim, monday, multiplier)
        _simulate_inbound(sim, monday)
    _simulate_legacy(sim)
    _simulate_expansion(sim)


def _chunks(rows: list[dict], size: int = 2000):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


async def clear_demo(session: AsyncSession, refs: list[str] | None = None) -> None:
    refs = refs or [o["public_ref"] for o in DEMO_ORGS]
    await session.execute(delete(Organization).where(Organization.public_ref.in_(refs)))


def _challenges(org: Organization, n_reps: int, now: datetime) -> list[Challenge]:
    monday = d.week_start(now)
    return [
        Challenge(
            organization_id=org.id,
            name="Blitz appels",
            scope="individual",
            metric="calls",
            target_value=Decimal("220"),
            description="220 appels de prospection en 5 semaines : la régularité fait la différence.",
            starts_on=monday - timedelta(days=14),
            ends_on=monday + timedelta(days=20),
            reward_points=150,
        ),
        Challenge(
            organization_id=org.id,
            name="Défi 14 RDV",
            scope="individual",
            metric="meetings_booked",
            target_value=Decimal("14"),
            description="Décrocher 14 rendez-vous qualifiés en 4 semaines.",
            starts_on=monday - timedelta(days=7),
            ends_on=monday + timedelta(days=21),
            reward_points=250,
        ),
        Challenge(
            organization_id=org.id,
            name="Pipe collectif",
            scope="team",
            metric="pipeline_created",
            target_value=Decimal(str(90000 * n_reps)),
            description="Créer ensemble du pipe outbound sur le mois : chacun compte.",
            starts_on=monday - timedelta(days=7),
            ends_on=monday + timedelta(days=21),
            reward_points=300,
        ),
        Challenge(
            organization_id=org.id,
            name="Chasse aux nouveaux comptes",
            scope="individual",
            metric="accounts_touched",
            target_value=Decimal("60"),
            description="Prospecter 60 comptes différents en 2 semaines.",
            starts_on=monday - timedelta(days=35),
            ends_on=monday - timedelta(days=22),
            reward_points=100,
        ),
    ]


async def seed_organization(
    session: AsyncSession,
    org_def: dict,
    now: datetime,
    rng: random.Random,
    referential_id: uuid.UUID,
    labels: dict[str, str],
) -> list[tuple[str, str, str]]:
    org = Organization(public_ref=org_def["public_ref"], display_name=org_def["display_name"])
    session.add(org)
    await session.flush()
    slug = org_def["public_ref"].removeprefix("org_")[:6]

    credentials = [("org_admin", org_def["admin_login"], org_def["admin_password"])]
    session.add(
        DashboardAccount(
            login=org_def["admin_login"],
            password_hash=hash_password(org_def["admin_password"]),
            role=DashboardRole.ORG_ADMIN.value,
            organization_id=org.id,
        )
    )

    current_monday = d.week_start(now)
    used_names: set[str] = set()
    sims: list[_Sim] = []
    for ref, alias, login, password, persona_key in org_def["users"]:
        user = AppUser(organization_id=org.id, public_ref=ref, alias=alias)
        session.add(user)
        await session.flush()
        session.add(
            DashboardAccount(
                login=login,
                password_hash=hash_password(password),
                role=DashboardRole.SALES_USER.value,
                organization_id=org.id,
                user_id=user.id,
            )
        )
        credentials.append(("sales_user", login, password))
        sim = _Sim(rng, now, org, user, PERSONAS[persona_key], referential_id, labels)
        session.add_all(_make_accounts(sim, used_names, slug))
        sims.append(sim)
    await session.flush()

    valid_from = current_monday - timedelta(weeks=HISTORY_WEEKS)
    for metric, value in d.DEFAULT_WEEKLY_TARGETS.items():
        session.add(
            SalesTarget(
                organization_id=org.id,
                user_id=None,
                metric=metric,
                period="week",
                target_value=Decimal(value),
                valid_from=valid_from,
            )
        )
    session.add(
        SalesTarget(
            organization_id=org.id,
            user_id=None,
            metric="revenue_won",
            period="quarter",
            target_value=Decimal(d.DEFAULT_QUARTER_QUOTA),
            valid_from=valid_from,
        )
    )

    for sim in sims:
        _simulate_rep(sim, current_monday)
        persona = sim.persona
        if persona.target_scale != 1.0:
            for metric, value in d.DEFAULT_WEEKLY_TARGETS.items():
                scaled = (
                    max(1, round(value * persona.target_scale))
                    if metric != "pipeline_created"
                    else round(value * persona.target_scale)
                )
                session.add(
                    SalesTarget(
                        organization_id=org.id,
                        user_id=sim.user.id,
                        metric=metric,
                        period="week",
                        target_value=Decimal(scaled),
                        valid_from=valid_from,
                    )
                )
        if persona.quarter_quota != d.DEFAULT_QUARTER_QUOTA:
            session.add(
                SalesTarget(
                    organization_id=org.id,
                    user_id=sim.user.id,
                    metric="revenue_won",
                    period="quarter",
                    target_value=Decimal(persona.quarter_quota),
                    valid_from=valid_from,
                )
            )

        for account in [*sim.prospects, *sim.customers]:
            account.first_touch_at = sim.first_touch.get(account.id)
            account.last_activity_at = sim.last_touch.get(account.id)
            if account.id in sim.won_accounts:
                account.kind = "customer"
        session.add_all([a for a in sim.prospects if a.public_ref.startswith("acc_in_")])
        await session.flush()

    for sim in sims:
        for chunk in _chunks(sim.opportunities):
            await session.execute(insert(Opportunity), chunk)
    await session.flush()
    for sim in sims:
        for chunk in _chunks(sim.events):
            await session.execute(insert(OpportunityStageEvent), chunk)
        for chunk in _chunks(sim.meetings):
            await session.execute(insert(MeetingClassification), chunk)
        for chunk in _chunks(sim.activities):
            await session.execute(insert(Activity), chunk)

    session.add_all(_challenges(org, len(sims), now))
    await _seed_coaching_actions(session, org, org_def, sims, now)
    await session.flush()
    return credentials


async def _seed_coaching_actions(
    session: AsyncSession, org: Organization, org_def: dict, sims: list[_Sim], now: datetime
) -> None:
    by_persona = {sim.persona.key: sim for sim in sims}
    today = now.date()
    plans = [
        (
            "fading",
            "one_to_one",
            "Point 1:1 : comprendre le décrochage des 3 dernières semaines",
            "Écoute avant tout : charge perso, deals perdus, démotivation ?",
            "open",
            2,
        ),
        (
            "newbie",
            "call_shadowing",
            "Écouter 3 appels et débriefer sur l'accroche",
            "Objectif : passer de 20 à 30 appels par semaine sans stress.",
            "open",
            4,
        ),
        ("spray", "training", "Micro-training : cibler au lieu d'arroser (ICP et tier A)", None, "open", 6),
        (
            "farmer",
            "nudge",
            "Bloquer 2 demi-journées de chasse par semaine",
            "Déléguer le suivi des petits comptes clients.",
            "open",
            3,
        ),
        (
            "hunter_star",
            "recognition",
            "Féliciter en réunion d'équipe et recueillir sa routine d'appels",
            None,
            "done",
            None,
        ),
        ("steady", "nudge", "Dérouler la liste tier A sans opportunité en cours", None, "done", None),
    ]
    for persona_key, kind, title, note, status, due in plans:
        sim = by_persona.get(persona_key)
        if not sim:
            continue
        session.add(
            CoachingAction(
                organization_id=org.id,
                user_id=sim.user.id,
                created_by=org_def["admin_login"],
                kind=kind,
                title=title,
                note=note,
                status=status,
                due_on=today + timedelta(days=due) if due else None,
                completed_at=now - timedelta(days=2) if status == "done" else None,
                related_metric="hunting_index",
            )
        )


async def seed_demo(
    session: AsyncSession, orgs: list[dict] | None = None, now: datetime | None = None, seed: int = 20261018
) -> list[tuple[str, str, str]]:
    """Recrée les organisations de démonstration. Idempotent : supprime puis recharge."""
    orgs = orgs or DEMO_ORGS
    now = now or d.utcnow()
    await clear_demo(session, [o["public_ref"] for o in orgs])
    await session.commit()

    ref_row, ref_payload = await ensure_active_referential(session)
    labels = {c.id: c.label for c in ref_payload.categories}
    rng = random.Random(seed)
    credentials: list[tuple[str, str, str]] = []
    for org_def in orgs:
        credentials += await seed_organization(session, org_def, now, rng, ref_row.id, labels)
        await session.commit()
    return credentials


async def existing_demo_orgs(session: AsyncSession) -> list[str]:
    refs = [o["public_ref"] for o in DEMO_ORGS]
    rows = await session.execute(select(Organization.public_ref).where(Organization.public_ref.in_(refs)))
    return [r[0] for r in rows.all()]
