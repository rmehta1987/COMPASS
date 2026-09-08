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

    os.environ.setdefault("COMPASS_DICTIONARY", str(ROOT / "dictionary.json"))
    assert main(["--site-dir", str(repo_ish), "--port", "0"]) == 2
    assert main(["--site-dir", str(safe), "--run-dir", str(safe / "run"),
                 "--port", "0"]) == 2


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


def test_show_instrument_is_refused_on_a_non_loopback_bind() -> None:
    """Who can reach the socket, and what the socket says, are separate claims.

    Together the two flags are "publish the withheld instrument to the network",
    so the combination is refused rather than warned about.
    """
    from serve.api import main

    os.environ.setdefault("COMPASS_DICTIONARY", str(ROOT / "dictionary.json"))
    site = ROOT / "serve"          # any real directory with no withheld markers
    assert main(["--show-instrument", "--host", "0.0.0.0",
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


def test_the_pipeline_model_is_named_and_reported_not_assumed() -> None:
    """A caller may name a model; the payload must say whether it was the proxy."""
    from serve.api import PIPELINE_MODEL

    assert PIPELINE_MODEL == "claude-haiku-4-5"
