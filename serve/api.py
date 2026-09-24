"""A loopback HTTP endpoint so the tool page can drive real runs during testing.

    export COMPASS_CLAUDE_CONFIG_DIR=~/.claude-enterprise   # which seat pays
    export COMPASS_DICTIONARY=/home/mehta5/COMPASS/dictionary.json
    python -m serve.api --port 8080          # --site-dir defaults to ROOT/site

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
import re
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


class Unresolvable(ValueError):
    """A construct key that names nothing, reported so the advice survives redaction.

    THE EXPLANATION AND THE OFFENDING KEY ARE SEPARATE STRINGS, deliberately.
    `Scrubber.scrub` replaces a WHOLE string whenever it carries a key -- editing
    inside a sentence would leave something that still reads as a citation -- so
    a message with the key interpolated into it is redacted in full, and a
    reviewer who typed a lower-case letter is answered with
    `{"error": "[REDACTED: instrument wording]"}` and no way to find out why.
    Split, the key is redacted on its own and the sentence saying what to do
    arrives intact. Under `--show-instrument` both come through.

    The advice therefore may not name a key either, not even an illustrative
    one: a literal example in the message redacts the message just as thoroughly
    as the caller's own input does.

    Attributes:
        role: `exposure` or `outcome`, which is what identifies the offending
            input to a caller who typed both. It is not key-shaped, so it
            survives the scrubber.
        typed: The key as the caller typed it, echoed in its own field.
    """

    def __init__(self, role: str, key: str) -> None:
        """Build the split refusal.

        Args:
            role: `exposure` or `outcome`.
            key: The construct key as the caller typed it.
        """
        self.role = role
        self.typed = key
        super().__init__(
            f"the {role} key does not resolve to any construct in this "
            f"dictionary. Keys are case-sensitive. The shape is a module id, a "
            f"colon, an optional roster prefix, a capital Q, and a question id. "
            f"Nothing was spent: this is checked before the model runs. Pass "
            f'"allow_unresolvable": true to drive the refusal path deliberately.')

#: What KIND of run a ticket names. `--enable-specify` governs one route, but
#: the gate used to match the path prefix `/api/specify`, which caught the
#: shared status route and therefore both proposal routes' tickets as well. A
#: proposal is a different thing from a run: `/api/pair` and `/api/resolve` cost
#: about $0.012 against `/api/specify`'s $0.118, they commit nothing -- every
#: reply carries `not_a_selection` -- and they do not touch the Specifier. So
#: the ticket carries its own kind and the gate reads that instead of the path.
JOB_PAIR = "pair"
JOB_RESOLVE = "resolve"
JOB_SPECIFY = "specify"

#: Kinds a caller may poll while `--enable-specify` is off. Stated as an
#: allowlist, not as "everything but specify": a kind added later is refused
#: until someone decides it is cheap, which is the direction a spending gate
#: should fail in.
POLLABLE_WHILE_DISABLED = frozenset({JOB_PAIR, JOB_RESOLVE})

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

#: The shape `benchmark/rediscovery.py::boundary` prints. Restated rather than
#: imported, because importing that module here would put the design-key reader
#: in this process -- and this process runs in the clone where prompts are
#: edited. `tests/test_serve_compare.py` pins the two strings equal.
COMPARE_SCHEMA = "compass/rediscovery-boundary/1"

#: The four states a compared field may be in, and the only ones forwarded.
COMPARE_STATES = frozenset({"MATCH", "DIFFERS", "REVIEW", "UNAVAILABLE"})

#: The only per-field keys forwarded from the scoring clone, and the only
#: top-level ones. An ALLOWLIST, in the shape of `pseudonymise_hit`: a key the
#: scoring clone adds later -- the paper's recorded value above all -- is
#: dropped here until someone decides it may cross.
COMPARE_FIELD_KEYS = ("field", "state", "why")
COMPARE_TOP_KEYS = ("pmid", "design_key_readable", "same_build",
                    "record_dictionary_version", "dictionary_version",
                    "complaint_count")

#: Seconds one comparison may run. The scoring clone imports the schema and
#: loads its dictionary; a clone that hangs must not pin a request thread.
COMPARE_TIMEOUT_S = 60

#: Where the scoring clone keeps its record of page comparisons, relative to
#: that clone. Written there, never here: the states it holds say what the
#: answer key contains.
COMPARE_LEDGER = Path("run") / "compare_ledger.jsonl"


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
                 enable_specify: bool = False,
                 allowed_models: frozenset[str] | None = None,
                 enable_compare: bool = False,
                 scoring_clone: Path | None = None,
                 scoring_python: str | None = None) -> None:
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
                THE DEFAULT WAS `True` while this line already said "off",
                which is the unenforced-guarantee shape `AGENTS.md` names as
                this codebase's recurring defect. `main` has always passed it
                explicitly, so no deployed endpoint was affected -- but every
                other constructor got the expensive route enabled, and a test
                asserting the 403 found a live Specifier run starting instead
                (2026-09-15). A flag that spends a seat defaults to off.
            allowed_models: Models a REQUEST may name. Defaults to the pipeline
                proxy alone; the operator widens it, never the caller.
            enable_compare: Allow `POST /api/compare`. Off by default for the
                reason `enable_specify` is: the route consults the answer key,
                and a route that does that is not something to infer.
            scoring_clone: The clone that holds `benchmark/design_key.py`. The
                comparison runs THERE, as a subprocess, so the key is never
                imported into this process or this clone.
            scoring_python: The interpreter to run it with, defaulting to this
                process's own.
        """
        self.deploy_root = deploy_root
        self.site_dir = site_dir
        self.run_dir = run_dir
        self.show_instrument = show_instrument
        self.auth = auth
        self.enable_specify = enable_specify
        self.allowed_models = frozenset(allowed_models or DEFAULT_MODELS)
        self.enable_compare = enable_compare
        self.scoring_clone = scoring_clone
        self.scoring_python = scoring_python or sys.executable
        # One comparison at a time: each is a process in another clone, and the
        # rate limit alone would allow sixty of them at once.
        self.compare_lock = threading.Lock()
        # Counted so the page can say how often this session has looked. Held in
        # memory only; the durable record is the scoring clone's ledger.
        self.compare_count = 0
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
                from retriever import CompassRetriever  # type: ignore[import-not-found]

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
    from template import covered  # type: ignore[import-not-found]
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


def _member_index(constructs: dict[str, Any]) -> dict[str, str]:
    """Map every sub-item key to the construct that owns it.

    Derived from `Construct.member_keys`, which is already the grouping
    `load_constructs` built out of the entries' `construct_key` column -- so
    this is a reshape of the dictionary the caller already loaded, not a second
    source that could disagree with it.

    MEASURED 2026-09-15 on `3dc8415eccfe`: 2,804 sub-item keys over 1,080
    constructs, ZERO owned by two constructs and ZERO that are a DIFFERENT
    construct's key, so the map is a lookup and never a judgement.
    `tests/test_serve_redaction.py::test_the_sub_item_index_is_unambiguous_on_this_instrument`
    turns red if that stops being true.

    Args:
        constructs: Construct keys to Construct, from `load_constructs`.

    Returns:
        Sub-item key to construct key.
    """
    # `c.member_keys`, not a `getattr` fallback: a value without the attribute
    # would yield an EMPTY index, which refuses every sub-item key again and
    # silently, with nothing going red. Failing loudly on the wrong type is the
    # only version of this that stays enforced.
    return {m: ck for ck, c in constructs.items() for m in c.member_keys}


