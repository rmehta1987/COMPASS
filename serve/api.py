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
    KEY_RE,
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

#: Models a REQUEST may name. The body used to be taken verbatim, so anyone
#: holding the shared password chose what the operator's seat spent -- and a
#: larger model reads as a better result. The operator widens this with
#: `--allow-model`; a caller cannot.
DEFAULT_MODELS = frozenset({PIPELINE_MODEL})


class Busy(RuntimeError):
    """A serialised resource is in use. Answered as 409, not 500 or a hang."""

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

#: How often a client should ask again about a running job, in milliseconds.
#: Sent to the page rather than written there: `site/tools/no_fabrication.py`
#: forbids a numeric literal on the page, and a poll interval is a number the
#: server knows and the page should not invent.
POLL_MS = 4000

#: Distinct clients tracked before aged-out windows are swept.
RATE_CLIENTS = 4096

#: Wall-clock ceiling on one request's socket. `BaseHTTPRequestHandler` sets
#: none, so a connection that opens and sends nothing holds a thread for ever,
#: BEFORE `_gate` runs -- neither auth nor the rate limit is involved. A few
#: thousand of those exhaust a `ThreadingHTTPServer` with no request made.
REQUEST_TIMEOUT_S = 30


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
                 enable_specify: bool = True,
                 allowed_models: frozenset[str] | None = None) -> None:
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
            enable_specify: Allow `POST /api/specify`. Off unless `main` is
                asked for it, because each run spends the operator's seat.
            allowed_models: Models a REQUEST may name. Defaults to the pipeline
                proxy alone; the operator widens it, never the caller.
        """
        self.deploy_root = deploy_root
        self.site_dir = site_dir
        self.run_dir = run_dir
        self.show_instrument = show_instrument
        self.auth = auth
        self.enable_specify = enable_specify
        self.allowed_models = frozenset(allowed_models or DEFAULT_MODELS)
        # Per-client request times, for the rate limit. Keyed by source address,
        # which is all a shared endpoint has: this bounds volume, not identity.
        self._hits: dict[str, list[float]] = {}
        self._hits_lock = threading.Lock()
        # Finished and in-flight Specifier runs, by ticket. A run outlives the
        # request that started it, so the result has to live somewhere the next
        # request can find it.
        self.jobs: dict[str, dict[str, Any]] = {}
        self._jobs_lock = threading.Lock()
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
            # DO NOT record a refused request. Appending before the comparison
            # meant a client over the limit kept its own window permanently full
            # and could never recover -- one loop from any address held the
            # bucket shut for everyone, unauthenticated, forever.
            if len(seen) >= RATE_LIMIT:
                self._hits[client] = seen
                return False
            seen.append(now)
            self._hits[client] = seen
            # Evict clients whose windows have aged out. Pruning only the
            # REQUESTING client left a key per address seen, which a rotating
            # source grows without bound.
            if len(self._hits) > RATE_CLIENTS:
                self._hits = {k: v for k, v in self._hits.items()
                              if v and now - v[-1] < RATE_WINDOW_S}
            return True

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
    # Build the request through the SHIPPED template rather than encoding the
    # free text, so what is reported is what was actually encoded. `to_query`
    # drops an instance whose content words the construct already carries, and
    # that silent drop is exactly what the Intake panel exists to show.
    from retriever import (  # after retriever() extends sys.path
        RetrievalRequest,
        VariableRole,
    )
    from template import covered
    req = RetrievalRequest(construct=query, role=VariableRole.EXPOSURE,
                           instances=list(body.get("instances") or []))
    rendered = req.to_query()
    hits = r.search(rendered, k=k)
    top = hits[0]["cos"] if hits else 0.0
    return {
        "query": query,
        # What the encoder saw, and how it was assembled. Same fields the
        # committed runs carry, so the panel renders a live query and a run
        # through one code path.
        "rendered_query": rendered,
        "request": {"construct": query, "role": "exposure",
                    "instances": list(body.get("instances") or []),
                    "population": None},
        # The TEMPLATE's own predicate, not a substring test. `breast cancer` is
        # dropped from `how often siblings were diagnosed with breast cancer`
        # because every content word is already there -- and it is also a
        # substring of it, so `not in rendered` reported nothing dropped and the
        # panel silently disagreed with the template it exists to explain.
        "instances_dropped_as_covered": [
            i for i in (body.get("instances") or [])
            if i and covered(i, query)],
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


def _pin_keys_from_prose(request: str, constructs: dict[str, Any]) -> dict[str, str]:
    """Keys the caller wrote into the request, in the order they appear.

    A key in the prose is not something to infer. `m3:Q4.2 and m2:Q5.8` has
    already answered the question the model would be asked, so it is honoured
    directly -- first key is the exposure, second the outcome, which is the
    order the sentence puts them in.

    Args:
        request: The researcher's prose.
        constructs: Construct keys to Construct, for validation.

    Returns:
        `{role: key}` for whichever roles the prose pinned.
    """
    seen: list[str] = []
    for raw in KEY_RE.findall(request):
        fixed = raw if raw in constructs else None
        if fixed is None:
            folded = {k.casefold(): k for k in constructs}
            fixed = folded.get(raw.casefold())
        if fixed and fixed not in seen:
            seen.append(fixed)
    roles = {}
    for role, key in zip(("exposure", "outcome"), seen, strict=False):
        roles[role] = key
    return roles


def _role_candidates(state: State, request: str, role: str, k: int) -> dict[str, Any]:
    """The pool for one role, and the surface that will be asked about it.

    The request is framed by role because the same prose contains both, and the
    retriever cannot tell which half it is being asked for. That framing is the
    only project-authored text this route adds to a model-visible surface.

    Args:
        state: Shared handles.
        request: The researcher's prose.
        role: `exposure` or `outcome`.
        k: Pool size.

    Returns:
        `{"surface": SelectionContract, "candidates": [...], "cos": {...}}`.

    Raises:
        ValueError: When no candidate can be bound to wording.
    """
    from agent import prompt_contract as PC
    from env import labels

    # `state.retriever()` is what extends sys.path to the deploy bundle, so the
    # bundle's own modules import only AFTER it has run once. Import-sorting
    # moved this above that call and the route died with ModuleNotFoundError on
    # a cold server -- the ordering is load-bearing, not stylistic.
    r = state.retriever()
    from retriever import RetrievalRequest, VariableRole

    req = RetrievalRequest(construct=request,
                           role=VariableRole.EXPOSURE if role == "exposure"
                           else VariableRole.OUTCOME)
    hits = r.search(req.to_query(), k=k)

    keys, facts, cos_by_key, skipped = [], {}, {}, []
    for h in hits:
        key = h["key"]
        try:
            labels.cite(key)
        except Exception:
            skipped.append(key)
            continue
        keys.append(key)
        cos_by_key[key] = h["cos"]
        facts[key] = {"module": h["module"], "roster_family_size": h["fold_size"]}
    if not keys:
        raise ValueError(f"no candidate for the {role} could be bound to wording")

    cands = PC.candidates_from_keys(keys, facts)
    framed = f"{request}\n\nWhich item serves as the {role.upper()} here?"
    return {"surface": PC.retrieval_contract(framed, cands),
            "cands": cands, "cos": cos_by_key, "skipped": skipped}


def _pair(state: State, body: dict[str, Any]) -> dict[str, Any]:
    """Propose BOTH anchors from one piece of prose. The human confirms.

    Args:
        state: Shared handles.
        body: The request, carrying `request` prose and optionally `k`, `model`.

    Returns:
        A ticket; the run is two model calls.

    Raises:
        ValueError: When `request` is missing or the model is not offered.
        Busy: When another model run holds the lock.
    """
    request = str(body.get("request") or "").strip()
    if not request:
        raise ValueError("request is required: this route takes prose")
    # Deeper than the single-construct route by default: a request naming two
    # constructs has to carry candidates for both halves in one pool.
    k = max(2, min(_int_arg(body, "k", 20), 40))
    model = str(body.get("model") or PIPELINE_MODEL)
    if model not in state.allowed_models:
        raise ValueError(f"model {model!r} is not offered by this endpoint.")

    from generate.funnel import load_constructs
    constructs, version = load_constructs()
    pinned = _pin_keys_from_prose(request, constructs)

    # ONE POOL, OFFERED TO BOTH ROLES. `deploy/template.py:12` states it
    # outright -- "`role` is never rendered" -- so a per-role request builds the
    # IDENTICAL query and the identical pool; asking twice bought nothing and I
    # had assumed otherwise. MEASURED on "does cigarette smoking raise the risk
    # of high blood pressure": at k=8 every candidate was a hypertension item
    # and the exposure came back `absent` -- correctly, because smoking was
    # never offered. At k=20 the smoking items appear at ranks 19-20. So the
    # pool is deepened and shared, and the model picks each role from it.
    shared = None if len(pinned) == 2 else _role_candidates(state, request, "exposure", k)
    roles = {r: shared for r in ("exposure", "outcome") if r not in pinned}

    if not state.model_lock.acquire(blocking=False):
        raise Busy("a model run is already in progress on this endpoint.")
    ticket = f"{time.strftime('%H%M%S')}-{os.urandom(3).hex()}"
    with state._jobs_lock:
        state.jobs[ticket] = {"status": "running", "started": time.time()}

    def _run() -> None:
        try:
            from agent import prompt_contract as PC
            from agent.cli_backend import ClaudeCliBackend
            from env import labels

            backend = ClaudeCliBackend(model=model, mode="benchmark")
            t0 = time.time()
            out: dict[str, Any] = {}
            for role in ("exposure", "outcome"):
                if role in pinned:
                    key = pinned[role]
                    out[role] = {
                        "verdict": "pinned",
                        "reason": "the request named this key, so it was not inferred",
                        "proposed_indices": [],
                        "pinned_key": key if state.show_instrument else None,
                        "pinned_wording": labels.cite(key).wording,
                        "candidates": [],
                    }
                    continue
                pool = roles[role]
                # The role framing goes on the ASK, not the pool: one pool,
                # two questions of it.
                framed = PC.retrieval_contract(
                    f"{request}\n\nWhich item serves as the {role.upper()} here?",
                    pool["cands"])
                chosen = PC.VariableSelection.model_validate_json(
                    _first_json(str(backend.transduce(framed.render()).content)))
                proposed = [i for i in chosen.indices if 1 <= i <= len(pool["cands"])]
                out[role] = {
                    "verdict": chosen.verdict,
                    "reason": chosen.reason,
                    "recipe": chosen.recipe or None,
                    "missing_dimension": chosen.missing_dimension or None,
                    "proposed_indices": proposed,
                    "skipped_uncitable": pool["skipped"],
                    "candidates": [
                        {"index": c.index,
                         "key": c.key if state.show_instrument else None,
                         "wording": c.wording,
                         "proposed": c.index in proposed,
                         "cos": pool["cos"][c.key],
                         **c.facts}
                        for c in pool["cands"]],
                }
            done = {"status": "done", "run": {
                "request": request,
                "dictionary_version": version,
                "model_id": backend.name,
                "elapsed_s": round(time.time() - t0, 2),
                "cost_usd": backend.last_cost,
                "roles": out,
                "anchors_proposed_by": "model",
                "not_a_selection":
                    "Proposals only. Nothing is committed: confirm each anchor "
                    "before running the Specifier. A pair proposed by a model "
                    "is still externally posed -- screened_from stays 0 and it "
                    "never enters a benchmark denominator.",
            }}
        except Exception as exc:
            done = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        finally:
            state.model_lock.release()
        with state._jobs_lock:
            state.jobs[ticket] = done

    threading.Thread(target=_run, daemon=True).start()
    return {"ticket": ticket, "status": "running", "poll_after_ms": POLL_MS,
            "pinned": {r: (k if state.show_instrument else "pinned")
                       for r, k in pinned.items()},
            "note": "Both anchors are proposed, then you confirm. Ask "
                    "/api/specify/status for this ticket."}


def _resolve(state: State, body: dict[str, Any]) -> dict[str, Any]:
    """Resolve prose to CANDIDATES with a model, by index. Never to one key.

    The deployed retriever supplies the pool -- it is the thing that can rank
    1,353 targets against prose cheaply -- and the model then reads the request
    and that pool and says what KIND of answer the request has: one item, a
    whole roster family, something to derive, genuinely ambiguous, or absent.
    That verdict is the part cosine cannot produce, and it is why a compound
    request like "environment and hypertension" can be called ambiguous here
    instead of silently matching one side.

    The model selects by index and never sees a key, so it cannot emit one
    wrong (`agent/prompt_contract.py`). The harness resolves the index against
    the pool it offered.

    Args:
        state: Shared handles.
        body: The request, carrying `request` prose and optionally `k`.

    Returns:
        A ticket. The run is a model call, so it is a job like `/api/specify`.

    Raises:
        ValueError: When `request` is missing or `k` is out of range.
        Busy: When another model run holds the lock.
    """
    request = str(body.get("request") or "").strip()
    if not request:
        raise ValueError("request is required: this route takes prose")
    k = max(2, min(_int_arg(body, "k", 8), 20))
    model = str(body.get("model") or PIPELINE_MODEL)
    if model not in state.allowed_models:
        raise ValueError(
            f"model {model!r} is not offered by this endpoint. Allowed: "
            f"{', '.join(sorted(state.allowed_models))}.")

    r = state.retriever()
    from retriever import RetrievalRequest, VariableRole
    from template import covered  # noqa: F401  (kept beside the other import)

    req = RetrievalRequest(construct=request, role=VariableRole.EXPOSURE)
    rendered = req.to_query()
    hits = r.search(rendered, k=k)

    from agent import prompt_contract as PC
    from env import labels

    keys, facts, skipped, cos_by_key = [], {}, [], {}
    for h in hits:
        key = h["key"]
        try:
            labels.cite(key)          # the only maker of a bound citation
        except Exception:
            skipped.append(key)
            continue
        keys.append(key)
        cos_by_key[key] = h["cos"]
        facts[key] = {"module": h["module"], "roster_family_size": h["fold_size"]}
    if not keys:
        raise ValueError("no candidate in the pool could be bound to wording; "
                         "nothing can be offered for selection")

    cands = PC.candidates_from_keys(keys, facts)
    surface = PC.retrieval_contract(request, cands)

    if not state.model_lock.acquire(blocking=False):
        raise Busy("a model run is already in progress on this endpoint. "
                   "Runs are serialised. Try again in a moment.")
    ticket = f"{time.strftime('%H%M%S')}-{os.urandom(3).hex()}"
    with state._jobs_lock:
        state.jobs[ticket] = {"status": "running", "started": time.time()}

    def _run() -> None:
        try:
            from agent.cli_backend import ClaudeCliBackend
            backend = ClaudeCliBackend(model=model, mode="benchmark")
            t0 = time.time()
            raw = str(backend.transduce(surface.render()).content)
            chosen = PC.VariableSelection.model_validate_json(_first_json(raw))
            proposed = [i for i in chosen.indices if 1 <= i <= len(cands)]
            done = {"status": "done", "run": {
                "request": request,
                "rendered_query": rendered,
                "model_id": backend.name,
                "elapsed_s": round(time.time() - t0, 2),
                "cost_usd": backend.last_cost,
                "verdict": chosen.verdict,
                "reason": chosen.reason,
                "recipe": chosen.recipe or None,
                "missing_dimension": chosen.missing_dimension or None,
                "proposed_indices": proposed,
                "skipped_uncitable": skipped,
                # EVERY candidate, always. The rule is candidates with wording,
                # never one key: a verdict of `resolved` is a PROPOSAL the
                # reader confirms, not a selection this route makes for them.
                "candidates": [
                    {"index": c.index,
                     "key": c.key if state.show_instrument else None,
                     "wording": c.wording,
                     "proposed": c.index in proposed,
                     # Keyed, not zipped: `cands` is shorter than `hits`
                     # whenever a key is skipped as uncitable, and zipping the
                     # two would misalign every cosine after the skip.
                     "cos": cos_by_key[c.key],
                     **c.facts}
                    for c in cands],
                "not_a_selection":
                    "Candidates only. This route never commits an anchor: pick "
                    "one yourself, including when the verdict is `resolved`.",
            }}
        except Exception as exc:
            done = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        finally:
            state.model_lock.release()
        with state._jobs_lock:
            state.jobs[ticket] = done

    threading.Thread(target=_run, daemon=True).start()
    return {"ticket": ticket, "status": "running", "poll_after_ms": POLL_MS,
            "note": "A model reads the request and the candidate pool. Ask "
                    "/api/specify/status for this ticket."}


def _first_json(text: str) -> str:
    """The first JSON object in a model reply.

    There is no grammar enforcement through the CLI (`agent/cli_backend.py`
    names that as an accepted, named degradation), so a reply can carry prose
    or a fence around the object.

    Args:
        text: The raw reply.

    Returns:
        The substring from the first brace to its match.

    Raises:
        ValueError: When no balanced object is present.
    """
    start = text.find("{")
    if start < 0:
        raise ValueError("the model returned no JSON object")
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ValueError("the model returned an unbalanced JSON object")


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
    if model not in state.allowed_models:
        raise ValueError(
            f"model {model!r} is not offered by this endpoint. Allowed: "
            f"{', '.join(sorted(state.allowed_models))}. Every run spends the "
            f"operator's Claude seat, so which model runs is the operator's "
            f"choice (--allow-model), not the caller's.")

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

    # Refuse rather than queue. A run holds this lock for minutes, so a second
    # caller used to block silently and then hit their own client timeout with
    # no idea why -- on a shared endpoint that reads as a broken page. Saying
    # "busy" immediately is the difference between a queue and a hang.
    if not state.model_lock.acquire(blocking=False):
        raise Busy("a Specifier run is already in progress on this endpoint. "
                   "Runs are serialised because each one allocates a sealed "
                   "worktree and an MCP server. Try again in a few minutes.")

    # THE RUN OUTLIVES THE REQUEST. Cloudflare gives up on an origin after about
    # 100 seconds and that ceiling cannot be raised on a quick tunnel, while a
    # run takes 300-600. Held open, the request could never finish through the
    # tunnel however healthy the run was -- and both times it was the request
    # that died, not the run. So the POST starts a job and hands back a ticket.
    ticket = f"{time.strftime('%H%M%S')}-{os.urandom(3).hex()}"
    with state._jobs_lock:
        state.jobs[ticket] = {"status": "running", "started": time.time()}

    def _run() -> None:
        try:
            backend = ClaudeCliBackend(model=model, mode="benchmark")
            identity = run_identity(pair, version, 0, backend.name,
                                    "externally_posed")
            t0 = time.time()
            res = specify(backend, pair, k=k, mode="benchmark",
                          parked_dir=ROOT / "parked", identity=identity)
            payload = _specify_payload(res, identity, version, model, canonical,
                                       allow_unresolvable, backend,
                                       round(time.time() - t0, 2))
            done = {"status": "done", "run": payload}
        except Exception as exc:
            done = {"status": "error",
                    "error": f"{type(exc).__name__}: {exc}"}
        finally:
            state.model_lock.release()
        with state._jobs_lock:
            state.jobs[ticket] = done

    threading.Thread(target=_run, daemon=True).start()
    return {"ticket": ticket, "status": "running", "poll_after_ms": POLL_MS,
            "note": "A run takes minutes. Ask /api/specify/status for this "
                    "ticket; the run continues whatever happens to this page."}


def _specify_status(state: State, body: dict[str, Any]) -> dict[str, Any]:
    """Report a run started earlier, by ticket.

    Args:
        state: Shared handles.
        body: The request, carrying `ticket`.

    Returns:
        `{status: running}` with a poll interval, or the finished run.

    Raises:
        ValueError: When the ticket is missing or unknown.
    """
    ticket = str(body.get("ticket") or "").strip()
    if not ticket:
        raise ValueError("ticket is required")
    with state._jobs_lock:
        job = state.jobs.get(ticket)
    if job is None:
        raise ValueError(f"no run with ticket {ticket!r} on this endpoint. "
                         "Tickets do not survive a restart.")
    if job["status"] == "running":
        return {"status": "running", "poll_after_ms": POLL_MS,
                "elapsed_s": round(time.time() - job["started"], 1)}
    if job["status"] == "error":
        return {"status": "error", "error": job["error"]}
    return {"status": "done", **job["run"]}


def _maybe_json(raw: str | None) -> Any:
    """Parse a rejected record if it is JSON, else hand back the raw text.

    The object a failed transduction emitted is a STRING, and it is often not
    valid JSON -- that is frequently why it was rejected. Returning the text
    when it will not parse keeps the design readable instead of discarding the
    one artefact that says what the model actually built.

    Args:
        raw: The rejected object, or None.

    Returns:
        Parsed JSON, the original string, or None.
    """
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


def _specify_payload(res: Any, identity: Any, version: str, model: str,
                     canonical: dict[str, str], allow_unresolvable: bool,
                     backend: Any, elapsed: float) -> dict[str, Any]:
    """Shape a finished run for the wire.

    Split out of `_specify` so the run can be assembled on the worker thread,
    after the request that started it has already answered.

    Args:
        res: The `agent.specifier.Result`.
        identity: The run identity.
        version: Dictionary version hash.
        model: The model that was asked for.
        canonical: Any key-case corrections applied.
        allow_unresolvable: Whether the refusal path was driven deliberately.
        backend: The backend, for its cost.
        elapsed: Wall-clock seconds.

    Returns:
        The payload `/api/specify/status` returns when the run is done.
    """
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
             "error": a.error,
             "tool_log": a.tool_log_path,
             # THE DESIGN SURVIVES ITS REJECTION. `Attempt` keeps both of these
             # whatever the gate decided, and not showing them made a rejected
             # sample look like nothing had been produced -- a run can spend ten
             # minutes and 49 tool calls building a design and then report only
             # that it failed. The gate's verdict is unchanged; what changes is
             # that the reader can now see and score what was rejected, which is
             # the whole point at this stage of the pipeline.
             "rejected_record": _maybe_json(a.rejected),
             "analysis": a.analysis or None}
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
    #: `socketserver.StreamRequestHandler` honours this; without it a socket
    #: that opens and never speaks pins a thread indefinitely, before `_gate`.
    timeout = REQUEST_TIMEOUT_S

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
        # Headers are decoded as ISO-8859-1, so any byte >= 0x80 yields a
        # non-ASCII str and `compare_digest` raises TypeError rather than
        # returning False -- an unauthenticated crash that told an attacker the
        # password guard was on before they spent a guess. Compare bytes.
        try:
            offered_b = offered.encode("ascii")
        except UnicodeEncodeError:
            offered_b = b""
        # Constant-time: a naive `==` leaks the shared secret one byte at a time
        # to anyone who can time responses, and this check is the thing
        # protecting the endpoint exactly when it is reachable off the machine.
        if hmac.compare_digest(offered_b, expected.encode("ascii")):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="COMPASS test endpoint"')
        self.end_headers()
        return False

    def do_GET(self) -> None:
        """Serve `/console`, `/api/health`, or a file from the site directory."""
        try:
            self._get()
        except Exception as exc:
            # `do_POST` distinguished 400 from 500 and `do_GET` had no `try` at
            # all, so three reachable cases reset the connection with no status:
            # a NUL byte in the path (`Path.resolve` raises ValueError), a
            # missing console.html, and a mode-000 file that `is_file()` says
            # exists. A reset is indistinguishable from a dead endpoint.
            self._send(500, self._scrubbed_error(exc, prefix=True))

    def _get(self) -> None:
        """The GET routes, wrapped by `do_GET`."""
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
            self.send_header("Cache-Control", "no-store, must-revalidate")
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
        if ctype == "text/html":
            # The page's live panel is INERT unless this marker is present, and
            # only the server can honestly set it. Without it the committed page
            # would have to guess whether an endpoint is there, and on GitHub
            # Pages a root-relative `/api/retrieve` does not fail -- it resolves
            # against github.io, leaves the browser carrying the reader's typed
            # text, and returns 404. `site/tools/offline.py` certifies "zero
            # external requests" and cannot see that, so the page must not be
            # able to make it at all.
            body = body.replace(
                b"</head>",
                b"<script>window.COMPASS_ENDPOINT=true;</script></head>", 1)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # This route serves files that are being EDITED. With no cache headers a
        # browser is free to reuse the copy it has, so a plain reload showed the
        # previous page and a change looked like it had not been made -- which
        # is exactly how it looked to the operator when a new panel "did
        # nothing". A dev rig must never make someone wonder whether they are
        # looking at their own edit.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        """Dispatch `/api/retrieve` and `/api/specify`."""
        if not self._gate():
            return
        route = self.path.split("?")[0]
        if route.startswith("/api/specify") and not self.state.enable_specify:
            # Disabled rather than merely rate-limited: every call spends a named
            # human's Claude seat with no per-caller accounting, and runs
            # serialise, so one visitor holds the lock for ten minutes.
            self._send(403, {"error": "/api/specify is disabled on this endpoint "
                                      "(start with --enable-specify). Each run "
                                      "spends the operator's Claude seat and "
                                      "blocks every other caller while it runs."})
            return
        routes = {"/api/retrieve": _retrieve, "/api/specify": _specify,
                  "/api/specify/status": _specify_status,
                  "/api/resolve": _resolve,
                  "/api/pair": _pair}
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
        except Busy as exc:
            # 409, not 500: nothing is broken and retrying is the right move.
            self._send(409, self._scrubbed_error(exc))
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
                         "Required unless --no-auth is passed. The bind address "
                         "does not decide this: a tunnel forwards to 127.0.0.1.")
    ap.add_argument("--no-auth", action="store_true",
                    help="serve with no password, stating that this socket is "
                         "unreachable. An explicit claim, because the process "
                         "cannot see what forwards to it.")
    ap.add_argument("--allow-model", action="append", default=None,
                    metavar="MODEL",
                    help="a model a request may name; repeatable. Defaults to "
                         f"{PIPELINE_MODEL} alone. The caller does not choose "
                         "what the operator's seat spends.")
    ap.add_argument("--enable-specify", action="store_true",
                    help="allow POST /api/specify. OFF by default on every bind: "
                         "each run spends the operator's Claude seat, has no "
                         "per-caller accounting, and holds the lock for minutes.")
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
    # A TUNNEL IS A LOOPBACK BIND. `cloudflared tunnel --url http://127.0.0.1:P`
    # connects TO 127.0.0.1, so `a.host` is a loopback address while the whole
    # internet is routed to the socket. Every guard that read the bind address
    # concluded "private" for exactly the deployment that is public, and the
    # operator was never asked for a password on the one that needed it most.
    # So the bind address decides NOTHING here any more: reachability is a fact
    # about the network, which this process cannot see, and the operator states
    # it instead of the code guessing.
    if not auth and not a.no_auth:
        print("refusing to serve without authentication. Pass --auth USER:PASS "
              "(or COMPASS_SERVE_AUTH), or --no-auth to say plainly that this "
              "socket is unreachable. The bind address cannot tell us which: a "
              "tunnel forwards to 127.0.0.1 and is public.", file=sys.stderr)
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
    # Reachable now. The previous form tested `not loopback and not auth`, which
    # the auth gate above had already returned on, so it was dead code that read
    # like a guarantee. `--no-auth` is the case it actually has to catch.
    if a.show_instrument and a.no_auth and not loopback:
        print(f"refusing --show-instrument with --no-auth on {a.host}: wording "
              f"behind a password is a disclosure to named people; wording on "
              f"an unauthenticated socket is a publication.", file=sys.stderr)
        return 2
    # OFF unless asked for, on every bind. It used to default to `loopback`,
    # which meant it was ON behind a tunnel -- the one place where an anonymous
    # caller could spend the operator's Claude seat and hold the lock for
    # minutes. A route that expensive is not something to infer.
    enable_specify = bool(a.enable_specify)
    state = State(a.deploy_root.resolve(), a.site_dir.resolve(), a.run_dir.resolve(),
                  show_instrument=a.show_instrument, auth=auth,
                  enable_specify=enable_specify,
                  allowed_models=frozenset(a.allow_model or DEFAULT_MODELS))
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
