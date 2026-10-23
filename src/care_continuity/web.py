"""Loopback HTTP adapter for the Care Continuity application."""

import argparse
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from secrets import token_urlsafe
from urllib.parse import parse_qs, urlencode, urlsplit

from .application import CareApplication
from . import demo, demo_views
from .conversation import ConversationService
from .reviews import SuggestionReviews
from .circle import CircleService
from .directory import DirectoryService
from .domain import AccessDenied, Clock, Conflict, RequestState, timestamp, utc_now
from .sessions import SessionService
from .store import SQLiteStore
from . import web_views as views


@dataclass
class Response:
    status: int = 200
    body: str = ""
    headers: dict[str, str] = field(default_factory=dict)


class WebApp:
    """Transport-independent controller managing the local profiles."""

    def __init__(self, store: SQLiteStore, clock: Clock = utc_now) -> None:
        self.store = store
        self.directory = DirectoryService(store, CircleService(store, clock), clock)
        demo.install_examples(store)
        self.app = CareApplication(store, clock, reviewers=self.directory.reviewers(),
                                   delivery_providers=frozenset({demo.TRANSPORT}))
        self.sessions = SessionService(store, clock)
        self._csrf_key = token_urlsafe(32).encode()
        self.conversation = ConversationService(store, adapters={demo.MODEL: demo.suggest}, clock=lambda: self.app.clock())
        self.reviews = SuggestionReviews(self.conversation)

    def approval_signature(self, token: str, request_id: str, expires: str, provider: str) -> str:
        payload = json.dumps([token, request_id, expires, provider]).encode()
        return hmac.new(self._csrf_key, payload, hashlib.sha256).hexdigest()

    def suggestion_page(self, token: str, handle: str, *, message: str | None = None, error: str = "") -> Response:
        review = self.reviews.get(token, handle)
        context = self.conversation._context(token, review.provider, review.selections,
                                             require_grants=review.suggestion is not None)
        body = demo_views.review(review, context, handle, self.csrf(token), [m for m in self.app.members(token) if m["removed_at"] is None],
                                 self.directory.names(), message=message, error=error)
        return Response(400 if error else 200, views.page("Review a simulated suggestion", body,
            actor=self.actor(token), csrf=self.csrf(token), names=self.directory.names()))

    def csrf(self, token: str) -> str:
        return hmac.new(self._csrf_key, token.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def cookie(token: str) -> str:
        # HTTP loopback only. A production HTTPS adapter must add Secure.
        return f"care_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={28800 if token else 0}"

    @staticmethod
    def one(data: dict[str, list[str]], key: str) -> str:
        values = data.get(key, [])
        if len(values) != 1:
            raise ValueError("A required field is missing or repeated")
        return values[0]

    @staticmethod
    def redirect(path: str) -> Response:
        return Response(303, headers={"Location": path})

    def actor(self, token: str) -> str:
        actor = self.sessions.resolve(token)
        self.directory.require_person(actor)
        return actor

    def get(self, target: str, token: str) -> Response:
        self.reviews.prune()
        path = urlsplit(target).path
        if path == "/style.css":
            return Response(body=files("care_continuity").joinpath("static/style.css").read_text(),
                            headers={"Content-Type": "text/css; charset=utf-8"})
        if path == "/admin":
            # Local setup surface, like the profile chooser: loopback only, no identity claim.
            return Response(body=views.admin(self.directory.people(), self.directory.relationships(),
                                             self.directory.names(), self.csrf(token)))
        try:
            actor = self.actor(token)
        except AccessDenied:
            return Response(body=views.login(self.directory.people(), self.csrf(token)))
        csrf, names = self.csrf(token), self.directory.names()
        if path == "/export":
            return Response(body=json.dumps(self.app.export(token), indent=2), headers={
                "Content-Type": "application/json; charset=utf-8",
                "Content-Disposition": 'attachment; filename="care-continuity-export.json"'})
        if path == "/suggestions":
            title, body = "Try a suggested request", demo_views.choose(self.app.export(token)["memories"], csrf)
        elif path == "/suggestion/review":
            return self.suggestion_page(token, self.one(parse_qs(urlsplit(target).query), "handle"))
        elif path == "/attention":
            title, body = "What needs attention?", demo_views.attention(self.app.requests(token),
                self.app.pending_observations(token), self.app.deliveries(token), names)
        elif path == "/request/preview":
            query = parse_qs(urlsplit(target).query)
            request_id = self.one(query, "id")
            hours = int(self.one(query, "hours")) if "hours" in query else 24
            provider = self.one(query, "provider") if "provider" in query else "local"
            if hours not in (1, 24, 168) or provider not in ("local", demo.TRANSPORT):
                raise ValueError("Choose an offered delivery method and duration")
            request = self.app.read_request(token, request_id)
            if request.subject != actor or request.state != RequestState.DRAFT:
                raise AccessDenied("Draft unavailable")
            expires = timestamp(self.app.clock() + timedelta(hours=hours))
            signature = self.approval_signature(token, request_id, expires, provider)
            title = "Review before sharing"
            body = views.preview(request, names, csrf, expires, provider=provider, signature=signature, hours=hours)
        elif path == "/knowledge":
            query = parse_qs(urlsplit(target).query, keep_blank_values=True)
            search = self.one(query, "q") if "q" in query else ""
            title, body = "Knowledge library", views.knowledge_library(
                self.app.search_knowledge(token, search), names, search)
        elif path == "/knowledge/submissions":
            title, body = "Knowledge submissions", views.knowledge_submissions(
                self.app.knowledge_submissions(token), names, actor)
        elif path == "/knowledge/new":
            title, body = "Contribute a knowledge card", views.knowledge_form(csrf)
        elif path == "/knowledge/review":
            card_id = self.one(parse_qs(urlsplit(target).query), "id")
            evidence = self.app.knowledge_evidence(token, card_id)
            card = next(card for card in self.app.knowledge_submissions(token) if card.id == card_id)
            title, body = "Inspect knowledge submission", views.knowledge_review(card, evidence, names, actor, csrf)
        elif path == "/deliveries":
            title, body = "Delivery status", views.deliveries(self.app.deliveries(token), names)
        elif path == "/inbox":
            title, body = "My inbox", views.inbox(self.app.inbox(token), names, csrf)
        elif path == "/observations":
            title, body = "My observations", views.observations(
                self.app.my_observations(token), self.app.circle_subjects(token), names, csrf)
        elif path in ("/", "/memories", "/circle", "/sharing", "/requests", "/history"):
            account = self.app.export(token)
            if path == "/memories":
                title, body = "What matters to me", views.memories(
                    account, names, csrf, self.app.pending_observations(token))
            elif path == "/circle":
                title, body = "My care circle", views.circle(account, actor, names, csrf)
            elif path == "/sharing":
                title, body = "What I’m sharing", views.sharing(account, names, csrf)
            elif path == "/requests":
                title, body = "My support requests", views.requests(account, names, csrf, token_urlsafe(20))
            elif path == "/history":
                title = "My activity history"
                body = '<p>Changes to your records and requests, in order.</p><ol>' + ''.join(
                    f'<li><strong>{views.e(event["action"])}</strong> · {views.e(event["actor"])} · {views.e(event["occurred_at"])}</li>'
                    for event in account["events"]) + '</ol>'
            else:
                title = f"Welcome, {names.get(actor, actor)}"
                pending = sum(r["state"] in ("draft", "queued", "delivered") for r in account["requests"])
                body = '<p class="lead">Your preferences. Your choices. Support you can follow.</p><div class="cards">'
                for href, heading, count, description in (
                    ("/memories", "Remember what matters", len(account["memories"]), "preferences saved"),
                    ("/requests", "Follow through", pending, "requests awaiting agreement"),
                    ("/inbox", "Support someone", len(self.app.inbox(token)), "requests shared with you"),
                ):
                    body += f'<article><h2><a href="{href}">{heading}</a></h2><p class="count">{count}</p><p>{description}</p></article>'
                body += '</div><section><h2>You stay in control</h2><p>Choose what is remembered and who can see it. You can change your mind at any time.</p><p><a href="/sharing">Review sharing</a> · <a href="/history">View activity history</a> · <a href="/export">Download my records (JSON)</a></p></section>'
        else:
            return self.error(404, "Page not found", token)
        return Response(body=views.page(title, body, actor=actor, csrf=csrf, section=path, names=names))

    def post(self, path: str, data: dict[str, list[str]], token: str) -> Response:
        self.reviews.prune()
        try:
            return self._post(path, data, token)
        finally:
            self.reviews.prune()

    def _post(self, path: str, data: dict[str, list[str]], token: str) -> Response:
        csrf = self.one(data, "csrf")
        if not hmac.compare_digest(csrf, self.csrf(token)):
            raise AccessDenied("This form expired. Reload the page and try again")
        fields = {
            "/suggestion/preview": {"memory", "hours"},
            "/suggestion/generate": {"handle"}, "/suggestion/discard": {"handle"},
            "/suggestion/save": {"handle", "message", "recipient"},
            "/knowledge/submit": {"title", "body", "kind", "source", "audience", "setting", "language",
                                  "limitations", "publication_rights", "publication_authorized"},
            "/knowledge/publish": {"id", "days", "privacy_checked", "scope_checked", "evidence"},
            "/knowledge/withdraw": {"id"},
            "/login": {"profile"}, "/logout": set(),
            "/memory/save": {"text"}, "/memory/revise": {"id", "text", "revision"},
            "/memory/forget": {"id"}, "/circle/add": {"member", "role"}, "/circle/remove": {"member"},
            "/sharing/revoke": {"id"}, "/request/draft": {"recipient", "message", "memory", "key"},
            "/request/approve": {"id", "expires", "provider", "signature"}, "/request/transition": {"id", "state"},
            "/request/followup": {"id", "hours", "alternative"}, "/request/resolve": {"id", "note"},
            "/observation/submit": {"subject", "text"}, "/observation/accept": {"id"},
            "/observation/dismiss": {"id"}, "/observation/withdraw": {"id"},
            "/admin/person": {"id", "name", "kind"},
            "/admin/relationship": {"subject", "member", "role"},
            "/admin/relationship/end": {"subject", "member"},
        }
        if path not in fields:
            return self.error(404, "Action not found", token)
        if set(data) - fields[path] - {"csrf"}:
            raise ValueError("Unexpected form field")
        value = lambda key: self.one(data, key)
        if path == "/login":
            actor = value("profile")
            self.directory.require_person(actor)
            if token:
                self.sessions.revoke(token)
            new_token = self.sessions.issue(actor)
            result = self.redirect("/")
            result.headers["Set-Cookie"] = self.cookie(new_token)
            return result
        if path == "/admin/person":
            # Setup identity is fixed here, never taken from the form.
            self.directory.create_person(operator="local-setup", person_id=value("id"),
                                         name=value("name"), kind=value("kind"))
            return self.redirect("/admin")
        if path == "/admin/relationship":
            self.directory.set_relationship(operator="local-setup", subject=value("subject"),
                                            member=value("member"), role=value("role"))
            return self.redirect("/admin")
        if path == "/admin/relationship/end":
            self.directory.end_relationship(operator="local-setup", subject=value("subject"),
                                            member=value("member"))
            return self.redirect("/admin")
        self.actor(token)
        if path == "/logout":
            self.app.logout(token)
            result = self.redirect("/")
            result.headers["Set-Cookie"] = self.cookie("")
            return result
        if path == "/suggestion/preview":
            memories = {m["id"]: m for m in self.app.export(token)["memories"]}
            ids = data.get("memory", [])
            if not ids or len(ids) > 20 or len(set(ids)) != len(ids) or any(key not in memories for key in ids):
                raise ValueError("Select between one and twenty of your current memories")
            handle = self.reviews.create(token, provider=demo.MODEL, hours=int(value("hours")),
                selections=tuple((key, memories[key]["revision"]) for key in ids))
            return self.redirect("/suggestion/review?" + urlencode({"handle": handle}))
        if path == "/suggestion/generate":
            self.reviews.generate(token, value("handle"))
            return self.redirect("/suggestion/review?" + urlencode({"handle": value("handle")}))
        if path == "/suggestion/discard":
            self.reviews.discard(token, value("handle"))
            return self.redirect("/suggestions")
        if path == "/suggestion/save":
            review = self.reviews.get(token, value("handle"))
            if review.suggestion is None:
                raise Conflict("Generate and review a suggestion before saving")
            message = value("message")
            if not message.strip() or len(message) > 4000:
                return self.suggestion_page(token, value("handle"), message=message[:4000],
                                            error="Enter a message between 1 and 4000 characters.")
            request_id = self.conversation.save_draft(token, review.suggestion, reviewed_message=message,
                recipient=value("recipient"), purpose="support visit", idempotency_key="review-" + value("handle"))
            return self.redirect("/request/preview?" + urlencode({"id": request_id}))
        if path == "/knowledge/submit":
            card_id = self.app.submit_knowledge(token,
                **{key: value(key) for key in ("title", "body", "kind", "source", "audience", "setting",
                                               "language", "limitations", "publication_rights")},
                publication_authorized=value("publication_authorized") == "yes")
            return self.redirect("/knowledge/review?" + urlencode({"id": card_id}))
        if path == "/knowledge/publish":
            days = int(value("days"))
            if not 1 <= days <= 365:
                raise ValueError("Choose a review interval between 1 and 365 days")
            self.app.review_knowledge(token, value("id"), review_due=self.app.clock() + timedelta(days=days),
                privacy_checked=value("privacy_checked") == "yes", scope_checked=value("scope_checked") == "yes",
                evidence=value("evidence"))
            return self.redirect("/knowledge/review?" + urlencode({"id": value("id")}))
        if path == "/knowledge/withdraw":
            self.app.withdraw_knowledge(token, value("id"))
            return self.redirect("/knowledge/submissions")
        if path == "/memory/save":
            self.app.remember(token, text=value("text"), confirmed=True)
            return self.redirect("/memories")
        if path == "/memory/revise":
            self.app.revise(token, value("id"), text=value("text"), expected_revision=int(value("revision")))
            return self.redirect("/memories")
        if path == "/memory/forget":
            self.app.forget(token, value("id"))
            return self.redirect("/memories")
        if path == "/circle/add":
            self.directory.require_person(value("member"))
            self.app.add_member(token, member=value("member"), role=value("role"))
            return self.redirect("/circle")
        if path == "/circle/remove":
            self.app.remove_member(token, member=value("member"))
            return self.redirect("/circle")
        if path == "/sharing/revoke":
            self.app.revoke(token, value("id"))
            return self.redirect("/sharing")
        if path == "/request/draft":
            if not value("message").strip() or len(value("message")) > 4000:
                account = self.app.export(token)
                self.app._circle.require_member(self.actor(token), value("recipient"))
                body = views.requests(account, self.directory.names(), csrf, value("key"),
                    entered=data, error="Enter a message between 1 and 4000 characters.")
                return Response(400, views.page("My support requests", body, actor=self.actor(token),
                    csrf=csrf, names=self.directory.names()))
            request_id = self.app.create_request(token, recipient=value("recipient"), purpose="support visit",
                message=value("message"), idempotency_key=value("key"), memory_ids=tuple(data.get("memory", [])))
            return self.redirect("/request/preview?" + urlencode({"id": request_id}))
        if path == "/request/approve":
            provider = value("provider")
            expected = self.approval_signature(token, value("id"), value("expires"), provider)
            if not hmac.compare_digest(value("signature"), expected):
                raise AccessDenied("Sharing preview changed or expired; review it again")
            expiry = datetime.fromisoformat(value("expires"))
            if not self.app.clock() < expiry <= self.app.clock() + timedelta(days=7):
                raise ValueError("Choose an expiry within the next seven days")
            if provider == "local":
                self.app.approve_request(token, value("id"), expires_at=expiry)
                return self.redirect("/requests")
            if provider != demo.TRANSPORT:
                raise AccessDenied("Choose a configured delivery method")
            self.app.approve_external_request(token, value("id"), provider=provider, expires_at=expiry)
            return self.redirect("/deliveries")
        if path == "/request/transition":
            state = RequestState(value("state"))
            if state not in (RequestState.ACCEPTED, RequestState.COMPLETED, RequestState.CANCELLED):
                raise ValueError("Unsupported action")
            self.app.transition(token, value("id"), state=state)
            return self.redirect("/requests" if state == RequestState.CANCELLED else "/inbox")
        if path == "/request/resolve":
            self.app.resolve_followup(token, value("id"), note=value("note"))
            return self.redirect("/requests")
        if path == "/observation/submit":
            self.app.observe(token, subject=value("subject"), text=value("text"))
            return self.redirect("/observations")
        if path == "/observation/accept":
            self.app.accept_observation(token, value("id"))
            return self.redirect("/memories")
        if path == "/observation/dismiss":
            self.app.dismiss_observation(token, value("id"))
            return self.redirect("/memories")
        if path == "/observation/withdraw":
            self.app.withdraw_observation(token, value("id"))
            return self.redirect("/observations")
        hours = int(value("hours"))
        if not 1 <= hours <= 168:
            raise ValueError("Choose between 1 and 168 hours")
        self.app.plan_followup(token, value("id"), due_at=self.app.clock() + timedelta(hours=hours), alternative=value("alternative"))
        return self.redirect("/requests")

    def error(self, status: int, message: str, token: str) -> Response:
        try:
            actor = self.actor(token)
        except AccessDenied:
            actor = None
        body = f'<p role="alert">{views.e(message)}</p><p><a href="/suggestions">Start a new suggestion</a> · <a href="/requests">Review requests</a> · <a href="/">Return to overview</a></p>'
        return Response(status, views.page("We couldn’t complete that", body, actor=actor, csrf=self.csrf(token)))


def handler_for(web: WebApp, authority: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            # Request targets, cookies, and bodies may contain private information.
            pass

        def _send(self, response: Response) -> None:
            body = response.body.encode("utf-8")
            self.send_response(response.status)
            headers = {
                "Content-Type": "text/html; charset=utf-8", "Content-Length": str(len(body)),
                "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            }
            for key, value in (headers | response.headers).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _token(self) -> str:
            cookie = SimpleCookie()
            cookie.load(self.headers.get("Cookie", ""))
            return cookie["care_session"].value if "care_session" in cookie else ""

        def _handle(self, *, post: bool) -> None:
            token = ""
            try:
                if self.headers.get_all("Host") != [authority]:
                    raise AccessDenied("Use the local address printed by the server")
                token = self._token()
                if len(token) > 256:
                    raise AccessDenied("Session unavailable")
                if not post:
                    response = web.get(self.path, token)
                else:
                    # Some local WebKit form submissions omit or redact Origin.
                    # The session-bound CSRF token remains mandatory in all cases.
                    origin = self.headers.get("Origin")
                    if origin not in (None, "null", "http://" + authority) or self.headers.get("Sec-Fetch-Site") == "cross-site":
                        raise AccessDenied("Submit this form from the local application")
                    if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                        raise ValueError("Unsupported request body")
                    length = int(self.headers["Content-Length"])
                    if not 0 < length <= 32768:
                        raise ValueError("Form is too large or empty")
                    if self.headers.get_content_type() != "application/x-www-form-urlencoded":
                        raise ValueError("Use a standard form submission")
                    body = self.rfile.read(length)
                    if len(body) != length:
                        raise ValueError("Incomplete form submission")
                    data = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=100)
                    if any(len(item) > 4000 for values in data.values() for item in values):
                        raise ValueError("Keep each field under 4,000 characters")
                    response = web.post(urlsplit(self.path).path, data, token)
            except AccessDenied as error:
                response = web.error(403, str(error), token)
            except Conflict as error:
                response = web.error(409, str(error), token)
            except (ValueError, TypeError, CookieError, UnicodeError):
                response = web.error(400, "Check the form fields and try again. If the page is old, reload it first.", token)
            self._send(response)

        def do_GET(self) -> None:
            self._handle(post=False)

        def do_POST(self) -> None:
            self._handle(post=True)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Care Continuity web application on loopback")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=":memory:", help="SQLite database path (default: in-memory)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Choose a port between 1 and 65535")
    authority = f"127.0.0.1:{args.port}"
    with SQLiteStore(args.db) as store:
        web = WebApp(store)
        with HTTPServer(("127.0.0.1", args.port), handler_for(web, authority)) as server:
            server.timeout = 1
            print(f"Care Continuity: http://{authority}", flush=True)
            storage = args.db if args.db != ":memory:" else "Records are held in memory"
            print(f"{storage}. Press Ctrl+C to stop.", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
