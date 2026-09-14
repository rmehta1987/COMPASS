"""The test endpoint must not publish the withheld instrument.

`serve/` exists so a browser can drive real runs, and the two things it drives
both answer with instrument content: `deploy/retriever.py::_hit` returns `stem`,
`option`, the variable `key` and roster `members`, and a `Cited` label carries
`question_text` byte for byte. `README.md` §What is withheld lists all of it as
not cleared for release, direct identifiers included.

`site/tools/no_instrument.py` proves wording never lands in a FILE under
`site/`. A live endpoint answers one query at a time and never writes a file, so
that gate cannot see it at all. These are the checks that can.

Each partition carries an anti-vacuity probe: a filter that redacts everything
passes a leak test trivially, so every "it was removed" assertion is paired with
"and this clean value survived".
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve.redact import (  # noqa: E402
    KEY_RE,
    REDACTED,
    SAFE_HIT_FIELDS,
    WITHHELD_HIT_FIELDS,
    WORDING_FIELDS,
    DictionaryUnavailable,
    Pseudonymiser,
    Scrubber,
    dictionary_path,
    pseudonymise_hit,
)

#: A hit with every field `_hit` builds, plus one it does not. The extra field
#: is the point: an allowlist must exclude what it has never heard of.
FULL_HIT = {
    "target_id": 417,
    "key": "m3:Q16.1_2",
    "construct_key": "m3:Q16.1",
    "module": "3",
    "stem": "How often do you use scented candles or air fresheners?",
    "option": "Every day",
    "fold_size": 6,
    "n_siblings": 5,
    "members": ["m3:Q16.1_1", "m3:Q16.1_2"],
    "cos": 0.731576,
    "a_field_added_next_year": "whatever the deploy bundle starts returning",
}


@pytest.fixture(autouse=True)
def _clean_serve_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let the operator's own shell decide what these tests exercise.

    `COMPASS_SERVE_AUTH` is the documented way to configure auth, so it is
    routinely set in the shell that runs the suite. Read by `main`, it changes
    which guard a test reaches -- one test fell past every guard into
    `serve_forever()` and hung the run on `0.0.0.0`, and others would have
    passed on the auth check rather than the one they are named for.
    """
    monkeypatch.delenv("COMPASS_SERVE_AUTH", raising=False)
    monkeypatch.setenv("COMPASS_DICTIONARY", str(ROOT / "dictionary.json"))


def _dictionary_or_skip() -> Path:
    """The built dictionary, or skip -- it is withheld from the public tree.

    Returns:
        Path to a readable dictionary.
    """
    p = dictionary_path()
    if p is None:
        pytest.skip("dictionary withheld here; set COMPASS_DICTIONARY to run")
    return p


# --------------------------------------------------------------- structural


def test_pseudonymised_hit_carries_no_withheld_field() -> None:
    """No field `_hit` fills with instrument content survives the filter."""
    out = pseudonymise_hit(FULL_HIT, Pseudonymiser(salt="fixed"))
    leaked = WITHHELD_HIT_FIELDS & set(out)
    assert not leaked, f"withheld fields on the wire: {sorted(leaked)}"


def test_pseudonymised_hit_still_carries_the_numbers() -> None:
    """Anti-vacuity: the filter is not simply emptying the dict."""
    out = pseudonymise_hit(FULL_HIT, Pseudonymiser(salt="fixed"))
    assert out["cos"] == FULL_HIT["cos"]
    assert out["fold_size"] == FULL_HIT["fold_size"]
    assert SAFE_HIT_FIELDS & set(out), "no safe field survived; the panel gets nothing"


def test_the_filter_is_an_allowlist_not_a_denylist() -> None:
    """A field the deploy bundle adds later is excluded until it is named safe.

    The failure mode of a denylist here is publishing the instrument; the
    failure mode of an allowlist is a missing number in a demo panel.
    """
    out = pseudonymise_hit(FULL_HIT, Pseudonymiser(salt="fixed"))
    assert "a_field_added_next_year" not in out


def test_the_raw_target_id_never_leaves() -> None:
    """The row index is a join key into the withheld targets file."""
    out = pseudonymise_hit(FULL_HIT, Pseudonymiser(salt="fixed"))
    assert "target_id" not in out
    assert str(FULL_HIT["target_id"]) not in json.dumps(out)


def test_pseudonyms_are_stable_within_a_salt_and_differ_across_them() -> None:
    """Stable enough to debug a run, not stable enough to publish."""
    a, b = Pseudonymiser(salt="one"), Pseudonymiser(salt="two")
    assert a.label(417) == a.label(417)
    assert a.label(417) != a.label(418)
    assert a.label(417) != b.label(417)


def test_the_pseudonym_map_is_written_but_never_part_of_a_response(
    tmp_path: Path,
) -> None:
    """The inverse map is an operator artefact, not a payload."""
    p = Pseudonymiser(salt="fixed")
    label = p.label(417)
    p.dump(tmp_path / "pseudonyms.json")
    written = json.loads((tmp_path / "pseudonyms.json").read_text())
    assert written["labels"]["417"] == label
    assert label not in json.dumps(pseudonymise_hit(FULL_HIT, Pseudonymiser(salt="x")))


# ------------------------------------------------------------------ textual


