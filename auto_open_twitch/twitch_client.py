# Copyright 2026 Enoch Bunnell, AlyxiC
# SPDX-License-Identifier: Apache-2.0
# See LICENSE in the project root for the full Apache License 2.0 text.

"""Thin wrapper around Twitch's Helix API.

Phase 1 (and ongoing) only needs one Helix endpoint: GET /streams. Given a
list of streamer logins, Twitch returns one entry per streamer who is
*currently* live — offline streamers are simply absent from the response.
That's how we tell who's live.

See https://dev.twitch.tv/docs/api/reference/#get-streams for the full
response schema. We extract the fields the watcher cares about (game name,
title, viewer count, started_at) so the LLM prompt has context to work with.
"""

from __future__ import annotations

import requests

from config import CLIENT_ID

HELIX_BASE = "https://api.twitch.tv/helix"


class TokenExpired(Exception):
    """Raised when Helix returns 401 so the watcher can refresh and retry.

    Twitch access tokens expire after ~4 hours. We don't normally hit this
    because twitch_auth refreshes proactively based on the expiry timestamp,
    but a server-side revocation or clock skew could still produce a 401.
    """


def get_live_streams(
    usernames: list[str], access_token: str
) -> dict[str, dict[str, object]]:
    """Return {login: stream_info} for the streamers that are currently live.

    Streamers not currently live are simply absent from the returned dict.
    stream_info contains the subset of fields the watcher and LLM prompt
    consume: game_name, title, viewer_count, started_at.

    Args:
        usernames: list of lowercased Twitch logins to query.
        access_token: a valid user OAuth token (any scope — /streams is open).

    Raises:
        TokenExpired: if Helix returns 401 (caller should refresh + retry).
        requests.RequestException: on transport-level errors.
    """
    if not usernames:
        return {}

    headers = {
        "Client-Id": CLIENT_ID,
        "Authorization": f"Bearer {access_token}",
    }
    streams: dict[str, dict[str, object]] = {}

    # Helix /streams accepts up to 100 user_login query parameters per call,
    # so we batch in chunks of 100. For most personal watchlists this loops
    # exactly once.
    for i in range(0, len(usernames), 100):
        batch = usernames[i:i + 100]
        # `params` is a list of tuples so we can repeat the same key.
        params = [("user_login", name) for name in batch]
        resp = requests.get(
            f"{HELIX_BASE}/streams", headers=headers, params=params, timeout=15
        )
        if resp.status_code == 401:
            raise TokenExpired()
        resp.raise_for_status()
        for stream in resp.json().get("data", []):
            login = stream["user_login"].lower()
            streams[login] = {
                "game_name": stream.get("game_name", ""),
                "title": stream.get("title", ""),
                "viewer_count": stream.get("viewer_count", 0),
                "started_at": stream.get("started_at", ""),
            }
    return streams