def _split_rewrites(canonical: dict[str, str]) -> tuple[dict[str, str],
                                                        dict[str, str]]:
    """Separate a case fix from a change of GRAIN, for reporting.

    Both are rewrites of the caller's input and both travel in one dict, but
    they are not the same claim. A case fix resolves to the construct the
    caller already named. A sub-item translation replaces one battery member
    with the whole battery, which the Specifier may then derive within -- a
    different request, at a coarser grain. Reporting that under
    `key_case_corrected` would state something false beside a changed value,
    which is the shape `PINNED_REASON` was corrected for.

    Args:
        canonical: `{typed: resolved}` as `_canonical_key` recorded it.

    Returns:
        The case fixes and the grain changes, in that order.
    """
    case = {k: v for k, v in canonical.items() if k.casefold() == v.casefold()}
    grain = {k: v for k, v in canonical.items() if k.casefold() != v.casefold()}
    return case, grain


def _canonical_key(key: str, constructs: dict[str, Any], role: str,
                   canonical: dict[str, str], members: dict[str, str]) -> str:
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
        canonical: Mutated with `{typed: resolved}` when a rewrite was applied,
            so the response can report it rather than silently rewriting input.
        members: Sub-item key to construct key, from `_member_index`. Required
            rather than defaulted: a call site that omitted it would refuse
            every sub-item key again, silently and with no test going red.

    Returns:
        The key as the dictionary spells it.

    Raises:
        Unresolvable: When the key resolves to no construct. It subclasses
            `ValueError`, so the 400 branch that caught the old one catches it.

    Note:
        A SUB-ITEM KEY IS ACCEPTED AND TRANSLATED TO ITS CONSTRUCT. `/api/pair`
        proposes whatever the retriever offered, and that is the sub-item `key`
        field: MEASURED 2026-09-15, 407 of the 1,353 offerable keys are
        sub-item keys, so a third of every proposal -- and the whole `derive`
        path, the site's own demo request included -- was refused here with a
        400 and the caller had to substitute the construct by hand. The mapping
        needs no inference, since `deploy/retriever.py::_hit` already returns
        `construct_key` beside `key`. The translation is REPORTED, and reported
        apart from a case fix, because it changes the request's grain:
        `_split_rewrites`.
    """
    if key in constructs:
        return key
    # Construct keys first, at both exactnesses, so a string that is a
    # construct key can never be read as some other construct's member. The
    # measurement in `_member_index` says no such string exists today; the
    # ordering means this stays correct rather than lucky if one appears.
    folded = {k.casefold(): k for k in constructs}
    fixed = folded.get(key.casefold())
    if fixed is None:
        owner = members.get(key)
        if owner is None:
            folded_members = {k.casefold(): v for k, v in members.items()}
            owner = folded_members.get(key.casefold())
        fixed = owner
    if fixed is not None:
        canonical[key] = fixed
        return fixed
    raise Unresolvable(role, key)


#: What a pinned anchor tells the human who confirms it. The KEY was named, so
#: it was not inferred; the ROLE was, from position alone. This used to read
#: "the request named this key, so it was not inferred" beside an outcome
#: labelled exposure, which asks the confirmation step to trust a false claim.
PINNED_REASON = ("the request named this key, so the key was not inferred. Its "
                 "role was assigned by position -- the first key named is the "
                 "exposure, the second the outcome -- not read from the "
                 "sentence. Check the direction before confirming.")


def _absence_scope(verdict: str, shown: int) -> str | None:
    """What an `absent` verdict can claim on a route that showed `shown` items.

    C29a. The model saw the top `shown` candidates, never the instrument, so
    `absent` here means the POOL missed; it is not a finding that the cohort
    lacks the construct. C29 measured the pool missing constructs a request
    names (`out/pool_coverage.json`), so reading `absent` the other way would
    tell a researcher the cohort does not measure X when it does.

    Args:
        verdict: The model's verdict.
        shown: How many candidates it was offered.

    Returns:
        The scope sentence for `absent`, else None.
    """
    if verdict != "absent":
        return None
    return (f"none of the {shown} candidates shown measures this. Nothing searched "
            f"the rest of the instrument, so this is not a finding that the "
            f"cohort lacks it: ask again in other words, or with a larger k.")


def _pin_keys_from_prose(request: str, constructs: dict[str, Any]) -> dict[str, str]:
    """Keys the caller wrote into the request, given roles BY POSITION.

    A key in the prose is not something to infer: `m3:Q4.2 and m2:Q5.8` has
    already said which constructs, so they are honoured directly, with no
    retrieval and no model call. Which ROLE each fills is not read from the
    sentence. The first key named becomes the exposure and the second the
    outcome, whatever the grammar says: "is `m3:Q4.2` predicted by `m2:Q5.8`"
    names the outcome first and pins it as the exposure. Reading direction from
    grammar would be a heuristic nothing checks, so the rule is stated instead,
    here and in `PINNED_REASON`, which every pinned anchor carries to the human
    who confirms it.

    More than two keys is refused, not truncated. A third key used to be dropped
    without a word, and the route then answered a request the caller never made.

    Args:
        request: The researcher's prose.
        constructs: Construct keys to Construct, for validation.

    Returns:
        `{role: key}` for whichever roles the prose pinned, by position.

    Raises:
        ValueError: When the prose names more than two distinct keys.
    """
    seen: list[str] = []
    for raw in KEY_RE.findall(request):
        fixed = raw if raw in constructs else None
        if fixed is None:
            folded = {k.casefold(): k for k in constructs}
            fixed = folded.get(raw.casefold())
        if fixed and fixed not in seen:
            seen.append(fixed)
    if len(seen) > 2:
        raise ValueError(
            f"the request names {len(seen)} distinct keys and this route pins at "
            f"most two, by position: the first is the exposure, the second the "
            f"outcome. Name two, or send exposure and outcome to /api/specify.")
    return dict(zip(("exposure", "outcome"), seen, strict=False))


def _role_candidates(state: State, request: str, role: str, k: int) -> dict[str, Any]:
    """The pool offered for one role, and the surface that will be asked about it.

    `role` DOES NOT REACH THE ENCODER. It is passed to `RetrievalRequest` and
    `deploy/template.py::to_query` never renders it — the template's own module
    docstring says so outright — so the query built here is a pure function of
    `request`, and the pool is byte-identical whichever role is named. What is
    framed by role is the ASK, not the retrieval: `_pair` puts
    "Which item serves as the EXPOSURE here?" on the prompt built from this
    pool. That framing is the only project-authored text this route adds to a
    model-visible surface.

    The corrected wording matters because the previous one claimed the retrieval
    was role-aware, which made `_pair`'s one shared pool look like an
    optimisation rather than the only thing this function can produce.
    `role` is still a live field on `RetrievalRequest`; if a future `to_query`
    renders it, `_pair`'s single pool — built with `role="exposure"` — becomes
    exposure-biased while still being served as the outcome pool.
    `tests/test_serve_redaction.py::test_the_role_never_reaches_the_encoder`
    turns red first.

    Args:
        state: Shared handles.
        request: The researcher's prose.
        role: `exposure` or `outcome`.
        k: Pool size.

    Returns:
        `{"cands": [...], "cos": {key: cosine}, "skipped": [...],
        "rendered": str}` -- the pool, its scores, the keys no wording could be
        bound to, and the query the encoder actually saw.

        NO `surface`. One was returned for as long as this function existed and
        nothing ever read it: `_pair` builds its own, and it has to, because a
        surface built here carries the framing for the role this call names
        while `_pair` offers the ONE pool to both roles. Reusing it would ask
        "which item serves as the EXPOSURE here?" and record the answer as the
        outcome. It was dead weight that read like an optimisation someone had
        forgotten to take, so it is gone rather than commented.

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
    rendered = req.to_query()
    hits = r.search(rendered, k=k)

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
    return {"cands": cands, "cos": cos_by_key, "skipped": skipped,
            "rendered": rendered, "min_cos": r.min_cos}


