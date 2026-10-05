import asyncio
import unittest

from ircweb.core import ChatError, Hub


def drain(u):
    out = []
    while not u.queue.empty():
        out.append(u.queue.get_nowait())
    return out


class HubTest(unittest.TestCase):
    def setUp(self):
        self.h = Hub()
        self.a = self.h.connect("alice")
        self.b = self.h.connect("bob")

    def test_join_and_message(self):
        self.h.handle(self.a.token, "", "/join lobby")
        self.h.handle(self.b.token, "", "/join #lobby")
        drain(self.a)
        drain(self.b)
        self.h.handle(self.a.token, "#lobby", "hi")
        self.assertEqual(drain(self.b)[0]["text"], "hi")
        drain(self.a)
        self.h.handle(self.a.token, "#lobby", "/names")
        self.assertEqual(drain(self.a)[0]["users"], ["alice", "bob"])

    def test_pm(self):
        self.h.handle(self.a.token, "", "/msg bob secret")
        ev = drain(self.b)[-1]
        self.assertEqual((ev["type"], ev["nick"], ev["text"]), ("pm", "alice", "secret"))
        with self.assertRaises(ChatError):
            self.h.handle(self.a.token, "", "/msg nobody x")

    def test_nick_and_part(self):
        self.h.handle(self.a.token, "", "/join #x")
        self.h.handle(self.a.token, "#x", "/nick carol")
        self.assertEqual(self.a.nick, "carol")
        with self.assertRaises(ChatError):
            self.h.handle(self.a.token, "#x", "/nick bob")
        self.h.handle(self.a.token, "#x", "/part")
        self.assertNotIn("#x", self.h.channels)

    def test_errors(self):
        with self.assertRaises(ChatError):
            self.h.connect("alice")
        with self.assertRaises(ChatError):
            self.h.handle(self.a.token, "", "hello")
        with self.assertRaises(ChatError):
            self.h.handle("bad", "", "/help")

    def test_disconnect_notifies(self):
        self.h.handle(self.a.token, "", "/join #x")
        self.h.handle(self.b.token, "", "/join #x")
        drain(self.a)
        self.h.disconnect(self.b.token)
        self.assertEqual(drain(self.a)[0]["type"], "quit")


if __name__ == "__main__":
    unittest.main()
