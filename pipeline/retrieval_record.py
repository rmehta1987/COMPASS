"""The persisted outcome of one retrieval: what was asked, what came back.

A `RetrievalRecord` is stored whole inside every artefact that names a variable,
so a proposal can be traced back to the exact request, threshold and cosine that
selected each key. It is written once and never backfilled: a field added later
would leave earlier artefacts incomparable, which is why the abstained case, the
threshold and the runner-up margin are all recorded from the start.

Two deliberate absences:

* No stem or option wording. Artefacts are committed to a public tree and the
  instrument's wording is withheld from it; the record carries keys, and wording
  is resolved at run time by key through `env/labels.py::cite`.
* No reference to the `RetrievalRequest` dataclass itself. The bundle loads
  `deploy/template.py` by path under its own module name, so a second import
  would yield a second class; the record snapshots the request's fields instead.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RequestSnapshot(BaseModel):
    """The fields of a `RetrievalRequest`, as plain values.

    Attributes:
        construct_text: What the requester wants measured, in their words. Named
            `construct_text` because `construct` shadows a `BaseModel` method.
        role: `exposure`, `outcome` or `confounder`; the enum's string value.
        population: A population qualifier, or None under the shipped contract.
        timeframe: A recall window such as "past 12 months", or None.
        instances: Named instances of the construct, in request order.
        source: `user` when a person typed the construct, `instrument` when
            auto intake built it from a dictionary construct's own stem. An
            instrument-sourced `construct_text` and its rendered `query` ARE
            withheld wording, and an artefact writer must redact them before
            anything is committed to the public tree.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    construct_text: str = Field(min_length=1)
    role: str = Field(min_length=1)
    population: str | None = None
    timeframe: str | None = None
    instances: tuple[str, ...] = ()
    source: str = Field(default="user", pattern="^(user|instrument)$")

    @classmethod
    def from_request(cls, req: Any, source: str = "user") -> RequestSnapshot:
        """Snapshot a `deploy.template.RetrievalRequest`.

        Typed `Any` because the dataclass is loaded by path (see module doc);
        only the five field names are relied on.

        Args:
            req: The request object.
            source: `user` or `instrument`; see the attribute.

        Returns:
            The snapshot.
        """
        role = req.role
        return cls(construct_text=req.construct,
                   role=str(getattr(role, "value", role)),
                   population=req.population, timeframe=req.timeframe,
                   instances=tuple(req.instances), source=source)


class Hit(BaseModel):
    """The selected target, keys only.

    Attributes:
        key: The canonical variable key the query selected.
        construct_key: The construct the key belongs to, as the deployed
            target set names it.
        dict_construct_key: The same construct as the built dictionary names
            it; differs from `construct_key` on 2 of 1,353 targets, and is the
            key the funnel's `Construct.construct_key` is compared with.
        module: The instrument module, "1", "2" or "3".
        target_id: Row number in the deployed target set, 1-based.
        fold_size: How many dictionary rows fold into this target.
        n_siblings: How many other targets share the construct.
        members: Every variable key folded into this target, including `key`.
        stratum: The target's stratum by `src/char_strata.py`'s keyword rule.
        unmeasured_stratum: True when the retrieval benchmark has zero gold
            rows in that stratum, so its accuracy there is unknown, not poor.
            Four such strata hold the mediators of every disparities
            hypothesis; see `pipeline/strata.py`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1)
    construct_key: str = Field(min_length=1)
    dict_construct_key: str = Field(min_length=1)
    module: str = Field(min_length=1)
    target_id: int = Field(ge=1)
    fold_size: int = Field(ge=1)
    n_siblings: int = Field(ge=0)
    members: tuple[str, ...] = Field(min_length=1)
    stratum: str = Field(min_length=1)
    unmeasured_stratum: bool

    @classmethod
    def from_hit(cls, hit: dict[str, Any], *, stratum: str,
                 unmeasured_stratum: bool, dict_construct_key: str | None = None) -> Hit:
        """Build from a `CompassRetriever.search()` / `select()` dict.

        Args:
            hit: One hit dict as the retriever returns it.
            stratum: From `pipeline.strata.Strata.of`.
            unmeasured_stratum: Likewise.
            dict_construct_key: From the target row; the retriever's hit dict
                does not carry it. Falls back to `construct_key`.

        Returns:
            The keys-only view of it. Wording fields are dropped on purpose.
        """
        return cls(key=hit["key"], construct_key=hit["construct_key"],
                   dict_construct_key=dict_construct_key or hit["construct_key"],
                   module=str(hit["module"]), target_id=hit["target_id"],
                   fold_size=hit["fold_size"], n_siblings=hit["n_siblings"],
                   members=tuple(hit["members"]), stratum=stratum,
                   unmeasured_stratum=unmeasured_stratum)


class RetrievalRecord(BaseModel):
    """One retrieval, persisted whole.

    Attributes:
        request: The request's fields.
        query: The exact string the template rendered and the encoder saw.
        dictionary_hash: The dictionary the bundle was built from.
        min_cos: The abstention threshold in force for this call.
        best_cos: The top cosine, recorded even when it fell below `min_cos`.
        margin: `best_cos - min_cos`; negative on an abstention.
        margin_12: Top-1 minus top-2 cosine, None when the call abstained.
        abstained: True when no target cleared `min_cos`.
        nearest_key: The top-1 target's key regardless of the threshold, so a
            rank-based score and an abstention diagnosis both stay possible.
        hit: The selected target, None when abstained.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: RequestSnapshot
    query: str = Field(min_length=1)
    dictionary_hash: str = Field(min_length=1)
    min_cos: float
    best_cos: float
    margin: float
    margin_12: float | None
    abstained: bool
    nearest_key: str = Field(min_length=1)
    hit: Hit | None

    @model_validator(mode="after")
    def _abstention_is_consistent(self) -> RetrievalRecord:
        """Refuse a record whose flag, hit and cosine disagree.

        Abstained means no hit and a cosine below the threshold; resolved means
        a hit and a cosine at or above it.

        Returns:
            The record, unchanged.

        Raises:
            ValueError: When the flag, the hit and the cosine disagree.
        """
        if self.abstained:
            if self.hit is not None:
                raise ValueError("abstained record carries a hit")
            if self.best_cos >= self.min_cos:
                raise ValueError("abstained record clears min_cos")
            if self.margin_12 is not None:
                raise ValueError("abstained record carries margin_12")
        else:
            if self.hit is None:
                raise ValueError("resolved record has no hit")
            if self.best_cos < self.min_cos:
                raise ValueError("resolved record is below min_cos")
            if self.hit.key != self.nearest_key:
                raise ValueError("resolved hit is not the nearest target")
        if abs((self.best_cos - self.min_cos) - self.margin) > 1e-9:
            raise ValueError("margin != best_cos - min_cos")
        return self

    def to_json(self) -> str:
        """Serialise losslessly; `from_json` inverts it.

        Returns:
            Compact JSON.
        """
        return self.model_dump_json()

    @classmethod
    def from_json(cls, text: str) -> RetrievalRecord:
        """Parse what `to_json` wrote.

        Args:
            text: The JSON.

        Returns:
            An equal record.
        """
        return cls.model_validate_json(text)
