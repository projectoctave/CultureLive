"""Faux Google Calendar (googleapiclient) en mémoire, avec pagination."""

from datetime import datetime


class _Request:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class FakeCalendarStore:
    def __init__(self, page_size: int = 3):
        self.events: list[dict] = []
        self.page_size = page_size
        self._counter = 0
        self.list_calls = 0

    def add(self, summary, start, end, description=None, time_zone="Europe/Paris") -> dict:
        self._counter += 1
        event = {
            "id": f"fake_evt_{self._counter}",
            "summary": summary,
            "description": description,
            "start": {"dateTime": start, "timeZone": time_zone},
            "end": {"dateTime": end, "timeZone": time_zone},
            "htmlLink": f"https://calendar.example/event/{self._counter}",
            "status": "confirmed",
        }
        self.events.append(event)
        return event

    def find(self, summary_prefix: str) -> dict:
        return next(e for e in self.events if e["summary"].startswith(summary_prefix))


class _Events:
    def __init__(self, store: FakeCalendarStore):
        self._store = store

    def list(self, calendarId, timeMin, timeMax, pageToken=None, **_):
        def run():
            self._store.list_calls += 1
            lo = datetime.fromisoformat(timeMin.replace("Z", "+00:00"))
            hi = datetime.fromisoformat(timeMax.replace("Z", "+00:00"))
            inside = sorted(
                (
                    e
                    for e in self._store.events
                    if lo <= datetime.fromisoformat(e["start"]["dateTime"].replace("Z", "+00:00")) <= hi
                ),
                key=lambda e: e["start"]["dateTime"],
            )
            offset = int(pageToken or 0)
            page = inside[offset : offset + self._store.page_size]
            body: dict = {"items": page}
            if offset + self._store.page_size < len(inside):
                body["nextPageToken"] = str(offset + self._store.page_size)
            return body

        return _Request(run)

    def insert(self, calendarId, body):
        def run():
            return self._store.add(
                body["summary"],
                body["start"]["dateTime"],
                body["end"]["dateTime"],
                body.get("description"),
                body["start"].get("timeZone", "Europe/Paris"),
            )

        return _Request(run)


class FakeCalendarService:
    def __init__(self, store: FakeCalendarStore):
        self._store = store

    def events(self):
        return _Events(self._store)


def fake_build(store: FakeCalendarStore):
    def build(service_name, version, credentials=None, **_):
        assert service_name == "calendar", f"service inattendu: {service_name}"
        return FakeCalendarService(store)

    return build
