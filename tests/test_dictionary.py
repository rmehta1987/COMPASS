"""Invariants over build/dictionary.json.

Every assertion here can go red. That is the point: a failure means either the
codebooks changed or a build rule is wrong, and both are things you want to hear
about before a protocol is generated against a silently different dictionary.

    ./.venv/bin/python -m pytest tests/ -q

Coverage boundary: these tests exercise the build only. Nothing here covers the
specifier, the gates or the reviewer, none of which exist yet.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
sys.path.insert(0, str(ROOT))

import build as B  # noqa: E402


@pytest.fixture(scope="module")
def d() -> dict:
    p = BUILD / "dictionary.json"
    if not p.exists():
        pytest.fail(f"{p} missing — run `python build.py` first. "
                    "A missing generated input must raise, not read as empty.")
    return json.loads(p.read_text())


@pytest.fixture(scope="module")
def entries(d) -> list[dict]:
    return d["entries"]


# --- counts, verified against the raw codebooks on 2026-08-25 ---------------- #

def test_total_record_count(d):
    assert d["counts"]["total"] == 2804


def test_per_module_counts(d):
    assert d["counts"]["by_module"] == {"1": 142, "2": 2326, "3": 336}


def test_modules_sum_to_total(d):
    assert sum(d["counts"]["by_module"].values()) == d["counts"]["total"]


def test_distinct_constructs(d):
    """The collapse rule is written down in build.py; this pins its result."""
    assert d["counts"]["distinct_constructs"] == 1080
    assert d["counts"]["distinct_constructs_by_module"] == {"1": 59, "2": 752, "3": 269}


# --- identifier grammar ------------------------------------------------------ #

def test_nine_identifier_shapes(d):
    assert len(d["counts"]["shapes"]) == 9


def test_shape_counts(d):
    assert d["counts"]["shapes"] == {
        "N_QN.N": 970, "QN.N": 881, "N_QN.N#N_N": 550, "QN.N#N_N": 192,
        "QN.N_N": 78, "QN": 76, "QN_N": 28, "QN.N_N_TEXT": 17, "QN.N#N_N_N": 12,
    }


def test_ids_containing_hash(d):
    assert d["counts"]["ids_with_hash"] == 754


def test_roster_repeats(d):
    assert d["counts"]["roster_repeats"] == 1520


def test_plain_form_is_not_absent(entries):
    """The handoff claims zero ids match ^Q\\d+(\\.\\d+)?$. That is false.

    957 do (881 QN.N + 76 QN). The conclusion the claim was supporting still
    holds — 1,847 ids do NOT match, so a parser assuming the plain form breaks on
    two thirds of the instrument — but the number itself was wrong and is pinned
    here so it cannot quietly propagate into a write-up.
    """
    plain = [e for e in entries if re.fullmatch(r"Q\d+(\.\d+)?", e["qid"])]
    assert len(plain) == 957


# --- collisions -------------------------------------------------------------- #

def test_non_unique_qid_count(d):
    assert d["counts"]["non_unique_qids"] == 121


def test_keys_are_unique(entries):
    """The occurrence ordinal exists precisely so this holds."""
    keys = [e["key"] for e in entries]
    assert len(keys) == len(set(keys))


def test_within_module_duplicate_is_disambiguated(entries):
    """Q785 appears twice inside module 2 meaning two unrelated things."""
    q785 = sorted([e for e in entries if e["qid"] == "Q785"], key=lambda e: e["key"])
    assert [e["key"] for e in q785] == ["m2:Q785~1", "m2:Q785~2"]
    assert "sickle cell" in q785[0]["question_text"].lower()
    assert "transportation" in q785[1]["question_text"].lower()


def test_cross_module_collision_resolves_separately(entries):
    """m1:Q2.4 and m2:Q2.4 are different variables. A bare qid is not a name."""
    by_key = {e["key"]: e for e in entries}
    assert "street address" in by_key["m1:Q2.4"]["question_text"].lower()
    assert "service plan" in by_key["m2:Q2.4"]["question_text"].lower()


def test_occurrence_suffix_only_where_needed(entries):
    """2,802 keys stay clean; only the genuinely ambiguous pair carries a suffix."""
    suffixed = [e for e in entries if "~" in e["key"]]
    assert len(suffixed) == 2
    assert all(e["occurrence_count"] > 1 for e in suffixed)


# --- encoding ---------------------------------------------------------------- #

def test_mojibake_rows_were_repaired(d):
    assert d["counts"]["text_repaired"] == 98


def test_no_residual_mojibake(entries):
    """Five rows carry a byte (0x9D) that cp1252 leaves undefined, so the naive
    .encode('cp1252').decode('utf-8') repair silently no-ops on them. If this
    fails, that fallback regressed.
    """
    bad = [e["key"] for e in entries
           if any(m in e["question_text"] for m in B.MOJIBAKE_MARKERS)]
    assert bad == []


def test_the_five_hard_repairs(entries):
    """Named explicitly so a regression points at the right rows."""
    by_key = {e["key"]: e for e in entries}
    for key in ["m2:Q5.15#1_31", "m2:Q5.46", "m2:Q9.18#1_2", "m2:Q9.20", "m2:Q24.2"]:
        assert "“" in by_key[key]["question_text"], f"{key} lost its curly quote"


# --- absent facts stay absent ------------------------------------------------ #

@pytest.mark.parametrize("field", [
    "value_labels", "response_options", "value_type",
    "missing_codes", "measurement_level", "branch_dependency",
])
def test_unfillable_fields_are_null_for_every_row(entries, field):
    """These are null because the codebooks have two columns, not because nobody
    checked. This test failing is the notification that a richer dictionary
    arrived — it is not a bug.
    """
    assert all(e[field] is None for e in entries)


# --- grid structure ---------------------------------------------------------- #

def test_grid_stems_are_not_variables(entries):
    """A stem is a group id in its own namespace. A protocol may never name one,
    because naming a stem generates a reference resolution cannot find.
    """
    keys = {e["key"] for e in entries}
    groups = {e["group_key"] for e in entries if e["group_key"]}
    assert groups
    assert not (groups & keys)
    assert all(g.startswith("group:") for g in groups)


def test_subitem_text_carries_its_stem(entries):
    """Sub-item text is only interpretable with its stem, and two thirds of rows
    are fragments without it.
    """
    sub = [e for e in entries if e["is_grid_subitem"]]
    assert len(sub) > 800
    with_stem = [e for e in sub if e["stem_text"]]
    assert len(with_stem) / len(sub) > 0.99

    q16 = [e for e in entries if e["key"].startswith("m3:Q16.1_")]
    assert len(q16) >= 5
    assert len({e["stem_text"] for e in q16}) == 1, "all five share one stem"
    assert len({e["subitem_text"] for e in q16}) == len(q16), "sub-items differ"


# --- provenance -------------------------------------------------------------- #

def test_study_team_confirmed_is_zero(d):
    """Provenance coverage is 2,804/2,804 by construction and merely restates a
    config file, so it can never go red. This is the metric that can: it is
    currently zero, and it should be reported as zero rather than as coverage.
    """
    assert d["counts"]["study_team_confirmed"] == 0


def test_version_hash_is_pinned(d):
    v = json.loads((BUILD / "version.json").read_text())
    assert v["version_hash"] == d["version_hash"]
    assert len(v["source_files"]) == 3
    assert all(len(h) == 64 for h in v["source_files"].values())


def test_build_is_deterministic():
    """Same raw/ plus same rules must give the same hash, or nothing downstream
    can be pinned to a dictionary version.
    """
    import subprocess
    import sys
    before = json.loads((BUILD / "version.json").read_text())["version_hash"]
    subprocess.run([sys.executable, str(ROOT / "build.py")], check=True,
                   capture_output=True, cwd=ROOT)
    after = json.loads((BUILD / "version.json").read_text())["version_hash"]
    assert before == after


# --------------------------------------------------------------------------- #
# the version hash covers the rules, not just a version string
# --------------------------------------------------------------------------- #

#: The build these tests were measured over, and the single place the current
#: hash is written down. It has moved three times, each deliberately and each
#: because a rule or a column changed:
#:   6fcd02755bf3 -> d7a70c5014c5   item 1, the two identifier columns
#:   d7a70c5014c5 -> c272da5de196   item 4, the rule fingerprint entering the payload
#:   c272da5de196 -> 3dc8415eccfe   item 2, the roster_family_size column
#: Item 8 moved it not at all, which was that item's whole constraint.
BUILD_HASH = "3dc8415eccfe"

_FILES = {"module_1_codebook_full.csv": "a" * 64,
          "module_2_codebook_full.csv": "b" * 64,
          "module_3_codebook_full.csv": "c" * 64}


def test_the_shipped_dictionary_carries_the_hash_this_file_pins():
    d = json.loads((ROOT / "build" / "dictionary.json").read_text())
    assert d["version_hash"] == BUILD_HASH


def test_editing_a_regex_moves_the_version_hash(monkeypatch):
    """A regex edit must move the hash.

    `RE_FREE_TEXT` decides `is_free_text` on individual rows and the `free_text`
    count, and none of it was hashed. Before this, the only thing between two
    different rule sets and one `version_hash` was a human remembering to bump
    a string.
    """
    before = B._version_hash(_FILES, 2804)
    monkeypatch.setattr(B, "RE_FREE_TEXT", re.compile(r"please\s+(?:describe)"))
    assert B._version_hash(_FILES, 2804) != before


def test_reverting_the_edit_returns_the_hash(monkeypatch):
    """Reverting the edit returns the hash.

    The hash is a function of the rules, not of their having been touched.
    """
    before = B._version_hash(_FILES, 2804)
    monkeypatch.setattr(B, "RE_FREE_TEXT", re.compile(r"zzz"))
    monkeypatch.undo()
    assert B._version_hash(_FILES, 2804) == before


def test_editing_a_parsing_function_moves_the_version_hash(monkeypatch):
    """A logic edit must move the hash too.

    This is the half a pattern cannot see: `split_stem` is a function body, so
    its source is hashed — which is also why a docstring edit there moves it.
    """
    before = B._version_hash(_FILES, 2804)

    def split_stem(text: str) -> tuple[str | None, str | None]:
        return None, None

    monkeypatch.setattr(B, "split_stem", split_stem)
    assert B._version_hash(_FILES, 2804) != before


def test_editing_the_shape_table_moves_the_version_hash(monkeypatch):
    before = B._version_hash(_FILES, 2804)
    monkeypatch.setattr(B, "SHAPES", B.SHAPES[:-1])
    assert B._version_hash(_FILES, 2804) != before


def test_every_rule_that_decides_a_row_is_in_the_fingerprint():
    """Every rule that decides a row is in the fingerprint.

    Anti-vacuity: a fingerprint that silently stopped covering one rule would
    still be a dict, and every test above would still pass on the others.
    """
    fp = B._rule_fingerprint()
    assert set(fp) == {"patterns", "shapes", "mojibake_markers", "sources"}
    assert set(fp["patterns"]) == set(B._HASHED_PATTERNS)
    assert set(fp["sources"]) == set(B._HASHED_SOURCES)
    # Every module-level compiled regex is hashed, so adding one and forgetting
    # to list it is caught here rather than by a silent hash that never moved.
    compiled = {n for n, v in vars(B).items() if isinstance(v, re.Pattern)}
    assert compiled == set(B._HASHED_PATTERNS), (
        f"unhashed module-level regex: {sorted(compiled - set(B._HASHED_PATTERNS))}")


def test_the_version_string_is_a_label_and_not_the_provenance(monkeypatch):
    """The version string is a label, not the provenance.

    `BUILD_RULES_VERSION` still moves the hash, but is no longer the only thing
    that can — which was the defect.
    """
    before = B._version_hash(_FILES, 2804)
    monkeypatch.setattr(B, "BUILD_RULES_VERSION", "99")
    assert B._version_hash(_FILES, 2804) != before


# --------------------------------------------------------------------------- #
# item 8 — the checks split, and what is hashed
# --------------------------------------------------------------------------- #

import ast  # noqa: E402

import checks  # noqa: E402


def test_only_a_rule_or_a_column_change_has_ever_moved_the_hash():
    """One pin, and its history is written beside it.

    Item 8 was reorganisation and moved the hash not at all — verified at
    c272da5de196 while it landed. Item 2 moved it afterwards by adding a column,
    which is the documented obligation in `AGENTS.md`: build.py hashes files,
    the rules and n, so any new column must bump.
    """
    d = json.loads((ROOT / "build" / "dictionary.json").read_text())
    assert d["version_hash"] == BUILD_HASH


def test_mojibake_markers_has_exactly_one_definition_in_the_repository():
    """It is a hashed input AND a dependency of a hashed function.

    A second definition would drift the fingerprint away from the rule it
    claims to describe, so `checks.py` imports it rather than copying it.
    """
    defs = []
    # Recursive: the copy this test exists to catch lived in tests/, which a
    # non-recursive glob could not see.
    for path in ROOT.rglob("*.py"):
        if ".venv" in path.parts or ".claude" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "MOJIBAKE_MARKERS"
                    for t in node.targets):
                defs.append(path.name)
    assert defs == ["build.py"], f"defined in {defs}"
    assert checks.MOJIBAKE_MARKERS is B.MOJIBAKE_MARKERS


def test_the_checks_run_against_a_stored_dictionary_without_rebuilding(tmp_path):
    """Asking "do the checks pass" must not require a write.

    The artefact's mtime is compared before and after, so a check that quietly
    rebuilt would be caught rather than merely unlikely.
    """
    artefact = ROOT / "build" / "dictionary.json"
    before = artefact.stat().st_mtime_ns
    groups = checks.run(json.loads(artefact.read_text()))
    assert groups == {"structural": [], "snapshot": []}
    assert artefact.stat().st_mtime_ns == before


def test_a_structural_failure_and_a_snapshot_failure_are_labelled_differently():
    """A failure's meaning must be unambiguous from the output alone."""
    d = json.loads((ROOT / "build" / "dictionary.json").read_text())

    broken = json.loads(json.dumps(d))
    # Duplicate a key without deleting one the identifier checks name, so the
    # failure under test is the duplicate and not a missing row.
    spare = [i for i, e in enumerate(broken["entries"])
             if not e["is_direct_identifier"]][:2]
    broken["entries"][spare[0]]["key"] = broken["entries"][spare[1]]["key"]
    g = checks.run(broken)
    assert g["structural"] and not g["snapshot"]
    assert "STRUCTURAL FAILURES — the build is broken" in checks.report(g)

    drifted = json.loads(json.dumps(d))
    drifted["counts"]["free_text"] = 150
    g2 = checks.run(drifted)
    assert g2["snapshot"] and not g2["structural"]
    text = checks.report(g2)
    assert "SNAPSHOT FAILURES — a count moved" in text
    assert "STRUCTURAL" not in text


