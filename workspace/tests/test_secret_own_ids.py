"""ORCH-66 (#1015, #1022) after two security reviews.

- orch's own report text never puts a ticket or run id where a label goes (an id followed by a colon), so a
  random id that spells pw, pin or key is never read as a password label; the scanner itself has no
  exemption for ids.
- Pictures get the full rules on every byte, as before PR 1065: no input from the reviews gets through.
Every input from review rounds 1 and 2 is a refused test here."""

import random
import zlib

import pytest

from orch import diag_report, phone_view, runs, secretscan, tickets
from orch.diag_checks import dead_lock_holder, no_heartbeat, run_gone_ticket_working, waiting_for_permission
from orch.errors import Refused

TOKEN = "ghp_" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0"  # built at run time
SECRET = "Hunter2!Strong"
PLAIN = f"password: {SECRET}\nDB_PASS={SECRET}".encode()
RNG_SEED = 1015  # fixed, so CI never flakes; the ids are still drawn from the real alphabets


# ---------------------------------------------------------------- own ids in orch's report text


def _ids(rng: random.Random, n: int, prefix: str, size: int, alphabet: str) -> list[str]:
    return [prefix + "".join(rng.choice(alphabet) for _ in range(size)) for _ in range(n)]


def _evidence(tid: str, rid: str) -> list[str]:
    """The lines the real checks write about one ticket and its run."""
    now = runs._parse("2026-11-16T22:30:00Z")
    gone = {
        "now": now,
        "collected": {
            "tickets": {"data": {"tickets": {tid: {"status": "active", "age_s": 1800}}}},
            "runs": {"data": {"runs": {tid: {"run": rid, "process": "dead", "pid": 4242, "pid_started": 1}}}},
            "locks": {"data": {"locks": []}},
        },
    }
    rec = {
        "run": rid,
        "process": "alive",
        "heartbeat_age_s": 3600,
        "live_state": "attention",
        "live_since": "2026-11-16T22:00:00Z",
    }
    alive = {"now": now, "collected": {"runs": {"data": {"runs": {tid: rec}}}}}
    working = {"now": now, "collected": {"runs": {"data": {"runs": {tid: {**rec, "live_state": "working"}}}}}}
    out = []
    for mod, snap in (
        (run_gone_ticket_working, gone),
        (dead_lock_holder, gone),
        (no_heartbeat, working),
        (waiting_for_permission, alive),
    ):
        out += mod.check(snap)["evidence"]
    return out


def test_the_checks_write_ids_in_label_position_nowhere():
    lines = _evidence("t_abc1pw", "r_ab1pw000")
    assert len(lines) == 4 and all("t_abc1pw" in ln for ln in lines), lines
    assert all(secretscan.find(ln) == [] for ln in lines), lines


def _summary(pairs: list[tuple[str, str]]) -> str:
    checks = [
        {"name": "real-writers", "verdict": "problem", "fact": "lines from the real checks", "evidence": ev}
        for ev in (_evidence(t, r) for t, r in pairs)
    ]
    timeline = [
        {"at": "2026-11-16T22:30:00.000Z", "source": "cli", "ev": "run.start", "ticket": t, "run": r}
        for t, r in pairs
    ]
    t0, r0 = pairs[0]
    return diag_report.summary(
        f"r-1116-2230-{t0}-2", {"ticket": t0, "run": r0}, 0, 60, "the run started", checks, [], timeline,
        None, None, [], False,
    )  # fmt: skip


def test_20000_random_ticket_ids_in_a_report_summary_never_trip_the_check(tmp_path):
    rng = random.Random(RNG_SEED)
    tids = _ids(rng, 20000, "t_", 6, tickets._ALPHABET)
    rids = _ids(rng, 20000, "r_", 8, runs._ALPHA)
    pairs = list(zip(tids, rids, strict=True))
    for i in range(0, 20000, 50):  # 400 real summaries, 50 ticket and 50 run ids each
        text = _summary(pairs[i : i + 50])
        assert secretscan.find(text) == [], text
        secretscan.refuse_if_secret(text.encode(), "report file SUMMARY.md", tmp_path)
        secretscan.refuse_if_secret_in(tmp_path, {"summary": text}, "report")


@pytest.mark.parametrize(
    "text",
    [
        "password: hunter2",
        "t_abc1pw password: hunter2",  # an id next to a real label
        f"t_abc1pw: {TOKEN}",
        "t_secret: hunter2",
        "r_password: hunter2",
        "t_dbpass= hunter2",
        "t_apikey: hunter2",
        "r_mytoken1: hunter2",
        "T_ABC1PW: hunter2",
        "x_abc1pw: hunter2",
        # review round 1 (Low): short secret words in id-shaped names
        "t_pw1234: hunter2",
        "t_pin123: 1234",
        "t_pass12: hunter2",
        f"t_pwd123: {SECRET}",
        "r_sshkey12: x9q2",
        "r_authkey1: hunter2",
        f"t_abc1pw: {SECRET}",
        "t_abc1pw= hunter2",
        # review round 2 (Low): a passphrase that looks like prose
        "t_pw1234: correct horse battery staple",
        "t_pin123: Summer sunshine",
        "t_pw1234=correct horse battery",
    ],
)
def test_a_secret_after_an_id_shaped_name_is_refused(text, tmp_path):
    assert secretscan.find(text) != []
    with pytest.raises(Refused):
        secretscan.refuse_if_secret_in(tmp_path, {"summary": text}, "report")
    with pytest.raises(Refused):
        secretscan.refuse_if_secret(text.encode(), "report file SUMMARY.md", tmp_path)


