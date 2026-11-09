"""Check every contract example (tickets incl. ext.automation, run records, pending input, Needs you rows,
agent adapters and their config entries, messages, workspaces, add-on manifests and views), the publish
crypto vectors, the workspace look (look.json, look/icons, vectors/look-v1.json), and the phone API v3 (every /v1/phone example in review/relay-api.examples.json against
phone-api.schema.json, plus vectors/phone-v3-v1.json), and Chat + group chat (vectors/chat-groups/*.json against message.schema.json,
chat-groups.schema.json and the host rules in cg_rules). Every examples/<kind>/ folder needs at least one valid-* and one invalid-* file.

Run: uv run --with jsonschema --with rfc3339-validator --with cryptography python contracts/validate.py [<kind> ...]
With kinds (activity, secrets, jobs, blocks, inventory, addon-manifest, screen, counts, human, proposal) only those draft-02 checks run.
"""
import base64
import hashlib
import json
import re
import struct
import sys
import tomllib
import types
import unicodedata
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

HERE = Path(__file__).parent
fails = []


_CATS = {}


def _class_body(cat):
    """Python's re has no \\p{..}: expand a Unicode category (L, Zs, ...) to explicit ranges."""
    if not _CATS:
        for cp in range(sys.maxunicode + 1):
            c = unicodedata.category(chr(cp))
            _CATS.setdefault(c, []).append(cp)
            _CATS.setdefault(c[0], []).append(cp)
    out, cps = [], _CATS.get(cat, [])
    i = 0
    while i < len(cps):
        j = i
        while j + 1 < len(cps) and cps[j + 1] == cps[j] + 1:
            j += 1
        a, b = cps[i], cps[j]
        out.append(re.escape(chr(a)) if a == b else f"{re.escape(chr(a))}-{re.escape(chr(b))}")
        i = j + 1
    return "".join(out)


