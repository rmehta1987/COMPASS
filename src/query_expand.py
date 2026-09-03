"""Deterministic query expansion: the template, pre-registered.

FUSION.md sec 1 found that what predicts retrieval accuracy on the fixture is
query INFORMATIVENESS -- the absolute count of shared content words, rho 0.186,
perm p 0.005 -- and that R@1 climbs 0.493 -> 0.537 -> 0.676 from 1-2 to 3 to 4+
content words. The fixture's queries are terse lookup labels by instruction.
The pipeline's specifier is in the opposite position: when it needs a variable
it already knows the construct, the role, the population and the timeframe.
This module puts that back with a TEMPLATE -- no model call, no network, same
input -> same query -> same variable, every run -- so the abstention decision
stays reproducible, which FUSION.md sec 4 showed a rewriter cannot guarantee.

    from query_expand import RetrievalRequest, VariableRole
    RetrievalRequest("sibling prostate cancer", VariableRole.EXPOSURE,
                     population="sibling", timeframe=None,
                     instances=("Prostate cancer",)).to_query()
    -> "sibling prostate cancer"          # every term already present: unchanged

    python src/query_expand.py --preregister out/qx_preregistration.json

THE TEMPLATE  (RetrievalRequest.to_query)
------------------------------------------
    [population] construct [timeframe][: instance, instance, ...]

  * `construct` is emitted verbatim. It is the request as the specifier wrote
    it; on the fixture it is the row's own query.
  * `population` is prepended only when it is not None AND its content words
    are not already in the construct (light-stemmed; see `covered`).
  * `timeframe` is appended under the same rule.
  * each `instance` is appended, comma-separated after a colon, unless ALL of
    its content words already appear in the text built so far.
  * `role` is NOT rendered. Exposure / outcome / confounder names the analysis
    the variable will sit in, not the construct; no instrument stem says
    "exposure". It is carried on the dataclass because the pipeline needs it
    downstream, and deliberately kept out of the query as padding.

  The "already covered" rule exists so the expansion is strictly additive
  information: a term that is already in the request adds nothing but a
  repeat, and FUSION.md sec 1 says the mechanism is shared-word COUNT, which a
  repeat does not raise.

  What is deliberately NOT added: any wording of the STRUCTURE the target sits
  in. FUSION.md sec 4's worked loss -- `sibling prostate cancer` falling from
  rank 1 to 2 when "sibling" became "your brother or sister", the roster
  block's own wording -- is the failure this rule avoids. The population noun
  is the specifier's relationship word ("sibling"), never the block's stem.

SOURCE OF THE FIELDS ON THE FIXTURE ROWS  (`fields_from_target`)
----------------------------------------------------------------
This is the experiment's main threat and is therefore fixed here, before any
result is seen. The specifier at query time knows the construct, population,
timeframe and instances from the HYPOTHESIS, not from the codebook. The fixture
has no specifier, so its rows' fields are derived from the gold target's
metadata as a stand-in for that knowledge -- and ONLY from metadata that
encodes something the specifier would genuinely know:

  construct   the row's own query, verbatim. Nothing from the gold's stem.
  population  the ROSTER BLOCK the target belongs to, looked up in
              POPULATION_BY_ROSTER_BLOCK below. A roster target is a per-person
              repeat of one question (targets.json::roster_family_size non-null)
              and the block it sits in is one relationship class in the
              instrument's household roster: m1:Q6 household member, m2:Q8
              pregnancy, m2:Q16 sibling, m2:Q18 child. The specifier asking for
              a sibling's cancer history knows it is a sibling. Non-roster
              targets get None: the questions about "your mother" / "your
              father" are NOT roster items, so no population is supplied for
              them even though a specifier would have one -- the metadata does
              not carry it, and reading it off the stem would be copying the
              gold. Family size alone does NOT identify the population (the
              size-20 family in module 2 holds both the pregnancy roster and
              the sibling roster), which is why the key is the block.
  timeframe   None on every row. dictionary.json carries no timeframe field;
              the only place it lives is the stem text, and extracting it from
              there is reading the gold. This slot is therefore UNTESTED by the
              fixture experiment and is a specifier-supplied field in the
              pipeline.
  instances   (option,) when the target is a MATRIX COLUMN
              (targets.json::matrix_col non-null), else (). A matrix column's
              label is the instance the specifier is asking for -- "Prostate
              cancer", "Angina", "Playing tennis, squash or racquetball" -- and
              is the codebook's rendering of a thing the specifier already
              names in the request. Grid sub-items and text companions
              (`option` in {"Text", "AM/PM", "City", "Product 2", ...}) are NOT
              instances: they name the structure of the item, which is exactly
              what the template must not add. The rule is structural
              (matrix_col), not a word list, so it is applied blind; it admits
              a few unit-like columns ("Feet", "Minutes") as the price of not
              hand-curating.

  This is the most leak-prone field and it is kept because the alternative --
  a specifier who wants sibling prostate cancer and cannot say "prostate
  cancer" -- is the fixture's artificial constraint, not the pipeline's. The
  paired experiment reports the template with and without the instances slot
  (arms F and P) so the reader can see how much of any gain rests on it.

  The fields could also be read as "the whole option SET of the block". That
  reading is rejected: appending all 22 cancer types to every cancer request
  is padding that names the block, and FUSION.md sec 1 says count of SHARED
  words is the mechanism, not length.

SOURCE OF THE FIELDS ON THE NEGATIVES
-------------------------------------
A negative has no gold target and so no metadata. Its fields are what a
specifier would have for a construct that does not exist: population from the
request (only n44 asks about someone other than the participant), instances as
one to three concrete examples or synonyms a domain analyst would list, hand-
written per row from the request text alone -- no corpus lookup, no score seen
-- and committed in fixtures/negative_expansion_fields.json with its sha256 in
the pre-registration. Timeframe None, mirroring the positives. The asymmetry
(positives' instances come from the codebook, negatives' from an analyst's
head) is stated, not hidden, and arm P (population only) bounds it.
"""
from __future__ import annotations

