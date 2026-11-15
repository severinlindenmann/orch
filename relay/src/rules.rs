//! Checks every workspace message must pass (contracts/relay-api.md "Rules the relay checks").
use crate::crypto::Key;
use crate::error::*;
use crate::store::{self, get_msg, open_payload};
use crate::util::valid_id;
use rusqlite::{Connection, OptionalExtension};
use serde_json::Value;
use std::sync::OnceLock;

static SCHEMA: OnceLock<jsonschema::JSONSchema> = OnceLock::new();

fn schema() -> &'static jsonschema::JSONSchema {
    SCHEMA.get_or_init(|| {
        let s: Value = serde_json::from_str(include_str!("../../contracts/message.schema.json"))
            .expect("message schema");
        jsonschema::JSONSchema::options()
            .should_validate_formats(true)
            .compile(&s)
            .expect("compile message schema")
    })
}

/// The ticket's display key when it follows the contract pattern `^[A-Z0-9]{2,4}-[1-9][0-9]{0,8}$`
/// (message.schema.json `key`, e.g. DM1-12); anything else is no key.
pub fn ticket_key(v: &Value) -> Option<&str> {
    let k = v.as_str()?;
    let (code, n) = k.split_once('-')?;
    let code_ok = (2..=4).contains(&code.len())
        && code
            .bytes()
            .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit());
    let n_ok =
        (1..=9).contains(&n.len()) && n.bytes().all(|b| b.is_ascii_digit()) && !n.starts_with('0');
    (code_ok && n_ok).then_some(k)
}

/// A `key` that is not a valid display key is dropped (never stored, listed or pushed); the message itself is kept.
pub fn clean_ticket_key(msg: &mut Value) {
    if msg["body"].get("proposal_result").is_some() {
        return;
    }
    if msg.get("key").is_some() && ticket_key(&msg["key"]).is_none() {
        if let Some(o) = msg.as_object_mut() {
            o.remove("key");
        }
    }
}

/// Err(text of the first problems) when `msg` is not a valid orch.msg/1.
pub fn validate_schema(msg: &Value) -> Result<(), String> {
    match schema().validate(msg) {
        Ok(()) => Ok(()),
        Err(errs) => Err(errs
            .take(3)
            .map(|e| format!("{} ({})", e, e.instance_path))
            .collect::<Vec<_>>()
            .join("; ")),
    }
}

/// `body.update.title` follows the description character rule (relay-api.md): NFC, allowed characters, at most 2 stacked
/// marks. The schema checks most of it; NFC and the exact character rule are checked here.
pub fn check_update_title(msg: &Value) -> Result<(), String> {
    let Some(t) = msg["body"]["update"]["title"].as_str() else {
        return Ok(());
    };
    let n = store::valid_description(t).map_err(|e| format!("update.title: {e}"))?;
    if n != t.trim() || t.chars().any(|c| c == '\n' || c == '\r') {
        return Err("update.title must be one line of plain text in NFC form.".into());
    }
    Ok(())
}

/// The one answer for "unknown workspace" and "not connected".
pub const NO_REACHABLE: &str = "No reachable workspace with this id. Ask the admin.";

/// Pair rule index: text 0, files 1, delegate 2, start 3.
fn kind_of(typ: &str) -> Option<(usize, &'static str)> {
    match typ {
        "text" | "question" => Some((0, "text")),
        "file" => Some((1, "files")),
        "delegate" => Some((2, "delegate")),
        "start" => Some((3, "start")),
        _ => None,
    }
}

