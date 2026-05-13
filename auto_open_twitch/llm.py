# Copyright 2026 Enoch Bunnell, AlyxiC
# SPDX-License-Identifier: Apache-2.0
# See LICENSE in the project root for the full Apache License 2.0 text.

"""Generate Twitch lurk messages via a local LLM through Ollama.

Ollama (https://ollama.com) is a small local server that runs LLMs on your
machine. It exposes an HTTP API on http://localhost:11434 — we POST a prompt
and get back the model's response. The watcher uses this to vary lurk
phrasing per streamer and mention the game they're playing, which feels far
more human than always sending the same template.

The model is configurable (AI_BACKEND env var, default llama3.2:3b). A 3B
quantized model runs fine on CPU and is plenty for ~200-character outputs.

On any failure — Ollama daemon down, model not installed, malformed
response, empty output — we raise LLMUnavailable and the caller (watcher)
falls back to picking from messages.txt. Falling back silently is by
design: the watcher should keep working without the LLM.
"""

from __future__ import annotations

import requests

from config import AI_MODEL, OLLAMA_URL

# Per the project's original spec (twitchappsetuo.md), this template has
# been "tested extensively" — preserved as-is in intent. Placeholders use
# Python format() names so we can interpolate streamer + game per call.
# Tweak the wording if you want a different vibe, but keep the constraints
# (length cap, no quotes/preamble) — they're what makes the output usable.
PROMPT_TEMPLATE = """\
Generate ONE short friendly Twitch chat message.

We Are Watching The Streamer: {streamer}
They Are Playing The Game: {game}
Tone: casual and supportive
Mention:
- I'm away from my PC
- lurking
- will return later
- end by telling them to have a great stream!

Keep under 200 characters.
Avoid sounding robotic.
Respond with ONLY the message text. No quotes, no preamble, no labels.
"""

# First inference on a cold model can take 10-30s while Ollama loads the
# weights into memory. 60s timeout covers cold start with margin.
GENERATE_TIMEOUT = 60

# Twitch caps chat messages at 500 chars. We leave headroom because the
# model occasionally goes over and trailing-ellipsis truncation reads
# better than a hard cut at exactly 500.
MAX_MESSAGE_LENGTH = 450


class LLMUnavailable(Exception):
    """Ollama isn't reachable or returned something we can't use."""


def generate_lurk_message(streamer: str, game: str | None) -> str:
    """Ask Ollama for one lurk message. Raises LLMUnavailable on any problem.

    Args:
        streamer: lowercased username (gets embedded in the prompt).
        game: human-readable game name from Twitch's Helix response, or
            None if Helix didn't include one (rare).
    """
    prompt = PROMPT_TEMPLATE.format(
        streamer=streamer,
        game=game or "(unknown game)",
    )

    # Ollama's /api/generate body. `stream: false` returns the full response
    # in one HTTP reply (vs streaming chunks, which we don't need). `keep_alive`
    # tells Ollama to keep the model resident in memory for the given duration
    # so the next call doesn't pay the cold-load cost again.
    body = {
        "model": AI_MODEL,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "60m",
        "options": {
            "temperature": 0.8,    # some variety but not chaos
            "num_predict": 80,     # plenty for a ~200-char chat message
        },
    }
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate", json=body, timeout=GENERATE_TIMEOUT
        )
    except requests.RequestException as e:
        raise LLMUnavailable(f"Ollama unreachable at {OLLAMA_URL}: {e}") from e

    if resp.status_code != 200:
        raise LLMUnavailable(
            f"Ollama returned HTTP {resp.status_code}: {resp.text[:200]}"
        )

    try:
        data = resp.json()
    except ValueError as e:
        # Either the response wasn't JSON, or it was malformed JSON. Either
        # way we can't trust it — fall back to a template.
        raise LLMUnavailable(f"Ollama returned non-JSON: {e}") from e

    text = data.get("response", "").strip()
    if not text:
        raise LLMUnavailable("Ollama returned an empty response.")

    return _sanitize(text)


def is_available() -> tuple[bool, str]:
    """One-shot health check for use at watcher startup.

    Returns (ok, msg). Doesn't actually generate anything — just hits Ollama's
    /api/tags endpoint to confirm the daemon is up and the configured model
    is installed. This lets the watcher print a clear startup message
    instead of failing on the first go-live.
    """
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        resp.raise_for_status()
        installed = {m.get("name", "") for m in resp.json().get("models", [])}
    except requests.RequestException as e:
        return False, f"Ollama not reachable at {OLLAMA_URL} ({e})"
    if AI_MODEL not in installed:
        return False, (
            f"Ollama is up but {AI_MODEL!r} is not installed. "
            f"Install with: ollama pull {AI_MODEL}"
        )
    return True, f"Ollama ready ({AI_MODEL})"


def _sanitize(text: str) -> str:
    """Tidy LLM output for chat: single line, no surrounding quotes, length cap.

    Even with the prompt saying "no quotes, no preamble", small models
    occasionally wrap their answer in quotes or include trailing newlines.
    This cleans that up so the chat send is consistently chat-shaped.
    """
    # Strip whitespace, then strip any wrapping quotes the model added.
    text = text.strip().strip("\"'").strip()
    # Collapse all whitespace (including newlines) into single spaces — IRC
    # treats \r and \n as line terminators, so a stray newline would break
    # the chat send.
    text = " ".join(text.split())
    # Trim aggressively to Twitch's chat cap, preferring to cut on a word
    # boundary and appending an ellipsis if we had to cut.
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH].rsplit(" ", 1)[0] + "…"
    return text


if __name__ == "__main__":
    # Standalone test: generate one message for a hypothetical scenario so
    # you can eyeball the model's output without running the full watcher.
    import sys

    streamer = sys.argv[1] if len(sys.argv) > 1 else "celestiayukihime"
    game = sys.argv[2] if len(sys.argv) > 2 else "Valorant"
    print(f"Model: {AI_MODEL}")
    print(f"Streamer: {streamer}")
    print(f"Game: {game}")
    print("Generating...")
    print()
    print(generate_lurk_message(streamer, game))
