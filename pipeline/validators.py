"""Deterministic validators over the typed causal structure.

Each validator reads the `HypothesisRecord`'s graph and the pair it was built
from, and returns zero or more `Critique`s with `source ==
"validator:<name>"`. None raises: a rejection is a typed objection on the
record, so the hypothesis and the reason it was rejected travel together and
a reviewer sees both. `apply()` attaches the critiques; `blocking()` says
whether any of them stops the hypothesis from shipping.

Four validators, all checkable without a model and regression-tested by
seeding a violation:

temporality        a mediator, a descendant of the exposure or a
                   confounder-or-mediator asserted under a cross-sectional
                   design claims a temporal order one questionnaire cannot
                   establish; the mediator claim is blocking.
dag_consistency    the graph is acyclic, the hypothesised edge is present,
                   every adjusted node touches an anchor, and no adjusted node
                   sits on a directed path from the exposure to the outcome.
cell_counts        when an analytic n and the design's `at_n` both exist and
                   n falls short, the design is not falsifiable at its own
                   floor. With no n there is nothing to check; the gate
                   already marks the record blocked_no_metadata.
measurement_level  a grid-battery anchor referenced as a bare variable needs
                   a signed derivation; a free-text anchor carries no coding.
"""

from __future__ import annotations

from collections.abc import Callable

from agent.schema import CausalRole
from pipeline.causal_structure import CROSS_SECTIONAL, CausalStructure
from pipeline.hypothesis import Critique, HypothesisRecord
from pipeline.resolved_pair import ResolvedPair

Validator = Callable[[HypothesisRecord, ResolvedPair], tuple[Critique, ...]]


def _crit(name: str, category: str, statement: str, severity: str,
          key: str | None = None) -> Critique:
    return Critique(source=f"validator:{name}", category=category, statement=statement,
                    grounding_key=key, severity=severity, resolved=False)


def temporality(rec: HypothesisRecord, pair: ResolvedPair) -> tuple[Critique, ...]:
    """Reject temporal-order claims a cross-sectional design cannot support.

    Args:
        rec: The record.
        pair: Its pair (unused; the structure carries the design).

    Returns:
        A blocking critique per mediator, a major one per descendant-of-exposure
        or confounder-or-mediator, when the design is cross-sectional.
    """
    s = rec.structure
    if s.design != CROSS_SECTIONAL:
        return ()
    out: list[Critique] = []
    for n in s.nodes:
        if n.role == CausalRole.mediator.value:
            out.append(_crit("temporality", "identification",
                             f"{n.key} is asserted to mediate {s.exposure} -> "
                             f"{s.outcome}, but the design is cross-sectional "
                             f"(unit {s.unit_of_analysis!r}): one questionnaire "
                             f"cannot order exposure before mediator before outcome",
                             "blocking", n.key))
        elif n.role in (CausalRole.descendant_of_exposure.value,
                        CausalRole.confounder_or_mediator.value):
            out.append(_crit("temporality", "identification",
                             f"{n.key} carries role {n.role!r}, a temporal claim a "
                             f"cross-sectional design cannot settle",
                             "major", n.key))
    return tuple(out)


def _reaches(s: CausalStructure, src: str, dst: str) -> bool:
    seen: set[str] = set()
    stack = [src]
    while stack:
        k = stack.pop()
        if k == dst:
            return True
        if k in seen:
            continue
        seen.add(k)
        stack.extend(e.target for e in s.edges if e.source == k)
    return False


def dag_consistency(rec: HypothesisRecord, pair: ResolvedPair) -> tuple[Critique, ...]:
    """Check the graph's invariants.

    Args:
        rec: The record.
        pair: Its pair (unused).

    Returns:
        Blocking critiques for a cycle, a missing hypothesised edge, or an
        adjusted node on the exposure-outcome path; a major one for an adjusted
        node touching neither anchor.
    """
    s = rec.structure
    out: list[Critique] = []
    if not any(e.source == s.exposure and e.target == s.outcome and
               e.relation == "hypothesised" for e in s.edges):
        out.append(_crit("dag_consistency", "identification",
                         "the exposure -> outcome edge under test is absent",
                         "blocking"))
    for n in s.nodes:
        if _reaches(s, n.key, n.key) and any(e.source == n.key for e in s.edges):
            # a node that reaches itself through at least one edge is on a cycle
            if any(_reaches(s, e.target, n.key) for e in s.edges if e.source == n.key):
                out.append(_crit("dag_consistency", "identification",
                                 f"{n.key} lies on a cycle", "blocking", n.key))
    for key in s.adjustment_set:
        touches = any((e.source == key and e.target in (s.exposure, s.outcome)) or
                      (e.target == key and e.source in (s.exposure, s.outcome))
                      for e in s.edges)
        if not touches:
            out.append(_crit("dag_consistency", "confounding",
                             f"{key} is adjusted for but touches neither anchor",
                             "major", key))
        if _reaches(s, s.exposure, key) and _reaches(s, key, s.outcome):
            out.append(_crit("dag_consistency", "identification",
                             f"{key} is adjusted for but lies on a directed path "
                             f"from {s.exposure} to {s.outcome}: adjusting for it "
                             f"blocks the effect under test", "blocking", key))
    return tuple(out)


