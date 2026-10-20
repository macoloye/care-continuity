# Local text interface

The web application makes the service workflows usable through ordinary forms. It has no JavaScript dependency and keeps all records in memory unless you pass `--db`.

```sh
python -m pip install -e .
care-continuity-web
```

Open **http://127.0.0.1:8765**. Use that exact host, rather than `localhost`. Set another port with `care-continuity-web --port 8766`. Keep records between runs with `care-continuity-web --db care.db`. Without installation, run `PYTHONPATH=src python3 -m care_continuity.web` from the repository directory.

The server binds only to loopback. Stopping it clears records and sessions held in memory. The profile chooser is intentionally available to anyone who can reach this local process; it is not an identity-verification flow. Do not expose it through a tunnel or public hosting.

## Try the full loop

1. Choose **Mei**. Open **My memories** to inspect the two starter preferences. Save a new preference or expand a record to correct it and inspect previous versions.
2. Open **My requests**. Choose Lina, write a short request, and select the preferences to include. **Review my request** saves a private draft.
3. Review the recipient, exact message, selected memories, purpose, and expiry. **Approve sharing and deliver** grants the displayed permissions and delivers to the local inbox in one transaction. **Not now** leaves the draft unsent.
4. Leave Mei's profile, choose **Lina**, and open **Inbox**. Accept the request, then mark it completed. Delivery, acceptance, and completion are separate states.
5. Return to Mei. **Sharing** lists the grants and lets you revoke them individually. **Care circle** can end all of a person's access and cancel their unfinished requests.

You can also record a follow-up plan, inspect activity history, or download a JSON account export. A due follow-up is displayed when you load the request list. There is no background scheduler or notification delivery.

## Implementation

| File | Responsibility |
| --- | --- |
| `web.py` | Loopback HTTP boundary, profile bootstrap, session cookies, form routing, errors |
| `web_views.py` | HTML rendering and escaping |
| `static/style.css` | Responsive layout, readable controls, keyboard focus styling |
| `application.py` | Session-derived identity, permissions, atomic request approval, account views |

`approve_request` first validates ownership, draft state, current context revisions, and active circle membership. It creates the required grants, queues the request, and delivers locally inside one transaction. Changed context fails before grants are created. Repeated approval returns a conflict rather than duplicating permissions.

All mutations use POST and require a session-bound CSRF token. The transport validates the Host header, rejects foreign origins and cross-site fetch metadata, limits form size, and rejects unexpected identity fields. Some local browser forms omit or redact Origin; those still require the CSRF token. Session cookies are HttpOnly and SameSite=Strict. This HTTP-only loopback server does not set Secure; a future HTTPS adapter must.

HTML escapes record content. Responses disable caching, framing, scripts, and external resources through headers. The server does not log request targets, cookies, or bodies. These controls support local use; Python's development HTTP server and the profile chooser are not a production authentication stack.

## Accessibility checks and limits

Pages use headings, landmarks, labelled fields, native buttons and disclosure controls, an explicit skip link, visible focus outlines, and a layout that wraps on narrow screens. The UI remains functional without JavaScript.

Manual verification covered the draft-to-completion flow in the in-app browser, the narrow layout, and keyboard activation of the skip link. These checks do not establish accessibility conformance. Full keyboard traversal, screen-reader testing, zoom and mobile testing, and sessions with older adults remain required.

The first interface intentionally limits requests to a support visit with a seven-day permission window. Knowledge review, worker observation submissions, verified login, voice, and external delivery are not yet exposed.
