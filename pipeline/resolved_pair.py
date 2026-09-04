"""A pair the Specifier can take, built from two `RetrievalRecord`s.

`agent.specifier.PairLike` names what the Specifier reads from a pair: two
anchors carrying a construct key, stem, member keys and two flags, plus
`pair_id`, `estimability` and `requires_derivation`. The funnel's `Candidate`
is one implementation; this is the other. It takes the exposure and outcome
records retrieval produced, looks each hit's dictionary construct up in the
built dictionary, and presents the same anchors the funnel would, so the
Specifier's prompt is byte-identical for the same two constructs whether the
pair was enumerated or requested. The records ride along in `retrieval` for
the artefact to persist.

A record that abstained has no construct to anchor, and a hit whose
dictionary construct the dictionary does not know is a bundle-dictionary
mismatch; both refuse to build rather than produce a pair with a hole in it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from generate.funnel import Construct
from pipeline.retrieval_record import RetrievalRecord


class Unresolved(ValueError):
    """A record cannot anchor a pair."""


@dataclass(frozen=True)
class ResolvedPair:
    """Two dictionary constructs selected by retrieval, plus their records.

    Attributes:
        exposure: The exposure anchor, from the built dictionary.
        outcome: The outcome anchor, likewise.
        retrieval: `(exposure_record, outcome_record)`, the records that
            selected the anchors; persisted whole by the artefact.
        estimability: The gate's verdict for the pair, or None before gating.
        requires_derivation: True when either anchor is a grid battery, the
            funnel's S2 rule.
    """

    exposure: Construct
    outcome: Construct
    retrieval: tuple[RetrievalRecord, RetrievalRecord]
    estimability: str | None = None
    requires_derivation: bool = False

    @property
    def pair_id(self) -> str:
        """`<exposure construct key> -> <outcome construct key>`.

        Returns:
            The id, in the funnel's format.
        """
        return f"{self.exposure.construct_key} -> {self.outcome.construct_key}"


def anchor_from(rec: RetrievalRecord, constructs: dict[str, Construct],
                side: str) -> Construct:
    """The dictionary construct a record selected.

    Args:
        rec: The record.
        constructs: `generate.funnel.load_constructs().constructs`.
        side: `exposure` or `outcome`, for the error message and a role check.

    Returns:
        The construct.

    Raises:
        Unresolved: When the record abstained, its role is not `side`, or its
            hit names a construct the dictionary does not hold.
    """
    if rec.request.role != side:
        raise Unresolved(f"{side} record carries role {rec.request.role!r}")
    if rec.abstained or rec.hit is None:
        raise Unresolved(f"{side} request abstained (nearest {rec.nearest_key}, "
                         f"margin {rec.margin:+.4f}); nothing to anchor")
    ck = rec.hit.dict_construct_key
    if ck not in constructs:
        raise Unresolved(f"{side} hit names construct {ck!r}, which the built "
                         f"dictionary ({rec.dictionary_hash}) does not hold")
    return constructs[ck]


def from_records(exposure: RetrievalRecord, outcome: RetrievalRecord,
                 constructs: dict[str, Construct],
                 estimability: str | None = None) -> ResolvedPair:
    """Build a pair from two records.

    Args:
        exposure: The exposure's record; its request role must be `exposure`.
        outcome: The outcome's record; role `outcome`.
        constructs: The built dictionary's constructs.
        estimability: The gate's verdict, when already known.

    Returns:
        The pair.

    Raises:
        Unresolved: See `anchor_from`.
    """
    e = anchor_from(exposure, constructs, "exposure")
    o = anchor_from(outcome, constructs, "outcome")
    return ResolvedPair(exposure=e, outcome=o, retrieval=(exposure, outcome),
                        estimability=estimability,
                        requires_derivation=bool(e.is_group or o.is_group))


def from_pair_resolution(pr: Any, constructs: dict[str, Construct],
                         estimability: str | None = None) -> ResolvedPair:
    """Build from `pipeline.auto_intake.PairResolution`.

    Args:
        pr: The resolution; both sides must have resolved.
        constructs: The built dictionary's constructs.
        estimability: The gate's verdict, when already known.

    Returns:
        The pair.

    Raises:
        Unresolved: When either side did not resolve to the funnel's construct.
    """
    if not pr.both_resolved:
        raise Unresolved(f"{pr.pair_id}: exposure_resolved={pr.exposure_resolved}, "
                         f"outcome_resolved={pr.outcome_resolved}")
    return from_records(pr.exposure, pr.outcome, constructs, estimability)