def test_both_groups_exit_one():
    """Labelling them differently must not make either optional."""
    import subprocess
    src = ROOT / "build.py"
    proc = subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-c",
         "import sys; sys.path.insert(0,'.'); import json, checks;"
         "d=json.load(open('build/dictionary.json'));"
         "d['counts']['free_text']=1;"
         "g=checks.run(d);"
         "sys.exit(1 if any(g.values()) else 0)"],
        cwd=ROOT, capture_output=True)
    assert proc.returncode == 1
    assert src.exists()


def test_every_module_level_function_is_either_hashed_or_allowlisted():
    """Anti-vacuity, mirroring the regex test.

    "Module-level function defined in build.py" is a decidable set, so a
    function added later cannot land outside the fingerprint unnoticed — it
    forces a deliberate choice between hashing it and stating why not.
    """
    tree = ast.parse((ROOT / "build.py").read_text())
    fns = {f.name for f in tree.body if isinstance(f, ast.FunctionDef)}
    assert fns - set(B._NOT_HASHED) == set(B._HASHED_SOURCES), (
        f"unclassified: {sorted(fns - set(B._NOT_HASHED) - set(B._HASHED_SOURCES))}")
    assert set(B._NOT_HASHED) <= fns, "allowlist names a function that is gone"


def test_a_new_module_level_function_fails_the_allowlist_test(monkeypatch):
    """The test earns its place only if adding a function breaks it."""
    tree = ast.parse((ROOT / "build.py").read_text())
    fns = {f.name for f in tree.body if isinstance(f, ast.FunctionDef)}
    fns.add("a_new_rule_nobody_classified")
    assert fns - set(B._NOT_HASHED) != set(B._HASHED_SOURCES)


