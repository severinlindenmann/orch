"""#1015 and #1022: the secret check never takes orch's own ids (ticket, run, report folder) or the compressed
data of a picture for a password, and real secrets are still caught."""

import random
import zlib

import pytest

from orch import diag_report, phone_results, phone_view, runs, secretscan, tickets
from orch.errors import Refused

TOKEN = "ghp_" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0"  # built at run time
RNG_SEED = 1015  # fixed, so CI never flakes; the ids are still drawn from the real alphabets


def _ids(rng: random.Random, n: int, prefix: str, size: int, alphabet: str) -> list[str]:
    return [prefix + "".join(rng.choice(alphabet) for _ in range(size)) for _ in range(n)]


def _summary(tids: list[str], rids: list[str]) -> str:
    """A real report summary (diag_report.summary) that names every id the way orch writes them: the scope,
    the gone-run check line '<id>: Working for 1800 s, ...', the timeline lines and the report ref."""
    checks = [
        {
            "name": "run_gone_ticket_working",
            "verdict": "problem",
            "fact": "tickets say Working but no helper runs",
            "evidence": [f"{t}: Working for 1800 s, the run ended" for t in tids[i : i + 5]],
        }
        for i in range(0, len(tids), 5)
    ]
    timeline = [
        {
            "at": "2026-11-16T22:30:00.000Z",
            "source": "cli",
            "lvl": "info",
            "ev": "run.start",
            "ticket": t,
            "run": r,
        }
        for t, r in zip(tids, rids, strict=True)
    ]
    ref = f"r-1116-2230-{tids[0]}-2"
    return diag_report.summary(
        ref, {"ticket": tids[0], "run": rids[0]}, 0, 60, "the run started", checks, [], timeline,
        f"{tids[0]}: the board froze", None, [], False,
    )  # fmt: skip


def test_20000_random_ticket_ids_in_a_report_summary_never_trip_the_check(tmp_path):
    rng = random.Random(RNG_SEED)
    tids = _ids(rng, 20000, "t_", 6, tickets._ALPHABET)
    rids = _ids(rng, 20000, "r_", 8, runs._ALPHA)
    for i in range(0, 20000, 50):  # 400 real summaries, 50 ticket and 50 run ids each
        text = _summary(tids[i : i + 50], rids[i : i + 50])
        assert secretscan.find(text) == [], text
        secretscan.refuse_if_secret(text.encode(), "report file SUMMARY.md", tmp_path)
        secretscan.refuse_if_secret_in(tmp_path, {"summary": text}, "report")


@pytest.mark.parametrize(
    "tid", ["t_abc1pw", "t_4pin56", "t_9key00", "t_ab0sid", "t_otp123", "t_12pwd3", "t_0x1sig"]
)
def test_ids_that_used_to_read_as_a_password_label_pass(tid, tmp_path):
    """Each of these read as a password label before the fix (pw, pin, key, sid, otp, pwd, sig as a word)."""
    assert phone_view.secret_name(tid.replace("t_", "x_")), "the plain name rule still knows these words"
    line = f"- {tid}: Working for 1800 s, the run ended"
    assert secretscan.find(line) == []
    assert secretscan.find(f"# Diagnostic report r-1116-2230-{tid}-2: made at 22:30") == []
    assert secretscan.find(f"see r_{tid[2:]}xy: done at 22:30, see the log") == []  # a run id
    secretscan.refuse_if_secret_in(tmp_path, {"note": f"{tid}= the ticket I meant"}, "evidence", verb="saved")


