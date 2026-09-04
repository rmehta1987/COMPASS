"""The Specifier's artefact, with every named variable traced to its record.

`emit()` wraps a validated `ProtocolSpecification` with the two
`RetrievalRecord`s that selected its anchors and a provenance line for every
variable the record names: exposure, outcome, and each adjusted, excluded or
undetermined covariate. Anchors carry the full record. A covariate the
Specifier named through the environment's tools carries `source ==
"specifier_tool"` and no record, because no retrieval selected it and a
record fabricated after the fact would say otherwise; if it belongs to an
anchor construct it carries that anchor's record.

`redact()` produces the form that may be committed to the public tree. The
instrument's wording is withheld there, and it enters an artefact in two
places: `quoted_wording` on every variable reference, and the request text
and rendered query of an instrument-sourced record. Redaction replaces each
with `sha256:<hex>` of the exact text, so anyone holding the dictionary can
verify the artefact and the scoring harness can rehydrate it by key. Nothing
else changes, and `redacted` says which form a file is.
"""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent.schema import ProtocolSpecification
from pipeline.resolved_pair import ResolvedPair
from pipeline.retrieval_record import RetrievalRecord

WHERE = ("exposure", "outcome", "adjusted", "excluded", "undetermined")


def sha256_text(text: str) -> str:
    """`sha256:<hex>` of the exact text.

    Args:
        text: The text.

    Returns:
        The tagged digest.
    """
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


class VariableProvenance(BaseModel):
    """Where one named variable came from.

    Attributes:
        key: The variable key, or `derivation:<id>` / `area:<id>`.
        where: `exposure`, `outcome`, `adjusted`, `excluded` or `undetermined`.
        kind: `variable`, `derivation` or `area_measure`.
        source: `retrieval` when a record selected it, `specifier_tool` when
            the Specifier named it through the environment's tools.
        retrieval: The record, when `source == "retrieval"`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1)
    where: str = Field(pattern="^(" + "|".join(WHERE) + ")$")
    kind: str = Field(pattern="^(variable|derivation|area_measure)$")
    source: str = Field(pattern="^(retrieval|specifier_tool)$")
    retrieval: RetrievalRecord | None


class SpecifierArtefact(BaseModel):
    """One hypothesis, persisted with its trace.

    Attributes:
        artefact_version: Bumped when a field is added; never backfilled.
        protocol_id: The record's id.
        record_hash: `ProtocolSpecification.record_hash()`.
        pair_id: The pair's id.
        estimability: The gate's verdict the pair carried.
        protocol: The record, as `model_dump(mode="json")`.
        retrieval: The anchor records, keyed `exposure` and `outcome`.
        variables: One provenance line per named variable.
        redacted: True after `redact()`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    artefact_version: int = 1
    protocol_id: str = Field(min_length=1)
    record_hash: str = Field(min_length=1)
    pair_id: str = Field(min_length=1)
    estimability: str = Field(min_length=1)
    protocol: dict[str, Any]
    retrieval: dict[str, RetrievalRecord]
    variables: tuple[VariableProvenance, ...] = Field(min_length=2)
    redacted: bool = False

    def to_json(self) -> str:
        """Serialise; `from_json` inverts it.

        Returns:
            JSON, indented for review.
        """
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, text: str) -> SpecifierArtefact:
        """Parse what `to_json` wrote.

        Args:
            text: The JSON.

        Returns:
            An equal artefact.
        """
        return cls.model_validate_json(text)


def _ref_key_kind(ref: Any) -> tuple[str, str]:
    kind = str(getattr(ref, "kind", "variable"))
    if kind == "derivation":
        return f"derivation:{ref.derivation_id}", kind
    if kind == "area_measure":
        return f"area:{ref.measure_id}", kind
    return str(ref.key), "variable"


