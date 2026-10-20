"""Escaped, server-rendered views for the web application."""

from html import escape
from datetime import datetime
from urllib.parse import urlencode


PEOPLE = {"mei": "Mei", "lina": "Lina", "worker": "Alex (visiting worker)"}


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
                            ("/sharing", "Sharing"), ("/requests", "My requests"), ("/inbox", "Inbox")):
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
                    "worker": "See only the information Mei has chosen to share with you."}
    for actor, name in PEOPLE.items():
        body += f'<article><h2>{e(name)}</h2><p>{e(descriptions[actor])}</p>'
        body += form("/login", csrf, hidden("profile", actor), f"Continue as {name}") + '</article>'
    body += '</div>'
    return page("A little continuity goes a long way.", body, actor=None, csrf=csrf)


def options(members: list[dict]) -> str:
    return ''.join(f'<option value="{e(member["member"])}">{e(PEOPLE.get(member["member"], member["member"]))}</option>'
                   for member in members if member["removed_at"] is None)


def memories(account: dict, csrf: str) -> str:
    body = '<p class="lead">Your words, with room to change your mind.</p>'
    body += '<section><h2>Remember something</h2>' + form("/memory/save", csrf,
        '<label for="new-memory">What would you like remembered?</label><textarea id="new-memory" name="text" required maxlength="4000" rows="3"></textarea>'
        '<p>Saving confirms these words as your preference. They stay private until you share them.</p>', "Save my preference") + '</section>'
    for memory in account["memories"]:
        mid = memory["id"]
        body += f'<article><p class="memory-text">{e(memory["text"])}</p><p class="meta">Source: {e(memory["source"])} · Revision {memory["revision"]}</p>'
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


def requests(account: dict, csrf: str, draft_key: str) -> str:
    body = '<p class="lead">A sent request is not yet an agreed arrangement.</p>'
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
        body += f'<article><span class="status">{e(request["state"])}</span><h2>To {e(PEOPLE.get(request["recipient"], request["recipient"]))}</h2>'
        body += f'<p>{e(request["message"] if request["content_available"] else "The original context changed or was forgotten. Create a fresh request to continue.")}</p>'
        if request["state"] == "draft" and request["content_available"]:
            body += f'<a class="button" href="/request/preview?{urlencode({"id": request["id"]})}">Review sharing</a>'
        if request["needs_followup"]:
            body += f'<p class="notice">No one has accepted yet. Your chosen next step: {e(request["alternative"])}</p>'
        if request["state"] in ("draft", "queued", "delivered"):
            body += '<details><summary>Plan a follow-up</summary>' + form("/request/followup", csrf,
                hidden("id", request["id"]) + f'<label for="hours-{request["id"]}">Check again in hours</label><input id="hours-{request["id"]}" name="hours" type="number" min="1" max="168" value="24" required>'
                f'<label for="alternative-{request["id"]}">If nobody accepts, what would you like to consider?</label><textarea id="alternative-{request["id"]}" name="alternative" required maxlength="4000">{e(request["alternative"] or "")}</textarea>'
                '<p>This records your plan. It does not send a reminder or contact anyone else.</p>', "Save follow-up plan") + '</details>'
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
