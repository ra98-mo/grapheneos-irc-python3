"""Dependency-free asyncio HTTP server: JSON API + Server-Sent Events + static UI."""
import argparse
import asyncio
import json
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .core import ChatError, Hub

STATIC = Path(__file__).parent / "static"
MAX_BODY = 8192
HEADERS = (
    "Cache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n"
    "Content-Security-Policy: default-src 'self'; style-src 'self'; script-src 'self'\r\n"
    "Referrer-Policy: no-referrer\r\n"
)


class App:
    def __init__(self):
        self.hub = Hub()

    async def respond(self, w, status, body=b"", ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        w.write(("HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n%sConnection: close\r\n\r\n"
                 % (status, ctype, len(body), HEADERS)).encode() + body)
        await w.drain()

    async def handle(self, r, w):
        try:
            line = await asyncio.wait_for(r.readline(), 15)
            parts = line.decode("latin-1").split()
            if len(parts) < 2:
                return
            method, target = parts[0], parts[1]
            length = 0
            while True:
                h = (await asyncio.wait_for(r.readline(), 15)).decode("latin-1")
                if h in ("\r\n", "\n", ""):
                    break
                k, _, v = h.partition(":")
                if k.lower() == "content-length":
                    length = int(v.strip() or 0)
            if length > MAX_BODY:
                return await self.respond(w, "413 Payload Too Large", {"error": "too large"})
            body = await asyncio.wait_for(r.readexactly(length), 15) if length else b""
            url = urlsplit(target)
            await self.route(method, url.path, parse_qs(url.query), body, w)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, ValueError):
            pass
        finally:
            try:
                w.close()
            except Exception:
                pass

    async def route(self, method, path, query, body, w):
        if method == "GET" and path == "/api/events":
            return await self.events(query.get("token", [""])[0], w)
        if method == "POST" and path.startswith("/api/"):
            try:
                data = json.loads(body or b"{}")
                if not isinstance(data, dict):
                    raise ValueError
            except ValueError:
                return await self.respond(w, "400 Bad Request", {"error": "bad json"})
            try:
                if path == "/api/connect":
                    user = self.hub.connect(str(data.get("nick", "")))
                    return await self.respond(w, "200 OK", {"token": user.token, "nick": user.nick})
                if path == "/api/send":
                    self.hub.handle(str(data.get("token", "")), str(data.get("target", "")),
                                    str(data.get("text", "")))
                    return await self.respond(w, "200 OK", {"ok": True})
                if path == "/api/disconnect":
                    self.hub.disconnect(str(data.get("token", "")))
                    return await self.respond(w, "200 OK", {"ok": True})
            except ChatError as e:
                return await self.respond(w, "400 Bad Request", {"error": str(e)})
            return await self.respond(w, "404 Not Found", {"error": "not found"})
        if method == "GET":
            name = "index.html" if path == "/" else path.lstrip("/")
            f = (STATIC / name).resolve()
            if STATIC.resolve() in f.parents and f.is_file():
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                return await self.respond(w, "200 OK", f.read_bytes(), ctype)
        await self.respond(w, "404 Not Found", {"error": "not found"})

    async def events(self, token, w):
        user = self.hub.tokens.get(token)
        if not user:
            return await self.respond(w, "401 Unauthorized", {"error": "invalid session"})
        w.write(("HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n%sConnection: close\r\n\r\n"
                 % HEADERS).encode())
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(user.queue.get(), 20)
                    w.write(("data: %s\n\n" % json.dumps(ev)).encode())
                except asyncio.TimeoutError:
                    w.write(b": ping\n\n")
                await w.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self.hub.disconnect(token)


async def serve(host, port):
    app = App()
    server = await asyncio.start_server(app.handle, host, port)
    print("Serving on http://%s:%d" % (host, port))
    async with server:
        await server.serve_forever()


def main():
    p = argparse.ArgumentParser(description="Mobile-friendly IRC-like web chat")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    a = p.parse_args()
    try:
        asyncio.run(serve(a.host, a.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
