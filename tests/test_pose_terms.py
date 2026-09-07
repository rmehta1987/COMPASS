"""The tiered arm's driver: terms in, one run directory per opaque case id."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from benchmark import tiered_score
from generate.funnel import load_constructs
from pipeline import ledger, pose, pose_terms
from pipeline.pose import construct_index
from tests.test_run import _backend, _resolver

TAU = 0.729476
POSED_PAIRS = Path("posed_pairs.json")
#: The deployed query template itself, not a stand-in: it is stdlib-only and
#: what the real run renders.
TEMPLATE = pose_terms.load_template()


@pytest.fixture(scope="module")
def constructs():
    try:
        return load_constructs()
    except FileNotFoundError:
        pytest.skip("build/dictionary.json is withheld from the public tree")


class _Strata:
    def of(self, target_id: int) -> tuple[str, bool]:
        return "chronic_condition", False


class _Retriever:
    """A retriever that answers from a term -> construct table."""

    min_cos = TAU
    manifest = {"dictionary_version_hash": "3dc8415eccfe"}  # noqa: RUF012

    def __init__(self, table: dict[str, str]) -> None:
        self.table = table
        self.targets = [{"dict_construct_key": ck} for ck in table.values()]

    def search(self, query: str, k: int = 10) -> list[dict]:
        # The query is whatever deploy/template.py renders, so the table is
        # matched by containment rather than by an invented query format. The
        # target id is the matching row's, because retrieve() reads
        # dict_construct_key out of targets[target_id - 1]: a fake that always
        # answered target 1 sent both sides of a pair to the same construct.
        match = next(((i, v) for i, (t, v) in enumerate(self.table.items(), 1)
                      if t in query), None)
        tid, ck = match if match is not None else (len(self.targets) + 1, None)
        cos = 0.9 if ck is not None else 0.1
        hit = {"key": f"{ck or 'm9:Q0'}_1", "construct_key": ck or "m9:Q0",
               "module": "2", "target_id": tid, "fold_size": 1, "n_siblings": 0,
               "members": [f"{ck or 'm9:Q0'}_1"], "cos": cos}
        second = dict(hit, cos=cos - 0.2)
        return [hit, second][:k]


def _driver_retriever(exposure_term: str, outcome_term: str,
                      e_key: str, o_key: str) -> _Retriever:
    return _Retriever({exposure_term: e_key, outcome_term: o_key})


# --- reading the case file ------------------------------------------------


def test_the_shipped_case_file_is_ninety_five_three_field_rows():
    cases = pose_terms.read_cases(POSED_PAIRS)
    assert len(cases) == 95
    assert len({c.case_id for c in cases}) == 95
    assert all(c.exposure and c.outcome for c in cases)


@pytest.mark.parametrize("extra", [{"pmid": "38397711"}, {"tier": "A"},
                                   {"direction": "increase"}])
def test_an_extra_field_is_refused_at_the_source_not_filtered(tmp_path, extra):
    # The brief's hard stop: a row carrying the answer is an operator problem.
    # A driver that dropped the field would leave the file leaking.
    row = {"case_id": "c001", "exposure": "PM2.5", "outcome": "fibroids", **extra}
    f = tmp_path / "posed_pairs.json"
    f.write_text(json.dumps([row]))
    with pytest.raises(pose_terms.LeakedField, match=next(iter(extra))):
        pose_terms.read_cases(f)


@pytest.mark.parametrize("term", ["m2:Q5.8", "see 38397711"])
def test_a_term_holding_a_key_or_a_pmid_is_refused(tmp_path, term):
    f = tmp_path / "posed_pairs.json"
    f.write_text(json.dumps([{"case_id": "c001", "exposure": term,
                              "outcome": "fibroids"}]))
    with pytest.raises(pose_terms.LeakedField, match="variable key or a pmid"):
        pose_terms.read_cases(f)


def test_a_missing_field_is_an_error_not_an_empty_term(tmp_path):
    f = tmp_path / "posed_pairs.json"
    f.write_text(json.dumps([{"case_id": "c001", "exposure": "PM2.5"}]))
    with pytest.raises(ValueError, match="missing"):
        pose_terms.read_cases(f)


# --- resolving a term -----------------------------------------------------


def test_a_term_that_resolves_names_its_construct():
    r = _Retriever({"air pollution": "m3:Q16.1"})
    side = pose_terms.resolve_term(r, "air pollution", TEMPLATE.VariableRole.EXPOSURE,
                                   strata=_Strata(), template=TEMPLATE)
    assert side.construct_key == "m3:Q16.1" and not side.abstained
    assert side.term == "air pollution"


def test_a_term_that_abstains_records_the_near_miss_rather_than_a_construct():
    # An absent anchor is an outcome, not an error: for a tier D case it is
    # the correct answer, so the near miss is recorded and scored.
    r = _Retriever({"air pollution": "m3:Q16.1"})
    side = pose_terms.resolve_term(r, "residential radon", TEMPLATE.VariableRole.EXPOSURE,
                                   strata=_Strata(), template=TEMPLATE)
    assert side.abstained and side.construct_key is None
    assert side.nearest_key and side.best_cos < TAU


# --- posing a case --------------------------------------------------------


def test_a_resolved_case_runs_under_its_own_case_id(constructs, tmp_path):
    C, version = constructs
    r = _driver_retriever("air pollution", "fibroids", "m3:Q16.1", "m2:Q5.8")
    cases = [pose_terms.Case("c001", "air pollution", "fibroids")]
    (out,) = pose_terms.pose_cases(
        cases, backend=_backend(version, 0), constructs=C, version=version,
        run_dir=tmp_path / "tiered", retriever=r, inventory="handoff-public dcd80da",
        synthetic=False, strata=_Strata(), template=TEMPLATE,
        resolver=_resolver(resolve_second=True), k=1, allow_unestimable=True,
        retry_pause=0.0, log=lambda s: None)

    # The shared fixture record is the one tests/test_run.py uses, a mediator
    # under a cross-sectional design, so the temporality validator discards it.
    # What this pins is the run directory and the posed identity, not a verdict.
    assert out.state == "discarded" and out.note == "validator:temporality"
    assert out.artefact
    case_dir = tmp_path / "tiered" / "c001"
    assert case_dir.is_dir(), "one run directory per case, named by the case id"
    (row,) = ledger.Ledger(case_dir).rows()
    art = json.loads((case_dir / row.artefact).read_text())
    text = json.dumps(art["artefact"]["protocol"])
    assert '"screened_from": 0' in text
    assert '"selection_mode": "externally_posed"' in text
    assert "enumerated_screen" not in text


def test_the_case_id_reaches_the_artefacts_only_as_their_directory(constructs, tmp_path):
    # It never enters the prompt, the record or a key: the pipeline runs the
    # construct pair exactly as it would have without the tiered arm.
    C, version = constructs
    r = _driver_retriever("air pollution", "fibroids", "m3:Q16.1", "m2:Q5.8")
    pose_terms.pose_cases(
        [pose_terms.Case("c001", "air pollution", "fibroids")],
        backend=_backend(version, 0), constructs=C, version=version,
        run_dir=tmp_path / "tiered", retriever=r, inventory="handoff-public dcd80da",
        synthetic=False, strata=_Strata(), template=TEMPLATE,
        resolver=_resolver(resolve_second=True), k=1, allow_unestimable=True,
        retry_pause=0.0, log=lambda s: None)
    case_dir = tmp_path / "tiered" / "c001"
    (row,) = ledger.Ledger(case_dir).rows()
    art = (case_dir / row.artefact).read_text()
    # sha256 redaction digests are hex and can contain any short id as a
    # substring by chance -- the real run's c056 artefact holds "c056" inside
    # one. Blank the digests first, or this test fails on a coincidence and
    # passes on nothing.
    assert "c001" not in re.sub(r'"sha256:[0-9a-f]+"', '""', art)
    assert row.pair_id == "m3:Q16.1 -> m2:Q5.8"


def test_an_unresolved_anchor_spends_no_model_call(constructs, tmp_path):
    C, version = constructs

    class _Explode:
        name = "must-not-be-called"

        def complete(self, *a: object, **kw: object) -> object:
            raise AssertionError("a case with an absent anchor called the model")

    r = _driver_retriever("air pollution", "fibroids", "m3:Q16.1", "m2:Q5.8")
    (out,) = pose_terms.pose_cases(
        [pose_terms.Case("c002", "residential radon", "fibroids")],
        backend=_Explode(), constructs=C, version=version,
        run_dir=tmp_path / "tiered", retriever=r, inventory="handoff-public dcd80da",
        synthetic=False, strata=_Strata(), template=TEMPLATE,
        resolver=_resolver(resolve_second=True), k=1, allow_unestimable=True,
        retry_pause=0.0, log=lambda s: None)
    assert out.state == pose_terms.UNRESOLVED_ANCHOR
    assert "exposure abstained" in out.note
    assert not (tmp_path / "tiered" / "c002").exists()


def test_the_run_carries_its_inventory_provenance_and_a_case_index(constructs, tmp_path):
    C, version = constructs
    r = _driver_retriever("air pollution", "fibroids", "m3:Q16.1", "m2:Q5.8")
    run_dir = tmp_path / "tiered"
    outs = pose_terms.pose_cases(
        [pose_terms.Case("c001", "air pollution", "fibroids"),
         pose_terms.Case("c002", "residential radon", "fibroids")],
        backend=_backend(version, 0), constructs=C, version=version,
        run_dir=run_dir, retriever=r, inventory="handoff-public dcd80da",
        synthetic=False, strata=_Strata(), template=TEMPLATE,
        resolver=_resolver(resolve_second=True), k=1, allow_unestimable=True,
        retry_pause=0.0, log=lambda s: None)
    prov = pose.read_provenance(run_dir)
    assert prov["selection_mode"] == "externally_posed" and prov["pairs"] == 2
    rows = pose_terms.read_case_index(run_dir)
    assert [r["case_id"] for r in rows] == ["c001", "c002"]
    assert pose_terms.attrition(outs) == {"discarded": 1,
                                          pose_terms.UNRESOLVED_ANCHOR: 1}


def test_the_case_index_carries_no_pmid_and_no_wording(constructs, tmp_path):
    C, version = constructs
    r = _driver_retriever("air pollution", "fibroids", "m3:Q16.1", "m2:Q5.8")
    run_dir = tmp_path / "tiered"
    pose_terms.pose_cases(
        [pose_terms.Case("c001", "air pollution", "fibroids")],
        backend=_backend(version, 0), constructs=C, version=version,
        run_dir=run_dir, retriever=r, inventory="handoff-public dcd80da",
        synthetic=False, strata=_Strata(), template=TEMPLATE,
        resolver=_resolver(resolve_second=True), k=1, allow_unestimable=True,
        retry_pause=0.0, log=lambda s: None)
    text = (run_dir / pose_terms.CASE_INDEX).read_text()
    assert "38397711" not in text
    row = json.loads(text.splitlines()[0])
    assert set(row) == {"case_id", "state", "artefact", "note", "exposure", "outcome"}
    assert set(row["exposure"]) == {"term", "abstained", "best_cos",
                                    "nearest_key", "construct_key"}


# --- item 14: a run assembles into a report -------------------------------


def test_a_run_assembles_into_a_report_through_the_case_index(constructs, tmp_path):
    """The driver's output is the scorer's input, end to end, on one case."""
    C, version = constructs
    # A paper written for this test, not the shared fixture: the scripted
    # backend's record is the worked pair, so the paper's anchors are its two
    # constructs. Tier A by the predicate, one pair, direction increase.
    paper = {
        "paper": "fW", "intended_tier": "A",
        "exposures": [{"label": "synthetic exposure W", "status": "present",
                       "key": "m3:Q16.1_2", "analogue_key": None,
                       "modality": None, "confident": True}],
        "outcomes": [{"label": "synthetic outcome W", "status": "present",
                      "key": "m2:Q5.8", "analogue_key": None,
                      "modality": None, "confident": True}],
        "covariates": [{"label": "income", "status": "present", "key": "m1:Q5.4",
                        "analogue_key": None, "modality": None, "confident": True}],
        "pairs": [{"case_id": "w001", "direction": "increase"}]}

    run_dir = tmp_path / "tiered"
    r = _driver_retriever("air pollution", "fibroids", "m3:Q16.1", "m2:Q5.8")
    outs = pose_terms.pose_cases(
        [pose_terms.Case("w001", "air pollution", "fibroids")],
        backend=_backend(version, 0), constructs=C, version=version,
        run_dir=run_dir, retriever=r, inventory="tests: hand-written paper fW",
        synthetic=True, strata=_Strata(), template=TEMPLATE,
        resolver=_resolver(resolve_second=True), k=1, allow_unestimable=True,
        retry_pause=0.0, log=lambda s: None)

    idx = construct_index(C)
    reports = tiered_score.assemble(run_dir, [paper],
                                    lambda k: idx[k].construct_key if k in idx else None)
    (report,) = reports
    assert report.case_id == "w001" and report.tier == "A"
    assert report.state == outs[0].state == "discarded"
    assert report.anchor is not None and report.anchor.hits == 2
    # The record was discarded by a blocking validator, so it is NOT scored:
    # crediting the harness for output the pipeline rejected measures the
    # wrong thing. It is counted in the run's attrition instead.
    assert report.covariate is None

    out = tiered_score.render_report(reports, handoff=tiered_score.load_handoff(),
                                     inventory="tests: hand-written paper fW",
                                     synthetic=True, run_id="t-e2e")
    assert "SYNTHETIC" in out
    assert out.index("TARGETS") < out.index("TIER A")
    assert "fW / w001" in out and "no record emitted" in out


def test_the_index_is_written_after_every_case_not_only_at_the_end(constructs,
                                                                   tmp_path):
    # b2-20260904 died at pair 16 of 48 on one backend error. A run that dies
    # part way must still leave the scorer something to read.
    C, version = constructs
    r = _driver_retriever("air pollution", "fibroids", "m3:Q16.1", "m2:Q5.8")
    run_dir = tmp_path / "tiered"
    seen: list[int] = []

    def log(_: str) -> None:
        path = run_dir / pose_terms.CASE_INDEX
        seen.append(len(path.read_text().splitlines()) if path.exists() else 0)

    pose_terms.pose_cases(
        [pose_terms.Case("c002", "residential radon", "fibroids"),
         pose_terms.Case("c003", "residential radon", "fibroids")],
        backend=_backend(version, 0), constructs=C, version=version,
        run_dir=run_dir, retriever=r, inventory="x", synthetic=True,
        strata=_Strata(), template=TEMPLATE, resolver=_resolver(True), k=1,
        allow_unestimable=True, retry_pause=0.0, log=log)
    assert max(seen) >= 1, "the index was empty until the run finished"


def test_a_recorded_case_is_not_re_run_when_skip_recorded_is_set(constructs,
                                                                 tmp_path):
    C, version = constructs
    r = _driver_retriever("air pollution", "fibroids", "m3:Q16.1", "m2:Q5.8")
    run_dir = tmp_path / "tiered"
    cases = [pose_terms.Case("c001", "air pollution", "fibroids")]
    common = dict(constructs=C, version=version, run_dir=run_dir, retriever=r,
                  inventory="x", synthetic=True, strata=_Strata(),
                  template=TEMPLATE, resolver=_resolver(True), k=1,
                  allow_unestimable=True, retry_pause=0.0, log=lambda s: None)
    (first,) = pose_terms.pose_cases(cases, backend=_backend(version, 0), **common)

    class _Explode:
        name = "must-not-be-called"

        def complete(self, *a: object, **kw: object) -> object:
            raise AssertionError("a recorded case called the model again")

    (again,) = pose_terms.pose_cases(cases, backend=_Explode(),
                                     skip_recorded=True, **common)
    assert again.state == first.state and again.artefact == first.artefact


def test_stamping_walks_the_case_directories_and_not_the_run_root(constructs,
                                                                  tmp_path):
    # pipeline.run.stamp_run parses every *.json in ONE directory as a record.
    # A tiered run's root holds inventory_provenance.json, which is not one.
    C, version = constructs
    r = _driver_retriever("air pollution", "fibroids", "m3:Q16.1", "m2:Q5.8")
    run_dir = tmp_path / "tiered"
    pose_terms.pose_cases(
        [pose_terms.Case("c001", "air pollution", "fibroids")],
        backend=_backend(version, 0), constructs=C, version=version,
        run_dir=run_dir, retriever=r, inventory="x", synthetic=True,
        strata=_Strata(), template=TEMPLATE, resolver=_resolver(True), k=1,
        allow_unestimable=True, retry_pause=0.0, log=lambda s: None)

    from pipeline.generation_env import GenerationEnv
    env = GenerationEnv(key_present=False, key_fetchable=False, tree_sha="0" * 40,
                        tree_clean=True, branch="ralph-loop")
    assert pose_terms.stamp_cases(run_dir, env) == 1
    prov = json.loads((run_dir / pose.PROVENANCE_NAME).read_text())
    assert prov["selection_mode"] == "externally_posed", "the root was left alone"


def test_the_candidate_carries_the_case_id_only_in_its_tags(constructs):
    # The artefact-text test above cannot see this: wording is sha256-redacted
    # on the way into an artefact, so a case id injected into a construct's
    # stem would vanish there while still reaching the model's prompt, which
    # renders PAIR {pair_id} and the two stems. This is where that is caught.
    C, _ = constructs
    case = pose_terms.Case("c001", "air pollution", "fibroids")
    side = pose_terms.SideResolution("t", False, 0.9, "m3:Q16.1_1", "m3:Q16.1")
    other = pose_terms.SideResolution("t", False, 0.9, "m2:Q5.8_1", "m2:Q5.8")
    cand = pose_terms.candidate_for(case, side, other, C)
    assert cand is not None
    assert cand.tags["case_id"] == "c001"
    assert case.case_id not in cand.pair_id
    assert case.case_id not in cand.exposure.stem_text + cand.outcome.stem_text
