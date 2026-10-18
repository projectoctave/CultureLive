from dataclasses import dataclass
from datetime import datetime

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from backend.config import Settings


@dataclass
class CalendarEventDTO:
    id: str
    title: str
    description: str | None
    start: datetime
    end: datetime
    html_link: str | None
    raw: dict


def _credentials(settings: Settings, refresh_token: str) -> Credentials:
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=[
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
    )


def _parse_dt(value: dict | None) -> datetime:
    if not value:
        return datetime.fromisoformat("1970-01-01T00:00:00+00:00")
    if value.get("dateTime"):
        return datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
    if value.get("date"):
        return datetime.fromisoformat(f"{value['date']}T00:00:00+00:00")
    return datetime.fromisoformat("1970-01-01T00:00:00+00:00")


def list_events(
    settings: Settings,
    refresh_token: str,
    time_min: str,
    time_max: str,
    calendar_id: str = "primary",
) -> list[CalendarEventDTO]:
    service = build("calendar", "v3", credentials=_credentials(settings, refresh_token))
    items = []
    page_token = None
    while True:
        resp = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
                pageToken=page_token,
            )
            .execute()
        )
        items.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    out: list[CalendarEventDTO] = []
    for e in items:
        if not e.get("id") or not e.get("summary"):
            continue
        out.append(
            CalendarEventDTO(
                id=e["id"],
                title=e["summary"],
                description=e.get("description"),
                start=_parse_dt(e.get("start")),
                end=_parse_dt(e.get("end")),
                html_link=e.get("htmlLink"),
                raw=e,
            )
        )
    return out


def create_event(
    settings: Settings,
    refresh_token: str,
    summary: str,
    start_iso: str,
    end_iso: str,
    description: str | None = None,
    time_zone: str = "Europe/Paris",
    calendar_id: str = "primary",
) -> CalendarEventDTO:
    service = build("calendar", "v3", credentials=_credentials(settings, refresh_token))
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_iso, "timeZone": time_zone},
        "end": {"dateTime": end_iso, "timeZone": time_zone},
    }
    e = service.events().insert(calendarId=calendar_id, body=body).execute()
    return CalendarEventDTO(
        id=e["id"],
        title=e["summary"],
        description=e.get("description"),
        start=_parse_dt(e.get("start")),
        end=_parse_dt(e.get("end")),
        html_link=e.get("htmlLink"),
        raw=e,
    )
