# grapheneos-irc-python3

IRC-like chat in pure Python 3 (no dependencies) with a mobile-first web UI.

    python3 -m ircweb --host 0.0.0.0 --port 8080

Open the page, pick a nickname, then use `/join #channel`, `/msg nick text`,
`/me`, `/nick`, `/names`, `/list`, `/topic`, `/part`, `/help`. Tap ☰ for
channels and the user list; tap a user to start a DM. Transport is JSON over
HTTP POST plus Server-Sent Events. State is in memory; run behind TLS in
production.

Tests: `python3 -m unittest discover tests`
