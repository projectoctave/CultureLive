"""Agenda fictif d'un AE B2B SaaS — titres réalistes pour tester la typologie."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SalesMeetingFixture:
    title: str
    description: str
    expected_category: str


SALES_AGENDA: list[SalesMeetingFixture] = [
    SalesMeetingFixture(
        title="Cold call — DSI retail (liste outbound)",
        description="Premier contact à froid, pitch 90s, objectif RDV discovery.",
        expected_category="cold_call",
    ),
    SalesMeetingFixture(
        title="Discovery call Acme Corp",
        description="Qualification besoin, cartographie stakeholders, budget et timing.",
        expected_category="discovery_call",
    ),
    SalesMeetingFixture(
        title="Démo CultureLive — walkthrough intégrations",
        description="Live product tour: agenda Google, classification, dashboard.",
        expected_category="demo",
    ),
    SalesMeetingFixture(
        title="Négociation MSA + pricing annuel",
        description="Closing: remise volume, conditions contrat, signature Q4.",
        expected_category="negotiation",
    ),
    SalesMeetingFixture(
        title="Follow-up post-démo — next steps",
        description="Suivi actions, envoi business case, relance décideurs.",
        expected_category="follow_up",
    ),
    SalesMeetingFixture(
        title="QBR Customer Success — compte Nordia",
        description="Onboarding phase 2, adoption, renewal health.",
        expected_category="customer_success",
    ),
    SalesMeetingFixture(
        title="Pipeline review hebdo (interne)",
        description="Forecast équipe, coaching, prep calls semaine.",
        expected_category="internal",
    ),
    SalesMeetingFixture(
        title="Point café avec un ami",
        description="Hors scope commercial.",
        expected_category="other",
    ),
]