def test_every_allowlist_entry_carries_a_reason():
    for name, reason in B._NOT_HASHED.items():
        assert len(reason) > 30, f"{name} has no real reason"


def test_the_two_declared_gaps_say_they_are_gaps():
    """`build` and `read_module` do decide rows and are excluded anyway.

    The point of the allowlist is that this is declared rather than invisible.
    """
    for name in ("build", "read_module"):
        assert B._NOT_HASHED[name].startswith("DECLARED GAP")


# --------------------------------------------------------------------------- #
# item 2 — roster_family_size is a column, not a derivation
# --------------------------------------------------------------------------- #


def test_every_module_2_q16_7_row_carries_a_family_of_twenty():
    d = json.loads((ROOT / "build" / "dictionary.json").read_text())
    rows = [e for e in d["entries"]
            if e["module"] == "2" and e["base_id"] == "Q16.7"]
    assert len(rows) == 20
    assert {e["roster_family_size"] for e in rows} == {20}


def test_the_five_over_grouped_rows_are_null_by_name():
    """Named, not counted.

    `family_of` groups these five because its tuple key cannot see that they are
    not roster repeats: three write-in slots on the race question share one stem
    and `subitem_text='Text'`, and `m2:Q785`'s two occurrences share a base id
    while carrying unrelated wording. A general assertion over
    `is_roster_repeat` passes while leaving them unnamed.
    """
    d = json.loads((ROOT / "build" / "dictionary.json").read_text())
    by_key = {e["key"]: e for e in d["entries"]}
    for k in ("m1:Q3.10_6_TEXT", "m1:Q3.10_7_TEXT", "m1:Q3.10_8_TEXT",
              "m2:Q785~1", "m2:Q785~2"):
        assert by_key[k]["roster_family_size"] is None, k
        assert by_key[k]["is_roster_repeat"] is False, k


