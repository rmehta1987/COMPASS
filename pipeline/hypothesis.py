"""The hypothesis record: the artefact plus its typed causal structure.

One file per hypothesis the pipeline emits. `SpecifierArtefact` carries the
Specifier's record with every variable traced to its retrieval;
`CausalStructure` carries the same record's causal commitments as a graph.
Both are derived from one validated `ProtocolSpecification`, so they cannot
disagree, and a validator reads the graph rather than the prose.

Two seams are declared now and populated by nothing in this loop. `critiques`
and `revision` exist so that when a validator or reviewer starts writing to
them, the hundred artefacts generated before that day stay comparable to the
ones after: a field added later cannot be backfilled. `generation` is the
machine-measured stamp of the clone that produced the artefact; the scoring
harness refuses an artefact whose stamp says the answer key was reachable.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agent.schema import ProtocolSpecification
from pipeline.artefact import SpecifierArtefact, emit, redact
from pipeline.causal_structure import CausalStructure, derive
from pipeline.generation_env import GenerationEnv
from pipeline.resolved_pair import ResolvedPair

CATEGORIES = ("confounding", "measurement", "identification", "feasibility")
SEVERITIES = ("blocking", "major", "minor")


class Critique(BaseModel):
    """One objection to a hypothesis, from a validator or a reviewer.

    Attributes:
        source: Who raised it: `validator:<name>`, later a model id or a person.
        category: `confounding`, `measurement`, `identification` or `feasibility`.
        statement: The objection.
        grounding_key: The RetrievalRecord key it rests on, if any.
        severity: `blocking`, `major` or `minor`.
        resolved: Whether a later revision answered it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1)
    category: str = Field(pattern="^(" + "|".join(CATEGORIES) + ")$")
    statement: str = Field(min_length=1)
    grounding_key: str | None = None
    severity: str = Field(pattern="^(" + "|".join(SEVERITIES) + ")$")
    resolved: bool = False


class HypothesisRecord(BaseModel):
    """One emitted hypothesis, whole.

    Attributes:
        artefact: The Specifier's record with its retrieval trace.
        structure: The record's causal structure, typed.
        critiques: Objections raised against it; empty in this loop.
        revision: 0 until something revises it.
        generation: The clone's stamp; None until `stamped()` after the push.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    artefact: SpecifierArtefact
    structure: CausalStructure
    critiques: tuple[Critique, ...] = ()
    revision: int = Field(default=0, ge=0)
    generation: GenerationEnv | None = None

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

    def stamped(self, env: GenerationEnv) -> HypothesisRecord:
        """Attach the generation stamp.

        Args:
            env: Measured by `pipeline.generation_env.stamp` after the push.

        Returns:
            A copy carrying it.
        """
        return self.model_copy(update={"generation": env})


def build(p: ProtocolSpecification, pair: ResolvedPair) -> HypothesisRecord:
    """Build the record from a validated protocol and its pair.

    Args:
        p: The record the Specifier produced.
        pair: The pair, with its two retrieval records.

    Returns:
        The hypothesis record.
    """
    return HypothesisRecord(artefact=emit(p, pair), structure=derive(p))
