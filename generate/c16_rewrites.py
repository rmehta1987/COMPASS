"""Driver for C16's rewrite stage: produce phrasings, then measure the delta.

Two subcommands, deliberately separate. `produce` makes the model calls once and
writes an artifact; `measure` reads that artifact and scores it. Splitting them
is what makes the measurement re-derivable without re-running a model: the
scored arm is a committed file, not a live call whose output nobody kept.

The model is `claude-haiku-4-5`, the in-pipeline pin (`AGENTS.md` §Hard
Constraints). A rewrite stage is in-pipeline work, so it runs at the pin rather
than at whatever is convenient; `agent/cli_backend.py::ClaudeCliBackend` defaults
to sonnet, which is why the model is named explicitly everywhere below.

Every call runs inside `agent/sealed.py::SealedWorktree` with no MCP config and
the standard deny list, so the rewriter has no filesystem, no web and no
environment tools — it sees the request string and nothing else.

Run it:
    python -m generate.c16_rewrites produce
    python -m generate.c16_rewrites measure
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import statistics
import sys
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from agent.query_rewrite import (
    N_PHRASINGS,
    POOL_CAP,
    REWRITE_PROMPT,
    ModelFn,
    Rewrite,
    RewriteSearch,
    min_rank_fusion,
    rewrite,
    rrf_fusion,
)
from agent.sealed import SealedWorktree
from benchmark import retrieval_eval as R

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "run"

#: The in-pipeline pin. Never widened to pass a run (`AGENTS.md`).
MODEL = "claude-haiku-4-5"

#: How many rewrite calls run at once. Subprocesses, so threads are the right
#: pool. Every worker gets its OWN sealed cwd: eight workers sharing one
#: finished 40 rows in 55 minutes against 3.6 seconds for the same call alone,
#: which is contention on the per-directory state the CLI keeps, not the model
#: being slow.
WORKERS = 6


def prompt_hash() -> str:
    """A short digest of the prompt body every phrasing was produced under.

    Returns:
        The first twelve hex characters of the body's SHA-256, so an artifact
        produced under an edited prompt cannot be mistaken for one produced
        under this prompt.
    """
    return hashlib.sha256(REWRITE_PROMPT.body.encode()).hexdigest()[:12]


def artifact_path(model: str = MODEL) -> Path:
    """Where a produced artifact lives.

    Args:
        model: The model whose rewrites the artifact holds.

    Returns:
        The path, named by model and prompt digest.
    """
    return RUN / f"c16_rewrites.{model}.{prompt_hash()}.json"


def requests_from_fixture() -> tuple[str, ...]:
    """Every distinct request string in the committed retrieval fixture.

    Returns:
        The requests, in fixture order, deduplicated.
    """
    seen: set[str] = set()
    out: list[str] = []
    for row in R.load_fixture().queries:
        if row.query not in seen:
            seen.add(row.query)
            out.append(row.query)
    return tuple(out)


def sealed_model(worktree: SealedWorktree, model: str = MODEL) -> ModelFn:
    """A `(prompt) -> raw text` callable running inside one seal.

    Args:
        worktree: The sealed cwd every call runs in.
        model: The model id.

    Returns:
        The `ModelFn` the rewriter calls.
    """
    def call(prompt: str) -> str:
        out = worktree.run([*worktree.base_argv(model), prompt], timeout=240.0)
        if out.get("is_error"):
            raise RuntimeError(f"claude -p reported an error: "
                               f"{str(out.get('result'))[:400]}")
        return str(out.get("result", ""))
    return call


class PerThreadSeal:
    """One `SealedWorktree` per worker thread, shared by nobody.

    A pass with eight threads through a single sealed cwd finished 40 of 221
    rows in 55 minutes while the same call alone took 3.6 seconds. The seal is
    per-directory state, so sharing one directory serialises the workers behind
    each other. A thread-local worktree is the fix, and it costs a `mkdtemp` and
    two small files per thread.

    Attributes:
        model: The model id every call runs at.
        mode: The registry mode the seal is built for.
    """

    def __init__(self, model: str = MODEL, mode: str = "benchmark",
                 system: str = "") -> None:
        """Prepare the thread-local store.

        Args:
            model: The model id.
            mode: The registry mode.
            system: A system prompt appended to the CLI's own. A large static
                one is how a long candidate list gets CACHED: measured
                2026-09-02 on a 38k-token instrument catalogue, carrying it as
                the system prompt read 40,581 cached tokens per row after the
                first, while carrying it in the user prompt with the request
                appended re-created all 38k every row and cost 3x.
        """
        self.model = model
        self.mode = mode
        self.system = system
        self._local = threading.local()
        self._all: list[SealedWorktree] = []
        self._lock = threading.Lock()

    def _worktree(self) -> SealedWorktree:
        """This thread's sealed cwd, made on first use.

        Returns:
            The worktree bound to the calling thread.
        """
        wt = getattr(self._local, "wt", None)
        if wt is None:
            wt = SealedWorktree(mode=self.mode)
            self._local.wt = wt
            with self._lock:
                self._all.append(wt)
        return wt

    def __call__(self, prompt: str) -> str:
        """Run one prompt in this thread's seal.

        Args:
            prompt: The rendered prompt.

        Returns:
            The model's raw text.
        """
        return str(self.call_json(prompt).get("result", ""))

    def call_json(self, prompt: str, timeout: float = 600.0) -> dict:
        """Run one prompt and return the CLI's whole reply.

        The usage block is the point: a caller that needs to report token cost
        or whether the cache was read cannot get either from the result text.

        Args:
            prompt: The rendered prompt.
            timeout: Seconds to allow.

        Returns:
            The parsed JSON the CLI wrote.

        Raises:
            RuntimeError: If the CLI reported an error.
        """
        wt = self._worktree()
        argv = [*wt.base_argv(self.model)]
        if self.system:
            argv += ["--append-system-prompt", self.system]
        out = wt.run([*argv, prompt], timeout=timeout)
        if out.get("is_error"):
            raise RuntimeError(f"claude -p reported an error: "
                               f"{str(out.get('result'))[:400]}")
        return out

    def manifest(self) -> dict:
        """The seal every call ran under.

        Returns:
            The manifest of the first worktree made, plus how many were used.

        Raises:
            RuntimeError: If no call has run, so no seal exists to describe.
        """
        if not self._all:
            raise RuntimeError("no sealed worktree was made; nothing ran")
        return {**self._all[0].manifest(), "worktrees": len(self._all)}

    def close(self) -> None:
        """Remove every worktree this pass made."""
        for wt in self._all:
            shutil.rmtree(wt.cwd, ignore_errors=True)


def _safe_rewrite(request: str, call: ModelFn, n: int,
                  attempts: int = 2) -> Rewrite:
    """One request's rewrite, with a retry, that cannot take the pass down.

    The first live pass lost 220 finished calls to one subprocess that hung past
    its timeout, because `ThreadPoolExecutor.map` re-raises. A failed call is a
    row that degrades to the control arm — the same outcome as a malformed
    reply — and that is a result to record, not an exception to propagate.

    Args:
        request: The researcher's words.
        call: The `(prompt) -> raw text` seam.
        n: How many phrasings to ask for.
        attempts: How many times to try before giving up on the row.

    Returns:
        The rewrite, or a malformed one carrying the error text as `raw`.
    """
    last = ""
    for _ in range(attempts):
        try:
            return rewrite(request, call, n)
        except Exception as exc:
            last = f"ERROR {type(exc).__name__}: {str(exc)[:300]}"
    return Rewrite(request=request, phrasings=(request,), malformed=True,
                   raw=last)


def produce(model: str = MODEL, n: int = N_PHRASINGS) -> Path:
    """Make one rewrite call per distinct fixture request and write the artifact.

    Resumable: a request already carrying a parsed reply in the artifact is not
    re-asked, so a pass interrupted by a hung call resumes at the rows it never
    reached instead of spending 221 calls again.

    Args:
        model: The model id to run at.
        n: How many phrasings to ask for.

    Returns:
        The artifact path.
    """
    requests = requests_from_fixture()
    done: dict[str, Rewrite] = {}
    if artifact_path(model).exists():
        prior = json.loads(artifact_path(model).read_text())["rewrites"]
        done = {q: Rewrite(request=q, phrasings=tuple(v["phrasings"]),
                           malformed=v["malformed"], raw=v["raw"])
                for q, v in prior.items() if not v["malformed"]}
    todo = [q for q in requests if q not in done]
    started = time.time()
    call = PerThreadSeal(model)
    seal: dict = {}
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(_safe_rewrite, q, call, n) for q in todo]
            for i, fut in enumerate(as_completed(futures), start=1):
                r = fut.result()
                done[r.request] = r
                seal = call.manifest()
                # Checkpointed, because the first pass spent 221 live calls and
                # kept none of them: the driver held every result in memory and
                # wrote once at the end, so a timeout at row 200 was a timeout
                # at row 0.
                if i % 10 == 0 or i == len(todo):
                    _write(model, n, seal, started, requests, done, len(todo))
                    print(f"  {i}/{len(todo)}", flush=True)
    finally:
        call.close()
    return _write(model, n, seal, started, requests, done, len(todo))


def _write(model: str, n: int, seal: dict, started: float,
           requests: Sequence[str], done: dict[str, Rewrite],
           asked: int) -> Path:
    """Write the artifact from whatever has finished so far.

    Args:
        model: The model id the phrasings were produced at.
        n: How many phrasings each request asked for.
        seal: `SealedWorktree.manifest()`, the isolation the calls ran under.
        started: When the pass began, for the elapsed figure.
        requests: Every request, in fixture order.
        done: The rewrites finished so far.
        asked: How many requests this pass called the model for.

    Returns:
        The artifact path.
    """
    results = [done[q] for q in requests if q in done]
    path = artifact_path(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "c16_rewrites/1",
        "generated": time.strftime("%Y-%m-%d"),
        "model": model,
        "asked_for": n,
        "prompt_hash": prompt_hash(),
        "seal": seal,
        "seconds": round(time.time() - started, 1),
        "malformed": sum(1 for r in results if r.malformed),
        "asked_this_pass": asked,
        "finished": len(results),
        "requests": len(requests),
        "rewrites": {r.request: {"phrasings": list(r.phrasings),
                                 "malformed": r.malformed,
                                 "raw": r.raw} for r in results},
    }, indent=1))
    return path


def load_rewrites(path: Path | None = None) -> dict[str, list[str]]:
    """Read a produced artifact.

    Args:
        path: The artifact; the current model and prompt digest by default.

    Returns:
        Request -> phrasings, the request itself first.

    Raises:
        FileNotFoundError: If no artifact exists for this prompt.
    """
    p = path or artifact_path()
    if not p.exists():
        raise FileNotFoundError(
            f"{p} is missing. Run `python -m generate.c16_rewrites produce`. "
            f"An artifact for a DIFFERENT prompt hash does not substitute: the "
            f"phrasings are what the prompt produced.")
    doc = json.loads(p.read_text())
    return {q: list(v["phrasings"]) for q, v in doc["rewrites"].items()}


def _depth_table(depths: Sequence[int]) -> str:
    """Render the rank-depth distribution C17 needs to size its read window.

    Args:
        depths: The fused rank of the gold wording, one per row that has one.

    Returns:
        A multi-line block of quantiles and a cumulative table.
    """
    s = sorted(depths)
    q = statistics.quantiles(s, n=100) if len(s) > 2 else list(s)
    lines = [f"    n={len(s)}  min {s[0]}  median {int(statistics.median(s))}  "
             f"max {s[-1]}"]
    lines.append(f"    p50 {int(statistics.median(s))}  p75 {int(q[74])}  "
                 f"p90 {int(q[89])}  p95 {int(q[94])}  p99 {int(q[98])}")
    lines.append("    depth   rows at or above   share")
    for d in (1, 5, 10, 25, 50, 100, 250, 500, 1000, 2804):
        n = sum(1 for x in s if x <= d)
        lines.append(f"    {d:>5}   {n:>16}   {100 * n / len(s):5.1f}%")
    return "\n".join(lines)


def measure(path: Path | None = None) -> int:
    """Score the produced arm against the committed fixture and report.

    Args:
        path: The artifact to score.

    Returns:
        A process exit code: 0 when `gold_excluded` reached 0, 1 otherwise.
    """
    rewrites = load_rewrites(path)
    fixture = R.load_fixture()
    base = R.evaluate(fixture=fixture, fixture_path=R.FIXTURE)

    arms: dict[str, RewriteSearch] = {
        "min_rank": RewriteSearch(rewrites, fusion=min_rank_fusion, cap=POOL_CAP),
        "rrf": RewriteSearch(rewrites, fusion=rrf_fusion, cap=POOL_CAP),
    }
    reports = {name: R.evaluate(search=arm, fixture=fixture,
                                fixture_path=R.FIXTURE)
               for name, arm in arms.items()}

    print("C16 rewrite stage — delta against the shipped search\n")
    print(f"model            {MODEL}")
    print(f"prompt           {prompt_hash()}")
    print(f"phrasings        {N_PHRASINGS} asked, request always searched first")
    print("turns per row    1 (one rewrite call; no confidence-driven re-query)")
    print(f"pool cap         {POOL_CAP}")
    print(f"fixture          {base.fixture_path}")
    print(f"dictionary       {base.dictionary_version}\n")
    print(R.BIAS_BANNER)
    print(f"    {base.known_bias}\n")

    ex_base = sum(1 for o in base.results if o.rank is None)
    print(f"{'arm':<10} {'gold_excluded':>14} {'@1':>6} {'@5':>6} {'@10':>6}")
    print(f"{'control':<10} {f'{ex_base}/224':>14} "
          f"{base.recall_at(1):>6.3f} {base.recall_at(5):>6.3f} "
          f"{base.recall_at(10):>6.3f}")
    for name, rep in reports.items():
        ex = sum(1 for o in rep.results if o.rank is None)
        print(f"{name:<10} {f'{ex}/224':>14} "
              f"{rep.recall_at(1):>6.3f} {rep.recall_at(5):>6.3f} "
              f"{rep.recall_at(10):>6.3f}")

    best = "min_rank"
    rep = reports[best]
    depths = [o.rank for o in rep.results if o.rank is not None]
    print(f"\nrank depth of the gold wording, {best} arm — C17's read window:")
    print(_depth_table(depths))

    pools = sorted(arms[best].pool_sizes.values())
    print(f"\npool size per row (pre-cap), {best} arm:")
    print(f"    min {pools[0]}  median {int(statistics.median(pools))}  "
          f"p90 {pools[int(0.9 * len(pools)) - 1]}  max {pools[-1]}")

    ex = sum(1 for o in rep.results if o.rank is None)
    print(f"\nACCEPTANCE  gold_excluded {ex_base}/224 -> {ex}/224")
    return 0 if ex == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run a subcommand.

    Args:
        argv: Command-line arguments; `sys.argv[1:]` by default.

    Returns:
        A process exit code.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("produce", "measure"))
    args = ap.parse_args(argv)
    if args.command == "produce":
        print(produce())
        return 0
    return measure()


if __name__ == "__main__":
    sys.exit(main())
