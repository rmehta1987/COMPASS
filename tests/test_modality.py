"""`modality` is carried on the request and the record, and never rendered.

Why this file is output-level and not a string comparison. Asserting that
`to_query()` is byte-identical with a modality set and unset is necessary but
not sufficient: modality could still move retrieval through an embedding cache
key, a request hash, a serialisation order consumed downstream, or a sort key
among tied targets. So the invariants pinned here are the retrieval OUTPUTS on a
fixed corpus and a fixed request set -- resolved keys, cosines at full
precision, R@1, and the abstention decision at the deployed threshold -- across
EVERY value of the enum, not `UNKNOWN` against one other.

`role` is pinned by the same parametrisation. The bundle has always documented
`role` as "NOT rendered" and nothing tested it; a constraint asserted only in a
comment is the failure this file exists to prevent, so both fields are covered
rather than leaving the older one unprotected.

The real bundle needs torch, which `pyproject.toml` does not declare
(`AGENTS.md` section Testing Patterns), so the real-bundle test skips when it is
absent and `tests/` stays runnable without it. The fake-retriever tests below
carry the same invariants unconditionally, against a retriever whose cosines are
a deterministic function of the query string: if a modality ever reached the
query, its cosines, its ranking and its abstention would all move.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from pipeline import canary as C
from pipeline import retrieve as R
from pipeline.retrieval_record import RequestSnapshot, RetrievalRecord

ROOT = Path(__file__).resolve().parent.parent
TAU = 0.729476
PREREG = ROOT / "out" / "qx_preregistration.json"
HANDOFF = ROOT / "handoff" / "for_harness.json"

#: Values, not enum members. `deploy/retriever.py` rebinds
#: `sys.modules["compass_deploy_template"]` at import time, so importing the
#: real bundle REPLACES the template module `pipeline.retrieve.load_template`
#: cached and any member held from before it is a different object with the
#: same value. Identity across that boundary is not a property this codebase
#: has; every comparison below therefore goes through `.value`, and
#: `test_the_record_stores_modality_as_a_string` pins the reason it is safe to.
MODALITY_VALUES = tuple(m.value for m in R.load_template().Modality)
ROLE_VALUES = tuple(r.value for r in R.load_template().VariableRole)


def _tpl() -> Any:
    """The template module as it stands NOW, never a member cached at import."""
    return R.load_template()


# --------------------------------------------------------------- the vocabulary

def test_the_enum_is_the_inventory_vocabulary_plus_unknown():
    """The enum may not drift from the vocabulary the scorer will join on."""
    declared = tuple(json.loads(HANDOFF.read_text())["modality_values"])
    assert MODALITY_VALUES == ("unknown", *declared)


def test_the_record_pattern_and_the_template_enum_agree():
    """`RequestSnapshot` writes the vocabulary out; the two must not diverge."""
    pattern = RequestSnapshot.model_fields["modality"].metadata[0].pattern
    allowed = set(pattern.strip("^$()").split("|"))
    assert allowed == set(MODALITY_VALUES)


def test_an_unknown_modality_is_refused_by_the_record():
    with pytest.raises(ValueError):
        RequestSnapshot(construct_text="hypertension", role="exposure",
                        modality="proxy_report")


def test_the_default_is_unknown_on_both_types():
    tpl = _tpl()
    req = tpl.RetrievalRequest(construct="x", role=tpl.VariableRole.EXPOSURE)
    assert req.modality.value == "unknown"
    assert RequestSnapshot(construct_text="x", role="exposure").modality == "unknown"


# --------------------------------------------------------- the fixed request set

#: Pre-registered rows whose top cosine TIES, measured 2026-09-07 by scanning
#: all 224 through the deployed bundle. They are named explicitly because the
#: tie-break is one of the channels a carried field could perturb without ever
#: reaching the query: `pipeline.retrieve.retrieve` resolves a tie by lowest
#: target id, and `search` does NOT return equal cosines in a stable order
#: (rows 72 and 73 come back 2-then-1 and 1-then-2). Without these rows the
#: fixed set below contains no tie at all and the invariance tests could not
#: see a tie-break defect.
TIE_ROWS = (72, 73, 74, 75, 98, 107, 140, 141, 143)


def _fixed_requests() -> list[dict[str, Any]]:
    """Canaries (5 abstaining, 2 resolving), 15 positives, then every tie row.

    Both files are tracked, so the request set is fixed and the corpus is the
    deployed target set. `gold_key` is None for the canaries, which have none.
    """
    rows: list[dict[str, Any]] = [
        {"construct": c.construct, "instances": c.instances, "gold_key": None}
        for c in C.CANARIES
    ]
    pos = json.loads(PREREG.read_text())["positives"]
    for p in list(pos[:15]) + [pos[i] for i in TIE_ROWS]:
        rows.append({"construct": p["query"], "instances": tuple(p["instances"]),
                     "gold_key": p["gold_key"]})
    return rows


FIXED = _fixed_requests()


def _request(row: dict[str, Any], modality: str, role: str) -> Any:
    """Build a request from VALUES, resolving the template at call time."""
    tpl = _tpl()
    return tpl.RetrievalRequest(construct=row["construct"],
                                role=tpl.VariableRole(role),
                                instances=tuple(row["instances"]),
                                modality=tpl.Modality(modality))


def _outputs(retriever: Any, modality: str, role: str,
             strata: Any = None) -> list[dict[str, Any]]:
    """Every retrieval output that must not move, at full precision."""
    out = []
    for row in FIXED:
        rec = R.retrieve(retriever, _request(row, modality, role),
                         min_cos=TAU, strata=strata)
        out.append({
            "query": rec.query,
            "nearest_key": rec.nearest_key,
            "hit_key": None if rec.hit is None else rec.hit.key,
            "best_cos": rec.best_cos,          # exact float, not rounded
            "margin": rec.margin,
            "margin_12": rec.margin_12,
            "abstained": rec.abstained,
            "rank1": (rec.hit is not None and row["gold_key"] is not None
                      and row["gold_key"] in (rec.hit.members or ())),
        })
    return out


# -------------------------------------------------------- a query-sensitive fake

class HashRetriever:
    """Cosines derived from the query string, so any change to it is visible.

    Three targets whose cosines are a deterministic function of the query. A
    modality that leaked into `to_query()` would move every cosine here, the
    ranking among them, and which rows fall the abstaining side of TAU.
    """

    min_cos = TAU
    manifest: ClassVar[dict[str, Any]] = {"dictionary_version_hash": "3dc8415eccfe"}
    targets: ClassVar[list[dict[str, Any]]] = [
        {"target_id": 1, "key": "m2:Q5.7", "construct_key": "m2:Q5.7", "module": "2",
         "fold_size": 1, "n_siblings": 0, "members": ["m2:Q5.7"]},
        {"target_id": 2, "key": "m1:Q5.4", "construct_key": "m1:Q5.4", "module": "1",
         "fold_size": 1, "n_siblings": 0, "members": ["m1:Q5.4"]},
        {"target_id": 3, "key": "m3:Q16.1", "construct_key": "m3:Q16.1", "module": "3",
         "fold_size": 1, "n_siblings": 0, "members": ["m3:Q16.1"]},
    ]

    def search(self, query: str, k: int = 10) -> list[dict[str, Any]]:
        out = []
        for t in self.targets:
            d = hashlib.sha256(f"{query}|{t['key']}".encode()).digest()
            cos = round(0.55 + int.from_bytes(d[:4], "big") / 2**32 * 0.40, 6)
            out.append({**t, "cos": cos})
        out.sort(key=lambda h: (-h["cos"], h["target_id"]))
        return out[:k]


class _FakeStrata:
    def of(self, target_id: int) -> tuple[str, bool]:
        return ("chronic_condition", False)


@pytest.mark.parametrize("modality", MODALITY_VALUES)
@pytest.mark.parametrize("role", ROLE_VALUES)
def test_the_query_string_is_byte_identical_for_every_role_and_modality(modality, role):
    """Necessary, not sufficient -- the output tests below are the real pin."""
    for row in FIXED:
        base = _request(row, "unknown", "exposure")
        assert _request(row, modality, role).to_query() == base.to_query()


@pytest.mark.parametrize("modality", MODALITY_VALUES)
@pytest.mark.parametrize("role", ROLE_VALUES)
def test_fake_retriever_outputs_are_identical_for_every_role_and_modality(modality, role):
    """Keys, cosines, margins and abstentions, through the adapter's own path."""
    st = _FakeStrata()
    base = _outputs(HashRetriever(), "unknown", "exposure", strata=st)
    assert _outputs(HashRetriever(), modality, role, strata=st) == base


