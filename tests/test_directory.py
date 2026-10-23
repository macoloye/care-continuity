"""Directory setup contracts: people and relationships never grant data access."""

import unittest
from datetime import timedelta

from care_continuity import (AccessDenied, CareApplication, ConsentService, Conflict,
                             MemoryService, SQLiteStore, SessionService)
from care_continuity.circle import CircleService
from care_continuity.directory import DirectoryService


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteStore()
        self.addCleanup(self.store.close)
        self.directory = DirectoryService(self.store, CircleService(self.store))
        for person_id, kind in (("mei", "person"), ("lina", "carer")):
            self.directory.ensure_person(person_id=person_id, name=person_id.title(), kind=kind)
        self.app = CareApplication(self.store)
        self.mei = SessionService(self.store).issue("mei")
        self.lina = SessionService(self.store).issue("lina")

    def events(self, subject):
        return self.store.connection.execute(
            "SELECT actor, action FROM events WHERE subject=? ORDER BY sequence", (subject,)).fetchall()

    def test_create_person_adds_a_choosable_profile_and_audit_entry(self):
        person = self.directory.create_person(operator="local-setup", person_id="priya",
                                              name="Priya", kind="person")
        self.assertEqual("person", person["kind"])
        self.assertIn("priya", self.directory.names())
        self.assertEqual([("local-setup", "person.created")],
                         [(row["actor"], row["action"]) for row in self.events("priya")])

    def test_create_person_rejects_invalid_input(self):
        for person_id, name, kind in (("Priya!", "Priya", "person"), ("", "Priya", "person"),
                                      ("priya", "  ", "person"), ("priya", "x" * 61, "person"),
                                      ("priya", "Priya", "reviewer"), ("priya", "Priya", "admin")):
            with self.subTest(person_id=person_id, kind=kind):
                with self.assertRaises(ValueError):
                    self.directory.create_person(operator="local-setup", person_id=person_id,
                                                 name=name, kind=kind)
        self.directory.create_person(operator="local-setup", person_id="priya", name="Priya", kind="person")
        with self.assertRaises(Conflict):
            self.directory.create_person(operator="local-setup", person_id="priya", name="Again", kind="carer")

    def test_ensure_person_is_idempotent_for_restarts(self):
        before = len(self.events("mei"))
        self.directory.ensure_person(person_id="mei", name="Mei", kind="person")
        self.directory.ensure_person(person_id="mei", name="Mei", kind="person")
        self.assertEqual({"mei", "lina"}, set(self.directory.names()))
        self.assertEqual(before, len(self.events("mei")))

    def deny_read(self, actor, subject):
        """A filtered summary alone is not denial; check a direct read of the record."""
        memories = self.app.export(self.mei)["memories"]
        self.assertEqual((), self.app.memories(actor, subject=subject, purpose="support visit"))
        with self.assertRaises(AccessDenied):
            MemoryService(self.store, ConsentService(self.store)).read(
                memories[0]["id"], actor=actor, purpose="support visit")

    def test_set_relationship_records_membership_and_audits_the_operator(self):
        self.directory.set_relationship(operator="local-setup", subject="mei", member="lina", role="worker")
        relationship = self.directory.relationships()[0]
        self.assertEqual(("mei", "lina", "worker"),
                         (relationship["subject"], relationship["member"], relationship["role"]))
        self.assertIsNone(relationship["removed_at"])
        self.assertEqual(("local-setup", "circle.added"),
                         (self.events("mei")[-1]["actor"], self.events("mei")[-1]["action"]))
        # Saving again changes the role without a second membership row.
        self.directory.set_relationship(operator="local-setup", subject="mei", member="lina", role="coordinator")
        self.assertEqual(1, len(self.directory.relationships()))
        self.assertEqual("coordinator", self.directory.relationships()[0]["role"])

    def test_relationship_setup_grants_no_access_to_care_records(self):
        self.app.remember(self.mei, text="I prefer breakfast after 8.", confirmed=True)
        self.directory.set_relationship(operator="local-setup", subject="mei", member="lina", role="worker")
        self.deny_read(self.lina, "mei")
        # Membership is still a contribution boundary.
        self.app.observe(self.lina, subject="mei", text="Mei enjoyed the garden.")
        self.assertEqual(1, len(self.app.pending_observations(self.mei)))

    def test_relationships_require_two_known_people(self):
        with self.assertRaises(AccessDenied):
            self.directory.set_relationship(operator="local-setup", subject="mei", member="stranger", role="worker")
        with self.assertRaises(AccessDenied):
            self.directory.set_relationship(operator="local-setup", subject="stranger", member="lina", role="worker")
        with self.assertRaises(ValueError):
            self.directory.set_relationship(operator="local-setup", subject="mei", member="mei", role="worker")
        with self.assertRaises(ValueError):
            self.directory.set_relationship(operator="local-setup", subject="mei", member="lina", role="friend")

    def test_end_relationship_revokes_sharing_and_cancels_unfinished_requests(self):
        self.directory.set_relationship(operator="local-setup", subject="mei", member="lina", role="supporter")
        request = self.app.create_request(self.mei, recipient="lina", purpose="support visit",
                                          message="Company in the garden?", idempotency_key="garden")
        self.app.approve_request(self.mei, request, expires_at=self.app.clock() + timedelta(days=1))
        self.assertEqual(1, len(self.app.inbox(self.lina)))
        self.directory.end_relationship(operator="local-setup", subject="mei", member="lina")
        sharing = self.app.sharing(self.mei)
        self.assertTrue(sharing)
        self.assertFalse(any(grant["active"] for grant in sharing))
        self.assertEqual("cancelled", self.app.requests(self.mei)[0]["state"])
        self.assertEqual((), self.app.inbox(self.lina))
        self.assertEqual(("local-setup", "circle.removed"),
                         (self.events("mei")[-1]["actor"], self.events("mei")[-1]["action"]))

    def test_end_relationship_requires_an_active_membership(self):
        with self.assertRaises(AccessDenied):
            self.directory.end_relationship(operator="local-setup", subject="mei", member="lina")


if __name__ == "__main__":
    unittest.main()
