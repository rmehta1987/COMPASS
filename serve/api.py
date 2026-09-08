"""A loopback HTTP endpoint so the tool page can drive real runs during testing.

    export COMPASS_CLAUDE_CONFIG_DIR=~/.claude-enterprise   # which seat pays
    export COMPASS_DICTIONARY=/home/mehta5/COMPASS/dictionary.json
    export COMPASS_SITE_DIR=/home/mehta5/compass-site/site
    ./.venv/bin/python -m serve.api --port 8080

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
It is a test rig. It serves `site/` and the two routes that page cannot fake:
`/api/retrieve` runs the deployed CPU retriever, `/api/specify` runs the real
Specifier against headless `claude -p`. Both execute the shipped code paths --
nothing here reimplements ranking, scoring or selection.

It is NOT a measurement surface and NOT a public service.

  * Every record it produces is `externally_posed` with `screened_from=0` and
    never enters a benchmark denominator (`AGENTS.md` §Contamination Practice).
    A pair a browser names was screened from nothing; copying the funnel's
    denominator onto it would fabricate one.
  * There is no grammar enforcement through the CLI (`agent/cli_backend.py`
    names this), and no seed or temperature, so k samples vary without being
    reproducible. A run through here is not evidence about the 8-27B target.
  * It binds loopback by default. `ClaudeCliBackend` uses the CLI's own auth
    rather than an API key, so every `/api/specify` run spends a named human's
    seat -- the one `COMPASS_CLAUDE_CONFIG_DIR` selects -- which is why that
    route is OFF by default anywhere but loopback.

OFF-LOOPBACK, FOR NAMED PEOPLE
------------------------------
`--host` off loopback requires `--auth USER:PASS`, and auth is also what
permits `--show-instrument` there. The distinction is disclosure, not secrecy:
the redaction is a contamination control aimed at the IN-PIPELINE model, and
that model cannot reach a web page at all (`agent/sealed.py::DENY_TOOLS` denies
WebSearch and WebFetch, and `cli_backend.py` passes them to `claude -p`), so
nothing served here can contaminate a run. What is left is who reads it, and
the study distributes the codebooks -- so a researcher who already holds the
dictionary learns nothing new from wording behind a password. An anonymous
socket is a different claim, and the password is the line between them.

Two things auth does NOT fix, both bounded rather than closed: `cos` remains a
wording oracle (`serve/redact.py`), which the rate limit prices rather than
removes; and `/api/specify` has no per-caller accounting, so it stays disabled
unless `--enable-specify` is passed deliberately.

Serving the page from the same origin as the API is the point of the design:
it removes the mixed-content problem, CORS and the tunnel in one move. The
published page on GitHub Pages is unaffected -- it keeps fetching its baked
artefacts and never learns this endpoint exists.
"""
from __future__ import annotations

import argparse
import base64
import hmac
import json
import math
import mimetypes
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve.redact import (  # noqa: E402
    Pseudonymiser,
    Scrubber,
    pseudonymise_hit,
)

#: A browser must not be able to fan out an unbounded number of model calls.
MAX_K = 5

#: The in-pipeline Specifier: the proxy for the 8-27B target
#: (`generate/live_specifier.py`). A run on anything else is a different claim,
#: so `/api/specify` reports which one answered rather than assuming this one.
PIPELINE_MODEL = "claude-haiku-4-5"

#: Largest request body accepted. A `Content-Length` is attacker-supplied even
#: on loopback, and `rfile.read(n)` would otherwise size an allocation from it.
MAX_BODY_BYTES = 64 * 1024

#: Loopback only. Named rather than inlined so the test can assert on it.
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})

#: Requests per client per window, and the window, for a shared endpoint.
#: `cos` is a wording oracle by construction (`serve/redact.py`), and an oracle
#: is only useful at volume: reconstructing a stem means hill-climbing hundreds
#: of near-miss queries. A researcher looking things up makes a handful. This
#: does not close the channel -- nothing does -- but it prices it.
RATE_LIMIT = 60
RATE_WINDOW_S = 60.0