#: Where a scored baseline run is read from. Scoring happens in the clone that
#: holds the prevalence key, on a tag; this endpoint reads the RESULT, never the
#: key, and cannot score. Overridable so the path is not a fact about one box.
SCORED_RUNS = Path(os.environ.get("COMPASS_SCORED_RUNS",
                                  "/home/mehta5/compass-score/artefacts"))

#: A run id is a directory name under `SCORED_RUNS`, so it must not traverse.
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _metrics_wording(key: str) -> str | None:
    """Bind `key` to its question wording, or None when it cannot be bound.

    A scored artefact stores `quoted_wording` as a sha256, so that a run can
    travel without carrying instrument text. Wording therefore has to be
    re-bound from the dictionary on the serving machine, and only
    `env/labels.py::cite` may bind one -- it raises rather than citing empty, so
    an unbindable key becomes None here and is never filled in with a guess.

    Args:
        key: A variable key.

    Returns:
        The question wording, or None when no citation can be bound.
    """
    from env import labels

    try:
        return labels.cite(key).wording
    except labels.CitationUnavailable:
        return None


def _metrics(state: State, body: dict[str, Any]) -> dict[str, Any]:
    """Serve the exposure and outcome behind each scored artefact.

    Keyed by `record_hash`, which is what the public artefact carries, so the
    page can join the two without ever having held a key itself.

    Args:
        state: Shared handles.
        body: Optionally `run`, the run id to read.

    Returns:
        `pairs`, a record hash to key-and-wording map, with the run's identity.

    Raises:
        ValueError: When the run id is malformed or the run is not on this box.
    """
    run = str(body.get("run") or "b3-20260904").strip()
    if not RUN_ID_RE.fullmatch(run):
        raise ValueError(f"{run!r} is not a run id")
    run_dir = SCORED_RUNS / run
    ledger = run_dir / "ledger.jsonl"
    if not ledger.is_file():
        raise ValueError(
            f"no scored run {run!r} on this machine. Scoring runs in the clone "
            f"that holds the prevalence key, on a tag, and this endpoint reads "
            f"the result rather than producing it. Set COMPASS_SCORED_RUNS if "
            f"that clone is elsewhere.")

    if not state.show_instrument:
        return {"run": run, "pairs": None,
                "why": ("the keys and their wording are instrument content, and "
                        "this endpoint was not started with --show-instrument")}

    # The scored set is the ledger's `emitted` rows. More artefact files than
    # that sit in the directory -- a discarded pair can still have written one --
    # so globbing would inflate the denominator.
    emitted: dict[str, dict[str, Any]] = {}
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("outcome") == "emitted":
            emitted[r["record_hash"]] = r

    pairs: dict[str, dict[str, Any]] = {}
    for f in sorted(run_dir.glob("*.json")):
        if f.name == "summary.json":
            continue
        try:
            a = json.loads(f.read_text(encoding="utf-8"))["artefact"]
        except (KeyError, ValueError):
            continue
        if a.get("record_hash") not in emitted:
            continue
        pr = a["protocol"]
        pairs[a["record_hash"]] = {
            "exposure": pr["exposure"]["key"],
            "outcome": pr["outcome"]["key"],
            "exposure_wording": _metrics_wording(pr["exposure"]["key"]),
            "outcome_wording": _metrics_wording(pr["outcome"]["key"]),
            "exposure_wording_hash": pr["exposure"]["quoted_wording"],
            "outcome_wording_hash": pr["outcome"]["quoted_wording"],
            "question": pr["question"],
            "direction": pr["expected_direction"]["direction"],
            "estimability": a["estimability"],
        }
    return {
        "run": run, "pairs": pairs, "scored": len(emitted), "served": len(pairs),
        "wording_note": ("the run stores each wording as a sha256, so that an "
                         "artefact can travel without carrying instrument text. "
                         "The wording here is re-bound from the dictionary on "
                         "this machine; the stored hash is beside it."),
        "note": ("read from a run scored in the clone that holds the prevalence "
                 "key. This endpoint cannot score: the key is not here, and "
                 "scoring runs once, on a tag, before any tuning."),
    }


def _spread_by_exposure(cands: list[Any], limit: int) -> list[Any]:
    """Take `limit` candidates spread across exposures, not the head of the list.

    `generate/funnel.py::s1_enumerate` is an exposure-major `product()`, so the
    first N candidates are all one exposure until N passes the outcome count.
    On the shipped frame that is 64, and the page asks for 25 -- so every pair a
    reader could ever see on the Generate tab was `m3:Q16.1 -> ...`, and the
    panel's honest "showing 25 of 384" read as a sample of the 384 rather than
    as the first 39% of one exposure. Round-robin here and the same 25 span
    every exposure the frame has.

    Display only. Enumeration order is the frame's and is left alone: it decides
    every reported denominator (`generate/funnel.py::Frame`, T7) and `counts` is
    computed over the whole list before this runs, so nothing here moves a
    number. Pruned candidates are kept rather than filtered -- the count says
    384 and the reader should be able to see what the other 128 are -- which is
    why `pairs` carries `state` and the page refuses them a launch button.

    Args:
        cands: Every candidate the funnel produced, in enumeration order.
        limit: How many to return.

    Returns:
        At most `limit` candidates, taking one per exposure per pass in the
        order the exposures first appear.
    """
    lanes: dict[str, list[Any]] = {}
    for c in cands:
        lanes.setdefault(c.exposure.construct_key, []).append(c)
    rows = list(lanes.values())
    if not rows:
        return []
    out: list[Any] = []
    for depth in range(max(len(r) for r in rows)):
        for row in rows:
            if depth < len(row):
                out.append(row[depth])
                if len(out) == limit:
                    return out
    return out


def _enumerate(state: State, body: dict[str, Any]) -> dict[str, Any]:
    """Run the funnel: enumerate pairs, prune, and report the gate.

    Free and deterministic -- `generate/funnel.py` makes no model call. The
    exposure and outcome sets default to the ones
    `generate/live_specifier.py::main` uses, so the enumeration here is the one
    the pipeline itself performs rather than a variant invented for a web page.

    Args:
        state: Shared handles.
        body: Optionally `exposure_module`, `exposure_prefix`,
            `outcome_module`, `outcome_prefix`, and `limit`.

    Returns:
        The candidates, the funnel's own counts, and the estimability gate.
    """
    from generate.funnel import load_constructs
    from generate.funnel import run as funnel_run

    C, version = load_constructs()
    ex_mod = str(body.get("exposure_module") or "3")
    ex_pre = str(body.get("exposure_prefix") or "Q16.")
    out_mod = str(body.get("outcome_module") or "2")
    out_pre = str(body.get("outcome_prefix") or "Q5.")
    limit = max(1, min(_int_arg(body, "limit", 25), 200))

    exposures = sorted([c for c in C.values()
                        if c.module == ex_mod and c.base_id.startswith(ex_pre)],
                       key=lambda c: c.base_id)
    outcomes = sorted([c for c in C.values()
                       if c.module == out_mod and c.base_id.startswith(out_pre)],
                      key=lambda c: c.base_id)
    if not exposures or not outcomes:
        raise ValueError(
            f"nothing to enumerate: {len(exposures)} exposure(s) matching "
            f"module {ex_mod} {ex_pre!r} and {len(outcomes)} outcome(s) matching "
            f"module {out_mod} {out_pre!r}")

    cands, counts = funnel_run(exposures, outcomes)
    shown = _spread_by_exposure(cands, limit)
    return {
        "dictionary_version": version,
        "sets": {"exposures": len(exposures), "outcomes": len(outcomes),
                 "exposure_module": ex_mod, "exposure_prefix": ex_pre,
                 "outcome_module": out_mod, "outcome_prefix": out_pre},
        "counts": counts,
        "pairs": [
            {"pair_id": c.pair_id,
             "exposure": c.exposure.construct_key if state.show_instrument else None,
             "outcome": c.outcome.construct_key if state.show_instrument else None,
             "exposure_stem": c.exposure.stem_text,
             "outcome_stem": c.outcome.stem_text,
             # A pruned pair used to be indistinguishable from a live one here,
             # and the page gave every row a launch button. Invisible while the
             # slice was the head of the list -- the prunes sit at index 256 --
             # and reachable the moment the slice spreads.
             "state": c.state,
             "stage": c.stage,
             "reason": c.reason}
            for c in shown],
        "shown": len(shown),
        "note": ("The funnel enumerates and prunes with no model call. A pair "
                 "run from here carries `enumerated_screen` and a real "
                 "denominator, unlike a pair you type, which carries "
                 "`externally_posed` and zero. Every run this endpoint makes is "
                 "stamped `produced_by: serve-endpoint` either way."),
    }


