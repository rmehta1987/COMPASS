"""A typed causal structure derived from the record, never written as prose.

The Specifier's record already commits to one causal role per covariate
(`agent.schema.CausalRole`) and to a unit of analysis. This module reads
those commitments and lays them out as nodes and edges a validator can walk:
the exposure-outcome edge under test, a confounder pointing at both anchors,
a mediator on the path between them, a precision variable pointing at the
outcome only, and so on. Nothing is inferred that the record did not state;
a role with no defensible edge (an unadjudicated covariate, a variable that
causes neither anchor) is a node without edges, and the role is kept.

Design is derived from the unit of analysis: one questionnaire per
participant is cross-sectional; a visit or participant-year unit is repeated
measures. That distinction is what a temporality validator needs.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent.schema import CausalRole, ProtocolSpecification
from pipeline.artefact import named_variables

CROSS_SECTIONAL = "cross_sectional"
REPEATED_MEASURES = "repeated_measures"
DESIGNS = (CROSS_SECTIONAL, REPEATED_MEASURES)
POSITIONS = ("exposure", "outcome", "covariate")
DECISIONS = ("adjusted", "excluded", "undetermined")
RELATIONS = ("hypothesised", "causes", "proxies")

#: Per role, the edges it asserts, as (source, target) over the placeholders
#: X (exposure), Y (outcome) and C (the covariate itself). A role absent here
#: asserts no edge.
EDGES_BY_ROLE: dict[str, tuple[tuple[str, str], ...]] = {
    CausalRole.confounder.value: (("C", "X"), ("C", "Y")),
    CausalRole.cause_of_exposure_only.value: (("C", "X"),),
    CausalRole.precision.value: (("C", "Y"),),
    CausalRole.proxy.value: (("C", "X"), ("C", "Y")),
    CausalRole.mediator.value: (("X", "C"), ("C", "Y")),
    CausalRole.descendant_of_exposure.value: (("X", "C"),),
    CausalRole.descendant_of_outcome.value: (("Y", "C"),),
}


class Node(BaseModel):
    """One variable in the structure.

    Attributes:
        key: The variable key, or `derivation:<id>` / `area:<id>`.
        kind: `variable`, `derivation` or `area_measure`.
        position: `exposure`, `outcome` or `covariate`.
        role: The record's `CausalRole` value for a covariate; None for anchors.
        decision: `adjusted`, `excluded` or `undetermined` for a covariate.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1)
    kind: str = Field(pattern="^(variable|derivation|area_measure)$")
    position: str = Field(pattern="^(" + "|".join(POSITIONS) + ")$")
    role: str | None = None
    decision: str | None = Field(default=None,
                                 pattern="^(" + "|".join(DECISIONS) + ")$")


class Edge(BaseModel):
    """One directed edge.

    Attributes:
        source: Node key.
        target: Node key.
        relation: `hypothesised` for the exposure-outcome edge under test,
            `proxies` for a proxy's edges, `causes` otherwise.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    relation: str = Field(pattern="^(" + "|".join(RELATIONS) + ")$")


class CausalStructure(BaseModel):
    """The record's causal commitments as a graph.

    Attributes:
        design: `cross_sectional` or `repeated_measures`.
        unit_of_analysis: The record's unit of analysis, verbatim.
        exposure: The exposure node's key.
        outcome: The outcome node's key.
        expected_direction: The record's expected direction, as its enum value.
        nodes: Every named variable, anchors first.
        edges: Directed edges asserted by the roles.
        adjustment_set: Keys of the adjusted covariates, in record order.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    design: str = Field(pattern="^(" + "|".join(DESIGNS) + ")$")
    unit_of_analysis: str = Field(min_length=1)
    exposure: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    expected_direction: str = Field(min_length=1)
    nodes: tuple[Node, ...] = Field(min_length=2)
    edges: tuple[Edge, ...] = Field(min_length=1)
    adjustment_set: tuple[str, ...] = ()

    def node(self, key: str) -> Node:
        """Look a node up by key.

        Args:
            key: The node's key.

        Returns:
            The node.

        Raises:
            KeyError: When no node has that key.
        """
        for n in self.nodes:
            if n.key == key:
                return n
        raise KeyError(key)

    def roles(self, decision: str | None = None) -> dict[str, str]:
        """Covariate roles, optionally for one decision list.

        Args:
            decision: `adjusted`, `excluded`, `undetermined` or None for all.

        Returns:
            Key to role.
        """
        return {n.key: n.role for n in self.nodes
                if n.role is not None and (decision is None or n.decision == decision)}


def design_of(unit_of_analysis: str) -> str:
    """The design implied by a unit of analysis.

    Args:
        unit_of_analysis: The record's `model_spec.unit_of_analysis` value.

    Returns:
        `cross_sectional` for one questionnaire per participant, else
        `repeated_measures`.
    """
    return CROSS_SECTIONAL if unit_of_analysis == "participant" else REPEATED_MEASURES


def _enum_value(x: Any) -> str:
    return str(getattr(x, "value", x))


def derive(p: ProtocolSpecification) -> CausalStructure:
    """Lay the record's roles out as a graph.

    Args:
        p: A validated record.

    Returns:
        The structure. Anchors are the first two nodes; the exposure-outcome
        edge is the first edge.
    """
    named = named_variables(p)
    (x_key, _, x_kind), (y_key, _, y_kind) = named[0], named[1]
    nodes = [Node(key=x_key, kind=x_kind, position="exposure"),
             Node(key=y_key, kind=y_kind, position="outcome")]
    edges = [Edge(source=x_key, target=y_key, relation="hypothesised")]
    entries = [(e, "adjusted") for e in p.adjusted_covariates]
    entries += [(e, "excluded") for e in p.excluded_variables]
    entries += [(e, "undetermined") for e in p.undetermined_covariates]
    for (key, _, kind), (entry, decision) in zip(named[2:], entries, strict=True):
        role = _enum_value(entry.role)
        nodes.append(Node(key=key, kind=kind, position="covariate", role=role,
                          decision=decision))
        relation = "proxies" if role == CausalRole.proxy.value else "causes"
        place = {"X": x_key, "Y": y_key, "C": key}
        for s, t in EDGES_BY_ROLE.get(role, ()):
            edges.append(Edge(source=place[s], target=place[t], relation=relation))
    unit = _enum_value(p.model_spec.unit_of_analysis)
    return CausalStructure(
        design=design_of(unit), unit_of_analysis=unit, exposure=x_key, outcome=y_key,
        expected_direction=_enum_value(p.expected_direction.direction),
        nodes=tuple(nodes), edges=tuple(edges),
        adjustment_set=tuple(n.key for n in nodes if n.decision == "adjusted"))
