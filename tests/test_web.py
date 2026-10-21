"""Browser adapter contracts and real loopback HTTP boundary checks."""

import http.client
import json
import re
import threading
import unittest
from datetime import timedelta
from http.server import HTTPServer
from queue import Queue
from urllib.parse import parse_qs, urlencode, urlsplit

from care_continuity import AccessDenied, Conflict, SQLiteStore
from care_continuity.domain import timestamp
from care_continuity.web import WebApp, handler_for


class WebContracts(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteStore()
        self.addCleanup(self.store.close)
        self.web = WebApp(self.store)
        self.mei = self.web.sessions.issue("mei")
        self.lina = self.web.sessions.issue("lina")
        self.worker = self.web.sessions.issue("worker")

    def post(self, path, token=None, **fields):
        token = token or self.mei
        data = {key: value if isinstance(value, list) else [str(value)] for key, value in fields.items()}
        data["csrf"] = [self.web.csrf(token)]
        return self.web.post(path, data, token)

    def draft(self):
        memory = self.web.app.export(self.mei)["memories"][0]
        response = self.post("/request/draft", recipient="lina", message="Company in the garden?",
                             key="garden", memory=[memory["id"]])
        return parse_qs(urlsplit(response.headers["Location"]).query)["id"][0], memory

    def approve(self, request):
        return self.post("/request/approve", id=request,
                         expires=timestamp(self.web.app.clock() + timedelta(days=1)))

    def test_preview_precedes_delivery_and_full_loop_works(self):
        request, _ = self.draft()
        self.assertEqual((), self.web.app.inbox(self.lina))
        preview = self.web.get("/request/preview?id=" + request, self.mei).body
        for expected in ("Company in the garden?", "Permission ends", "support visit", "Approve sharing"):
            self.assertIn(expected, preview)
        self.approve(request)
        self.assertIn("Company in the garden?", self.web.get("/inbox", self.lina).body)
        self.post("/request/transition", self.lina, id=request, state="accepted")
        self.post("/request/transition", self.lina, id=request, state="completed")
        self.assertEqual("completed", self.web.app.requests(self.mei)[0]["state"])

    def test_changed_preview_cannot_create_partial_grants(self):
        request, memory = self.draft()
        self.web.app.revise(self.mei, memory["id"], text="No visits", expected_revision=1)
        with self.assertRaises(Conflict):
            self.approve(request)
        self.assertEqual([], self.web.app.sharing(self.mei))
        self.assertEqual("draft", self.web.app.requests(self.mei)[0]["state"])

    def test_approval_retry_does_not_create_grants_twice(self):
        request, _ = self.draft()
        self.approve(request)
        before = len(self.web.app.sharing(self.mei))
        with self.assertRaises(Conflict):
            self.approve(request)
        self.assertEqual(before, len(self.web.app.sharing(self.mei)))

    def test_other_actor_cannot_approve_or_override_identity(self):
        request, _ = self.draft()
        with self.assertRaises(AccessDenied):
            self.post("/request/approve", self.lina, id=request,
                      expires=timestamp(self.web.app.clock() + timedelta(days=1)))
        with self.assertRaises(ValueError):
            self.post("/memory/save", self.lina, actor="mei", text="Forged")

    def test_csrf_must_match_the_current_session(self):
        with self.assertRaises(AccessDenied):
            self.web.post("/memory/save", {"csrf": [self.web.csrf(self.lina)], "text": ["Forged"]}, self.mei)

    def test_profile_switch_revokes_previous_session(self):
        response = self.post("/login", profile="lina")
        self.assertIn("HttpOnly; SameSite=Strict", response.headers["Set-Cookie"])
        with self.assertRaises(AccessDenied):
            self.web.sessions.resolve(self.mei)

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(AccessDenied):
            self.post("/login", profile="stranger")

    def test_rendered_memory_is_escaped(self):
        self.post("/memory/save", text='<script>alert("private")</script>')
        html = self.web.get("/memories", self.mei).body
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_forgetting_removes_text_from_owner_pages_and_export(self):
        request, memory = self.draft()
        self.approve(request)
        self.post("/memory/forget", id=memory["id"])
        exported = json.loads(self.web.get("/export", self.mei).body)
        self.assertNotIn(memory["text"], json.dumps(exported))
        self.assertEqual("cancelled", exported["requests"][0]["state"])
        self.assertNotIn("Company in the garden?", self.web.get("/inbox", self.lina).body)

    def test_permission_revocation_removes_inbox_content(self):
        request, _ = self.draft()
        self.approve(request)
        grant = self.web.app.sharing(self.mei)[0]
        self.post("/sharing/revoke", id=grant["id"])
        self.assertNotIn("Company in the garden?", self.web.get("/inbox", self.lina).body)

    def test_observation_submission_and_owner_review(self):
        response = self.post("/observation/submit", self.worker, subject="mei", text="Mei enjoyed the garden.")
        self.assertEqual("/observations", response.headers["Location"])
        worker_page = self.web.get("/observations", self.worker).body
        self.assertIn("Mei enjoyed the garden.", worker_page)
        self.assertIn("Waiting for review", worker_page)
        owner_page = self.web.get("/memories", self.mei).body
        self.assertIn("Observations to review", owner_page)
        self.assertIn("From Alex", owner_page)
        observation = self.web.app.pending_observations(self.mei)[0]
        self.post("/observation/accept", self.mei, id=observation.id)
        owner_page = self.web.get("/memories", self.mei).body
        self.assertNotIn("Observations to review", owner_page)
        self.assertIn("observation · Source: Alex", owner_page)
        worker_page = self.web.get("/observations", self.worker).body
        self.assertIn("Added to the record", worker_page)

    def test_owner_can_dismiss_an_observation(self):
        self.post("/observation/submit", self.worker, subject="mei", text="Seemed tired.")
        observation = self.web.app.pending_observations(self.mei)[0]
        self.post("/observation/dismiss", self.mei, id=observation.id)
        self.assertEqual((), self.web.app.pending_observations(self.mei))
        self.assertNotIn("Seemed tired.", json.dumps(json.loads(self.web.get("/export", self.mei).body)))

    def test_contributor_can_withdraw_a_pending_observation(self):
        self.post("/observation/submit", self.worker, subject="mei", text="Mentioned an old friend.")
        observation = self.web.app.pending_observations(self.mei)[0]
        self.post("/observation/withdraw", self.worker, id=observation.id)
        self.assertEqual((), self.web.app.pending_observations(self.mei))
        self.assertNotIn("Mentioned an old friend.", self.web.get("/observations", self.worker).body)

    def test_observation_submission_requires_membership(self):
        with self.assertRaises(AccessDenied):
            self.post("/observation/submit", self.worker, subject="lina", text="About Lina.")

    def test_followup_outcome_can_be_recorded(self):
        request, _ = self.draft()
        self.approve(request)
        self.post("/request/followup", id=request, hours=24, alternative="Ask about next week.")
        self.post("/request/resolve", id=request, note="Called Lina on the phone.")
        page = self.web.get("/requests", self.mei).body
        self.assertIn("Called Lina on the phone.", page)
        self.assertNotIn("No one has accepted yet", page)
        with self.assertRaises(Conflict):
            self.post("/request/resolve", id=request, note="Again.")

    def test_all_owner_pages_render_without_javascript(self):
        for path in ("/", "/memories", "/circle", "/sharing", "/requests", "/history", "/inbox", "/observations"):
            with self.subTest(path=path):
                response = self.web.get(path, self.mei)
                self.assertEqual(200, response.status)
                self.assertIn('id="main"', response.body)
                self.assertIn('lang="en"', response.body)
                self.assertNotIn('<script', response.body)


class HTTPBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ready = Queue()

        def serve():
            try:
                with SQLiteStore() as store:
                    web = WebApp(store)
                    with HTTPServer(("127.0.0.1", 0), handler_for(web, "pending")) as server:
                        authority = f"127.0.0.1:{server.server_port}"
                        server.RequestHandlerClass = handler_for(web, authority)
                        ready.put((server, authority))
                        server.serve_forever(poll_interval=0.02)
            except BaseException as error:
                ready.put(error)

        cls.thread = threading.Thread(target=serve, daemon=True)
        cls.thread.start()
        result = ready.get(timeout=10)
        if isinstance(result, BaseException):
            raise result
        cls.server, cls.authority = result

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)

    def request(self, method="GET", path="/", data=None, headers=None):
        connection = http.client.HTTPConnection(self.authority, timeout=5)
        try:
            body = urlencode(data) if data else None
            request_headers = {"Content-Type": "application/x-www-form-urlencoded"} if data else {}
            request_headers.update(headers or {})
            connection.request(method, path, body, request_headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode()
        finally:
            connection.close()

    def login_data(self):
        _, _, html = self.request()
        csrf = re.search(r'name="csrf" value="([^"]+)"', html)[1]
        return {"csrf": csrf, "profile": "mei"}

    def test_security_headers_and_stylesheet(self):
        status, headers, body = self.request()
        self.assertEqual(200, status)
        self.assertEqual("no-store", headers["Cache-Control"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertIn("Care Continuity", body)
        status, headers, body = self.request(path="/style.css")
        self.assertEqual(200, status)
        self.assertIn("text/css", headers["Content-Type"])
        self.assertIn("focus-visible", body)

    def test_cross_origin_and_rebinding_requests_fail(self):
        self.assertEqual(403, self.request(headers={"Host": "attacker.invalid"})[0])
        self.assertEqual(403, self.request("POST", "/login", self.login_data(), {"Origin": "https://attacker.invalid"})[0])
        self.assertEqual(403, self.request("POST", "/login", self.login_data(), {"Origin": "null", "Sec-Fetch-Site": "cross-site"})[0])

    def test_local_webkit_origin_fallback_still_requires_csrf(self):
        for origin in (None, "null", "http://" + self.authority):
            headers = {} if origin is None else {"Origin": origin}
            status, response_headers, _ = self.request("POST", "/login", self.login_data(), headers)
            self.assertEqual(303, status)
            self.assertIn("HttpOnly", response_headers["Set-Cookie"])
            self.assertEqual(403, self.request("POST", "/login", {"csrf": "forged", "profile": "mei"}, headers)[0])

    def test_malformed_form_and_post_only_mutations(self):
        status, _, _ = self.request("POST", "/login", {"csrf": "", "profile": "mei"}, {"Origin": "http://" + self.authority})
        self.assertEqual(403, status)
        status, headers, _ = self.request("POST", "/login", self.login_data(), {"Origin": "http://" + self.authority})
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(404, self.request(path="/memory/forget", headers={"Cookie": cookie})[0])
        status, _, body = self.request(path="/export", headers={"Cookie": cookie})
        self.assertEqual(200, status)
        self.assertEqual("mei", json.loads(body)["subject"])


if __name__ == "__main__":
    unittest.main()
