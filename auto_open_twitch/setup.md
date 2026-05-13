# Setup

One-time setup. Follow in order. Expect 15–20 minutes total.

## Prerequisites

- Windows 10 or 11
- Python 3.11 or newer (3.14 is what the project was developed against)
- A Chromium-based browser — Opera GX is the assumed default in the included
  scripts; Chrome, Edge, and Brave also work
- ~3 GB free disk space (for the Llama 3.2 model)
- A Twitch account

---

## 1. Python + virtual environment

Install Python from <https://www.python.org/downloads/> if you don't have it.
Make sure "Add Python to PATH" is checked during install.

Open a terminal in the project folder and run:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Or, if you use VS Code:

1. Open the project folder.
2. Press **Ctrl+Shift+P** → "Python: Create Environment".
3. Pick **Venv**, then Python 3.14.
4. When prompted, check `requirements.txt` so dependencies get auto-installed.

Verify by running:

```powershell
.venv\Scripts\python.exe -c "import requests, dotenv; print('OK')"
```

---

## 2. Register a Twitch developer application

The watcher calls Twitch's official Helix API. Twitch requires every API
caller to register an "application" to get a Client ID + Client Secret.

1. Go to <https://dev.twitch.tv/console/apps>.
2. Sign in with your Twitch account.
3. Click **Register Your Application**.
4. Fill in:
   - **Name**: anything (e.g., `auto-lurker`).
   - **OAuth Redirect URLs**: `http://localhost:3000/auth/twitch/callback`
     **(must match byte-for-byte what you'll put in `.env`)**.
   - **Category**: *Application Integration*.
   - **Client Type**: *Confidential*.
5. Click **Create**.
6. On the app detail page:
   - Copy the **Client ID** (always visible).
   - Click **New Secret** and copy the secret immediately — it's only shown once.

---

## 3. Create the `.env` file

Create a file named `.env` in the project root (same directory as
`watcher.py`). It's already in `.gitignore`. Paste this, substituting your
real values from step 2:

```
CLIENT_ID=your_client_id_here
CLIENT_SECRET=your_client_secret_here
REDIRECT_URI=http://localhost:3000/auth/twitch/callback
AI_BACKEND=llama3.2:3b
```

Notes:

- `REDIRECT_URI` must be **identical** to the URL you registered in step 2.
  Twitch rejects auth codes if even one character differs (trailing slash,
  port number, http vs https, case).
- `AI_BACKEND` is the Ollama model name. We use the 3B variant of Llama 3.2
  because it runs comfortably on CPU and is fast enough for short messages.

---

## 4. Install Ollama and pull the model

Ollama is a small local server for running LLMs on your machine. The
watcher talks to it over HTTP on `localhost:11434`.

1. Download Ollama for Windows from <https://ollama.com/download/windows>.
2. Run the installer.
3. After install, Ollama runs as a **system tray icon** and autostarts at
   login by default.
4. Open a terminal and pull the model:

   ```powershell
   ollama pull llama3.2:3b
   ```

   This downloads ~2 GB. The model name here **must match `AI_BACKEND`** in
   your `.env`.

Verify Ollama is running:

```powershell
curl http://localhost:11434/api/tags
```

You should get a JSON response listing the installed models, including
`llama3.2:3b`.

If you'd rather skip the LLM, the watcher falls back to picking from
`messages.txt` automatically. But the per-stream variety in generated
messages is the main reason to have Ollama set up.

---

## 5. Browser debug mode

The watcher uses the **Chrome DevTools Protocol** (CDP) to:

- See which Twitch tabs you already have open (avoid dupes)
- Open new tabs in the background (no focus steal mid-game)
- Close tabs when streamers go offline (after grace period)

Any Chromium-based browser supports this *if* it's launched with the
`--remote-debugging-port=9222` flag.

Pick one approach:

### Option A — patch your Opera shortcut (recommended)

Run `enable_opera_debug.bat` once. It finds your Opera shortcut(s) in the
Start menu / Desktop / taskbar pin folders and appends the debug flag to
their Arguments field. After running:

1. Close **all** Opera windows (Task Manager → check for stray `opera.exe`
   if you want to be thorough).
2. Launch Opera normally from the Start menu / taskbar / desktop.
3. It's now running with CDP enabled, and every future launch will too.

To undo: right-click the shortcut → Properties → remove
`--remote-debugging-port=9222` from the Target/Arguments field.

### Option B — launch_opera.bat each session

Don't want to patch shortcuts? Run `launch_opera.bat` instead of clicking
the Opera icon. It opens Opera with the debug flag for that session only.

Same caveat: Opera ignores the flag if an instance is already running, so
close all Opera windows first.

### Option C — manually edit the shortcut

Right-click Opera shortcut → Properties → append
` --remote-debugging-port=9222` to the Target field (note the leading space
between the existing path and the flag).

### Verify

Once Opera is running with the flag, open a new tab and visit
<http://localhost:9222/json>. You should see a JSON array of your open
tabs. If you get a connection error, the flag isn't active — either Opera
was already running before you applied the flag, or the shortcut wasn't
modified.

---

## 6. List your streamers

Open `streamers.txt`. Replace the example with the streamers you actually
want to track. Format:

```
# Comments start with # and are ignored.
# Full URLs or bare usernames both work.
https://www.twitch.tv/celestiayukihime
candypeachesgg
shroud
```

Hot-reloaded — the watcher reads this file each poll, so you can edit it
while the watcher is running.

---

## 7. First run + Twitch authorization

Double-click `start_watcher.bat`. The first run will:

1. Open a browser tab to Twitch's authorize page.
2. Twitch asks: *"Allow this app to send chat messages on your behalf?"* —
   click **Authorize**.
3. Twitch redirects to `localhost:3000/auth/twitch/callback?code=…`. The
   watcher has spun up a tiny local HTTP server that catches the redirect,
   exchanges the code for access + refresh tokens, and stores them in
   `tokens.json`.
4. The watcher prints `Watcher started as @<your_login>.` and begins polling.

Subsequent runs reuse `tokens.json`. The watcher silently refreshes the
access token when it expires (every ~4 hours), so you only see the auth
flow once.

---

## 8. (Optional) Run on every login

If you want the watcher running every time you sign into Windows:

Double-click `enable_autostart.bat`. It drops a shortcut into your
Windows Startup folder. The watcher's console window will appear at each
login — you can minimize it. To stop without disabling autostart, close
that console (or Ctrl+C in it).

To turn it off: `disable_autostart.bat`.

---

## Verification checklist

After setup, all of these should succeed:

```powershell
# 1. Auth works (and creates/refreshes tokens.json)
.venv\Scripts\python.exe twitch_auth.py
# Expected: "Got access token (length=...) for @<your_login>."

# 2. Helix API works (returns empty dict if no one is live)
.venv\Scripts\python.exe -c "from twitch_auth import get_access_token; from twitch_client import get_live_streams; print(get_live_streams(['celestiayukihime'], get_access_token()))"

# 3. LLM works
.venv\Scripts\python.exe llm.py
# Expected: a coherent lurk message

# 4. Chat send works (real message to YOUR own channel)
.venv\Scripts\python.exe irc_chat.py
# Expected: "Sent." — check your own channel chat for the message

# 5. Browser CDP works (Opera must be running with the flag)
curl http://localhost:9222/json
# Expected: JSON array of tabs
```

If all five pass, run `start_watcher.bat` and you're done.

---

## Common setup issues

**`KeyError: 'CLIENT_ID'`**
`.env` is missing, or doesn't have `CLIENT_ID=` on a line. Check that the
file is in the project folder (next to `watcher.py`), not in a parent or
subfolder.

**`Twitch OAuth failed: invalid redirect URI`**
The `REDIRECT_URI` in `.env` doesn't byte-match what you registered in the
Twitch dev console. Common mistakes: trailing slash, `http` vs `https`,
port number, missing `/auth/twitch/callback` path.

**`[WinError 10048] Only one usage of each socket address`** (during auth)
Something else is using port 3000. Either kill that process, or change
your redirect URI to a different port (e.g., `http://localhost:3001/auth/twitch/callback`)
in **both** the Twitch dev console and `.env`.

**`Ollama not reachable`**
The Ollama tray app isn't running. Open it from the Start menu. If it
should autostart and doesn't, check Windows Settings → Apps → Startup.

**`Ollama is up but 'llama3.2:3b' is not installed`**
You haven't pulled the model, or the name in `.env` doesn't match what
`ollama list` shows. Run `ollama pull llama3.2:3b`.

**Opera shows tabs in `/json` but watcher says CDP not reachable**
Possible Windows firewall block. Allow `python.exe` and `opera.exe` in
Windows Defender Firewall for the loopback adapter, or try the script
from an elevated terminal once.

**Tabs still steal focus when opening**
Opera isn't running with the debug flag. Run `enable_opera_debug.bat`,
then close ALL Opera windows and relaunch.

**Watcher closes the streamer's tab even though they're still online**
False-offline detection from Twitch is rare but happens. Increase
`OFFLINE_CLOSE_GRACE_SECONDS` in `config.py`. The default 300s (5 min) is
already generous, but you can bump it to 600 or 900 if you're seeing it.