def _union_pools(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge per-phrase pools into one, interleaved by rank, each key once.

    Round-robin by rank so no phrase's candidates are buried under another's:
    the first-ranked item of every phrase comes before any second-ranked one.

    Args:
        parts: Pools as `_role_candidates` returns them.

    Returns:
        One pool in the same shape, re-indexed 1..n.
    """
    from agent import prompt_contract as PC

    keys: list[str] = []
    facts: dict[str, dict[str, Any]] = {}
    cos: dict[str, float] = {}
    for rank in range(max(len(p["cands"]) for p in parts)):
        for p in parts:
            if rank < len(p["cands"]) and p["cands"][rank].key not in cos:
                c = p["cands"][rank]
                keys.append(c.key)
                facts[c.key] = dict(c.facts)
                cos[c.key] = p["cos"][c.key]
    skipped: list[str] = []
    for p in parts:
        skipped += [s for s in p["skipped"] if s not in skipped]
    return {"cands": PC.candidates_from_keys(keys, facts), "cos": cos,
            "min_cos": next((p["min_cos"] for p in parts if p.get("min_cos")), None),
            "skipped": skipped,
            "rendered": " | ".join(p["rendered"] for p in parts)}


def _split_pools(state: State, backend: Any, request: str, k: int,
                 fallback: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """C29-C: split the request, then give each role the pool its phrases build.

    One shared pool carries every construct a request names in only 32 of 100
    composed requests (`out/pool_coverage.json`). Here a model names the
    exposures and outcomes first, `agent/prompt_contract.py::parse_split`
    refuses any entry that is not the request's own words, and each phrase is
    retrieved alone at an equal share of `k` -- the same total budget.

    ANY SPLIT THAT CANNOT BE USED FALLS BACK TO THE SHARED POOL, and says why.
    A refused or unsplittable reply, or a role whose phrases cite nothing,
    leaves the route exactly as it was without `split`.

    Args:
        state: Shared handles.
        backend: The model backend, already holding the lock.
        request: The researcher's prose.
        k: The route's total pool budget.
        fallback: The shared pool for every role left unpinned.

    Returns:
        `(pools by role, what the split did)`.
    """
    from agent import prompt_contract as PC

    note: dict[str, Any] = {"splitter_model": backend.name}
    try:
        split = PC.parse_split(
            request, str(backend.transduce(PC.split_prompt(request)).content))
    except ValueError as exc:
        return fallback, {**note, "status": "fallback", "why": str(exc)[:300]}
    if split.unsplittable:
        return fallback, {**note, "status": "fallback",
                          "why": "the splitter found no exposure and outcome"}
    phrases = {"exposure": split.exposures, "outcome": split.outcomes}
    each = max(1, k // (len(split.exposures) + len(split.outcomes)))
    pools: dict[str, Any] = {}
    for role in fallback:
        parts = []
        for phrase in phrases[role]:
            try:
                parts.append(_role_candidates(state, phrase, role, each))
            except ValueError:
                continue
        if not parts:
            return fallback, {**note, "status": "fallback",
                              "why": f"no {role} phrase built a citable pool"}
        pools[role] = _union_pools(parts)
    return pools, {**note, "status": "used", "exposures": list(split.exposures),
                   "outcomes": list(split.outcomes), "per_phrase_k": each}


def _abstention_note(pool: dict[str, Any]) -> dict[str, Any]:
    """Whether the deployed retriever would have abstained on this pool.

    `/api/retrieve` calls `select`, which refuses below the manifest's
    threshold and reports `abstained`. `/api/pair` calls `search`, which does
    not -- so a construct the retriever would REFUSE is offered to the model as
    a candidate. MEASURED 2026-09-16 on the split phrase "discriminated
    against": top cosine 0.699991 against a threshold of 0.729476, and the
    model answered `resolved`, for a construct whose distinctive words occur
    zero times in the build.

    Reported, never enforced. Refusing here would change what the model is
    asked, and the threshold was derived for single-construct queries rather
    than for a split phrase at a share of `k`, so tightening it into a refusal
    needs its own measurement.

    Args:
        pool: A pool as `_role_candidates` or `_union_pools` returns it. A
            stubbed pool carries no `min_cos`, and then no verdict is claimed --
            absence of a threshold is not evidence the pool cleared one.

    Returns:
        `top_cos`, `min_cos` and `below_threshold`.
    """
    cos = pool.get("cos") or {}
    top = max(cos.values()) if cos else None
    thr = pool.get("min_cos")
    return {"top_cos": top, "min_cos": thr,
            "below_threshold": bool(top is not None and thr and top < thr)}


def _pair(state: State, body: dict[str, Any]) -> dict[str, Any]:
    """Propose BOTH anchors from one piece of prose. The human confirms.

    Args:
        state: Shared handles.
        body: The request, carrying `request` prose and optionally `k`, `model`,
            and `split` to have a model separate the request into its
            exposures and outcomes before anything is retrieved (C29-C).

    Returns:
        A ticket; the run is two model calls, three with `split`.

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
    # C29-C, opt-in until it is measured on a clean fixture. The split is a
    # model call, so it runs inside the job after the lock, and it falls back to
    # the shared pool above whenever the split cannot be used.
    split_on = bool(body.get("split")) and len(pinned) < 2

    if not state.model_lock.acquire(blocking=False):
        raise Busy("a model run is already in progress on this endpoint.")
    ticket = f"{time.strftime('%H%M%S')}-{os.urandom(3).hex()}"
    _start_job(state, ticket, JOB_PAIR)

    def _run() -> None:
        try:
            from agent import prompt_contract as PC
            from agent.cli_backend import ClaudeCliBackend
            from env import labels

            backend = ClaudeCliBackend(model=model, mode="benchmark")
            t0 = time.time()
            out: dict[str, Any] = {}
            pools: dict[str, Any] = dict(roles)
            split_info: dict[str, Any] = {"status": "off"}
            if split_on:
                pools, split_info = _split_pools(state, backend, request, k,
                                                 pools)
            for role in ("exposure", "outcome"):
                if role in pinned:
                    key = pinned[role]
                    out[role] = {
                        "verdict": "pinned",
                        "reason": PINNED_REASON,
                        "proposed_indices": [],
                        "pinned_key": key if state.show_instrument else None,
                        "pinned_wording": labels.cite(key).wording,
                        "candidates": [],
                    }
                    continue
                pool = pools[role]
                # `shared` is None only when both roles are pinned, and then
                # `roles` is empty, so no loop pass reaches here without a pool.
                assert pool is not None
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
                    "absent_scope": _absence_scope(chosen.verdict,
                                                   len(pool["cands"])),
                    "reason": chosen.reason,
                    "recipe": chosen.recipe or None,
                    "missing_dimension": chosen.missing_dimension or None,
                    "proposed_indices": proposed,
                    "skipped_uncitable": pool["skipped"],
                    **_abstention_note(pool),
                    # THE ABSTENTION VERDICT, REPORTED ON THIS PATH TOO.
                    # `/api/retrieve` calls `select`, which refuses below the
                    # manifest's threshold and says `abstained`. This route
                    # calls `search`, which does not -- so a construct the
                    # deployed retriever would REFUSE was handed to the model
                    # as a candidate and resolved. MEASURED 2026-09-16 on
                    # "discriminated against": top cosine 0.7000 against a
                    # threshold of 0.729476, and the model answered `resolved`
                    # -- for a construct whose distinctive words occur ZERO
                    # times in the build, which `scorability.py`'s docstring
                    # already names as the word test's worst false survivor.
                    #
                    # REPORTED, NOT ENFORCED. Refusing here would change what
                    # the model is asked, and the threshold was derived for
                    # single-construct queries, not for a split phrase at a
                    # share of k. So the number and the verdict travel with the
                    # pool and the reader sees them; tightening it into a
                    # refusal needs its own measurement.
                    "candidates": [
                        {"index": c.index,
                         "key": c.key if state.show_instrument else None,
                         "wording": c.wording,
                         "proposed": c.index in proposed,
                         "cos": pool["cos"][c.key],
                         **c.facts}
                        for c in pool["cands"]],
                }
            rendered = shared["rendered"] if shared else request
            done = {"status": "done", "run": {
                "request": request,
                # The same Intake fields `/api/retrieve` returns, so the Intake
                # panel explains a pair resolve too. Without these it rendered
                # its placeholder after an "Ask the model" run -- the panel that
                # says what the encoder saw, blank on the route that most needs
                # explaining, because the pool query never came back.
                "rendered_query": rendered,
                "pool_request": {"construct": request, "role": "exposure",
                                 "instances": [], "population": None},
                "dictionary_version": version,
                "model_id": backend.name,
                "elapsed_s": round(time.time() - t0, 2),
                "cost_usd": backend.last_cost,
                "roles": out,
                "split": split_info,
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
        _finish_job(state, ticket, done, JOB_PAIR)

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
    _start_job(state, ticket, JOB_RESOLVE)

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
                "absent_scope": _absence_scope(chosen.verdict, len(cands)),
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
        _finish_job(state, ticket, done, JOB_RESOLVE)

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


#: What a model id may look like when a caller reports one.
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}")


def _resolver_model(body: dict[str, Any]) -> str | None:
    """The model that proposed the anchors, when the caller says one did.

    C17: a pair `/api/pair` proposed reaches `/api/specify` as two keys, and
    without this the record would name the Specifier alone. The value lands in
    the record's provenance, never in a prompt; it is still held to the shape of
    a model id so a caller cannot write arbitrary text into a record.

    Args:
        body: The request.

    Returns:
        The model id, or None when the caller named none.

    Raises:
        ValueError: When the field is present but is not a model id.
    """
    raw = body.get("resolver_model")
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or not _MODEL_ID.fullmatch(raw):
        raise ValueError("resolver_model must be a model id such as "
                         "claude-haiku-4-5")
    return raw


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
            key the dictionary does not contain. `resolver_model` names the
            model that proposed the anchors when they came from `/api/pair`,
            so the record names it too (C17).

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
    resolver_model = _resolver_model(body)
    canonical: dict[str, str] = {}
    if not allow_unresolvable:
        members = _member_index(C)
        exposure = _canonical_key(exposure, C, "exposure", canonical, members)
        outcome = _canonical_key(outcome, C, "outcome", canonical, members)
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
    _start_job(state, ticket, JOB_SPECIFY)

    def _run() -> None:
        try:
            backend = ClaudeCliBackend(model=model, mode="benchmark")
            identity = run_identity(
                pair, version, 0, backend.name, "externally_posed",
                models={"resolver": resolver_model} if resolver_model else None,
                anchors_proposed_by="model" if resolver_model else "person")
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
        _finish_job(state, ticket, done, JOB_SPECIFY)

    threading.Thread(target=_run, daemon=True).start()
    return {"ticket": ticket, "status": "running", "poll_after_ms": POLL_MS,
            "note": "A run takes minutes. Ask /api/specify/status for this "
                    "ticket; the run continues whatever happens to this page."}


def _start_job(state: State, ticket: str, kind: str) -> None:
    """Record an in-flight run, labelled with what kind of run it is.

    The label is written at BOTH ends -- here and in `_finish_job` -- because
    the done record replaces this one wholesale rather than updating it, so a
    kind set only at the start is lost the moment the run completes.

    Args:
        state: Shared handles.
        ticket: The run's ticket.
        kind: One of `JOB_PAIR`, `JOB_RESOLVE`, `JOB_SPECIFY`.
    """
    with state._jobs_lock:
        state.jobs[ticket] = {"status": "running", "started": time.time(),
                              "kind": kind}


def _finish_job(state: State, ticket: str, done: dict[str, Any],
                kind: str) -> None:
    """Store and persist a finished run, keeping its kind.

    Three routes ran these two statements themselves, and the kind had to be
    stamped on every one of them for the gate to work; a helper is used so a
    fourth route cannot land unlabelled and silently become pollable.

    Args:
        state: Shared handles.
        ticket: The run's ticket.
        done: The finished job record.
        kind: One of `JOB_PAIR`, `JOB_RESOLVE`, `JOB_SPECIFY`.
    """
    done["kind"] = kind
    with state._jobs_lock:
        state.jobs[ticket] = done
    _save_job(state, ticket, done)


def _ticket_kind(state: State, ticket: str) -> str | None:
    """What kind of run a ticket names, in memory or on disk.

    Args:
        state: Shared handles.
        ticket: The ticket as the caller sent it.

    Returns:
        The kind, `JOB_SPECIFY` for a record written before kinds existed, or
        None when this endpoint has no such run.

    Note:
        An UNLABELLED record resolves to `JOB_SPECIFY`, the refused kind.
        Finished runs outlive the process, so `_load_job` reads records from
        older builds; reading those as proposals would widen what a default
        bind serves, and a spending gate may not be weakened by a file's age.
    """
    with state._jobs_lock:
        job = state.jobs.get(ticket)
    if job is None:
        job = _load_job(state, ticket)
    if job is None:
        return None
    return str(job.get("kind") or JOB_SPECIFY)


def _job_path(state: State, ticket: str) -> Path:
    """Where a finished run is kept.

    Args:
        state: Shared handles.
        ticket: The run's ticket.

    Returns:
        The file path. Tickets are `HHMMSS-hex`, so the name is safe.
    """
    return state.run_dir / JOBS_DIR_NAME / f"{ticket}.json"


def _save_job(state: State, ticket: str, done: dict[str, Any]) -> None:
    """Keep a finished run, so a restart does not lose it.

    Args:
        state: Shared handles.
        ticket: The run's ticket.
        done: The finished job record.
    """
    try:
        path = _job_path(state, ticket)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(done, indent=1), encoding="utf-8")
    except OSError:
        # Losing the copy must not lose the answer the caller is waiting on.
        pass


