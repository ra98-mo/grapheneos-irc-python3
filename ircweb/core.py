"""Transport-independent chat logic: channels, DMs, presence, commands."""
import asyncio
import re
import secrets
import time

NICK_RE = re.compile(r"^[A-Za-z_\[\]\\^{}|`][A-Za-z0-9_\[\]\\^{}|`-]{0,19}$")
CHAN_RE = re.compile(r"^#[A-Za-z0-9_.-]{1,29}$")
MAX_TEXT = 1000
HISTORY = 50

HELP = [
    "/join #channel - join (or create) a channel",
    "/part [#channel] - leave a channel",
    "/msg nick text - send a private message",
    "/me action - send an action",
    "/nick newnick - change nickname",
    "/names [#channel] - list users in a channel",
    "/list - list channels",
    "/topic [text] - show or set the channel topic",
    "/help - show this help",
]


class ChatError(Exception):
    pass


class User:
    def __init__(self, nick):
        self.nick = nick
        self.token = secrets.token_urlsafe(24)
        self.channels = set()
        self.queue = asyncio.Queue(maxsize=1000)

    def push(self, event):
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            pass


class Hub:
    def __init__(self):
        self.users = {}  # lower nick -> User
        self.tokens = {}  # token -> User
        self.channels = {}  # name.lower() -> {"name","topic","members","history"}

    def _event(self, kind, **kw):
        return dict(type=kind, ts=time.time(), **kw)

    def _user(self, token):
        user = self.tokens.get(token)
        if not user:
            raise ChatError("invalid session")
        return user

    def _to_channel(self, chan, event, exclude=None):
        for nick in list(chan["members"]):
            u = self.users.get(nick.lower())
            if u and u is not exclude:
                u.push(event)

    def _members(self, chan):
        return sorted(chan["members"], key=str.lower)

    def _announce_names(self, chan):
        self._to_channel(
            chan,
            self._event("names", channel=chan["name"], users=self._members(chan)),
        )

    def connect(self, nick):
        if not NICK_RE.match(nick or ""):
            raise ChatError("invalid nickname")
        if nick.lower() in self.users:
            raise ChatError("nickname in use")
        user = User(nick)
        self.users[nick.lower()] = user
        self.tokens[user.token] = user
        user.push(self._event("welcome", nick=nick))
        return user

    def disconnect(self, token):
        user = self.tokens.pop(token, None)
        if not user:
            return
        self.users.pop(user.nick.lower(), None)
        for name in list(user.channels):
            self._leave(user, name, "quit")

    def _join(self, user, name):
        if not CHAN_RE.match(name):
            raise ChatError("invalid channel name (use #name)")
        key = name.lower()
        chan = self.channels.get(key)
        if chan is None:
            chan = self.channels[key] = dict(name=name, topic="", members=set(), history=[])
        if user.nick in chan["members"]:
            return
        chan["members"].add(user.nick)
        user.channels.add(chan["name"])
        self._to_channel(chan, self._event("join", channel=chan["name"], nick=user.nick))
        user.push(self._event("joined", channel=chan["name"], topic=chan["topic"],
                              history=list(chan["history"])))
        self._announce_names(chan)

    def _leave(self, user, name, why="part"):
        chan = self.channels.get(name.lower())
        if not chan or user.nick not in chan["members"]:
            raise ChatError("not in " + name)
        self._to_channel(chan, self._event(why, channel=chan["name"], nick=user.nick))
        chan["members"].discard(user.nick)
        user.channels.discard(chan["name"])
        if why == "part":
            user.push(self._event("parted", channel=chan["name"]))
        if chan["members"]:
            self._announce_names(chan)
        else:
            del self.channels[name.lower()]

    def say(self, user, target, text):
        if target.startswith("#"):
            chan = self.channels.get(target.lower())
            if not chan or user.nick not in chan["members"]:
                raise ChatError("not in " + target)
            ev = self._event("message", target=chan["name"], nick=user.nick, text=text)
            chan["history"].append(ev)
            del chan["history"][:-HISTORY]
            self._to_channel(chan, ev)
        else:
            other = self.users.get(target.lower())
            if not other:
                raise ChatError("no such nick: " + target)
            ev = self._event("pm", nick=user.nick, to=other.nick, text=text)
            other.push(ev)
            if other is not user:
                user.push(ev)

    def handle(self, token, target, text):
        """Process a line typed by a user. `target` is the current channel/nick."""
        user = self._user(token)
        text = (text or "").strip()[:MAX_TEXT]
        if not text:
            return
        if not text.startswith("/") or text.startswith("//"):
            if text.startswith("//"):
                text = text[1:]
            if not target:
                raise ChatError("join a channel first with /join #channel")
            return self.say(user, target, text)
        cmd, _, rest = text[1:].partition(" ")
        cmd, rest = cmd.lower(), rest.strip()
        if cmd == "join":
            if not rest:
                raise ChatError("usage: /join #channel")
            for name in rest.split()[:5]:
                self._join(user, name if name.startswith("#") else "#" + name)
        elif cmd == "part":
            self._leave(user, rest or target or "")
        elif cmd in ("msg", "query"):
            to, _, body = rest.partition(" ")
            if not to or not body.strip():
                raise ChatError("usage: /msg nick text")
            self.say(user, to, body.strip())
        elif cmd == "me":
            if not target or not rest:
                raise ChatError("usage: /me action (in a channel or DM)")
            self.say(user, target, "\x01ACTION " + rest)
        elif cmd == "nick":
            self._rename(user, rest)
        elif cmd == "names":
            chan = self.channels.get((rest or target or "").lower())
            if not chan:
                raise ChatError("no such channel")
            user.push(self._event("names", channel=chan["name"], users=self._members(chan)))
        elif cmd == "list":
            lines = ["%s (%d)%s" % (c["name"], len(c["members"]),
                                    " - " + c["topic"] if c["topic"] else "")
                     for c in sorted(self.channels.values(), key=lambda c: c["name"].lower())]
            user.push(self._event("info", text="Channels: " + (", ".join(lines) or "none")))
        elif cmd == "topic":
            chan = self.channels.get((target or "").lower())
            if not chan or user.nick not in chan["members"]:
                raise ChatError("topic: not in a channel")
            if rest:
                chan["topic"] = rest[:200]
                self._to_channel(chan, self._event("topic", channel=chan["name"],
                                                   nick=user.nick, topic=chan["topic"]))
            else:
                user.push(self._event("info", text="Topic: " + (chan["topic"] or "(none)")))
        elif cmd == "help":
            user.push(self._event("info", text="\n".join(HELP)))
        else:
            raise ChatError("unknown command /" + cmd)

    def _rename(self, user, new):
        if not NICK_RE.match(new):
            raise ChatError("invalid nickname")
        if new.lower() in self.users and self.users[new.lower()] is not user:
            raise ChatError("nickname in use")
        old = user.nick
        chans = [self.channels[c.lower()] for c in user.channels]
        del self.users[old.lower()]
        user.nick = new
        self.users[new.lower()] = user
        for chan in chans:
            chan["members"].discard(old)
            chan["members"].add(new)
        user.push(self._event("nick", old=old, new=new, mine=True))
        for chan in chans:
            self._to_channel(chan, self._event("nick", old=old, new=new, mine=False),
                             exclude=user)
            self._announce_names(chan)
