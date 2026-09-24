"""Pins for `serve/api.py::_compare`, the website's comparison against a paper.

The route consults the answer key, which lives only in the scoring clone, so
every guarantee here is about what may cross from that clone into this one:
the recorded values may not, its error text may not, nothing it returns may be
written down here, and the record it compares is the one the Specifier
produced, looked up by ticket, never one a caller sends. Each test is named for
the defect its red state reports.

The scoring clone is a STUB built in a temporary directory: a
`benchmark/rediscovery.py` that echoes a scripted reply. No test here reads
the real design key, and none may -- an agent that reads a key and then edits
this clone is the channel the whole arrangement exists to close.
"""

from __future__ import annotations

import ast
import contextlib
import json
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import api  # noqa: E402
from serve.api import State, build_server  # noqa: E402

TICKET = "120000-abcdef"
PMID = "12345678"

#: A stub `benchmark.rediscovery`: records what it was sent, then replays the
#: reply scripted in `stub.json` beside it.
STUB = '''
import json, sys
from pathlib import Path
here = Path(__file__).resolve().parent.parent
(here / "seen_record.json").write_text(sys.stdin.read())
(here / "seen_argv.json").write_text(json.dumps(sys.argv[1:]))
reply = json.loads((here / "stub.json").read_text())
sys.stdout.write(reply.get("stdout", ""))
sys.stderr.write(reply.get("stderr", ""))
sys.exit(reply.get("exit", 0))
'''

#: A boundary payload in the shape rediscovery prints, before the allowlist.
GOOD = {"schema": api.COMPARE_SCHEMA, "pmid": PMID, "design_key_readable": True,
        "same_build": True, "record_dictionary_version": "3dc8415eccfe",
        "dictionary_version": "3dc8415eccfe", "complaint_count": 0,
        "fields": [{"field": "exposure_keys", "state": "MATCH", "why": ""},
                   {"field": "model_form", "state": "REVIEW",
                    "why": "not the same vocabulary"}]}


def _clone(tmp_path: Path, reply: dict) -> Path:
    """Build a stub scoring clone that will answer with `reply`.

    Args:
        tmp_path: pytest's directory.
        reply: `{stdout, stderr, exit}` for the stub to replay.

    Returns:
        The clone's path.
    """
    clone = tmp_path / "scoring"
    (clone / "benchmark").mkdir(parents=True)
    (clone / "benchmark" / "__init__.py").write_text("")
    (clone / "benchmark" / "rediscovery.py").write_text(STUB)
    (clone / "stub.json").write_text(json.dumps(reply))
    return clone


def _state(tmp_path: Path, clone: Path | None, *, enable: bool = True,
           selected: object = "default", status: str = "done",
           kind: str = api.JOB_SPECIFY) -> State:
    """A State holding one Specifier job, with comparison on or off.

    Args:
        tmp_path: pytest's directory.
        clone: The scoring clone, or None.
        enable: Whether `/api/compare` is on.
        selected: The job's selected record; "default" for a small valid one,
            None for a refusal.
        status: The job's status.
        kind: The job's kind.

    Returns:
        The state.
    """
    site = tmp_path / "site"
    site.mkdir(exist_ok=True)
    (site / "index.html").write_text("<html><head></head><body>ok</body></html>")
    state = State(tmp_path / "deploy", site, tmp_path / "run",
                  enable_compare=enable, scoring_clone=clone,
                  scoring_python=sys.executable)
    record = ({"protocol_id": "P-JOB", "question": "q"}
              if selected == "default" else selected)
    job: dict = {"status": status, "kind": kind, "started": 0.0}
    if status == "done":
        job["run"] = {"selected": record,
                      "samples": [{"rejected_record": {"protocol_id": "REJECTED"}}]}
    state.jobs[TICKET] = job
    return state