def cell_counts(rec: HypothesisRecord, pair: ResolvedPair) -> tuple[Critique, ...]:
    """Compare the analytic n with the design's own falsifiability floor.

    Args:
        rec: The record.
        pair: Its pair (unused).

    Returns:
        A blocking feasibility critique when n is known and below `at_n`;
        nothing when either is unknown, since the gate already marks that.
    """
    est = rec.artefact.protocol.get("estimability", {})
    n = est.get("analytic_n")
    at_n = (est.get("smallest_detectable_effect") or {}).get("at_n")
    if n is None or at_n is None:
        return ()
    if int(n) < int(at_n):
        return (_crit("cell_counts", "feasibility",
                      f"analytic n {n} is below the n={at_n} this design commits "
                      f"to being falsifiable at", "blocking"),)
    return ()


def measurement_level(rec: HypothesisRecord, pair: ResolvedPair) -> tuple[Critique, ...]:
    """Check each anchor's reference against what its construct can carry.

    Args:
        rec: The record.
        pair: Its pair, whose constructs know whether they are grid batteries
            or free text.

    Returns:
        Blocking measurement critiques.
    """
    s = rec.structure
    out: list[Critique] = []
    for node, con in ((s.nodes[0], pair.exposure), (s.nodes[1], pair.outcome)):
        if con.is_free_text:
            out.append(_crit("measurement_level", "measurement",
                             f"{node.position} {con.construct_key} is free text "
                             f"and carries no coding", "blocking", node.key))
        elif con.is_group and node.kind == "variable":
            out.append(_crit("measurement_level", "measurement",
                             f"{node.position} {con.construct_key} is a grid "
                             f"battery referenced as a bare variable; it needs a "
                             f"signed derivation", "blocking", node.key))
    return tuple(out)


VALIDATORS: tuple[Validator, ...] = (temporality, dag_consistency, cell_counts,
                                     measurement_level)


def validate(rec: HypothesisRecord, pair: ResolvedPair,
             validators: tuple[Validator, ...] = VALIDATORS) -> tuple[Critique, ...]:
    """Run every validator.

    Args:
        rec: The record.
        pair: Its pair.
        validators: The validators to run, in order.

    Returns:
        Every critique raised, in validator order.
    """
    out: list[Critique] = []
    for v in validators:
        out.extend(v(rec, pair))
    return tuple(out)


def blocking(critiques: tuple[Critique, ...]) -> bool:
    """Whether any critique stops the hypothesis from shipping.

    Args:
        critiques: The critiques.

    Returns:
        True when one is unresolved and blocking.
    """
    return any(c.severity == "blocking" and not c.resolved for c in critiques)


def apply(rec: HypothesisRecord, pair: ResolvedPair,
          validators: tuple[Validator, ...] = VALIDATORS) -> HypothesisRecord:
    """Attach the validators' critiques to the record.

    Args:
        rec: The record; its existing critiques are kept.
        pair: Its pair.
        validators: The validators to run.

    Returns:
        A copy carrying the critiques. `revision` is untouched: a critique is
        not a revision.
    """
    found = validate(rec, pair, validators)
    return rec.model_copy(update={"critiques": rec.critiques + found})


def rejected_note(critiques: tuple[Critique, ...]) -> str:
    """The ledger note for a rejected record.

    Args:
        critiques: The critiques.

    Returns:
        The blocking sources, joined; empty when none is blocking.
    """
    return "; ".join(sorted({c.source for c in critiques
                             if c.severity == "blocking" and not c.resolved}))
