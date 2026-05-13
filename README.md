# Twitch Auto-Lurker

A personal automation tool that watches your favorite Twitch streamers, opens
their stream in your browser when they go live, sends a (LLM-generated) lurk
message to chat so they know you're around, and tidies up the tab when they
go offline.

## What it does

Every 60 seconds the watcher:

1. Asks Twitch's Helix API which of your tracked streamers are currently live.
2. For any streamer that **just transitioned offline → live**:
   - Opens their stream in a new browser tab — in the *background*, no focus steal.
   - Generates a lurk message via a local Llama 3.2 model that mentions the
     game they're playing (with `messages.txt` templates as fallback).
   - Sends that message to their chat over Twitch IRC after a small random delay.
3. For any streamer that **just transitioned live → offline**:
   - Starts a 5-minute grace timer (so brief disconnects don't matter).
   - If they don't come back within that window, closes the auto-opened tab.

The watcher uses your Twitch account (via OAuth) so the chat message comes
from you, not a separate bot account.

## Quick start

Setup is one-time — see [setup.md](setup.md) for the full walkthrough
(Twitch API registration, Ollama install, browser debug mode, OAuth).

Once setup is done, daily use is:

1. Open Opera GX (already has the debug flag baked into its shortcut if you
   ran `enable_opera_debug.bat`).
2. Double-click `start_watcher.bat`.

Or run `enable_autostart.bat` once and skip step 2 forever.

## File map

### Data files (you edit these)

| File | Purpose |
|---|---|
| `streamers.txt` | Your watch list. One URL or username per line. Hot-reloaded each poll. |
| `messages.txt` | Fallback lurk templates, picked at random when Ollama is unavailable. |
| `.env` | Twitch API credentials + Ollama model name. **Gitignored.** |
| `tokens.json` | Auto-managed OAuth tokens. **Gitignored** — don't share. |

### Python modules (the program)

| File | Purpose |
|---|---|
| `watcher.py` | Main poll loop and orchestrator. Run this. |
| `config.py` | Loads `.env`, defines tunable constants, parses `streamers.txt`. |
| `twitch_auth.py` | OAuth Authorization Code flow with token persistence + auto-refresh. |
| `twitch_client.py` | Helix `/streams` API client. |
| `browser_check.py` | Chrome DevTools Protocol: list / open-in-background / close tabs. |
| `irc_chat.py` | Twitch IRC chat sender + lurk-template picker. |
| `llm.py` | Ollama HTTP client for LLM-generated lurk messages. |

### Launcher scripts (you double-click these)

| File | Purpose |
|---|---|
| `start_watcher.bat` | Run the watcher in the project's venv. |
| `launch_opera.bat` | Force-launch Opera GX with the CDP debug flag enabled. |
| `enable_opera_debug.bat` | One-time patch: add the CDP flag to your Opera shortcut so it's always on. |
| `enable_autostart.bat` | Make the watcher run automatically at Windows login. |
| `disable_autostart.bat` | Undo the above. |

## Standalone tests

Each major module has a `__main__` self-test you can run directly:

```powershell
.venv\Scripts\python.exe twitch_auth.py    # confirm/refresh OAuth tokens
.venv\Scripts\python.exe llm.py            # generate one sample lurk message
.venv\Scripts\python.exe irc_chat.py       # send one message to your OWN channel
```

`irc_chat.py` defaults to your own channel as a safe target so you can verify
chat sending works without spamming someone else.

## Configuration

Tunable constants live in [config.py](config.py):

| Constant | Default | What it does |
|---|---|---|
| `POLL_INTERVAL_SECONDS` | 60 | How often to ask Twitch who's live. |
| `LURK_DELAY_MIN_SECONDS` / `LURK_DELAY_MAX_SECONDS` | 5 / 15 | Random delay before sending a chat message, so it doesn't look like a 0-second bot reaction. |
| `OFFLINE_CLOSE_GRACE_SECONDS` | 300 | Grace period before closing a tab when a streamer goes offline. Set to `0` for immediate close. |
| `SCOPES` | `["chat:read", "chat:edit"]` | Twitch OAuth scopes requested. Changing requires re-auth. |
| `AI_MODEL` | from `.env` | Ollama model name. |

## What you'll see at runtime

```
Watcher started as @ryuzenku_. Polling every 60s. Ctrl+C to stop.
[STARTUP] Ollama ready (llama3.2:3b)
[LIVE]    celestiayukihime — tab already open (Valorant)
[GO-LIVE] otherstreamer — opened https://www.twitch.tv/otherstreamer (Marvel Rivals)
[LLM]     otherstreamer — generated: 'lurking from afk, gl with rivals!'
[LURK]    otherstreamer — sending in 9.7s: 'lurking from afk, gl with rivals!'
[LURK]    otherstreamer — sent
[OFF]     otherstreamer went offline — closing tab in 5 min if still offline.
[BACK]    otherstreamer recovered within grace period — kept tab, no lurk
[CLOSE]   otherstreamer — offline 5 min+; closed 1 tab(s).
```

Log labels:

- `[STARTUP]` — info shown once at watcher start
- `[LIVE]` — initial state of a tracked streamer when the watcher first runs
- `[GO-LIVE]` — streamer just transitioned offline → live
- `[LLM]` / `[LURK]` — message generation and chat send
- `[OFF]` — streamer just transitioned live → offline (grace timer started)
- `[BACK]` — streamer came back live before grace timer expired (no re-lurk)
- `[CLOSE]` — grace timer expired, tab closed
- `[ERROR]` — non-fatal error (network, IRC, etc.) — watcher continues

## Troubleshooting

**"Stored token is missing required scopes …"** — normal after upgrading
scopes (Phase 1 → Phase 2). The watcher pops the Twitch authorize page
automatically; click Authorize and it continues.

**"Browser remote debugging not detected on :9222"** — Opera isn't running
with the debug flag. Either run `launch_opera.bat`, or run
`enable_opera_debug.bat` once to make the flag stick to your shortcut.
Without CDP, the watcher still works but tabs open in the foreground and
there's no auto-close.

**"Ollama not reachable"** — the Ollama tray app isn't running. Open it
from the Start menu, or check that it autostarts. Watcher falls back to
`messages.txt` templates so this is non-fatal.

**Twitch IRC auth rejected** — token doesn't have `chat:edit` scope.
Delete `tokens.json` and re-run; new auth flow will request the right scopes.

**Tab opens but no chat message sent** — check the console for `[ERROR]`
lines. Most likely Ollama failed *and* the IRC send failed; both failing
together is rare but possible (network drop). The watcher will retry on the
next go-live event.

**Brief disconnects causing dupe lurks** — increase
`OFFLINE_CLOSE_GRACE_SECONDS` in `config.py`. The grace timer suppresses a
second lurk when the streamer recovers within the window.

## Privacy & security notes

- `--remote-debugging-port=9222` means anything on `localhost` can read your
  open tabs and inspect pages. Fine on a personal machine; **don't enable it
  on a shared computer**.
- `tokens.json` contains your Twitch access + refresh tokens. Gitignored by
  default. Anyone with the file can act as you on Twitch. Treat it like a
  password.
- `.env` contains your app's client secret. Same.
- IRC messages are sent over TLS (port 6697) but the message body is visible
  to anyone in chat (obviously).

## Future ideas

The original [twitchappsetuo.md](twitchappsetuo.md) spec lists possible
extensions: auto-recording streams, auto-clipping highlights, AI-generated
stream summaries, "smart watchlist" prioritization. None of these are
implemented — they're listed there as ideas if you want to extend the
project.
