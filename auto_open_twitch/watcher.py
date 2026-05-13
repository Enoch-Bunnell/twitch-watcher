# Copyright 2026 Enoch Bunnell, AlyxiC
# SPDX-License-Identifier: Apache-2.0
# See LICENSE in the project root for the full Apache License 2.0 text.

"""Main poll loop. This is the file you actually run.

The watcher keeps three pieces of state across ticks:

    previously_live    set of logins that were live on the previous tick.
                       Used to detect offline->live and live->offline
                       transitions (the difference between this tick's
                       `live` and the previous tick's `live`).

    offline_since      dict of {login: timestamp} for streamers we've
                       SEEN go offline but haven't closed the tab for
                       yet (still inside the grace period). Cleared when
                       the streamer either comes back live or the grace
                       period elapses.

    first_poll         True only on the very first poll after startup.
                       Used so we don't lurk-spam on cold start (we have
                       no idea if the user was already mid-stream from
                       a previous session).

Each tick:

    1. Re-read streamers.txt (hot-reload).
    2. Filter state: drop streamers no longer in the list.
    3. Hit Helix /streams to find out who's currently live.
    4. Query CDP for which Twitch tabs you already have open.
    5. Branch:
        - First poll: open any missing tabs for currently-live streamers,
          but don't lurk. Snapshot to previously_live.
        - Subsequent polls: handle offline->live (open tab + lurk), handle
          live->offline (start grace timer), and check expired grace timers
          (close tab).
"""

from __future__ import annotations

import random
import time
import webbrowser

import requests

from browser_check import close_twitch_tabs, open_tab_background, open_twitch_tabs
from config import (
    LURK_DELAY_MAX_SECONDS,
    LURK_DELAY_MIN_SECONDS,
    OFFLINE_CLOSE_GRACE_SECONDS,
    POLL_INTERVAL_SECONDS,
    load_streamers,
)
from irc_chat import IRCAuthError, pick_lurk_message, send_lurk_message
from llm import LLMUnavailable, generate_lurk_message, is_available as llm_is_available
from twitch_auth import force_reauth, get_access_token, get_authenticated_login
from twitch_client import TokenExpired, get_live_streams


def _open_tab(url: str) -> str:
    """Open a tab without raising the browser window when possible.

    CDP's /json/new keeps the browser in the background; webbrowser.open
    is the focus-stealing fallback for when CDP isn't reachable. We return
    which path we took so the caller can log clearly.

    Returns "bg" (background, ideal) or "fg" (foreground, fallback).
    """
    if open_tab_background(url):
        return "bg"
    webbrowser.open(url)
    return "fg"


def _compose_lurk_message(streamer: str, game: str) -> str:
    """Generate a lurk message via the LLM, falling back to a template.

    Both paths return a chat-ready string. The LLM path logs its output;
    the fallback path logs why it had to fall back.
    """
    try:
        msg = generate_lurk_message(streamer, game)
        print(f"[LLM]     {streamer} — generated: {msg!r}")
        return msg
    except LLMUnavailable as e:
        print(f"[LLM]     unavailable: {e}. Falling back to template.")
        return pick_lurk_message()


def _handle_go_live(
    name: str,
    game: str,
    already_open: set[str],
    token: str,
    my_login: str,
) -> None:
    """The full "streamer just went live" workflow: open tab + send lurk.

    Called from the main loop for each offline->live transition that isn't
    a brief-disconnect recovery (those are handled inline as [BACK] events).
    """
    # 1. Open the tab (skip if it's already open from a previous session
    #    or manual browsing).
    if name in already_open:
        print(f"[GO-LIVE] {name} — tab already open" + (f" ({game})" if game else ""))
    else:
        url = f"https://www.twitch.tv/{name}"
        mode = _open_tab(url)
        focus_note = " [browser raised — launch via launch_opera.bat]" if mode == "fg" else ""
        print(
            f"[GO-LIVE] {name} — opened {url}"
            + (f" ({game})" if game else "")
            + focus_note
        )

    # 2. Generate the lurk message (LLM or template) and wait a small
    #    random delay before sending. The delay makes the timing look less
    #    bot-like — a real chatter wouldn't type the moment a stream starts.
    message = _compose_lurk_message(name, game)
    delay = random.uniform(LURK_DELAY_MIN_SECONDS, LURK_DELAY_MAX_SECONDS)
    print(f"[LURK]    {name} — sending in {delay:.1f}s: {message!r}")
    time.sleep(delay)

    # 3. Send the message. Errors here are non-fatal — log and continue.
    try:
        send_lurk_message(name, message, token, my_login)
        print(f"[LURK]    {name} — sent")
    except IRCAuthError as e:
        print(f"[ERROR]   {e}")
    except (OSError, TimeoutError, ConnectionError) as e:
        print(f"[ERROR]   IRC send failed for {name}: {e}")


def _format_grace() -> str:
    """Human-readable grace period for log messages ("5 min" or "30s")."""
    if OFFLINE_CLOSE_GRACE_SECONDS >= 60:
        return f"{int(OFFLINE_CLOSE_GRACE_SECONDS // 60)} min"
    return f"{int(OFFLINE_CLOSE_GRACE_SECONDS)}s"