class State:
    """Process-wide handles, built lazily and shared across requests.

    The retriever loads a 33M-parameter encoder and 1,353 vectors, so it is
    built once and reused. `claude -p` runs are serialised: each one allocates
    a sealed worktree and spawns an MCP server, and two of those racing would
    interleave their tool logs -- the file `agent/tool_authority.py` reads to
    decide whether a record is authorised.

    Attributes:
        deploy_root: Where the retriever bundle lives. The withheld
            `targets.json` and `model/` are untracked, so a git worktree does
            not have them and this points at the operator's clone.
        site_dir: The directory served at `/`.
        scrubber: The instrument filter. Built at startup so a missing
            dictionary stops the server rather than a request.
        run_dir: Where the pseudonym map is written. Never served.
    """

    def __init__(self, deploy_root: Path, site_dir: Path, run_dir: Path,
                 show_instrument: bool = False, auth: str | None = None,
                 enable_specify: bool = True) -> None:
        """Prepare shared state and fail early on a missing instrument.

        Args:
            deploy_root: The `deploy/` bundle directory.
            site_dir: The static page directory.
            run_dir: Private output directory for the pseudonym map.
            show_instrument: Serve instrument content -- the question wording as
                well as the key -- unredacted. `main` permits this off loopback
                only when `auth` is set.
            auth: `USER:PASS` for HTTP Basic, or None for no authentication.
                `main` requires it for any non-loopback bind.
            enable_specify: Allow `POST /api/specify`. `main` defaults it to
                loopback-only, because each run spends the operator's seat.
        """
        self.deploy_root = deploy_root
        self.site_dir = site_dir
        self.run_dir = run_dir
        self.show_instrument = show_instrument
        self.auth = auth
        self.enable_specify = enable_specify
        # Per-client request times, for the rate limit. Keyed by source address,
        # which is all a shared endpoint has: this bounds volume, not identity.
        self._hits: dict[str, list[float]] = {}
        self._hits_lock = threading.Lock()
        self.scrubber = Scrubber()
        self.pseud = Pseudonymiser()
        self._retriever: Any = None
        self._retriever_lock = threading.Lock()
        self.model_lock = threading.Lock()
        self.started = time.time()

    def allow(self, client: str) -> bool:
        """Record a request from `client` and say whether it is within the limit.

        Args:
            client: Source address.

        Returns:
            True when the request may proceed.
        """
        now = time.time()
        with self._hits_lock:
            seen = [t for t in self._hits.get(client, []) if now - t < RATE_WINDOW_S]
            seen.append(now)
            self._hits[client] = seen
            return len(seen) <= RATE_LIMIT

    def retriever(self) -> Any:
        """The deployed retriever, loaded on first use.

        Returns:
            The `CompassRetriever` instance. Its constructor asserts the
            dictionary hash and every shipped file's checksum, and raises
            rather than serving stale vectors.
        """
        with self._retriever_lock:
            if self._retriever is None:
                sys.path.insert(0, str(self.deploy_root))
                from retriever import CompassRetriever

                self._retriever = CompassRetriever(root=self.deploy_root)
            return self._retriever


