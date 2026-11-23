"""How deeply a JSON text nests, counted on its raw bytes before it is parsed.

Python's JSON reader recurses once per ``[`` or ``{``, and every later walk over the
value (credential redaction, the output budget, the host's secret check) has the same
limit. So the depth is counted first, on the bytes, with brackets inside strings
ignored. A Discord answer nested deeper than ``MAX_ANSWER_DEPTH`` is not parsed: the
answer sits three levels below the step's response envelope
(``{result: {response: {data: ...}}}``), and the envelope may nest at most 48 levels.
"""

from __future__ import annotations

import re
from itertools import accumulate

MAX_ANSWER_DEPTH = 45

#: A JSON string with its escapes; an unterminated one runs to the end of the text.
_STRING = re.compile(rb'"[^"\\]*(?:\\.[^"\\]*)*"?', re.DOTALL)
_NOT_BRACKETS = bytes(b for b in range(256) if b not in b"[]{}")
_STEP = {ord("["): 1, ord("{"): 1, ord("]"): -1, ord("}"): -1}


def depth(raw: bytes) -> int:
    """The deepest bracket nesting of ``raw``, brackets inside JSON strings ignored."""
    brackets = _STRING.sub(b"", raw).translate(None, _NOT_BRACKETS)
    if not brackets:
        return 0
    return max(0, max(accumulate(map(_STEP.__getitem__, brackets))))


def too_deep(raw: bytes, limit: int = MAX_ANSWER_DEPTH) -> bool:
    return depth(raw) > limit
