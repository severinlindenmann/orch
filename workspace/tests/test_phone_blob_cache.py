"""The blob cache belongs to one relay and workspace; a relay that lost a blob (404) gets it again, and the
same message still carries its ticket page."""

import json

from test_phone_artifacts import artifact
from test_ticket_view import conn, views  # noqa: F401 (fixture)

from orch import net, phone_view


def _ticket(proj, run, new_ticket):
    tid = new_ticket("Shortlist")
    artifact(proj, tid, "shortlist.md")
    assert run("ticket", "summary", tid, "Draft is in shortlist.md")[0] == 0
    return tid


def _strict_messages(conn):  # noqa: F811
    """The relay answers 404 to a message naming a blob it does not hold (as the real relay does)."""
    post = next(fn for m, rx, fn in conn.routes if rx == "/v1/messages")
    seen = []

    def strict(m, q, body):
        view = json.loads(body)["body"].get("ticket_view") or {}
        seen.append(view)
        if any(a["blob_id"] not in conn.blobs for a in view.get("attachments", [])):
            return 404, {"error": "not_found", "message": "Upload the attachment first (POST /v1/blobs)"}
        return post(m, q, body)

    conn.routes.insert(0, ("POST", "/v1/messages", strict))
    return seen


def test_a_cache_from_another_relay_is_not_used(proj, run, new_ticket, conn):  # noqa: F811
    tid = _ticket(proj, run, new_ticket)
    phone_view.view_for(proj, tid)
    cfg = net.load_service(proj, "relay")
    other = dict(
        cfg, url=cfg["url"].replace("127.0.0.1", "localhost")
    )  # "relay B": same fake, another address
    net.write_json(net.secrets_dir(proj) / "relay.json", other, True)
    conn.blobs.clear()  # relay B holds nothing
    again = phone_view.view_for(proj, tid)["attachments"][0]["blob_id"]
    assert list(conn.blobs) == [again], "uploaded again to the new relay"
    assert phone_view.blob_scope(proj).startswith(other["url"])


def test_connect_drops_the_blobs_of_another_relay(proj, run, new_ticket, conn):  # noqa: F811
    tid = _ticket(proj, run, new_ticket)
    phone_view.view_for(proj, tid)
    assert phone_view.load_state(proj)["blobs"]
    phone_view.update_state(proj, lambda st: st["blobs"].update({"http://old|ws_x|abc": {"blob_id": "b_1"}}))
    cfg = net.load_service(proj, "relay")
    assert (
        run("relay", "connect", cfg["url"], "--workspace", cfg["workspace"], "--token", cfg["token"])[0] == 0
    )
    keys = list(phone_view.load_state(proj)["blobs"])
    assert keys and all(k.startswith(phone_view.blob_scope(proj)) for k in keys)


def test_a_404_for_a_blob_uploads_again_and_the_view_is_delivered(proj, run, new_ticket, conn):  # noqa: F811
    tid = _ticket(proj, run, new_ticket)
    phone_view.view_for(proj, tid)  # cached
    conn.blobs.clear()  # the relay expired it
    seen = _strict_messages(conn)
    code, _, err = run("relay", "send", "phones", "Done", "--ticket", tid, "--update", "result")
    assert code == 0, err
    assert len(conn.blobs) == 1
    assert seen[-1].get("attachments") and "ticket page" not in err
    assert len(seen) == 2, "refused once, then sent again with the view"


def test_a_second_404_falls_back_to_plain_text_with_the_hint(proj, run, new_ticket, conn):  # noqa: F811
    tid = _ticket(proj, run, new_ticket)
    post = next(fn for m, rx, fn in conn.routes if rx == "/v1/messages")

    def always(m, q, body):
        if "ticket_view" in json.loads(body)["body"]:
            return 404, {"error": "not_found", "message": "Upload the attachment first (POST /v1/blobs)"}
        return post(m, q, body)

    conn.routes.insert(0, ("POST", "/v1/messages", always))
    code, _, err = run("relay", "send", "phones", "Done", "--ticket", tid, "--update", "result")
    assert code == 0, err
    assert "without the ticket page" in err


def test_a_404_that_is_not_about_a_blob_does_not_reupload(proj, run, new_ticket, conn):  # noqa: F811
    tid = _ticket(proj, run, new_ticket)
    post = next(fn for m, rx, fn in conn.routes if rx == "/v1/messages")
    seen = []

    def gone(m, q, body):
        seen.append(1)
        if "ticket_view" in json.loads(body)["body"]:
            return 404, {"error": "not_found", "message": "No such device."}
        return post(m, q, body)

    conn.routes.insert(0, ("POST", "/v1/messages", gone))
    code, _, err = run("relay", "send", "phones", "Done", "--ticket", tid, "--update", "result")
    assert code == 0, err
    assert len(seen) == 2 and len(conn.blobs) == 1, "one try with the view, one plain: no second upload"