def test_the_fake_retriever_would_notice_a_leak():
    """Anti-vacuity: the fake's outputs DO move when the query moves.

    Without this, the invariance tests above would pass just as well against a
    retriever that ignored its input.
    """
    st = _FakeStrata()
    base = _outputs(HashRetriever(), "unknown", "exposure", strata=st)
    leaked = []
    for row in FIXED:
        rec = R.retrieve(HashRetriever(),
                         _request({**row, "construct": row["construct"] + " measured"},
                                  "unknown", "exposure"),
                         min_cos=TAU, strata=st)
        leaked.append(rec.best_cos)
    assert [o["best_cos"] for o in base] != leaked


# ------------------------------------------------------------- the real bundle

@pytest.mark.parametrize("modality", MODALITY_VALUES)
def test_real_bundle_outputs_are_identical_for_every_modality(modality):
    """The deployed encoder, fixed corpus, fixed request set, full precision.

    Resolved keys, cosines, R@1 and the abstention decision at the deployed
    threshold, for every enum value against `UNKNOWN`.
    """
    pytest.importorskip("torch", reason="the deployed bundle is not installable here")
    r = _real_retriever()
    strata = _real_strata(r)
    base = _outputs(r, "unknown", "exposure", strata=strata)
    got = _outputs(r, modality, "exposure", strata=strata)
    assert got == base
    assert sum(o["rank1"] for o in got) == sum(o["rank1"] for o in base)
    assert [o["abstained"] for o in got] == [o["abstained"] for o in base]


