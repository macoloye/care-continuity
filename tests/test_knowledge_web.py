"""Editorial browser flows and their disclosure boundaries."""

import unittest
from urllib.parse import parse_qs, urlsplit

from care_continuity import AccessDenied, Conflict, SQLiteStore
from care_continuity.web import WebApp


class KnowledgeWebTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteStore()
        self.addCleanup(self.store.close)
        self.web = WebApp(self.store)
        self.author = self.web.sessions.issue("mei")
        self.reader = self.web.sessions.issue("lina")
        self.reviewer = self.web.sessions.issue("reviewer")

    def post(self, path, token, **values):
        return self.web.post(path, {"csrf": [self.web.csrf(token)],
                                   **{key: [str(value)] for key, value in values.items()}}, token)

    def submit(self, token=None, **overrides):
        fields = dict(title="Example <script> card", body="Synthetic body", kind="experience",
                      source="Source <citation>", audience="Supporters", setting="Home", language="en",
                      limitations="Example only", publication_rights="Private rights evidence", publication_authorized="yes")
        response = self.post("/knowledge/submit", token or self.author, **(fields | overrides))
        url = response.headers["Location"]
        return url, parse_qs(urlsplit(url).query)["id"][0]

    def publish(self, card, token=None, **overrides):
        return self.post("/knowledge/publish", token or self.reviewer,
                         **(dict(id=card, days=30, privacy_checked="yes", scope_checked="yes",
                                 evidence="Private review evidence") | overrides))

    def test_editorial_flow_and_public_private_separation(self):
        url, card = self.submit()
        self.assertNotIn("Synthetic body", self.web.get("/knowledge", self.reader).body)
        self.assertNotIn("Example &lt;script&gt;", self.web.get("/knowledge/submissions", self.reader).body)
        with self.assertRaises(AccessDenied):
            self.web.get(url, self.reader)
        preview = self.web.get(url, self.reviewer).body
        self.assertIn("Private rights evidence", preview)
        self.assertIn("Record review and publish", preview)
        self.assertNotIn("Record review and publish", self.web.get(url, self.author).body)
        self.publish(card)
        library = self.web.get("/knowledge?q=Synthetic", self.reader).body
        for content in ("Synthetic body", "Example &lt;script&gt; card", "Source &lt;citation&gt;", "Example only"):
            self.assertIn(content, library)
        for content in ("<script>", "Private rights evidence", "Private review evidence"):
            self.assertNotIn(content, library)
        self.assertIn("Private review evidence", self.web.get(url, self.author).body)
        self.post("/knowledge/withdraw", self.author, id=card)
        self.assertNotIn("Synthetic body", self.web.get("/knowledge", self.reader).body)
        self.assertNotIn("Record review and publish", self.web.get(url, self.reviewer).body)
        with self.assertRaises(Conflict):
            self.publish(card)

    def test_authority_identity_fields_and_csrf_cannot_be_forged(self):
        _, card = self.submit()
        with self.assertRaises(AccessDenied):
            self.publish(card, self.author)
        with self.assertRaises(AccessDenied):
            self.post("/knowledge/withdraw", self.reader, id=card)
        with self.assertRaises(ValueError):
            self.submit(contributor="reviewer")
        with self.assertRaises(AccessDenied):
            self.web.post("/knowledge/withdraw", {"id": [card], "csrf": [self.web.csrf(self.reader)]}, self.author)
        self.web.app.logout(self.reviewer)
        with self.assertRaises(AccessDenied):
            self.publish(card)

    def test_self_review_and_incomplete_attestations_are_denied(self):
        _, card = self.submit(self.reviewer)
        with self.assertRaises(AccessDenied):
            self.publish(card)
        _, card = self.submit()
        for fields in ({"days": 0}, {"days": 366}, {"evidence": " "},
                       {"privacy_checked": "no"}, {"scope_checked": "no"}):
            with self.assertRaises(ValueError):
                self.publish(card, **fields)
        self.assertEqual((), self.web.app.search_knowledge(self.reader))
        with self.assertRaises(AccessDenied):
            self.submit(publication_authorized="no")

    def test_empty_pages_and_search_are_escaped(self):
        for path in ("/knowledge", "/knowledge/new", "/knowledge/submissions"):
            body = self.web.get(path, self.author).body
            self.assertIn('<main id="main"', body)
            self.assertIn('href="/knowledge"', body)
        body = self.web.get('/knowledge?q=%22%3E%3Cscript%3E', self.reader).body
        self.assertNotIn('<script>', body)
        self.assertIn('&lt;script&gt;', body)
