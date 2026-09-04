"""Item 13a: the critique seam and the generation stamp on HypothesisRecord.

The critique fields exist, default empty, round-trip, and revision is 0 on
every artefact this loop produces. The day something writes a critique, the
`critiques == ()` assertion here fails and the change is deliberate.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.schema import ProtocolSpecification
from generate.funnel import load_constructs
from generate.run_specifier import fixture
from pipeline import generation_env as G
from pipeline import hypothesis as H
from pipeline import resolved_pair as RP
from pipeline.retrieval_record import Hit, RequestSnapshot, RetrievalRecord

TAU = 0.729476
ROOT = Path(__file__).resolve().parent.parent


def _rec(role: str, key: str, ck: str, members: tuple[str, ...]) -> RetrievalRecord:
    return RetrievalRecord(
        request=RequestSnapshot(construct_text="t", role=role), query="t",
        dictionary_hash="h", min_cos=TAU, best_cos=0.9, margin=0.9 - TAU,
        margin_12=0.1, abstained=False, nearest_key=key,
        hit=Hit(key=key, construct_key=ck, dict_construct_key=ck, module=ck[1],
                target_id=1, fold_size=1, n_siblings=0, members=members,
                stratum="x", unmeasured_stratum=False))


@pytest.fixture(scope="module")
def record() -> H.HypothesisRecord:
    try:
        C, version = load_constructs()
    except FileNotFoundError:
        pytest.skip("build/dictionary.json is withheld from the public tree")
    p = ProtocolSpecification.model_validate_json(fixture(version, 384))
    e = C["m3:Q16.1"]
    pair = RP.from_records(_rec("exposure", e.member_keys[0], e.construct_key,
                                tuple(e.member_keys)),
                           _rec("outcome", "m2:Q5.8", "m2:Q5.8", ("m2:Q5.8",)),
                           C, estimability="blocked_no_metadata")
    return H.build(p, pair)


def test_the_seam_is_empty_on_every_artefact_this_loop_produces(record):
    assert record.critiques == ()
    assert record.revision == 0
    assert record.generation is None


def test_the_seam_round_trips_and_is_visible_in_the_wire_format(record):
    d = json.loads(record.to_json())
    assert set(d) == {"artefact", "structure", "critiques", "revision", "generation"}
    assert d["critiques"] == [] and d["revision"] == 0 and d["generation"] is None
    assert H.HypothesisRecord.from_json(record.to_json()) == record


def test_a_critique_is_typed_and_round_trips_when_one_exists(record):
    c = H.Critique(source="validator:temporality", category="identification",
                   statement="a mediator is asserted under a cross-sectional design",
                   grounding_key="m2:Q5.8", severity="blocking", resolved=False)
    with_one = record.model_copy(update={"critiques": (c,), "revision": 1})
    assert H.HypothesisRecord.from_json(with_one.to_json()) == with_one
    with pytest.raises(ValidationError):
        H.Critique(source="x", category="style", statement="s", severity="minor")
    with pytest.raises(ValidationError):
        H.Critique(source="x", category="measurement", statement="s", severity="fatal")


def test_generation_env_round_trips_and_gates_scoring():
    env = G.GenerationEnv(key_present=False, key_fetchable=False,
                          tree_sha="a" * 40, tree_clean=True, branch="ralph-loop")
    assert env.clean_for_scoring
    for bad in ({"key_present": True}, {"key_fetchable": True}):
        assert not env.model_copy(update=bad).clean_for_scoring


def test_stamp_measures_this_generation_clone():
    env = G.stamp(ROOT)
    assert env.key_present is False                # the key is on scoring-key only
    assert env.key_fetchable is False              # single-branch clone, no ref
    assert len(env.tree_sha) == 40
    assert env.branch and env.clean_for_scoring


def test_key_fetchable_is_true_for_a_wildcard_refspec_or_a_present_ref(tmp_path):
    def git(*a: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True,
                       capture_output=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (tmp_path / "f").write_text("x")
    git("add", "f")
    git("commit", "-q", "-m", "c")
    git("remote", "add", "origin", "https://example.invalid/r.git")
    git("config", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/main")
    assert G.key_fetchable(tmp_path) is False
    git("config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
    assert G.key_fetchable(tmp_path) is True        # a fetch could pull it in
    git("config", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/main")
    git("branch", G.KEY_BRANCH)
    assert G.key_fetchable(tmp_path) is True        # the ref itself is present


def test_stamped_attaches_the_env_without_touching_anything_else(record):
    env = G.stamp(ROOT)
    s = record.stamped(env)
    assert s.generation == env and s.artefact == record.artefact
    assert s.structure == record.structure and s.critiques == () and s.revision == 0