def _load_job(state: State, ticket: str) -> dict[str, Any] | None:
    """A finished run kept from an earlier process, or None.

    Args:
        state: Shared handles.
        ticket: The run's ticket.

    Returns:
        The job record, or None when nothing was kept under that ticket.
    """
    if not re.fullmatch(r"\d{6}-[0-9a-f]{6}", ticket):
        return None                      # not a ticket we ever issued
    try:
        job: dict[str, Any] = json.loads(
            _job_path(state, ticket).read_text(encoding="utf-8"))
        return job
    except (OSError, ValueError):
        return None


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
        # Finished runs are on disk, so a restart loses only what was IN FLIGHT.
        # The operator lost a run to a restart under them and got a message that
        # blamed the ticket; the truthful distinction is between "this endpoint
        # never had it", "it finished and here it is", and "the process died
        # mid-run and the work is gone".
        job = _load_job(state, ticket)
    if job is None:
        raise ValueError(
            f"no run with ticket {ticket!r} on this endpoint. A run that was "
            "still going when the endpoint restarted is lost -- the model call "
            "dies with the process. Finished runs are kept on disk and would "
            "have been found. Start it again.")
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
        canonical: Any rewrites applied to the caller's keys, case fixes and
            sub-item translations together; reported as two fields.
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
    case_fixed, grain_changed = _split_rewrites(canonical)
    payload: dict[str, Any] = {
        "identity": {
            "protocol_id": identity.protocol_id,
            "prompt_hash": identity.prompt_hash,
            "model_id": identity.model_id,
            "dictionary_version": version,
            "screened_from": 0,
            "selection_mode": "externally_posed",
            # A silent rewrite of the caller's input is its own small version of
            # the substitution problem: say what was changed and to what. The
            # two rewrites are reported SEPARATELY because they are different
            # claims -- a case fix names the construct the caller meant, a
            # sub-item translation coarsens the request to the whole battery.
            "key_case_corrected": case_fixed or None,
            "key_subitem_to_construct": grain_changed or None,
            "allow_unresolvable": allow_unresolvable,
            # Stamped on EVERY run, whatever its selection mode. A posed pair
            # is kept out of a benchmark denominator by `screened_from = 0`; an
            # enumerated one carries a real denominator and nothing else would
            # distinguish a run made here from one the pipeline made.
            "produced_by": "serve-endpoint",
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


def _compare_record(state: State, ticket: str) -> str:
    """The finished protocol a ticket names, as JSON text.

    Looked up by ticket and never read from the request body: a caller that
    could send its own record could send one built to probe the key.

    Args:
        state: Shared handles.
        ticket: A Specifier run's ticket.

    Returns:
        The selected `ProtocolSpecification`, serialised.

    Raises:
        ValueError: When there is no such run, it is still going, it is not a
            Specifier run, or it ended in a refusal. Each says what to do.
    """
    with state._jobs_lock:
        job = state.jobs.get(ticket)
    if job is None:
        job = _load_job(state, ticket)
    if job is None:
        raise ValueError("no finished Specifier run with that ticket on this "
                         "endpoint; run the pair on Ask first")
    if job.get("status") == "running":
        raise ValueError("the Specifier is still running; compare once the "
                         "record has landed")
    if str(job.get("kind") or JOB_SPECIFY) != JOB_SPECIFY:
        raise ValueError("that ticket is a proposal, not a Specifier record")
    if job.get("status") != "done":
        raise ValueError("that run failed, so there is no record to compare")
    selected = (job.get("run") or {}).get("selected")
    if not selected:
        # A refusal, or a design the gate rejected. The rejected one is NOT
        # compared: the gate's verdict stands, and comparing it would treat an
        # unauthorised design as the pipeline's answer.
        raise ValueError("The Specifier refused this pair, so there is nothing "
                         "to place beside the paper.")
    return json.dumps(selected)


def _compare_failure(proc: Any) -> str:
    """Say why the scoring clone produced no comparison, without quoting it.

    Its stderr can carry key content -- a validation error echoes field values
    -- so only the exception's class name crosses, never its message.

    Args:
        proc: The finished `subprocess.CompletedProcess`.

    Returns:
        A sentence for the page.
    """
    lines = [ln.strip() for ln in (proc.stderr or "").splitlines() if ln.strip()]
    last = lines[-1] if lines else ""
    name = re.match(r"([A-Za-z_][\w.]*(?:Error|Exception|Exit))\b", last)
    what = f" ({name.group(1)})" if name else ""
    # argparse's own shape: a `usage:` line and an `error:` line, exit 2. That
    # is the stale clone, whose rediscovery does not know --json yet. Anything
    # else is the clone failing at its own work -- a missing build, an
    # unwritable run/ -- and telling that operator to update would send them
    # the wrong way.
    stale = any(ln.startswith("usage:") for ln in lines) and last.startswith("error:")
    if stale:
        return (f"the scoring clone could not run the comparison (exit "
                f"{proc.returncode}): it is on an older commit than this one. "
                f"Update it so benchmark/rediscovery.py accepts --json.")
    return (f"the scoring clone failed while comparing (exit {proc.returncode})"
            f"{what}. Run `python -m benchmark.rediscovery` there to see why; "
            f"a missing build/dictionary.json is the usual cause.")


def _compare(state: State, body: dict[str, Any]) -> dict[str, Any]:
    """Place one finished record beside one paper's recorded design.

    WHERE THE KEY IS READ. Not here. `benchmark/rediscovery.py` runs as a
    subprocess inside `state.scoring_clone`, the only clone holding
    `benchmark/design_key.py`, and what comes back is filtered to an allowlist
    of field names, states and fixed reasons. The recorded values never enter
    this process, and nothing this route receives is written to disk here: no
    job file, no log line beyond the request line `log_message` always writes.

    WHAT IT DOES NOT CLOSE. A MATCH says the paper's key equals the one the
    record used, and on an Ask record the person asking chose that key -- so a
    MATCH discloses the key to whoever is using the page. The operator accepted
    that on 2026-09-24. The ledger in the scoring clone is what keeps the
    resulting feedback loop visible to the tagged baseline.

    Args:
        state: Shared handles.
        body: The request, carrying `ticket` and `pmid`.

    Returns:
        `{compare: {...}, comparisons_this_session, not_a_score}`.

    Raises:
        ValueError: On a bad request, a missing record or a refusal.
        Busy: When another comparison is running.
        RuntimeError: When the scoring clone is missing or cannot run.
    """
    import subprocess

    ticket = str(body.get("ticket") or "").strip()
    pmid = str(body.get("pmid") or "").strip()
    if not ticket or not pmid:
        raise ValueError("ticket and pmid are both required")
    if not re.fullmatch(r"\d{1,9}", pmid):
        raise ValueError("pmid must be a PubMed identifier, digits only")
    record = _compare_record(state, ticket)

    clone = state.scoring_clone
    if clone is None or not clone.is_dir():
        raise RuntimeError("the scoring clone is not at the configured path; "
                           "restart with --scoring-clone pointing at it")
    if not (clone / "benchmark" / "rediscovery.py").is_file():
        raise RuntimeError(f"the scoring clone ({clone.name}) has no "
                           "benchmark/rediscovery.py; update it to this commit")

    if not state.compare_lock.acquire(blocking=False):
        raise Busy("another comparison is running; try again in a moment")
    try:
        # PYTHONPATH is dropped so the child imports the scoring clone's own
        # modules and not this clone's, which is where a stale checkout would
        # otherwise hide.
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        try:
            proc = subprocess.run(
                [state.scoring_python, "-m", "benchmark.rediscovery",
                 "--pmid", pmid, "--record", "-", "--json",
                 "--ledger", str(clone / COMPARE_LEDGER)],
                input=record, capture_output=True, text=True, cwd=clone,
                env=env, timeout=COMPARE_TIMEOUT_S, check=False)
        except FileNotFoundError as exc:
            raise RuntimeError("the scoring clone's interpreter was not found; "
                               "restart with --scoring-python") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"the scoring clone did not answer within "
                               f"{COMPARE_TIMEOUT_S} s") from exc
        state.compare_count += 1
        count = state.compare_count
    finally:
        state.compare_lock.release()

    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    try:
        raw = json.loads(lines[-1]) if lines else None
    except ValueError:
        raw = None
    # The schema line is the sentinel. Exit 2 means "key withheld" to
    # rediscovery and "usage error" to argparse, so the status alone would
    # show a stale clone as a withheld key.
    if not isinstance(raw, dict) or raw.get("schema") != COMPARE_SCHEMA:
        raise RuntimeError(_compare_failure(proc))
    if raw.get("error") == "unknown_pmid":
        raise ValueError(f"PMID {pmid} is not in the bibliography the scoring "
                         "clone carries")

    fields = []
    for f in raw.get("fields") or []:
        if not isinstance(f, dict) or f.get("state") not in COMPARE_STATES:
            continue
        kept = {k: str(f.get(k) or "") for k in COMPARE_FIELD_KEYS}
        # `why` is safe only while rediscovery writes fixed sentences, and the
        # scoring clone may be on another commit. Checked HERE, because
        # `_send` does not scrub at all under --show-instrument.
        if KEY_RE.search(kept["why"]):
            kept["why"] = ""
        fields.append(kept)
    out = {k: raw.get(k) for k in COMPARE_TOP_KEYS}
    out["fields"] = fields
    return {
        "compare": out,
        "comparisons_this_session": count,
        "not_a_score": ("A diagnostic of one externally posed record, never a "
                        "benchmark result. The pair was posed, so this cannot "
                        "show whether the pipeline would have found the study; "
                        "the tagged baseline is the only score."),
    }


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
                "compare_enabled": s.enable_compare,
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
            # The comparison control is shown only where the route is on, for
            # the same reason: a button that can only answer 403 is dead.
            marker = (b"<script>window.COMPASS_ENDPOINT=true;"
                      + (b"window.COMPASS_COMPARE=true;"
                         if self.state.enable_compare else b"")
                      + b"</script></head>")
            body = body.replace(b"</head>", marker, 1)
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
        # THE PREFIX MATCH WAS THE BUG. `route.startswith("/api/specify")` also
        # caught `/api/specify/status`, the one route the cheap proposal routes
        # share, so a single flag governed three routes with different costs:
        # `/api/pair` accepted a request on a default bind, spent its model
        # call, returned a ticket -- and every poll of it answered 403. It
        # failed in the shape that reads as "the server is broken" rather than
        # "this route is off" (found by running the site's own flow,
        # 2026-09-15). So the expensive route is named exactly, and the status
        # route is judged on the TICKET's kind, below, once the body is parsed.
        if route == "/api/specify" and not self.state.enable_specify:
            self._send(403, self._specify_disabled())
            return
        if route == "/api/compare" and not self.state.enable_compare:
            self._send(403, {"error": "/api/compare is disabled on this endpoint "
                                      "(start with --enable-compare and "
                                      "--scoring-clone). It consults the answer "
                                      "key, so it is off unless asked for."})
            return
        routes = {"/api/retrieve": _retrieve, "/api/specify": _specify,
                  "/api/specify/status": _specify_status,
                  "/api/resolve": _resolve,
                  "/api/pair": _pair,
                  "/api/enumerate": _enumerate,
                  "/api/metrics": _metrics,
                  "/api/compare": _compare}
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
        if route == "/api/specify/status" and not self.state.enable_specify:
            # Judged on the ticket, not the path: a proposal already ran and
            # cost what it cost, so withholding its result protects nothing and
            # loses work already paid for. A Specifier ticket is still refused,
            # and so is an unlabelled one -- `_ticket_kind` says why.
            kind = _ticket_kind(self.state, str(body.get("ticket") or "").strip())
            if kind is not None and kind not in POLLABLE_WHILE_DISABLED:
                self._send(403, self._specify_disabled())
                return
            # kind is None: this endpoint never issued the ticket. The route's
            # own 400 tells the truth ("no run with this ticket"); a 403 would
            # send the caller looking for a flag that is not their problem.
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

    def _specify_disabled(self) -> dict[str, Any]:
        """The refusal both gate branches send, worded once.

        Disabled rather than merely rate-limited: every call spends a named
        human's Claude seat with no per-caller accounting, and runs serialise,
        so one visitor holds the lock for ten minutes. That reasoning is
        unchanged by serving proposal tickets -- a proposal runs neither.

        Returns:
            The error body.
        """
        return {"error": "/api/specify is disabled on this endpoint "
                         "(start with --enable-specify). Each run "
                         "spends the operator's Claude seat and "
                         "blocks every other caller while it runs."}

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
        body: dict[str, Any] = {
            "error": f"{type(exc).__name__}: {exc}" if prefix else str(exc)}
        # Reported BESIDE the message, never inside it -- `Unresolvable`'s
        # docstring says what interpolating the key costs. Redacting `typed`
        # alone is the right outcome, not a failure of this path.
        if isinstance(exc, Unresolvable):
            body["role"] = exc.role
            body["typed"] = exc.typed
        return body


#: Names that mark a directory as holding withheld material rather than the
#: published page. `README.md` §What is withheld is the source of the list.
WITHHELD_MARKERS = ("dictionary.json", "build", "targets.json", "raw",
                    "prevalence_key.py", "cohort_papers.py")

#: The pseudonym map's filename. Named once and used by the writer, so the
#: refusal below and `main` cannot drift apart.
PSEUDONYM_MAP_NAME = "pseudonyms.json"

#: Where finished runs are kept, relative to `run_dir`. Same reason.
JOBS_DIR_NAME = "jobs"

#: What THIS ENDPOINT writes. A separate tuple from `WITHHELD_MARKERS` because
#: the source of truth is different: that list comes from `README.md`, this one
#: from the two writers in this module -- `Pseudonymiser.dump` and `_save_job`.
#: Both are as withholdable as the instrument and neither was listed:
#: `pseudonyms.json` carries the SALT and the label map, which together un-do
#: the pseudonymiser, and `jobs/<ticket>.json` is the job record as the route
#: built it -- `_send` scrubs on the wire, `_save_job` writes before that, so
#: the file holds `Cited.wording` verbatim.
#:
#: The run-dir clause at the end of `_refuse_unsafe_site_dir` compares the
#: CURRENT `run_dir` only. A run directory from an earlier session sitting
#: inside `site_dir` cleared it, and the static route has no content filter:
#: MEASURED 2026-09-15, `GET /old-run/pseudonyms.json` and
#: `GET /old-run/jobs/<ticket>.json` both returned 200 with the salt and
#: unscrubbed wording. Walking for these names is what closes that, and it is
#: the same walk, so it closes it at every depth.
OWN_OUTPUT_MARKERS = (PSEUDONYM_MAP_NAME, JOBS_DIR_NAME)

#: Directories `_refuse_unsafe_site_dir` will visit before it gives up and
#: refuses. A published page directory is tens of entries; needing thousands to
#: describe one is itself the signal that this is a source tree, so the cap is a
#: second check rather than only a budget.
MAX_SITE_DIR_WALK = 2000


def _refuse_unsafe_site_dir(site_dir: Path, run_dir: Path) -> str | None:
    """Refuse a `--site-dir` whose contents the static route must not publish.

    The containment check on the static route is correct: it keeps a request
    inside `site_dir`. It says nothing about what `site_dir` IS. Handed the
    repository root it happily serves `build/dictionary.json` -- every
    `question_text` in the instrument -- and, if the run directory sits inside
    it, `pseudonyms.json`, which un-does the pseudonymiser completely. The
    filter guards what this process COMPUTES; nothing guarded what it was
    pointed at.

    Two marker sets, because they have two sources of truth: `WITHHELD_MARKERS`
    is `README.md`'s list, `OWN_OUTPUT_MARKERS` is this module's own writers.
    The second closes the STALE run directory -- the `run_dir` comparison below
    sees only the run this process was given, so a run directory from an
    earlier session inside `site_dir` was served (MEASURED 2026-09-15, 200 on
    both shapes). The comparison is kept as well: it refuses a run directory
    that has not written anything yet, which no marker can see.

    Args:
        site_dir: The resolved directory to be served at `/`.
        run_dir: The resolved private output directory.

    Returns:
        The refusal message, or None when the directory is safe to serve.
    """
    # DEPTH ONE WAS NOT ENOUGH. The old check tested `site_dir / marker` and
    # nothing deeper, so a parent directory passed while the withheld material
    # sat one level further down -- `--site-dir ~` with a clone inside it leaves
    # `<clone>/build/dictionary.json` INSIDE site_dir, which is precisely what
    # the static route's containment check certifies and then serves. Measured
    # 2026-09-09: a tree holding `pages/deep/build/dictionary.json` was cleared.
    #
    # So walk it, and FAIL CLOSED. A tree too large to certify is refused rather
    # than served: not finding a marker in the part we managed to look at is not
    # the same as there being none, and this is the check that decides whether
    # the instrument is downloadable.
    seen = 0
    for parent, dirnames, filenames in os.walk(site_dir):
        seen += 1
        if seen > MAX_SITE_DIR_WALK:
            return (f"refusing to serve {site_dir}: it holds more than "
                    f"{MAX_SITE_DIR_WALK} directories, so this check cannot "
                    f"certify that nothing withheld is inside it. A published "
                    f"page directory is far smaller -- point --site-dir at one, "
                    f"not at a source tree or a home directory.")
        for marker in WITHHELD_MARKERS:
            # Symlinks are not followed by `os.walk`, but a symlink NAMED for a
            # marker still appears here and is still served through it.
            if marker in dirnames or marker in filenames:
                where = Path(parent, marker).relative_to(site_dir)
                return (f"refusing to serve {site_dir}: it contains {str(where)!r}, "
                        f"which is withheld (README.md §What is withheld). The "
                        f"static route has no content filter -- point --site-dir "
                        f"at the published page directory, not at a source tree.")
        for marker in OWN_OUTPUT_MARKERS:
            if marker in dirnames or marker in filenames:
                where = Path(parent, marker).relative_to(site_dir)
                return (f"refusing to serve {site_dir}: it contains {str(where)!r}, "
                        f"which THIS ENDPOINT writes -- a run directory, this "
                        f"one's or an earlier session's. {PSEUDONYM_MAP_NAME} "
                        f"carries the salt and the label map, and "
                        f"{JOBS_DIR_NAME}/ holds job records written before "
                        f"anything scrubbed them. Point --run-dir outside "
                        f"--site-dir and move what is already there.")
    if run_dir == site_dir or run_dir.is_relative_to(site_dir):
        return (f"refusing to serve {site_dir}: the run directory {run_dir} is "
                f"inside it, so pseudonyms.json would be downloadable and the "
                f"pseudonymiser would be pointless.")
    return None


def _refuse_scoring_clone(scoring: Path | None) -> str | None:
    """Refuse a `--scoring-clone` that would defeat the point of having one.

    Args:
        scoring: The resolved scoring clone, or None when none was given.

    Returns:
        Why it is refused, or None when it may be used.
    """
    if scoring is None:
        return "--enable-compare needs --scoring-clone: the comparison runs there"
    if scoring == ROOT.resolve() or ROOT.resolve().is_relative_to(scoring) \
            or scoring.is_relative_to(ROOT.resolve()):
        # The whole design is that the key lives in a DIFFERENT clone from the
        # one where prompts are edited. Pointing at this one, or at a directory
        # inside or around it, would put the key where the rule forbids it.
        return (f"refusing --scoring-clone {scoring}: it is this clone or "
                f"overlaps it, and the answer key must live in a separate one")
    if not scoring.is_dir():
        return f"--scoring-clone not found: {scoring}"
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
    # WHAT IS IN THAT DOCSTRING IS PRINTED BY `--help`, which is why two lines
    # came out of it on 2026-09-15. It exported
    # `COMPASS_SITE_DIR=/home/mehta5/compass-site/site` -- one occurrence in the
    # tracked tree, so read by NO code (`argparse` owns that path, below) and
    # naming a clone that has not held the page since `0606136` -- and it told
    # the reader to run `./.venv/bin/python`, which cannot work: that venv has
    # `ruff` and neither `pydantic` nor `pytest`.
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    # IN-TREE, not a sibling clone. This defaulted to
    # `/home/mehta5/compass-site/site`, which was the only copy of the page that
    # existed, so `python -m serve.api` exited 2 with "site dir not found" on any
    # box but one and the server could not be started from a clean checkout. The
    # page is 25 files; `site/` is now carried here and the pair of defaults is
    # checked against `_refuse_unsafe_site_dir` by a test, because a `site/`
    # inside the repository sits one directory from `build/dictionary.json`.
    ap.add_argument("--site-dir", type=Path, default=ROOT / "site")
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
    ap.add_argument("--enable-compare", action="store_true",
                    help="allow POST /api/compare, which places a finished Ask "
                         "record beside a paper's recorded design. OFF by "
                         "default: it consults the answer key. Needs "
                         "--scoring-clone.")
    ap.add_argument("--scoring-clone", type=Path, default=None,
                    help="the clone holding benchmark/design_key.py. The "
                         "comparison runs there as a subprocess; the key is "
                         "never imported into this clone.")
    ap.add_argument("--scoring-python", default=None,
                    help="interpreter for the scoring clone (default: this one)")
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
    scoring = a.scoring_clone.resolve() if a.scoring_clone else None
    if a.enable_compare:
        refusal = _refuse_scoring_clone(scoring)
        if refusal:
            print(refusal, file=sys.stderr)
            return 2
    state = State(a.deploy_root.resolve(), a.site_dir.resolve(), a.run_dir.resolve(),
                  show_instrument=a.show_instrument, auth=auth,
                  enable_specify=enable_specify,
                  allowed_models=frozenset(a.allow_model or DEFAULT_MODELS),
                  enable_compare=bool(a.enable_compare), scoring_clone=scoring,
                  scoring_python=a.scoring_python)
    srv = build_server(a.host, a.port, state)
    print(f"COMPASS test endpoint   http://{a.host}:{a.port}/")
    print(f"  site        {state.site_dir}")
    print(f"  deploy      {state.deploy_root}")
    print(f"  dictionary  {state.scrubber.source} "
          f"({len(state.scrubber.corpus)} five-word runs indexed)")
    print("  routes      GET /api/health · GET /console · POST /api/retrieve"
          " · POST /api/specify")
    if state.enable_compare and state.scoring_clone is not None:
        print(f"  compare     ON, run in {state.scoring_clone.name} with "
              f"{state.scoring_python}; ledger kept there, nothing kept here")
    print("  NOT a measurement surface: posed records, screened_from=0.")
    if state.show_instrument:
        print("  ** --show-instrument: responses carry question wording, options "
              "and keys VERBATIM. Withheld content. Loopback only. **")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.pseud.dump(state.run_dir / PSEUDONYM_MAP_NAME)
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
