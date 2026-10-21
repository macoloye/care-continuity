"""Escaped, server-rendered views for the web application."""

from html import escape
from datetime import datetime
from urllib.parse import urlencode


PEOPLE = {"mei": "Mei", "lina": "Lina", "worker": "Alex (visiting worker)", "reviewer": "Sam (demo reviewer)"}


def e(value: object) -> str:
    return escape(str(value), quote=True)


def readable_time(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%d %b %Y at %H:%M UTC")


def hidden(name: str, value: object) -> str:
    return f'<input type="hidden" name="{e(name)}" value="{e(value)}">'


def form(action: str, csrf: str, content: str, label: str, *, secondary: bool = False) -> str:
    style = ' class="secondary"' if secondary else ""
    return (f'<form method="post" action="{e(action)}">{hidden("csrf", csrf)}{content}'
            f'<button{style} type="submit">{e(label)}</button></form>')


def page(title: str, body: str, *, actor: str | None, csrf: str, section: str = "") -> str:
    navigation = ""
    if actor:
        links = []
        for path, label in (("/", "Overview"), ("/memories", "My memories"), ("/circle", "Care circle"),
                            ("/sharing", "Sharing"), ("/requests", "My requests"), ("/inbox", "Inbox"),
                            ("/deliveries", "Deliveries"), ("/observations", "Observations"), ("/knowledge", "Knowledge")):
            current = ' aria-current="page"' if path == section else ""
            links.append(f'<a href="{path}"{current}>{label}</a>')
        navigation = '<nav aria-label="Main">' + "".join(links) + '</nav>'
        identity = f'<span>Viewing as <strong>{e(PEOPLE[actor])}</strong></span>' + form("/logout", csrf, "", "Leave profile", secondary=True)
    else:
        identity = '<span>Care circle</span>'
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} · Care Continuity</title><link rel="stylesheet" href="/style.css"></head>
<body><a class="skip" href="#main">Skip to content</a>
<header><a class="brand" href="/">Care Continuity<span>Remember. Choose. Follow through.</span></a><div class="identity">{identity}</div></header>
<div class="layout">{navigation}<main id="main" tabindex="-1"><h1>{e(title)}</h1>{body}</main></div>
<footer><a href="/">Return to overview</a></footer></body></html>'''


def login(csrf: str) -> str:
    body = '<p class="lead">Try everyday support from each person’s point of view.</p><div class="cards">'
    descriptions = {"mei": "Save your preferences, choose what to share, and ask for support.",
                    "lina": "Read an approved request and accept responsibility for a visit.",
                    "worker": "See only the information Mei has chosen to share with you.",
                    "reviewer": "Try independent knowledge review with example content. This is not a verified professional identity."}
    for actor, name in PEOPLE.items():
        body += f'<article><h2>{e(name)}</h2><p>{e(descriptions[actor])}</p>'
        body += form("/login", csrf, hidden("profile", actor), f"Continue as {name}") + '</article>'
    body += '</div>'
    return page("A little continuity goes a long way.", body, actor=None, csrf=csrf)


def observations(submissions: list[dict], subjects: list[str], csrf: str) -> str:
    body = '<p class="lead">What you noticed, offered for the person to review.</p>'
    if subjects:
        body += '<section><h2>Record an observation</h2>' + form("/observation/submit", csrf,
            '<label for="subject">Who is it about?</label><select id="subject" name="subject">' +
            ''.join(f'<option value="{e(subject)}">{e(PEOPLE.get(subject, subject))}</option>' for subject in subjects) +
            '</select><label for="observation-text">What did you notice?</label>'
            '<textarea id="observation-text" name="text" required maxlength="4000" rows="3"></textarea>'
            '<p>The person reviews every observation before it joins their record. It is not shared with anyone else.</p>',
            "Send for review") + '</section>'
    else:
        body += '<p class="empty">You are not in anyone’s care circle, so there is nothing to record here.</p>'
    for item in submissions:
        name = PEOPLE.get(item["subject"], item["subject"])
        accepted = item["status"] == "accepted"
        body += f'<article><p class="memory-text">{e(item["text"])}</p><p class="meta">About {e(name)} · {"Added to the record" if accepted else "Waiting for review"}</p>'
        if not accepted:
            body += form("/observation/withdraw", csrf, hidden("id", item["id"]), "Withdraw it", secondary=True)
        body += '</article>'
    if subjects and not submissions:
        body += '<p class="empty">No observations recorded yet.</p>'
    return body


def options(members: list[dict]) -> str:
    return ''.join(f'<option value="{e(member["member"])}">{e(PEOPLE.get(member["member"], member["member"]))}</option>'
                   for member in members if member["removed_at"] is None)


def memories(account: dict, csrf: str, pending) -> str:
    body = '<p class="lead">Your words, with room to change your mind.</p>'
    if pending:
        body += '<section><h2>Observations to review</h2><p>People in your care circle recorded these. Accepting keeps the contributor visible and adds the observation to your record. Dismissing removes it without sharing it.</p>'
        for observation in pending:
            name = PEOPLE.get(observation.source, observation.source)
            body += f'<article><p class="memory-text">{e(observation.text)}</p><p class="meta">From {e(name)} · {e(readable_time(observation.created_at))}</p>'
            body += form("/observation/accept", csrf, hidden("id", observation.id), "Accept this observation")
            body += form("/observation/dismiss", csrf, hidden("id", observation.id), "Dismiss it", secondary=True) + '</article>'
        body += '</section>'
    body += '<section><h2>Remember something</h2>' + form("/memory/save", csrf,
        '<label for="new-memory">What would you like remembered?</label><textarea id="new-memory" name="text" required maxlength="4000" rows="3"></textarea>'
        '<p>Saving confirms these words as your preference. They stay private until you share them.</p>', "Save my preference") + '</section>'
    for memory in account["memories"]:
        if memory["kind"] == "observation" and not memory["confirmed"]:
            continue  # Pending observations wait in the review section above.
        mid = memory["id"]
        name = PEOPLE.get(memory["source"], memory["source"])
        body += f'<article><p class="memory-text">{e(memory["text"])}</p><p class="meta">{e(memory["kind"].value)} · Source: {e(name)} · Revision {memory["revision"]}</p>'
        body += '<details><summary>Change this preference</summary>' + form("/memory/revise", csrf,
            hidden("id", mid) + hidden("revision", memory["revision"]) +
            f'<label for="edit-{mid}">Updated preference</label><textarea id="edit-{mid}" name="text" required maxlength="4000">{e(memory["text"])}</textarea>', "Save correction") + '</details>'
        body += '<details><summary>Previous versions</summary><ol>'
        body += ''.join(f'<li>{e(item["text"])} <span class="meta">(revision {item["revision"]})</span></li>' for item in memory["history"])
        body += '</ol></details><details><summary>Forget this memory</summary><p>This removes its saved text and history and redacts linked requests. Unfinished linked requests are cancelled.</p>'
        body += form("/memory/forget", csrf, hidden("id", mid), "Forget this memory", secondary=True) + '</details></article>'
    if not account["memories"]:
        body += '<p class="empty">No preferences saved yet.</p>'
    return body


def circle(account: dict, actor: str, csrf: str) -> str:
    body = '<p class="lead">Being in your circle does not give someone access to your memories.</p>'
    active = {m["member"] for m in account["care_circle"] if m["removed_at"] is None}
    for member in account["care_circle"]:
        if member["removed_at"] is None:
            body += f'<article><h2>{e(PEOPLE.get(member["member"], member["member"]))}</h2><p>{e(member["role"])}</p>'
            body += '<details><summary>End their access</summary><p>This revokes all sharing and cancels unfinished requests for this person.</p>'
            body += form("/circle/remove", csrf, hidden("member", member["member"]), "Remove from my circle", secondary=True) + '</details></article>'
    candidates = [p for p in PEOPLE if p != actor and p not in active]
    if candidates:
        body += '<section><h2>Add someone</h2>' + form("/circle/add", csrf,
            '<label for="member">Person</label><select id="member" name="member">' +
            ''.join(f'<option value="{p}">{e(PEOPLE[p])}</option>' for p in candidates) + '</select>'
            '<label for="role">Relationship</label><select id="role" name="role"><option value="supporter">Supporter</option><option value="worker">Care worker</option><option value="coordinator">Coordinator</option></select>', "Add to my circle") + '</section>'
    return body


def sharing(account: dict, csrf: str) -> str:
    body = '<p class="lead">Review each permission, including when it ends.</p>'
    names = {m["id"]: m["text"] for m in account["memories"]}
    labels = {"read": "read", "share": "receive in a handover", "act": "accept and complete"}
    for grant in account["sharing"]:
        if not grant["active"]:
            continue
        resource = names.get(grant["resource_id"], "Support request")
        body += f'<article><h2>{e(PEOPLE.get(grant["recipient"], grant["recipient"]))} may {e(labels[grant["operation"]])}</h2>'
        body += f'<p>{e(resource)}</p><p>Purpose: {e(grant["purpose"])} · Until {e(readable_time(grant["expires_at"]))}</p>'
        body += form("/sharing/revoke", csrf, hidden("id", grant["id"]), "Revoke this permission", secondary=True) + '</article>'
    if not any(g["active"] for g in account["sharing"]):
        body += '<p class="empty">Nothing is shared right now.</p>'
    return body + '<p>To approve a new handover, start in <a href="/requests">My requests</a>. To end all access for someone, use <a href="/circle">Care circle</a>.</p>'


def deliveries(items: list[dict]) -> str:
    descriptions = {
        "pending": ("Waiting to send", "A worker will check sharing permissions again before sending."),
        "sending": ("Sending", "A delivery attempt is in progress. Its outcome is not yet known."),
        "received": ("Provider received it", "Provider receipt does not mean the person has read or accepted the request."),
        "unknown": ("Delivery uncertain", "It may have arrived. Automatic sending has stopped until the provider outcome is checked. Do not create a duplicate request to retry it."),
        "blocked": ("Delivery stopped", "The request or its sharing permissions no longer allow delivery. Review the request and sharing before deciding what to do next."),
        "failed": ("Delivery attempts exhausted", "The provider reported no delivery after three attempts. Automatic sending has stopped."),
    }
    body = '<p class="lead">Track external delivery separately from the person’s response.</p>'
    body += '<p>This page shows saved delivery jobs. Browser approvals currently use the local inbox; no external provider is configured here.</p>'
    body += '<p><a href="/deliveries">Refresh delivery status</a> · <a href="/sharing">Review sharing</a> · <a href="/requests">My requests</a></p>'
    if not items:
        return body + '<p class="empty">No external deliveries. Local inbox requests appear in My requests.</p>'
    for item in items:
        label, explanation = descriptions.get(item["state"], ("Status unavailable", "Review this delivery with the service operator before retrying."))
        body += f'<article><h2>To {e(PEOPLE.get(item["recipient"], item["recipient"]))}</h2>'
        body += f'<p><strong>Delivery: {e(label)}</strong></p><p>{e(explanation)}</p>'
        body += f'<p>Provider: {e(item["provider"])}. Attempts: {e(item["attempts"])}.</p>'
        body += f'<p><strong>Request: {e(item["request_state"])}</strong>.</p>'
        if item["request_state"] in ("draft", "queued", "delivered", "blocked"):
            body += '<p class="notice">No one has accepted this request yet.</p>'
        if item["request_state"] in ("cancelled", "blocked"):
            body += '<p>The request has stopped. This does not recall information already sent or cancel an external send already in progress.</p>'
        body += f'<p><a href="/requests#request-{e(item["request_id"])}">Review this request and follow-up options</a></p></article>'
    return body


def requests(account: dict, csrf: str, draft_key: str) -> str:
    body = '<p class="lead">A sent request is not yet an agreed arrangement.</p>'
    body += '<p><a href="/deliveries">Check external delivery status</a></p>'
    recipients = options(account["care_circle"])
    if recipients:
        content = hidden("key", draft_key) + '<label for="recipient">Who would you like to ask?</label><select id="recipient" name="recipient">' + recipients + '</select>'
        content += '<label for="message">Your message</label><textarea id="message" name="message" required maxlength="4000" rows="3"></textarea>'
        content += '<fieldset><legend>Include preferences (optional)</legend>'
        for memory in account["memories"]:
            content += f'<label class="check"><input type="checkbox" name="memory" value="{e(memory["id"])}">{e(memory["text"])}</label>'
        content += '</fieldset><p>Purpose: support visit. You will review sharing before anything is delivered.</p>'
        body += '<section><h2>Ask for support</h2>' + form("/request/draft", csrf, content, "Review my request") + '</section>'
    else:
        body += '<p><a href="/circle">Add someone to your circle</a> before making a request.</p>'
    for request in account["requests"]:
        body += f'<article id="request-{e(request["id"])}"><span class="status">{e(request["state"])}</span><h2>To {e(PEOPLE.get(request["recipient"], request["recipient"]))}</h2>'
        body += f'<p>{e(request["message"] if request["content_available"] else "The original context changed or was forgotten. Create a fresh request to continue.")}</p>'
        if request["state"] == "draft" and request["content_available"]:
            body += f'<a class="button" href="/request/preview?{urlencode({"id": request["id"]})}">Review sharing</a>'
        if request["needs_followup"]:
            body += f'<p class="notice">No one has accepted yet. Your chosen next step: {e(request["alternative"])}</p>'
        if request.get("resolved_at"):
            body += f'<p class="meta">Follow-up recorded {e(readable_time(request["resolved_at"]))}: {e(request["resolution"])}</p>'
        if request["state"] in ("draft", "queued", "delivered"):
            body += '<details><summary>Plan a follow-up</summary>' + form("/request/followup", csrf,
                hidden("id", request["id"]) + f'<label for="hours-{request["id"]}">Check again in hours</label><input id="hours-{request["id"]}" name="hours" type="number" min="1" max="168" value="24" required>'
                f'<label for="alternative-{request["id"]}">If nobody accepts, what would you like to consider?</label><textarea id="alternative-{request["id"]}" name="alternative" required maxlength="4000">{e(request["alternative"] or "")}</textarea>'
                '<p>This records your plan. It does not send a reminder or contact anyone else.</p>', "Save follow-up plan") + '</details>'
            if request.get("due_at") and not request.get("resolved_at"):
                body += '<details><summary>Record the outcome</summary>' + form("/request/resolve", csrf,
                    hidden("id", request["id"]) +
                    f'<label for="outcome-{request["id"]}">How did you follow up?</label>'
                    f'<textarea id="outcome-{request["id"]}" name="note" required maxlength="4000"></textarea>'
                    '<p>This records your decision. It does not contact anyone.</p>', "Save the outcome") + '</details>'
        if request["state"] not in ("completed", "cancelled"):
            body += form("/request/transition", csrf, hidden("id", request["id"]) + hidden("state", "cancelled"), "Cancel this request", secondary=True)
        body += '</article>'
    return body


def preview(request, csrf: str, expires: str) -> str:
    body = f'<p class="lead">Only approve this if it reflects what you want.</p><section><h2>To {e(PEOPLE.get(request.recipient, request.recipient))}</h2><p class="memory-text">{e(request.message)}</p><h3>Included preferences</h3><ul>'
    body += ''.join(f'<li>{e(memory.text)} <span class="meta">(revision {memory.revision})</span></li>' for memory in request.context) or '<li>No memories included.</li>'
    body += f'</ul><p>Purpose: {e(request.purpose)}. Permission ends at <strong>{e(readable_time(expires))}</strong>.</p>'
    body += '<p>The recipient may read this request, accept it, and mark it complete. They may read the selected preferences and receive them in this handover until permission ends.</p><p>You can revoke access in Sharing. Already seen information cannot be recalled.</p>'
    body += form("/request/approve", csrf, hidden("id", request.id) + hidden("expires", expires), "Approve sharing and deliver")
    return body + '<p><a href="/requests">Not now — return to my requests</a></p></section>'


def inbox(items, csrf: str) -> str:
    body = '<p class="lead">Requests shared with you, with clear responsibility.</p>'
    for item in items:
        body += f'<article><span class="status">{e(item.state.value)}</span><h2>From {e(PEOPLE.get(item.subject, item.subject))}</h2><p class="memory-text">{e(item.message)}</p><ul>'
        body += ''.join(f'<li>{e(memory.text)}</li>' for memory in item.context) + '</ul>'
        next_state = {"delivered": ("accepted", "Accept this request"), "accepted": ("completed", "Mark completed")}.get(item.state.value)
        if next_state:
            body += form("/request/transition", csrf, hidden("id", item.id) + hidden("state", next_state[0]), next_state[1])
        body += '</article>'
    return body if items else body + '<p class="empty">No current requests are shared with you.</p>'


def knowledge_links() -> str:
    return '<p><a href="/knowledge">Knowledge library</a> · <a href="/knowledge/submissions">Submissions</a> · <a href="/knowledge/new">Contribute a card</a></p>'


def knowledge_card(card) -> str:
    body = f'<h2>{e(card.title)}</h2><p class="status">{e(card.kind)}</p><p class="memory-text">{e(card.body)}</p>'
    for label, value in (("Source citation", card.source), ("Contributor", PEOPLE.get(card.contributor, card.contributor)),
                         ("Audience", card.audience), ("Setting", card.setting), ("Language", card.language),
                         ("Limitations", card.limitations), ("First published", card.published_at),
                         ("Review due", card.review_due), ("Reviewer", card.reviewer)):
        body += f'<p><strong>{label}:</strong> {e(value or "Not recorded")}</p>'
    return body


def knowledge_library(cards, query: str) -> str:
    body = knowledge_links() + '<p class="lead">Current experience and procedure cards, with their sources and limits.</p>'
    body += ('<form method="get" action="/knowledge"><label for="q">Search titles and content</label>'
             f'<input id="q" name="q" value="{e(query)}" maxlength="4000"><button type="submit">Search</button></form>')
    body += ''.join('<article>' + knowledge_card(card) + '</article>' for card in cards)
    return body if cards else body + '<p class="empty">No current reviewed cards match this search.</p>'


def knowledge_submissions(cards, actor: str) -> str:
    body = knowledge_links() + '<p>Inspect your contributions and their review history.</p>'
    if actor == "reviewer":
        body += '<p class="notice">Demo reviewer: you can inspect all submissions. Use example content only.</p>'
    for card in cards:
        url = "/knowledge/review?" + urlencode({"id": card.id})
        body += f'<article><h2><a href="{e(url)}">{e(card.title)}</a></h2><p class="status">{e(card.status)}</p><p>Contributor: {e(PEOPLE.get(card.contributor, card.contributor))}</p></article>'
    return body if cards else body + '<p class="empty">No submissions available.</p>'


def knowledge_form(csrf: str) -> str:
    body = knowledge_links() + '<p class="notice">Use example content in this local pilot. Your draft and evidence are visible to you and the configured reviewer. After independent review, the card and its attribution become available to everyone in the library. Evidence stays private.</p>'
    fields = '<label for="kind">Card kind</label><select id="kind" name="kind"><option value="experience">Personal experience</option><option value="procedure">Procedure</option></select>'
    for name, label in (("title", "Title"), ("body", "Card content"), ("source", "Source citation"),
                        ("audience", "Intended audience"), ("setting", "Care setting"), ("language", "Language"),
                        ("limitations", "Limitations"), ("publication_rights", "Evidence of publication rights")):
        fields += f'<label for="{name}">{label}</label>'
        if name in ("body", "limitations", "publication_rights"):
            fields += f'<textarea id="{name}" name="{name}" required maxlength="4000" rows="3"></textarea>'
        else:
            fields += f'<input id="{name}" name="{name}" required maxlength="4000">'
    fields += '<label class="check"><input type="checkbox" name="publication_authorized" value="yes" required>I authorize publication of this card, its source and attribution after independent review.</label>'
    return body + form("/knowledge/submit", csrf, fields, "Submit private draft")


def knowledge_review(card, evidence: dict, actor: str, csrf: str) -> str:
    body = knowledge_links() + f'<p class="status">{e(card.status)}</p><article>' + knowledge_card(card) + '</article>'
    rights = evidence["publication_rights"]
    body += '<section><h2>Private publication evidence</h2>'
    if rights:
        body += f'<p>{e(rights["evidence"])}</p><p>Authorized by {e(rights["actor"])} at {e(rights["authorized_at"])}</p>'
    else:
        body += '<p>Legacy card: submit a new card with complete metadata and publication rights before publication.</p>'
    body += '</section><section><h2>Review history</h2>'
    for review in evidence["reviews"]:
        body += f'<article><p>{e(review["evidence"])}</p><p>Reviewed by {e(review["reviewer"])} at {e(review["reviewed_at"])}</p><p>Review due: {e(review["review_due"])}</p></article>'
    if not evidence["reviews"]:
        body += '<p>No review recorded.</p>'
    body += '</section>'
    if card.status != "withdrawn" and rights and card.kind != "guidance" and actor == "reviewer" and actor != card.contributor:
        body += '<section><h2>Independent publication review</h2><p>Publishing makes the card, source, attribution and review dates available to everyone in the library. Check the exact content above. Review evidence stays private.</p>'
        fields = hidden("id", card.id)
        fields += '<label for="evidence">Source, privacy and scope review evidence</label><textarea id="evidence" name="evidence" required maxlength="4000"></textarea>'
        fields += '<label for="days">Review again in this many days</label><input id="days" name="days" type="number" min="1" max="365" value="30" required>'
        fields += '<label class="check"><input type="checkbox" name="privacy_checked" value="yes" required>I checked privacy and publication rights.</label>'
        fields += '<label class="check"><input type="checkbox" name="scope_checked" value="yes" required>I checked the source, audience, setting and limitations.</label>'
        body += form("/knowledge/publish", csrf, fields, "Record review and publish") + '</section>'
    elif card.kind == "guidance":
        body += '<p class="notice">Professional guidance publication is disabled pending qualified-review support.</p>'
    if card.status != "withdrawn":
        body += '<section><h2>Withdraw this card</h2><p>Withdrawal removes the card from future library searches. It cannot recall copies already seen. A replacement requires a new submission and review.</p>'
        body += form("/knowledge/withdraw", csrf, hidden("id", card.id), "Withdraw card", secondary=True) + '</section>'
    return body
