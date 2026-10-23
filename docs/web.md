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

You can also record a follow-up plan and, once you have handled an unanswered request yourself, record the outcome from **My requests**. As a circle member, **Observations** lets you record what you noticed; the person then accepts or dismisses it from **My memories**. You can inspect activity history or download a JSON account export. A due follow-up is displayed when you load the request list. There is no background scheduler or notification delivery.

## Local setup

The chooser page links to **Local setup**, which lists the people on this device and their care-circle relationships. It can add a person (someone receiving support, or a carer) and record, change the role of, or end a relationship. A new profile appears in the chooser immediately, starts with no records, and can see nothing until the person shares with them.

Setup is a privileged local surface, like the profile chooser: it does not verify identity, so it must stay bound to loopback and must not be exposed through a tunnel or public hosting. It is not an administrator role in the domain. A relationship only lets the member record observations for the person to review — it never grants access to memories or requests. Ending a relationship revokes all sharing and cancels unfinished requests, exactly as if the person had removed the member themselves. Setup actions are recorded in the person's activity history attributed to *local setup*.

Two deliberate limits: reviewer authority is configured by the host and cannot be created here, and people cannot be deleted once added, because record deletion needs its own dependency design.

## Implementation

| File | Responsibility |
| --- | --- |
| `web.py` | Loopback HTTP boundary, profile bootstrap, session cookies, form routing, errors |
| `web_views.py` | HTML rendering and escaping |
| `static/style.css` | Responsive layout, readable controls, keyboard focus styling |
| `directory.py` | People directory and relationship setup behind the local console |
| `application.py` | Session-derived identity, permissions, atomic request approval, account views |

`approve_request` first validates ownership, draft state, current context revisions, and active circle membership. It creates the required grants, queues the request, and delivers locally inside one transaction. Changed context fails before grants are created. Repeated approval returns a conflict rather than duplicating permissions.

All mutations use POST and require a session-bound CSRF token. The transport validates the Host header, rejects foreign origins and cross-site fetch metadata, limits form size, and rejects unexpected identity fields. Some local browser forms omit or redact Origin; those still require the CSRF token. Session cookies are HttpOnly and SameSite=Strict. This HTTP-only loopback server does not set Secure; a future HTTPS adapter must.

HTML escapes record content. Responses disable caching, framing, scripts, and external resources through headers. The server does not log request targets, cookies, or bodies. These controls support local use; Python's development HTTP server and the profile chooser are not a production authentication stack.

## Accessibility checks and limits

Pages use headings, landmarks, labelled fields, native buttons and disclosure controls, an explicit skip link, visible focus outlines, and a layout that wraps on narrow screens. The UI remains functional without JavaScript.

Manual verification covered the draft-to-completion flow in the in-app browser, the narrow layout, and keyboard activation of the skip link. These checks do not establish accessibility conformance. Full keyboard traversal, screen-reader testing, zoom and mobile testing, and sessions with older adults remain required.

Requests use the support-visit purpose, with one-hour, one-day or seven-day permission windows shown in the approval preview. Local simulated suggestion review and simulated external delivery approval are available. Verified login, voice and live external delivery remain unavailable. Knowledge contribution and review are available through **Knowledge**, using the [knowledge pilot walkthrough](knowledge.md#browser-workflow). The additional **Sam (demo reviewer)** profile has host-configured editorial authority for local examples only.

The knowledge workflow was checked in the in-app browser with synthetic content: contribution,
keyboard submission, profile switching, independent review, and library retrieval. The narrow
layout was inspected visually. Automated tests additionally cover private draft isolation,
escaping, withdrawal, invalid attestations, self-review, forged identity fields, session
revocation and CSRF rejection. Screen-reader evaluation remains pending.

## Delivery status

**Deliveries** shows external jobs created through the trusted application integration.
It distinguishes provider receipt from the request being accepted, explains uncertain
outcomes, and links to the matching request and sharing controls. Refresh does not retry
or reconcile delivery. The empty state explains that local mailbox requests stay in
**My requests**. Browser approval offers the local mailbox or the configured local delivery simulator; simulator jobs require the host-only runner in `demo.py`. The complete simulator walkthrough and its release verification remain tracked in the [release plan](next-release-plan.md).

A synthetic uncertain delivery was checked in the in-app browser, including narrow layout,
keyboard activation of Deliveries, the skip link and refresh focus, and navigation to the
matching request. Screen-reader and user evaluation remain pending.