@pytest.mark.parametrize("role", ROLE_VALUES)
def test_real_bundle_outputs_are_identical_for_every_role(role):
    """The same pin for `role`, which the bundle documented and nothing tested."""
    pytest.importorskip("torch", reason="the deployed bundle is not installable here")
    r = _real_retriever()
    strata = _real_strata(r)
    base = _outputs(r, "unknown", "exposure", strata=strata)
    assert _outputs(r, "unknown", role, strata=strata) == base


_REAL: list[Any] = []


def _real_retriever() -> Any:
    if not _REAL:
        _REAL.append(R.load_retriever())
    return _REAL[0]


_STRATA: list[Any] = []


def _real_strata(retriever: Any) -> Any:
    if not _STRATA:
        from pipeline.strata import Strata
        _STRATA.append(Strata.from_retriever(retriever))
    return _STRATA[0]


# ------------------------------------------------------------ carried, not lost

def test_the_record_carries_the_declared_modality():
    r = HashRetriever()
    req = _request(FIXED[0], "ehr", "outcome")
    rec = R.retrieve(r, req, min_cos=TAU, strata=_FakeStrata())
    assert rec.request.modality == "ehr"
    assert RetrievalRecord.from_json(rec.to_json()).request.modality == "ehr"


def test_a_record_written_before_the_field_existed_reads_as_unknown():
    """Old artefacts stay parseable, and read as the silence they were."""
    old = {"construct_text": "hypertension", "role": "exposure", "population": None,
           "timeframe": None, "instances": [], "source": "user"}
    assert RequestSnapshot.model_validate(old).modality == "unknown"


