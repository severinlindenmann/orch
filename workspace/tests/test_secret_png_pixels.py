"""ORCH-303 (#1022, #1101): plain screenshots pass the secret check, hidden text in a picture is refused.

Compressed pixel data spells a short password label by chance in about half of all screenshots. pngpixels
proves which bytes are only Huffman-coded deflate data; the label rules skip just those bytes, the token
patterns and the stored-key check read every byte, and any doubt about the picture scans every byte with every
rule. The ORCH-66 review inputs live in test_secret_own_ids.py and still run; the inputs that aim at this
proof (a stored block next to pixels, data after the stream, a second IDAT run, ...) are here."""

import random
import time
import zlib

import pytest

from orch import phone_view, pngpixels, publish, secretscan
from orch.errors import Refused

SECRET = "Hunter2!Strong"
PLAIN = f"password: {SECRET}\nDB_PASS={SECRET}".encode()
TOKEN = "ghp_" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0"  # built at run time
SEED = 1022  # fixed, so CI never flakes


def _chunk(kind: bytes, body: bytes) -> bytes:
    return len(body).to_bytes(4, "big") + kind + body + zlib.crc32(kind + body).to_bytes(4, "big")


def _ihdr(w: int, h: int, depth: int = 8, color: int = 2, interlace: int = 0) -> bytes:
    return _chunk(
        b"IHDR", w.to_bytes(4, "big") + h.to_bytes(4, "big") + bytes([depth, color, 0, 0, interlace])
    )


def _rows(rng: random.Random, w: int, h: int, bpp: int = 3, noise: float = 1.0) -> bytes:
    """Filtered scanlines: each pixel new and random with chance `noise`, else the one before (flat areas)."""
    out = bytearray()
    for _ in range(h):
        out.append(rng.randrange(5))
        px = rng.randbytes(bpp)
        for _ in range(w):
            if rng.random() < noise:
                px = rng.randbytes(bpp)
            out += px
    return bytes(out)


def _png(
    stream: bytes, w: int, h: int, *, split: int = 8192, ihdr: bytes | None = None, before=b"", after=b""
):
    idat = b"".join(_chunk(b"IDAT", stream[i : i + split]) for i in range(0, len(stream), split))
    return b"\x89PNG\r\n\x1a\n" + (ihdr or _ihdr(w, h)) + before + idat + after + _chunk(b"IEND", b"")


def _flushed(
    data: bytes, level: int = 6, strategy: int = zlib.Z_DEFAULT_STRATEGY, every: int = 50000
) -> bytes:
    """A zlib stream with a sync flush every `every` bytes (each writes an empty stored block, as browsers do)
    and a final empty fixed block."""
    c = zlib.compressobj(level, zlib.DEFLATED, 15, 9, strategy)
    out = b""
    for i in range(0, len(data), every):
        out += c.compress(data[i : i + every]) + c.flush(zlib.Z_SYNC_FLUSH)
    return out + c.flush()


def screenshot(seed: int, w: int = 680, h: int = 340, noise: float = 0.35) -> bytes:
    """A plain picture of about 300 KB: flat areas and noisy ones, so its compressed bytes are close to
    random (the old rules held back about half of such pictures)."""
    rng = random.Random(seed)
    return _png(_flushed(_rows(rng, w, h, noise=noise)), w, h)


def _old_rules_flag(pic: bytes) -> bool:
    """The rules before ORCH-303 on the Latin-1 reading (one of the readings the file check uses)."""
    return bool(secretscan.find(pic.decode("latin-1"), None, strict=False))


def _refused(pic: bytes, tmp_path) -> bool:
    try:
        secretscan.refuse_if_secret(pic, "added file shot.png", tmp_path)
    except Refused:
        return True
    return False


def _stored(data: bytes) -> bytes:
    """Raw deflate stored blocks (not final) for `data`."""
    out = b""
    for i in range(0, len(data), 65535):
        p = data[i : i + 65535]
        out += b"\x00" + len(p).to_bytes(2, "little") + (len(p) ^ 0xFFFF).to_bytes(2, "little") + p
    return out


