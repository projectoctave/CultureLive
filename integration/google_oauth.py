from google_auth_oauthlib.flow import Flow

from backend.config import Settings

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
]


def build_flow(settings: Settings) -> Flow:
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }
    return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=settings.google_redirect_uri)


def authorization_url(settings: Settings, state: str) -> str:
    flow = build_flow(settings)
    url, _ = flow.authorization_url(access_type="offline", prompt="consent", state=state)
    return url


def exchange_code(settings: Settings, code: str) -> tuple[str, str]:
    flow = build_flow(settings)
    flow.fetch_token(code=code)
    creds = flow.credentials
    if not creds.refresh_token:
        raise RuntimeError("Pas de refresh_token — révoquez l'accès Google et reconnectez-vous.")

    from googleapiclient.discovery import build

    oauth2 = build("oauth2", "v2", credentials=creds)
    profile = oauth2.userinfo().get().execute()
    email = profile.get("email")
    if not email:
        raise RuntimeError("Email Google introuvable")
    return creds.refresh_token, email