/// Apply the rules for a message from workspace `sender`. Returns the message to store
/// (answers get `ticket` and `question_id` copied from the question).
pub fn authorize(c: &Connection, key: &Key, sender: &str, mut msg: Value) -> Res<Value> {
    let typ = msg["type"].as_str().unwrap_or("").to_string();
    let to = msg["to"].as_str().unwrap_or("").to_string();
    // The marker is checked wherever it appears, not only on a text (the schema refuses other types too).
    // The caller holds the one database lock from the duplicate check to the insert, so the one-result
    // rule below cannot race another result.
    if msg["body"].get("proposal_result").is_some() {
        if typ != "text" {
            return Err(invalid("Invalid proposal result."));
        }
        check_proposal_result(c, key, sender, &msg)?;
    }
    if msg["body"].get("review_result").is_some() {
        if typ != "text" {
            return Err(invalid("Invalid review result."));
        }
        check_review_result(c, key, sender, &msg)?;
    }
    if msg["body"].get("taken_back").is_some() {
        if typ != "text" {
            return Err(invalid("Invalid taken-back text."));
        }
        check_taken_back(c, key, sender, &msg)?;
    }
    if let Some((idx, label)) = kind_of(&typ) {
        if to == "phones" || valid_id(&to, "ph_", 10) {
            if idx != 0 {
                return Err(not_allowed("Only text and questions can go to a phone."));
            }
            // A phone is reachable when the admin paired it with the sender (relay admin > Phones).
            if to != "phones" && !store::phone_reaches(c, &to, sender) {
                let from_name = store::ws_name(c, sender).unwrap_or_default();
                return Err(not_allowed(format!(
                    "That phone is not paired with {from_name}. In the relay admin, open Phones and tick {from_name} for this phone (or add the phone there), then run `orch relay refresh`."
                )));
            }
        } else if valid_id(&to, "ws_", 10) {
            // Unknown id and "not connected" answer the same, so a workspace this one has no
            // rule with is never revealed (existence or name).
            let connected = store::rule_flags(c, sender, &to).is_some()
                || store::rule_flags(c, &to, sender).is_some();
            let to_name = store::ws_name(c, &to).filter(|_| connected);
            let Some(to_name) = to_name else {
                return Err(not_found(NO_REACHABLE));
            };
            let ok = store::rule_flags(c, sender, &to).is_some_and(|f| f[idx]);
            if !ok {
                let from_name = store::ws_name(c, sender).unwrap_or_default();
                return Err(not_allowed(format!(
                    "{from_name} may not send {label} to {to_name}."
                )));
            }
        } else {
            return Err(not_allowed(
                "Send to a workspace (ws_…), a paired phone (ph_…) or `phones` (every phone paired with you).",
            ));
        }
        if typ == "file" {
            check_blob(c, sender, &msg)?;
        }
        if typ == "text" {
            check_ticket_view(c, sender, &msg)?;
        }
        if typ == "question" {
            check_review_question(&msg)?;
            check_proposal_question(&msg)?;
            check_card_question(c, sender, &msg)?;
        }
        return Ok(msg);
    }
    match typ.as_str() {
        "answer" => {
            let q = reply_target(c, &msg)?;
            // Questions to phones are answered by phones only (POST /v1/phone/answer).
            if q.typ != "question" || q.from != to || q.to != sender {
                return Err(not_allowed("That is not a question for you to answer."));
            }
            let prev = c
                .query_row(
                    "SELECT 1 FROM messages WHERE reply_to=?1 AND type='answer'",
                    [&q.id],
                    |_| Ok(()),
                )
                .optional()?;
            if prev.is_some() {
                return Err(already_answered("This question was already answered."));
            }
            let (qbody, qextra) = open_payload(key, &q);
            msg["ticket"] = q.ticket.clone().map(Value::from).unwrap_or(Value::Null);
            // the asker's display key travels with its ticket id; never trusted from the answerer
            match qextra.get("key").and_then(ticket_key) {
                Some(k) => msg["key"] = k.into(),
                None => {
                    if let Some(o) = msg.as_object_mut() {
                        o.remove("key");
                    }
                }
            }
            if let Some(qid) = qbody.get("question_id") {
                msg["body"]["question_id"] = qid.clone();
            }
            // Set by the relay, not trusted from the sender.
            let who: String = store::ws_name(c, sender)
                .unwrap_or_default()
                .chars()
                .take(58)
                .collect();
            msg["body"]["answered_by"] = format!("agent:{who}").into();
            Ok(msg)
        }
        "allow" => {
            let q = reply_target(c, &msg)?;
            let kind = msg["body"]["kind"].as_str().unwrap_or("");
            if q.from != to || q.to != sender || q.typ != kind {
                return Err(not_allowed(
                    "An allow must answer a delegate or start sent to you.",
                ));
            }
            Ok(msg)
        }
        _ => Err(forbidden("Only the relay makes this kind of message.")),
    }
}

