"""Source contracts for the paste-first new ticket dialog."""

from .webjs import WEB, all_js


def test_new_ticket_has_one_large_paste_box_and_optional_metadata():
    js = (WEB / "pages" / "newticket.js").read_text()
    assert "'What needs doing?'" in js
    assert "input.rows = 4; input.maxLength = 500000; input.required = true" in js
    assert (
        "Paste or write it here. A short title or a long text with many points: the agent splits it into tasks."
        in js
    )
    assert "el('details', 'new-ticket-options')" in js
    assert "el('summary', '', 'More options')" in js
    assert "t ? ['owner', 'due', 'note', 'done_when'] : ['owner', 'due', 'done_when']" in js
    for removed in ("One point per line", "Something new", "Something broken", "Small job"):
        assert removed not in js


def test_paste_title_and_description_use_existing_create_action():
    js = all_js()
    assert "const fullText = inputs.text.value;" in js
    assert "values.title = ticketTextTitle(" in js
    assert "shortText.length <= 1500" in js
    assert "inputs.text.setCustomValidity(empty ? 'What needs doing?' : '')" in js
    assert "const args = {title:values.title" in js and "act('ticket.new', args)" in js
    assert "long_text:longText" in js
    assert "files:files.map(({name, text, data})" in js


def test_attachments_and_safe_preview():
    js = (WEB / "pages" / "newticket.js").read_text()
    assert "maxLength = 20000" not in js
    assert "button('Attach file', 'new-ticket-attach'" in js
    assert "for (const target of [form])" in js  # drops land on the whole form
    assert "pre.textContent = file.text.slice(0, 200000)" in js
    assert "innerHTML" not in js
    assert "URL.revokeObjectURL" in js
    assert "previewActions.firstChild.textContent = 'Close'" in js
    app = (WEB / "app.js").read_text()
    assert "body.length < 60000 ? {keepalive:true} : {}" in app


def test_edit_and_create_start_semantics_are_preserved():
    js = all_js()
    assert (
        "act('ticket.edit', {ticket:t.id, owner:values.owner, due:values.due, note:values.note, done_when:values.done_when, if_revision:t.revision})"
        in js
    )
    assert "let startAfter = !t" in js
    assert "startAfter = false; form.requestSubmit()" in js  # Create without starting
    assert "const planFirst = startAfter && !!planBox?.checked" in js  # Show me the plan first
    assert "startAfter = true;" in js
    assert "act('run.start', {ticket:created.id})" in js
    assert "t.title === values.title && !previous.has(t.id)" in js
    assert "creationUnresolved = true" in js
    assert "submit.disabled = creationUnresolved" in js
    assert "The ticket was created, but the helper did not start: " in js
    assert "The ticket was created, but could not be found in the reply." in js


def test_paste_styles_are_scoped_to_new_ticket():
    css = (WEB / "pages" / "newticket.css").read_text()
    assert ".new-ticket .new-ticket-text" in css
    for rule in (
        "width: 100%",
        "min-height: 6.5em",
        "resize: vertical",
        "font-size: 16px",
        "min-height: 44px",
    ):
        assert rule in css
