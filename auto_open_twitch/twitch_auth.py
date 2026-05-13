"""Twitch OAuth (Authorization Code flow) with token persistence and refresh.

This module owns the full OAuth dance:

  First run:
    1. We spin up a tiny local HTTP server on the loopback URL declared by
       REDIRECT_URI in .env (e.g., http://localhost:3000/auth/twitch/callback).
    2. We open a browser to Twitch's /authorize page with our CLIENT_ID and
       the scopes we need (chat:read, chat:edit).
    3. The user clicks Authorize. Twitch redirects their browser back to our
       loopback URL with an authorization "code" in the query string.
    4. Our local server catches the redirect, extracts the code.
    5. We POST the code (plus our CLIENT_SECRET) to Twitch's /token endpoint
       and get back an access_token + refresh_token, which we cache in
       tokens.json.

  Subsequent runs:
    - tokens.json is loaded.
    - If it's missing required scopes (because we upgraded SCOPES in code),
      we wipe it and run the full flow again.
    - If the access_token is near/past expiry, we use the refresh_token to
      get fresh ones from the /token endpoint silently (no browser needed).
    - Otherwise we just use what we have.

References:
  Twitch OAuth: https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/
"""

from __future__ import annotations

import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from config import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPES, TOKENS_FILE

# Twitch's OAuth endpoints. AUTHORIZE_URL is what the user's browser visits
# to grant consent; TOKEN_URL is what our code POSTs to for code↔token
# exchanges (both initial and refresh).
AUTHORIZE_URL = "https://id.twitch.tv/oauth2/authorize"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"