import argparse
import enum
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from phrase_overlap import content_words          # noqa: E402  (doc_stem tokenisation)


class VariableRole(str, enum.Enum):
    EXPOSURE = "exposure"
    OUTCOME = "outcome"
    CONFOUNDER = "confounder"


# The population noun for each roster block of the instrument. Keyed on
# (module, question block) because roster_family_size is not unique: module 2
# size 20 is both Q8 (pregnancies) and Q16 (siblings). The noun is the
# relationship the specifier asks about, NOT the block's stem wording.
POPULATION_BY_ROSTER_BLOCK: dict[tuple[str, str], str] = {
    ("1", "Q6"): "household member",
    ("2", "Q8"): "pregnancy",
    ("2", "Q16"): "sibling",
    ("2", "Q18"): "child",
}

_BLOCK_RE = re.compile(r"^m(\d+):(Q\d+)")


def covered(phrase: str, text: str) -> bool:
    """True when every content word of `phrase` is already in `text`.
    Empty phrases (all stopwords) count as covered: nothing to add."""
    p = content_words(phrase, True)
    return not p or p <= content_words(text, True)


@dataclass(frozen=True)
class RetrievalRequest:
    construct: str                     # "nonsteroidal anti-inflammatory medication use"
    role: VariableRole                 # exposure / outcome / confounder -- NOT rendered
    population: str | None = None      # "participant" | "sibling" | "household member"
    timeframe: str | None = None       # "past 12 months" | "lifetime" | "current"
    instances: tuple[str, ...] = ()    # ("ibuprofen", "naproxen", "aspirin")

    def to_query(self, *, with_instances: bool = True) -> str:
        """Deterministic template. No model call, no network."""
        text = self.construct.strip()
        pop = (self.population or "").strip()
        if pop and pop.lower() != "participant" and not covered(pop, text):
            text = f"{pop} {text}"
        tf = (self.timeframe or "").strip()
        if tf and not covered(tf, text):
            text = f"{text} {tf}"
        if with_instances:
            added = []
            for inst in self.instances:
                inst = inst.strip()
                if inst and not covered(inst, text + " " + " ".join(added)):
                    added.append(inst)
            if added:
                text = f"{text}: {', '.join(added)}"
        return text