/// Validate proposal results before generic routing so malformed routes are always 422.
fn check_proposal_result(c: &Connection, key: &Key, sender: &str, msg: &Value) -> Res<()> {
    let body = &msg["body"];
    let Some(result) = body.get("proposal_result") else {
        return Ok(());
    };
    let kind = result["result"].as_str().unwrap_or("");
    let display = result.get("key").and_then(ticket_key);
    let fields_ok = result.as_object().is_some_and(|o| {
        o.keys()
            .all(|k| matches!(k.as_str(), "result" | "key" | "reason"))
    }) && (result.get("key").is_none() || display.is_some());
    let canonical = match kind {
        "made" if display.is_some() && result.get("reason").is_none() => {
            format!("Ticket made: {}", display.unwrap())
        }
        "refused"
            if result.get("key").is_none()
                && matches!(
                    result["reason"].as_str(),
                    Some("needs_person" | "unavailable")
                ) =>
        {
            "Couldn't make the ticket".into()
        }
        "decided" if result.get("reason").is_none() => display
            .map(|k| format!("Ticket made: {k}"))
            .unwrap_or_else(|| "Already decided".into()),
        _ => return Err(invalid("Invalid proposal result.")),
    };
    let to = msg["to"].as_str().unwrap_or("");
    if !fields_ok
        || body["text"].as_str() != Some(canonical.as_str())
        || !body.as_object().is_some_and(|o| o.len() == 2)
        || msg.as_object().is_none_or(|o| {
            o.keys().any(|k| {
                !matches!(
                    k.as_str(),
                    "schema" | "id" | "from" | "to" | "type" | "reply_to" | "created_at" | "body"
                )
            })
        })
        || !msg["reply_to"]
            .as_str()
            .is_some_and(|id| valid_id(id, "m_", 16))
        || (kind == "made" && to != "phones")
        || (kind != "made" && !valid_id(to, "ph_", 10))
    {
        return Err(invalid(
            "Invalid proposal result shape, text or destination.",
        ));
    }
    let rid = msg["reply_to"].as_str().unwrap();
    let q = get_msg(c, rid)?
        .filter(|q| q.from == sender)
        .ok_or_else(|| not_found("The message you reply to does not exist."))?;
    if q.typ != "question" || open_payload(key, &q).0["proposal"] != "make_ticket" {
        return Err(not_allowed("That is not your ticket proposal question."));
    }
    if to != "phones" {
        if !store::phone_reaches(c, to, sender) {
            let from_name = store::ws_name(c, sender).unwrap_or_default();
            return Err(not_allowed(format!(
                "That phone is not paired with {from_name}. In the relay admin, open Phones and tick {from_name} for this phone (or add the phone there), then run `orch relay refresh`."
            )));
        }
        let answered = c
            .query_row(
                "SELECT 1 FROM messages WHERE reply_to=?1 AND type='answer' AND from_addr=?2",
                [rid, to],
                |_| Ok(()),
            )
            .optional()?
            .is_some();
        if !answered {
            return Err(not_allowed("That phone did not answer this proposal."));
        }
    }
    if kind != "decided" {
        let mut st = c.prepare(&format!(
            "SELECT {} FROM messages WHERE reply_to=?1 AND type='text' AND from_addr=?2",
            store::MSG_COLS
        ))?;
        for row in st.query_map([rid, sender], store::msg_from_row)? {
            let (body, _) = open_payload(key, &row?);
            if matches!(
                body["proposal_result"]["result"].as_str(),
                Some("made" | "refused")
            ) {
                return Err(conflict(
                    "This proposal already has a made or refused result.",
                ));
            }
        }
    }
    Ok(())
}

