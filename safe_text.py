"""
safe_text.py — text from the file system that is not valid Unicode

NTFS allows a lone UTF-16 surrogate in a name. Python reads such a name fine, but the string
cannot be encoded as UTF-8, so writing it to a file, a log or the page would raise.
"""

from __future__ import annotations

import json


def printable(text: str) -> str:
    """The text with each lone surrogate shown as a \\udXXX escape, so it can be displayed and written anywhere."""
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def dumps(value, **options) -> str:
    """
    json.dumps that keeps non-ASCII text readable and never yields text that cannot be encoded.
    A lone surrogate comes out as a \\udXXX escape, which a JSON or JavaScript parser reads back unchanged.
    """
    text = json.dumps(value, ensure_ascii=False, **options)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return json.dumps(value, **options)
    return text