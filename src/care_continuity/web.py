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
from .domain import AccessDenied, Conflict, RequestState, timestamp
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

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self.app = CareApplication(store)
        self.sessions = SessionService(store)
        self._csrf_key = token_urlsafe(32).encode()
        token = self.sessions.issue("mei")
        self.app.add_member(token, member="lina", role="supporter")
        self.app.add_member(token, member="worker", role="worker")
        self.app.remember(token, text="I prefer breakfast after 8.", confirmed=True)
        self.app.remember(token, text="Agree a time first and keep visits short.", confirmed=True)
        self.app.logout(token)

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
        if actor not in views.PEOPLE:
            raise AccessDenied("Profile unavailable")
        return actor

    def get(self, target: str, token: str) -> Response:
        path = urlsplit(target).path
        if path == "/style.css":
            return Response(body=files("care_continuity").joinpath("static/style.css").read_text(),
                            headers={"Content-Type": "text/css; charset=utf-8"})
        try:
            actor = self.actor(token)
        except AccessDenied:
            return Response(body=views.login(self.csrf(token)))
        csrf = self.csrf(token)
        if path == "/export":
            return Response(body=json.dumps(self.app.export(token), indent=2), headers={
                "Content-Type": "application/json; charset=utf-8",
                "Content-Disposition": 'attachment; filename="care-continuity-export.json"'})
        if path == "/request/preview":
            request_id = self.one(parse_qs(urlsplit(target).query), "id")
            request = self.app.read_request(token, request_id)
            if request.subject != actor or request.state != RequestState.DRAFT:
                raise AccessDenied("Draft unavailable")
            title = "Review before sharing"
            body = views.preview(request, csrf, timestamp(self.app.clock() + timedelta(days=7)))
        elif path == "/inbox":
            title, body = "My inbox", views.inbox(self.app.inbox(token), csrf)
        elif path in ("/", "/memories", "/circle", "/sharing", "/requests", "/history"):
            account = self.app.export(token)
            if path == "/memories":
                title, body = "What matters to me", views.memories(account, csrf)
            elif path == "/circle":
                title, body = "My care circle", views.circle(account, actor, csrf)
            elif path == "/sharing":
                title, body = "What I’m sharing", views.sharing(account, csrf)
            elif path == "/requests":
                title, body = "My support requests", views.requests(account, csrf, token_urlsafe(20))
            elif path == "/history":
                title = "My activity history"
                body = '<p>Changes to your records and requests, in order.</p><ol>' + ''.join(
                    f'<li><strong>{views.e(event["action"])}</strong> · {views.e(event["actor"])} · {views.e(event["occurred_at"])}</li>'
                    for event in account["events"]) + '</ol>'
            else:
                title = f"Welcome, {views.PEOPLE[actor]}"
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
        return Response(body=views.page(title, body, actor=actor, csrf=csrf, section=path))

    def post(self, path: str, data: dict[str, list[str]], token: str) -> Response:
        csrf = self.one(data, "csrf")
        if not hmac.compare_digest(csrf, self.csrf(token)):
            raise AccessDenied("This form expired. Reload the page and try again")
        fields = {
            "/login": {"profile"}, "/logout": set(),
            "/memory/save": {"text"}, "/memory/revise": {"id", "text", "revision"},
            "/memory/forget": {"id"}, "/circle/add": {"member", "role"}, "/circle/remove": {"member"},
            "/sharing/revoke": {"id"}, "/request/draft": {"recipient", "message", "memory", "key"},
            "/request/approve": {"id", "expires"}, "/request/transition": {"id", "state"},
            "/request/followup": {"id", "hours", "alternative"},
        }
        if path not in fields:
            return self.error(404, "Action not found", token)
        if set(data) - fields[path] - {"csrf"}:
            raise ValueError("Unexpected form field")
        value = lambda key: self.one(data, key)
        if path == "/login":
            actor = value("profile")
            if actor not in views.PEOPLE:
                raise AccessDenied("Profile unavailable")
            if token:
                self.sessions.revoke(token)
            new_token = self.sessions.issue(actor)
            result = self.redirect("/")
            result.headers["Set-Cookie"] = self.cookie(new_token)
            return result
        self.actor(token)
        if path == "/logout":
            self.app.logout(token)
            result = self.redirect("/")
            result.headers["Set-Cookie"] = self.cookie("")
            return result
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
            if value("member") not in views.PEOPLE:
                raise ValueError("Choose one of the listed people")
            self.app.add_member(token, member=value("member"), role=value("role"))
            return self.redirect("/circle")
        if path == "/circle/remove":
            self.app.remove_member(token, member=value("member"))
            return self.redirect("/circle")
        if path == "/sharing/revoke":
            self.app.revoke(token, value("id"))
            return self.redirect("/sharing")
        if path == "/request/draft":
            request_id = self.app.create_request(token, recipient=value("recipient"), purpose="support visit",
                message=value("message"), idempotency_key=value("key"), memory_ids=tuple(data.get("memory", [])))
            return self.redirect("/request/preview?" + urlencode({"id": request_id}))
        if path == "/request/approve":
            expiry = datetime.fromisoformat(value("expires"))
            # The preview offers seven days; a forged form cannot extend it.
            if not self.app.clock() < expiry <= self.app.clock() + timedelta(days=7):
                raise ValueError("Choose an expiry within the next seven days")
            self.app.approve_request(token, value("id"), expires_at=expiry)
            return self.redirect("/requests")
        if path == "/request/transition":
            state = RequestState(value("state"))
            if state not in (RequestState.ACCEPTED, RequestState.COMPLETED, RequestState.CANCELLED):
                raise ValueError("Unsupported action")
            self.app.transition(token, value("id"), state=state)
            return self.redirect("/requests" if state == RequestState.CANCELLED else "/inbox")
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
        body = f'<p role="alert">{views.e(message)}</p><p><a href="/">Return to overview</a></p>'
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
