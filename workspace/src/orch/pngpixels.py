"""Which bytes of a PNG are only compressed pixels (#1022, ORCH-303).

The secret scan reads a picture's bytes as text. Compressed pixel data is close to random, so the loose label
rules (a short secret-looking name, `=` or `:`, a value) match by chance in about half of all screenshots.
This module proves which bytes are Huffman-coded deflate data and nothing else, so the scan can keep the label
rules away from them; every other byte (chunk headers, other chunks, the zlib header and checksum, block
headers) is still scanned with every rule, and the token patterns and stored-key check read the whole file.

The proof walks the deflate stream of the joined IDAT data block by block (structure only, no pixel bytes are
built; pure Python, about 0.1 s for a 300 KB screenshot) and cross-checks it with zlib. Anything odd gives no
proof (None), and the caller scans every byte with every rule, as before:
- not a PNG, a broken chunk walk, IDAT chunks not in one run, anything after IEND;
- a zlib header with a preset dictionary, any inflate error, data after the stream, a wrong checksum;
- a stored (uncompressed) block that holds bytes: its bytes are plain text in the file (an empty stored block,
  which encoders write on a flush, holds nothing);
- more or fewer pixel bytes than the IHDR size says.

Accepted gap (an encoding, like base64): a Huffman table deliberately chosen so that the coded bytes spell a
label and a value. The token patterns and the stored-key check still read those bytes."""

from __future__ import annotations

import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_CHUNKS = 10000  # a bounded walk: more chunks than this = no proof
MAX_PIXEL_BYTES = 1 << 30  # an IHDR that claims more than this = no proof
# What a proven pixel run is replaced with in the text the label rules read: a line break in UTF-8, Latin-1
# and in UTF-16 (both byte orders, both alignments), so no label can join across it.
SEP = b"\n\x00\n\n\x00\n"

_LEN_EXTRA = [0] * 8 + [1] * 4 + [2] * 4 + [3] * 4 + [4] * 4 + [5] * 4 + [0]  # length codes 257..285
_LEN_BASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131,
             163, 195, 227, 258]  # fmt: skip
_DIST_EXTRA = [0, 0, 0, 0] + [n for n in range(1, 14) for _ in (0, 1)]
_DIST_BASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537,
              2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577]  # fmt: skip
_CL_ORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}  # color type -> samples per pixel
_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
_ADAM7 = [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]


class _Bad(Exception):
    pass


def _table(lengths: list[int], single_ok: bool) -> tuple[list[int], int]:
    """A decode table indexed by the next `maxlen` bits (LSB first): entry = symbol << 4 | code length, 0 = no
    code. Refuses what zlib refuses: an oversubscribed code, and an incomplete one (except a single code of
    length 1 for literal/length and distance codes, as zlib allows)."""
    maxlen = max(lengths)
    if not maxlen:
        raise _Bad("empty code")
    count = [0] * 16
    for n in lengths:
        count[n] += 1
    count[0] = 0
    left = 1
    for n in range(1, 16):
        left = (left << 1) - count[n]
        if left < 0:
            raise _Bad("oversubscribed")
    if left > 0 and not (single_ok and maxlen == 1):
        raise _Bad("incomplete")
    nxt, code = [0] * 16, 0
    for n in range(1, 16):
        code = (code + count[n - 1]) << 1
        nxt[n] = code
    size = 1 << maxlen
    t = [0] * size
    for sym, n in enumerate(lengths):
        if n:
            r = int(format(nxt[n], f"0{n}b")[::-1], 2)  # Huffman codes are packed from their top bit
            nxt[n] += 1
            for i in range(r, size, 1 << n):
                t[i] = sym << 4 | n
    return t, size - 1


_FIXED: tuple | None = None


def _fixed() -> tuple:
    global _FIXED
    if _FIXED is None:
        _FIXED = (_table([8] * 144 + [9] * 112 + [7] * 24 + [8] * 8, True), _table([5] * 32, True))
    return _FIXED