def main() -> None:
    # === One-time startup ===

    # get_access_token will pop the OAuth flow if needed (first run, or
    # after scopes changed). Subsequent runs are silent.
    token = get_access_token()
    my_login = get_authenticated_login()

    # Persistent loop state. See the module docstring for what each is for.
    previously_live: set[str] = set()
    offline_since: dict[str, float] = {}
    cdp_warned = False
    first_poll = True
    grace_text = _format_grace()

    print(
        f"Watcher started as @{my_login}. "
        f"Polling every {POLL_INTERVAL_SECONDS}s. Ctrl+C to stop."
    )

    # One-time Ollama health check so the user knows upfront whether the
    # LLM path will work or whether they're getting templates only.
    ok, msg = llm_is_available()
    print(f"[STARTUP] {msg}")
    if not ok:
        print("[STARTUP] Lurk messages will fall back to messages.txt templates.")

    # === Main loop ===

    while True:
        # Re-read streamers.txt so edits are picked up without restarting.
        streamers = load_streamers()
        if not streamers:
            print("streamers.txt is empty — add at least one channel URL.")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        # If the user removed a streamer mid-run, drop any per-streamer
        # state for them so we don't, e.g., auto-close their tab 5 minutes
        # after they removed it from the list.
        streamers_set = set(streamers)
        previously_live &= streamers_set
        for name in list(offline_since):
            if name not in streamers_set:
                del offline_since[name]

        # Ask Helix who's live. Network/auth errors don't kill the watcher.
        try:
            live_streams = get_live_streams(streamers, token)
        except TokenExpired:
            print("Token rejected — re-authenticating.")
            token = force_reauth()
            my_login = get_authenticated_login()
            continue
        except requests.RequestException as e:
            print(f"Network error: {e}. Retrying next tick.")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        live = set(live_streams)
        now = time.time()

        # Ask the browser (via CDP) which tracked streamers already have a
        # tab open. None means CDP isn't reachable — fall back to "I don't
        # know what's open" (empty set).
        externally_open = open_twitch_tabs(streamers)
        if externally_open is None:
            if not cdp_warned:
                print(
                    "Browser remote debugging not detected on :9222 — tab "
                    "detection and auto-close are disabled. Use launch_opera.bat "
                    "to start Opera GX with the flag enabled."
                )
                cdp_warned = True
            already_open: set[str] = set()
        else:
            already_open = externally_open

        if first_poll:
            # === Warm-up tick ===
            # On the very first poll we don't know if the user is mid-stream
            # from earlier or just started the watcher. To avoid spamming
            # chat at startup we open tabs for anyone live but DON'T lurk.
            for name in sorted(live - already_open):
                game = str(live_streams[name].get("game_name", ""))
                url = f"https://www.twitch.tv/{name}"
                mode = _open_tab(url)
                focus_note = (
                    " [browser raised — launch via launch_opera.bat]"
                    if mode == "fg" else ""
                )
                print(
                    f"[LIVE]    {name} — opened {url}"
                    + (f" ({game})" if game else "")
                    + focus_note
                )
            for name in sorted(live & already_open):
                game = str(live_streams[name].get("game_name", ""))
                print(
                    f"[LIVE]    {name} — tab already open"
                    + (f" ({game})" if game else "")
                )
            previously_live = set(live)
            first_poll = False
        else:
            # === Normal tick ===

            # offline -> live transitions. Some are genuine go-lives; others
            # are recoveries from a brief disconnect we hadn't yet acted on
            # because the grace timer hadn't expired. Recovered streamers
            # whose tabs are still open get a quiet [BACK] log and NO lurk
            # (their stream effectively never stopped from a viewer's POV).
            for name in sorted(live - previously_live):
                game = str(live_streams[name].get("game_name", ""))
                came_back = offline_since.pop(name, None) is not None
                if came_back and name in already_open:
                    note = f" ({game})" if game else ""
                    print(
                        f"[BACK]    {name} recovered within grace period — "
                        f"kept tab, no lurk{note}"
                    )
                else:
                    _handle_go_live(name, game, already_open, token, my_login)

            # live -> offline transitions. Don't close yet — start a grace
            # timer instead. The user explicitly wants a buffer so brief
            # scene transitions / disconnects don't yank tabs away.
            for name in sorted(previously_live - live):
                offline_since[name] = now
                print(
                    f"[OFF]     {name} went offline — closing tab in "
                    f"{grace_text} if still offline."
                )

            # Anyone whose grace period has fully expired? Close their tab.
            # We iterate a list() copy of the dict's keys so we can delete
            # entries mid-loop.
            for name in sorted(list(offline_since)):
                if now - offline_since[name] < OFFLINE_CLOSE_GRACE_SECONDS:
                    continue
                closed = close_twitch_tabs(name)
                if closed > 0:
                    print(
                        f"[CLOSE]   {name} — offline {grace_text}+; "
                        f"closed {closed} tab(s)."
                    )
                elif closed == 0:
                    print(
                        f"[CLOSE]   {name} — offline {grace_text}+; "
                        "no matching tab found."
                    )
                else:
                    # close_twitch_tabs returns -1 when CDP isn't reachable.
                    # We still drop them from offline_since so we don't
                    # spam-log every tick — the user already saw the once-
                    # per-run CDP-unavailable warning above.
                    print(
                        f"[CLOSE]   {name} — offline {grace_text}+; "
                        "CDP unavailable, tab not closed."
                    )
                del offline_since[name]

            previously_live = set(live)

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Clean exit on Ctrl+C — no traceback, just a brief acknowledgment.
        print("\nStopped.")