def _int_arg(body: dict[str, Any], name: str, default: int) -> int:
    """Read an integer request field, refusing anything that is not one.

    `int(body.get(name, default))` looks equivalent and is not: a JSON `null`
    reaches it as None and raises TypeError, which the dispatcher turns into a
    500. A caller sending `{"k": null}` made a bad request, not a server error,
    and the status code is the only thing telling them which.

    Args:
        body: The decoded request.
        name: Field to read.
        default: Value when the field is absent.

    Returns:
        The integer.

    Raises:
        ValueError: When the field is present but is not an integer.
    """
    raw = body.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise ValueError(f"{name} must be a number, got {type(raw).__name__}")
    # `json.loads` accepts the non-standard literals `Infinity` and `NaN`, and
    # `1e400` overflows to inf. Those are floats, so they pass the check above,
    # and `int(inf)` raises OverflowError -- which is neither TypeError nor
    # ValueError, so it escaped to the 500 branch: the exact confusion of "bad
    # request" with "server error" this function exists to prevent.
    if isinstance(raw, float) and not math.isfinite(raw):
        raise ValueError(f"{name} must be a finite number, got {raw}")
    try:
        return int(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a number: {exc}") from exc


def _retrieve(state: State, body: dict[str, Any]) -> dict[str, Any]:
    """Run one retrieval and return only what may leave the process.

    Args:
        state: Shared handles.
        body: The request, carrying `query` and optionally `k`.

    Returns:
        The pseudonymised hits, the abstention verdict and the threshold.

    Raises:
        ValueError: When `query` is missing or empty.
    """
    query = str(body.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")
    k = max(1, min(_int_arg(body, "k", 5), 20))
    r = state.retriever()
    hits = r.search(query, k=k)
    top = hits[0]["cos"] if hits else 0.0
    return {
        "query": query,
        "threshold": r.min_cos,
        "abstained": bool(top < r.min_cos),
        "margin_12": round(hits[0]["cos"] - hits[1]["cos"], 6) if len(hits) > 1 else None,
        "hits": [pseudonymise_hit(h, state.pseud,
                                  show_instrument=state.show_instrument)
                 for h in hits],
        # No absolute path here: it named `run_dir` on every response, and said
        # "is written" in the present tense about a file only written at
        # shutdown -- false for the whole life of the server, and permanently
        # false if the process is killed. And the note must not claim targets
        # are pseudonymised while --show-instrument is printing the wording:
        # a response that describes itself wrongly is worse than one that says
        # nothing, because it is the part a reader trusts.
        "note": ("UNREDACTED: question wording, options and variable keys are "
                 "verbatim withheld instrument content (README.md §What is "
                 "withheld). Loopback only; do not paste this anywhere."
                 if state.show_instrument else
                 "Targets are pseudonymised: the instrument is withheld "
                 "(README.md §What is withheld). The label->target map is "
                 "written to the run directory at shutdown and never served. "
                 "`cos` is a wording oracle by construction -- see "
                 "serve/redact.py's module docstring."),
    }


def _canonical_key(key: str, constructs: dict[str, Any], role: str,
                   canonical: dict[str, str]) -> str:
    """Resolve a construct key's case before a model call, or refuse cheaply.

    WHY THIS IS NOT THE MODEL'S JOB. The Specifier is forbidden to substitute a
    key: "never substitute a similar-sounding item -- a key that resolves while
    naming the wrong construct is the one failure with no automated detector."
    That rule has to hold for `m3:Q16.1` -> `m3:Q16.2` as much as for a capital
    letter, and a model cannot be given the second permission without the first.

    So the fix belongs here instead, where it is deterministic and checkable: an
    EXACT case-insensitive match against the dictionary's own key set, which is
    a lookup and not a judgement. MEASURED 2026-09-08: over the 2,929 keys and
    construct keys in `dictionary.json` there are ZERO case-insensitive
    collisions, so such a match names exactly one construct or none.

    Anything short of that is a 400 before any model call. `m3:q16.1` cost a
    live run 78s and $0.04 to be told about a capital letter -- and the refusal
    it produced was correct, which is exactly why the harness has to catch it
    first. Pass `allow_unresolvable` to skip this and drive the refusal path on
    purpose; `generate/live_specifier.py::stand_in` exists so that stays possible.

    Args:
        key: The construct key as the caller typed it.
        constructs: Construct keys to Construct, from `load_constructs`.
        role: `exposure` or `outcome`, for the error message.
        canonical: Mutated with `{typed: resolved}` when a case fix was applied,
            so the response can report it rather than silently rewriting input.

    Returns:
        The key as the dictionary spells it.

    Raises:
        ValueError: When the key resolves to no construct.
    """
    if key in constructs:
        return key
    folded = {k.casefold(): k for k in constructs}
    fixed = folded.get(key.casefold())
    if fixed is not None:
        canonical[key] = fixed
        return fixed
    raise ValueError(
        f"{role} {key!r} does not resolve to a construct in dictionary "
        f"{(constructs and 'loaded') or 'empty'}. Keys are case-sensitive and "
        f"look like 'm3:Q16.1' (module, colon, capital Q, question id). "
        f"Nothing was spent: this is checked before the model runs. Pass "
        f'"allow_unresolvable": true to drive the refusal path deliberately.')


def _specify(state: State, body: dict[str, Any]) -> dict[str, Any]:
    """Run the real Specifier against headless `claude -p` on a posed pair.

    The pair is STATED by the caller, so it carries no funnel denominator:
    `screened_from` is 0 and the selection mode is `externally_posed`. This is
    the same branch `generate/live_specifier.py` takes for `--exposure`, reused
    rather than reimplemented.

    Args:
        state: Shared handles.
        body: The request, carrying `exposure`, `outcome` and optionally `k`,
            `model`, and `allow_unresolvable` to drive the refusal path with a
            key the dictionary does not contain.

    Returns:
        The run: identity, per-sample gate values, and both outcome fields --
        `selected` (a protocol) and `refusal` -- with any instrument wording
        replaced and the replacements listed under `redactions`.

    Raises:
        ValueError: When either construct key is missing or does not resolve,
            or k is out of range.
    """
    exposure = str(body.get("exposure") or "").strip()
    outcome = str(body.get("outcome") or "").strip()
    if not exposure or not outcome:
        raise ValueError("exposure and outcome are both required")
    k = _int_arg(body, "k", 1)
    if not 1 <= k <= MAX_K:
        raise ValueError(f"k must be between 1 and {MAX_K}")
    # The caller MAY name a model, and that is deliberate on a comparison rig --
    # but the first version of this line carried a comment claiming the model was
    # "never widened here" while the code accepted whatever was posted. An
    # unenforced guarantee is this codebase's recurring defect, so the claim is
    # gone and the payload reports whether the pipeline's pinned proxy actually
    # ran. A larger model reads as a better result unless something says it was
    # not the one the pipeline uses.
    model = str(body.get("model") or PIPELINE_MODEL)

    from agent.cli_backend import ClaudeCliBackend
    from agent.specifier import specify
    from generate.funnel import Candidate, load_constructs
    from generate.live_specifier import run_identity, stand_in

    C, version = load_constructs()
    allow_unresolvable = bool(body.get("allow_unresolvable"))
    canonical: dict[str, str] = {}
    if not allow_unresolvable:
        exposure = _canonical_key(exposure, C, "exposure", canonical)
        outcome = _canonical_key(outcome, C, "outcome", canonical)
    pair = Candidate(exposure=C.get(exposure) or stand_in(exposure),
                     outcome=C.get(outcome) or stand_in(outcome))

    with state.model_lock:
        backend = ClaudeCliBackend(model=model, mode="benchmark")
        identity = run_identity(pair, version, 0, backend.name, "externally_posed")
        t0 = time.time()
        res = specify(backend, pair, k=k, mode="benchmark",
                      parked_dir=ROOT / "parked", identity=identity)
        elapsed = round(time.time() - t0, 2)

    # `selected` and `refusal` are two fields on purpose: a refusal is not a
    # protocol that won, and `selected` is None whenever the environment ruled
    # the pair unspecifiable (`agent/specifier.py::Result`). Collapsing them
    # into one "record" here would re-introduce exactly the discrimination that
    # class refuses to push onto its callers, so both are reported.
    payload: dict[str, Any] = {
        "identity": {
            "protocol_id": identity.protocol_id,
            "prompt_hash": identity.prompt_hash,
            "model_id": identity.model_id,
            "dictionary_version": version,
            "screened_from": 0,
            "selection_mode": "externally_posed",
            # A silent rewrite of the caller's input is its own small version of
            # the substitution problem: say what was changed and to what.
            "key_case_corrected": canonical or None,
            "allow_unresolvable": allow_unresolvable,
            "model_requested": model,
            "is_pipeline_model": model == PIPELINE_MODEL,
        },
        "elapsed_s": elapsed,
        "cost_usd": backend.last_cost,
        "yield": res.yield_line,
        "reason": res.reason,
        "samples": [
            {"seed": a.seed, "gate": str(a.gate), "tool_calls": a.steps,
             "transductions": a.attempts,
             "distinct_tools": sorted(set(a.tool_names)),
             "error": a.error}
            for a in res.attempts
        ],
        "selected": (json.loads(res.selected.model_dump_json())
                     if res.selected is not None else None),
        "refusal": (json.loads(res.refusal.model_dump_json())
                    if res.refusal is not None else None),
        "parked": len(res.parked),
        "distinct_valid": res.distinct,
        "not_a_measurement": (
            "externally posed, screened_from=0, no grammar enforcement, no seed. "
            "Never cite this as a result (AGENTS.md §Verification Discipline)."),
    }
    # No scrub here: `Handler._send` filters EVERY response body. Doing it per
    # route is how `/api/retrieve` ended up relying on `pseudonymise_hit` alone.
    return payload


class Handler(BaseHTTPRequestHandler):
    """Static page at `/`, two JSON routes under `/api/`.

    Attributes:
        state: Injected by `build_server`; shared across every request.
    """

    state: State
    server_version = "compass-serve"

    def log_message(self, fmt: str, *args: Any) -> None:
        """Log to stderr with a timestamp.

        Args:
            fmt: printf-style format.
            *args: Its arguments.
        """
        sys.stderr.write(f"{time.strftime('%H:%M:%S')} {fmt % args}\n")

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        """Write one JSON response, filtered.

        THE FILTER LIVES HERE, not in each route. Scrubbing per route is how
        `/api/retrieve` came to rely on `pseudonymise_hit`'s allowlist alone
        while `/api/specify` was filtered, and how the error path was filtered
        by neither: a new route, or a new error, is unprotected by default. One
        chokepoint makes "nothing reaches the socket unscrubbed" a property of
        the class rather than a habit of whoever adds the next handler.

        The static-file branch of `do_GET` deliberately does not pass through
        here: it serves `site/`, whose contents are already proved clean by
        `site/tools/no_instrument.py`, and its own containment check is what
        keeps it inside that directory.

        Args:
            code: HTTP status.
            payload: The body.
        """
        if self.state.show_instrument:
            # The flag exists to show exactly what the scrubber removes, so
            # scrubbing here would silently cancel it -- the operator would pass
            # --show-instrument and still get pseudonyms, with nothing saying
            # why. Only reachable on a loopback bind: `main` refuses the
            # combination otherwise.
            payload = {**payload,
                       "REDACTION_DISABLED": "--show-instrument is on; this "
                                             "response carries withheld content"}
        else:
            payload, marks = self.state.scrubber.scrub(payload)
            if marks:
                payload = {**payload, "redactions": marks}
        raw = json.dumps(payload, indent=1).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _gate(self) -> bool:
        """Authenticate and rate-limit before any route runs.

        Applied to EVERY request including the static page, because the gate is
        what makes off-loopback exposure defensible at all: the endpoint answers
        with instrument wording when `--show-instrument` is set, and `main`
        permits that off-loopback only when auth is configured. A gate the
        static branch skipped would be a gate with a door next to it.

        Returns:
            True when the request may proceed; otherwise the response has
            already been written.
        """
        client = self.client_address[0] if self.client_address else "?"
        if not self.state.allow(client):
            self.send_response(429)
            self.send_header("Retry-After", str(int(RATE_WINDOW_S)))
            self.end_headers()
            return False
        if self.state.auth is None:
            return True
        offered = self.headers.get("Authorization", "")
        expected = "Basic " + base64.b64encode(self.state.auth.encode()).decode()
        # Constant-time: a naive `==` leaks the shared secret one byte at a time
        # to anyone who can time responses, and this endpoint is reachable from
        # off the machine exactly when this check is the thing protecting it.
        if hmac.compare_digest(offered, expected):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="COMPASS test endpoint"')
        self.end_headers()
        return False

    def do_GET(self) -> None:
        """Serve `/console`, `/api/health`, or a file from the site directory."""
        if not self._gate():
            return
        route = self.path.split("?")[0]
        if route in ("/console", "/console/"):
            # Shipped from serve/, NOT from site/. The published page is built
            # by the site clone under its own gate; putting a live panel in
            # there is a separate change with a separate review, and a dev rig
            # must not be able to reach the tracked page by accident.
            body = (Path(__file__).resolve().parent / "console.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/api/health":
            s = self.state
            self._send(200, {
                "ok": True,
                "uptime_s": round(time.time() - s.started, 1),
                # Names, not absolute paths: the full location of the withheld
                # dictionary was on this response.
                "site_dir": s.site_dir.name,
                "deploy_root": s.deploy_root.name,
                "dictionary": s.scrubber.source.name,
                "retriever_loaded": s._retriever is not None,
            })
            return
        rel = route.lstrip("/") or "index.html"
        target = (self.state.site_dir / rel).resolve()
        # `is_relative_to`, not `str.startswith`: a string prefix test passes a
        # sibling whose name merely extends the root -- serving `/…/site-old`
        # to a request under `/…/site` -- and the containment check is the only
        # thing standing between a URL and an arbitrary file read.
        if not target.is_relative_to(self.state.site_dir.resolve()):
            self._send(403, {"error": "path escapes the site directory"})
            return
        if not target.is_file():
            self._send(404, {"error": f"no such file: {rel}"})
            return
        body = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        """Dispatch `/api/retrieve` and `/api/specify`."""
        if not self._gate():
            return
        route = self.path.split("?")[0]
        if route == "/api/specify" and not self.state.enable_specify:
            # Disabled rather than merely rate-limited: every call spends a named
            # human's Claude seat with no per-caller accounting, and runs
            # serialise, so one visitor holds the lock for ten minutes.
            self._send(403, {"error": "/api/specify is disabled on this endpoint "
                                      "(start with --enable-specify). Each run "
                                      "spends the operator's Claude seat and "
                                      "blocks every other caller while it runs."})
            return
        routes = {"/api/retrieve": _retrieve, "/api/specify": _specify}
        fn = routes.get(route)
        if fn is None:
            self._send(404, {"error": f"no route {route}"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, {"error": "Content-Length is not a number"})
            return
        if n > MAX_BODY_BYTES:
            self._send(413, {"error": f"body over {MAX_BODY_BYTES} bytes"})
            return
        try:
            body = json.loads(self.rfile.read(max(n, 0)) or b"{}")
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            # RecursionError is a RuntimeError, not a ValueError: a 4 KB body of
            # nested brackets -- far under MAX_BODY_BYTES -- escaped do_POST
            # entirely, reached socketserver.handle_error and reset the socket,
            # so the client got no status at all from a handler whose sibling
            # branches exist to tell 400 from 500.
            self._send(400, {"error": f"bad JSON body: {type(exc).__name__}"})
            return
        if not isinstance(body, dict):
            self._send(400, {"error": "body must be a JSON object"})
            return
        try:
            self._send(200, fn(self.state, body))
        except ValueError as exc:
            self._send(400, self._scrubbed_error(exc))
        except Exception as exc:
            # The whole failure, not its first line: a run that costs a model
            # call is exactly where the reason has to survive.
            self._send(500, self._scrubbed_error(exc, prefix=True))

    def _scrubbed_error(self, exc: Exception, *, prefix: bool = False) -> dict[str, Any]:
        """Filter an exception message before it is sent.

        THE ERROR PATH IS A RESPONSE PATH. `_specify` scrubs the payload it
        returns, but a raised exception went straight to the socket unfiltered,
        and the exceptions this endpoint raises are the ones most likely to
        quote the instrument: a pydantic `ValidationError` echoes the offending
        field VALUE, and for a record built out of `Cited` labels that value is
        `question_text` byte for byte. So the filter that guards the success
        path guards this one too.

        Args:
            exc: The exception to report.
            prefix: Whether to include the exception class name.

        Returns:
            The error body, with any instrument content replaced.
        """
        return {"error": f"{type(exc).__name__}: {exc}" if prefix else str(exc)}


#: Names that mark a directory as holding withheld material rather than the
#: published page. `README.md` §What is withheld is the source of the list.
WITHHELD_MARKERS = ("dictionary.json", "build", "targets.json", "raw",
                    "prevalence_key.py", "cohort_papers.py")


def _refuse_unsafe_site_dir(site_dir: Path, run_dir: Path) -> str | None:
    """Refuse a `--site-dir` whose contents the static route must not publish.

    The containment check on the static route is correct: it keeps a request
    inside `site_dir`. It says nothing about what `site_dir` IS. Handed the
    repository root it happily serves `build/dictionary.json` -- every
    `question_text` in the instrument -- and, if the run directory sits inside
    it, `pseudonyms.json`, which un-does the pseudonymiser completely. The
    filter guards what this process COMPUTES; nothing guarded what it was
    pointed at.

    Args:
        site_dir: The resolved directory to be served at `/`.
        run_dir: The resolved private output directory.

    Returns:
        The refusal message, or None when the directory is safe to serve.
    """
    for marker in WITHHELD_MARKERS:
        if (site_dir / marker).exists():
            return (f"refusing to serve {site_dir}: it contains {marker!r}, which "
                    f"is withheld (README.md §What is withheld). The static route "
                    f"has no content filter -- point --site-dir at the published "
                    f"page directory, not at a source tree.")
    if run_dir == site_dir or run_dir.is_relative_to(site_dir):
        return (f"refusing to serve {site_dir}: the run directory {run_dir} is "
                f"inside it, so pseudonyms.json would be downloadable and the "
                f"pseudonymiser would be pointless.")
    return None


def build_server(host: str, port: int, state: State) -> ThreadingHTTPServer:
    """Wire the handler to shared state and bind the socket.

    Args:
        host: Bind address.
        port: Bind port.
        state: Shared handles.

    Returns:
        The bound, unstarted server.
    """
    handler = type("BoundHandler", (Handler,), {"state": state})
    return ThreadingHTTPServer((host, port), handler)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Read the endpoint's arguments.

    Args:
        argv: The command line, without the program name.

    Returns:
        The parsed arguments.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--site-dir", type=Path,
                    default=Path("/home/mehta5/compass-site/site"))
    ap.add_argument("--deploy-root", type=Path, default=ROOT / "deploy")
    ap.add_argument("--run-dir", type=Path, default=ROOT / "run" / "serve")
    ap.add_argument("--auth", default=None,
                    help="USER:PASS for HTTP Basic auth, or set COMPASS_SERVE_AUTH. "
                         "Required for any non-loopback bind, and it is what "
                         "permits --show-instrument off-loopback.")
    ap.add_argument("--enable-specify", action="store_true", default=None,
                    help="allow POST /api/specify. On by default on loopback; "
                         "OFF by default anywhere else, because each run spends "
                         "the operator's Claude seat and serialises the server.")
    ap.add_argument("--show-instrument", action="store_true",
                    help="return the question wording, options and variable key "
                         "beside each hit instead of a pseudonym. Loopback only. "
                         "For an operator testing retrieval against a dictionary "
                         "already on their own disk -- a pseudonym cannot tell "
                         "you whether the RIGHT variable was found.")
    ap.add_argument("--i-am-not-serving-the-public", action="store_true",
                    help="required to bind a non-loopback address; every "
                         "request spends the seat COMPASS_CLAUDE_CONFIG_DIR "
                         "selects, and responses carry withheld instrument "
                         "content unless redaction holds")
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    """Start the endpoint.

    Args:
        argv: The command line, without the program name.

    Returns:
        Process exit code.
    """
    a = parse_args(argv)
    if a.host not in LOOPBACK and not a.i_am_not_serving_the_public:
        print(f"refusing to bind {a.host}: not a loopback address. Every request "
              f"spends a named human's Claude seat and the retriever answers "
              f"with withheld instrument content. Pass "
              f"--i-am-not-serving-the-public if you meant it.", file=sys.stderr)
        return 2
    if not a.site_dir.is_dir():
        print(f"site dir not found: {a.site_dir}", file=sys.stderr)
        return 2
    unsafe = _refuse_unsafe_site_dir(a.site_dir.resolve(), a.run_dir.resolve())
    if unsafe:
        print(unsafe, file=sys.stderr)
        return 2
    auth = a.auth or os.environ.get("COMPASS_SERVE_AUTH")
    loopback = a.host in LOOPBACK
    # Auth is what makes an off-loopback bind defensible, so it is required
    # there rather than recommended. On loopback the OS already limits reach.
    if not loopback and not auth:
        print(f"refusing to bind {a.host} without --auth USER:PASS (or "
              f"COMPASS_SERVE_AUTH). Off loopback this endpoint is reachable by "
              f"anyone who can route to it, and it answers with instrument "
              f"content.", file=sys.stderr)
        return 2
    if auth and ":" not in auth:
        print("--auth must be USER:PASS", file=sys.stderr)
        return 2
    # `--show-instrument` off-loopback is permitted ONLY behind auth. The
    # redaction is a contamination control aimed at the in-pipeline model, and
    # that model cannot reach a web page at all -- `agent/sealed.py::DENY_TOOLS`
    # denies WebSearch and WebFetch at the process boundary, so nothing served
    # here can reach it. What remains is disclosure, and the codebooks are
    # distributed by the study, so a named researcher who already holds the
    # dictionary learns nothing new. An ANONYMOUS socket is a different claim,
    # and auth is the line between the two.
    if a.show_instrument and not loopback and not auth:
        print(f"refusing --show-instrument on {a.host} without --auth: wording "
              f"behind a password is a disclosure to named people; wording on "
              f"an open socket is a publication.", file=sys.stderr)
        return 2
    enable_specify = loopback if a.enable_specify is None else a.enable_specify
    state = State(a.deploy_root.resolve(), a.site_dir.resolve(), a.run_dir.resolve(),
                  show_instrument=a.show_instrument, auth=auth,
                  enable_specify=enable_specify)
    srv = build_server(a.host, a.port, state)
    print(f"COMPASS test endpoint   http://{a.host}:{a.port}/")
    print(f"  site        {state.site_dir}")
    print(f"  deploy      {state.deploy_root}")
    print(f"  dictionary  {state.scrubber.source} "
          f"({len(state.scrubber.corpus)} five-word runs indexed)")
    print("  routes      GET /api/health · GET /console · POST /api/retrieve"
          " · POST /api/specify")
    print("  NOT a measurement surface: posed records, screened_from=0.")
    if state.show_instrument:
        print("  ** --show-instrument: responses carry question wording, options "
              "and keys VERBATIM. Withheld content. Loopback only. **")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.pseud.dump(state.run_dir / "pseudonyms.json")
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