def _walk(s: bytes, start: int) -> tuple[int, list[tuple[int, int]], int]:
    """Walk the raw deflate stream in `s` from byte `start` to its final block. (end byte, the bit ranges
    [first, end) of its Huffman-coded blocks, pixel bytes it inflates to). Raises _Bad on any error and on a
    stored block that holds bytes."""
    pos, b, n, out, L = start, 0, 0, 0, len(s)
    huff: list[tuple[int, int]] = []
    while True:
        first = pos * 8 - n
        if n < 3:
            if pos >= L:
                raise _Bad("eof")
            b |= s[pos] << n
            pos += 1
            n += 8
        final, btype = b & 1, (b >> 1) & 3
        b >>= 3
        n -= 3
        if btype == 0:
            pos = (first + 3 + 7) // 8  # to the next byte boundary
            b = n = 0
            if pos + 4 > L:
                raise _Bad("eof")
            size = s[pos] | s[pos + 1] << 8
            if s[pos + 2] | s[pos + 3] << 8 != size ^ 0xFFFF:
                raise _Bad("stored length")
            if size:
                raise _Bad("stored bytes")  # plain bytes: no proof
            pos += 4
        elif btype == 3:
            raise _Bad("block type 3")
        else:
            if btype == 1:
                (lt, lm), (dt, dm) = _fixed()
            else:
                while n < 14:
                    if pos >= L:
                        raise _Bad("eof")
                    b |= s[pos] << n
                    pos += 1
                    n += 8
                hlit, hdist, hclen = (b & 31) + 257, ((b >> 5) & 31) + 1, ((b >> 10) & 15) + 4
                b >>= 14
                n -= 14
                if hlit > 286 or hdist > 30:
                    raise _Bad("counts")
                cl = [0] * 19
                for i in range(hclen):
                    if n < 3:
                        if pos >= L:
                            raise _Bad("eof")
                        b |= s[pos] << n
                        pos += 1
                        n += 8
                    cl[_CL_ORDER[i]] = b & 7
                    b >>= 3
                    n -= 3
                ct, cm = _table(cl, False)
                lens: list[int] = []
                total = hlit + hdist
                while len(lens) < total:
                    while n < 16:
                        if pos >= L:
                            raise _Bad("eof")
                        b |= s[pos] << n
                        pos += 1
                        n += 8
                    e = ct[b & cm]
                    k = e & 15
                    if not k:
                        raise _Bad("code length code")
                    b >>= k
                    n -= k
                    sym = e >> 4
                    if sym < 16:
                        lens.append(sym)
                    elif sym == 16:
                        if not lens:
                            raise _Bad("repeat first")
                        lens += [lens[-1]] * (3 + (b & 3))
                        b >>= 2
                        n -= 2
                    elif sym == 17:
                        lens += [0] * (3 + (b & 7))
                        b >>= 3
                        n -= 3
                    else:
                        lens += [0] * (11 + (b & 127))
                        b >>= 7
                        n -= 7
                if len(lens) > total or not lens[256]:
                    raise _Bad("lengths")
                lt, lm = _table(lens[:hlit], True)
                dist = lens[hlit:]
                dt, dm = _table(dist, True) if max(dist) else ([0, 0], 1)  # no distance code: any use fails
            while True:  # the symbols of one block; at most 48 bits each
                if n < 48:
                    k = (64 - n) >> 3
                    got = min(k, L - pos)
                    b |= int.from_bytes(s[pos : pos + got], "little") << n
                    pos += got
                    n += got * 8
                e = lt[b & lm]
                k = e & 15
                if not k or k > n:
                    raise _Bad("code")
                b >>= k
                n -= k
                sym = e >> 4
                if sym < 256:
                    out += 1
                    continue
                if sym == 256:
                    break
                sym -= 257
                if sym >= 29:
                    raise _Bad("length code")
                x = _LEN_EXTRA[sym]
                if n < x:
                    raise _Bad("eof")
                length = _LEN_BASE[sym] + (b & ((1 << x) - 1))
                b >>= x
                n -= x
                e = dt[b & dm]
                k = e & 15
                if not k:
                    raise _Bad("distance code")
                b >>= k
                n -= k
                d = e >> 4
                if d >= 30:
                    raise _Bad("distance code")
                x = _DIST_EXTRA[d]
                if n < x:
                    raise _Bad("eof")
                if _DIST_BASE[d] + (b & ((1 << x) - 1)) > out:
                    raise _Bad("distance too far back")
                b >>= x
                n -= x
                out += length
            huff.append((first, pos * 8 - n))
        if final:
            return pos - (n >> 3), huff, out