# ---------------------------------------------------------------- pictures: every byte, full rules


def _chunk(kind: bytes, body: bytes) -> bytes:
    return len(body).to_bytes(4, "big") + kind + body + zlib.crc32(kind + body).to_bytes(4, "big")


def _screenshot(*idat: bytes, before: bytes = b"", after: bytes = b"") -> bytes:
    """A plain 64x64 RGB picture (a clean screenshot): IHDR, `before` chunks, its IDAT (or the given IDAT
    payloads), `after` chunks, IEND."""
    rng = random.Random(7)
    rows = b"".join(
        b"\x00" + bytes(rng.choice((0x20, 0x21, 0xF0, 0xFF)) for _ in range(64 * 3)) for _ in range(64)
    )
    payloads = idat or (zlib.compress(rows, 6),)
    ihdr = _chunk(b"IHDR", (64).to_bytes(4, "big") * 2 + bytes([8, 2, 0, 0, 0]))
    body = b"".join(_chunk(b"IDAT", p) for p in payloads)
    return b"\x89PNG\r\n\x1a\n" + ihdr + before + body + after + _chunk(b"IEND", b"")


def _stored(data: bytes, block: int = 65535) -> bytes:
    """A valid zlib stream of stored (uncompressed) deflate blocks of at most `block` bytes each."""
    parts = [data[i : i + block] for i in range(0, len(data), block)] or [b""]
    out = b"\x78\x01"
    for n, p in enumerate(parts):
        out += bytes([1 if n == len(parts) - 1 else 0]) + len(p).to_bytes(2, "little")
        out += (len(p) ^ 0xFFFF).to_bytes(2, "little") + p
    return out + zlib.adler32(data).to_bytes(4, "big")


FULLWIDTH = "ｐａｓｓｗｏｒｄ" + f": {SECRET}"  # NFKC makes it a plain label


def _hidden_in_a_png() -> list[tuple[str, bytes]]:
    """A labelled value hidden in a clean screenshot, by every method of review rounds 1 and 2."""
    whole = _stored(PLAIN)
    half = len(whole) // 2
    return [
        ("stored block", _screenshot(_stored(PLAIN))),
        ("level 0", _screenshot(zlib.compress(PLAIN, 0))),
        ("utf-16 stored", _screenshot(_stored(PLAIN.decode().encode("utf-16-le")))),
        ("split over two IDAT chunks", _screenshot(whole[:half], whole[half:])),
        ("7-byte stored blocks", _screenshot(_stored(PLAIN, 7))),
        ("fullwidth label", _screenshot(_stored(FULLWIDTH.encode()))),
        ("short label", _screenshot(_stored(b"\x01pw=1234\x01"))),
        ("PLTE", _screenshot(before=_chunk(b"PLTE", (b"\x00\x01\x02" + PLAIN).ljust(51, b"\x00")))),
        ("tRNS", _screenshot(after=_chunk(b"tRNS", PLAIN))),
        ("pHYs", _screenshot(after=_chunk(b"pHYs", PLAIN))),
        ("gAMA", _screenshot(after=_chunk(b"gAMA", PLAIN))),
        ("tEXt", _screenshot(after=_chunk(b"tEXt", b"Comment\x00" + PLAIN))),
        ("token in IDAT", _screenshot(_stored(b" " + TOKEN.encode() + b" "))),
        ("after IEND", _screenshot() + PLAIN),
    ]


@pytest.mark.parametrize("how,pic", _hidden_in_a_png(), ids=[h for h, _ in _hidden_in_a_png()])
def test_a_labelled_value_hidden_in_a_screenshot_is_refused(how, pic, tmp_path):
    assert phone_view._scan_texts(pic, "shot.png")[0] in ("secret", "unknown"), how  # never sent to the phone
    with pytest.raises(Refused):
        secretscan.refuse_if_secret(pic, "added file shot.png", tmp_path)


def _jpeg(*segments: bytes, scan: bytes = b"\x12\x34") -> bytes:
    out = b"\xff\xd8"
    for marker, payload in segments:
        out += b"\xff" + bytes([marker]) + (len(payload) + 2).to_bytes(2, "big") + payload
    return out + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00" + scan + b"\xff\xd9"


APP0 = (0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")


def _split(data: bytes, sep: bytes, n: int = 7) -> bytes:
    return sep.join(data[i : i + n] for i in range(0, len(data), n))


@pytest.mark.parametrize(
    "how,scan",
    [
        ("plaintext as scan data", PLAIN),
        ("split by RST markers", _split(PLAIN, b"\xff\xd0")),
        ("split by other RST markers", _split(PLAIN, b"\xff\xd7")),
        ("split by stuffed FF 00", _split(PLAIN, b"\xff\x00")),
        ("fullwidth label", FULLWIDTH.encode()),
    ],
)
def test_a_labelled_value_in_a_photo_is_refused(how, scan):
    assert phone_view._photo_verdict(_jpeg(APP0, scan=b"\x12\x34" + scan)) == "secret", how
