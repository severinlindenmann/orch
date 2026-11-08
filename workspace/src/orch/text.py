"""Text from outside (relay messages, webhooks) before it goes into a ticket or an agent prompt.

Implements contracts/vectors/clean-untrusted-v1.json: invisible characters can't hide instructions.
Visible text is never rewritten.
"""

from __future__ import annotations

import re
import unicodedata

# Default_Ignorable_Code_Point plus U+2800 (braille blank). Many are Cf already; some are Cn or Lo.
_IGNORABLE = [
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x2800, 0x2800),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
]
_DROP_CATEGORIES = {"Cc", "Cf", "Cn", "Cs"}
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _drop(ch: str) -> bool:
    if ch in "\n\t":
        return False
    cp = ord(ch)
    if any(lo <= cp <= hi for lo, hi in _IGNORABLE):
        return True
    return unicodedata.category(ch) in _DROP_CATEGORIES


def clean_untrusted(text: str, limit: int = 2000) -> str:
    """NFC; U+2028/2029 become a newline; control, format, unassigned and invisible characters go; HTML
    comments (also nested by cleaning) go, an unterminated one with everything after it; cut to `limit`."""
    text = unicodedata.normalize("NFC", str(text)).replace(" ", "\n").replace(" ", "\n")
    text = "".join(ch for ch in text if not _drop(ch))
    while True:
        new = _COMMENT.sub("", text)
        if new == text:
            break
        text = new
    cut = text.find("<!--")
    if cut != -1:
        text = text[:cut]
    return text[:limit]