def fields_from_target(query: str, target: dict,
                       role: VariableRole = VariableRole.EXPOSURE) -> RetrievalRequest:
    """Fixture-row stand-in for the specifier: fields from the gold target's
    METADATA only (roster block -> population, matrix column -> instance).
    Never reads the stem."""
    population = None
    if target.get("roster_family_size"):
        m = _BLOCK_RE.match(target["construct_key"])
        if m is None:
            raise ValueError(f"unparseable construct_key {target['construct_key']!r}")
        population = POPULATION_BY_ROSTER_BLOCK.get((m.group(1), m.group(2)))
        if population is None:
            raise ValueError(f"roster block {m.groups()} has no population noun; "
                             f"add it to POPULATION_BY_ROSTER_BLOCK")
    instances: tuple[str, ...] = ()
    if target.get("matrix_col") is not None and target.get("option"):
        instances = (target["option"],)
    return RetrievalRequest(construct=query, role=role, population=population,
                            timeframe=None, instances=instances)


def fields_from_negative(neg_row: dict, fields: dict,
                         role: VariableRole = VariableRole.EXPOSURE) -> RetrievalRequest:
    f = fields[neg_row["id"]]
    return RetrievalRequest(construct=neg_row["query"], role=role,
                            population=f.get("population"), timeframe=None,
                            instances=tuple(f.get("instances") or ()))


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ------------------------------------------------------------- pre-registration

