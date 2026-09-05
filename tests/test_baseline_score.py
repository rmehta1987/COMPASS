"""The baseline harness on an injected key table; the real key never loads here."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, ClassVar

import pytest

from benchmark import baseline_score as B
from pipeline import ledger as L
from pipeline.artefact import SpecifierArtefact, VariableProvenance
from pipeline.causal_structure import CausalStructure, Edge, Node
from pipeline.generation_env import GenerationEnv
from pipeline.hypothesis import HypothesisRecord
from pipeline.retrieval_record import Hit, RequestSnapshot, RetrievalRecord

TAU = 0.729476
HASH = "3dc8415eccfe"
SHA = "a" * 40
CLEAN = GenerationEnv(key_present=False, key_fetchable=False, tree_sha=SHA,
                      tree_clean=True, branch="ralph-loop")


class FakeRetriever:
    """Three targets; a query naming one lands on it, anything else abstains."""

    min_cos = TAU
    manifest: ClassVar[dict[str, Any]] = {"dictionary_version_hash": HASH}
    targets: ClassVar[list[dict[str, Any]]] = [
        {"target_id": 1, "canonical_key": "m2:Q9.95", "construct_key": "m2:Q9.95",
         "module": "2", "stem": "ever used hormone therapy for menopause", "option": "O",
         "fold_size": 1, "siblings": [], "members": ["m2:Q9.95"]},
        {"target_id": 2, "canonical_key": "m2:Q5.2", "construct_key": "m2:Q5",
         "module": "2", "stem": "diagnosed high blood pressure hypertension",
         "option": "O", "fold_size": 1, "siblings": [], "members": ["m2:Q5.2"]},
        {"target_id": 3, "canonical_key": "m1:Q5.4", "construct_key": "m1:Q5.4",
         "module": "1", "stem": "total household income", "option": "O",
         "fold_size": 1, "siblings": [], "members": ["m1:Q5.4"]},
    ]
    cue: ClassVar[dict[str, int]] = {"hormone": 1, "hypertension": 2, "income": 3}

    def search(self, query: str, k: int = 10) -> list[dict[str, Any]]:
        hit = next((t for w, t in self.cue.items() if w in query), None)
        out = []
        for t in self.targets:
            cos = 0.9 if t["target_id"] == hit else 0.3
            out.append({"target_id": t["target_id"], "key": t["canonical_key"],
                        "construct_key": t["construct_key"], "module": t["module"],
                        "stem": t["stem"], "option": t["option"],
                        "fold_size": t["fold_size"], "n_siblings": 0,
                        "members": t["members"], "cos": cos})
        out.sort(key=lambda h: -h["cos"])
        return out[:k]


def _rec(role: str, key: str, ck: str, stratum: str, h: str = HASH) -> RetrievalRecord:
    return RetrievalRecord(
        request=RequestSnapshot(construct_text="sha256:x", role=role,
                                source="instrument"),
        query="sha256:x", dictionary_hash=h, min_cos=TAU, best_cos=0.9, margin=0.9 - TAU,
        margin_12=0.1, abstained=False, nearest_key=key,
        hit=Hit(key=key, construct_key=ck, dict_construct_key=ck, module=ck[1],
                target_id=1, fold_size=1, n_siblings=0, members=(key,),
                stratum=stratum, unmeasured_stratum=False))


def _record(*, redacted: bool = True, h: str = HASH,
            env: GenerationEnv | None = CLEAN) -> HypothesisRecord:
    e = _rec("exposure", "m2:Q9.95", "m2:Q9.95", "reproductive_hormonal", h)
    o = _rec("outcome", "m2:Q5.2", "m2:Q5", "chronic_condition", h)
    art = SpecifierArtefact(
        protocol_id="p1", record_hash="r1", pair_id="m2:Q9.95->m2:Q5",
        estimability="blocked_no_metadata", protocol={"a": "b"},
        retrieval={"exposure": e, "outcome": o},
        variables=(VariableProvenance(key="m2:Q9.95", where="exposure", kind="variable",
                                      source="retrieval", retrieval=e),
                   VariableProvenance(key="m2:Q5.2", where="outcome", kind="variable",
                                      source="retrieval", retrieval=o)),
        redacted=redacted)
    st = CausalStructure(
        design="cross_sectional", unit_of_analysis="participant", exposure="m2:Q9.95",
        outcome="m2:Q5.2", expected_direction="positive",
        nodes=(Node(key="m2:Q9.95", kind="variable", position="exposure"),
               Node(key="m2:Q5.2", kind="variable", position="outcome")),
        edges=(Edge(source="m2:Q9.95", target="m2:Q5.2", relation="hypothesised"),))
    return HypothesisRecord(artefact=art, structure=st, generation=env)


def _run_dir(tmp_path: Path, rec: HypothesisRecord, name: str = "p1.r1.json",
             emitted_name: str | None = "p1.r1.json") -> Path:
    d = tmp_path / "baseline-x"
    d.mkdir()
    (d / name).write_text(rec.to_json() + "\n")
    led = L.Ledger(d, "baseline-x")
    common = {"exposure_key": "m2:Q9.95", "outcome_key": "m2:Q5",
              "exposure_stratum": "reproductive_hormonal",
              "outcome_stratum": "chronic_condition",
              "estimability": "blocked_no_metadata"}
    led.append(pair_id="a", outcome="gate_blocked", **common)
    led.append(pair_id="b", outcome="discarded", note="validator:temporality",
               **common)
    led.append(pair_id="c", outcome="emitted", protocol_id="p1", record_hash="r1",
               artefact=emitted_name, **common)
    led.write_summary()
    return d


TABLE = (
    B.PaperKey("36702470", ("hormone therapy",), ("m2:Q5.2",)),      # both sides
    B.PaperKey("11111111", ("hormone therapy",), ()),                # no outcome key
    B.PaperKey("22222222", ("community characteristics",), ("m2:Q5.2",)),  # abstains
    B.PaperKey("33333333", ("hormone therapy",), ("m2:Q5.9",)),      # outcome differs
    B.PaperKey("44444444", ("household income",), ("m2:Q5.2",)),     # exposure differs
)
OK = {"contamination_check": "ok", "input_leakage": "ok", "unearned_assertions": "ok"}


def test_a_match_needs_both_sides_and_the_denominator_is_the_ledgers(tmp_path):
    d = _run_dir(tmp_path, _record())
    b = B.score([d / "p1.r1.json"], table=TABLE, retriever=FakeRetriever(),
                verdicts=OK, require_sha=SHA[:12])
    assert (b.scored, b.matched, b.rate, b.denominator) == (1, 1, 1.0, 3)
    assert b.matches == (B.Match("p1.r1.json", "36702470", "m2:Q9.95", "m2:Q5.2"),)
    assert (b.papers, b.papers_with_outcome_key, b.papers_exposure_resolved,
            b.papers_matched) == (5, 4, 4, 1)
    assert b.exposure_abstentions == {"22222222": ("community characteristics",)}
    assert b.by_outcome == {"gate_blocked": 1, "discarded": 1, "emitted": 1}
    assert b.strata == ("chronic_condition", "reproductive_hormonal")
    assert b.generation == CLEAN and b.dictionary_hash == HASH
    assert b.verdicts == OK and b.qualifier == B.QUALIFIER
    # the ceiling: 36702470, 33333333 and 44444444 are matchable (outcome key
    # on record and an exposure that resolved); 22222222 abstained, 11111111
    # has no outcome key. The one artefact hits on both sides, so N == max.
    c = b.ceiling
    assert (c.papers_matchable, c.outcome_side, c.exposure_side,
            c.max_matched) == (3, 1, 1, 1)
    assert c.max_rate == 1.0 and c.at_ceiling
    text = B.render(b)
    assert B.QUALIFIER in text
    assert text.splitlines()[2].startswith("**Ceiling: at most 1 of 1 artefacts")
    assert "at its ceiling" in text.splitlines()[2]
    for cell in ("| matched (N) | 1 |", "(M) | 1 |", "| match rate N/M | 1.000 |",
                 "total_generated_this_run | 3 |", "PMID 36702470"):
        assert cell in text, cell


def test_keys_of_covers_variable_members_and_both_construct_names():
    rec = _rec("outcome", "m2:Q5.2", "m2:Q5", "chronic_condition")
    assert B.keys_of(rec) == {"m2:Q5.2", "m2:Q5"}
    assert B.keys_of(rec.model_copy(update={"hit": None, "abstained": True})) == set()


@pytest.mark.parametrize(("rec", "phrase"), [
    (_record(env=None), "no generation stamp"),
    (_record(env=CLEAN.model_copy(update={"key_present": True})), "key was reachable"),
    (_record(env=CLEAN.model_copy(update={"key_fetchable": True})), "key was reachable"),
    (_record(env=CLEAN.model_copy(update={"tree_clean": False})), "dirty tree"),
    (_record(env=CLEAN.model_copy(update={"tree_sha": "b" * 40})), "stamped at bbbb"),
    (_record(redacted=False), "not the redacted form"),
    (_record(h="000000000000"), "retrieved under 000000000000"),
])
def test_every_refusal_is_fatal(tmp_path, rec, phrase):
    d = _run_dir(tmp_path, rec)
    with pytest.raises(B.Refused, match=phrase):
        B.score([d / "p1.r1.json"], table=TABLE, retriever=FakeRetriever(),
                verdicts=OK, require_sha=SHA[:12])


def test_the_scored_set_must_be_exactly_the_ledgers_emitted_set(tmp_path):
    d = _run_dir(tmp_path, _record())
    extra = d / "p2.r2.json"
    extra.write_text(_record().to_json())
    with pytest.raises(B.Refused, match=r"p2\.r2\.json.*not emitted"):
        B.score([d / "p1.r1.json", extra], table=TABLE, retriever=FakeRetriever(),
                verdicts=OK)
    with pytest.raises(B.Refused, match=r"p1\.r1\.json.*emitted but not given"):
        B.score([extra], table=TABLE, retriever=FakeRetriever(), verdicts=OK)
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "p1.r1.json").write_text(_record().to_json())
    with pytest.raises(B.Refused, match="span 2 run directories"):
        B.score([d / "p1.r1.json", other / "p1.r1.json"], table=TABLE,
                retriever=FakeRetriever(), verdicts=OK)
    with pytest.raises(B.Refused, match="no artefact paths"):
        B.score([], table=TABLE, retriever=FakeRetriever(), verdicts=OK)


def test_a_red_halting_verdict_stops_before_anything_is_read(tmp_path):
    missing = [tmp_path / "nothing" / "p1.r1.json"]
    for name in B.HALTING:
        bad = {**OK, name: "FAIL (exit 1)"}
        with pytest.raises(B.Refused, match=f"halting verdict: {name}=FAIL"):
            B.score(missing, table=TABLE, retriever=FakeRetriever(), verdicts=bad)
    with pytest.raises(B.Refused, match="contamination_check=missing"):
        B.score(missing, table=TABLE, retriever=FakeRetriever(), verdicts={})
    # advisory never halts: the refusal that follows is the missing ledger
    d = _run_dir(tmp_path, _record())
    b = B.score([d / "p1.r1.json"], table=TABLE, retriever=FakeRetriever(),
                verdicts={**OK, "unearned_assertions": "advisory (2 hits)"})
    assert b.verdicts["unearned_assertions"] == "advisory (2 hits)"


def test_the_key_side_modules_are_imported_inside_functions_only():
    """The harness must load where the key is unreachable, which is this clone."""
    src = (Path(B.__file__)).read_text()
    tree = ast.parse(src)
    top = {n.module or "" for n in tree.body if isinstance(n, ast.ImportFrom)}
    top |= {a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names}
    for key_side in ("scorability", "contamination_check", "input_leakage",
                     "unearned_assertions", "prevalence_key", "leak_facts"):
        assert not any(key_side in m for m in top), key_side
    inner = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
             and n.module and n.module.startswith("benchmark.")]
    assert {n.module for n in inner} >= {"benchmark.scorability",
                                         "benchmark.input_leakage",
                                         "benchmark.unearned_assertions"}


def test_a_zero_ceiling_names_itself_as_not_a_measurement(tmp_path):
    d = _run_dir(tmp_path, _record())
    unmatchable = (B.PaperKey("36702470", ("household income",), ("m2:Q5.9",)),)
    b = B.score([d / "p1.r1.json"], table=unmatchable, retriever=FakeRetriever(),
                verdicts=OK, require_sha=SHA[:12])
    assert b.matched == 0 and b.ceiling.max_matched == 0 and b.ceiling.at_ceiling
    assert b.ceiling.papers_matchable == 1 and b.ceiling.max_rate == 0.0
    line = B.render(b).splitlines()[2]
    assert "The observed rate IS the ceiling" in line
    assert "not a measurement of hypothesis quality" in line
    # a matchable paper the artefact misses on one side only: ceiling above N
    one_side = (B.PaperKey("36702470", ("hormone therapy",), ("m2:Q5.9",)),
                B.PaperKey("44444444", ("household income",), ("m2:Q5.2",)))
    b = B.score([d / "p1.r1.json"], table=one_side, retriever=FakeRetriever(),
                verdicts=OK, require_sha=SHA[:12])
    assert b.matched == 0 and b.ceiling.max_matched == 1 and not b.ceiling.at_ceiling
    assert "gap below the ceiling is the pipeline's" in B.render(b).splitlines()[2]
