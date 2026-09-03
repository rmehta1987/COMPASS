from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from agent.prompt_contract import (
    VariableSelection,
    candidates_from_keys,
    catalogue_contract,
)
from env import labels

# The size arm D was costed against, from the rendering table in the task that
# commissioned it. A CEILING WITH A FLOOR, both at 10%: too large and the arm
# stops fitting the context budget it was justified by; too small and something
# stopped being rendered, which is the failure that would look like a saving.
TARGET_CHARS = 138_192
TOLERANCE = 0.10

#: Every fully qualified key in this dictionary starts this way.
_KEY_SHAPE = re.compile(r"\bm[123]:[A-Za-z0-9_.#]+")

#: A piped Qualtrics reference, as it would look if one survived into the
#: rendering. Deliberately NOT `#\d` alone: `Additional Contact #1 - Name` is
#: instrument content and must survive.
_IDENTIFIER_SHAPE = re.compile(r"\b\d*_?Q\d+\.\d+")


@pytest.fixture(scope="module")
def catalogue() -> labels.Catalogue:
    return labels.build_catalogue()


@pytest.fixture(scope="module")
def rendered(catalogue: labels.Catalogue) -> str:
    return labels.render_catalogue(catalogue)


# --------------------------------------------------------------------------- #
# size, determinism
# --------------------------------------------------------------------------- #

def test_the_rendering_fits_the_budget_it_was_justified_by(rendered):
    lo = TARGET_CHARS * (1 - TOLERANCE)
    hi = TARGET_CHARS * (1 + TOLERANCE)
    assert lo <= len(rendered) <= hi, (
        f"{len(rendered):,} chars against a {TARGET_CHARS:,} target "
        f"({100 * (len(rendered) - TARGET_CHARS) / TARGET_CHARS:+.1f}%). Above "
        f"the band the context argument weakens; below it, check what stopped "
        f"being rendered before calling it a saving")


#: The most bytes one `exec` argument may carry on Linux. The CLI takes its
#: system prompt as an argument, so the whole arm-D prompt has to fit inside
#: one of these — and when it did not, `claude` failed with `OSError [Errno 7]
#: Argument list too long` on all 221 rows of a live pass, which reads as the
#: model refusing rather than as the harness overflowing.
MAX_ARG_STRLEN = 131_072

#: Bytes of headroom demanded, so a rebuild that adds a few questions does not
#: land on the limit.
ARG_HEADROOM = 2_048


def test_the_whole_prompt_fits_one_exec_argument():
    """Measured 2026-09-02, and it cost a whole live pass to learn.

    `--append-system-prompt-file` is ACCEPTED by this CLI build and silently
    ignored — probed with a system prompt that demanded a fixed word, and the
    reply ignored it — so there is no file-based escape from this limit. The
    prompt is trimmed to fit instead, and this pins the fit.
    """
    from generate.arm_d import build_surface

    n = len(build_surface().prompt.encode())
    assert n + ARG_HEADROOM <= MAX_ARG_STRLEN, (
        f"the arm D prompt is {n:,} bytes against a {MAX_ARG_STRLEN:,} limit "
        f"with {ARG_HEADROOM:,} demanded as headroom. Every call will fail "
        f"with Errno 7, one row at a time, and look like a model failure")


def test_rendering_twice_produces_identical_bytes():
    """A prompt hash over this is only stable if the rendering is.

    Built from scratch both times, not rendered twice from one catalogue: the
    ordering has to come from the dictionary, not from a dict that happened to
    be populated in one order.
    """
    assert labels.render_catalogue(labels.build_catalogue()) == \
           labels.render_catalogue(labels.build_catalogue())


def test_indices_are_one_to_n_in_render_order(catalogue, rendered):
    assert [o.index for o in catalogue.options] == \
           list(range(1, len(catalogue.options) + 1))
    printed = [int(m) for m in re.findall(r"^i(\d+) ", rendered, re.M)]
    assert printed == [o.index for o in catalogue.options], (
        "the printed numbering and the resolvable indices disagree, so the "
        "harness would resolve a different item than the model chose")


# --------------------------------------------------------------------------- #
# wording provenance
# --------------------------------------------------------------------------- #

def test_every_option_binds_to_cite_byte_for_byte(catalogue):
    """`cite()` stays the only maker of a key bound to its text."""
    for o in catalogue.options:
        assert labels.cite(o.representative).wording, o.representative


def test_the_display_differs_from_the_instrument_only_by_the_two_removals(
        catalogue):
    """Whitespace, the leading roster index, the piped reference. Nothing else.

    This is the honest form of "byte-verbatim": the display is NOT
    `question_text`, and saying it was would be false for 308 of the 1,400
    options. What it is, exactly, is `catalogue_display` applied to
    `question_text` — so the removals are auditable and no third one can creep
    in unnoticed.
    """
    for o in catalogue.options:
        verbatim = labels.cite(o.representative).wording
        assert o.display == labels.catalogue_display(verbatim), o.representative