def _raw(data: bytes, level: int = 6) -> bytes:
    c = zlib.compressobj(level, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush(zlib.Z_SYNC_FLUSH)  # ends on a byte boundary, not final


def _zlib(raw_blocks: bytes, data: bytes) -> bytes:
    """A zlib stream from raw (non-final) deflate blocks plus a final empty fixed block, with the checksum."""
    return b"\x78\x9c" + raw_blocks + b"\x03\x00" + zlib.adler32(data).to_bytes(4, "big")


# ---------------------------------------------------------------- plain pictures pass


def test_plain_screenshots_pass_every_check(tmp_path):
    pics = [screenshot(SEED + i) for i in range(16)]
    assert all(250_000 < len(p) < 350_000 for p in pics)
    flagged_before = sum(_old_rules_flag(p) for p in pics)
    assert flagged_before >= 4  # the test means something: the old rules held many of them back
    for i, pic in enumerate(pics):
        assert pngpixels.pixel_spans(pic), i
        assert not _refused(pic, tmp_path), i
        assert phone_view._scan_texts(pic, "shot.png")[0] == "ok", i
        assert not phone_view._has_secret(pic), i
        publish.scan_files(tmp_path, [("shot.png", pic)])


def test_screenshot_like_pictures_of_every_kind_get_a_proof():
    rng = random.Random(SEED)
    w, h = 300, 120
    rows = _rows(rng, w, h, noise=0.05)
    cases = {
        "level 9": zlib.compress(rows, 9),
        "level 1": zlib.compress(rows, 1),
        "fixed codes": _flushed(rows, 6, zlib.Z_FIXED),
        "huffman only": _flushed(rows, 6, zlib.Z_HUFFMAN_ONLY),
        "rle": _flushed(rows, 6, zlib.Z_RLE),
        "many flushes": _flushed(rows, 6, every=997),
    }
    for how, stream in cases.items():
        for split in (61, 997, 8192, 1 << 20):
            pic = _png(stream, w, h, split=split)
            spans = pngpixels.pixel_spans(pic)
            assert spans, (how, split)
            assert sum(b - a for a, b in spans) > 0.8 * len(stream), (how, split)
    # palette, grey 1-bit, 16-bit RGBA and an interlaced picture: the IHDR size is computed right
    for depth, color, bpp_bits in ((8, 3, 8), (1, 0, 1), (16, 6, 64)):
        rowb = (w * bpp_bits + 7) // 8
        data = b"".join(b"\x00" + bytes(rng.choice(b"\x00\x11\x7f") for _ in range(rowb)) for _ in range(h))
        pic = _png(zlib.compress(data), w, h, ihdr=_ihdr(w, h, depth, color))
        assert pngpixels.pixel_spans(pic), (depth, color)
    size = pngpixels._pixel_bytes(_ihdr(w, h, interlace=1)[8:-4])
    pic = _png(
        zlib.compress(bytes(rng.choice(b"\x00\x01\x02") for _ in range(size))),
        w,
        h,
        ihdr=_ihdr(w, h, interlace=1),
    )
    assert pngpixels.pixel_spans(pic)


def test_a_300_kb_picture_is_checked_quickly(tmp_path):
    pic = screenshot(SEED)
    t = time.perf_counter()
    assert pngpixels.pixel_spans(pic)
    proof = time.perf_counter() - t
    t = time.perf_counter()
    assert not _refused(pic, tmp_path)
    whole = time.perf_counter() - t
    assert proof < 1.5 and whole < 6, (proof, whole)  # about 0.1 s and 1 s on a laptop; CI runners are slower


# ---------------------------------------------------------------- readable text in a picture is still refused


def _pixels(seed: int = SEED, w: int = 200, h: int = 60) -> tuple[bytes, int, int]:
    return _rows(random.Random(seed), w, h, noise=0.35), w, h


def _hidden_next_to_pixels() -> list[tuple[str, bytes]]:
    rows, w, h = _pixels()
    good = zlib.compress(rows, 6)
    half = len(rows) // 2
    mixed = _zlib(_raw(rows[:half]) + _stored(PLAIN), rows[:half] + PLAIN)
    longer = rows[: half - len(PLAIN)] + PLAIN
    return [
        (
            "stored block between pixel blocks",
            _png(
                _zlib(
                    _raw(rows[:half]) + _stored(PLAIN) + _raw(rows[half:]), rows[:half] + PLAIN + rows[half:]
                ),
                w,
                h,
            ),
        ),
        ("stored block at the end, size off", _png(mixed, w, h)),
        (
            "stored block, size right",
            _png(_zlib(_raw(longer[: -len(PLAIN)]) + _stored(PLAIN), longer), w, h // 2),
        ),
        ("after the stream in IDAT", _png(good + PLAIN, w, h)),
        ("a second zlib stream", _png(good + zlib.compress(PLAIN, 0), w, h)),
        (
            "a second IDAT run",
            _png(
                good,
                w,
                h,
                after=_chunk(b"tIME", b"\x07\xea\x0b\x11\x00\x00\x00") + _chunk(b"IDAT", _stored(PLAIN)),
            ),
        ),
        ("tEXt next to proven pixels", _png(good, w, h, before=_chunk(b"tEXt", b"Comment\x00" + PLAIN))),
        ("unknown chunk next to proven pixels", _png(good, w, h, after=_chunk(b"prVt", PLAIN))),
        ("utf-16 in a chunk", _png(good, w, h, after=_chunk(b"prVt", PLAIN.decode().encode("utf-16-le")))),
        ("short label in a chunk", _png(good, w, h, after=_chunk(b"prVt", b"\x01pw=1234\x01"))),
        ("after IEND", _png(good, w, h) + PLAIN),
        (
            "bad checksum, text after",
            _png(good[:-4] + b"\x00\x00\x00\x00", w, h, after=_chunk(b"prVt", PLAIN)),
        ),
        (
            "token in a stored block",
            _png(_zlib(_raw(rows) + _stored(TOKEN.encode()), rows + TOKEN.encode()), w, h),
        ),
        ("token in a chunk", _png(good, w, h, after=_chunk(b"prVt", b" " + TOKEN.encode() + b" "))),
        ("level 0 picture", _png(zlib.compress(PLAIN + rows[len(PLAIN) :], 0), w, h)),
    ]


@pytest.mark.parametrize("how,pic", _hidden_next_to_pixels(), ids=[h for h, _ in _hidden_next_to_pixels()])
def test_readable_text_next_to_proven_pixels_is_refused(how, pic, tmp_path):
    assert _refused(pic, tmp_path), how
    assert phone_view._scan_texts(pic, "shot.png")[0] in ("secret", "unknown"), how
    with pytest.raises(Refused):
        publish.scan_files(tmp_path, [("shot.png", pic)])


def test_a_stored_block_with_bytes_gives_no_proof():
    rows, w, h = _pixels()
    stream = _zlib(_raw(rows[:-10]) + _stored(rows[-10:]), rows)
    assert zlib.decompress(stream) == rows
    assert pngpixels.pixel_spans(_png(stream, w, h)) == []
    assert pngpixels.pixel_spans(_png(_zlib(_raw(rows) + _stored(b""), rows), w, h))  # an empty one is fine


def test_wrong_pixel_count_or_a_preset_dictionary_gives_no_proof():
    rows, w, h = _pixels()
    good = zlib.compress(rows)
    assert pngpixels.pixel_spans(_png(b"\x78\xbb" + good[2:], w, h)) == []
    assert pngpixels.pixel_spans(_png(zlib.compress(rows), w, h))
    assert pngpixels.pixel_spans(_png(zlib.compress(rows), w, h + 1)) == []
    assert pngpixels.pixel_spans(_png(zlib.compress(rows + b"\x00"), w, h)) == []


def test_the_token_patterns_and_stored_keys_still_read_the_pixel_bytes(tmp_path):
    """Pixel bytes skip only the label rules: the raw file still goes through find() with labels=False, which
    keeps the token patterns and the stored-key check."""
    pic = screenshot(SEED)
    (view, labels_view), (raw, labels_raw) = secretscan.passes(pic)
    assert raw == pic and labels_view and not labels_raw and len(view) < len(pic) // 10
    assert secretscan.find(f"x {TOKEN} y", None, labels=False)
    assert not secretscan.find(f"password: {SECRET}", None, labels=False)
    assert secretscan.find(f"password: {SECRET}", None)
    assert phone_view._scrubbed(f"x {TOKEN} y".encode(), False)
    assert not phone_view._scrubbed(PLAIN, False)
    assert secretscan.passes(PLAIN) == [(PLAIN, True)]


def test_a_label_does_not_join_across_a_pixel_run():
    for codec in ("utf-8", "latin-1", "utf-16-le", "utf-16-be"):
        for pad in (b"", b"x"):
            text = (pad + b"pw" + pngpixels.SEP + b"=1234").decode(codec, "replace")
            assert not secretscan.find(text, None), (codec, pad)


# ---------------------------------------------------------------- the walker is safe on any input


def test_the_walker_agrees_with_zlib_on_random_streams():
    rng = random.Random(SEED)
    for i in range(60):
        size = rng.randrange(1, 40000)
        data = rng.randbytes(size) if i % 3 == 0 else bytes(rng.choice(b"ab \n\x00\xff") for _ in range(size))
        level = rng.choice((1, 6, 9))
        strategy = rng.choice((zlib.Z_DEFAULT_STRATEGY, zlib.Z_FIXED, zlib.Z_HUFFMAN_ONLY, zlib.Z_RLE))
        stream = _flushed(data, level, strategy, every=rng.randrange(100, 50000))
        try:
            end, huff, out = pngpixels._walk(stream, 2)
        except pngpixels._Bad as e:
            assert "stored bytes" in str(e), i  # zlib falls back to stored blocks for random data
            continue
        assert out == len(data) and end == len(stream) - 4, i
        assert all(a < b for a, b in huff), i


def test_broken_pictures_never_raise_and_spans_stay_in_the_pixel_data():
    rng = random.Random(SEED)
    rows, w, h = _pixels(w=80, h=30)
    base = _png(zlib.compress(rows, 6), w, h, split=300)
    for _ in range(2000):
        pic = bytearray(base)
        for _ in range(rng.randrange(1, 4)):
            pic[rng.randrange(8, len(pic))] = rng.randrange(256)
        if rng.random() < 0.2:
            del pic[rng.randrange(8, len(pic)) :]
        spans = pngpixels.pixel_spans(bytes(pic))
        for a, b in spans:
            assert 33 <= a < b <= len(pic) - 12
        assert pngpixels.label_view(bytes(pic)) is None or spans


# ---------------------------------------------------------------- inputs from the review of the walker


class _Bits:
    """A deflate bit writer: fields LSB first, Huffman codes from their top bit."""

    def __init__(self):
        self.v, self.n = 0, 0

    def put(self, value: int, width: int):
        self.v |= value << self.n
        self.n += width

    def code(self, code: int, width: int):
        self.put(int(format(code, f"0{width}b")[::-1], 2), width)

    def fixed_literal(self, lit: int):
        self.code(0x30 + lit, 8) if lit < 144 else self.code(0x190 + lit - 144, 9)

    def done(self) -> bytes:
        return self.v.to_bytes((self.n + 7) // 8, "little")


def _canonical(lengths: list[int]) -> dict[int, tuple[int, int]]:
    count = [0] * 16
    for n in lengths:
        count[n] += 1
    count[0] = 0
    code, nxt = 0, [0] * 16
    for n in range(1, 16):
        code = (code + count[n - 1]) << 1
        nxt[n] = code
    out = {}
    for sym, n in enumerate(lengths):
        if n:
            out[sym] = (nxt[n], n)
            nxt[n] += 1
    return out


def test_text_in_a_dynamic_code_table_is_not_exempt(tmp_path):
    """The code tables of a dynamic block can carry any bytes: here `pw=x`. Only the coded symbols after the
    table are exempt from the label rules."""
    w = _Bits()
    w.put(0b010, 3)  # not final, fixed codes: literals 0 and 144 (the 1x1 picture), end of block
    w.fixed_literal(0)
    w.fixed_literal(144)
    w.code(0, 7)
    for _ in range(2):  # two empty fixed blocks: the dynamic table starts on a byte boundary
        w.put(0b010, 3)
        w.code(0, 7)
    w.put(0b101, 3)  # final, dynamic codes
    w.put(0, 5)  # 257 literal/length codes
    w.put(0, 5)  # one distance code
    w.put(15, 4)  # all 19 code length codes
    order = pngpixels._CL_ORDER
    cl_in_order = [0, 6, 5, 3, 7, 2, 7, 1, 0, 7, 5, 6, 7, 0, 0, 0, 0, 0, 0]
    for v in cl_in_order:
        w.put(v, 3)
    cl = [0] * 19
    for sym, v in zip(order, cl_in_order, strict=True):
        cl[sym] = v
    codes = _canonical(cl)
    lit = [8] * 255 + [9, 9]
    for n in [*lit, 0]:
        w.code(*codes[n])
    w.code(*_canonical(lit)[256])  # end of block
    pixels = b"\x00\x90"
    stream = b"\x78\x01" + w.done() + zlib.adler32(pixels).to_bytes(4, "big")
    assert zlib.decompress(stream) == pixels
    pic = _png(stream, 1, 1, ihdr=_ihdr(1, 1, 8, 0))
    assert b"pw=x" in pic
    view = pngpixels.label_view(pic)
    assert view is None or b"pw=x" in view
    assert _refused(pic, tmp_path)


def test_many_tiny_blocks_over_many_chunks_end_quickly():
    w = _Bits()
    w.put(0b010, 3)
    w.fixed_literal(0)
    w.fixed_literal(144)
    w.code(0, 7)
    for _ in range(100_000):
        w.put(0b010, 3)
        w.code(0, 7)
    w.put(0b011, 3)
    w.code(0, 7)
    pixels = b"\x00\x90"
    stream = b"\x78\x01" + w.done() + zlib.adler32(pixels).to_bytes(4, "big")
    assert zlib.decompress(stream) == pixels
    pic = _png(stream, 1, 1, split=14, ihdr=_ihdr(1, 1, 8, 0))
    t = time.perf_counter()
    assert pngpixels.pixel_spans(pic) == []  # past MAX_BLOCKS: no proof, every rule on every byte
    assert time.perf_counter() - t < 3


def test_the_work_caps_give_no_proof(monkeypatch):
    pic = screenshot(SEED, 200, 100)
    assert pngpixels.pixel_spans(pic)
    monkeypatch.setattr(pngpixels, "MAX_TABLE_WORK", 100)
    assert pngpixels.pixel_spans(pic) == []
    monkeypatch.setattr(pngpixels, "MAX_TABLE_WORK", 1 << 23)
    monkeypatch.setattr(pngpixels, "MAX_BLOCKS", 1)
    assert pngpixels.pixel_spans(pic) == []