@contextlib.contextmanager
def _served(state: State) -> Iterator:
    """Run the endpoint on an ephemeral port.

    Args:
        state: The state to serve.

    Yields:
        `(post, get)`: callables returning `(status, body)`.
    """
    srv = build_server("127.0.0.1", 0, state)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://{srv.server_address[0]}:{srv.server_address[1]}"

    def post(route: str, body: dict) -> tuple[int, dict]:
        req = urllib.request.Request(base + route, method="POST",
                                     data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def get(route: str) -> tuple[int, str]:
        with urllib.request.urlopen(base + route, timeout=30) as r:
            return r.status, r.read().decode()

    try:
        yield post, get
    finally:
        srv.shutdown()
        srv.server_close()


def _tree(path: Path) -> dict[str, bytes]:
    """Every file under `path` with its bytes, for before/after comparison.

    Args:
        path: The directory.

    Returns:
        Relative path to content; empty when the directory does not exist.
    """
    if not path.exists():
        return {}
    return {str(p.relative_to(path)): p.read_bytes()
            for p in sorted(path.rglob("*")) if p.is_file()}


# --- the gate ---------------------------------------------------------------- #

def test_the_comparison_route_is_off_unless_asked_for(tmp_path: Path) -> None:
    """A route that consults the answer key is never inferred on."""
    assert State(tmp_path / "d", tmp_path, tmp_path / "r").enable_compare is False, (
        "the comparison route defaults on")
    clone = _clone(tmp_path, {"stdout": json.dumps(GOOD)})
    with _served(_state(tmp_path, clone, enable=False)) as (post, _get):
        code, body = post("/api/compare", {"ticket": TICKET, "pmid": PMID})
    assert code == 403 and "--enable-compare" in body["error"]
    assert not (clone / "seen_record.json").exists(), (
        "a disabled route still ran the scoring clone")


def test_the_page_offers_the_control_only_where_the_route_is_on(tmp_path: Path) -> None:
    """A button that can only answer 403 is a dead button."""
    for enable in (True, False):
        with _served(_state(tmp_path, None, enable=enable)) as (_post, get):
            _code, page = get("/")
        assert ("window.COMPASS_COMPARE=true" in page) is enable


def test_a_scoring_clone_inside_or_around_this_one_is_refused(tmp_path: Path) -> None:
    """The key must live in a different clone from the one prompts are edited in."""
    assert "needs --scoring-clone" in (api._refuse_scoring_clone(None) or "")
    for bad in (api.ROOT, api.ROOT / "benchmark", api.ROOT.parent):
        assert "overlaps it" in (api._refuse_scoring_clone(bad.resolve()) or ""), bad
    assert api._refuse_scoring_clone(tmp_path.resolve()) is None


# --- what crosses the boundary ----------------------------------------------- #

def test_no_recorded_value_crosses_even_when_the_clone_sends_one(tmp_path: Path) -> None:
    """The allowlist, not the scoring clone's good behaviour, keeps the key out.

    Seeded: forwarding `raw` instead of the allowlisted `out` turns this red.
    """
    hostile = {**GOOD, "recorded_design": "WITHHELD-DESIGN-LINE",
               "fields": [{"field": "exposure_keys", "state": "MATCH", "why": "",
                           "recorded": "m3:Q16.1", "specified": "m3:Q16.1"}]}
    clone = _clone(tmp_path, {"stdout": json.dumps(hostile)})
    with _served(_state(tmp_path, clone)) as (post, _get):
        code, body = post("/api/compare", {"ticket": TICKET, "pmid": PMID})
    assert code == 200, body
    text = json.dumps(body)
    assert "m3:Q16.1" not in text and "WITHHELD-DESIGN-LINE" not in text, (
        "a recorded key crossed the clone boundary")
    assert [set(f) for f in body["compare"]["fields"]] == [set(api.COMPARE_FIELD_KEYS)]


def test_a_state_outside_the_four_is_dropped(tmp_path: Path) -> None:
    """A PASS or a score is not one of the declared states and never renders."""
    odd = {**GOOD, "fields": [{"field": "exposure_keys", "state": "PASS", "why": ""},
                              {"field": "model_form", "state": "REVIEW", "why": ""}]}
    clone = _clone(tmp_path, {"stdout": json.dumps(odd)})
    with _served(_state(tmp_path, clone)) as (post, _get):
        _code, body = post("/api/compare", {"ticket": TICKET, "pmid": PMID})
    assert [f["state"] for f in body["compare"]["fields"]] == ["REVIEW"]


def test_the_scoring_clones_error_text_never_crosses(tmp_path: Path) -> None:
    """A validation error echoes field values; only its class name may cross."""
    clone = _clone(tmp_path, {"stderr": "pydantic_core.ValidationError: 1 error\n"
                                        "  value: WITHHELD-QUESTION-WORDING\n"
                                        "ValidationError: WITHHELD-QUESTION-WORDING",
                              "exit": 1})
    with _served(_state(tmp_path, clone)) as (post, _get):
        code, body = post("/api/compare", {"ticket": TICKET, "pmid": PMID})
    assert code == 500
    assert "WITHHELD-QUESTION-WORDING" not in json.dumps(body), (
        "the scoring clone's stderr crossed the boundary")
    assert "could not run" in body["error"]


def test_a_usage_error_is_not_shown_as_a_withheld_key(tmp_path: Path) -> None:
    """Exit 2 is also argparse's; the schema line, not the status, is the sentinel."""
    clone = _clone(tmp_path, {"stderr": "usage: rediscovery.py\nerror: "
                                        "unrecognized arguments: --json", "exit": 2})
    with _served(_state(tmp_path, clone)) as (post, _get):
        code, body = post("/api/compare", {"ticket": TICKET, "pmid": PMID})
    assert code == 500
    assert "withheld" not in body["error"].lower(), (
        "a usage error rendered as a withheld key")
    assert "older commit" in body["error"]


def test_a_stale_clone_without_the_module_is_named(tmp_path: Path) -> None:
    """A clone missing rediscovery.py says so, rather than failing to import."""
    clone = tmp_path / "scoring"
    clone.mkdir()
    with _served(_state(tmp_path, clone)) as (post, _get):
        code, body = post("/api/compare", {"ticket": TICKET, "pmid": PMID})
    assert code == 500 and "no benchmark/rediscovery.py" in body["error"]


# --- what is compared, and what is kept ------------------------------------- #

def test_the_record_is_read_by_ticket_never_from_the_body(tmp_path: Path) -> None:
    """A caller who could send a record could send one built to probe the key."""
    clone = _clone(tmp_path, {"stdout": json.dumps(GOOD)})
    with _served(_state(tmp_path, clone)) as (post, _get):
        post("/api/compare", {"ticket": TICKET, "pmid": PMID,
                              "record": {"protocol_id": "FROM-THE-BODY"}})
    seen = json.loads((clone / "seen_record.json").read_text())
    assert seen["protocol_id"] == "P-JOB", "the route compared a caller-supplied record"


def test_a_refusal_is_not_compared_and_says_why(tmp_path: Path) -> None:
    """The gate's verdict stands: a rejected design is not the pipeline's answer.

    Seeded: falling back to `samples[0].rejected_record` turns this red.
    """
    clone = _clone(tmp_path, {"stdout": json.dumps(GOOD)})
    with _served(_state(tmp_path, clone, selected=None)) as (post, _get):
        code, body = post("/api/compare", {"ticket": TICKET, "pmid": PMID})
    assert code == 400 and "refused this pair" in body["error"]
    assert not (clone / "seen_record.json").exists(), (
        "a rejected design compared as a record")


def test_a_run_still_in_flight_is_not_compared(tmp_path: Path) -> None:
    """No run may see a comparison of itself while it is still being written."""
    clone = _clone(tmp_path, {"stdout": json.dumps(GOOD)})
    with _served(_state(tmp_path, clone, status="running")) as (post, _get):
        code, body = post("/api/compare", {"ticket": TICKET, "pmid": PMID})
    assert code == 400 and "still running" in body["error"]


def test_nothing_is_written_in_the_editing_clone(tmp_path: Path) -> None:
    """The result goes to the browser and nowhere else here.

    Seeded: a `_save_job` call in `_compare` turns this red.
    """
    clone = _clone(tmp_path, {"stdout": json.dumps(GOOD)})
    state = _state(tmp_path, clone)
    before = _tree(state.run_dir)
    with _served(state) as (post, _get):
        code, _body = post("/api/compare", {"ticket": TICKET, "pmid": PMID})
    assert code == 200
    assert _tree(state.run_dir) == before, "comparison persisted in the editing clone"


def test_the_scoring_clone_is_asked_to_ledger_every_comparison(tmp_path: Path) -> None:
    """The ledger is how the tagged baseline learns what the page looked at."""
    clone = _clone(tmp_path, {"stdout": json.dumps(GOOD)})
    with _served(_state(tmp_path, clone)) as (post, _get):
        post("/api/compare", {"ticket": TICKET, "pmid": PMID})
    argv = json.loads((clone / "seen_argv.json").read_text())
    assert "--ledger" in argv
    assert Path(argv[argv.index("--ledger") + 1]).is_relative_to(clone), (
        "the ledger is written outside the scoring clone")


def test_an_unknown_pmid_is_a_bad_request_not_a_broken_clone(tmp_path: Path) -> None:
    reply = {"stdout": json.dumps({"schema": api.COMPARE_SCHEMA, "pmid": PMID,
                                   "error": "unknown_pmid"}), "exit": 1}
    clone = _clone(tmp_path, reply)
    with _served(_state(tmp_path, clone)) as (post, _get):
        code, body = post("/api/compare", {"ticket": TICKET, "pmid": PMID})
    assert code == 400 and "not in the bibliography" in body["error"]


# --- the key reader stays out of this process ------------------------------- #

def test_serve_never_imports_a_key_reader() -> None:
    """The subprocess is the boundary; an in-process import would erase it.

    Seeded: `from benchmark import rediscovery` anywhere under serve/ turns
    this red with the file named.
    """
    readers = {"benchmark.design_key", "benchmark.rediscovery",
               "benchmark.prevalence_key", "benchmark.leak_facts"}
    found = []
    for path in sorted((ROOT / "serve").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            found += [f"{path.name}: {n}" for n in names if n in readers]
    assert not found, f"key reader imported in-process: {found}"


def test_the_boundary_schema_is_the_one_rediscovery_prints() -> None:
    """Restated in serve/ on purpose; the two strings must not drift."""
    from benchmark import rediscovery as RD

    assert api.COMPARE_SCHEMA == RD.BOUNDARY_SCHEMA
    assert set(api.COMPARE_FIELD_KEYS) == set(RD.BOUNDARY_FIELDS)
    assert api.COMPARE_STATES == {RD.MATCH, RD.DIFFERS, RD.REVIEW, RD.UNAVAILABLE}


@pytest.mark.parametrize("body", [{}, {"ticket": TICKET}, {"pmid": PMID},
                                  {"ticket": TICKET, "pmid": "PMID123"}])
def test_a_malformed_request_is_a_bad_request(tmp_path: Path, body: dict) -> None:
    clone = _clone(tmp_path, {"stdout": json.dumps(GOOD)})
    with _served(_state(tmp_path, clone)) as (post, _get):
        code, _body = post("/api/compare", body)
    assert code == 400