def _pixel_bytes(ihdr: bytes) -> int:
    """How many bytes the IHDR's picture inflates to (filter bytes included); 0 = not a valid IHDR."""
    if len(ihdr) != 13:
        return 0
    w, h = int.from_bytes(ihdr[0:4], "big"), int.from_bytes(ihdr[4:8], "big")
    depth, color, method, filt, interlace = ihdr[8:13]
    if not w or not h or color not in _CHANNELS or depth not in _DEPTHS[color] or method or filt:
        return 0
    bpp = _CHANNELS[color] * depth
    if interlace == 0:
        return h * (1 + (w * bpp + 7) // 8)
    if interlace != 1:
        return 0
    total = 0
    for xs, ys, dx, dy in _ADAM7:
        pw, ph = (w - xs + dx - 1) // dx if w > xs else 0, (h - ys + dy - 1) // dy if h > ys else 0
        if pw and ph:
            total += ph * (1 + (pw * bpp + 7) // 8)
    return total


def pixel_spans(data: bytes) -> list[tuple[int, int]]:
    """The byte ranges [start, end) of `data` that are only Huffman-coded pixel data, or [] when that can't be
    proven (see the module text). Never raises."""
    try:
        return _spans(data)
    except (_Bad, zlib.error, IndexError, ValueError):
        return []


def _spans(data: bytes) -> list[tuple[int, int]]:
    if not data.startswith(SIGNATURE):
        return []
    pos, pieces, ihdr, idat_done = 8, [], b"", False  # pieces: (file offset, length) of each IDAT payload
    for _ in range(MAX_CHUNKS):
        if pos + 12 > len(data):
            return []
        length = int.from_bytes(data[pos : pos + 4], "big")
        kind = data[pos + 4 : pos + 8]
        end = pos + 12 + length
        if end > len(data) or length > 0x7FFFFFFF:
            return []
        if pos == 8:
            if kind != b"IHDR":
                return []
            ihdr = data[pos + 8 : pos + 8 + length]
        elif kind == b"IDAT":
            if idat_done:
                return []  # IDAT chunks must be one run
            pieces.append((pos + 8, length))
        elif pieces:
            idat_done = True
        if kind == b"IEND":
            if end != len(data):
                return []  # data after the end
            break
        pos = end
    else:
        return []
    expected = _pixel_bytes(ihdr)
    if not pieces or not expected or expected > MAX_PIXEL_BYTES:
        return []
    stream = b"".join(data[o : o + n] for o, n in pieces)
    if len(stream) < 6:
        return []
    cmf, flg = stream[0], stream[1]
    if cmf & 15 != 8 or cmf >> 4 > 7 or flg & 0x20 or (cmf << 8 | flg) % 31:
        return []  # not deflate, a window over 32 KB, a preset dictionary, a bad header check
    end, huff, out = _walk(stream, 2)
    if out != expected or end + 4 != len(stream):
        return []  # more or fewer pixels than the IHDR says, data after the stream
    d = zlib.decompressobj()  # the same stream through zlib: no error, the checksum, the same size and end
    tail, size = stream, 0
    while tail and not d.eof:
        size += len(d.decompress(tail, 1 << 22))
        tail = d.unconsumed_tail
    if not d.eof or d.unused_data or tail or size != expected:
        return []
    spans: list[tuple[int, int]] = []
    starts, acc = [], 0  # stream offset of each piece
    for _, n in pieces:
        starts.append(acc)
        acc += n
    for first, last in huff:
        a, z = (first + 7) // 8, last // 8  # only whole bytes inside the block
        for (off, n), s0 in zip(pieces, starts, strict=True):
            lo, hi = max(a, s0), min(z, s0 + n)
            if lo < hi:
                lo, hi = off + lo - s0, off + hi - s0
                if spans and spans[-1][1] == lo:
                    spans[-1] = (spans[-1][0], hi)
                else:
                    spans.append((lo, hi))
    return spans


def label_view(data: bytes) -> bytes | None:
    """`data` with each proven pixel run replaced by SEP: what the label rules read. None = no proof (scan
    every byte with every rule)."""
    spans = pixel_spans(data)
    if not spans:
        return None
    parts, last = [], 0
    for a, z in spans:
        parts += [data[last:a], SEP]
        last = z
    parts.append(data[last:])
    return b"".join(parts)
