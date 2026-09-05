"""Posed pairs: keys in, the same artefacts out, never the funnel's denominator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from generate.funnel import load_constructs
from pipeline import ledger, pose
from tests.test_run import _backend, _resolver

TAU = 0.729476


@pytest.fixture(scope="module")
def constructs():
    try:
        return load_constructs()
    except FileNotFoundError:
        pytest.skip("build/dictionary.json is withheld from the public tree")


def test_read_pairs_takes_keys_and_ignores_the_pmid(tmp_path):
    f = tmp_path / "pairs.jsonl"
    f.write_text('{"pmid": "1", "exposure_key": "m3:Q16.1_2", "outcome_key": "m2:Q5.8"}\n'
                 '\n{"exposure_key": "m3:Q16.1_2", "outcome_key": "m2:Q5.8"}\n')
    assert pose.read_pairs(f) == [("m3:Q16.1_2", "m2:Q5.8")] * 2
    f.write_text('{"exposure_key": "m3:Q16.1_2"}\n')
    with pytest.raises(ValueError, match="missing 'outcome_key'"):
        pose.read_pairs(f)


def test_candidates_resolve_variable_keys_to_their_constructs(constructs):
    C, _ = constructs
    e = C["m3:Q16.1"]
    member = e.member_keys[0]
    (cand,) = pose.candidates_for([(member, "m2:Q5.8")], C)
    assert cand.exposure is e and cand.outcome is C["m2:Q5.8"]
    assert cand.state == "live" and cand.tags["posed"]
    assert cand.tags["exposure_key"] == member
    with pytest.raises(KeyError, match=r"m9:Q1\.1 is not"):
        pose.candidates_for([("m9:Q1.1", "m2:Q5.8")], C)


class _Retriever:
    """Only what `Strata.from_retriever` needs; the resolver is injected below."""

    min_cos = TAU
    manifest = {"dictionary_version_hash": "3dc8415eccfe"}  # noqa: RUF012
    targets: list[dict] = []  # noqa: RUF012


def test_posed_records_carry_screened_from_zero_and_externally_posed(
        constructs, tmp_path, monkeypatch):
    C, version = constructs
    run_dir = tmp_path / "posed"
    monkeypatch.setattr(pose, "default_resolver",
                        lambda retriever, strata: _resolver(resolve_second=True))
    summary = pose.pose([("m3:Q16.1_2", "m2:Q5.8")], backend=_backend(version, 0),
                        constructs=C, version=version, run_dir=run_dir,
                        retriever=_Retriever(), strata=object(), k=1,
                        allow_unestimable=True, retry_pause=0.0, log=lambda s: None)
    assert summary.total_generated_this_run == 1
    (row,) = ledger.Ledger(run_dir).rows()
    assert row.pair_id == "m3:Q16.1 -> m2:Q5.8" and row.artefact
    art = json.loads((run_dir / row.artefact).read_text())
    protocol = art["artefact"]["protocol"]
    text = json.dumps(protocol)
    assert '"selection_mode": "externally_posed"' in text
    assert '"screened_from": 0' in text
    assert "enumerated_screen" not in text


def test_without_the_flag_a_posed_pair_is_gate_blocked_like_any_other(
        constructs, tmp_path, monkeypatch):
    C, version = constructs
    monkeypatch.setattr(pose, "default_resolver",
                        lambda retriever, strata: _resolver(resolve_second=True))
    summary = pose.pose([("m3:Q16.1_2", "m2:Q5.8")], backend=_backend(version, 0),
                        constructs=C, version=version, run_dir=tmp_path / "g",
                        retriever=_Retriever(), strata=object(), k=1,
                        allow_unestimable=False, retry_pause=0.0, log=lambda s: None)
    assert summary.by_outcome == {"gate_blocked": 1}


def test_dry_run_lists_the_pairs_without_loading_the_retriever(
        constructs, tmp_path, capsys):
    f = tmp_path / "p.jsonl"
    f.write_text('{"exposure_key": "m3:Q16.1_2", "outcome_key": "m2:Q5.8"}\n')
    assert pose.main(["dry", "--pairs", str(f), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "posed: 1 pairs, 1 distinct" in out and "m3:Q16.1 -> m2:Q5.8" in out
    assert not (Path(pose.ARTEFACTS) / "dry").exists()