@pytest.mark.parametrize(
    "text",
    [
        "password: hunter2",
        "t_abc1pw password: hunter2",  # an id next to a real label
        "t_abc1pw: ok\npassword: hunter2",
        f"t_abc1pw: {TOKEN}",  # a real token after an id
        "t_secret: hunter2",  # id-shaped names that spell a long secret word stay secret names
        "r_password: hunter2",
        "t_dbpass= hunter2",
        "t_apikey: hunter2",
        "r_mytoken1: hunter2",
        "T_ABC1PW: hunter2",  # not the exact id shape (capitals): the full rule
        "t_abc1pwd: hunter2",  # seven characters: not a ticket id
        "x_abc1pw: hunter2",
        # an own id passes only before prose (security review of PR 1065, Low)
        "t_pw1234: hunter2",
        "t_pin123: 1234",
        "t_pass12: hunter2",
        "t_pwd123: Hunter2!Strong",
        "r_sshkey12: x9q2",
        "r_authkey1: hunter2",
        "t_abc1pw: Hunter2!Strong",
        "t_abc1pw= hunter2",
        "t_abc1pw: hunter2 2026",  # two words, but the first is no plain word
    ],
)
def test_real_secrets_are_still_caught(text, tmp_path):
    assert secretscan.find(text) != []
    with pytest.raises(Refused):
        secretscan.refuse_if_secret_in(tmp_path, {"summary": text}, "report")
    with pytest.raises(Refused):
        secretscan.refuse_if_secret(text.encode(), "report file SUMMARY.md", tmp_path)


def test_a_line_full_of_ids_stays_fast():
    """Every own id before prose is looked at a bounded distance, never to the end of its line."""
    import time

    line = "t_abc1pw: Working " * 20000 + "password: hunter2"
    t0 = time.monotonic()
    assert secretscan.find(line) != []  # the real label at the end is still found
    assert time.monotonic() - t0 < 5


def _chunk(kind: bytes, body: bytes) -> bytes:
    return len(body).to_bytes(4, "big") + kind + body + zlib.crc32(kind + body).to_bytes(4, "big")


def _png(*chunks: bytes) -> bytes:
    ihdr = _chunk(b"IHDR", (1).to_bytes(4, "big") * 2 + bytes([8, 2, 0, 0, 0]))
    return b"\x89PNG\r\n\x1a\n" + ihdr + b"".join(chunks) + _chunk(b"IEND", b"")


# chance letters in compressed pixel data: label-like runs, each shorter than phone_view.PICTURE_RUN
PIXELS = b"\x13\x88PW=a\x9a\x01q\xf0\nkey:7\xfe\x02z\x99\npwd=x7\x00\x11"
PLAIN = b"password: Hunter2!Strong\nDB_PASS=Hunter2!Strong"


def test_picture_data_is_not_read_as_text(tmp_path):
    pic = _png(_chunk(b"IDAT", PIXELS * 50))
    assert phone_view._scan_texts(pic, "shot.png")[0] == "ok"
    secretscan.refuse_if_secret(pic, "report file screen/page.png", tmp_path)


def _plaintext_pictures() -> list[tuple[str, bytes]]:
    """Security review of PR 1065 (High, Medium): labelled plaintext put into a picture as it is."""
    stored = zlib.compress(PLAIN, 0)  # level 0: a stored deflate block, the text sits in the file verbatim
    plte = (b"\x00\x01\x02" + PLAIN).ljust(51, b"\x00")  # a multiple of 3: a valid palette length
    return [
        ("stored.png", _png(_chunk(b"IDAT", PIXELS + stored + PIXELS))),
        ("utf16.png", _png(_chunk(b"IDAT", PIXELS + zlib.compress(PLAIN.decode().encode("utf-16-le"), 0)))),
        ("plte.png", _png(_chunk(b"PLTE", plte), _chunk(b"IDAT", PIXELS))),
        ("trns.png", _png(_chunk(b"tRNS", PLAIN), _chunk(b"IDAT", PIXELS))),
        ("phys.png", _png(_chunk(b"pHYs", PLAIN), _chunk(b"IDAT", PIXELS))),  # wrong length: no pHYs
        ("gama.png", _png(_chunk(b"gAMA", PLAIN), _chunk(b"IDAT", PIXELS))),
    ]


@pytest.mark.parametrize("name,pic", _plaintext_pictures())
def test_labelled_plaintext_in_a_picture_is_refused(name, pic, tmp_path):
    assert phone_view._scan_texts(pic, name)[0] in ("secret", "unknown")  # never sent to the phone
    with pytest.raises(Refused):
        secretscan.refuse_if_secret(pic, f"added file {name}", tmp_path)


