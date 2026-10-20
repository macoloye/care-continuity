"""Application walkthrough with separate owner and caregiver sessions."""

from datetime import datetime, timedelta, timezone

from .application import CareApplication
from .domain import Operation, RequestState
from .sessions import SessionService
from .store import SQLiteStore


def main() -> None:
    now = datetime(2026, 10, 19, 8, tzinfo=timezone.utc)
    clock = lambda: now
    with SQLiteStore() as store:
        sessions, app = SessionService(store, clock), CareApplication(store, clock)
        # Local session bootstrap. A production adapter must verify identity first.
        mei, lina = sessions.issue("mei"), sessions.issue("lina")
        app.add_member(mei, member="lina", role="supporter")
        memory = app.remember(mei, text="Agree a time first and keep visits short.", confirmed=True)
        print("Lina's memory view before sharing:", len(app.memories(lina, subject="mei", purpose="visit")))
        request = app.create_request(mei, recipient="lina", purpose="visit",
                                     message="I'd like company in the garden this weekend.",
                                     idempotency_key="garden", memory_ids=(memory.id,))
        print("Mei previews:", app.read_request(mei, request).message)
        for resource_type, resource_id, operations in (
            ("memory", memory.id, (Operation.READ, Operation.SHARE)),
            ("request", request, (Operation.READ, Operation.ACT)),
        ):
            for operation in operations:
                app.grant(mei, recipient="lina", purpose="visit", resource_type=resource_type,
                          resource_id=resource_id, operation=operation, expires_at=now + timedelta(days=1))
        app.plan_followup(mei, request, due_at=now + timedelta(hours=1),
                          alternative="Ask me whether to suggest a different day.")
        app.queue(mei, request)
        app.dispatch(mei, request)
        now += timedelta(hours=1)
        print("Needs a response:", app.requests(mei)[0]["needs_followup"])
        print("Lina's inbox:", app.inbox(lina)[0].message)
        app.transition(lina, request, state=RequestState.ACCEPTED)
        print("After acceptance:", app.requests(mei)[0]["state"])
        print("Export sections:", ", ".join(app.export(mei)))
        app.remove_member(mei, member="lina")
        print("Lina's inbox after removal:", len(app.inbox(lina)))
        print("Unfinished request:", app.requests(mei)[0]["state"])
        app.logout(mei)
        app.logout(lina)
        print("Sessions closed.")


if __name__ == "__main__":
    main()
