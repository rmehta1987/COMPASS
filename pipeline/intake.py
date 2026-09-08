"""User intake: a typed line of text becomes a `RetrievalRequest`.

Deterministic, no model call. The grammar is the shipped template's own
rendering read backwards, so a request round-trips through `to_query()`:

    construct[: instance, instance, ...][ [timeframe] ]

    "use of anti-inflammatory medication: ibuprofen, naproxen [past 12 months]"

`population` is never set: the shipped contract is instances only
(`deploy/manifest.json::template.shipped_contract`).

Specificity is the cheapest accuracy lever in the system. On the 224-row
fixture, rank-1 accuracy was 0.493 for queries of 1-2 content words and 0.676
at 4 or more (`QUERY_EXPANSION.md`, the query-length table). Intake therefore
counts content words with the template's own rule and attaches a note when a
request is short or names no instances. It never rewrites the request: a
rewriter was measured and retired, and a note is a request to the person, not
a change to what the encoder sees.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from typing import Any

from pipeline.retrieve import load_template

#: Content words at or above which the fixture's rank-1 accuracy was 0.676,
#: against 0.493 at 1-2 (QUERY_EXPANSION.md). A cutoff for the note only.
SPECIFIC_MIN_CONTENT_WORDS = 4

ROLES = ("exposure", "outcome", "confounder")
_TIMEFRAME = re.compile(r"\s*\[([^\[\]]+)\]\s*$")


def modalities() -> tuple[str, ...]:
    """The modality values a caller may declare, from the template's own enum.

    Read from `deploy/template.py` rather than restated, so the vocabulary has
    one definition. Deliberately a function, not a module constant: the
    template is loaded by path and a constant would run that at import time.

    Intake never reads a modality out of the typed text. "measured blood
    pressure" is a construct whose wording happens to contain a modality word,
    and treating that as a declaration is exactly the inference the UNKNOWN
    default exists to prevent: it would invent a mismatch on a legitimate
    resolve. A caller declares one or the request stays `unknown`.

    Returns:
        Every `Modality` value, `unknown` included.
    """
    return tuple(m.value for m in load_template().Modality)


@dataclass(frozen=True)
class Intake:
    """A parsed request and what intake noticed about it.

    Attributes:
        request: The `RetrievalRequest`, ready for `pipeline.retrieve`.
        query: What `to_query()` renders; exactly what the encoder will see.
        content_words: The template's content-word count of `query`.
        specific: `content_words >= SPECIFIC_MIN_CONTENT_WORDS`.
        notes: Advice to the requester, never applied automatically.
    """

    request: Any
    query: str
    content_words: int
    specific: bool
    notes: tuple[str, ...]


def parse_request(text: str, *, role: str = "exposure",
                  timeframe: str | None = None,
                  modality: str = "unknown") -> Intake:
    """Parse one typed request.

    Args:
        text: `construct[: instances][ [timeframe] ]`. A bracketed suffix is
            the timeframe unless `timeframe` is given explicitly.
        role: `exposure`, `outcome` or `confounder`. Not rendered; carried.
        timeframe: Overrides a bracketed suffix.
        modality: One of `modalities()`. Declared by the caller or left
            `unknown`; never read out of `text`, and never rendered.

    Returns:
        The intake.

    Raises:
        ValueError: On an empty construct, an unknown role or an unknown
            modality.
    """
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {role!r}")
    allowed = modalities()
    if modality not in allowed:
        raise ValueError(f"modality must be one of {allowed}, got {modality!r}")
    body = text.strip()
    m = _TIMEFRAME.search(body)
    if m:
        body = body[: m.start()].rstrip()
        if timeframe is None:
            timeframe = m.group(1).strip() or None
    construct, _, rest = body.partition(":")
    construct = construct.strip()
    if not construct:
        raise ValueError("a request needs a construct before the colon")
    seen: list[str] = []
    for inst in rest.split(","):
        inst = inst.strip()
        if inst and inst not in seen:
            seen.append(inst)
    tpl = load_template()
    req = tpl.RetrievalRequest(construct=construct, role=tpl.VariableRole(role),
                               population=None, timeframe=timeframe,
                               instances=tuple(seen),
                               modality=tpl.Modality(modality))
    query = req.to_query()
    n = len(tpl.content_words(query, True))
    notes: list[str] = []
    if n < SPECIFIC_MIN_CONTENT_WORDS:
        notes.append(f"{n} content word(s); rank-1 accuracy on the fixture was "
                     f"0.493 at 1-2 against 0.676 at 4+. Name instances or be "
                     f"more specific.")
    if not seen:
        notes.append("no instances named; 'construct: instance, instance' adds "
                     "them and is the shipped template's contract")
    return Intake(request=req, query=query, content_words=n,
                  specific=n >= SPECIFIC_MIN_CONTENT_WORDS, notes=tuple(notes))


def main(argv: list[str] | None = None) -> int:
    """Command line: parse a request and print what the encoder would see.

    Args:
        argv: Arguments; `sys.argv[1:]` when None.

    Returns:
        0 always; the notes are advice, not errors.
    """
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", help="construct[: instances][ [timeframe] ]")
    ap.add_argument("--role", choices=ROLES, default="exposure")
    ap.add_argument("--modality", choices=modalities(), default="unknown",
                    help="how the variable was measured; declared, never inferred")
    a = ap.parse_args(argv)
    it = parse_request(a.text, role=a.role, modality=a.modality)
    print(f"query:         {it.query!r}")
    print(f"role:          {it.request.role.value}")
    print(f"modality:      {it.request.modality.value}")
    print(f"instances:     {list(it.request.instances)}")
    print(f"timeframe:     {it.request.timeframe}")
    print(f"content words: {it.content_words} ({'specific' if it.specific else 'short'})")
    for n in it.notes:
        print(f"note:          {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
