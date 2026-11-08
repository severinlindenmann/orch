"""Source contracts for the paste-first new ticket dialog."""
from .webjs import WEB, all_js


def test_new_ticket_has_one_large_paste_box_and_optional_metadata():
    js = (WEB / "pages" / "newticket.js").read_text()
    assert "'What needs doing?'" in js
    assert "input.rows = 10; input.maxLength = 20000; input.required = true" in js
    assert "Paste or write it here. A short title or a long text with many points: the agent splits it into tasks." in js
    assert "el('details', 'new-ticket-options')" in js
    assert "el('summary', '', 'More options')" in js
    assert "t ? ['owner', 'due', 'note', 'done_when'] : ['owner', 'due', 'done_when']" in js
    for removed in ("One point per line", "Something new", "Something broken", "Small job"):
        assert removed not in js


def test_paste_title_and_description_use_existing_create_action():
    js = all_js()
    assert "const fullText = inputs.text.value;" in js
    assert r"fullText.split(/\r?\n/).map(line => line.trim()).find(Boolean).slice(0, 200)" in js
    assert r"values.note = /[\r\n]/.test(fullText) || fullText.trim() !== values.title ? fullText : '';" in js
    assert "inputs.text.setCustomValidity(inputs.text.value.trim() ? '' : 'What needs doing?')" in js
    assert "// m1-api: switch to the paste action when it lands" in js
    assert "act('ticket.new', {title:values.title, ...Object.fromEntries(['owner', 'due', 'note', 'done_when'].filter(k => values[k]).map(k => [k, values[k]]))})" in js


def test_edit_and_create_start_semantics_are_preserved():
    js = all_js()
    assert "act('ticket.edit', {ticket:t.id, owner:values.owner, due:values.due, note:values.note, done_when:values.done_when, if_revision:t.revision})" in js
    assert "let startAfter = !t" in js
    assert "startAfter = false; form.requestSubmit()" in js
    assert "startAfter = true;" in js
    assert "act('run.start', {ticket:created.id})" in js
    assert "t.title === values.title && !previous.has(t.id)" in js
    assert "creationUnresolved = true" in js
    assert "submit.disabled = creationUnresolved" in js
    assert "The ticket was created, but the agent did not start: " in js
    assert "The ticket was created, but could not be found in the reply." in js


def test_paste_styles_are_scoped_to_new_ticket():
    css = (WEB / "pages" / "newticket.css").read_text()
    assert ".new-ticket .new-ticket-text" in css
    for rule in ("width: 100%", "min-height: 200px", "resize: vertical", "font-size: 16px", "min-height: 44px"):
        assert rule in css
