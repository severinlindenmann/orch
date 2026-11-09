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

/// Largest `body.ticket_view` the relay keeps: compact UTF-8 JSON bytes (message.schema.json).
pub const MAX_TICKET_VIEW: usize = 16384;

/// `body.ticket_view` (schema-checked already): at most 16 KB, and every attachment blob is one the sender
/// uploaded, with its size. A blob of someone else answers exactly like a missing one (no existence oracle).
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