def test_scrubber_refuses_to_start_without_the_instrument(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scan that cannot see the instrument certifies nothing, so it raises."""
    monkeypatch.setenv("COMPASS_DICTIONARY", str(tmp_path / "nope.json"))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(DictionaryUnavailable):
        Scrubber(path=tmp_path / "nope.json")


def test_real_instrument_wording_is_replaced() -> None:
    """A five-word run lifted from the dictionary does not survive a response."""
    dic = _dictionary_or_skip()
    entries = json.loads(dic.read_text(encoding="utf-8"))["entries"]
    wording = next(e["question_text"] for e in entries
                   if isinstance(e.get("question_text"), str)
                   and len(e["question_text"].split()) > 6)
    s = Scrubber(path=dic)
    assert s.hits(wording), "the scanner did not recognise its own corpus"
    clean, marks = s.scrub({"record": {"note": wording}})
    assert clean["record"]["note"] == REDACTED
    assert marks == ["record.note"]


def test_wording_is_caught_inside_a_sentence_the_model_wrote() -> None:
    """Wording arrives wrapped in prose, not as a bare field."""
    dic = _dictionary_or_skip()
    entries = json.loads(dic.read_text(encoding="utf-8"))["entries"]
    wording = next(e["question_text"] for e in entries
                   if isinstance(e.get("question_text"), str)
                   and len(e["question_text"].split()) > 6)
    s = Scrubber(path=dic)
    sentence = f"I called resolve_variable and it returned {wording} which I used."
    assert s.hits(sentence)
    clean, marks = s.scrub([sentence])
    assert clean == [REDACTED]
    assert marks == ["[0]"]


def test_clean_prose_survives_the_scrubber() -> None:
    """Anti-vacuity: the scrubber is not replacing every string it sees."""
    dic = _dictionary_or_skip()
    s = Scrubber(path=dic)
    payload = {"reason": "no protocol here is valid; the outcome is not estimable",
               "elapsed_s": 12.5, "samples": [{"gate": "REFUSAL_UPHELD"}]}
    clean, marks = s.scrub(payload)
    assert clean == payload, "clean prose was destroyed; the filter is vacuous"
    assert marks == []


def test_a_bare_variable_key_is_caught() -> None:
    """Tier A forbids a key anywhere the browser can see it."""
    dic = _dictionary_or_skip()
    s = Scrubber(path=dic)
    assert KEY_RE.findall("the anchor was m3:Q16.1_2 in module 3")
    clean, marks = s.scrub({"analysis": "the anchor was m3:Q16.1_2 in module 3"})
    assert clean["analysis"] == REDACTED
    assert marks == ["analysis"]


def test_whitespace_is_collapsed_before_the_scan() -> None:
    """Codebooks break phrases across lines; a raw scan would miss them."""
    dic = _dictionary_or_skip()
    entries = json.loads(dic.read_text(encoding="utf-8"))["entries"]
    wording = next(e["question_text"] for e in entries
                   if isinstance(e.get("question_text"), str)
                   and len(e["question_text"].split()) > 6)
    s = Scrubber(path=dic)
    broken = wording.replace(" ", "\n   ", 2)
    assert s.hits(broken), "line breaks defeated the scan"


# ------------------------------------------------------------------- server


def test_a_non_loopback_bind_is_refused_without_the_explicit_flag() -> None:
    """Every request spends a named human's Claude seat; loopback is the default."""
    os.environ.setdefault("COMPASS_DICTIONARY", str(ROOT / "dictionary.json"))
    from serve.api import LOOPBACK, main

    assert "127.0.0.1" in LOOPBACK
    assert main(["--host", "0.0.0.0", "--port", "0"]) == 2


def test_the_specify_route_is_capped() -> None:
    """A browser must not be able to fan out an unbounded number of model calls."""
    from serve.api import MAX_K

    assert 1 <= MAX_K <= 5


def test_a_sibling_directory_sharing_the_prefix_is_not_served(tmp_path: Path) -> None:
    """The containment check is the only thing between a URL and any file.

    Driven over a raw socket, because an HTTP client normalises `..` out of the
    path before it is sent and would silently stop testing anything. A
    `str.startswith` containment test passes `/…/site-old` for a root of
    `/…/site`; the withheld instrument sits in exactly such sibling
    directories on this machine.
    """
    import socket
    import threading

    from serve.api import State, build_server

    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("ok")
    sibling = tmp_path / "site-old"
    sibling.mkdir()
    (sibling / "secret.json").write_text("WITHHELD-INSTRUMENT")

    state = State(tmp_path / "deploy", site, tmp_path / "run")
    srv = build_server("127.0.0.1", 0, state)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with socket.create_connection(srv.server_address, timeout=5) as s:
            s.sendall(b"GET /../site-old/secret.json HTTP/1.0\r\n\r\n")
            reply = b""
            while chunk := s.recv(4096):
                reply += chunk
    finally:
        srv.shutdown()
        srv.server_close()

    assert b"WITHHELD-INSTRUMENT" not in reply, "traversal served a file outside site/"
    assert b"403" in reply.split(b"\r\n", 1)[0]


def test_a_json_null_is_a_bad_request_not_a_server_error() -> None:
    """`int(None)` raises TypeError, which the dispatcher would report as a 500."""
    from serve.api import _int_arg

    assert _int_arg({}, "k", 3) == 3
    assert _int_arg({"k": "4"}, "k", 3) == 4
    for bad in (None, [], {}, True):
        with pytest.raises(ValueError):
            _int_arg({"k": bad}, "k", 3)


def test_key_pattern_matches_every_key_the_instrument_actually_uses() -> None:
    """The regex encodes a belief about the key grammar; check it against reality.

    The pattern this started as a copy of matched 1,080 of 2,804 keys and missed
    every roster-prefixed shape. A key-shaped regex that quietly covers 39% of
    the instrument is worse than none, because it reads as enforcement.
    """
    dic = _dictionary_or_skip()
    entries = json.loads(dic.read_text(encoding="utf-8"))["entries"]
    keys = {e["key"] for e in entries} | {e["construct_key"] for e in entries}
    missed = sorted(k for k in keys if not KEY_RE.fullmatch(k))
    assert not missed, f"{len(missed)} of {len(keys)} keys unmatched, e.g. {missed[:5]}"


def test_a_variable_key_used_as_a_dict_key_is_caught() -> None:
    """The walk only looked at values, so a key-keyed map shipped its keys."""
    dic = _dictionary_or_skip()
    s = Scrubber(path=dic)
    clean, marks = s.scrub({"per_variable": {"m1:1_Q6.2": {"role": "confounder"}}})
    assert "m1:1_Q6.2" not in json.dumps(clean)
    assert any("<key>" in m for m in marks)
    assert clean["per_variable"][f"{REDACTED}#0"]["role"] == "confounder"


def test_wording_fields_go_structurally_not_by_word_count() -> None:
    """Three dictionary rows are under five words; the run rule cannot see them."""
    dic = _dictionary_or_skip()
    s = Scrubber(path=dic)
    short = "List of Countries"
    assert not s.hits(short), "this row is no longer short; pick another"
    clean, marks = s.scrub({"cited": {"key": "m1:Q2.2_1", "wording": short}})
    assert clean["cited"]["wording"] == REDACTED
    assert "cited.wording" in marks


def test_every_json_response_is_filtered_at_one_chokepoint() -> None:
    """`_send` filters, so a new route or a new error is protected by default.

    Scrubbing per route is how `/api/retrieve` came to rely on the hit allowlist
    alone while `/api/specify` was scrubbed, and the 500 path by neither. The
    exceptions this endpoint raises are the ones most likely to quote the
    instrument: a pydantic `ValidationError` echoes the offending field VALUE,
    and for a record built from `Cited` labels that value is `question_text`.
    """
    import io
    import types

    from serve.api import Handler

    dic = _dictionary_or_skip()
    entries = json.loads(dic.read_text(encoding="utf-8"))["entries"]
    wording = next(e["question_text"] for e in entries
                   if isinstance(e.get("question_text"), str)
                   and len(e["question_text"].split()) > 6)

    class Capture(Handler):
        def __init__(self) -> None:
            self.state = types.SimpleNamespace(scrubber=Scrubber(path=dic),
                                               show_instrument=False)
            self.wfile = io.BytesIO()
            self.codes: list[int] = []

        def send_response(self, code: int, message: str | None = None) -> None:
            self.codes.append(code)

        def send_header(self, *a: object, **k: object) -> None:
            return

        def end_headers(self) -> None:
            return

    h = Capture()
    h._send(500, {"error": f"ValidationError: bad value: {wording}"})
    body = h.wfile.getvalue().decode()
    assert wording not in body, "the error path put instrument wording on the wire"
    assert REDACTED in body
    assert "redactions" in body

    clean = Capture()
    clean._send(400, {"error": "k must be a number"})
    out = json.loads(clean.wfile.getvalue())
    assert out["error"] == "k must be a number", "clean errors must stay readable"
    assert "redactions" not in out


def test_files_serve_ships_verbatim_carry_no_instrument_content() -> None:
    """`serve/console.html` is in NEITHER gate's scope, so it gets its own.

    `do_GET` serves it with `read_bytes()` straight to the socket: the runtime
    scrubber never sees it, and `site/tools/no_instrument.py` scans `site/`, not
    `serve/`. Two real construct keys sat in it as input defaults until this
    test existed.
    """
    dic = _dictionary_or_skip()
    s = Scrubber(path=dic)
    served = ROOT / "serve" / "console.html"
    text = served.read_text(encoding="utf-8")
    found = s.hits(text)
    assert not found, f"{served.name} carries instrument content: {found[:3]}"


def test_key_matching_is_case_insensitive_on_both_paths() -> None:
    """A model that lower-cased its own prose still names a real key."""
    dic = _dictionary_or_skip()
    s = Scrubber(path=dic)
    for variant in ("m1:1_Q6.2", "M1:1_Q6.2", "m1:1_q6.2", "M1:1_q6.2"):
        assert s.hits(f"I turned down {variant} because it is the wrong construct"), \
            f"{variant} slipped both the regex and the literal sweep"


def test_a_redaction_mark_never_reprints_what_it_removed() -> None:
    """`_send` ships `redactions` to the client, so a mark is a response too.

    The path was interpolated from the dict key, so a key-keyed map had its key
    deleted from the body and reprinted verbatim in the report beside it.
    """
    dic = _dictionary_or_skip()
    s = Scrubber(path=dic)
    clean, marks = s.scrub({"per_variable": {"m1:1_Q6.2": {"role": "confounder"}}})
    whole = json.dumps({"body": clean, "redactions": marks})
    assert "m1:1_Q6.2" not in whole, f"the mark reprinted the key: {marks}"
    assert marks and all(not s.hits(m) for m in marks)


def test_a_non_finite_k_is_a_bad_request_not_a_server_error() -> None:
    """`json.loads` accepts `Infinity`; `int(inf)` raises OverflowError."""
    from serve.api import _int_arg

    assert json.loads('{"k": Infinity}')["k"] == float("inf")
    for bad in (float("inf"), float("-inf"), float("nan"), 1e400):
        with pytest.raises(ValueError):
            _int_arg({"k": bad}, "k", 3)


def test_a_site_dir_holding_withheld_material_is_refused(tmp_path: Path) -> None:
    """The containment check keeps requests INSIDE site_dir; nothing checked what it is.

    Pointed at a source tree, the static route serves `build/dictionary.json` --
    every `question_text` in the instrument -- and `pseudonyms.json`, which
    un-does the pseudonymiser entirely.
    """
    from serve.api import _refuse_unsafe_site_dir

    safe = tmp_path / "site"
    safe.mkdir()
    assert _refuse_unsafe_site_dir(safe, tmp_path / "run") is None

    repo_ish = tmp_path / "tree"
    (repo_ish / "build").mkdir(parents=True)
    assert _refuse_unsafe_site_dir(repo_ish, tmp_path / "run") is not None

    nested_run = tmp_path / "site2"
    nested_run.mkdir()
    assert _refuse_unsafe_site_dir(nested_run, nested_run / "run") is not None

    # And the wiring, not just the function: a guard nothing calls is not a guard.
    from serve.api import main

    # `--no-auth` so these reach the site-dir check. Without it they would exit
    # 2 on the auth gate and pass for a reason that has nothing to do with the
    # guarantee they are named for.
    assert main(["--no-auth", "--site-dir", str(repo_ish), "--port", "0"]) == 2
    assert main(["--no-auth", "--site-dir", str(safe),
                 "--run-dir", str(safe / "run"), "--port", "0"]) == 2


def test_pseudonyms_are_wide_enough_not_to_collide_over_the_corpus() -> None:
    """24 bits over 1,353 targets collides ~5.5% of runs, merging two variables."""
    p = Pseudonymiser(salt="fixed")
    label = p.label(1)
    bits = 4 * (len(label) - 1)
    assert bits >= 48, f"{bits}-bit labels: birthday risk over 1,353 targets"
    seen = {p.label(i) for i in range(1, 1354)}
    assert len(seen) == 1353, "collision across the corpus"


def test_show_instrument_returns_the_wording_and_is_off_by_default() -> None:
    """The redaction is aimed at other people, not at the operator's own disk.

    A pseudonym cannot tell you whether the retriever found the RIGHT variable,
    which is the one question a retrieval demo exists to answer. So the flag
    returns the wording -- but the DEFAULT still has to be the safe one, because
    that default is what stops a later `--host 0.0.0.0` publishing the codebook.
    """
    default = pseudonymise_hit(FULL_HIT, Pseudonymiser(salt="fixed"))
    assert not WITHHELD_HIT_FIELDS & set(default)

    shown = pseudonymise_hit(FULL_HIT, Pseudonymiser(salt="fixed"),
                             show_instrument=True)
    assert shown["stem"] == FULL_HIT["stem"], "the question wording is the point"
    assert shown["option"] == FULL_HIT["option"]
    assert shown["key"] == FULL_HIT["key"]
    assert shown["target_id"] == FULL_HIT["target_id"]
    assert "INSTRUMENT_SHOWN" in shown, "unredacted output must say so"
    assert shown["target"] == default["target"], "the pseudonym stays, for the map"


def test_show_instrument_is_refused_on_an_unauthenticated_public_bind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Who can reach the socket, and what the socket says, are separate claims.

    Together the two flags are "publish the instrument to an anonymous socket",
    so the combination is refused rather than warned about.

    `COMPASS_SERVE_AUTH` is DELETED, not defaulted. This test omitted that and
    its siblings did not: with the variable set in the operator's own shell --
    the documented way to configure auth -- `main` fell through every guard to
    `serve_forever()`, so the suite hung on `0.0.0.0` with wording unredacted
    and the thirteen tests after it never ran.
    """
    from serve.api import main

    monkeypatch.delenv("COMPASS_SERVE_AUTH", raising=False)
    monkeypatch.setenv("COMPASS_DICTIONARY", str(ROOT / "dictionary.json"))
    site = ROOT / "serve"          # any real directory with no withheld markers
    assert main(["--show-instrument", "--host", "0.0.0.0", "--no-auth",
                 "--i-am-not-serving-the-public",
                 "--site-dir", str(site), "--port", "0"]) == 2


def test_the_chokepoint_does_not_cancel_the_flag(tmp_path: Path) -> None:
    """Scrubbing an intentionally-unredacted response would silently undo it."""
    import io
    import types

    from serve.api import Handler

    dic = _dictionary_or_skip()
    entries = json.loads(dic.read_text(encoding="utf-8"))["entries"]
    wording = next(e["question_text"] for e in entries
                   if isinstance(e.get("question_text"), str)
                   and len(e["question_text"].split()) > 6)

    class Capture(Handler):
        def __init__(self, show: bool) -> None:
            self.state = types.SimpleNamespace(scrubber=Scrubber(path=dic),
                                               show_instrument=show)
            self.wfile = io.BytesIO()

        def send_response(self, code: int, message: str | None = None) -> None:
            return

        def send_header(self, *a: object, **k: object) -> None:
            return

        def end_headers(self) -> None:
            return

    on = Capture(show=True)
    on._send(200, {"stem": wording})
    assert wording in on.wfile.getvalue().decode(), "the flag was cancelled"
    assert "REDACTION_DISABLED" in on.wfile.getvalue().decode()

    off = Capture(show=False)
    off._send(200, {"stem": wording})
    assert wording not in off.wfile.getvalue().decode(), "default must still redact"


# ------------------------------------------------------- posed-key resolution


def test_a_mis_cased_key_is_fixed_in_code_and_reported_not_guessed() -> None:
    """The harness may canonicalise case; the model may never substitute a key.

    The Specifier is forbidden to swap a key that does not resolve -- "a key
    that resolves while naming the wrong construct is the one failure with no
    automated detector" -- and that rule cannot be relaxed for a capital letter
    without also relaxing it for `m3:Q16.1` -> `m3:Q16.2`. So the fix lives in
    Python, as an exact case-insensitive lookup against the dictionary's own
    keys, and the correction is reported rather than applied silently.
    """
    from serve.api import _canonical_key

    constructs = {"m3:Q16.1": object(), "m2:Q5.8": object()}
    seen: dict[str, str] = {}
    assert _canonical_key("m3:Q16.1", constructs, "exposure", seen) == "m3:Q16.1"
    assert seen == {}, "an exact match is not a correction"

    assert _canonical_key("m3:q16.1", constructs, "exposure", seen) == "m3:Q16.1"
    assert seen == {"m3:q16.1": "m3:Q16.1"}, "the rewrite must be reported"


def test_an_unresolvable_key_costs_nothing() -> None:
    """A typo cost a live run 78s and $0.04 before this existed."""
    from serve.api import _canonical_key

    constructs = {"m3:Q16.1": object()}
    with pytest.raises(ValueError, match="does not resolve"):
        _canonical_key("m3:Q99.9", constructs, "exposure", {})


def test_case_insensitive_key_matching_is_unambiguous_on_this_instrument() -> None:
    """The canonicaliser is only safe while no two keys differ by case alone."""
    dic = _dictionary_or_skip()
    entries = json.loads(dic.read_text(encoding="utf-8"))["entries"]
    both = {e["key"] for e in entries} | {e["construct_key"] for e in entries}
    folded = [k.casefold() for k in both]
    assert len(set(folded)) == len(both), "two keys differ only by case"


def test_the_refusal_path_stays_reachable_on_purpose() -> None:
    """`stand_in` exists so an unresolvable pair is representable; keep it so."""
    from generate.live_specifier import stand_in

    c = stand_in("m3:Q99.9")
    assert c.construct_key == "m3:Q99.9"
    assert c.stem_text == "", "stand_in must invent no wording"


def test_the_pipeline_model_is_named_and_reported_not_assumed() -> None:
    """A caller may name a model; the payload must say whether it was the proxy."""
    from serve.api import PIPELINE_MODEL

    assert PIPELINE_MODEL == "claude-haiku-4-5"


# ------------------------------------------------------------- shared access


def test_a_public_bind_requires_a_password() -> None:
    """Off loopback the OS stops limiting reach, so something else must."""
    from serve.api import main

    os.environ.setdefault("COMPASS_DICTIONARY", str(ROOT / "dictionary.json"))
    os.environ.pop("COMPASS_SERVE_AUTH", None)
    site = ROOT / "serve"
    assert main(["--host", "0.0.0.0", "--i-am-not-serving-the-public",
                 "--site-dir", str(site), "--port", "0"]) == 2


def test_wording_off_loopback_needs_the_password_not_a_flag() -> None:
    """Wording behind a password is disclosure; on an open socket it is publication.

    The redaction is a contamination control aimed at the in-pipeline model, and
    that model cannot reach a web page (`agent/sealed.py::DENY_TOOLS` denies
    WebSearch and WebFetch). So the question off-loopback is who reads it, and
    auth is the line.
    """
    from serve.api import main

    os.environ.setdefault("COMPASS_DICTIONARY", str(ROOT / "dictionary.json"))
    os.environ.pop("COMPASS_SERVE_AUTH", None)
    site = ROOT / "serve"
    assert main(["--show-instrument", "--host", "0.0.0.0",
                 "--i-am-not-serving-the-public",
                 "--site-dir", str(site), "--port", "0"]) == 2


def test_the_sealed_model_cannot_reach_a_web_page() -> None:
    """The premise the off-loopback decision rests on, asserted rather than assumed."""
    from agent.sealed import DENY_TOOLS

    assert "WebFetch" in DENY_TOOLS
    assert "WebSearch" in DENY_TOOLS


def test_the_rate_limit_actually_limits(tmp_path: Path) -> None:
    """Anti-vacuity: a limiter that never says no is not a limiter."""
    from serve.api import RATE_LIMIT, State

    os.environ.setdefault("COMPASS_DICTIONARY", str(ROOT / "dictionary.json"))
    st = State(tmp_path / "deploy", tmp_path / "site", tmp_path / "run")
    assert all(st.allow("1.2.3.4") for _ in range(RATE_LIMIT))
    assert not st.allow("1.2.3.4"), "the limit never fires"
    assert st.allow("5.6.7.8"), "one client's traffic throttled another"


def test_a_tunnel_is_a_loopback_bind() -> None:
    """The bind address must decide nothing: cloudflared forwards to 127.0.0.1.

    Every guard used to read `a.host in LOOPBACK` and conclude "private" for
    exactly the deployment that is public. Auth was not required, and
    `/api/specify` -- which spends the operator's Claude seat with no
    per-caller accounting -- was ENABLED, on the one bind an anonymous caller
    could reach.
    """
    from serve.api import main

    site = ROOT / "serve"
    assert main(["--host", "127.0.0.1", "--site-dir", str(site), "--port", "0"]) == 2


def test_specify_is_off_unless_asked_for_on_every_bind() -> None:
    """It defaulted to `loopback`, which is True behind a tunnel."""
    import inspect

    from serve.api import main

    src = inspect.getsource(main)
    assert "enable_specify = bool(a.enable_specify)" in src
    assert "loopback if a.enable_specify" not in src


def test_a_refused_request_is_not_recorded(tmp_path: Path) -> None:
    """Recording a refusal kept the window permanently full: a one-line DoS.

    `allow` appended before comparing, so a client over the limit could never
    fall back under it -- one loop from any address held the bucket shut for
    everyone, including the operator, unauthenticated, for as long as it ran.
    """
    from serve.api import RATE_LIMIT, State

    st = State(tmp_path / "deploy", tmp_path / "site", tmp_path / "run")
    for _ in range(RATE_LIMIT):
        assert st.allow("1.2.3.4")
    assert not st.allow("1.2.3.4")
    st._hits["1.2.3.4"] = []
    assert st.allow("1.2.3.4"), "a refused client could never recover"


def test_a_non_ascii_authorization_header_is_a_401_not_a_crash() -> None:
    """Headers decode as ISO-8859-1; `compare_digest` on non-ASCII str raises.

    An unauthenticated TypeError told an attacker the password guard was on
    before they spent a guess, and reset the connection with no status.
    """
    import io
    import types

    from serve.api import Handler

    class Capture(Handler):
        def __init__(self) -> None:
            self.state = types.SimpleNamespace(auth="u:p", allow=lambda c: True)
            self.headers = {"Authorization": "Basic \xff\xfe"}
            self.client_address = ("1.2.3.4", 1)
            self.wfile = io.BytesIO()
            self.codes: list[int] = []

        def send_response(self, code: int, message: str | None = None) -> None:
            self.codes.append(code)

        def send_header(self, *a: object, **k: object) -> None:
            return

        def end_headers(self) -> None:
            return

    h = Capture()
    assert h._gate() is False
    assert h.codes == [401]


# ------------------------------------------------- specify on a shared endpoint


def test_a_second_run_is_refused_not_queued(tmp_path: Path) -> None:
    """A run holds the lock for minutes; a queued caller just times out.

    On a shared endpoint that reads as a broken page. `Busy` is answered 409 so
    the caller is told to retry rather than left hanging.
    """
    from serve.api import Busy, State, _specify

    st = State(tmp_path / "deploy", tmp_path / "site", tmp_path / "run")
    st.model_lock.acquire()
    try:
        with pytest.raises(Busy):
            _specify(st, {"exposure": "m3:Q16.1", "outcome": "m2:Q5.8"})
    finally:
        st.model_lock.release()


def test_a_caller_cannot_choose_what_the_seat_spends(tmp_path: Path) -> None:
    """`model` was taken verbatim from the body on a password-shared endpoint."""
    from serve.api import DEFAULT_MODELS, PIPELINE_MODEL, State, _specify

    assert DEFAULT_MODELS == frozenset({PIPELINE_MODEL})
    st = State(tmp_path / "deploy", tmp_path / "site", tmp_path / "run")
    with pytest.raises(ValueError, match="not offered by this endpoint"):
        _specify(st, {"exposure": "m3:Q16.1", "outcome": "m2:Q5.8",
                      "model": "claude-opus-5"})


def test_the_operator_can_widen_the_model_list(tmp_path: Path) -> None:
    """Anti-vacuity: the allowlist is a control, not a wall."""
    from serve.api import PIPELINE_MODEL, State

    st = State(tmp_path / "deploy", tmp_path / "site", tmp_path / "run",
               allowed_models=frozenset({PIPELINE_MODEL, "claude-sonnet-5"}))
    assert "claude-sonnet-5" in st.allowed_models


def _scored_run(root: Path) -> Path:
    """Write a two-row run: one emitted artefact and one the ledger discarded.

    Args:
        root: Directory to build the runs tree under.

    Returns:
        The runs directory, ready for `COMPASS_SCORED_RUNS`.
    """
    run = root / "r1"
    run.mkdir(parents=True)

    def artefact(h: str, ex: str, out: str) -> dict[str, object]:
        return {"artefact": {"record_hash": h, "estimability": "blocked_no_metadata",
                             "protocol": {
                                 "question": "q",
                                 "exposure": {"key": ex, "quoted_wording": "sha256:a"},
                                 "outcome": {"key": out, "quoted_wording": "sha256:b"},
                                 "expected_direction": {"direction": "increase"}}}}

    (run / "kept.json").write_text(json.dumps(artefact("aaaa", "m9:Q1.1", "m9:Q2.2")))
    # Written, then discarded by the ledger. A route that globbed would serve it.
    (run / "dropped.json").write_text(json.dumps(artefact("bbbb", "m9:Q3.3", "m9:Q4.4")))
    (run / "ledger.jsonl").write_text(
        json.dumps({"record_hash": "aaaa", "outcome": "emitted"}) + "\n"
        + json.dumps({"record_hash": "bbbb", "outcome": "discarded"}) + "\n")
    return root


def test_metrics_withholds_the_keys_unless_the_operator_asked_for_them(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The default endpoint serves a scored run's shape, never its instrument."""
    from serve import api

    monkeypatch.setattr(api, "SCORED_RUNS", _scored_run(tmp_path / "runs"))
    st = api.State(tmp_path / "deploy", tmp_path / "site", tmp_path / "run")
    assert st.show_instrument is False
    out = api._metrics(st, {"run": "r1"})
    assert out["pairs"] is None
    assert "show-instrument" in out["why"]
    assert "m9:Q1.1" not in json.dumps(out)


def test_metrics_run_id_cannot_traverse(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`run` names a directory; a path is not a run id."""
    from serve import api

    monkeypatch.setattr(api, "SCORED_RUNS", _scored_run(tmp_path / "runs"))
    st = api.State(tmp_path / "deploy", tmp_path / "site", tmp_path / "run")
    for bad in ("../r1", "r1/../r1", "/etc", "."):
        with pytest.raises(ValueError, match="not a run id"):
            api._metrics(st, {"run": bad})


def test_metrics_serves_the_ledgers_emitted_rows_not_the_directory(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A discarded pair can still have written an artefact file."""
    from serve import api

    monkeypatch.setattr(api, "SCORED_RUNS", _scored_run(tmp_path / "runs"))
    monkeypatch.setattr(api, "_metrics_wording", lambda key: None)
    st = api.State(tmp_path / "deploy", tmp_path / "site", tmp_path / "run",
                   show_instrument=True)
    out = api._metrics(st, {"run": "r1"})
    assert set(out["pairs"]) == {"aaaa"}, "the discarded artefact was served"
    assert out["scored"] == out["served"] == 1


def test_an_unresolvable_key_refusal_stays_readable_after_redaction() -> None:
    """The refusal used to redact itself into silence.

    `_canonical_key` interpolated the caller's key into its own message, and
    `Scrubber.scrub` replaces a whole string that carries a key. A reviewer who
    typed a lower-case letter therefore got `{"error": REDACTED}` and no way to
    find out why -- the endpoint's most common 400, answered with nothing.
    """
    from serve.api import Unresolvable

    sc = Scrubber()
    exc = Unresolvable("exposure", "m3:1_q16.1")
    body = {"error": str(exc), "role": exc.role, "typed": exc.typed}
    out, marks = sc.scrub(body)

    # The advice arrives whole. Asserting on the text, not merely on "not
    # REDACTED": a message reduced to a stub would also pass that.
    assert out["error"] == str(exc)
    assert "case-sensitive" in out["error"]
    assert "allow_unresolvable" in out["error"]
    # ...and it identifies which of the two inputs was wrong, without a key.
    assert out["role"] == "exposure"

    # Anti-vacuity: the key itself is still withheld. A message that survives
    # because the scrubber stopped working is the failure this pairs against.
    assert out["typed"] == REDACTED
    assert marks == ["typed"]


def test_the_unresolvable_advice_names_no_key_of_its_own() -> None:
    """A literal example key redacts the message as thoroughly as the caller's.

    The message that this replaced said keys "look like 'm3:Q16.1'", so it was
    redacted in full even for a caller whose own input was clean. This is the
    property that keeps it readable, held against the scrubber rather than
    against a regex, so a newly built key shape cannot slip past it.
    """
    from serve.api import Unresolvable

    sc = Scrubber()
    for role in ("exposure", "outcome"):
        advice = str(Unresolvable(role, "m3:1_q16.1"))
        assert sc.hits(advice) == [], (role, sc.hits(advice))
        assert not KEY_RE.search(advice), role


def test_a_withheld_marker_below_the_top_level_is_refused(tmp_path: Path) -> None:
    """`--site-dir` one level above a clone used to be cleared to serve it.

    The check tested `site_dir / marker` and nothing deeper. The static route's
    containment check is satisfied by exactly these paths -- they ARE inside
    `site_dir` -- so a parent directory cleared here made every
    `question_text` in the clone downloadable.
    """
    from serve.api import _refuse_unsafe_site_dir

    site = tmp_path / "pages"
    (site / "clone" / "build").mkdir(parents=True)
    (site / "clone" / "build" / "dictionary.json").write_text("{}", encoding="utf-8")
    msg = _refuse_unsafe_site_dir(site, tmp_path / "run")

    assert msg is not None
    # Named by path, not just by marker: the operator has to be able to find it.
    assert "clone/build" in msg.replace(os.sep, "/")


def test_a_clean_page_directory_is_still_served(tmp_path: Path) -> None:
    """Anti-vacuity for the walk: it is a filter, not a wall.

    A check that refused everything would pass the test above trivially, and
    would take the published page down with it.
    """
    from serve.api import _refuse_unsafe_site_dir

    site = tmp_path / "pages"
    (site / "artefacts").mkdir(parents=True)
    (site / "index.html").write_text("<h1>page</h1>", encoding="utf-8")
    (site / "artefacts" / "runs.json").write_text("{}", encoding="utf-8")

    assert _refuse_unsafe_site_dir(site, tmp_path / "run") is None


def test_a_tree_too_large_to_certify_is_refused_not_served(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed. Finding no marker in the part we looked at is not "none"."""
    import serve.api as api

    site = tmp_path / "pages"
    for i in range(4):
        (site / f"d{i}").mkdir(parents=True)
    monkeypatch.setattr(api, "MAX_SITE_DIR_WALK", 2)
    msg = api._refuse_unsafe_site_dir(site, tmp_path / "run")

    assert msg is not None
    assert "cannot" in msg and "certify" in msg
    # ...and the same tree is served once the walk can finish, so the refusal is
    # the cap talking and not the directory being rejected for some other reason.
    monkeypatch.setattr(api, "MAX_SITE_DIR_WALK", 100)
    assert api._refuse_unsafe_site_dir(site, tmp_path / "run") is None


def test_every_withheld_hit_text_field_is_covered_structurally() -> None:
    """The allowlist guards one path; the Scrubber has to guard the rest.

    `pseudonymise_hit` keeps `stem`, `option` and `members` off `/api/retrieve`.
    Every OTHER route, and the error path, is guarded by the Scrubber instead --
    and the five-word rule does not reach these fields. MEASURED 2026-09-09 over
    `deploy/targets.json`: `members` has ZERO five-word runs at all, so no
    corpus could ever cover it, and 12 `stem` values carry 14 runs the corpus
    does not hold, because the retriever's stem is a shortened form of
    `stem_text` and the shortening manufactures runs no dictionary field has.

    Asserted as a relationship between the two sets rather than as a field list,
    so a newly withheld field cannot be added on one side alone.
    """
    key_fields = {"key", "construct_key"}
    text_fields = WITHHELD_HIT_FIELDS - key_fields
    assert text_fields <= WORDING_FIELDS, sorted(text_fields - WORDING_FIELDS)
    # The two key fields are covered by the other mechanism, not this one.
    for f in sorted(key_fields):
        assert f not in WORDING_FIELDS


def test_the_retrievers_text_fields_are_redacted_by_name(tmp_path: Path) -> None:
    """By NAME, so content the five-word rule cannot see is still withheld.

    The values here are synthetic: a roster member name short enough that the
    textual rule is blind to it by construction, which is the case that made
    the structural rule necessary. No instrument text belongs in this file.
    """
    sc = Scrubber()
    body = {"stem": "a synthetic stem that no instrument contains anywhere",
            "option": "Strongly agree",
            "members": ["Alice", "Bob"],
            "cos": 0.87,
            "module": "m1",
            "note": "a synthetic sentence carrying no instrument content at all"}
    out, marks = sc.scrub(body)

    assert out["stem"] == REDACTED
    assert out["option"] == REDACTED
    assert out["members"] == REDACTED
    assert sorted(marks) == ["members", "option", "stem"]
    # Anti-vacuity: a filter that redacted everything would pass the above and
    # take the safe fields with it. `note` is prose the rule genuinely cleared.
    assert out["cos"] == 0.87
    assert out["module"] == "m1"
    assert out["note"] == body["note"]


def test_the_role_never_reaches_the_encoder() -> None:
    """`role` changes nothing about the query, so one pool serves both roles.

    `serve/api.py::_role_candidates` passes `role` into `RetrievalRequest`, and
    `deploy/template.py::to_query` never renders it. `_pair` relies on that: it
    builds ONE pool with `role="exposure"` and offers it to both roles. If a
    future `to_query` renders `role`, that pool silently becomes exposure-biased
    while still being served as the outcome pool, and nothing else would catch
    it — `_pair` has no test. This is that test.
    """
    # `deploy/template.py` is tracked and stdlib-only, so this needs none of
    # the withheld bundle artifacts -- no model, no vectors, no targets.json.
    sys.path.insert(0, str(ROOT / "deploy"))
    from template import RetrievalRequest, VariableRole

    for construct in ("blood pressure", "does smoking cause hypertension",
                      "walking while shopping or doing errands"):
        exposure = RetrievalRequest(construct=construct,
                                    role=VariableRole.EXPOSURE).to_query()
        outcome = RetrievalRequest(construct=construct,
                                   role=VariableRole.OUTCOME).to_query()
        assert exposure == outcome, (
            f"to_query rendered `role` for {construct!r}: exposure gave "
            f"{exposure!r} and outcome gave {outcome!r}. serve/api.py::_pair "
            f"offers ONE pool, built with role='exposure', to both roles — that "
            f"pool is now exposure-biased. Either stop rendering role, or give "
            f"_pair a pool per role.")


def test_pinned_roles_come_from_position_not_from_the_sentence() -> None:
    """C31(a): a pinned key's role is its position, as `_pin_keys_from_prose` says.

    "is X predicted by Y" names the outcome first, and position pins it as the
    exposure. The rule is stated rather than fixed because reading direction from
    grammar is a heuristic nothing checks; this holds the code to the statement,
    so a change to either has to change both.
    """
    from serve.api import _pin_keys_from_prose

    constructs = {"m3:Q4.2": None, "m2:Q5.8": None}
    assert _pin_keys_from_prose("is m3:Q4.2 predicted by m2:Q5.8", constructs) == {
        "exposure": "m3:Q4.2", "outcome": "m2:Q5.8"}
    assert _pin_keys_from_prose("does m2:Q5.8 predict m3:Q4.2", constructs) == {
        "exposure": "m2:Q5.8", "outcome": "m3:Q4.2"}


def test_a_third_named_key_is_refused_not_dropped() -> None:
    """C31(b): `zip(..., strict=False)` dropped a third key without a word."""
    from serve.api import _pin_keys_from_prose

    constructs = {"m3:Q4.2": None, "m2:Q5.8": None, "m1:Q1.1": None}
    with pytest.raises(ValueError, match="names 3 distinct keys"):
        _pin_keys_from_prose("m3:Q4.2 and m1:Q1.1 against m2:Q5.8", constructs)
    # Anti-vacuity: a repeated key, in either case, is one key and not a third.
    assert _pin_keys_from_prose("m3:Q4.2, M3:q4.2 and m2:Q5.8", constructs) == {
        "exposure": "m3:Q4.2", "outcome": "m2:Q5.8"}


def test_a_pair_named_in_prose_spends_nothing_and_says_the_role_was_positional(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`_pair`'s first test: two named keys are honoured, and the human is told how.

    With both keys pinned the route must retrieve nothing and call no model, and
    each anchor's `reason` must say its role came from position. The old reason,
    "the request named this key, so it was not inferred", sat beside an outcome
    labelled exposure for "is X predicted by Y".
    """
    import time

    from agent import cli_backend
    from serve import api

    class _NoModel:
        """Stands in for the backend; any model call fails the run."""

        name = "no-model"
        last_cost = None

        def __init__(self, **_: object) -> None:
            pass

        def transduce(self, *_: object) -> None:
            raise AssertionError("a pair the request pinned must make no model call")

    def _no_retrieval(*_: object) -> None:
        pytest.fail("a pair the request pinned must not retrieve")

    monkeypatch.setattr(cli_backend, "ClaudeCliBackend", _NoModel)
    monkeypatch.setattr(api, "_role_candidates", _no_retrieval)
    st = api.State(tmp_path / "deploy", tmp_path / "site", tmp_path / "run")
    # TASKS.md's C31 example. Both keys must be citable as well as constructs:
    # a pinned anchor quotes its wording, and `labels.cite` refuses a construct
    # key that is in no registry (`m3:Q16.1` is one).
    ticket = api._pair(st, {"request": "is m3:Q4.2 predicted by m2:Q5.8"})["ticket"]
    deadline = time.time() + 30
    while st.jobs[ticket]["status"] == "running" and time.time() < deadline:
        time.sleep(0.05)
    done = st.jobs[ticket]
    assert done["status"] == "done", done
    roles = done["run"]["roles"]
    for role in ("exposure", "outcome"):
        assert roles[role]["verdict"] == "pinned", roles[role]
        assert "by position" in roles[role]["reason"], roles[role]["reason"]


def test_an_absent_verdict_says_it_is_about_the_pool_not_the_instrument(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C29a: `absent` on a pool of k is a pool miss, and the response says so."""
    import time

    from agent import cli_backend
    from agent import prompt_contract as PC
    from agent.backends import Reply
    from serve import api

    assert api._absence_scope("resolved", 20) is None
    keys = ["m3:Q4.2", "m2:Q5.8"]
    pool = {"cands": PC.candidates_from_keys(keys), "skipped": [],
            "cos": dict.fromkeys(keys, 0.5), "rendered": "q"}

    class _SaysAbsent:
        """A backend whose every answer is `absent`."""

        name = "says-absent"
        last_cost = None

        def __init__(self, **_: object) -> None:
            pass

        def transduce(self, *_: object) -> Reply:
            return Reply(content='{"verdict": "absent", "indices": [], "reason": "no"}')

    monkeypatch.setattr(cli_backend, "ClaudeCliBackend", _SaysAbsent)
    monkeypatch.setattr(api, "_role_candidates", lambda *_a, **_k: pool)
    st = api.State(tmp_path / "deploy", tmp_path / "site", tmp_path / "run")
    ticket = api._pair(st, {"request": "does smoking raise blood pressure"})["ticket"]
    deadline = time.time() + 30
    while st.jobs[ticket]["status"] == "running" and time.time() < deadline:
        time.sleep(0.05)
    done = st.jobs[ticket]
    assert done["status"] == "done", done
    for role in ("exposure", "outcome"):
        out = done["run"]["roles"][role]
        assert out["verdict"] == "absent"
        assert "none of the 2 candidates shown" in out["absent_scope"]
        assert "not a finding that the cohort lacks it" in out["absent_scope"]


def test_both_prose_routes_state_the_scope_of_absent() -> None:
    """`_resolve` needs the deployed bundle to run, so its wiring is read instead."""
    import ast
    import inspect

    from serve import api

    for fn in (api._pair, api._resolve):
        tree = ast.parse(inspect.getsource(fn))
        called = {n.func.id for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert "_absence_scope" in called, (
            f"{fn.__name__} returns a verdict without saying what `absent` covers")


def test_a_resolver_model_is_accepted_only_as_a_model_id() -> None:
    """C17: it lands in a record, so it is held to the shape of a model id."""
    from serve.api import _resolver_model

    assert _resolver_model({}) is None
    assert _resolver_model({"resolver_model": ""}) is None
    assert _resolver_model({"resolver_model": "claude-haiku-4-5"}) == "claude-haiku-4-5"
    for bad in ("x; rm -rf /", "a b", 7, "-leading-dash"):
        with pytest.raises(ValueError, match="model id"):
            _resolver_model({"resolver_model": bad})


def test_specify_tells_run_identity_who_proposed_the_pair() -> None:
    """The posed-pair route names the resolver when there was one."""
    import ast
    import inspect

    from serve import api

    tree = ast.parse(inspect.getsource(api._specify))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "run_identity"]
    assert calls, "_specify no longer builds a run identity"
    assert {"models", "anchors_proposed_by"} <= {k.arg for k in calls[0].keywords}


# --------------------------------------------------------------------------- #
# C29-C: split before retrieving, and fall back to the shared pool when a split
# cannot be used
# --------------------------------------------------------------------------- #

_SPLIT_REQ = "does smoking raise high blood pressure"
_POOLS = {_SPLIT_REQ: ["m3:Q2.1"], "smoking": ["m3:Q4.2"],
          "high blood pressure": ["m2:Q5.8"]}


def _run_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: dict,
              replies: list[str]) -> tuple[dict, list[tuple[str, str, int]]]:
    """Drive `_pair` with scripted model replies and a pool per query text.

    Returns:
        The finished job and every `(query, role, k)` a pool was built for.
    """
    import time

    from agent import cli_backend
    from agent import prompt_contract as PC
    from agent.backends import Reply
    from serve import api

    seen: list[tuple[str, str, int]] = []
    script = iter(replies)

    def fake_pool(_state: object, query: str, role: str, k: int) -> dict:
        seen.append((query, role, k))
        ks = _POOLS[query]
        return {"cands": PC.candidates_from_keys(ks), "cos": dict.fromkeys(ks, 0.5),
                "skipped": [], "rendered": f"q:{query}"}

    class _Scripted:
        """A backend that answers from a script, in order."""

        name = "scripted"
        last_cost = None

        def __init__(self, **_: object) -> None:
            pass

        def transduce(self, *_: object) -> Reply:
            return Reply(content=next(script))

    monkeypatch.setattr(cli_backend, "ClaudeCliBackend", _Scripted)
    monkeypatch.setattr(api, "_role_candidates", fake_pool)
    st = api.State(tmp_path / "deploy", tmp_path / "site", tmp_path / "run",
                   show_instrument=True)
    ticket = api._pair(st, body)["ticket"]
    deadline = time.time() + 30
    while st.jobs[ticket]["status"] == "running" and time.time() < deadline:
        time.sleep(0.05)
    return st.jobs[ticket], seen


_PICK_FIRST = '{"verdict": "resolved", "indices": [1]}'


def test_a_split_pair_builds_each_role_from_its_own_phrases(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C29-C: each phrase is retrieved alone, at an equal share of k."""
    split = json.dumps({"exposures": ["smoking"], "outcomes": ["high blood pressure"]})
    done, seen = _run_pair(tmp_path, monkeypatch,
                           {"request": _SPLIT_REQ, "split": True},
                           [split, _PICK_FIRST, _PICK_FIRST])
    assert done["status"] == "done", done
    run = done["run"]
    assert run["split"]["status"] == "used", run["split"]
    assert ("smoking", "exposure", 10) in seen
    assert ("high blood pressure", "outcome", 10) in seen
    assert [c["key"] for c in run["roles"]["exposure"]["candidates"]] == ["m3:Q4.2"]
    assert [c["key"] for c in run["roles"]["outcome"]["candidates"]] == ["m2:Q5.8"]


def test_a_split_that_adds_a_word_falls_back_to_the_shared_pool(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A refused split leaves the route as it was, and says why."""
    invented = json.dumps({"exposures": ["tobacco"], "outcomes": ["high blood pressure"]})
    done, seen = _run_pair(tmp_path, monkeypatch,
                           {"request": _SPLIT_REQ, "split": True},
                           [invented, _PICK_FIRST, _PICK_FIRST])
    run = done["run"]
    assert run["split"]["status"] == "fallback"
    assert "own words" in run["split"]["why"]
    assert [q for q, _, _ in seen] == [_SPLIT_REQ], "only the shared pool was built"
    for role in ("exposure", "outcome"):
        assert [c["key"] for c in run["roles"][role]["candidates"]] == ["m3:Q2.1"]


def test_split_is_off_unless_asked_for(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The site's route is unchanged until a clean fixture measures the split."""
    done, seen = _run_pair(tmp_path, monkeypatch, {"request": _SPLIT_REQ},
                           [_PICK_FIRST, _PICK_FIRST])
    assert done["run"]["split"] == {"status": "off"}
    assert [q for q, _, _ in seen] == [_SPLIT_REQ]