/// Largest compact `body.card` (relay-api.md "Review cards on the phone"; review.MAX_CARD_JSON).
pub const MAX_CARD: usize = 65536;
/// Largest sum of `card_files` sizes.
pub const MAX_CARD_FILES: i64 = 20 * 1024 * 1024;
/// Largest compact `verdict` in a phone answer (review.MAX_NOTE_BYTES).
pub const MAX_VERDICT: usize = 8192;

pub fn compact_len(v: &Value) -> usize {
    serde_json::to_vec(v).map_or(usize::MAX, |b| b.len())
}

/// Every preview node of a card preview: itself, compare sides, option previews.
fn preview_nodes<'a>(pv: &'a Value, out: &mut Vec<&'a Value>) {
    if !pv.is_object() {
        return;
    }
    out.push(pv);
    for side in ["before", "after"] {
        preview_nodes(&pv[side], out);
    }
    for o in pv["options"].as_array().into_iter().flatten() {
        preview_nodes(&o["preview"], out);
    }
}

/// `body.card` / `body.card_files` of a question (the schema checked shapes and keys already): card size, option ids
/// that differ, table rows as wide as their columns, file indexes inside `card_files`, and every file blob an upload of
/// the sender with exactly that size and sha256 (404 for another's or an unknown blob, no existence oracle), at most
/// 20 MB together.
fn check_card_question(c: &Connection, sender: &str, msg: &Value) -> Res<()> {
    let b = &msg["body"];
    let card = &b["card"];
    let files: &[Value] = b["card_files"].as_array().map_or(&[], |a| a.as_slice());
    if card.is_null() && files.is_empty() {
        return Ok(());
    }
    let bad = |m: &str| Err(invalid(m));
    if !card.is_null() {
        if compact_len(card) > MAX_CARD {
            return bad("The card is bigger than 64 KB.");
        }
        let mut nodes = vec![];
        preview_nodes(&card["preview"], &mut nodes);
        for n in &nodes {
            let ids: Vec<&str> = n["options"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|o| o["id"].as_str())
                .collect();
            let mut seen = std::collections::HashSet::new();
            if !ids.iter().all(|i| seen.insert(*i)) {
                return bad("Option ids of a card must differ.");
            }
            if n["type"] == "table" {
                let cols = n["cols"].as_array().map_or(0, |a| a.len());
                if n["rows"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .any(|r| r.as_array().map_or(0, |a| a.len()) != cols)
                {
                    return bad("Every table row needs one cell per column.");
                }
            }
            if let Some(i) = n["src"]["file"].as_u64() {
                if i as usize >= files.len() {
                    return bad("A file reference points past card_files.");
                }
            }
        }
    }
    let mut total: i64 = 0;
    for f in files {
        let id = f["blob_id"].as_str().unwrap_or("");
        let row: Option<(i64, String)> = c
            .query_row(
                "SELECT size,sha256 FROM blobs WHERE id=?1 AND uploader=?2",
                [id, sender],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        let Some((size, sha)) = row else {
            return Err(not_found("Upload the card file first (POST /v1/blobs)."));
        };
        if Some(size) != f["size"].as_i64() || Some(sha.as_str()) != f["sha256"].as_str() {
            return bad("A card file's size or sha256 does not match the uploaded file.");
        }
        total = total.saturating_add(size);
    }
    if total > MAX_CARD_FILES {
        return bad("Card files add up to more than 20 MB.");
    }
    Ok(())
}

/// The one text a review result may carry (relay-api.md "Review result"): derived from the result, never free.
fn review_result_text(r: &Value) -> Option<&'static str> {
    Some(match r["result"].as_str()? {
        "applied" => "Got it",
        "changed" => "This changed. Look at it again",
        "decided" => "Already decided",
        "refused" => match r["reason"].as_str()? {
            "needs_person" | "invalid" | "unavailable" => "Couldn't use your answer",
            _ => return None,
        },
        _ => return None,
    })
}

/// A workspace's `body.review_result` text (relay-api.md "Review cards on the phone"): fixed text, body only
/// {text, review_result}, `to` one ph_, `reply_to` a question of this sender with a digest, the question's ticket,
/// `to` is the phone whose answer the relay stored, at most one per question.
fn check_review_result(c: &Connection, key: &Key, sender: &str, msg: &Value) -> Res<()> {
    let body = &msg["body"];
    let to = msg["to"].as_str().unwrap_or("");
    let shape_ok = review_result_text(&body["review_result"])
        .is_some_and(|t| body["text"].as_str() == Some(t))
        && body.as_object().is_some_and(|o| o.len() == 2)
        && msg.as_object().is_some_and(|o| {
            o.keys().all(|k| {
                matches!(
                    k.as_str(),
                    "schema"
                        | "id"
                        | "from"
                        | "to"
                        | "type"
                        | "reply_to"
                        | "created_at"
                        | "body"
                        | "ticket"
                        | "key"
                )
            })
        })
        && valid_id(to, "ph_", 10)
        && msg["reply_to"]
            .as_str()
            .is_some_and(|id| valid_id(id, "m_", 16));
    if !shape_ok {
        return Err(invalid("Invalid review result shape, text or destination."));
    }
    let rid = msg["reply_to"].as_str().unwrap();
    let q = get_msg(c, rid)?
        .filter(|q| q.from == sender && q.typ == "question")
        .ok_or_else(|| not_found("The message you reply to does not exist."))?;
    // Only a question sent to `phones` can be taken back (the sender owns it, so no id is probed here).
    if q.to != "phones" {
        return Err(not_allowed(
            "Only a question sent to the phones can be taken back.",
        ));
    }
    let (qbody, qextra) = open_payload(key, &q);
    if qbody.get("digest").is_none() {
        return Err(not_allowed("That is not one of your review questions."));
    }
    if msg.get("ticket").and_then(Value::as_str) != q.ticket.as_deref() {
        return Err(invalid("The ticket must be the question's ticket."));
    }
    // The display key, when given, is the question's own (a result never relabels the ticket on the phone).
    if let Some(k) = msg.get("key") {
        if Some(k) != qextra.get("key") {
            return Err(invalid("The key must be the question's key."));
        }
    }
    let answered = c
        .query_row(
            "SELECT 1 FROM messages WHERE reply_to=?1 AND type='answer' AND from_addr=?2 AND to_addr=?3",
            [rid, to, sender],
            |_| Ok(()),
        )
        .optional()?
        .is_some();
    if !answered {
        return Err(not_allowed("That phone did not answer this question."));
    }
    let mut st = c.prepare(&format!(
        "SELECT {} FROM messages WHERE reply_to=?1 AND type='text' AND from_addr=?2",
        store::MSG_COLS
    ))?;
    for row in st.query_map([rid, sender], store::msg_from_row)? {
        let (b, _) = open_payload(key, &row?);
        if b.get("review_result").is_some() {
            return Err(conflict("This question already has a result."));
        }
    }
    Ok(())
}

/// Longest `taken_back.reason` (characters).
const MAX_TAKEN_BACK_REASON: usize = 200;

/// A character a one-line reason may not contain: controls (C0, DEL, C1), line/paragraph separators, zero-width and
/// bidi format characters (U+200B-200F, 202A-202E, 2060-2064, 2066-2069, 061C, FEFF).
fn bad_reason_char(ch: char) -> bool {
    ch.is_control()
        || matches!(
            ch,
            '\u{2028}' | '\u{2029}' | '\u{200b}'..='\u{200f}' | '\u{202a}'..='\u{202e}'
                | '\u{2060}'..='\u{2064}' | '\u{2066}'..='\u{2069}' | '\u{061c}' | '\u{feff}'
        )
}

/// A workspace's `body.taken_back` text (relay-api.md "Question taken back"): body only {text, taken_back:{reason}},
/// text exactly `Taken back: <reason>`, `to` exactly `phones`, `reply_to` a plain `q<n>` question of THIS sender (404
/// for any other id, so no id is confirmed), the question's ticket, no phone answer stored yet, at most one per question.
/// The caller holds the one database lock from the duplicate check to the insert, so the one-take-back rule cannot race.
fn check_taken_back(c: &Connection, key: &Key, sender: &str, msg: &Value) -> Res<()> {
    let body = &msg["body"];
    let reason = body["taken_back"]["reason"].as_str().unwrap_or("");
    let n = reason.chars().count();
    let shape_ok = body["taken_back"].as_object().is_some_and(|o| o.len() == 1)
        && (1..=MAX_TAKEN_BACK_REASON).contains(&n)
        && !reason.chars().any(bad_reason_char)
        && !reason.trim().is_empty()
        && body["text"].as_str() == Some(format!("Taken back: {reason}").as_str())
        && body.as_object().is_some_and(|o| o.len() == 2)
        && msg.as_object().is_some_and(|o| {
            o.keys().all(|k| {
                matches!(
                    k.as_str(),
                    "schema"
                        | "id"
                        | "from"
                        | "to"
                        | "type"
                        | "reply_to"
                        | "created_at"
                        | "body"
                        | "ticket"
                        | "key"
                )
            })
        })
        && msg["to"].as_str() == Some("phones")
        && msg["reply_to"]
            .as_str()
            .is_some_and(|id| valid_id(id, "m_", 16));
    if !shape_ok {
        return Err(invalid("Invalid taken-back shape, text or destination."));
    }
    let rid = msg["reply_to"].as_str().unwrap();
    let q = get_msg(c, rid)?
        .filter(|q| q.from == sender && q.typ == "question")
        .ok_or_else(|| not_found("The message you reply to does not exist."))?;
    // Only a question sent to `phones` can be taken back (the sender owns it, so no id is probed here).
    if q.to != "phones" {
        return Err(not_allowed(
            "Only a question sent to the phones can be taken back.",
        ));
    }
    let (qbody, qextra) = open_payload(key, &q);
    let plain = qbody["question_id"].as_str().is_some_and(|id| {
        id.strip_prefix('q')
            .is_some_and(|d| !d.is_empty() && d.bytes().all(|b| b.is_ascii_digit()))
    });
    if !plain || qbody.get("proposal").is_some() || qbody.get("review").is_some() {
        return Err(not_allowed("Only an ordinary question can be taken back."));
    }
    if msg.get("ticket").and_then(Value::as_str) != q.ticket.as_deref() {
        return Err(invalid("The ticket must be the question's ticket."));
    }
    if let Some(k) = msg.get("key") {
        if Some(k) != qextra.get("key") {
            return Err(invalid("The key must be the question's key."));
        }
    }
    let answered = c
        .query_row(
            "SELECT 1 FROM messages WHERE reply_to=?1 AND type='answer'",
            [rid],
            |_| Ok(()),
        )
        .optional()?
        .is_some();
    if answered {
        return Err(already_answered("This question was already answered."));
    }
    // The same message id again is caught before this (a duplicate); another id for the same question is a conflict.
    if store::taken_back_reason(c, key, rid)?.is_some() {
        return Err(conflict("This question was already taken back."));
    }
    Ok(())
}

/// Largest `body.ticket_view` the relay keeps: compact UTF-8 JSON bytes (message.schema.json).
pub const MAX_TICKET_VIEW: usize = 16384;

/// body.review marks the review question (relay-api.md): question_id review-<n>, options exactly
/// accept and changes, no scope. Anything else with the marker is refused, so no other question can
/// show up as a review bar.
fn check_review_question(msg: &Value) -> Res<()> {
    let b = &msg["body"];
    if b.get("review").is_none() {
        return Ok(());
    }
    let qid = b["question_id"].as_str().unwrap_or("");
    let n = qid.strip_prefix("review-").unwrap_or("");
    let ok = b["review"] == true
        && !n.is_empty()
        && n.len() <= 4
        && n.bytes().all(|c| c.is_ascii_digit())
        && b["options"] == serde_json::json!(["accept", "changes"])
        && b.get("scope").is_none();
    if ok {
        Ok(())
    } else {
        Err(invalid(
            "A review question has review true, question_id review-<n>, options accept and changes, and no scope.",
        ))
    }
}

/// body.proposal marks the General helper's ticket proposal (relay-api.md "Ticket proposal question"):
/// proposal make_ticket, question_id proposal-<the message's own id>, title 1-120 chars, options exactly
/// make and not_now, no scope, no review, no ticket on the message.
fn check_proposal_question(msg: &Value) -> Res<()> {
    let b = &msg["body"];
    if b.get("proposal").is_none() {
        // the id prefix belongs to the marker: no other question may look like a proposal card
        return if b["question_id"]
            .as_str()
            .is_some_and(|q| q.starts_with("proposal-"))
        {
            Err(invalid(
                "A question_id starting with proposal- needs body.proposal make_ticket.",
            ))
        } else {
            Ok(())
        };
    }
    let own = msg["id"].as_str().unwrap_or("");
    let title_len = b["title"].as_str().map_or(0, |t| t.chars().count());
    let ok = b["proposal"] == "make_ticket"
        && !own.is_empty()
        && b["question_id"].as_str() == Some(format!("proposal-{own}").as_str())
        && (1..=120).contains(&title_len)
        && b["options"] == serde_json::json!(["make", "not_now"])
        && b.get("scope").is_none()
        && b.get("review").is_none()
        && msg.get("ticket").is_none_or(|t| t.is_null());
    if ok {
        Ok(())
    } else {
        Err(invalid(
            "A ticket proposal has proposal make_ticket, question_id proposal-<its own id>, a title of 1-120 characters, options make and not_now, no scope, no review and no ticket.",
        ))
    }
}

/// `body.ticket_view` (schema-checked already): at most 16 KB, and every attachment blob is one the sender
/// uploaded, with its size. A blob of someone else answers exactly like a missing one (no existence oracle).
fn check_ticket_view(c: &Connection, sender: &str, msg: &Value) -> Res<()> {
    let view = &msg["body"]["ticket_view"];
    if view.is_null() {
        return Ok(());
    }
    if serde_json::to_vec(view).map_or(usize::MAX, |v| v.len()) > MAX_TICKET_VIEW {
        return Err(invalid(
            "ticket_view is bigger than 16 KB. Send fewer lines or attachments.",
        ));
    }
    for a in view["attachments"].as_array().into_iter().flatten() {
        let Some(id) = a["blob_id"].as_str() else {
            continue;
        };
        let size: Option<i64> = c
            .query_row(
                "SELECT size FROM blobs WHERE id=?1 AND uploader=?2",
                [id, sender],
                |r| r.get(0),
            )
            .optional()?;
        match size {
            Some(n) if Some(n) == a["size"].as_i64() => {}
            Some(_) => {
                return Err(invalid(
                    "An attachment's size does not match the uploaded file.",
                ))
            }
            None => return Err(not_found("Upload the attachment first (POST /v1/blobs).")),
        }
    }
    Ok(())
}

fn reply_target(c: &Connection, msg: &Value) -> Res<store::Msg> {
    let rid = msg["reply_to"].as_str().unwrap_or("");
    get_msg(c, rid)?.ok_or_else(|| not_found("The message you reply to does not exist."))
}

fn check_blob(c: &Connection, sender: &str, msg: &Value) -> Res<()> {
    let b = &msg["body"];
    let row: Option<(String, i64, String)> = c
        .query_row(
            "SELECT uploader,size,sha256 FROM blobs WHERE id=?1",
            [b["blob_id"].as_str().unwrap_or("")],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()?;
    match row {
        Some((up, size, sha))
            if up == sender
                && Some(size) == b["size"].as_i64()
                && Some(sha.as_str()) == b["sha256"].as_str() =>
        {
            Ok(())
        }
        Some((up, ..)) if up != sender => Err(not_allowed("You did not upload that file.")),
        Some(_) => Err(invalid("Size or sha256 does not match the uploaded file.")),
        None => Err(not_found("Upload the file first (POST /v1/blobs).")),
    }
}