def preregister(out: Path, fixture: Path, targets: Path, negatives: Path,
                neg_fields: Path) -> dict:
    """Render every expanded query for the 224 rows and 44 negatives and write
    them, with the template file's sha256, BEFORE anything is scored."""
    this = Path(__file__).resolve()
    T = json.loads(targets.read_text())
    by_key = {m: t for t in T["targets"] for m in t["members"]}
    rows = json.loads(fixture.read_text())["queries"]
    negs = json.loads(negatives.read_text())["queries"]
    NF = json.loads(neg_fields.read_text())
    nf = {x["id"]: x for x in NF["fields"]}
    missing = [n["id"] for n in negs if n["id"] not in nf]
    if missing:
        raise SystemExit(f"negative fields missing for {missing}")

    pos = []
    for i, x in enumerate(rows):
        rq = fields_from_target(x["query"], by_key[x["key"]])
        pos.append({"row": i, "gold_key": x["key"], "query": x["query"],
                    "population": rq.population, "instances": list(rq.instances),
                    "expanded_F": rq.to_query(with_instances=True),
                    "expanded_P": rq.to_query(with_instances=False)})
    neg = []
    for x in negs:
        rq = fields_from_negative(x, nf)
        neg.append({"id": x["id"], "query": x["query"],
                    "population": rq.population, "instances": list(rq.instances),
                    "expanded_F": rq.to_query(with_instances=True),
                    "expanded_P": rq.to_query(with_instances=False)})

    def n_changed(lst, arm):
        return sum(1 for r in lst if r[arm] != r["query"])

    rep = {
        "schema": "compass_query_expansion_preregistration/1",
        "registered": "2026-09-03",
        "template_file": str(this.relative_to(Path.cwd())) if this.is_relative_to(Path.cwd()) else str(this),
        "template_sha256": sha256_file(this),
        "negative_fields_file": str(neg_fields),
        "negative_fields_sha256": sha256_file(neg_fields),
        "fixture_sha256": sha256_file(fixture),
        "negatives_sha256": sha256_file(negatives),
        "targets_sha256": sha256_file(targets),
        "dictionary_version_hash": T["dictionary_version_hash"],
        "template": "[population] construct [timeframe][: instance, ...]  "
                    "-- see src/query_expand.py docstring for every rule",
        "arms": {
            "S": "the row's own query, unchanged (control; must reproduce R@1 0.567 row for row)",
            "P": "template with population only (instances slot disabled)",
            "F": "template in full: population + instances. PRIMARY.",
        },
        "field_sources_fixture": {
            "construct": "row's own query verbatim",
            "population": "POPULATION_BY_ROSTER_BLOCK[(module, block)] when the gold "
                          "target is a roster repeat, else None",
            "timeframe": "None on every row (no metadata source; UNTESTED here)",
            "instances": "(gold option,) when matrix_col is non-null, else ()",
            "role": "not rendered",
        },
        "field_sources_negatives": {
            "construct": "the request verbatim",
            "population": "from the request text; hand-authored, only where the "
                          "request is about someone other than the participant",
            "timeframe": "None on every row",
            "instances": "1-3 concrete examples/synonyms an analyst would list, "
                         "hand-authored from the request text alone, no corpus "
                         "lookup, no score seen",
        },
        "decision_rule_recorded_before_running": (
            "Arm F vs arm S on all 224 rows: if the item-clustered bootstrap 95% CI "
            "on delta R@1 excludes zero AND the point estimate exceeds +0.05, the "
            "template is justified and ships (subject to task 3). If the CI contains "
            "zero it does not ship regardless of the point estimate. Arm P is "
            "diagnostic only and does not decide."),
        "predictions_recorded_before_running": [
            "The 10 items at 0/4 stay at 0/4 unless the expansion supplies a "
            "discriminator; by construction only the roster/matrix ones can change.",
            "The largest effect is in the 1-2 content-word subgroup.",
            "Expanded negatives score higher than unexpanded; the shipped tau "
            "0.7295 may reject fewer than 43/44 and need re-deriving once.",
        ],
        "what_was_seen_before_registering": (
            "FUSION.md and CHARACTERISATION.md in full (they name the 10 items at "
            "0/4 and per-stratum recall); the 56 gold targets' metadata and stems "
            "listed once to design fields_from_target; the 44 negative requests "
            "to author their fields. NOT opened: out/char_pos_bge-small_ft.json "
            "rows, out/fusion_task1_overlap.json rows, any per-row rank or "
            "correctness, or the 224 queries beyond the first six."),
        "counts": {
            "positive_rows": len(pos),
            "positive_rows_changed_F": n_changed(pos, "expanded_F"),
            "positive_rows_changed_P": n_changed(pos, "expanded_P"),
            "positive_items_changed_F": len({r["gold_key"] for r in pos
                                             if r["expanded_F"] != r["query"]}),
            "positive_rows_with_population": sum(1 for r in pos if r["population"]),
            "positive_rows_with_instances": sum(1 for r in pos if r["instances"]),
            "negative_rows": len(neg),
            "negative_rows_changed_F": n_changed(neg, "expanded_F"),
            "negative_rows_changed_P": n_changed(neg, "expanded_P"),
        },
        "positives": pos,
        "negatives": neg,
    }
    out.write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preregister", type=Path, required=True)
    ap.add_argument("--fixture", type=Path, default=Path("retrieval_queries.json"))
    ap.add_argument("--targets", type=Path, default=Path("deploy/targets.json"))
    ap.add_argument("--negatives", type=Path,
                    default=Path("fixtures/negative_requests.json"))
    ap.add_argument("--neg-fields", type=Path,
                    default=Path("fixtures/negative_expansion_fields.json"))
    a = ap.parse_args()
    rep = preregister(a.preregister, a.fixture, a.targets, a.negatives, a.neg_fields)
    c = rep["counts"]
    print(f"template sha256 {rep['template_sha256']}")
    print(f"negative fields sha256 {rep['negative_fields_sha256']}")
    print(f"positives: {c['positive_rows_changed_F']}/{c['positive_rows']} rows "
          f"({c['positive_items_changed_F']} items) change under F, "
          f"{c['positive_rows_changed_P']} under P; "
          f"{c['positive_rows_with_population']} rows carry a population, "
          f"{c['positive_rows_with_instances']} an instance")
    print(f"negatives: {c['negative_rows_changed_F']}/{c['negative_rows']} change "
          f"under F, {c['negative_rows_changed_P']} under P")
    print(f"-> {a.preregister}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
