"""The hypothesis record: the artefact plus its typed causal structure.

One file per hypothesis the pipeline emits. `SpecifierArtefact` carries the
Specifier's record with every variable traced to its retrieval;
`CausalStructure` carries the same record's causal commitments as a graph.
Both are derived from one validated `ProtocolSpecification`, so they cannot
disagree, and a validator reads the graph rather than the prose.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from agent.schema import ProtocolSpecification
from pipeline.artefact import SpecifierArtefact, emit, redact
from pipeline.causal_structure import CausalStructure, derive
from pipeline.resolved_pair import ResolvedPair


class HypothesisRecord(BaseModel):
    """One emitted hypothesis, whole.

    Attributes:
        artefact: The Specifier's record with its retrieval trace.
        structure: The record's causal structure, typed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    artefact: SpecifierArtefact
    structure: CausalStructure

    def to_json(self) -> str:
        """Serialise; `from_json` inverts it.

        Returns:
            JSON, indented for review.
        """
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, text: str) -> HypothesisRecord:
        """Parse what `to_json` wrote.

        Args:
            text: The JSON.

        Returns:
            An equal record.
        """
        return cls.model_validate_json(text)

    def redacted(self) -> HypothesisRecord:
        """The committable form; the structure holds keys only and is unchanged.

        Returns:
            A copy with the artefact redacted.
        """
        return self.model_copy(update={"artefact": redact(self.artefact)})


def build(p: ProtocolSpecification, pair: ResolvedPair) -> HypothesisRecord:
    """Build the record from a validated protocol and its pair.

    Args:
        p: The record the Specifier produced.
        pair: The pair, with its two retrieval records.

    Returns:
        The hypothesis record.
    """
    return HypothesisRecord(artefact=emit(p, pair), structure=derive(p))
