import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from routier import server
from routier.sessions import RateLimiter, SessionStore

SESSION_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
SESSION_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.previous_data_dir = os.environ.get("ROUTIER_DATA_DIR")
        os.environ["ROUTIER_DATA_DIR"] = str(Path(self.tmp.name) / "shared")
        self.saved = (server.SESSIONS, server.SESSION_EVENTS, server.IP_WRITES)
        server.SESSIONS = SessionStore(Path(self.tmp.name) / "sessions", server.seed_reference)
        server.SESSION_EVENTS = RateLimiter(server.EVENTS_PER_MINUTE_PER_SESSION)
        server.IP_WRITES = RateLimiter(server.WRITES_PER_MINUTE_PER_IP)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.SESSIONS, server.SESSION_EVENTS, server.IP_WRITES = self.saved
        if self.previous_data_dir is None:
            os.environ.pop("ROUTIER_DATA_DIR", None)
        else:
            os.environ["ROUTIER_DATA_DIR"] = self.previous_data_dir
        self.tmp.cleanup()

    def call(self, path, session=None, body=None, method=None):
        headers = {"Content-Type": "application/json"}
        if session:
            headers[server.SESSION_HEADER] = session
        data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
        request = Request(self.base + path, data=data, headers=headers, method=method or ("POST" if data is not None else "GET"))
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())


class SessionTests(ServerCase):
    def test_new_session_starts_from_the_reference_scenario(self):
        status, counts = self.call("/api/metrics", SESSION_A)
        self.assertEqual(status, 200)
        self.assertEqual((counts["accepted"], counts["duplicates"], counts["rejected"]), (4, 1, 1))
        _, overview = self.call("/api/overview", SESSION_A)
        self.assertEqual(overview["open_alerts"], 2)

    def test_a_visitor_never_sees_what_another_sent(self):
        message = server.stream_messages()[2]
        status, result = self.call("/api/events", SESSION_A, message)
        self.assertEqual((status, result["status"]), (201, "accepted"))
        _, mine = self.call("/api/overview", SESSION_A)
        _, theirs = self.call("/api/overview", SESSION_B)
        self.assertIn("flux-203", {event["event_id"] for event in mine["events"]})
        self.assertNotIn("flux-203", {event["event_id"] for event in theirs["events"]})
        _, shared = self.call("/api/overview")
        self.assertEqual(shared["total_events"], 0)

    def test_reset_returns_to_the_reference_scenario(self):
        for message in server.stream_messages()[:3]:
            self.call("/api/events", SESSION_A, message)
        self.assertEqual(self.call("/api/metrics", SESSION_A)[1]["accepted"], 7)
        status, _ = self.call("/api/reset", SESSION_A, method="POST")
        self.assertEqual(status, 200)
        counts = self.call("/api/metrics", SESSION_A)[1]
        self.assertEqual((counts["accepted"], counts["duplicates"], counts["rejected"]), (4, 1, 1))

    def test_reset_needs_a_session_and_bad_identifiers_are_refused(self):
        self.assertEqual(self.call("/api/reset", method="POST")[0], 400)
        self.assertEqual(self.call("/api/overview", "../../etc/passwd")[0], 400)

    def test_expired_sessions_are_deleted(self):
        clock = [1_000_000.0]
        store = SessionStore(Path(self.tmp.name) / "ttl", lambda path: path.touch(), ttl=60, clock=lambda: clock[0])
        old = store.path_for(SESSION_A)
        clock[0] += 120
        store.path_for(SESSION_B)
        self.assertFalse(old.exists())

    def test_session_count_is_capped(self):
        store = SessionStore(Path(self.tmp.name) / "cap", lambda path: path.touch(), max_sessions=2)
        ids = [f"{index:016d}" for index in range(4)]
        for session_id in ids:
            store.path_for(session_id)
        self.assertLessEqual(len(list((Path(self.tmp.name) / "cap").glob("*.db"))), 2)


class StreamTests(ServerCase):
    def test_stream_goes_through_the_real_contract_and_rules(self):
        status, payload = self.call("/api/stream")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(payload["interval_ms"], 1500)
        outcomes = []
        severities = []
        for message in payload["messages"]:
            _, result = self.call("/api/events", SESSION_A, message)
            outcomes.append(result["status"])
            if result["status"] == "accepted":
                severities.append(result["decision"]["severity"])
        self.assertEqual(outcomes.count("duplicate"), 1)
        self.assertEqual(outcomes.count("rejected"), 1)
        self.assertIn("critical", severities)
        audit = self.call("/api/audit", SESSION_A)[1]["items"]
        self.assertEqual(audit[0]["event_id"], payload["messages"][-1]["event_id"])
        rejected = [item for item in audit if item["outcome"] == "rejected" and item["event_id"] == "flux-204"]
        self.assertIn("delay_seconds", rejected[0]["reason"])

    def test_events_per_minute_are_limited_per_session(self):
        server.SESSION_EVENTS = RateLimiter(3)
        message = server.stream_messages()[0]
        codes = [self.call("/api/events", SESSION_A, message)[0] for _ in range(4)]
        self.assertEqual(codes[-1], 429)
        self.assertEqual(self.call("/api/events", SESSION_B, message)[0], 201)

    def test_writes_are_limited_per_ip(self):
        server.IP_WRITES = RateLimiter(2)
        codes = [self.call("/api/reset", SESSION_A, method="POST")[0] for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])


class RateLimiterTests(unittest.TestCase):
    def test_window_slides(self):
        clock = [0.0]
        limiter = RateLimiter(2, window=60, clock=lambda: clock[0])
        self.assertTrue(limiter.allow("ip"))
        self.assertTrue(limiter.allow("ip"))
        self.assertFalse(limiter.allow("ip"))
        clock[0] = 61
        self.assertTrue(limiter.allow("ip"))


if __name__ == "__main__":
    unittest.main()
