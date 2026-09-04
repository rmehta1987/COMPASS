"""Item 15a: the run driver end to end on the scripted backend, no model."""

from __future__ import annotations

import json

import pytest

from agent.backends import Reply, ScriptedBackend
from generate.funnel import Candidate, load_constructs
from generate.funnel import run as funnel_run
from generate.run_specifier import ANALYSIS, REASON_CALLS_A, REASON_CALLS_B, fixture
from pipeline import auto_intake, hypothesis, ledger
from pipeline import run as R
from pipeline.gate import BLOCKED
from pipeline.retrieval_record import Hit, RequestSnapshot, RetrievalRecord

TAU = 0.729476


def _rec(role: str, key: str, ck: str, members: tuple[str, ...],
         stratum: str) -> RetrievalRecord:
    return RetrievalRecord(
        request=RequestSnapshot(construct_text="stem", role=role, source="instrument"),
        query="stem", dictionary_hash="h", min_cos=TAU, best_cos=0.9, margin=0.9 - TAU,
        margin_12=0.1, abstained=False, nearest_key=key,
        hit=Hit(key=key, construct_key=ck, dict_construct_key=ck, module=ck[1],
                target_id=1, fold_size=1, n_siblings=0, members=members,
                stratum=stratum, unmeasured_stratum=False))


@pytest.fixture(scope="module")
def frame():
    try:
        C, version = load_constructs()
    except FileNotFoundError:
        pytest.skip("build/dictionary.json is withheld from the public tree")
    exposures = sorted([c for c in C.values() if c.module == "3"
                        and c.base_id.startswith("Q16.")], key=lambda c: c.base_id)
    outcomes = sorted([c for c in C.values() if c.module == "2"
                       and c.base_id.startswith("Q5.")], key=lambda c: c.base_id)
    cands, counts = funnel_run(exposures, outcomes)
    worked = next(c for c in cands if c.exposure.construct_key == "m3:Q16.1"
                  and c.outcome.construct_key == "m2:Q5.8")
    other = next(c for c in cands if c.state == "live" and c is not worked)
    return C, version, counts, worked, other


def _resolver(resolve_second: bool) -> R.Resolver:
    def resolve(cand: Candidate) -> auto_intake.PairResolution:
        e, o = cand.exposure, cand.outcome
        rec_e = _rec("exposure", e.member_keys[0], e.construct_key,
                     tuple(e.member_keys), "residence_commute")
        ok_o = resolve_second or cand.outcome.construct_key == "m2:Q5.8"
        rec_o = _rec("outcome", o.member_keys[0], o.construct_key if ok_o else "m9:Q0",
                     tuple(o.member_keys), "chronic_condition")
        return auto_intake.PairResolution(cand.pair_id, rec_e, rec_o, True, ok_o)
    return resolve


def _backend(version: str, screened_from: int) -> ScriptedBackend:
    record = fixture(version, screened_from)
    return ScriptedBackend([Reply(tool_calls=REASON_CALLS_A),
                            Reply(tool_calls=REASON_CALLS_B),
                            Reply(content=ANALYSIS), Reply(content=record)])


def test_the_driver_writes_one_ledger_row_per_gated_pair_and_redacted_artefacts(
        frame, tmp_path):
    C, version, counts, worked, other = frame
    run_dir = tmp_path / "baseline-test"
    summary = R.run([worked, other], backend=_backend(version, counts["enumerated"]),
                    resolver=_resolver(resolve_second=False), constructs=C,
                    version=version, screened_from=counts["enumerated"],
                    run_dir=run_dir, k=1, allow_unestimable=True, log=lambda s: None)
    rows = ledger.Ledger(run_dir).rows()
    assert summary.total_generated_this_run == len(rows) == 2
    assert ledger.verify(run_dir).by_outcome == summary.by_outcome
    by = {r.pair_id: r for r in rows}
    # the second pair did not resolve: discarded at intake, no model call spent
    assert by[other.pair_id].outcome == "discarded"
    assert "auto_intake" in by[other.pair_id].note
    # the worked pair produced the fixture record, which the temporality
    # validator rejects (a mediator under a cross-sectional design)
    w = by[worked.pair_id]
    assert w.outcome == "discarded" and w.note == "validator:temporality"
    assert w.artefact and (run_dir / w.artefact).exists()
    assert w.estimability == BLOCKED and w.exposure_stratum == "residence_commute"
    art = hypothesis.HypothesisRecord.from_json((run_dir / w.artefact).read_text())
    assert art.artefact.redacted and art.generation is None
    assert any(c.source == "validator:temporality" for c in art.critiques)
    # the artefact carries the record's hash and a trace for every variable;
    # the wording is digested, so the committed file re-validates only after
    # the scoring clone rehydrates it by key
    assert art.artefact.record_hash == w.record_hash
    assert all(v.startswith("sha256:") for v in _wordings(art.artefact.protocol))
    assert {v.where for v in art.artefact.variables} >= {"exposure", "outcome"}
    assert (run_dir / ledger.SUMMARY_NAME).exists()


def _wordings(node: object) -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "quoted_wording" and isinstance(v, str):
                out.append(v)
            else:
                out.extend(_wordings(v))
    elif isinstance(node, list):
        for x in node:
            out.extend(_wordings(x))
    return out


def test_without_the_flag_nothing_reaches_the_model(frame, tmp_path):
    C, version, counts, worked, _ = frame

    class Explode:
        name = "explode"

        def chat(self, *a: object, **k: object) -> None:
            raise AssertionError("the model was called")

    summary = R.run([worked], backend=Explode(), resolver=_resolver(True), constructs=C,
                    version=version, screened_from=counts["enumerated"],
                    run_dir=tmp_path / "r", k=1, allow_unestimable=False,
                    log=lambda s: None)
    assert summary.by_outcome == {"gate_blocked": 1}


def test_subset_is_seeded_and_order_stable(frame):
    _, _, _, worked, other = frame
    cands = [worked, other] * 5
    a = R.subset(cands, 4, 0)
    b = R.subset(cands, 4, 0)
    assert a == b and len(a) == 4
    assert R.subset(cands, None, 0) == cands
    assert [cands.index(x) for x in a] == sorted(cands.index(x) for x in a)


def test_stamp_run_refuses_an_unclean_env_and_stamps_every_artefact(frame, tmp_path):
    from pipeline.generation_env import GenerationEnv
    C, version, counts, worked, _ = frame
    run_dir = tmp_path / "s"
    R.run([worked], backend=_backend(version, counts["enumerated"]),
          resolver=_resolver(True), constructs=C, version=version,
          screened_from=counts["enumerated"], run_dir=run_dir, k=1,
          allow_unestimable=True, log=lambda s: None)
    dirty = GenerationEnv(key_present=True, key_fetchable=False, tree_sha="a" * 40,
                          tree_clean=True, branch="b")
    with pytest.raises(RuntimeError, match="answer key"):
        R.stamp_run(run_dir, dirty)
    clean = dirty.model_copy(update={"key_present": False})
    assert R.stamp_run(run_dir, clean) == 1
    art = next(f for f in run_dir.glob("*.json") if f.name != "summary.json")
    assert json.loads(art.read_text())["generation"]["tree_sha"] == "a" * 40