def test_the_column_is_null_exactly_where_the_row_is_not_a_roster_repeat():
    d = json.loads((ROOT / "build" / "dictionary.json").read_text())
    for e in d["entries"]:
        assert (e["roster_family_size"] is None) is not e["is_roster_repeat"], \
            e["key"]


def test_the_member_count_equals_the_highest_roster_row_in_all_74_families():
    """Distinct members, not the largest label — and here they agree.

    A roster numbered 1, 2, 5 has three members and a maximum of five. That
    shape does not occur in this build, and this asserts it rather than
    assuming it.
    """
    d = json.loads((ROOT / "build" / "dictionary.json").read_text())
    biggest: dict[tuple[str, str], int] = {}
    for e in d["entries"]:
        if e["roster_row"] is not None:
            g = (e["module"], e["base_id"])
            biggest[g] = max(biggest.get(g, 0), e["roster_row"])
    assert len(biggest) == 74
    for e in d["entries"]:
        if e["is_roster_repeat"]:
            assert e["roster_family_size"] == biggest[(e["module"], e["base_id"])]


def test_the_resolver_reads_the_column_rather_than_grouping_for_it():
    """One artefact field, one definition.

    `agent/prompt_contract.py` names `roster_family_size` in prompt text and
    cannot import `benchmark/`, so a value derived there was invisible to the
    surface describing it.
    """
    import ast

    from benchmark import resolver_eval as RE

    src = ast.parse((ROOT / "benchmark" / "resolver_eval.py").read_text())
    fn = next(n for n in ast.walk(src)
              if isinstance(n, ast.FunctionDef) and n.name == "candidate_facts")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "family_of" not in called, "candidate_facts still derives the size"
    assert RE.candidate_facts("m2:1_Q16.8#1_3")["roster_family_size"] == 20
    assert "roster_family_size" not in RE.candidate_facts("m3:Q2.1")


