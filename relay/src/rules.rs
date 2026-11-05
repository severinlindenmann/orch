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
            let Some(to_name) = store::ws_name(c, &to) else {
                return Err(not_found("There is no such workspace."));
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
            let (qbody, _) = open_payload(key, &q);
            msg["ticket"] = q.ticket.clone().map(Value::from).unwrap_or(Value::Null);
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
