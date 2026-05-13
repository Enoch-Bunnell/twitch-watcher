# Copyright 2026 Enoch Bunnell, AlyxiC
# SPDX-License-Identifier: Apache-2.0
# See LICENSE in the project root for the full Apache License 2.0 text.

"""Central configuration and constants for the watcher.

Loads secrets from .env (Twitch API credentials, Ollama model name), defines
the timing/feature tunables every other module reads from, and provides the
streamers.txt parser. Importing this module also implicitly loads .env into
the process's environment via python-dotenv.

Anything you'd want to tweak (poll cadence, grace periods, scopes, the AI
model) lives here — there are no hardcoded "magic numbers" scattered across
the other modules.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

# All paths are anchored to this file's directory so the project works no
# matter where you run it from (double-click, terminal, autostart, etc.).
ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

# Twitch OAuth credentials — get these from https://dev.twitch.tv/console/apps
# after registering an "Application". REDIRECT_URI must match what you
# registered byte-for-byte (twitch_auth.py spins up a local HTTP server on
# this URI to receive the auth callback).
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
REDIRECT_URI = os.environ["REDIRECT_URI"]

# Files the watcher reads/writes at runtime. tokens.json is gitignored
# (contains your live OAuth tokens) and recreated by twitch_auth on demand.
TOKENS_FILE = ROOT / "tokens.json"
STREAMERS_FILE = ROOT / "streamers.txt"

# How often to ask Twitch who's live. 60s is well under the rate limit and
# fast enough that a go-live is noticed within a minute.
POLL_INTERVAL_SECONDS = 60

# chat:edit lets us send messages; chat:read lets us read chat (kept for a
# future phase that may want chat context). Adding either of these to an
# existing token requires re-authorizing — the watcher detects missing scopes
# and pops the OAuth flow automatically.
SCOPES: list[str] = ["chat:read", "chat:edit"]

# When a tracked streamer goes live, wait a random amount of time before
# sending the lurk message. Avoids robotic "0-second response" timing that
# would look bot-like.
LURK_DELAY_MIN_SECONDS = 5.0
LURK_DELAY_MAX_SECONDS = 15.0

# How long a streamer must stay offline before we auto-close their tab.
# Brief disconnects and scene transitions usually resolve within a minute
# or two; 5 minutes means "they're probably really done streaming".
OFFLINE_CLOSE_GRACE_SECONDS = 300.0

# Ollama-served local model used to generate lurk messages. Pulled from the
# AI_BACKEND env var so you can swap models without editing code. If Ollama
# isn't running or the model isn't installed, the watcher falls back to the
# templates in messages.txt automatically.
AI_MODEL = os.environ.get("AI_BACKEND", "llama3.2:3b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


def load_streamers() -> list[str]:
    """Parse streamers.txt and return a list of lowercased Twitch usernames.

    Accepts two formats per line:
      - A full URL:  https://www.twitch.tv/celestiayukihime
      - A bare name: celestiayukihime

    Blank lines and lines starting with `#` are ignored, so users can leave
    comments in their watch list.

    Called by the watcher every poll cycle (not just at startup) so edits to
    streamers.txt are picked up live without restarting.
    """
    if not STREAMERS_FILE.exists():
        return []
    names: list[str] = []
    for raw in STREAMERS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # If it looks like a URL, extract the first path segment (the username).
        # Otherwise treat the whole line as the username.
        if "://" in line:
            path = urlparse(line).path.strip("/")
            username = path.split("/", 1)[0]
        else:
            username = line
        if username:
            # Helix and IRC both expect lowercase logins.
            names.append(username.lower())
    return names
