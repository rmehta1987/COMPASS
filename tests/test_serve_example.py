"""Ask's worked example: a kept Specifier run, named by ticket, served as a live one.

The operator asked for a pre-specified example on Ask, and chose a saved run on
the served page over a redacted copy committed everywhere. So the page is told
a TICKET and nothing else, and fetches the record through
`/api/specify/status` -- the route a live run is read through, redaction and
all. These pin the three places that could go wrong: a ticket that is not one
reaching a <script> tag, a ticket that names nothing reaching the page as a dead
button, and the record taking a different path from a live run's.
"""

from __future__ import annotations

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

TICKET = "215333-302845"
RECORD = {"protocol_id": "P-EX", "question": "QUESTION_TEXT"}


def _state(tmp_path: Path, ticket: str | None = TICKET,
           enable_specify: bool = True) -> State:
    site = tmp_path / "site"
    site.mkdir(parents=True, exist_ok=True)
    (site / "index.html").write_text("<html><head></head><body>ok</body></html>")
    return State(tmp_path / "deploy", site, tmp_path / "run", example_ticket=ticket,
                 enable_specify=enable_specify)


def _keep(state: State, job: dict) -> None:
    api._save_job(state, TICKET, job)


_DONE = {"status": "done", "kind": api.JOB_SPECIFY, "run": {"selected": RECORD}}


@contextlib.contextmanager
def _served(state: State) -> Iterator:
    srv = build_server("127.0.0.1", 0, state)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://{srv.server_address[0]}:{srv.server_address[1]}"

    def post(route: str, body: dict) -> tuple[int, dict]:
        req = urllib.request.Request(base + route, method="POST",
                                     data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def get(route: str) -> str:
        with urllib.request.urlopen(base + route, timeout=30) as r:
            return r.read().decode()

    try:
        yield post, get
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("bad", ['"</script><script>alert(1)//', "215333-30284",
                                 "abc", "215333-302845 "])
def test_a_value_that_is_not_a_ticket_never_reaches_the_page(
        tmp_path: Path, bad: str) -> None:
    """It is written into a <script> tag, so State refuses it, not only `main`."""
    with pytest.raises(ValueError, match="not a ticket"):
        _state(tmp_path, bad)


def test_no_example_configured_is_not_a_refusal(tmp_path: Path) -> None:
    assert api._example_refusal(_state(tmp_path, None)) is None


def test_an_example_needs_the_route_it_is_read_through(tmp_path: Path) -> None:
    """Without --enable-specify the status route 403s a Specifier record."""
    st = _state(tmp_path, enable_specify=False)
    _keep(st, _DONE)
    why = api._example_refusal(st)
    assert why and "needs --enable-specify" in why
    with _served(st) as (post, _get):
        code, _body = post("/api/specify/status", {"ticket": TICKET})
    assert code == 403, "the gate this refusal mirrors has moved; re-derive it"


def test_a_ticket_naming_no_kept_run_is_refused(tmp_path: Path) -> None:
    """The run directory is untracked: a ticket from another machine names nothing."""
    why = api._example_refusal(_state(tmp_path))
    assert why and "no finished run is kept" in why


@pytest.mark.parametrize(("job", "says"), [
    ({"status": "done", "kind": api.JOB_PAIR, "run": {}}, "pair job"),
    ({"status": "error", "kind": api.JOB_SPECIFY, "error": "x"}, "status 'error'"),
    ({"status": "done", "kind": api.JOB_SPECIFY, "run": {"selected": None}},
     "no protocol record"),
])
def test_a_kept_run_that_is_not_a_finished_protocol_is_refused(
        tmp_path: Path, job: dict, says: str) -> None:
    """Only a design can be the example: a proposal or a refusal shows none."""
    st = _state(tmp_path)
    _keep(st, job)
    why = api._example_refusal(st)
    assert why and says in why, why


def test_a_kept_finished_protocol_is_accepted(tmp_path: Path) -> None:
    st = _state(tmp_path)
    _keep(st, _DONE)
    assert api._example_refusal(st) is None


def test_the_server_will_not_start_on_an_example_it_cannot_offer(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A button that loads nothing reads as a broken page, so `main` stops first."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<html><head></head></html>")
    rc = api.main(["--host", "127.0.0.1", "--port", "0", "--site-dir", str(site),
                   "--run-dir", str(tmp_path / "run"), "--no-auth",
                   "--enable-specify", "--example-ticket", TICKET])
    assert rc == 2
    assert "no finished run is kept" in capsys.readouterr().err


def test_the_page_names_the_example_only_when_one_is_set(tmp_path: Path) -> None:
    for ticket in (TICKET, None):
        st = _state(tmp_path / str(ticket), ticket)
        with _served(st) as (_post, get):
            page = get("/")
        assert (f'window.COMPASS_EXAMPLE="{TICKET}"' in page) is (ticket is not None)
        assert "window.COMPASS_ENDPOINT=true" in page


def test_the_example_is_read_through_the_status_route_after_a_restart(
        tmp_path: Path) -> None:
    """A fresh process holds no jobs in memory; the kept file is what serves it."""
    st = _state(tmp_path)
    _keep(st, _DONE)
    assert not st.jobs, "the test must start with nothing in memory"
    with _served(st) as (post, _get):
        code, body = post("/api/specify/status", {"ticket": TICKET})
    assert code == 200, body
    assert body["status"] == "done"
    assert body["selected"]["question"] == "QUESTION_TEXT"
