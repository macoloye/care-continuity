"""Local demonstration views using native controls and escaped care text."""

from .web_views import e, form, hidden, readable_time, options


def duration(selected: int = 24) -> str:
    return '<label for="hours">Permission duration</label><select id="hours" name="hours">' + ''.join(
        f'<option value="{hours}"' + (' selected' if hours == selected else '') + f'>{label}</option>'
        for hours, label in ((1, 'One hour'), (24, 'One day'), (168, 'Seven days'))) + '</select>'


def choose(memories: list[dict], csrf: str) -> str:
    body = '<p>A fixed local simulator helps you try reviewing a suggestion. It is not AI and contacts no external service.</p>'
    if not memories:
        return body + '<p><a href="/memories">Save a preference first</a>.</p>'
    fields = '<fieldset><legend>Choose source memories (at least one)</legend>'
    for item in memories:
        fields += f'<label class="check"><input type="checkbox" name="memory" value="{e(item["id"])}">{e(item["text"])}</label>'
    fields += '</fieldset>' + duration()
    return body + form('/suggestion/preview', csrf, fields, 'Review simulator disclosure')


def review(item, context, handle: str, csrf: str, members: list[dict], names: dict[str, str],
           *, message: str | None = None, error: str = '') -> str:
    body = '<p class="notice">Local simulation only. No AI or external network service is used. Reviews expire after 15 minutes or when the app restarts.</p>'
    body += f'<p>Provider: {e(item.provider)}. Purpose: draft-support-request. Permission ends {e(readable_time(item.permission_expires.isoformat()))}.</p>'
    body += '<h2>Exact source context</h2><ul>'
    for memory in context.memories:
        body += f'<li>{e(memory.text)} — {e(memory.kind.value)}; source: {e(names.get(memory.source, memory.source))}; revision {memory.revision}; confirmed: {e(memory.confirmed)}</li>'
    body += '</ul><p>The simulator may read and receive these memories for drafting. You can revoke permission in Sharing.</p>'
    if item.suggestion is None:
        body += form('/suggestion/generate', csrf, hidden('handle', handle), 'Approve disclosure and generate simulation')
    else:
        body += '<h2>Review the simulated suggestion</h2><p>Edit this text to reflect your wishes. Saving creates a private draft; sharing needs separate approval. All sources above stay linked to the draft.</p>'
        if error:
            body += f'<p id="review-error" role="alert">{e(error)}</p>'
        if members:
            fields = hidden('handle', handle) + '<label for="message">Your reviewed message</label>'
            fields += '<textarea id="message" name="message" required maxlength="4000" rows="4"' + (' aria-describedby="review-error" aria-invalid="true"' if error else '') + f'>{e(item.suggestion.message if message is None else message)}</textarea>'
            fields += '<label for="recipient">Who would you like to ask?</label><select id="recipient" name="recipient">' + options(members, names) + '</select><p>Purpose: support visit.</p>'
            body += form('/suggestion/save', csrf, fields, 'Save my reviewed draft')
        else:
            body += '<p><a href="/circle">Add an active supporter</a> before saving a draft.</p>'
    return body + form('/suggestion/discard', csrf, hidden('handle', handle), 'Discard this suggestion', secondary=True)


def attention(requests: list[dict], observations: tuple, deliveries: list[dict], names: dict[str, str]) -> str:
    body = '<p>These are your current records. This page does not monitor emergencies or contact anyone automatically.</p>'
    rows = []
    if observations:
        rows.append(('/memories', f'{len(observations)} observations await your review'))
    for item in deliveries:
        if item['state'] == 'unknown':
            rows.append(('/deliveries', 'Delivery uncertain — check its outcome before retrying'))
    for item in requests:
        recipient = names.get(item['recipient'], item['recipient'])
        if item['needs_followup']:
            text = f'Follow-up is due for your request to {recipient}'
        elif item['state'] in ('queued', 'delivered'):
            text = f'{recipient} has not accepted yet'
        elif item['state'] == 'draft':
            text = f'Draft for {recipient} awaits your sharing decision'
        elif item['state'] == 'accepted':
            text = f'{recipient} accepted; completion is still pending'
        elif item['state'] == 'blocked':
            text = f'Request to {recipient} stopped — review what changed'
        else:
            continue
        rows.append((f'/requests#request-{item["id"]}', text))
    if not rows:
        body += '<p class="empty">Nothing needs your attention right now.</p>'
    else:
        body += '<ul>' + ''.join(f'<li><a href="{e(url)}">{e(text)}</a></li>' for url, text in rows) + '</ul>'
    return body + '<p><a href="/sharing">Review sharing permissions</a> · <a href="/inbox">Check requests shared with you</a></p>'