def test_a_bundle_without_the_field_still_snapshots():
    """`from_request` reads `modality` defensively; the bundle loads by path."""

    class OldRequest:
        construct = "hypertension"
        role = "exposure"
        population = None
        timeframe = None
        instances = ()

    assert RequestSnapshot.from_request(OldRequest()).modality == "unknown"


# -------------------------------------------------------------- never inferred

@pytest.mark.parametrize("text", [
    "measured blood pressure",
    "self-reported hypertension",
    "EHR stroke diagnosis",
    "clinic BMI",
    "assayed cotinine",
    "administrative claims for type 2 diabetes",
])
def test_intake_never_infers_a_modality_from_the_wording(text):
    """The wording naming a modality is not a declaration; a caller declares."""
    from pipeline.intake import parse_request
    assert parse_request(text).request.modality.value == "unknown"


def test_intake_carries_a_declared_modality_without_rendering_it():
    from pipeline.intake import parse_request
    a = parse_request("hypertension", modality="measured")
    b = parse_request("hypertension")
    assert a.query == b.query == "hypertension"
    assert a.request.modality.value == "measured"


def test_intake_refuses_a_modality_outside_the_vocabulary():
    from pipeline.intake import modalities, parse_request
    assert "proxy_report" not in modalities()
    with pytest.raises(ValueError, match="modality must be one of"):
        parse_request("hypertension", modality="proxy_report")


def test_the_record_stores_modality_as_a_string_not_an_enum():
    """Why a downstream `==` on the record is safe where `is` on the enum is not.

    `deploy/retriever.py` rebinds `sys.modules["compass_deploy_template"]` when
    it is imported, so two `Modality` members with the same value can be
    different objects in one process. The record snapshots the VALUE, so a
    scorer comparing `rec.request.modality == "self_report"` cannot be broken
    by which template module happened to be loaded first.
    """
    rec = R.retrieve(HashRetriever(), _request(FIXED[0], "self_report", "exposure"),
                     min_cos=TAU, strata=_FakeStrata())
    assert rec.request.modality == "self_report"
    assert isinstance(rec.request.modality, str)
    assert not hasattr(rec.request.modality, "value")


def test_the_fixed_set_actually_contains_a_rank_one_tie():
    """Anti-vacuity for TIE_ROWS: without a real tie, no tie-break is exercised.

    Skipped rather than faked when the bundle is absent: a tie is a property of
    the deployed vectors, and asserting one against a stand-in would prove
    nothing about the tie-break `retrieve()` actually applies.
    """
    pytest.importorskip("torch", reason="the deployed bundle is not installable here")
    r = _real_retriever()
    tied = 0
    for row in FIXED:
        top = r.search(_request(row, "unknown", "exposure").to_query(), k=R.TIE_K)
        best = float(top[0]["cos"])
        tied += sum(1 for h in top if float(h["cos"]) == best) > 1
    assert tied >= len(TIE_ROWS)


def test_modality_survives_redaction_and_is_never_wording():
    """Item 18 reads modality out of the COMMITTABLE artefact, so it must survive.

    `pipeline.artefact._redact_record` digests instrument-sourced wording before
    anything reaches the public tree. `modality` is a closed vocabulary, never
    wording, so it must come through the redaction unchanged -- otherwise the
    scorer would read `unknown` for every instrument-sourced side and could not
    tell a declared modality from a redacted one.
    """
    from pipeline.artefact import _redact_record
    rec = R.retrieve(HashRetriever(), _request(FIXED[0], "self_report", "exposure"),
                     min_cos=TAU, strata=_FakeStrata())
    instrument = rec.model_copy(update={
        "request": rec.request.model_copy(update={"source": "instrument"})})
    out = _redact_record(instrument)
    assert out.query.startswith("sha256:")                 # wording digested
    assert out.request.construct_text.startswith("sha256:")
    assert out.request.modality == "self_report"           # vocabulary preserved