def named_variables(p: ProtocolSpecification) -> list[tuple[str, str, str]]:
    """Every variable the record names.

    Args:
        p: The record.

    Returns:
        `(key, where, kind)` in record order: exposure, outcome, then the
        adjusted, excluded and undetermined covariates.
    """
    out: list[tuple[str, str, str]] = []
    for ref, where in ((p.exposure, "exposure"), (p.outcome, "outcome")):
        key, kind = _ref_key_kind(ref)
        out.append((key, where, kind))
    for lst, where in ((p.adjusted_covariates, "adjusted"),
                       (p.excluded_variables, "excluded"),
                       (p.undetermined_covariates, "undetermined")):
        for entry in lst:
            key, kind = _ref_key_kind(entry.variable)
            out.append((key, where, kind))
    return out


def emit(p: ProtocolSpecification, pair: ResolvedPair) -> SpecifierArtefact:
    """Wrap a validated record with the records that selected its anchors.

    Args:
        p: The record the Specifier produced for `pair`.
        pair: The pair, carrying `retrieval == (exposure_record, outcome_record)`.

    Returns:
        The artefact, unredacted.

    Raises:
        ValueError: When a variable anchor of the record is not in `pair`.
    """
    rec_e, rec_o = pair.retrieval
    anchors = {
        "exposure": (rec_e, {pair.exposure.construct_key, *pair.exposure.member_keys}),
        "outcome": (rec_o, {pair.outcome.construct_key, *pair.outcome.member_keys}),
    }
    # the record names its anchors by reference, not by pair id: a variable
    # anchor must belong to the pair's construct on that side. A derivation or
    # area measure is checked by its own signed file elsewhere, not here.
    for ref, where in ((p.exposure, "exposure"), (p.outcome, "outcome")):
        key, kind = _ref_key_kind(ref)
        if kind == "variable" and key not in anchors[where][1]:
            raise ValueError(f"record's {where} is {key!r}, which is not in the "
                             f"pair's {where} construct "
                             f"{getattr(pair, where).construct_key!r}")
    lines: list[VariableProvenance] = []
    for key, where, kind in named_variables(p):
        rec: RetrievalRecord | None = None
        if where in anchors:
            rec = anchors[where][0]
        else:
            for side_rec, keys in anchors.values():
                if key in keys:
                    rec = side_rec
        lines.append(VariableProvenance(
            key=key, where=where, kind=kind,
            source="retrieval" if rec is not None else "specifier_tool",
            retrieval=rec))
    return SpecifierArtefact(
        protocol_id=p.protocol_id, record_hash=p.record_hash(), pair_id=pair.pair_id,
        estimability=pair.estimability or "unknown",
        protocol=p.model_dump(mode="json"),
        retrieval={"exposure": rec_e, "outcome": rec_o}, variables=tuple(lines))


def _redact_record(rec: RetrievalRecord) -> RetrievalRecord:
    if rec.request.source != "instrument" or rec.query.startswith("sha256:"):
        return rec
    req = rec.request.model_copy(
        update={"construct_text": sha256_text(rec.request.construct_text)})
    return rec.model_copy(update={"request": req, "query": sha256_text(rec.query)})


def _redact_wording(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: (sha256_text(v) if k == "quoted_wording" and isinstance(v, str)
                    and not v.startswith("sha256:") else _redact_wording(v))
                for k, v in node.items()}
    if isinstance(node, list):
        return [_redact_wording(x) for x in node]
    return node


def redact(art: SpecifierArtefact) -> SpecifierArtefact:
    """The committable form: instrument wording replaced by its digest.

    Args:
        art: An artefact, redacted or not (idempotent).

    Returns:
        A copy with `redacted=True`.
    """
    variables = tuple(v.model_copy(update={"retrieval": _redact_record(v.retrieval)})
                      if v.retrieval is not None else v for v in art.variables)
    return art.model_copy(update={
        "protocol": _redact_wording(art.protocol),
        "retrieval": {k: _redact_record(r) for k, r in art.retrieval.items()},
        "variables": variables, "redacted": True})
