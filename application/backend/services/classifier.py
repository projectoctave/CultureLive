import json
import re

from pydantic import BaseModel

from backend.config import Settings
from backend.services.referential import SalesCategory, SalesReferentialPayload

KEYWORD_RULES: dict[str, list[re.Pattern[str]]] = {
    "cold_call": [
        re.compile(r"cold\s*call", re.I),
        re.compile(r"prospection", re.I),
        re.compile(r"appel\s*froid", re.I),
        re.compile(r"outbound", re.I),
    ],
    "discovery_call": [
        re.compile(r"discovery", re.I),
        re.compile(r"découverte", re.I),
        re.compile(r"qualif", re.I),
        re.compile(r"besoin client", re.I),
    ],
    "demo": [
        re.compile(r"\bdemo\b", re.I),
        re.compile(r"démo", re.I),
        re.compile(r"walkthrough", re.I),
        re.compile(r"live product", re.I),
    ],
    "negotiation": [
        re.compile(r"negociation|négociation", re.I),
        re.compile(r"closing", re.I),
        re.compile(r"contrat", re.I),
        re.compile(r"pricing", re.I),
        re.compile(r"MSA", re.I),
    ],
    "follow_up": [
        re.compile(r"follow[- ]?up", re.I),
        re.compile(r"suivi", re.I),
        re.compile(r"next steps", re.I),
        re.compile(r"relance", re.I),
    ],
    "customer_success": [
        re.compile(r"onboarding", re.I),
        re.compile(r"\bqbr\b", re.I),
        re.compile(r"customer success", re.I),
        re.compile(r"renewal", re.I),
    ],
    "internal": [
        re.compile(r"pipeline review", re.I),
        re.compile(r"forecast", re.I),
        re.compile(r"1:1", re.I),
        re.compile(r"interne", re.I),
        re.compile(r"roleplay", re.I),
    ],
}


class ClassificationResult(BaseModel):
    category_id: str
    category_label: str
    confidence: float
    rationale: str


class MeetingInput(BaseModel):
    event_id: str
    title: str
    description: str | None = None
    start_iso: str = ""
    end_iso: str = ""


def _category_by_id(referential: SalesReferentialPayload, category_id: str) -> SalesCategory:
    for c in referential.categories:
        if c.id == category_id:
            return c
    return next(c for c in referential.categories if c.id == "other")


def classify_heuristic(meeting: MeetingInput, referential: SalesReferentialPayload) -> ClassificationResult:
    blob = f"{meeting.title}\n{meeting.description or ''}"
    best_id = "other"
    best_score = 0
    valid_ids = {c.id for c in referential.categories}

    for cat_id, patterns in KEYWORD_RULES.items():
        if cat_id not in valid_ids:
            continue
        score = sum(1 for p in patterns if p.search(blob))
        if score > best_score:
            best_score = score
            best_id = cat_id

    cat = _category_by_id(referential, best_id)
    if best_score > 0:
        conf = min(0.88, 0.52 + best_score * 0.12)
        rationale = f"Heuristique: signaux « {cat.label} » dans titre/description."
    else:
        conf = 0.32
        rationale = "Heuristique: peu de signaux — « Autre »."

    return ClassificationResult(
        category_id=cat.id,
        category_label=cat.label,
        confidence=conf,
        rationale=rationale,
    )


async def classify_with_llm(
    settings: Settings,
    meeting: MeetingInput,
    referential: SalesReferentialPayload,
) -> ClassificationResult:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    cats = [c.model_dump() for c in referential.categories]
    prompt = f"""Tu es sales ops. Classe cette réunion selon UNE catégorie du référentiel.

Référentiel: {json.dumps(cats, ensure_ascii=False)}

Réunion:
- Titre: {meeting.title}
- Description: {meeting.description or "(vide)"}

JSON uniquement: {{"categoryId":"...","confidence":0.0-1.0,"rationale":"..."}}"""

    resp = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.15,
    )
    content = resp.choices[0].message.content or "{}"
    parsed = json.loads(content)
    cat = _category_by_id(referential, str(parsed.get("categoryId", "other")))
    conf = float(parsed.get("confidence", 0.5))
    conf = max(0.0, min(1.0, conf))
    return ClassificationResult(
        category_id=cat.id,
        category_label=cat.label,
        confidence=conf,
        rationale=str(parsed.get("rationale", "Classification IA.")),
    )


async def classify_meeting(
    settings: Settings,
    meeting: MeetingInput,
    referential: SalesReferentialPayload,
) -> ClassificationResult:
    if settings.openai_api_key:
        try:
            return await classify_with_llm(settings, meeting, referential)
        except Exception:
            pass
    return classify_heuristic(meeting, referential)