def test_the_renderer_reads_question_text_and_not_the_index_field():
    """`searchable_text` exists for the FTS index; it is not a wording source."""
    src = Path(labels.__file__).read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "build_catalogue")
    strings = {n.value for n in ast.walk(fn)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "question_text" in strings
    assert "searchable_text" not in strings


def test_no_display_is_empty(catalogue):
    """A stripped identifier must never leave a candidate with nothing to read."""
    blank = [o.index for o in catalogue.options if not o.display.strip()]
    assert not blank, blank


# --------------------------------------------------------------------------- #
# what may not appear in the rendering
# --------------------------------------------------------------------------- #

def test_no_variable_key_reaches_the_rendering(rendered):
    """`prompt_contract` withholds keys by design; this must not reintroduce them."""
    assert not _KEY_SHAPE.findall(rendered)


def test_no_piped_identifier_reaches_the_rendering(rendered):
    found = _IDENTIFIER_SHAPE.findall(rendered)
    assert not found, f"identifier-shaped tokens survived: {sorted(set(found))[:8]}"


def test_no_index_position_reads_as_a_withheld_figure(rendered):
    """A 1,400-item numbered list collides with every numeric marker under 1,400.

    Measured 2026-09-02: numbering the catalogue `602.` fired the markers `602`
    and `1092` — both published cohort figures, both matched on an index
    position carrying no figure. The fix is lexical and it strengthens the scan
    rather than exempting the surface from it: `i602` has no left word
    boundary, so a BARE `602` appearing here would still be caught.
    """
    from benchmark.contamination_check import check_markers

    assert not check_markers({"arm_d_catalogue": rendered})


def test_instrument_content_that_merely_looks_like_an_identifier_survives(
        rendered):
    """Anti-vacuity: the stripper must be narrow, not thorough.

    `Additional Contact #1` is a question about a person, not a Qualtrics
    reference. A stripper that removed it would pass the test above by deleting
    content, which is the failure mode of every over-eager sanitiser.
    """
    assert "Additional Contact #1" in rendered


# --------------------------------------------------------------------------- #
# the fold
# --------------------------------------------------------------------------- #

def test_every_dictionary_key_folds_into_exactly_one_option(catalogue):
    """Reachability is the whole claim of this arm, so it is checked, not stated."""
    entries = json.loads(
        (labels.BUILD / "dictionary.json").read_text())["entries"]
    folded = {k for o in catalogue.options for k in o.keys}
    assert folded == {e["key"] for e in entries}
    assert sum(len(o.keys) for o in catalogue.options) == len(entries), (
        "a key reached two options, so one index would resolve a variable "
        "another index also claims")


def test_the_family_fact_survives_the_members(catalogue):
    """A roster family folds to one line and keeps the fact that it was N."""
    big = [o for o in catalogue.options if len(o.keys) > 1]
    assert big, "no option folds more than one key; the fold is not happening"
    assert all(o.roster_family_size for o in big if o.roster_family_size), \
        "a folded option lost the size of the family it stands for"
    rendered = labels.render_catalogue(catalogue)
    assert "roster_family_size" in rendered


def test_a_roster_battery_folds_to_its_options_not_its_members(catalogue):
    """The measured case: 440 rows, 22 cancer types, 20 siblings."""
    q16_8 = [o for o in catalogue.options if o.construct_key == "m2:Q16.8"]
    assert len(q16_8) == 22, f"{len(q16_8)} options for a 22-type battery"
    assert sum(len(o.keys) for o in q16_8) == 440
    assert {o.roster_family_size for o in q16_8} == {20}


def test_an_index_resolves_to_the_wording_it_was_rendered_from(catalogue):
    """The contract's resolution and the catalogue's fold must agree."""
    cands = candidates_from_keys([o.representative for o in catalogue.options])
    contract = catalogue_contract(cands)
    for index in (1, 2, len(catalogue.options) // 2, len(catalogue.options)):
        option = catalogue.by_index(index)
        assert contract.resolve(index).key == option.representative
        assert labels.catalogue_display(contract.resolve(index).wording) == \
               option.display


def test_key_lookup_and_index_lookup_are_inverses(catalogue):
    for o in list(catalogue.options)[::137]:
        for k in o.keys:
            assert catalogue.index_of_key(k) == o.index


def test_an_out_of_range_index_raises_rather_than_returning_a_neighbour(
        catalogue):
    with pytest.raises(IndexError):
        catalogue.by_index(0)
    with pytest.raises(IndexError):
        catalogue.by_index(len(catalogue.options) + 1)


# --------------------------------------------------------------------------- #
# the selection surface
# --------------------------------------------------------------------------- #

def test_all_five_verdicts_stay_reachable():
    """Removing the filter removes the excuse for saying "not found".

    `docs/adr/003-index-selection.md` records that prior-art system 1 instructs
    its model AGAINST abstaining and that this system's measured failure is the
    opposite — five false positives in 21 rows. An arm shown all 1,400
    candidates is under MORE pressure to pick one, so the abstaining verdicts
    have to remain expressible and be counted separately.
    """
    verdicts = VariableSelection.model_fields["verdict"].annotation
    from typing import get_args
    assert set(get_args(verdicts)) == {
        "resolved", "family", "derive", "ambiguous", "absent"}


def test_the_catalogue_contract_names_no_request_so_the_prefix_is_static(
        catalogue):
    """Caching is the reason the request is a user turn, not a prompt head.

    Measured 2026-09-02: carried as a system prompt the 38k-token instrument is
    read from cache after the first row; carried in the user prompt with the
    request appended it is re-created every row, at three times the cost.
    """
    cands = candidates_from_keys([o.representative for o in catalogue.options])
    a = catalogue_contract(cands).render(catalogue="CATALOGUE")
    b = catalogue_contract(cands).render(catalogue="CATALOGUE")
    assert a == b
    assert "researcher asked for" not in a, (
        "the request is in the static prefix, so every row re-creates the cache")
    assert "'absent'" in a, "the surface must say how to refuse"


def test_the_rendered_surface_offers_every_candidate(catalogue):
    cands = candidates_from_keys([o.representative for o in catalogue.options])
    text = catalogue_contract(cands).render(
        catalogue=labels.render_catalogue(catalogue))
    assert f"Candidates ({len(catalogue.options)})" in text
    assert not _KEY_SHAPE.findall(text)
