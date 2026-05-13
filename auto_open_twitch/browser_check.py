"""Talk to a Chromium-based browser through the Chrome DevTools Protocol.

The Chrome DevTools Protocol (CDP) is a JSON-over-HTTP/WebSocket interface
that Chromium browsers expose when launched with the
`--remote-debugging-port=<port>` flag. We only need the HTTP half:

    GET    /json              -> list of open tabs (each with id, url, title)
    PUT    /json/new?<url>    -> create a new tab pointing at <url>
    GET    /json/close/<id>   -> close the tab with that id

Works with any Chromium browser (Chrome, Edge, Opera GX, Brave) — they all
implement the same protocol. Use launch_opera.bat to start Opera GX with
the flag, or enable_opera_debug.bat to bake the flag into its shortcut.

If the browser isn't running with the debug flag, every function here
fails gracefully (returns None / False / -1) so the watcher can fall back
to less-precise behaviors.
"""

from __future__ import annotations

from urllib.parse import quote

import requests

# All CDP HTTP endpoints share this prefix. Port 9222 is the conventional
# default; if you change it, update launch_opera.bat too.
CDP_BASE = "http://localhost:9222"


def open_twitch_tabs(streamers: list[str]) -> set[str] | None:
    """Return the subset of tracked streamers that already have a tab open.

    We use this to avoid opening a duplicate tab when the user already has
    the stream up (either from a previous run or from manual browsing).

    Returns:
        - set[str]: lowercased usernames whose channel tab is open
          (possibly empty if none of the tracked streamers are on screen)
        - None: CDP isn't reachable. The watcher treats this as "I don't
          know what's open" and falls back to opening every live streamer.
    """
    try:
        resp = requests.get(f"{CDP_BASE}/json", timeout=1.5)
        resp.raise_for_status()
        tabs = resp.json()
    except (requests.RequestException, ValueError):
        return None

    # Pull every tab's URL out once so the inner loop is fast.
    urls = [str(tab.get("url", "")).lower() for tab in tabs]
    found: set[str] = set()
    for name in streamers:
        needle = f"twitch.tv/{name.lower()}"
        for url in urls:
            idx = url.find(needle)
            if idx < 0:
                continue
            # Prefix-collision guard: "twitch.tv/shroud" is a substring of
            # "twitch.tv/shroudfanclub", so we require the character right
            # after the needle to be a path/query/fragment boundary (or end
            # of string), not another username character.
            tail = url[idx + len(needle): idx + len(needle) + 1]
            if tail in ("", "/", "?", "#"):
                found.add(name.lower())
                break
    return found


def close_twitch_tabs(streamer: str) -> int:
    """Close every 'main stream page' tab for this streamer.

    Conservative match — only closes tabs whose URL is *exactly*
    twitch.tv/<streamer> (optionally with ?query or #fragment). VODs, clips,
    profile pages, popout chats, and anything under /videos /clip /about /etc.
    are deliberately left alone since the user probably opened those on
    purpose (whereas the stream URL is the one the watcher auto-opens).

    Returns:
        >= 0: number of tabs actually closed
        -1: CDP unreachable, no action taken
    """
    try:
        resp = requests.get(f"{CDP_BASE}/json", timeout=1.5)
        resp.raise_for_status()
        tabs = resp.json()
    except (requests.RequestException, ValueError):
        return -1

    needle = f"twitch.tv/{streamer.lower()}"
    closed = 0
    for tab in tabs:
        url = str(tab.get("url", "")).lower()
        idx = url.find(needle)
        if idx < 0:
            continue
        tail = url[idx + len(needle): idx + len(needle) + 1]
        # The stricter list (vs open_twitch_tabs above) — no "/" allowed:
        # we want to close ONLY the bare stream URL, not /videos etc.
        if tail not in ("", "?", "#"):
            continue
        tab_id = tab.get("id")
        if not tab_id:
            continue
        try:
            r = requests.get(f"{CDP_BASE}/json/close/{tab_id}", timeout=2)
            if r.status_code == 200:
                closed += 1
        except requests.RequestException:
            # Other tabs might still close successfully; press on.
            pass
    return closed


def open_tab_background(url: str) -> bool:
    """Open a new tab WITHOUT raising/activating the browser window.

    The standard Python `webbrowser.open()` on Windows uses the shell URL
    handler (os.startfile), which always raises the browser window — a
    jump-scare while gaming. CDP's /json/new creates the tab directly in
    the running browser process without touching the window's z-order.

    Returns True if the tab was created; the caller should fall back to
    webbrowser.open() on False (e.g., when CDP is unreachable because the
    browser was launched without the debug flag).
    """
    # The URL goes into the query string. We URL-encode it but preserve the
    # characters that legitimately appear in URLs unescaped (/, :, ?, etc.)
    # so the browser sees the real URL, not double-encoded gibberish.
    endpoint = f"{CDP_BASE}/json/new?{quote(url, safe=':/?#@&=')}"
    try:
        resp = requests.put(endpoint, timeout=3)
        if resp.status_code == 200:
            return True
        # Some Chromium builds dropped PUT support and require POST — Opera
        # GX takes PUT in current versions but this fallback covers churn
        # in upstream Chromium.
        if resp.status_code in (404, 405, 501):
            resp = requests.post(endpoint, timeout=3)
        return resp.status_code == 200
    except requests.RequestException:
        return False
