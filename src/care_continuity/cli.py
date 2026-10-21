"""Run a complete care-circle workflow from the command line."""

from datetime import datetime, timedelta, timezone

from . import ConsentService, DelegationService, KnowledgeService, MemoryService, Operation, RequestState, SQLiteStore


def main() -> None:
    now = datetime(2026, 10, 19, 8, tzinfo=timezone.utc)
    clock = lambda: now
    with SQLiteStore() as store:
        consent = ConsentService(store, clock)
        memory = MemoryService(store, consent, clock)
        requests = DelegationService(store, consent, memory, clock)
        knowledge = KnowledgeService(store, reviewers=frozenset({"reviewer"}), clock=clock)

        def grant(recipient: str, resource_type: str, resource_id: str, operation: Operation) -> str:
            return consent.grant(actor="mei", subject="mei", recipient=recipient,
                                 purpose="visit", resource_type=resource_type, resource_id=resource_id,
                                 operation=operation, expires_at=now + timedelta(days=7))

        print("Care Continuity — local walkthrough\n")
        breakfast = memory.remember(actor="mei", subject="mei", source="mei",
                                    text="I prefer a light breakfast.", confirmed=True)
        worker_access = grant("worker", "memory", breakfast.id, Operation.READ)
        memory.revise(breakfast.id, actor="mei", text="I prefer breakfast after 8.", expected_revision=1)
        print("Current preference:", memory.read(breakfast.id, actor="worker", purpose="visit").text)

        visit = memory.remember(actor="mei", subject="mei", source="mei",
                                text="Agree a time first and keep visits short.", confirmed=True)
        memory.remember(actor="mei", subject="mei", source="mei", text="A family disagreement stays private.")
        for operation in (Operation.READ, Operation.SHARE):
            grant("lina", "memory", visit.id, operation)
        request_id = requests.create(actor="mei", subject="mei", recipient="lina", purpose="visit",
                                     message="I'd like some company in the garden this weekend.",
                                     idempotency_key="garden-visit", memory_ids=(visit.id,))
        print("Mei previews:", requests.read(request_id, actor="mei").message)
        for operation in (Operation.READ, Operation.ACT):
            grant("lina", "request", request_id, operation)
        requests.queue(request_id, actor="mei")
        print("Local delivery:", requests.dispatch(request_id, actor="mei").value)
        requests.transition(request_id, actor="lina", state=RequestState.ACCEPTED)
        print("Lina's response:", requests.read(request_id, actor="lina").state.value)
        requests.transition(request_id, actor="lina", state=RequestState.COMPLETED)
        print("Visit status:", requests.read(request_id, actor="mei").state.value)

        handover = requests.create(actor="mei", subject="mei", recipient="worker", purpose="visit",
                                   message="Please ask about breakfast at the next visit.",
                                   idempotency_key="worker-handover", memory_ids=(breakfast.id,))
        grant("worker", "memory", breakfast.id, Operation.SHARE)
        for operation in (Operation.READ, Operation.ACT):
            grant("worker", "request", handover, operation)
        requests.queue(handover, actor="mei")
        consent.revoke(actor="mei", grant_id=worker_access)
        print("Handover after revocation:", requests.dispatch(handover, actor="mei").value)
        print("Former worker's memory view:", memory.summary(subject="mei", actor="worker", purpose="visit"))

        card = knowledge.submit(contributor="editor", title="Handover procedure",
                                body="Check who accepted the request before marking help as arranged.",
                                kind="procedure", source="Care Continuity procedure library",
                                publication_authorized=True, audience="Supporters", setting="Local demonstration",
                                language="en", limitations="Software fixture, not reviewed care guidance",
                                publication_rights="Original repository demonstration")
        knowledge.review(card, actor="reviewer", review_due=now + timedelta(days=30),
                         privacy_checked=True, scope_checked=True, evidence="Demonstration review only")
        print("Knowledge card:", knowledge.search("handover")[0].title)
        print("\nAll records were held in memory.")


if __name__ == "__main__":
    main()