class _CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler that captures Twitch's auth redirect on localhost.

    HTTPServer creates a fresh handler instance per request, so we store the
    captured `code` (and `error`, and the `expected_state` we generated for
    this auth attempt) as CLASS attributes — they survive across requests
    and across the handler's lifetime in a way instance attributes wouldn't.
    """

    code: str | None = None
    error: str | None = None
    expected_state: str | None = None

    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)

        # Twitch can redirect with ?error=... if the user denied consent.
        if "error" in params:
            _CallbackHandler.error = params.get(
                "error_description", params["error"]
            )[0]
            self._respond("Authorization failed. You can close this tab.")
            return

        # Some browsers fetch /favicon.ico or similar after the redirect.
        # If there's no `code` param, it's not the call we care about.
        if "code" not in params:
            self._respond("Waiting for Twitch redirect…")
            return

        # `state` is a random token we generated and sent in the auth URL.
        # Twitch echoes it back; checking it prevents CSRF (an attacker
        # tricking your browser into completing someone else's auth flow).
        if params.get("state", [None])[0] != _CallbackHandler.expected_state:
            _CallbackHandler.error = "state mismatch"
            self._respond("Authorization failed (state mismatch). Close this tab.")
            return

        _CallbackHandler.code = params["code"][0]
        self._respond("Authorization successful. You can close this tab.")

    def _respond(self, body: str):
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args, **_kwargs):
        # Silence the default per-request stderr logging — too noisy and
        # would clutter the watcher's output during the OAuth flow.
        pass


def _run_oauth_flow() -> dict:
    """Drive the full browser-based authorization once. Blocks until the
    user authorizes (or 5 minutes elapse). Returns the stored token payload.
    """
    # Parse REDIRECT_URI to find which host/port to bind our local server to.
    # Twitch's redirect MUST come back to the same URL we registered.
    redirect = urlparse(REDIRECT_URI)
    host = redirect.hostname or "localhost"
    port = redirect.port or 3000

    # CSRF token: random per flow, checked when Twitch redirects back.
    state = secrets.token_urlsafe(16)
    _CallbackHandler.code = None
    _CallbackHandler.error = None
    _CallbackHandler.expected_state = state

    # Build the URL the user's browser will visit to grant consent.
    auth_url = f"{AUTHORIZE_URL}?" + urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
    })

    # Start the local server in a background thread so we can wait on the
    # callback from the main thread.
    server = HTTPServer((host, port), _CallbackHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        print(f"Opening browser for Twitch login.\nIf nothing opens, visit:\n  {auth_url}")
        webbrowser.open(auth_url)

        # Poll until the handler reports either success or failure, or we
        # hit the 5-minute timeout. (Polling is simpler than threading
        # primitives for a one-shot wait.)
        deadline = time.time() + 300
        while _CallbackHandler.code is None and _CallbackHandler.error is None:
            if time.time() > deadline:
                raise TimeoutError("Timed out waiting for Twitch authorization (5 min).")
            time.sleep(0.2)
    finally:
        # Always stop the server so the port doesn't stay bound.
        server.shutdown()
        server.server_close()

    if _CallbackHandler.error:
        raise RuntimeError(f"Twitch OAuth failed: {_CallbackHandler.error}")

    return _exchange_code(_CallbackHandler.code)


def _exchange_code(code: str) -> dict:
    """Trade an authorization code for an access/refresh token pair."""
    resp = requests.post(TOKEN_URL, data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }, timeout=15)
    resp.raise_for_status()
    return _store_tokens(resp.json())


def _refresh(refresh_token: str) -> dict:
    """Use a refresh_token to get a fresh access_token without a browser flow.

    Refresh tokens last until revoked (e.g., user disconnects the app on
    Twitch's settings page). If this call returns 4xx, the caller falls back
    to the full _run_oauth_flow.
    """
    resp = requests.post(TOKEN_URL, data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }, timeout=15)
    resp.raise_for_status()
    return _store_tokens(resp.json())


def _store_tokens(data: dict) -> dict:
    """Persist a token payload to tokens.json and return the stored shape."""
    payload = {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "obtained_at": int(time.time()),  # wall-clock seconds at issue
        "expires_in": data.get("expires_in", 0),
        "scope": data.get("scope", []),
    }
    # Cache the authenticated user's login (username) so IRC has the right
    # NICK without an extra Helix round-trip on every chat send. Failure
    # here is non-fatal — get_authenticated_login() will lazy-fetch later.
    try:
        resp = requests.get(
            "https://api.twitch.tv/helix/users",
            headers={
                "Client-Id": CLIENT_ID,
                "Authorization": f"Bearer {data['access_token']}",
            },
            timeout=10,
        )
        resp.raise_for_status()
        users = resp.json().get("data", [])
        if users:
            payload["login"] = users[0]["login"]
    except requests.RequestException:
        pass
    TOKENS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _load_tokens() -> dict | None:
    """Read tokens.json. Returns None if missing or unreadable (treat as
    'we need to authorize fresh')."""
    if not TOKENS_FILE.exists():
        return None
    try:
        return json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _is_expired(tokens: dict, leeway_seconds: int = 120) -> bool:
    """True if the access_token is within `leeway_seconds` of expiring.

    The 2-minute leeway prevents a token from expiring mid-request right
    after we checked it.
    """
    return time.time() >= tokens["obtained_at"] + tokens["expires_in"] - leeway_seconds


def _has_required_scopes(tokens: dict) -> bool:
    """True if the stored token covers everything SCOPES asks for.

    If we later add a new scope (e.g., add chat:read alongside chat:edit),
    existing tokens won't have it. This check forces a re-auth in that case.
    """
    return set(SCOPES).issubset(set(tokens.get("scope", [])))


def get_access_token() -> str:
    """The watcher's main entry point — returns a valid access token.

    Handles all three states:
      - No tokens yet (or scopes upgraded) -> full browser flow
      - Tokens expired                     -> silent refresh
      - Tokens fine                        -> use as-is
    """
    tokens = _load_tokens()
    if tokens is None or not _has_required_scopes(tokens):
        if tokens is not None and not _has_required_scopes(tokens):
            print(
                "Stored token is missing required scopes "
                f"({sorted(set(SCOPES) - set(tokens.get('scope', [])))}). "
                "Re-authorizing."
            )
        tokens = _run_oauth_flow()
    elif _is_expired(tokens):
        try:
            tokens = _refresh(tokens["refresh_token"])
        except requests.HTTPError:
            # Refresh token was revoked or otherwise invalid — full flow.
            tokens = _run_oauth_flow()
    return tokens["access_token"]


def get_authenticated_login() -> str:
    """Return the Twitch login (lowercased username) of the authenticated user.

    Used by IRC chat as the NICK. Cached in tokens.json by _store_tokens so
    this is almost always a disk read, not a network call.
    """
    get_access_token()  # ensures tokens.json is current
    tokens = _load_tokens()
    if tokens and tokens.get("login"):
        return tokens["login"]
    # Cold-cache fallback: fetch from Helix and update tokens.json.
    resp = requests.get(
        "https://api.twitch.tv/helix/users",
        headers={
            "Client-Id": CLIENT_ID,
            "Authorization": f"Bearer {tokens['access_token']}",
        },
        timeout=10,
    )
    resp.raise_for_status()
    login = resp.json()["data"][0]["login"]
    tokens["login"] = login
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
    return login


def force_reauth() -> str:
    """Wipe stored tokens and run the full OAuth flow again.

    Used when Helix returns 401 mid-session even though our timestamp
    suggested the token should still be valid (e.g., user revoked the app
    on Twitch's settings page).
    """
    if TOKENS_FILE.exists():
        TOKENS_FILE.unlink()
    return get_access_token()


if __name__ == "__main__":
    # Standalone: run/refresh the OAuth flow and print confirmation. Useful
    # for verifying setup before running the full watcher.
    token = get_access_token()
    login = get_authenticated_login()
    print(f"Got access token (length={len(token)}) for @{login}. Stored in {TOKENS_FILE}.")