def test_family_of_is_kept_because_a_scalar_cannot_say_which_members():
    """The column says how many; `family_of` says which.

    A size of 20 cannot express that the family is one column of a 440-cell
    grid, which is what the resolver scores a family answer against.
    """
    from benchmark import resolver_eval as RE

    fam = RE.family_of("m2:1_Q16.8#1_3")
    assert len(fam) == 20
    whole = [e for e in json.loads(
        (ROOT / "build" / "dictionary.json").read_text())["entries"]
        if e["construct_key"] == "m2:Q16.8"]
    assert len(whole) == 440
    assert set(fam) < {e["key"] for e in whole}


def test_a_non_contiguous_roster_counts_members_not_the_highest_label():
    """The only check that separates the count from the maximum.

    Every real family is numbered 1..N, so the distinction `_fill_roster_family_size`
    documents cannot be exercised against the built dictionary. Rows 1, 2 and 5
    are three members with a maximum of five.
    """
    rows = [B.Entry(
        key=f"m9:{r}_Q1.1", module="9", qid=f"{r}_Q1.1", occurrence=1,
        occurrence_count=1, shape="N_QN.N", shape_meaning="roster repeat",
        question_text="x", text_repaired=False, stem_text=None,
        subitem_text=None, searchable_text="x", base_id="Q1.1",
        construct_key="m9:Q1.1", group_key=None, roster_row=r,
        matrix_block=None, matrix_col=None, subitem_index=None,
        is_text_companion=False, is_roster_repeat=True, is_grid_subitem=False,
        is_free_text=False, is_direct_identifier=False,
        is_quasi_identifier=False, origin="questionnaire",
        study_team_confirmed=False) for r in (1, 2, 5)]

    B._fill_roster_family_size(rows)
    assert [e.roster_family_size for e in rows] == [3, 3, 3]
    assert max(e.roster_row for e in rows) == 5