def test_spec_lengths_of_the_small_png_chunks():
    assert phone_view._image_clean(_png(_chunk(b"pHYs", b"\x00" * 9), _chunk(b"IDAT", PIXELS)))
    for kind, body in [(b"pHYs", b"\x00" * 10), (b"gAMA", b"\x00" * 5), (b"sRGB", b"\x00\x00"),
                       (b"cHRM", b"\x00" * 33), (b"PLTE", b"\x00" * 4), (b"PLTE", b"\x00" * 771),
                       (b"tRNS", b"\x00" * 257)]:  # fmt: skip
        assert not phone_view._image_clean(_png(_chunk(kind, body), _chunk(b"IDAT", PIXELS))), kind


def test_labelled_plaintext_as_jpeg_scan_data_is_refused():
    """ASCII never holds 0xFF, so the walk takes it as scan data (security review of PR 1065, Medium)."""
    assert phone_view._photo_verdict(_jpeg(APP0, entropy=PLAIN)) == "secret"
    assert (
        phone_view._photo_verdict(_jpeg(APP0, entropy=b"\x12\x34" + PLAIN.replace(b"\n", b"\x00")))
        == "secret"
    )


def test_a_token_in_picture_data_is_still_caught(tmp_path):
    pic = _png(_chunk(b"IDAT", PIXELS + b" " + TOKEN.encode() + b" " + PIXELS))
    assert phone_view._scan_texts(pic, "shot.png")[0] == "secret"
    with pytest.raises(Refused, match="GitHub token"):
        secretscan.refuse_if_secret(pic, "added file shot.png", tmp_path)
    entropy = (b"\x12 " + TOKEN.encode() + b" \x34") * 2
    assert phone_view._photo_verdict(_jpeg(APP0, entropy=entropy)) == "secret"


def test_text_in_a_picture_is_still_caught(tmp_path):
    text_chunk = _png(_chunk(b"IDAT", PIXELS), _chunk(b"tEXt", b"Comment\x00" + TOKEN.encode()))
    assert phone_view._scan_texts(text_chunk, "shot.png")[0] == "unknown"  # not sent to the phone
    with pytest.raises(Refused):  # read as text again: every chance label in it counts too
        secretscan.refuse_if_secret(text_chunk, "added file shot.png", tmp_path)
    after_end = _png(_chunk(b"IDAT", b"\x13\x88\x9a")) + TOKEN.encode()
    with pytest.raises(Refused, match="GitHub token"):
        secretscan.refuse_if_secret(after_end, "added file shot.png", tmp_path)
    renamed = b"password: hunter2\n"  # a text file named .png is read as text
    with pytest.raises(Refused):
        secretscan.refuse_if_secret(renamed, "added file shot.png", tmp_path)


def test_a_stored_key_in_picture_data_is_still_caught(tmp_path, monkeypatch):
    class Hider:
        def hide_text(self, t):
            return t.replace("Zq7StoredValue9", "[hidden]")

        def hide_bytes(self, b):
            return b.replace(b"Zq7StoredValue9", b"[hidden]")

    monkeypatch.setattr(phone_results, "value_hider", lambda root: Hider())
    pic = _png(_chunk(b"IDAT", PIXELS + b"Zq7StoredValue9" + PIXELS))
    with pytest.raises(Refused, match="stored keys"):
        secretscan.refuse_if_secret(pic, "added file shot.png", tmp_path)
    assert phone_view._holds_stored_value(tmp_path, pic, phone_view._scan_texts(pic, "shot.png")[1])


def _jpeg(*segments: bytes, entropy: bytes = b"\x12\x34") -> bytes:
    out = b"\xff\xd8"
    for marker, payload in segments:
        out += b"\xff" + bytes([marker]) + (len(payload) + 2).to_bytes(2, "big") + payload
    return out + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00" + entropy + b"\xff\xd9"


APP0 = (0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")


def test_photo_picture_data_with_chance_labels_passes_but_its_metadata_is_read():
    entropy = PIXELS.replace(b"\xff", b"\xfe").replace(b"\x00", b"\x01") * 50
    assert phone_view._photo_verdict(_jpeg(APP0, entropy=entropy)) == "ok"
    exif = (0xE1, b"Exif\x00\x00" + TOKEN.encode())
    assert phone_view._photo_verdict(_jpeg(APP0, exif, entropy=entropy)) == "secret"
    table = (0xDB, (" " + TOKEN).encode("utf-16-le"))
    assert phone_view._photo_verdict(_jpeg(APP0, table, entropy=entropy)) == "secret"
