"""Send a one-shot message to a Twitch channel over IRC.

Twitch's chat runs on IRC (Internet Relay Chat) — a decades-old text
protocol that's still surprisingly clean for this kind of automation. We
do the smallest possible IRC dance:

    1. Open a TLS socket to irc.chat.twitch.tv:6697.
    2. Send `PASS oauth:<token>` and `NICK <username>`.
    3. Wait for the server to send back "001 welcome" (RPL_WELCOME), which
       confirms auth succeeded.
    4. Send `JOIN #<channel>` to enter that channel's chatroom.
    5. Send `PRIVMSG #<channel> :<message>` — this is the actual chat line.
    6. Send `QUIT` and close.

No long-lived connection, no PING/PONG keepalive, no chat reading. If a
future phase needs to watch chat for context, that'd need a persistent
connection in a background thread.

References:
  Twitch IRC: https://dev.twitch.tv/docs/irc/
  IRC protocol (RFC 1459): https://datatracker.ietf.org/doc/html/rfc1459
"""

from __future__ import annotations

import random
import socket
import ssl
import time
from pathlib import Path

# Twitch's IRC endpoint. Port 6697 is TLS; the plaintext port 6667 also
# works but TLS is the better default since we send an OAuth token.
IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6697

MESSAGES_FILE = Path(__file__).parent / "messages.txt"
# Used only if messages.txt is missing or empty AND the LLM is unavailable.
_FALLBACK_MESSAGE = "lurking, have a great stream!"


class IRCAuthError(Exception):
    """Twitch rejected our IRC credentials (token usually lacks chat:edit)."""


def send_lurk_message(
    channel: str, message: str, access_token: str, username: str
) -> None:
    """Connect to Twitch IRC, send one PRIVMSG, then disconnect.

    Args:
        channel: target channel name (no leading #; we add it). Lowercased.
        message: the chat line to send. Should be <500 chars (Twitch's cap).
        access_token: user OAuth token with chat:edit scope.
        username: the authenticated user's login (the IRC NICK).

    Raises:
        IRCAuthError: Twitch rejected our PASS/NICK (token issue).
        TimeoutError / ConnectionError / OSError: transport issues.
    """
    # Twitch is strict about lowercase + no leading #.
    channel = channel.lower().lstrip("#")
    username = username.lower()

    # Plain TCP first, then wrap in TLS. We use the default SSL context so
    # certificate validation happens (we're sending a credential, after all).
    raw_sock = socket.create_connection((IRC_HOST, IRC_PORT), timeout=10)
    ctx = ssl.create_default_context()
    sock = ctx.wrap_socket(raw_sock, server_hostname=IRC_HOST)
    sock.settimeout(10)
    try:
        # STEP 1+2: authenticate. Twitch wants PASS before NICK, and PASS
        # takes the OAuth token prefixed with "oauth:" (not a real password).
        sock.sendall(
            f"PASS oauth:{access_token}\r\nNICK {username}\r\n".encode("utf-8")
        )

        # STEP 3: wait for the welcome reply. _wait_for_welcome raises
        # IRCAuthError immediately if the server says auth failed, so we
        # don't end up JOINing a channel we can't post to.
        _wait_for_welcome(sock)

        # STEP 4: join the channel. We don't strictly need to wait for the
        # JOIN confirmation — Twitch accepts PRIVMSG even before we see
        # the join echo — but a small sleep avoids a race where the message
        # arrives before the JOIN registers.
        sock.sendall(f"JOIN #{channel}\r\n".encode("utf-8"))
        time.sleep(0.4)

        # STEP 5: send the actual chat message. The IRC format is
        # `PRIVMSG #channel :message text` — the `:` indicates "rest of line".
        sock.sendall(
            f"PRIVMSG #{channel} :{message}\r\n".encode("utf-8")
        )
        # Small pause so the server processes the PRIVMSG before we
        # disconnect (otherwise an immediate QUIT could drop the message).
        time.sleep(0.4)

        # STEP 6: polite disconnect. If QUIT fails because the server
        # already closed us, that's fine — close() below handles it.
        try:
            sock.sendall(b"QUIT\r\n")
        except OSError:
            pass
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _wait_for_welcome(sock: ssl.SSLSocket) -> None:
    """Block until we see RPL_WELCOME (numeric reply 001) or detect auth failure.

    Twitch sends a few lines after PASS+NICK:
      - On success: ":tmi.twitch.tv 001 <nick> :Welcome, GLHF!"
      - On failure: ":tmi.twitch.tv NOTICE * :Login authentication failed"

    We don't fully parse IRC — just substring-scan the accumulated buffer
    for ` 001 ` (success marker) or the known failure phrases.
    """
    buf = b""
    deadline = time.time() + 10
    while True:
        if b" 001 " in buf:
            return
        if (
            b"Login authentication failed" in buf
            or b"Login unsuccessful" in buf
            or b"Improperly formatted auth" in buf
        ):
            raise IRCAuthError(
                "Twitch IRC rejected the token. It's likely missing the "
                "chat:edit scope — delete tokens.json and rerun to re-authorize."
            )
        if time.time() > deadline:
            raise TimeoutError("Timed out waiting for Twitch IRC welcome.")
        chunk = sock.recv(4096)
        if not chunk:
            # Server hung up before saying anything useful.
            raise ConnectionError("Twitch IRC closed before sending welcome.")
        buf += chunk


def pick_lurk_message() -> str:
    """Return a random non-comment line from messages.txt.

    Used as the fallback when the LLM is unavailable. Comments (lines
    starting with #) and blank lines are skipped.
    """
    if not MESSAGES_FILE.exists():
        return _FALLBACK_MESSAGE
    lines = [
        line.strip()
        for line in MESSAGES_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return random.choice(lines) if lines else _FALLBACK_MESSAGE


if __name__ == "__main__":
    # Standalone self-test: send a random lurk message. Defaults to the
    # authenticated user's own channel (safe target — won't spam someone
    # else's chat). Pass another channel name as the first argument to
    # send there instead.
    import sys

    from twitch_auth import get_access_token, get_authenticated_login

    token = get_access_token()
    login = get_authenticated_login()
    channel = sys.argv[1] if len(sys.argv) > 1 else login
    message = pick_lurk_message()
    print(f"Sending to #{channel} as @{login}: {message!r}")
    send_lurk_message(channel, message, token, login)
    print("Sent.")