def _expand(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "pattern" and isinstance(v, str) and "\\p{" in v:
                node[k] = re.sub(r"\\p\{(\w+)\}", lambda m: _class_body(m.group(1)), v)
            else:
                _expand(v)
    elif isinstance(node, list):
        for v in node:
            _expand(v)
    return node


def validator(name):
    schema = _expand(json.loads((HERE / f"{name}.schema.json").read_text()))
    return Draft202012Validator(schema, format_checker=FormatChecker())


V = {
    "ticket": validator("ticket"),
    "message": validator("message"),
    "workspaces": validator("workspaces"),
    "addon-manifest": validator("addon-manifest"),
    "addon-view": validator("addon-view"),
    "run": validator("run"),
    "run-pending": validator("run-pending"),
    "needs": validator("needs"),
    "agent-adapter": validator("agent-adapter"),
    "run-event": validator("addons/focus/run-event"),
    "automation-ext": validator("addons/automation/ext"),
    "focus-ext": validator("addons/focus/ext"),
}
# The [workspace] agent + [agents.<name>] part of .orch/config.toml: a $def of agent-adapter.schema.json.
_adapters = json.loads((HERE / "agent-adapter.schema.json").read_text())
V["agent-config"] = Draft202012Validator(
    {"$ref": "#/$defs/user_config", "$defs": _adapters["$defs"]}, format_checker=FormatChecker()
)
# Core schemas never name an add-on or an agent tool (provider agnostic, core works alone). Older core files that
# predate this rule (message, workspaces, addon-manifest's reserved names) are not listed here.
CORE_CLEAN = ["ticket", "run", "run-pending", "needs", "agent-adapter"]
TOOL_NAMES = re.compile(r"scheduler|automation|focus|relay|dashboard|publish|claude|codex", re.I)
# Add-on ext schemas, keyed by ext name. A ticket's ext.<name> is checked with it (as the CLI does for installed add-ons).
EXT = {"automation": V["automation-ext"], "focus": V["focus-ext"]}


SESSION_ARG = re.compile(r"^(\{session\}|--[a-z][a-z0-9-]*=\{session\})$")


def argv_errors(doc):
    """Order rules of agent-adapter.schema.json $defs/argv that JSON Schema cannot express
    (adapters.py checks the same):
    {prompt} is a whole item after a '--' item; {session} is a whole item or --flag={session}."""
    out = []
    for name, a in (doc.get("adapters") or {}).items():
        for mode in ("oneshot", "live"):
            for key, argv in (a.get(mode) or {}).items():
                if not isinstance(argv, list):
                    continue
                for i, item in enumerate(argv):
                    where = f"{name}.{mode}.{key}[{i}]"
                    if "{prompt}" in item and (item != "{prompt}" or "--" not in argv[:i]):
                        out.append(f"{where}: {{prompt}} must be a whole item after '--'")
                    if "{session}" in item and not SESSION_ARG.match(item):
                        out.append(f"{where}: {{session}} must be a whole item or --flag={{session}}")
    return [types.SimpleNamespace(message=m) for m in out]


def errors(kind, doc):
    if kind == "run-event":  # an example file is a list of events (one log)
        if not isinstance(doc, list) or not doc:
            return [types.SimpleNamespace(message="needs a non-empty list of events")]
        return [e for ev in doc for e in V[kind].iter_errors(ev)]
    errs = list(V[kind].iter_errors(doc))
    if kind == "agent-adapter" and not errs:
        errs += argv_errors(doc)
    if kind == "ticket" and isinstance(doc.get("ext"), dict):
        for name, data in doc["ext"].items():
            if name in EXT:
                errs += list(EXT[name].iter_errors(data))
    return errs


def load(f):
    return tomllib.loads(f.read_text()) if f.suffix == ".toml" else json.loads(f.read_text())


def check(kind, doc, want_ok, label):
    errs = errors(kind, doc)
    if bool(errs) == want_ok:
        fails.append(f"{label}: expected {'valid' if want_ok else 'invalid'}, got {errs[0].message if errs else 'valid'}")



# ---------------------------------------------------------------------------------------------------------------------
# Draft 02 (Live + Insights): record, keys, jobs, blocks, inventory, screen, counts, proposals.
# `validate.py <kind> [<kind> ...]` runs only those kinds; no argument = everything (the checks above, then these).
# ---------------------------------------------------------------------------------------------------------------------
import shlex
from datetime import datetime, timedelta

SELECT = sys.argv[1:]


_W_REG = []


def _w(name, defname=None):
    """Validator for one schema (or one of its $defs); refs to other contract schemas resolve by file name."""
    if not _W_REG:
        reg = Registry()
        for f in sorted(HERE.glob("*.schema.json")):
            doc = _expand(json.loads(f.read_text()))
            reg = reg.with_resource(doc.get("$id", f.name), Resource.from_contents(doc))
        _W_REG.append(reg)
    schema = _expand(json.loads((HERE / f"{name}.schema.json").read_text()))
    if defname:
        schema = {"$id": schema["$id"], "$ref": f"#/$defs/{defname}", "$defs": schema["$defs"]}
    return Draft202012Validator(schema, format_checker=FormatChecker(), registry=_W_REG[0])


def _examples(folder, errfn):
    files = sorted((HERE / "examples" / folder).glob("*.*"))
    for f in files:
        errs = errfn(load(f))
        want = f.name.startswith("valid-")
        if bool(errs) == want:
            fails.append(f"examples/{folder}/{f.name}: expected {'valid' if want else 'invalid'}, got {errs[0] if errs else 'valid'}")
    for prefix in ("valid-", "invalid-"):
        if not any(f.name.startswith(prefix) for f in files):
            fails.append(f"examples/{folder}: needs at least one {prefix}* example")


def _msgs(v, doc):
    return [e.message for e in v.iter_errors(doc)]


def _vec(name):
    return json.loads((HERE / "vectors" / name).read_text())


def _expect(label, got, want):
    if got != want:
        fails.append(f"{label}: expected {json.dumps(want, ensure_ascii=False)[:300]}, got {json.dumps(got, ensure_ascii=False)[:300]}")


def _core_clean(*names):
    for name in names:
        hit = TOOL_NAMES.search((HERE / f"{name}.schema.json").read_text())
        if hit:
            fails.append(f"{name}.schema.json names an add-on or agent tool: {hit.group(0)!r}")


# --- activity (activity.md) ------------------------------------------------------------------------------------------
EVENT_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
FILE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
PRECEDENCE = {"hook": 2, "broker": 2, "job": 2, "core": 2, "log": 1}


def act_event_id(tool_call_id, run, seq):
    """The tool's own id when it is a safe id; an unsafe one is hashed (still the same for hook and log); none -> run:seq."""
    if tool_call_id is None:
        return f"{run}:{seq}"
    if EVENT_ID.match(tool_call_id):
        return tool_call_id
    return "x_" + hashlib.sha256(tool_call_id.encode()).hexdigest()[:32]


def act_detail_name(event_id):
    return event_id if FILE_ID.match(event_id) else "x_" + hashlib.sha256(event_id.encode()).hexdigest()[:32]


def act_dedupe(lines):
    """Indices of the lines readers keep: per (run, id, kind, finished) the highest precedence, ties -> first written."""
    best = {}
    for i, ln in enumerate(lines):
        key = (ln["run"], ln["id"], ln["kind"], ln.get("outcome") is not None)
        if key not in best or PRECEDENCE[ln["via"]] > PRECEDENCE[lines[best[key]]["via"]]:
            best[key] = i
    return sorted(best.values())


def _t(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


HOOK_KINDS = ("step", "denial", "helper.start", "helper.end", "usage")


def act_hook_accept(line):
    """What the out-of-process hook entry (orch run event) stores: only hook kinds, always via hook."""
    if line.get("kind") not in HOOK_KINDS:
        return "refused"
    return {**line, "via": "hook"}


def act_retention(case):
    now, keep, cap = _t(case["now"]), case["keep_days"], case["max_mb"]
    runs = [dict(r) for r in case["runs"]]
    out = {"delete_detail": [], "delete_run": []}
    for r in runs:
        if r["ended"] and now - _t(r["ended"]) > timedelta(days=keep):
            if r["detail_mb"]:
                out["delete_detail"].append(r["run"])
            out["delete_run"].append(r["run"])
            r["detail_mb"] = r["file_mb"] = 0
    ended = sorted((r for r in runs if r["ended"] and r["file_mb"]), key=lambda r: r["ended"])
    while sum(r["detail_mb"] + r["file_mb"] for r in runs) > cap:
        with_detail = [r for r in ended if r["detail_mb"]]
        if with_detail:
            with_detail[0]["detail_mb"] = 0
            out["delete_detail"].append(with_detail[0]["run"])
            continue
        left = [r for r in ended if r["file_mb"]]
        if not left:
            break
        left[0]["file_mb"] = 0
        out["delete_run"].append(left[0]["run"])
    out["fold_first"] = list(out["delete_run"])
    return out


def act_write_allowed(case):
    """hider: store | none | test. A store hider counts only from the trusted orch home; the test hider only when the
    tests package passes it in (entry = tests), never on a CLI entry, whatever env is set."""
    if case["hider"] == "store":
        return bool(case["home_trusted"])
    if case["hider"] == "test":
        return case["entry"] == "tests"
    return False


def _one_line(text, n):
    return " ".join(str(text).split())[:n]


def _shell_unwrap(cmd):
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return cmd
    if len(parts) == 3 and Path(parts[0]).name in ("sh", "bash", "zsh") and parts[1] in ("-c", "-lc"):
        return parts[2]
    return cmd


def act_map_stream(lines, ctx):
    """Reference mapping of an item.* JSON stream (one-shot collector) to orch.activity/1 events (activity.md)."""
    run, out, turn, session = ctx["run"], [], 0, None

    def emit(**k):
        ev = {"v": 1, "id": k.pop("id", None), "seq": len(out) + 1, "run": run, "session": session, "agent": "main",
              "parent": None, "at": ctx["at"], "ticket": ctx["ticket"], "harness": ctx["harness"], "via": "log",
              "used": None, "outcome": None, "detail": None, "coverage": "full"}
        ev.update(k)
        if ev["id"] is None:
            ev["id"] = f"{run}:{ev['seq']}"
        out.append(ev)

    for raw in lines:
        m = json.loads(raw)
        t, item = m.get("type"), m.get("item") or {}
        if t == "thread.started":
            session = m.get("thread_id")
        elif t == "turn.started":
            turn += 1
            emit(kind="run.state", text="Working", data={"state": "working"})
        elif t in ("item.started", "item.completed") and item.get("type") == "command_execution":
            eid = f"{run}:{turn}:{item['id']}"
            used = {"kind": "tool", "name": "Run command", "action": None, "source": "builtin", "version": None}
            text = _one_line(_shell_unwrap(item.get("command", "")), 200)
            if t == "item.started":
                emit(id=eid, kind="step", text=text, used=used)
            else:
                code = item.get("exit_code")
                ok = None if code is None else code == 0
                first = (item.get("aggregated_output") or "").strip().splitlines()[:1]
                err = None if ok is not False else _one_line(f"Exit code {code}: {first[0] if first else ''}".strip(), 300)
                emit(id=eid, kind="step", text=text, used=used, outcome={"ok": ok, "error": err, "ms": None},
                     detail=f"detail/{run}/{act_detail_name(eid)}.json")
        elif t == "item.completed" and item.get("type") == "agent_message":
            eid = f"{run}:{turn}:{item['id']}"
            say = _one_line(item.get("text", ""), 200)
            emit(id=eid, kind="run.state", text=say, data={"state": "working", "say": say},
                 detail=f"detail/{run}/{act_detail_name(eid)}.json")
        elif t == "turn.completed":
            u = m.get("usage") or {}
            emit(kind="usage", text=f"Tokens: {u.get('input_tokens', 0)} in, {u.get('output_tokens', 0)} out",
                 data={"tokens_in": u.get("input_tokens", 0), "tokens_out": u.get("output_tokens", 0)})
            emit(kind="run.state", text="Idle", data={"state": "idle"})
    return out


def kind_activity():
    v = _w("activity")
    vd = _w("activity", "detail_file")
    _examples("activity", lambda d: _msgs(v, d))
    _examples("activity-detail", lambda d: _msgs(vd, d))
    _core_clean("activity")
    vec = _vec("activity-v1.json")
    for c in vec["ids"]:
        _expect(f"activity ids {c['name']}", act_event_id(c["tool_call_id"], c["run"], c["seq"]), c["id"])
    for c in vec["detail_names"]:
        _expect(f"activity detail_names {c['id']}", act_detail_name(c["id"]), c["file"])
    for c in vec["dedupe"]:
        _expect(f"activity dedupe {c['name']}", act_dedupe(c["lines"]), c["keep"])
    for c in vec["hook_entry"]:
        _expect(f"activity hook_entry {c['name']}", act_hook_accept(c["line"]), c["stored"])
    for c in vec["retention"]:
        _expect(f"activity retention {c['name']}", act_retention(c), c["expect"])
    for c in vec["fail_closed"]:
        _expect(f"activity fail_closed {c['name']}", act_write_allowed(c), c["write"])
    for c in vec["stream_mapping"]:
        got = act_map_stream(c["lines"], c["ctx"])
        for ev in got:
            for e in v.iter_errors(ev):
                fails.append(f"activity stream_mapping {c['capture']} seq {ev['seq']}: {e.message}")
        _expect(f"activity stream_mapping {c['capture']}", got, c["events"])



# --- secrets (secrets.md) --------------------------------------------------------------------------------------------
SEC_MIN_LEN = 8  # values (and derived forms) shorter than this are never hidden by exact value (secrets.md, Hiding)


def sec_b64_forms(v):
    """base64 and base64url of the value at the 3 byte alignments (0, 1, 2 bytes before it), without padding and with
    the boundary characters that depend on neighbouring bytes trimmed: matches the value anywhere inside a longer
    encoded string (e.g. Basic base64("user:token"))."""
    b, out = v.encode(), []
    for k in range(3):
        enc = base64.b64encode(b"\0" * k + b).decode().rstrip("=")
        first, last = -(-8 * k // 6), (8 * (k + len(b))) // 6  # chars fully inside the value's bits
        part = enc[first:last]
        out += [part, part.translate(str.maketrans("+/", "-_"))]
    return out


def sec_forms(v):
    """Every required form of one value (applied once; the only nested form is url-quoted base64)."""
    from urllib.parse import quote

    hx = v.encode().hex()
    b64 = sec_b64_forms(v)
    cands = [v, json.dumps(v, ensure_ascii=False)[1:-1], quote(v, safe=""), hx, hx.upper()] + b64
    cands += [quote(f, safe="") for f in b64]
    return [c for c in dict.fromkeys(cands) if len(c) >= SEC_MIN_LEN]


def sec_needles(keys):
    """[(needle, name)] for a list of {name, type, value} (value of a json key = the object), longest first."""
    out = []

    def leaves(o):
        if isinstance(o, str):
            yield o
        elif isinstance(o, dict):
            for x in o.values():
                yield from leaves(x)
        elif isinstance(o, list):
            for x in o:
                yield from leaves(x)

    def add(v, name):
        if len(v) < SEC_MIN_LEN:
            return
        out.extend((f, name) for f in sec_forms(v))
        if "\n" in v:
            out.extend((ln, name) for ln in v.splitlines() if len(ln) >= 16)

    for k in keys:
        v, name = k["value"], k["name"]
        if k["type"] == "json":
            out.append((json.dumps(v, separators=(",", ":"), ensure_ascii=False), name))
            for leaf in leaves(v):
                add(leaf, name)
        else:
            add(v, name)
    seen, uniq = set(), []
    for n, name in sorted(out, key=lambda x: (-len(x[0]), x[0])):
        if n and n not in seen:
            seen.add(n)
            uniq.append((n, name))
    return uniq


def _hide_upto(buf, needles, stop):
    """Hide matches that START before index stop; returns (output, index where unprocessed text begins)."""
    out, i = [], 0
    while i < stop:
        for n, name in needles:
            if buf.startswith(n, i):
                out.append(f"[hidden: {name}]")
                i += len(n)
                break
        else:
            out.append(buf[i])
            i += 1
    return "".join(out), i


def sec_hide(text, needles):
    return _hide_upto(text, needles, len(text))[0]


def sec_hide_stream(chunks, needles):
    longest = max((len(n) for n, _ in needles), default=1)
    buf, out = "", []
    for c in chunks:
        buf += c
        done, i = _hide_upto(buf, needles, max(0, len(buf) - (longest - 1)))
        out.append(done)
        buf = buf[i:]
    out.append(sec_hide(buf, needles))
    return out


def sec_get(case):
    if not case["key_in_profile"]:
        return "not_in_profile"
    if not case["allow_get"]:
        return "get_off"
    if case["stdout_tty"]:
        return "get_to_terminal"
    return "ok"


def sec_resolve(entries):
    """Which entry is used per name ('workspace' wins) and which are shadowed."""
    used, shadowed = {}, []
    for e in entries:
        if e["name"] not in used or e["source"] == "workspace":
            if e["name"] in used:
                shadowed.append(e["name"])
            used[e["name"]] = e["source"]
        else:
            shadowed.append(e["name"])
    return {"used": dict(sorted(used.items())), "shadowed": sorted(set(shadowed))}


def kind_secrets():
    vp, vk, vl = _w("secrets", "profiles"), _w("secrets", "keys_file"), _w("secrets", "list_answer")
    _examples("secret-profiles", lambda d: _msgs(vp, d))
    _examples("secret-keys", lambda d: _msgs(vk, d))
    _examples("secret-list", lambda d: _msgs(vl, d))
    for f in sorted((HERE / "examples" / "secret-profiles").glob("valid-*")):
        if re.search(r"(?i)(dapi|ghp_|sk_live|-----BEGIN)", f.read_text()):
            fails.append(f"examples/secret-profiles/{f.name}: a profile must hold names only")
    vec = _vec("secrets-v1.json")
    for c in vec["hide"]:
        needles = sec_needles(c["keys"])
        whole = sec_hide("".join(c["chunks"]), needles)
        _expect(f"secrets hide {c['name']} (whole)", whole, c["expect"])
        streamed = sec_hide_stream(c["chunks"], needles)
        _expect(f"secrets hide {c['name']} (streamed)", "".join(streamed), c["expect"])
        for n, _ in needles:
            if n in c["expect"]:
                fails.append(f"secrets hide {c['name']}: a hidden form survives in expect: {n[:12]}...")
    for c in vec["min_len"]:
        _expect(f"secrets min_len {c['value']!r}", bool(sec_needles([{"name": "k", "type": "token", "value": c["value"]}])), c["hidden"])
    for c in vec["get"]:
        _expect(f"secrets get {c['name']}", sec_get(c), c["result"])
    for c in vec["resolve"]:
        _expect(f"secrets resolve {c['name']}", sec_resolve(c["entries"]), c["expect"])
    for c in vec["too_short"]:
        ok = not _msgs(vk, {"schema": "orch.keys/1", "keys": {"k": {"type": "token", "source": "workspace", "value": c["value"], "added_at": "2026-11-16T09:00:00Z"}}})
        _expect(f"secrets too_short {c['value']!r}", ok, c["stored"])



# --- blocks (blocks.md) ----------------------------------------------------------------------------------------------
BLOCK_TYPES = ["summary", "steps", "progress", "stat", "kv", "table", "file", "link", "log", "chart"]


def _strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for k, x in o.items():
            yield from _strings(k)
            yield from _strings(x)
    elif isinstance(o, list):
        for x in o:
            yield from _strings(x)


def blocks_errors(v, doc):
    errs = _msgs(v, doc)
    if not errs and len(json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode()) > 65536:
        errs.append("document over 64 KB")
    return errs


def kind_blocks():
    v = _w("blocks")
    _core_clean("blocks")
    files = sorted((HERE / "vectors" / "blocks").glob("*.json"))
    seen = set()
    for f in files:
        case = json.loads(f.read_text())
        label = f"vectors/blocks/{f.name}"
        want = f.name.startswith("valid-")
        if case.get("valid") is not want:
            fails.append(f"{label}: valid must be {want} for a {'valid' if want else 'invalid'}-* file")
        errs = blocks_errors(v, case["doc"])
        if bool(errs) == want:
            fails.append(f"{label}: expected {'valid' if want else 'invalid'}, got {errs[0] if errs else 'valid'}")
        if want:
            texts = set(_strings(case["doc"]))
            lines = texts | {ln for t in texts for ln in t.split("\n")}
            for s in case["shows"]:
                if s not in lines:
                    fails.append(f"{label}: shows {s!r} is not a whole text (or line) of the document")
            if not case["shows"]:
                fails.append(f"{label}: a valid fixture must list what it shows")
            unknown = sum(1 for b in case["doc"]["blocks"] if b.get("type") not in BLOCK_TYPES)
            _expect(f"{label} fallback", unknown, case["fallback"])
            seen.update(b.get("type") for b in case["doc"]["blocks"])
    missing = [t for t in BLOCK_TYPES if t not in seen]
    if missing:
        fails.append(f"vectors/blocks: no valid fixture uses {missing}")
    for prefix in ("valid-", "invalid-"):
        if not any(f.name.startswith(prefix) for f in files):
            fails.append(f"vectors/blocks: needs at least one {prefix}* fixture")



# --- jobs (job-events.md) --------------------------------------------------------------------------------------------
JOB_FINAL = ("ok", "failed", "cancelled", "lost")
JOB_EVENT_CAP = 2000
PROGRESS_RE = (re.compile(r"^\s*(\d+)\s*/\s*(\d+)\b"), re.compile(r"^\s*(\d{1,3}(?:\.\d+)?)\s*%"))


def job_replay(events, binding, cap=JOB_EVENT_CAP):
    """Apply input events of one job in order: [result per event], final state. result = 'ok' or a refusal code."""
    state, steps, results, stored = None, {}, [], 0
    for ev in events:
        t = ev["type"]
        if ev.get("job", binding["job"]) != binding["job"] or ev.get("run", binding["run"]) != binding["run"]:
            results.append("other_run")
            continue
        if t == "lost":
            if state == "running" and ev.get("by") == "orch":
                state = "lost"
                results.append("ok")
            else:
                results.append("ended" if state in JOB_FINAL else "not_allowed")
            continue
        if ev.get("by") is not None:
            results.append("not_allowed")
            continue
        if state is None and t != "start":
            results.append("not_started")
            continue
        if state in JOB_FINAL:
            results.append("ended")
            continue
        if t == "start" and state is not None:
            results.append("already_started")
            continue
        if stored >= cap:
            results.append("cap")
            continue
        if t == "step":
            prev = steps.get(ev["step"])
            if prev in ("done", "failed", "skipped"):
                results.append("step_finished")
                continue
            steps[ev["step"]] = ev["state"]
        if t == "progress" and ev.get("total") is not None and ev["done"] > ev["total"]:
            results.append("invalid")
            continue
        if t == "start":
            state = "running"
        if t == "end":
            state = ev["status"]
        stored += 1
        results.append("ok")
    return results, state


def job_is_lost(c):
    if c["state"] != "running":
        return False
    quiet = _t(c["now"]) - _t(c["last_event_at"]) >= timedelta(minutes=c.get("quiet_minutes", 10))
    return bool(quiet or c.get("process_gone") or c.get("run_ended"))


def job_progress_from_line(line):
    m = PROGRESS_RE[0].match(line)
    if m:
        done, total = int(m.group(1)), int(m.group(2))
        return {"done": done, "total": total} if total > 0 and done <= total else None
    m = PROGRESS_RE[1].match(line)
    if m and float(m.group(1)) <= 100:
        return {"done": float(m.group(1)), "total": 100, "unit": "%"}
    return None


def _job_stream_errors(v, doc):
    if not isinstance(doc, list) or not doc:
        return ["needs a non-empty list of events (one job)"]
    errs = [m for ev in doc for m in _msgs(v, ev)]
    if errs:
        return errs
    res, _ = job_replay(doc, {"job": doc[0]["job"], "run": doc[0]["run"]})
    if [s for s in [ev["seq"] for ev in doc]] != list(range(1, len(doc) + 1)):
        return ["seq must be 1, 2, 3 ... in a stored stream"]
    bad = [r for r in res if r != "ok"]
    return [f"stream breaks the state rules: {bad[0]}"] if bad else []


def kind_jobs():
    v, vi = _w("job-event"), _w("job-event", "input")
    _core_clean("job-event")
    _examples("job-event", lambda d: _job_stream_errors(v, d))
    _examples("job-input", lambda d: _msgs(vi, d))
    vec = _vec("jobs-v1.json")
    for c in vec["replay"]:
        for ev in c["events"]:
            if ev["type"] != "lost" and not ev.get("by"):
                for m in _msgs(vi, ev):
                    fails.append(f"jobs replay {c['name']}: input not valid: {m}")
        res, state = job_replay(c["events"], c["binding"], c.get("cap", JOB_EVENT_CAP))
        _expect(f"jobs replay {c['name']} results", res, c["results"])
        _expect(f"jobs replay {c['name']} state", state, c["state"])
    for c in vec["lost"]:
        _expect(f"jobs lost {c['name']}", job_is_lost(c), c["lost"])
    for c in vec["progress_pattern"]:
        _expect(f"jobs progress_pattern {c['line']!r}", job_progress_from_line(c["line"]), c["progress"])



# --- inventory (inventory.md) ----------------------------------------------------------------------------------------
INV_ORDER = {"skill": ["workspace", "admin", "marketplace", "builtin", "harness"],
             "connection": ["workspace", "admin", "harness"], "key": ["workspace", "admin"]}


def inv_skill_version(files):
    """files: {relative posix path: text}; dot-names are skipped."""
    h = hashlib.sha256()
    for path in sorted((p for p in files if not any(part.startswith(".") for part in p.split("/"))), key=lambda p: p.encode()):
        h.update(path.encode() + b"\0" + hashlib.sha256(files[path].encode()).hexdigest().encode() + b"\n")
    return "sha256:" + h.hexdigest()


def inv_conn_version(server):
    clean = {k: v for k, v in server.items() if k not in ("env", "headers")}
    return "sha256:" + hashlib.sha256(json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def inv_winners(kind, entries):
    order = INV_ORDER[kind]
    best = {}
    for e in entries:
        if e["name"] not in best or order.index(e["source"]) < order.index(best[e["name"]]):
            best[e["name"]] = e["source"]
    return dict(sorted(best.items()))


def inv_classify(c):
    """Source of a skill/connection found on disk; everything unproven is workspace."""
    name, version = c["name"], c["version"]
    if c.get("from_harness_settings"):
        return "harness"
    if [name, version] in c["refresh_items"]:
        return "admin"
    if c["shipped"].get(name) == version:
        return "builtin"
    if c["marketplace_index"].get(name) == version:
        return "marketplace"
    return "workspace"


def inv_allowed(c):
    """Allowed actions of one connection: the .orch/mcp.json entry counts only where it matches the proof-made grant
    (human-proof.md); no entry or no grant = nothing allowed (P1)."""
    entry, grant, actions = c.get("file"), c.get("grant"), c["actions"]
    if entry is None or grant is None:
        return []

    def expand(x):
        return set(actions) if x == "*" else set(x)

    return sorted(expand(entry) & expand(grant) & set(actions))


def inv_settle_allow(c):
    """Allow list over time: a proof sets file and grant; a file edit sets the file and NARROWS the grant to file ∩ grant
    (a list tombstone), never widens it. Effective after each event = file ∩ grant ∩ known actions."""
    actions = set(c["actions"])

    def expand(x):
        return set(actions) if x == "*" else set(x or [])

    file_val, grant, out = None, None, []
    for ev in c["events"]:
        if ev["by"] == "proof":
            file_val = grant = ev["value"]
        else:
            file_val = ev["value"]
            if grant is not None:
                grant = sorted(expand(grant) & expand(file_val))
        out.append(sorted(expand(file_val) & expand(grant) & actions) if grant is not None else [])
    return out


def kind_inventory():
    vi, vm, vp = _w("inventory", "inventory"), _w("inventory", "mcp_file"), _w("inventory", "conn_page")
    _core_clean("inventory")
    _examples("inventory", lambda d: _msgs(vi, d))
    _examples("mcp-file", lambda d: _msgs(vm, d))
    _examples("conn-page", lambda d: _msgs(vp, d))
    vec = _vec("inventory-v1.json")
    for c in vec["skill_version"]:
        _expect(f"inventory skill_version {c['name']}", inv_skill_version(c["files"]), c["version"])
    for c in vec["conn_version"]:
        _expect(f"inventory conn_version {c['name']}", inv_conn_version(c["server"]), c["version"])
    for c in vec["precedence"]:
        _expect(f"inventory precedence {c['name']}", inv_winners(c["kind"], c["entries"]), c["winners"])
    for c in vec["classify"]:
        _expect(f"inventory classify {c['name_case']}", inv_classify(c), c["source"])
    for c in vec["allow_settle"]:
        _expect(f"inventory allow_settle {c['name']}", inv_settle_allow(c), c["effective"])
    for c in vec["allowed"]:
        _expect(f"inventory allowed {c['name']}", inv_allowed(c), c["allowed"])



# --- addon-manifest amendment (addon-manifest.md, Reserved core commands) --------------------------------------------
RESERVED_W2B = ["record", "job", "secret", "conn", "run", "screen", "type"]


def kind_addon_manifest():
    if SELECT:  # without arguments the generic example loop above already checked these
        for f in sorted((HERE / "examples" / "addon-manifest").glob("*.toml")):
            check("addon-manifest", load(f), f.name.startswith("valid-"), f"examples/addon-manifest/{f.name}")
        check("addon-manifest", load(HERE / "review" / "automation.orch-addon.toml"), True, "review/automation.orch-addon")
    names = json.loads((HERE / "addon-manifest.schema.json").read_text())["properties"]["name"]["not"]["enum"]
    for n in RESERVED_W2B:
        if n not in names:
            fails.append(f"addon-manifest.schema.json: {n!r} must be a reserved core name")
    vpage, verr = _w("cli-answer", "page"), _w("cli-answer", "error")
    _examples("cli-page", lambda d: _msgs(vpage, d))
    _examples("cli-error", lambda d: _msgs(verr, d))



# --- screen (screen.md) ----------------------------------------------------------------------------------------------
import codecs

ALT_RE = re.compile(r"\x1b\[\?(1049|1047|47)([hl])")
LAYOUT_RE = re.compile(r",(\d+)x(\d+),")
OCTAL_RE = re.compile(rb"\\([0-7]{3})")


def scr_unescape(data):
    """tmux control mode: bytes below 0x20 and '\\' arrive as \\ooo; everything else raw."""
    return OCTAL_RE.sub(lambda m: bytes([int(m.group(1), 8)]), data)


class ScrStrip:
    """Streaming filter: drops every OSC (ESC ] / 0x9d), DCS (ESC P / 0x90), APC (ESC _ / 0x9f), PM (ESC ^ / 0x9e) and
    SOS (ESC X / 0x98) string up to its terminator (BEL, ESC \\ or 0x9c), also when split across chunks. P1: none of these
    are needed to draw the screen; they carry clipboard writes, links, titles, notifications and query replies."""

    STARTS = {"]": "osc", "P": "str", "_": "str", "^": "str", "X": "str"}
    C1 = {"\x9d": "osc", "\x90": "str", "\x9f": "str", "\x9e": "str", "\x98": "str"}

    def __init__(self):
        self.mode, self.pending = None, ""

    def feed(self, text, final=False):
        out, s, i = [], self.pending + text, 0
        self.pending = ""
        while i < len(s):
            ch = s[i]
            if self.mode:
                if (ch == "\x07" and self.mode == "osc") or ch == "\x9c":
                    self.mode = None
                elif ch == "\x1b":
                    if i + 1 >= len(s):
                        self.pending = ch if not final else ""
                        break
                    if s[i + 1] == "\\":
                        self.mode = None
                        i += 1
                i += 1
                continue
            if ch == "\x1b":
                if i + 1 >= len(s):
                    if not final:
                        self.pending = ch
                    else:
                        out.append(ch)
                    break
                if s[i + 1] in self.STARTS:
                    self.mode = self.STARTS[s[i + 1]]
                    i += 2
                    continue
            if ch in self.C1:
                self.mode = self.C1[ch]
                i += 1
                continue
            out.append(ch)
            i += 1
        return "".join(out)


def scr_from_control(lines, needles=()):
    """Control-mode lines (bytes, without newline) -> stream lines after hello/snapshot (seq from 1)."""
    out, dec, alt, size = [], codecs.getincrementaldecoder("utf-8")("replace"), False, None
    longest = max((len(n) for n, _ in needles), default=1)
    hold = [""]
    strip = ScrStrip()

    def emit(**k):
        out.append({"v": 1, "seq": len(out) + 1, **k})

    for raw in lines:
        if raw.startswith(b"%output "):
            parts = raw.split(b" ", 2)
            text = strip.feed(dec.decode(scr_unescape(parts[2] if len(parts) > 2 else b"")))
            buf = hold[0] + text
            done, i = _hide_upto(buf, list(needles), max(0, len(buf) - (longest - 1)))
            hold[0] = buf[i:]
            if done:
                emit(type="output", data=done)
            for m in ALT_RE.finditer(text):
                on = m.group(2) == "h"
                if on != alt:
                    alt = on
                    emit(type="alt", on=on)
        elif raw.startswith(b"%layout-change "):
            m = LAYOUT_RE.search(raw.decode("utf-8", "replace"))
            if m and (int(m.group(1)), int(m.group(2))) != size:
                size = (int(m.group(1)), int(m.group(2)))
                emit(type="resize", cols=size[0], rows=size[1])
        elif raw.startswith(b"%exit"):
            emit(type="end", reason="session-gone")
    rest = hold[0] + strip.feed(dec.decode(b"", final=True), final=True)
    if rest:
        emit(type="output", data=sec_hide(rest, list(needles)))
    return out


def scr_takeover(c):
    """c["proof"] = the hp_verify result of the call (human-proof.md); c["proof_by"] = by from the proof. No flag is read."""
    if not c["live_session"] or not c["session_typing"]:
        return "switched_off"
    if c["admin_lock"]:
        return "locked_by_admin"
    if c["proof"] != "ok":
        return "not_allowed"
    if not c["live"]:
        return "not_available"
    if c["held_by"] and c["held_by"] != c["proof_by"] and _t(c["now"]) < _t(c["expires_at"]):
        return "conflict"
    return "ok"


def scr_expired(c):
    return _t(c["now"]) >= _t(c["last_input_at"]) + timedelta(seconds=120)


def _screen_stream_errors(v, doc):
    if not isinstance(doc, list) or not doc:
        return ["needs a non-empty list of stream lines"]
    errs = [m for ln in doc for m in _msgs(v, ln)]
    if errs:
        return errs
    if [ln["seq"] for ln in doc] != list(range(1, len(doc) + 1)):
        return ["seq must be 1, 2, 3 ..."]
    if doc[0]["type"] != "hello" and not (len(doc) == 1 and doc[0]["type"] == "error"):
        return ["the first line must be hello (or a refusal: one error line)"]
    ends = [i for i, ln in enumerate(doc) if ln["type"] in ("end", "error")]
    if ends and ends[0] != len(doc) - 1:
        return ["end or error must be the last line"]
    return []


def kind_screen():
    v, vt = _w("screen"), _w("screen", "type_input")
    _examples("screen", lambda d: _screen_stream_errors(v, d))
    _examples("type-input", lambda d: _msgs(vt, d))
    for f in sorted((HERE / "examples" / "run").glob("*takeover*")):
        check("run", load(f), f.name.startswith("valid-"), f"examples/run/{f.name}")
    vec = _vec("screen-v1.json")
    for c in vec["control_mode"]:
        lines = [ln.encode() for ln in c["lines"]]
        got = scr_from_control(lines, sec_needles(c.get("keys", [])))
        for ln in got:
            for m in _msgs(v, ln):
                fails.append(f"screen control_mode {c['name']} seq {ln['seq']}: {m}")
        if "frames" in c:
            _expect(f"screen control_mode {c['name']}", got, c["frames"])
        if "joined" in c:
            _expect(f"screen control_mode {c['name']} joined", "".join(x.get("data", "") for x in got), c["joined"])
    for c in vec["utf8_split"]:
        got = scr_from_control([b"%output %0 " + bytes.fromhex(h) for h in c["chunks_hex"]])
        _expect(f"screen utf8_split {c['name']}", [x["data"] for x in got if x["type"] == "output"], c["data"])
    for c in vec["takeover"]:
        _expect(f"screen takeover {c['name']}", scr_takeover(c), c["result"])
    for c in vec["expiry"]:
        _expect(f"screen expiry {c['name']}", scr_expired(c), c["expired"])



# --- counts (counts.md, usage-counts.md) -----------------------------------------------------------------------------
import hmac

CNT_FIELDS = ("kind", "name", "source", "runs", "uses", "ok", "failed", "refused", "unknown", "seen")
NAMES_ALWAYS_SENT = ("admin", "builtin", "marketplace")  # P1: anything else (workspace, harness, none, unknown) is hidden


def cnt_items(case):
    """Reference counting with denominators: runs[].sees = kinds the run's agent tool can report."""
    runs, items = case["runs"], {}
    for inv in case.get("inventory", []):
        items.setdefault((inv["kind"], inv["name"], inv["source"]), {"uses": 0, "ok": 0, "failed": 0, "refused": 0, "unknown": 0, "used_runs": set()})
    for r in runs:
        for ev in r["events"]:
            it = items.setdefault((ev["kind"], ev["name"], ev["source"]), {"uses": 0, "ok": 0, "failed": 0, "refused": 0, "unknown": 0, "used_runs": set()})
            it["uses"] += 1
            it["used_runs"].add(r["run"])
            if ev.get("refused"):
                it["refused"] += 1
            elif ev["ok"] is True:
                it["ok"] += 1
            elif ev["ok"] is False:
                it["failed"] += 1
            else:
                it["unknown"] += 1
    out = []
    for (kind, name, source), it in sorted(items.items()):
        of = sum(1 for r in runs if kind in r["sees"])
        used = len(it["used_runs"])
        seen = "yes" if it["uses"] else ("not_seen" if of else "unknown")
        out.append({"kind": kind, "name": name, "source": source, "runs": {"used": used, "of": max(of, used), "unseen": len(runs) - max(of, used)},
                    "uses": it["uses"], "ok": it["ok"], "failed": it["failed"], "refused": it["refused"], "unknown": it["unknown"], "seen": seen})
    return out


def usage_name(kind, name, source, share_names, salt):
    if source in NAMES_ALWAYS_SENT or share_names:
        return {"name": name, "ref": None}
    return {"name": None, "ref": "h_" + hmac.new(salt.encode(), f"{kind}:{name}".encode(), hashlib.sha256).hexdigest()[:16]}


def usage_queue(c):
    if not c["share_counts"] or c["policy"] == "off":
        return {"send": [], "drop": sorted(c["pending"])}
    today = datetime.strptime(c["today"], "%Y-%m-%d")
    old = [d for d in c["pending"] if (today - datetime.strptime(d, "%Y-%m-%d")).days > 60]
    keep = sorted(d for d in c["pending"] if d not in old and d != c["today"])
    return {"send": keep if c["connected"] else [], "drop": sorted(old)}


def kind_counts():
    va, vd, vu, vp = (_w("counts", d) for d in ("answer", "day_file", "upload", "policy"))
    _core_clean("counts")
    _examples("counts", lambda d: _msgs(va, d))
    _examples("counts-day", lambda d: _msgs(vd, d))
    _examples("usage-upload", lambda d: _msgs(vu, d))
    _examples("usage-policy", lambda d: _msgs(vp, d))
    vec = _vec("counts-v1.json")
    for c in vec["denominators"]:
        _expect(f"counts denominators {c['name']}", cnt_items(c), c["items"])
    for c in vec["names"]:
        _expect(f"counts names {c['name']}", usage_name(c["kind"], c["item"], c["source"], c["share_names"], c["salt"]), c["sent"])
    for c in vec["queue"]:
        _expect(f"counts queue {c['name']}", usage_queue(c), c["expect"])
    for c in vec["idempotent"]:
        store = {}
        results = []
        for put in c["puts"]:
            key = (put["workspace"], put["day"])
            results.append("replaced" if key in store else "stored")
            store[key] = put["body"]
        _expect(f"counts idempotent {c['name']}", {"results": results, "days": len(store)}, c["expect"])



# --- human proof (human-proof.md, invariant H1) ----------------------------------------------------------------------
HP_MAX_LIFE = 60


def _b64u(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def hp_mint(key_hex, payload):
    body = "hp1." + _b64u(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    return body + "." + _b64u(hmac.new(bytes.fromhex(key_hex), body.encode(), hashlib.sha256).digest())


def hp_verify(c):
    """Reference check of a human-only call. Flags (--by, --from) and the environment are never trusted."""
    if c.get("agent_env"):
        return "agent_env"
    if c.get("home_trusted") is False:  # key, nonce store or settings came from an env-chosen orch home
        return "forged"
    proof = c.get("proof")
    if not proof:
        return "missing"
    parts = proof.split(".")
    if len(parts) != 3 or parts[0] != "hp1":
        return "forged"
    try:
        p = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except ValueError:
        return "forged"
    if not isinstance(p, dict) or _msgs(_w("human-proof", "payload"), p):
        return "forged"
    if p.get("dev"):  # test-human proof: only on a workspace with a dev RECORD in the guarded home (never a file)
        if not c.get("dev_record"):
            return "dev_on_real"
        key = c.get("dev_key")
        if not key or p["by"] != "human:test-human":
            return "forged"
    else:
        key = c["key"]
    want = _b64u(hmac.new(bytes.fromhex(key), f"hp1.{parts[1]}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(want, parts[2]):
        return "forged"
    if c.get("by_flag") is not None and c["by_flag"] != p["by"]:
        return "forged"
    if p["op"] != c["op"]:
        return "wrong_op"
    if p["target"] != c["target"]:
        return "wrong_target"
    if p["exp"] - p["iat"] > HP_MAX_LIFE or not p["iat"] <= c["now"] < p["exp"]:
        return "expired"
    if p["nonce"] in c.get("used_nonces", []):
        return "replayed"
    return "ok"


SETTING_DEFAULTS = {"focus.live_session": True, "focus.session_typing": False, "insights.share_counts": True,
                    "insights.share_names": False, "secret.allow_get": False, "conn.allow": False}


def hp_settle(c):
    """Effective value after each event. file:v = someone edited the file; proof:v = a person set it with a proof (the core
    writes file and record). Lowering in the file writes a tombstone record (false). Effective = file AND (record, or the
    default when no record ever existed)."""
    default = SETTING_DEFAULTS[c["setting"]]
    file_val, record, out = default, None, []
    for ev in c["events"]:
        if ev["by"] == "proof":
            file_val = record = ev["value"]
        else:
            file_val = ev["value"]
            if ev["value"] is False:
                record = False
        out.append(bool(file_val and (record if record is not None else default)))
    return out


def _pending_mac(key, workspace, ticket, line):
    canon = json.dumps({k: x for k, x in line.items() if k not in ("mac", "delivered_at", "human")}, sort_keys=True,
                       separators=(",", ":"), ensure_ascii=False)
    return _b64u(hmac.new(bytes.fromhex(key), f"pending1.{workspace}.{ticket}.{canon}".encode(), hashlib.sha256).digest())


def pending_is_human(c):
    """A pending line is a person's only with a valid MAC bound to this workspace and ticket; by/via/human are ignored."""
    line = c["line"]
    mac = line.get("mac")
    if not mac or line.get("kind") not in ("answer", "message", "text"):
        return False
    return hmac.compare_digest(_pending_mac(c["key"], c["workspace"], c["ticket"], line), mac)


def pending_deliver(c):
    """Deliver a line only when its id is not in the guarded delivered record (delivered_at is display only)."""
    return c["line"]["id"] not in c["delivered_ids"]


def _wontdo_mac(key, workspace, item):
    canon = json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _b64u(hmac.new(bytes.fromhex(key), f"wontdo1.{workspace}.{canon}".encode(), hashlib.sha256).digest())


def wontdo_is_human(c):
    """A synced won't-do is a person's only via the receiving core's relay-authenticated sender or its own wontdo1 MAC."""
    if c.get("relay_authenticated_sender"):
        return True
    m = c.get("mac")
    return bool(m) and hmac.compare_digest(m, _wontdo_mac(c["key"], c["workspace"], c["item"]))


def relay_conn(c):
    """Where relay calls go: only the record in the guarded home; a differing workspace file refuses; env never used."""
    rec = c.get("record")
    if not rec:
        return "not_connected"
    f = c.get("file")
    if f is not None and (f.get("url") != rec["url"] or f.get("workspace") != rec["workspace"]):
        return "refused"
    return {"url": rec["url"], "workspace": rec["workspace"], "token_from": "record", "proxy": None, "trust": "fixed"}


def dev_can_mark(c):
    """A workspace becomes dev only when a dev install creates it, and never once it has a human key."""
    return bool(c["install_dev"] and c["creating"] and not c["has_human_key"])


def _under(path, prefix):
    """Component-wise: is realpath `path` inside the literal `prefix` (both absolute POSIX strings)?"""
    pp, xp = [x for x in path.split("/") if x], [x for x in prefix.split("/") if x]
    return len(pp) > len(xp) and pp[: len(xp)] == xp


def home_ok(c):
    """Guarded orch home rule (secrets.md). Test paths exist only on a dev/test install, under the literal
    <account home>/.orch-test/ that lstats as a real directory owned by the user; paths are compared by realpath."""
    prefix = c["account_home"].rstrip("/") + "/.orch-test"
    active = c["install"] in ("dev", "test") and c["prefix_real_dir"]
    ws_test = active and _under(c["workspace_realpath"], prefix)
    default_home = c["account_home"].rstrip("/") + "/.orch-tool"
    if c["home_realpath"] == default_home:
        home = "default"
    elif active and _under(c["home_realpath"], prefix):
        home = "test"
    else:
        home = "other"
    return (not ws_test and home == "default") or (ws_test and home == "test")


def kind_human():
    vs = _w("human-proof", "settings_record")
    _examples("human-settings", lambda d: _msgs(vs, d))
    vec = _vec("human-proof-v1.json")
    for c in vec["verify"]:
        _expect(f"human verify {c['name']}", hp_verify(c), c["result"])
    for c in vec["concurrent"]:  # one nonce store under the key lock: the first call wins, the second is a replay
        used, got = [], []
        for call in c["calls"]:
            r = hp_verify({**call, "used_nonces": list(used)})
            if r == "ok":
                used.append(json.loads(base64.urlsafe_b64decode(call["proof"].split(".")[1] + "=="))["nonce"])
            got.append(r)
        _expect(f"human concurrent {c['name']}", got, c["results"])
    for c in vec["pending"]:
        _expect(f"human pending {c['name']}", pending_is_human(c), c["human"])
    for c in vec["deliver"]:
        _expect(f"human deliver {c['name']}", pending_deliver(c), c["deliver"])
    for c in vec["wont_do"]:
        _expect(f"human wont_do {c['name']}", wontdo_is_human(c), c["human"])
    for c in vec["relay"]:
        _expect(f"human relay {c['name']}", relay_conn(c), c["expect"])
    for c in vec["dev_mark"]:
        _expect(f"human dev_mark {c['name']}", dev_can_mark(c), c["ok"])
    for c in vec["home"]:
        _expect(f"human home {c['name']}", home_ok(c), c["ok"])
    for c in vec["settle"]:
        _expect(f"human settle {c['name']}", hp_settle(c), c["effective"])
    if set(SETTING_DEFAULTS) != set(json.loads((HERE / "vectors" / "human-proof-v1.json").read_text())["settings"]):
        fails.append("human: SETTING_DEFAULTS and vectors settings differ")



# --- proposals (proposal.md) -----------------------------------------------------------------------------------------
CHECKUP_ALLOWED = {("record", "query"), ("record", "tail"), ("record", "counts"), ("record", "propose"), ("ticket", "list"),
                   ("ticket", "show"), ("conn", "list"), ("log", None), ("check", None)}
SHELL_META = re.compile(r"[;&|`$<>\\\n(){}*?~]")


def checkup_allowed(c):
    """Layer 1 (the agent tool's own exact allowlist): the whole shell command must be `orch <cmd> [<sub>] ...` from the
    list, no shell syntax; log/check only on the check-up's own ticket. Layer 2 (core): propose only when the run record
    says profile checkup. Returns True when both layers allow it."""
    cmd = c["command"]
    if SHELL_META.search(cmd):
        return False
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return False
    if len(argv) < 2 or argv[0] != "orch":
        return False
    top, sub = argv[1], (argv[2] if len(argv) > 2 else None)
    if (top, sub) not in CHECKUP_ALLOWED and (top, None) not in CHECKUP_ALLOWED:
        return False
    if top in ("log", "check"):
        rest = [a for a in argv[2:] if not a.startswith("-")]
        tick = rest[1] if top == "check" and len(rest) > 1 and rest[0] in ("add", "done", "start") else (rest[0] if rest else None)
        if tick != c["own_ticket"]:
            return False
    if (top, sub) == ("record", "propose") and c.get("profile") != "checkup":
        return False
    return True


def change_sha256(change):
    if change is None:
        return None
    return "sha256:" + hashlib.sha256(json.dumps(change["files"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def proposal_from_draft(draft, ctx):
    """The core builds the stored proposal; the agent's draft supplies only its own fields. 'refused:<why>' on a bad draft."""
    if _msgs(_w("proposal", "draft"), draft):
        return "refused:invalid"
    if ctx.get("profile") != "checkup":
        return "refused:not_checkup"
    t = draft["target"]
    if draft["kind"] == "skill.new" and (t["name"].startswith("orch") or t["name"] in ctx["existing_names"]):
        return "refused:name_taken"
    files = None
    if draft["change"] is not None:
        files = [{"path": f["path"], "before": ctx["file_hashes"].get(f["path"]), "after": f["after"]} for f in draft["change"]["files"]]
    change = None if files is None else {"files": files}
    return {"schema": "orch.proposal/1", "id": ctx["id"], "created_at": ctx["now"], "checkup": ctx["checkup"],
            "kind": draft["kind"], "title": draft["title"], "plain": draft["plain"], "likely": draft["likely"],
            "evidence": draft["evidence"],
            "target": {"kind": t["kind"], "name": t["name"], "source": "new" if draft["kind"] == "skill.new" else ctx["source"],
                       "version": None if draft["kind"] == "skill.new" else ctx["version"]},
            "change": change, "change_sha256": change_sha256(change),
            "tests": {"state": "not_run", "cases": [], "ran_at": None}, "status": "proposed", "decided": None, "applied": None}


def proposal_hash(doc):
    """sha256 over {id, kind, target, change} of a proposal (canonical JSON); kept with the test result in orch home."""
    core = {k: doc.get(k) for k in ("id", "kind", "target", "change")}
    return "sha256:" + hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def proposal_step(c):
    """One decision. Status, tests and target come from the record in the guarded orch home (c["record"]); the workspace
    copy (c["file"]) only has to hash to the recorded value. Returns the new status or a refusal code."""
    rec, act = c["record"], c["action"]
    if act in ("accept", "rollback", "send_to_admin", "reject") and c.get("proof") != "ok":
        return "not_allowed"
    if rec is None:
        return "not_found"
    st = rec["status"]
    if act == "skill_changed":
        return "stale" if st in ("proposed", "tested") else st
    if act == "tests_done":
        return "tested" if st == "proposed" and c["tests"] == "passed" else st
    if act == "reject":
        return "rejected" if st in ("proposed", "tested") else "conflict"
    if proposal_hash(c["file"]) != rec["hash"]:
        return "changed"
    if act == "send_to_admin":
        return "sent_to_admin" if st == "tested" and rec["target"]["source"] == "admin" else "conflict"
    if act == "accept":
        if rec["target"]["source"] == "admin":
            return "admin_only"
        if st != "tested" or rec["tests"] != "passed":
            return "not_tested"
        if c["current_version"] != rec["target"]["version"]:
            return "stale"
        if c["proof_target"] != f"{rec['id']}@{rec['hash'].removeprefix('sha256:')}":
            return "changed"
        return "accepted"
    if act == "rollback":
        if st != "accepted":
            return "conflict"
        return "rolled_back" if c["current_version"] == rec["applied_after"] else "conflict"
    return "invalid"


def kind_proposal():
    v = _w("proposal")
    _examples("proposal", lambda d: _msgs(v, d))
    vec = _vec("proposal-v1.json")
    for c in vec["steps"]:
        _expect(f"proposal steps {c['name']}", proposal_step(c), c["result"])
    vd = _w("proposal", "draft")
    _examples("proposal-draft", lambda d: _msgs(vd, d))
    for c in vec["checkup_commands"]:
        _expect(f"proposal checkup_commands {c['command']!r}", checkup_allowed(c), c["allowed"])
    for c in vec["from_draft"]:
        got = proposal_from_draft(c["draft"], c["ctx"])
        if isinstance(got, dict):
            for m in _msgs(v, got):
                fails.append(f"proposal from_draft {c['name']}: stored proposal not valid: {m}")
        _expect(f"proposal from_draft {c['name']}", got, c["expect"])


# --- dispatch (keep last in this block) ------------------------------------------------------------------------------
KINDS = {
    "activity": kind_activity,
    "secrets": kind_secrets,
    "jobs": kind_jobs,
    "blocks": kind_blocks,
    "inventory": kind_inventory,
    "addon-manifest": kind_addon_manifest,
    "screen": kind_screen,
    "counts": kind_counts,
    "human": kind_human,
    "proposal": kind_proposal,
}


def _finish(label):
    if fails:
        print("\n".join("FAIL " + f for f in fails))
        sys.exit(1)
    print(f"{label}: ALL OK")
    sys.exit(0)


if SELECT:
    _unknown = [k for k in SELECT if k not in KINDS]
    if _unknown:
        print(f"Unknown kind: {', '.join(_unknown)}. Kinds: {', '.join(KINDS)}")
        sys.exit(2)
    for _k in dict.fromkeys(SELECT):
        KINDS[_k]()
    _finish("contracts " + " ".join(dict.fromkeys(SELECT)))
# ---------------------------------------------------------------------------------------------------------------------


for kind in V:
    files = sorted((HERE / "examples" / kind).glob("*.*"))
    for f in files:
        check(kind, load(f), f.name.startswith("valid-"), f"examples/{kind}/{f.name}")
    for prefix in ("valid-", "invalid-"):
        if not any(f.name.startswith(prefix) for f in files):
            fails.append(f"examples/{kind}: needs at least one {prefix}* example")

for name in CORE_CLEAN:
    hit = TOOL_NAMES.search((HERE / f"{name}.schema.json").read_text())
    if hit:
        fails.append(f"{name}.schema.json names an add-on or agent tool: {hit.group(0)!r}")

review = HERE / "review"
check("ticket", json.loads((review / "ticket.example.json").read_text()), True, "review/ticket")
check("workspaces", json.loads((review / "workspaces.example.json").read_text()), True, "review/workspaces")
check("addon-manifest", load(review / "automation.orch-addon.toml"), True, "review/automation.orch-addon")
check("addon-view", load(review / "scheduler.view.example.json"), True, "review/scheduler.view")
for i, m in enumerate(json.loads((review / "message.examples.json").read_text())):
    check("message", m, True, f"review/message[{i}]")


def decrypt(key_b64, blob):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = base64.urlsafe_b64decode(key_b64 + "=" * (-len(key_b64) % 4))
    if blob[:4] != b"OPF1" or len(blob) < 32:
        raise ValueError("bad magic")
    plain = AESGCM(key).decrypt(blob[4:16], blob[16:], b"OPF1")
    (n,) = struct.unpack(">I", plain[:4])
    if not 1 <= n <= 65536:
        raise ValueError("bad header length")
    header = json.loads(plain[4 : 4 + n].decode())
    body = plain[4 + n :]
    if header["size"] != len(body):
        raise ValueError("size mismatch")
    return header, body


vec = json.loads((HERE / "vectors" / "publish-blob-v1.json").read_text())
g = vec["good"]
for gname in ("good", "good_with_note"):
    g = vec[gname]
    try:
        h, body = decrypt(g["key_b64url"], bytes.fromhex(g["blob_hex"]))
        if body.decode() != g["content_utf8"]:
            fails.append(f"vector {gname}: content differs")
        if json.dumps(h, ensure_ascii=False, separators=(",", ":")) != g["header_json"]:
            fails.append(f"vector {gname}: header differs")
    except Exception as e:  # noqa: BLE001
        fails.append(f"vector {gname}: {e!r}")
for case in vec["must_fail"]:
    try:
        decrypt(case["key_b64url"], bytes.fromhex(case["blob_hex"]))
        fails.append(f"vector {case['name']}: decrypted but must fail")
    except Exception:  # noqa: BLE001
        pass


def unbundle(raw):
    """Reader rules of crypto.md "Folder bundle". Returns {path: bytes}."""
    (m,) = struct.unpack(">I", raw[:4])
    if not 1 <= m <= 1 << 20 or 4 + m > len(raw):
        raise ValueError("bad index length")
    idx = json.loads(raw[4 : 4 + m].decode())
    files, out, pos = idx["files"], {}, 4 + m
    if idx.get("v") != 1 or not 1 <= len(files) <= 2000 or not str(idx.get("entry", "")).lower().endswith((".html", ".htm")):
        raise ValueError("bad index")
    for f in files:
        p, n = f["path"], f["size"]
        segs = p.split("/")
        bad = not 1 <= len(p) <= 255 or "\\" in p or "\0" in p or any(x in ("", ".", "..") for x in segs)
        if bad or p in out or not isinstance(n, int) or n < 0:
            raise ValueError("bad path or size: " + p)
        out[p] = raw[pos : pos + n]
        pos += n
    if pos != len(raw) or idx["entry"] not in out:
        raise ValueError("sizes do not add up")
    return out


bvec = json.loads((HERE / "vectors" / "publish-bundle-v1.json").read_text())
for gname in ("good", "good_no_index"):
    try:
        raw = bytes.fromhex(bvec[gname]["bundle_hex"])
        got = unbundle(raw)
        want = {f["path"]: f["content_utf8"].encode() for f in bvec[gname]["files"]}
        (m,) = struct.unpack(">I", raw[:4])
        if got != want or json.loads(raw[4 : 4 + m])["entry"] != bvec[gname]["entry"]:
            fails.append(f"bundle vector {gname}: files or entry differ")
    except Exception as e:  # noqa: BLE001
        fails.append(f"bundle vector {gname}: {e!r}")
for case in bvec["must_fail"]:
    try:
        unbundle(bytes.fromhex(case["bundle_hex"]))
        fails.append(f"bundle vector {case['name']}: unpacked but must fail")
    except Exception:  # noqa: BLE001
        pass

# clean_untrusted (SA-14): reference rules of vectors/clean-untrusted-v1.json;
# workspace/src/orch/text.py must give the same outputs. Order matters: drop invisible characters FIRST
# (so they cannot split a comment marker), then remove comments until nothing changes, then an open "<!--" tail.
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_OPEN_TAIL = re.compile(r"<!--.*\Z", re.S)
# Default_Ignorable_Code_Point (Unicode DerivedCoreProperties), dropped whatever their category.
_DROP = (
    {0x00AD, 0x034F, 0x061C, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x3164, 0xFEFF, 0xFFA0}
    | set(range(0x180B, 0x1810))
    | set(range(0x200B, 0x2010))
    | set(range(0x202A, 0x202F))
    | set(range(0x2060, 0x2070))
    | set(range(0xFE00, 0xFE10))
    | set(range(0xFFF0, 0xFFF9))
    | set(range(0x1BCA0, 0x1BCA4))
    | set(range(0x1D173, 0x1D17B))
    | set(range(0xE0000, 0xE1000))
    | {0x2800}  # braille blank: looks empty, not ignorable
)


def clean_untrusted(text, limit=2000):
    text = unicodedata.normalize("NFC", text).replace("\u2028", "\n").replace("\u2029", "\n")
    text = "".join(
        ch
        for ch in text
        if ch in "\n\t" or (unicodedata.category(ch) not in ("Cc", "Cf", "Cn", "Cs") and ord(ch) not in _DROP)
    )
    while True:
        cut = _COMMENT.sub("", text)
        if cut == text:
            break
        text = cut
    return _OPEN_TAIL.sub("", text)[:limit]


cvec = json.loads((HERE / "vectors" / "clean-untrusted-v1.json").read_text())
if len(cvec["cases"]) < 3:
    fails.append("clean-untrusted vector: needs at least three cases")
for case in cvec["cases"]:
    if clean_untrusted(case["in"]) != case["out"]:
        fails.append(f"clean-untrusted vector {case['name']}: output differs")

# ticket_view (mobile chat): schema + the 16 KB cap on body.ticket_view as compact UTF-8 JSON.
# The relay (relay/tests/ticket_view.rs) and the workspace (workspace/tests/test_ticket_view.py) replay the same cases.
tvec = json.loads((HERE / "vectors" / "ticket-view-v1.json").read_text())
for case in tvec["cases"]:
    m = case["message"]
    view = m["body"].get("ticket_view")
    big = view is not None and len(json.dumps(view, separators=(",", ":"), ensure_ascii=False).encode()) > tvec["cap_bytes"]
    ok = not errors("message", m) and not big
    if ok != case["ok"]:
        fails.append(f"ticket-view vector {case['name']}: expected {'ok' if case['ok'] else 'refused'}")


# Ticket keys: reference rule for the code suggested from a folder name (workspace/src/orch/config.py
# suggest_code gives the same) and the key pattern of ticket.schema.json.
def suggest_code(name):
    """Initials of the words (up to 4); one word gives its first 3 characters. ASCII letters and digits only,
    uppercase; fewer than 2 characters are filled up with W, S (empty name -> WS)."""
    words = re.findall(r"[A-Za-z0-9]+", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode())
    code = ("".join(w[0] for w in words[:4]) if len(words) > 1 else (words[0][:3] if words else "")).upper()
    return (code + "WS")[:2] if len(code) < 2 else code


kvec = json.loads((HERE / "vectors" / "ticket-key-v1.json").read_text())
_ts = json.loads((HERE / "ticket.schema.json").read_text())["$defs"]
_KEY, _CODE = re.compile(_ts["key"]["pattern"]), re.compile(_ts["code"]["pattern"])
for name, want in kvec["suggest"]:
    got = suggest_code(name)
    if got != want or not _CODE.match(got):
        fails.append(f"ticket-key vector suggest {name!r}: got {got!r}, want {want!r}")
for k in kvec["valid_keys"]:
    if not _KEY.match(k):
        fails.append(f"ticket-key vector: {k!r} must be a valid key")
for k in kvec["invalid_keys"]:
    if _KEY.match(k):
        fails.append(f"ticket-key vector: {k!r} must be refused")


# Phone API v3 (relay-api.md, Phone API): request/response bodies in phone-api.schema.json, which points into
# message.schema.json. Every /v1/phone example and the phone-v3 vector are checked against it.
_msg_schema = _expand(json.loads((HERE / "message.schema.json").read_text()))
_phone_schema = _expand(json.loads((HERE / "phone-api.schema.json").read_text()))
_look_schema = json.loads((HERE / "look.schema.json").read_text())
_reg = Registry().with_resources(
    [(s["$id"], Resource.from_contents(s)) for s in (_msg_schema, _phone_schema, _look_schema)]
)


def phone_errors(defname, doc):
    v = Draft202012Validator({"$ref": f"{_phone_schema['$id']}#/$defs/{defname}"}, registry=_reg, format_checker=FormatChecker())
    return list(v.iter_errors(doc))


# (method, path regex, request $def or None, {status: response $def}); error statuses use $defs/error.
PHONE_ROUTES = [
    ("POST", r"/v1/phone/send", "send_request", {201: "send_response", 200: "send_response"}),
    ("POST", r"/v1/phone/answer", "answer_request", {201: "answer_response", 200: "answer_response"}),
    ("POST", r"/v1/phone/blobs", None, {201: "blob_response"}),
    ("GET", r"/v1/phone/messages(\?.*)?", None, {200: "messages_response"}),
    ("GET", r"/v1/phone/workspaces", None, {200: "workspaces_response"}),
    ("PATCH", r"/v1/phone/workspaces/ws_[a-z0-9]{10}", "workspace_patch_request", {200: "workspace_item"}),
    ("GET", r"/v1/phone/settings", None, {200: "settings"}),
    ("PATCH", r"/v1/phone/settings", "settings_patch_request", {200: "settings"}),
    ("PATCH", r"/v1/phone/groups/ws_[a-z0-9]{10}/grp_t_[a-z0-9]{6,16}", "group_mute_request", {200: "group_mute_response"}),
    ("POST", r"/v1/phone/invitations/redeem", "redeem_request", {200: "redeem_response"}),
    ("POST", r"/v1/phone/transcribe(\?.*)?", None, {200: "transcribe_response"}),
]
NEW_PHONE_PATHS = ["/v1/phone/blobs", "/v1/phone/speech/", "/v1/phone/settings", "/v1/phone/invitations/redeem", "/v1/phone/groups/"]
_seen_new = set()
for i, ex in enumerate(json.loads((review / "relay-api.examples.json").read_text())):
    req, resp = ex["request"], ex["response"]
    for np in NEW_PHONE_PATHS:
        if req["path"].startswith(np):
            _seen_new.add(np)
    for method, rx, reqdef, respdefs in PHONE_ROUTES:
        if req["method"] != method or not re.fullmatch(rx, req["path"]):
            continue
        label = f"review/relay-api[{i}] {method} {req['path']} {resp['status']}"
        if reqdef and req["body"] is not None:
            for e in phone_errors(reqdef, req["body"])[:1]:
                if resp["status"] < 400 or resp["status"] in (409, 410, 404):
                    fails.append(f"{label}: request: {e.message}")
        if resp["status"] >= 400:
            for e in phone_errors("error", resp["body"])[:1]:
                fails.append(f"{label}: error body: {e.message}")
        elif resp["status"] in respdefs:
            for e in phone_errors(respdefs[resp["status"]], resp["body"])[:1]:
                fails.append(f"{label}: response: {e.message}")
for np in NEW_PHONE_PATHS:
    if np not in _seen_new:
        fails.append(f"review/relay-api: needs an example for {np}")

canvec = json.loads((HERE / "vectors" / "phone-can-v1.json").read_text())
for case in canvec["workspaces"]:
    errs = phone_errors("workspaces_response", case["response"])
    if bool(errs) == case["ok"]:
        fails.append(f"phone-can vector {case['name']}: expected {'ok' if case['ok'] else 'refused'}, got {errs[0].message if errs else 'valid'}")

pvec = json.loads((HERE / "vectors" / "phone-v3-v1.json").read_text())


def build_phone_text(phone, req):
    """Reference: the text message the relay stores for POST /v1/phone/send (without id and created_at)."""
    m = {"schema": "orch.msg/1", "from": phone, "to": req["to"], "type": "text"}
    if req.get("ticket"):
        m["ticket"] = req["ticket"]
    if req.get("reply_to"):
        m["reply_to"] = req["reply_to"]
    body = {"client_id": req["client_id"]} if "client_id" in req else {}
    if req.get("general") is True:
        body["general"] = True
    for k in ("text", "attachments", "voice", "location", "feedback"):
        if k in req:
            body[k] = req[k]
    m["body"] = body
    return m


for case in pvec["send"]:
    ok = not phone_errors("send_request", case["request"])
    if ok != case["ok"]:
        fails.append(f"phone-v3 vector send {case['name']}: expected {'ok' if case['ok'] else 'refused'}")
    if case["ok"]:
        built = build_phone_text(pvec["phone"], case["request"])
        if built != case.get("built"):
            fails.append(f"phone-v3 vector send {case['name']}: built message differs")
        stored = {**built, "id": "m_0000000000000001", "created_at": "2026-11-06T20:00:00Z"}
        for e in errors("message", stored)[:1]:
            fails.append(f"phone-v3 vector send {case['name']}: built message invalid: {e.message}")
for sect, defname in (("answer", "answer_request"), ("settings_patch", "settings_patch_request"), ("workspace_patch", "workspace_patch_request")):
    for case in pvec[sect]:
        if (not phone_errors(defname, case["request"])) != case["ok"]:
            fails.append(f"phone-v3 vector {sect} {case['name']}: expected {'ok' if case['ok'] else 'refused'}")


# Mute (relay-api.md, Muted): push yes/no for a phone's mutes. Reference rule below; relay and phone replay the cases.
def _active(until, now):
    return until == "forever" or (isinstance(until, str) and until > now)


def mute_push(case):
    m, ph, now = case["message"], case["phone"], case["now"]
    if _active(ph.get("mute_all_until"), now):
        return False
    if _active(ph.get("workspace_mutes", {}).get(m["from"]), now):
        return False
    body = m.get("body", {})
    keys = [k for k in (body.get("group"), body.get("group_ref")) if isinstance(k, dict)]
    for g in ph.get("group_mutes", []):
        if _active(g["muted_until"], now) and any(k.get("host") == g["host"] and k.get("id") == g["id"] for k in keys):
            return False
    return True


mvec = json.loads((HERE / "vectors" / "mute-v1.json").read_text())
for case in mvec["cases"]:
    if mute_push(case) != case["push"]:
        fails.append(f"mute vector {case['name']}: expected push={case['push']}")
    for g in case["phone"].get("group_mutes", []):
        for e in phone_errors("group_mute", g)[:1]:
            fails.append(f"mute vector {case['name']}: group_mutes item: {e.message}")
for case in mvec["patch"]:
    if (not phone_errors(case["def"], case["request"])) != case["ok"]:
        fails.append(f"mute vector patch {case['name']}: expected {'ok' if case['ok'] else 'refused'}")


# Review question (relay-api.md, Review question): the question validates; the cases are fixed outcomes.
rqvec = json.loads((HERE / "vectors" / "review-question-v1.json").read_text())
check("message", rqvec["question"], True, "review-question vector: question")
for case in rqvec["cases"]:
    if case["do"] not in ("accept", "changes", "nothing") or (case["do"] == "changes" and not case.get("note")):
        fails.append(f"review-question vector {case['name']}: bad outcome")

# Ticket proposal question (relay-api.md, Ticket proposal question).
pqvec = json.loads((HERE / "vectors" / "proposal-question-v1.json").read_text())
for v in pqvec["valid"]:
    check("message", v["message"], True, f"proposal-question vector valid {v['name']}")
for v in pqvec["invalid"]:
    if v["name"] in ("question-id-not-own-id", "with-ticket", "prefix-without-marker", "null-marker"):  # relay-only rules, not schema
        continue
    check("message", v["message"], False, f"proposal-question vector invalid {v['name']}")
for case in pqvec["cases"]:
    if case["do"] not in ("make", "not_now", "nothing") or (case["do"] != "nothing" and not case.get("by")):
        fails.append(f"proposal-question vector {case['name']}: bad outcome")

# Ticket proposal result (relay-api.md, Ticket proposal result).
prvec = json.loads((HERE / "vectors" / "proposal-result-v1.json").read_text())


def _pr_text(r):
    """The one text a proposal result may carry (relay-api.md): derived from the result, never free."""
    if r["result"] == "made" or (r["result"] == "decided" and r.get("key")):
        return "Ticket made: " + r["key"]
    return "Couldn't make the ticket" if r["result"] == "refused" else "Already decided"


for v in prvec["valid"]:
    if v["message"]["body"]["text"] != _pr_text(v["message"]["body"]["proposal_result"]):
        fails.append(f"proposal-result vector valid {v['name']}: body.text is not the canonical line")
for v in prvec["valid"]:
    check("message", v["message"], True, f"proposal-result vector valid {v['name']}")
for v in prvec["invalid"]:
    check("message", v["message"], False, f"proposal-result vector invalid {v['name']}")
for v in prvec["relay"]:
    if "message" in v:  # relay rules (reply_to, routing, one result per proposal) are replayed by the relay's own tests
        check("message", v["message"], True, f"proposal-result vector relay (schema-valid) {v['name']}")
    if "message" in v and v["name"] != "text-names-another-key" and v["message"]["body"]["text"] != _pr_text(v["message"]["body"]["proposal_result"]):
        fails.append(f"proposal-result vector relay {v['name']}: body.text is not the canonical line")
    if v["name"] == "text-names-another-key" and v["message"]["body"]["text"] == _pr_text(v["message"]["body"]["proposal_result"]):
        fails.append("proposal-result vector relay text-names-another-key: text must differ from the canonical line")
    if v["expect"] not in (200, 201, 403, 404, 409, 422) or ("message" not in v and "request" not in v):
        fails.append(f"proposal-result vector relay {v['name']}: bad expect or entry")
_pr_to = {"made": "phones"}
for case in prvec["cases"]:
    n, snd, st = f"proposal-result vector case {case['name']}", case["send"], case["state"]
    if st not in ("open", "made", "gone", "answered_make", "answered_not_now", "result_recorded"):
        fails.append(f"{n}: bad state")
    should_send = case["authorised"] and case["answer"].strip().casefold() == "make"
    if (snd is not None) != should_send or (snd is None) != (case["to"] is None):
        fails.append(f"{n}: a result is sent exactly for an authorised make answer (and then has a `to`)")
    if snd is None:
        continue
    check("message", {"schema": "orch.msg/1", "id": "m_pres000000000099", "from": "ws_pilatus001", "to": case["to"], "type": "text",
                      "reply_to": "m_pr00000000000001", "created_at": "2026-11-09T10:42:00Z", "body": {"text": _pr_text(snd), "proposal_result": snd}},
          True, f"{n}: send body and routing")
    if case["to"] != _pr_to.get(snd["result"], case["from"]):
        fails.append(f"{n}: made goes to phones, refused/decided to the answering phone")
    if st in ("made", "gone", "answered_make", "answered_not_now") and snd["result"] != "decided":
        fails.append(f"{n}: a proposal that is not open gets decided")
    if st in ("made", "answered_make") and snd.get("key") != case.get("key"):
        fails.append(f"{n}: the decided result carries the key of the ticket the proposal became")
    if st in ("gone", "answered_not_now") and "key" in snd:
        fails.append(f"{n}: no ticket, no key")
    if st == "open":
        want = {"ok": {"result": "made", "key": case.get("key")}, "refused:human_proof": {"result": "refused", "reason": "needs_person"},
                "refused:other": {"result": "refused", "reason": "unavailable"}}.get(case.get("make"))
        if snd != want:
            fails.append(f"{n}: make outcome {case.get('make')} maps to {want}")
    if st == "made" and case.get("got_it_ack") is not False:
        fails.append(f"{n}: decided replaces the Got it ack")


def _proposal_card(events):
    card, final = "idle", False
    for e in events:
        if e == "answer_make":
            card = "making"
        elif e == "answer_not_now":
            card = "closed"
        elif e in ("2_min", "workspace_not_live"):
            card = "waiting" if card == "making" else card
        elif isinstance(e, dict) and e.get("reply_to") != "unknown" and not final:
            r = e["result"]
            card = "made" if r == "made" or (r == "decided" and e.get("key")) else "failed" if r == "refused" else "closed"
            final = card == "made" and r == "made"
    return card


for case in prvec["phone"]:
    if _proposal_card(case["events"]) != case["card"]:
        fails.append(f"proposal-result vector phone {case['name']}: card should be {case['card']}")

# Mobile mode (relay-api.md, Mobile mode).
mmvec = json.loads((HERE / "vectors" / "mobile-mode-v1.json").read_text())
for case in mmvec["heartbeat"]:
    if (not phone_errors("heartbeat_request", case["request"])) != case["ok"]:
        fails.append(f"mobile-mode vector heartbeat {case['name']}: expected {'ok' if case['ok'] else 'refused'}")
    if case["ok"] and phone_errors("heartbeat_response", {"mobile_mode": case["stored"]}):
        fails.append(f"mobile-mode vector heartbeat {case['name']}: stored value invalid")
for case in mmvec["control"]:
    if (not phone_errors("control_request", case["request"])) != case["ok"]:
        fails.append(f"mobile-mode vector control {case['name']}: expected {'ok' if case['ok'] else 'refused'}")
    if case["ok"]:
        body = {"control": case["request"]["control"]}
        if "client_id" in case["request"]:
            body["client_id"] = case["request"]["client_id"]
        built = {"schema": "orch.msg/1", "from": mmvec["phone"], "to": case["request"]["to"], "type": "control", "body": body}
        if built != case["built"]:
            fails.append(f"mobile-mode vector control {case['name']}: built message differs")
        stored = {**built, "id": "m_0000000000000001", "created_at": "2026-11-07T20:00:00Z"}
        for e in errors("message", stored)[:1]:
            fails.append(f"mobile-mode vector control {case['name']}: built message invalid: {e.message}")

def speech_text(body, limit):
    """Reference (relay-api.md, Speech): summary else text; URLs -> 'link'; drop * ` #; one space per whitespace run;
    longer than limit: cut after the last . ! ? that is followed by a space within the limit, else before the last
    space within the limit, else hard at the limit."""
    src = (body.get("speak") or {}).get("summary") or body["text"]
    src = re.sub(r"https?://\S+", "link", src)
    src = re.sub(r"[*`#]", "", src)
    src = re.sub(r"\s+", " ", src).strip()
    if len(src) <= limit:
        return src
    ends = [i for i in range(limit) if src[i] in ".!?" and src[i + 1] == " "]
    if ends:
        return src[: ends[-1] + 1]
    spaces = [i for i in range(limit + 1) if src[i] == " "]
    return src[: spaces[-1]] if spaces else src[:limit]


for case in pvec["speech_text"]:
    got = speech_text(case["body"], pvec["speech_max_chars"])
    if got != case["spoken"]:
        fails.append(f"phone-v3 vector speech_text {case['name']}: got {got!r}")
for case in pvec["general_updates"]:
    if (not errors("message", case["message"])) != case["ok"]:
        fails.append(f"phone-v3 vector general_updates {case['name']}: expected {'ok' if case['ok'] else 'refused'}")
for case in pvec["artifact_ids"]:
    got = "a_" + hashlib.sha256(f"{case['source']}\n{case['ref']}".encode()).hexdigest()[:12]
    if got != case["id"] or not re.fullmatch(_msg_schema["$defs"]["artifact_id"]["pattern"], got):
        fails.append(f"phone-v3 vector artifact_ids {case['ref']}: got {got}")

# Subscriber events and push signatures (relay-api.md, Subscribers).
import hmac as _hmac

_sub_v = validator("subscriber-event")
svec = json.loads((HERE / "vectors" / "subscriber-v1.json").read_text())
for ev in svec["valid_events"]:
    for e in _sub_v.iter_errors(ev):
        fails.append(f"subscriber vector {ev['id']}: {e.message}")
for case in svec["invalid_events"]:
    if not list(_sub_v.iter_errors(case["event"])):
        fails.append(f"subscriber vector invalid {case['name']}: accepted")
for case in svec["signatures"]:
    mac = _hmac.new(case["secret"].encode(), f"{case['timestamp']}.{case['body']}".encode(), hashlib.sha256).hexdigest()
    if "v1=" + mac != case["signature"]:
        fails.append(f"subscriber vector signature {case['name']}: got v1={mac}")


# Workspace look (look.md): allowlists in look.json, drawings in look/icons/, schema enums, vectors/look-v1.json.
look = json.loads((HERE / "look.json").read_text())
LOOK_ICONS = [i["id"] for i in look["icons"]]
LOOK_COLORS = [c["id"] for c in look["colors"]]
_cats = {c["id"] for c in look["categories"]}
if len(LOOK_ICONS) != 100 or len(set(LOOK_ICONS)) != 100:
    fails.append(f"look.json: needs 100 unique icon ids, has {len(set(LOOK_ICONS))}")
if len(LOOK_COLORS) != 12 or len(set(LOOK_COLORS)) != 12:
    fails.append("look.json: needs 12 unique colour tokens")
_svg_ok = re.compile(r'^<svg xmlns="http://www\.w3\.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">(<(path|circle|rect|line|polyline|polygon|ellipse)( (d|cx|cy|r|rx|ry|x|y|x1|y1|x2|y2|width|height|points|fill)="[-0-9a-zA-Z. ,]*")+/>)+</svg>\n$')
for i in look["icons"]:
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,23}", i["id"]) or i["category"] not in _cats or not i["label"]:
        fails.append(f"look.json icon {i['id']}: bad id, category or label")
    f = HERE / "look" / "icons" / f"{i['id']}.svg"
    if not f.is_file() or not _svg_ok.match(f.read_text()):
        fails.append(f"look/icons/{i['id']}.svg: missing, or not a plain 24px line drawing (shapes and numbers only)")
_extra = {f.stem for f in (HERE / "look" / "icons").glob("*")} - set(LOOK_ICONS)
if _extra:
    fails.append(f"look/icons: files without an id in look.json: {sorted(_extra)}")


def _lum(hx):
    c = [int(hx[k:k + 2], 16) / 255 for k in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(a, b):
    x, y = sorted((_lum(a), _lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def _mix(fg, bg, alpha):
    f = [int(fg[k:k + 2], 16) for k in (1, 3, 5)]
    g = [int(bg[k:k + 2], 16) for k in (1, 3, 5)]
    return "#" + "".join(f"{round(g[k] + (f[k] - g[k]) * alpha):02x}" for k in range(3))


for c in look["colors"]:
    for tone, key in (("dark", "tint_dark"), ("light", "tint_light")):
        hx, t = c[tone], look["badge"][key]
        if not re.fullmatch(r"#[0-9a-f]{6}", hx) or _contrast(hx, _mix(hx, t["surface"], t["alpha"])) < 4.5:
            fails.append(f"look.json colour {c['id']} {tone}: not #rrggbb or below 4.5:1 on its badge background")
if _look_schema["$defs"]["icon"]["oneOf"][0]["enum"] != LOOK_ICONS or _look_schema["$defs"]["color"]["oneOf"][0]["enum"] != LOOK_COLORS:
    fails.append("look.schema.json: icon/color enums differ from look.json")


def look_errors(defname, doc):
    v = Draft202012Validator({"$ref": f"{_look_schema['$id']}#/$defs/{defname}"}, registry=_reg)
    return list(v.iter_errors(doc))


def look_clean(name):
    return unicodedata.normalize("NFC", name).strip()


def look_default_color(name):
    h = 5381
    for b in look_clean(name).encode("utf-8"):
        h = (h * 33 + b) & 0xFFFFFFFF
    return h, LOOK_COLORS[h % len(LOOK_COLORS)]


def look_letter(name):
    for ch in look_clean(name):
        if unicodedata.category(ch)[0] in "LN":
            up = ch.upper()
            return up if len(up) == 1 else ch
    return "?"


def look_me_patch(stored, body, service):
    """PATCH /v1/me with look fields on relay or publish: (status, record after)."""
    if not isinstance(body, dict) or look_errors("me_look_patch" if service == "relay" else "publish_me_patch", body):
        return 422, stored
    after = {**stored, **body}
    if "icon" in body or "color" in body:
        after["look_by"] = "workspace"
    return 200, after


def look_meta(rec):
    return {"workspace": {k: rec[k] for k in ("name", "icon", "color")} if rec["show_on_shared_pages"] else None}


def look_local_set(local, caller, req):
    """orch look set / the dashboard: (ok, local after). An agent never overrides the person's pick."""
    if look_errors("admin_look_patch", req) or not req or (caller == "agent" and local["set_by"] == "human"):
        return False, local
    return True, {**local, **req, "set_by": caller}


def look_admin_patch(stored, body):
    """The look part of PATCH /admin/api/workspaces/<id>: (status, record after)."""
    part = {k: v for k, v in body.items() if k in ("icon", "color")}
    if not part:
        return 200, stored
    if look_errors("admin_look_patch", part):
        return 422, stored
    if stored["look_by"] == "workspace":
        return 409, stored
    return 200, {**stored, **part, "look_by": "admin"}


def look_render(name, icon, color):
    return {"icon": icon if icon in LOOK_ICONS else None,
            "color": color if color in LOOK_COLORS else look_default_color(name)[1], "letter": look_letter(name)}


def look_connect(local, remote):
    """On connect: (value written to .orch/config.toml or None, PATCH /v1/me body)."""
    if local["icon"] is None and local["color"] is None and remote["look_by"] == "admin":
        adopted = {"icon": remote["icon"], "color": remote["color"]}
        return {**adopted, "set_by": "human"}, adopted
    return None, {"icon": local["icon"], "color": local["color"]}


lvec = json.loads((HERE / "vectors" / "look-v1.json").read_text())
for case in lvec["default"]:
    if look_default_color(case["name"]) != (case["djb2_32"], case["color"]) or look_letter(case["name"]) != case["letter"]:
        fails.append(f"look vector default {case['name']!r}: got {look_default_color(case['name'])} {look_letter(case['name'])!r}")
for case in lvec["me_patch"]:
    if look_me_patch(case["stored"], case["body"], case["service"]) != (case["status"], case["after"]):
        fails.append(f"look vector me_patch {case['name']}: got {look_me_patch(case['stored'], case['body'], case['service'])}")
for case in lvec["admin_patch"]:
    if look_admin_patch(case["stored"], case["body"]) != (case["status"], case["after"]):
        fails.append(f"look vector admin_patch {case['name']}: got {look_admin_patch(case['stored'], case['body'])}")
for case in lvec["meta"]:
    if look_meta(case["record"]) != case["meta"] or look_errors("file_meta", case["meta"]):
        fails.append(f"look vector meta {case['name']}: got {look_meta(case['record'])}")
for case in lvec["shared_pages_set"]:
    ok = case["caller"] == "human" and isinstance(case["request"], bool)
    if (ok, case["request"] if ok else case["local"]) != (case["ok"], case["after"]):
        fails.append(f"look vector shared_pages_set {case['name']}: expected the core to {'allow' if case['ok'] else 'refuse'} it")
for case in lvec["local_set"]:
    if look_local_set(case["local"], case["caller"], case["request"]) != (case["ok"], case["after"]):
        fails.append(f"look vector local_set {case['name']}: got {look_local_set(case['local'], case['caller'], case['request'])}")
for case in lvec["render"]:
    got = look_render(case["name"], None if case.get("missing") else case["icon"], None if case.get("missing") else case["color"])
    if got != case["shown"]:
        fails.append(f"look vector render {case['why']}: got {got}")
for case in lvec["connect"]:
    if look_connect(case["local"], case["remote"]) != (case["write_local"], case["send"]):
        fails.append(f"look vector connect {case['name']}: got {look_connect(case['local'], case['remote'])}")
if not {200, 422}.issubset({c["status"] for c in lvec["me_patch"]}) or 409 not in {c["status"] for c in lvec["admin_patch"]}:
    fails.append("look vectors: need 200 and 422 me_patch cases and a 409 admin_patch case")

# Chat and group chat across workspaces (chat-groups.md): every vectors/chat-groups/*.json is one orch.msg/1 message
# (+ optional `context`: what the receiver already holds, and `expect`) that must pass message.schema.json,
# chat-groups.schema.json, the message rules (cg_rules) and the receiver rules (cg_receive); valid-* pass, invalid-* fail.
_msg_schema = _expand(json.loads((HERE / "message.schema.json").read_text()))
_cg_schema = _expand(json.loads((HERE / "chat-groups.schema.json").read_text()))
V_CG = Draft202012Validator(
    _cg_schema,
    registry=Registry().with_resource(_msg_schema["$id"], Resource.from_contents(_msg_schema)),
    format_checker=FormatChecker(),
)
CG_HOST_ONLY = ("group_event", "shared_ticket", "origin", "echo_of", "shared_files", "question_kind")
CG_MEMBER_ONLY = ("seen", "leave")
CG_FILE_MAX = 26214400
# task.status order: a status may repeat or move right, never left; the last column is final.
CG_TASK_RANK = {"waiting_start": 0, "waiting_approval": 1, "queued": 2, "working": 3, "done": 4, "failed": 4, "denied": 4}
CG_ALLOW_OPTIONS = ["once", "always", "no"]  # wire values; the UI shows "Allow once / Always / No"
CG_ORDER_BUFFER = 50
CG_ORDER_MAX_JUMP = 1000  # a forward jump above this over applied_seq is a gap skip
CG_ORDER_TIMEOUT_S = 600  # quiet group: skip a gap after 10 minutes
CG_MAX_OPEN_GROUPS_PER_HOST = 20
CG_CREATED_PER_HOUR = 5
# allow answer (wire) -> allow message -> group_event.approved.mode / denied
CG_ALLOW_MAP = {"once": {"allow_mode": "once", "approved_mode": "once"}, "always": {"allow_mode": "permanent", "approved_mode": "always"}, "no": {"status": "denied"}}
CG_LEGACY_WORDS = {"allow once": "once", "once": "once", "always": "always", "ignore": "no", "no": "no"}
CG_RATE = {"msgs_per_min": 20, "files_per_min": 3}


def cg_fanout_id(host, origin_id, to):
    """Id of the host's copy of a group message for one recipient: retries give the same id (relay: 200 no-op)."""
    return "m_" + hashlib.sha256(f"{host}\n{origin_id}\n{to}".encode()).hexdigest()[:16]


def cg_members(g):
    return [x.get("ws") for x in g.get("members", []) if isinstance(x, dict)]


def cg_targeted(m):
    """A host message for one member only (not a copy of a group-wide message): it carries no group.seq."""
    b = m.get("body") or {}
    return m.get("type") in ("delegate", "question") or "shared_ticket" in b


def cg_quiet(m):
    """Copies to phones are pushed only for: questions, approval_needed, member_added for no one (quiet), task done /
    failed, closed, and texts addressed to the person (body.to_person). Everything else is quiet (update.kind note)."""
    b = m.get("body") or {}
    ev = (b.get("group_event") or {}).get("kind")
    st = (b.get("task") or {}).get("status")
    return not (m.get("type") == "question" or ev in ("approval_needed", "closed") or st in ("done", "failed") or b.get("to_person") is True)


def cg_rules(m, ctx=None):
    """Message rules JSON Schema cannot express (chat-groups.md, Security G1-G8). Returns plain messages."""
    ctx = ctx or {}
    b, out = m.get("body") or {}, []
    g = b.get("group")
    if m.get("type") == "question" and b.get("allow_question") is True and b.get("options") != CG_ALLOW_OPTIONS:
        out.append("a permission (allow) question has the wire options once, always, no (UI words are only shown)")
    if not isinstance(g, dict):
        return out
    host, frm, to = g.get("host"), m.get("from"), m.get("to")
    if len(set(cg_members(g))) != len(cg_members(g)):
        out.append("group.members: each ws once")
    if host not in cg_members(g):
        out.append("group.members must include the host")
    if frm == host:
        if g.get("id") != "grp_" + str(m.get("ticket")):
            out.append("host message: group.id must be grp_ + the message's ticket (the host ticket)")
        if cg_targeted(m) and "seq" in g:
            out.append("a targeted host message (delegate, question, shared_ticket) carries no group.seq")
        if not cg_targeted(m) and "seq" not in g:
            out.append("a group-wide host message needs group.seq")
        if m.get("type") == "question" and b.get("question_kind") != "info":
            out.append("a host question to a member must be question_kind info")
        o = b.get("origin")
        hs0 = ctx.get("host_state") or {}
        if isinstance(o, dict) and str(o.get("from")).startswith("ph_") and "paired_phones" in hs0 and o["from"] not in hs0["paired_phones"]:
            out.append("origin.from is a ph_ only for a phone paired to this host workspace")
        if b.get("by") == "you":
            if b.get("via") == "phone" and not (isinstance(o, dict) and o.get("from") == b.get("phone")):
                out.append("by you via phone: origin.from must be that phone")
            if b.get("via") == "dashboard" and isinstance(o, dict) and o.get("from") != "dashboard":
                out.append("by you via dashboard: origin.from must be dashboard")
        if isinstance(b.get("task"), dict) and b["task"].get("ws") == host:
            out.append("task.ws is the member that got the task, never the host")
        if isinstance(o, dict) and (str(to).startswith("ws_") or to == "phones") and m.get("id") != cg_fanout_id(host, o["id"], to):
            out.append("host copy: id must be the fan-out id of (host, origin.id, to)")
        if to == "phones" and m.get("type") == "text" and cg_quiet(m) and (b.get("update") or {}).get("kind") != "note":
            out.append("copy to phones outside the push set must be quiet (update.kind note)")
        if str(to).startswith("ws_"):
            if to not in cg_members(g):
                out.append("host sends group messages only to members")
            if "ticket_view" in b or "shared_files" in b:
                out.append("ticket_view and shared_files never go to workspaces")
        for k in CG_MEMBER_ONLY:
            if k in b:
                out.append(f"body.{k} is for members only")
        if "shared_files" in b:
            have = {x.get("blob_id") for x in (b.get("ticket_view") or {}).get("attachments", [])}
            if not set(b["shared_files"]) <= have:
                out.append("shared_files must be blob ids of body.ticket_view.attachments")
        st = b.get("shared_ticket")
        if isinstance(st, dict):
            if st.get("ticket") != m.get("ticket"):
                out.append("shared_ticket must describe the host ticket")
            if len(json.dumps(st, separators=(",", ":"), ensure_ascii=False).encode()) > 4096:
                out.append("shared_ticket is over 4096 bytes")
    elif str(frm).startswith("ws_"):
        if to != host:
            out.append("members send group messages only to the host (only the host fans out)")
        if frm not in cg_members(g):
            out.append("sender is not a member")
        if b.get("by") != frm:
            out.append("a member's message is by the member itself (never by 'you')")
        if "seq" in g:
            out.append("only the host sets group.seq")
        for k in CG_HOST_ONLY + ("ticket_view",):
            if k in b:
                out.append(f"body.{k} is sent only by the host")
        if isinstance(b.get("task"), dict):
            if b["task"].get("ws") != frm:
                out.append("task.ws must be the sending member")
            if b["task"].get("status") == "waiting_start":
                out.append("only the host says waiting_start")
    else:
        out.append("only workspaces send body.group (phones write to the host ticket; the relay builds phone texts)")
    if m.get("type") == "allow":
        out.append("allow messages carry no body.group (the host matches them by reply_to)")
    if m.get("type") == "file" and "share" in b and int(b.get("size", 0)) > CG_FILE_MAX:
        out.append("a shared file is at most 25 MB")
    return out


def cg_receive(m, ctx):
    """What the receiver checks against what it already holds (context). Returns plain messages (= drop + log)."""
    b, out = m.get("body") or {}, []
    g = b.get("group") if isinstance(b.get("group"), dict) else None
    if g:
        if ctx.get("receiver_role") in ("member", "phone") and m.get("from") != g.get("host"):
            out.append("G3: at a member or phone, from != group.host is always dropped (also for a known group)")
        if m.get("from") == g.get("host") and cg_store(m, ctx)[1] == "new":
            # any group creation counts: an explicit `created` or the first message seen from the host
            if ctx.get("open_groups_of_host", 0) >= CG_MAX_OPEN_GROUPS_PER_HOST:
                out.append("dropped: this host already has 20 open groups here")
            recent = [t for t in ctx.get("creations_recv_s", []) if ctx.get("now_s", 0) - t < 3600]  # receive times, not created_at
            if len(recent) >= CG_CREATED_PER_HOUR:
                out.append("dropped: this host is over 5 `created` events an hour")
        # The group key is (host, id): an id held under another host is a different group, never a conflict.
        o = b.get("origin")
        if isinstance(o, dict) and [g.get("host"), g.get("id"), o.get("id")] in [list(x) for x in ctx.get("seen_origins", [])]:
            out.append("duplicate: this (host, group.id, origin.id) was already stored")
    hs = ctx.get("host_state")
    if g and hs is not None and m.get("from") != g.get("host"):
        frm = m.get("from")
        if frm not in hs.get("members", []):
            out.append("dropped: not a current member (left, removed or never added)")
        if hs.get("closed"):
            out.append("dropped: the group is closed")
        rate = hs.get("last_minute", {}).get(frm, {})
        if rate.get("msgs", 0) >= CG_RATE["msgs_per_min"] or (m.get("type") == "file" and rate.get("files", 0) >= CG_RATE["files_per_min"]):
            out.append("dropped: member over its rate limit")
        t = b.get("task")
        if isinstance(t, dict):
            if t.get("delegate") not in hs.get("delegates_sent", {}).get(frm, []):
                out.append("task.delegate is not a delegate the host sent to this member")
            old = hs.get("task_status", {}).get(t.get("delegate"))
            if old is not None:
                ro, rn = CG_TASK_RANK[old], CG_TASK_RANK.get(t.get("status"), -1)
                if rn < ro or (ro == 4 and t.get("status") != old):
                    out.append(f"task status may not go from {old} to {t.get('status')}")
    return out


def cg_parse_allow_answer(text):
    """Wire value is exact lowercase once|always|no. Old clients: trimmed, case-insensitive, single spaces:
    'Allow once', 'Always', 'Ignore', 'No'. Anything else: None (not an allow answer)."""
    if text in CG_ALLOW_OPTIONS:
        return text
    return CG_LEGACY_WORDS.get(" ".join(str(text).split()).casefold())


def cg_card(q, ctx, sender=None):
    """Phone approval card for a member's allow question: buttons only for the wire options; old wording -> 'Answer in Bank'."""
    if not (q.get("allow_question") is True and q.get("options") == CG_ALLOW_OPTIONS):
        return "answer_in_bank"
    shown = (ctx or {}).get("shown_in_group")
    if shown is not None:

        def key(r):  # same as chat_groups._ref_key: non-strings are invalid (None); stripped, lower-cased
            if not (isinstance(r, dict) and isinstance(r.get("host"), str) and isinstance(r.get("id"), str)):
                return None
            return r["host"].strip().lower(), r["id"].strip().lower()

        if key(q.get("group_ref")) is None or key(q.get("group_ref")) != key(shown):  # one group only
            return "answer_in_bank"
        members = (ctx or {}).get("group_members")
        if not isinstance(members, list) or sender not in members:  # unknown members: no buttons
            return "answer_in_bank"
    return "buttons"


def cg_store(m, ctx):
    """Receiver stores a group under (host, id). Returns (key, 'new'|'existing'); never a conflict between hosts."""
    g = m["body"]["group"]
    key = [g["host"], g["id"]]
    return key, ("existing" if key in [[k["host"], k["id"]] for k in ctx.get("known_groups", [])] else "new")


def cg_applied_after(m, ctx):
    """applied_seq after this message (see cg_order)."""
    od, seq = ctx["order"], m["body"]["group"]["seq"]
    out = cg_order(m, ctx)
    ap = od.get("applied_seq")
    if ap is None:
        ap = seq - 1  # first seen seq - 1; from_seq is display only, never trusted
    if out in ("apply", "skip_jump_and_apply"):
        return seq
    if out == "skip_gap_and_apply":
        # skip to just below the lowest buffered seq (or this one), apply the contiguous run
        have = sorted(set(od.get("buffered", [])) | {seq})
        cur = have[0]
        for x in have[1:]:
            if x == cur + 1:
                cur = x
            else:
                break
        return cur
    return ap


def cg_order(m, ctx):
    """Stateful checks (G9 task status, closed, membership) run in group.seq order (G12). Returns:
    apply | buffer | skip_jump_and_apply (jump > 1000 over applied_seq: applied_seq = seq - 1, log, apply; no per-seq gap entries, gaps are ranges) | skip_gap_and_apply (buffer of 50 full, or 10 min on the receiver clock since the earliest-received message still in the buffer (first_buffered_recv_s, recomputed after a partial flush): skip the gap,
    apply the contiguous run, late seqs below applied_seq count as old) | late_show_no_state (seq <= applied_seq:
    shown, but changes no state). Initial applied_seq = first seen seq - 1 (from_seq is never used). Time = the receiver's own clock (now_s, first_buffered_recv_s), never a message's created_at. None when no seq/context."""
    seq, od = ((m.get("body") or {}).get("group") or {}).get("seq"), ctx.get("order")
    if seq is None or od is None:
        return None
    ap = od.get("applied_seq")
    if ap is None:
        ap = seq - 1  # first seen seq - 1; from_seq is display only, never trusted
    if seq <= ap:
        return "late_show_no_state"
    if seq == ap + 1:
        return "apply"
    if seq - ap > CG_ORDER_MAX_JUMP:
        return "skip_jump_and_apply"
    if len(od.get("buffered", [])) >= CG_ORDER_BUFFER or (od.get("buffered") and od.get("now_s", 0) - od.get("first_buffered_recv_s", od.get("now_s", 0)) >= CG_ORDER_TIMEOUT_S):
        return "skip_gap_and_apply"
    return "buffer"


def cg_shown_as(m, ctx):
    """How a phone labels a copy. Only a host copy with by: you is 'You' (origin = a phone of its own account or the
    host's dashboard); any other ph_ is 'Other phone'. None when the message is not by: you."""
    b = m.get("body") or {}
    if b.get("by") != "you":
        return None
    o = b.get("origin") or {}
    g = b.get("group") or {}
    if m.get("from") != g.get("host"):
        return "Other phone"
    return "You" if o.get("from") == "dashboard" or o.get("from") in ctx.get("own_phones", []) else "Other phone"


def cg_phone_group(m, ctx):
    """True when a phone text joins the group: it goes to the host ticket and reply_to names a group copy the host
    sent to phones (the group composer always sets it). Otherwise it is a host-only note (rule G8)."""
    hs = ctx.get("host_state") or {}
    return (
        str(m.get("from")).startswith("ph_")
        and m.get("type") == "text"
        and m.get("ticket") == hs.get("ticket")
        and m.get("reply_to") in hs.get("group_copies", [])
    )


cg_dir = HERE / "vectors" / "chat-groups"
cg_files = sorted(cg_dir.glob("*.json"))
for f in cg_files:
    case = json.loads(f.read_text())
    m, ctx = case["message"], case.get("context") or {}
    errs = [e.message for e in V["message"].iter_errors(m)] + [e.message for e in V_CG.iter_errors(m)]
    errs += cg_rules(m, ctx) + cg_receive(m, ctx)
    exp = case.get("expect") or {}
    if "group_text" in exp and cg_phone_group(m, ctx) != exp["group_text"]:
        errs.append(f"phone text group_text expected {exp['group_text']}")
    if "shown_as" in exp and cg_shown_as(m, ctx) != exp["shown_as"]:
        errs.append(f"expected shown_as {exp['shown_as']}")
    if "order" in exp and cg_order(m, ctx) != exp["order"]:
        errs.append(f"expected order {exp['order']}, got {cg_order(m, ctx)}")
    if "applied_after" in exp and cg_applied_after(m, ctx) != exp["applied_after"]:
        errs.append(f"expected applied_seq {exp['applied_after']}, got {cg_applied_after(m, ctx)}")
    if "stored_as" in exp and (cg_store(m, ctx)[0] != exp["stored_as"] or cg_store(m, ctx)[1] != exp.get("store", "new")):
        errs.append(f"expected store {exp['stored_as']} {exp.get('store', 'new')}, got {cg_store(m, ctx)}")
    if "card" in exp and cg_card(m["body"], ctx, m.get("from")) != exp["card"]:
        errs.append(f"expected card {exp['card']}")
    for ans, want_ in (exp.get("parse") or {}).items():
        if cg_parse_allow_answer(ans) != want_:
            errs.append(f"parse {ans!r} expected {want_}")
    if "map" in exp:
        mp = exp["map"]
        if CG_ALLOW_MAP.get(cg_parse_allow_answer(mp["answer"])) != {k: v for k, v in mp.items() if k != "answer"}:
            errs.append("allow answer mapping differs from the table")
        ge = (m["body"].get("group_event") or {})
        if ge.get("kind") == "approved" and ge.get("mode") != mp.get("approved_mode"):
            errs.append("approved.mode must be the mapped value")
        if ge.get("kind") == "denied" and mp.get("status") != "denied":
            errs.append("denied event needs answer no")
    want = f.name.startswith("valid-")
    if bool(errs) == want:
        fails.append(f"vectors/chat-groups/{f.name}: expected {'valid' if want else 'invalid'}, got {errs[0] if errs else 'valid'}")
for prefix in ("valid-", "invalid-"):
    if not any(f.name.startswith(prefix) for f in cg_files):
        fails.append(f"vectors/chat-groups: needs at least one {prefix}* vector")

for _fn in KINDS.values():
    _fn()
if fails:
    print("\n".join("FAIL " + f for f in fails))
    sys.exit(1)
print("contracts: ALL OK")
