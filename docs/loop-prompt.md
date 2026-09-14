# The backlog loop — operator's prompt and its guards

Written 2026-09-10. Point `/loop` at this file. Everything here was checked against the
tree on that date; re-check before trusting a count, a path or a hash.

## Where you run

| clone / branch | has `serve/` | has `build/` `fixtures/` `raw/` `targets.json` | has `benchmark/prevalence_key.py` | runs the suite |
|---|---|---|---|---|
| `COMPASS` @ `merge-code-and-docs` | no | no | no | no |
| `compass-gen` @ `ralph-loop` | no | **yes** (untracked, survive a checkout) | no | no — 4 modules fail to import |
| `COMPASS/.claude/worktrees/serve-endpoint` @ `worktree-serve-endpoint` | **yes** | `build/` only (symlink) | no | no |
| `compass-score` @ `ralph-loop` | no | yes | **yes** | yes — 993 pass / 1 fail of 994 |

**Run in a dedicated clone**, made once by the operator, not by you:
`git clone /home/mehta5/COMPASS`, `git checkout worktree-serve-endpoint` (23 commits ahead
of `merge-code-and-docs`, zero behind, merge base `c7a27eb1`), then link `build/`,
`benchmark/fixtures/`, `raw/` and `deploy/targets.json` from `compass-gen`. Those four are
untracked, so they survive every checkout. Do not hijack `compass-gen` or `compass-score`;
both carry live work.

🛑 **Never open `compass-score`.** No currently-actionable item needs it. It holds the
answer key, and you author prompts and docstrings — reading it is the channel, and a fresh
session does not close it. If `benchmark.contamination_check` will not run, that is
**task 0d below**, not a reason to go and get the key.

## Clone setup: which artifacts may be symlinked, and which may NOT

🛑 **`build/` and `run/` must be REAL COPIES in the loop clone, never symlinks.**
`tests/test_dictionary.py::test_build_is_deterministic` runs `build.py` as a subprocess
with `cwd=ROOT`, and `build.py` writes `dictionary.json`, `version.json` and four CSVs
into `ROOT/"build"`. Through a symlink that write lands in the clone the link points at.
Observed 2026-09-10: two suite runs in the loop clone rewrote
`/home/mehta5/compass-gen/build/` — harmless that time because the rules were unmutated
and the hash stayed `3dc8415eccfe`, but `CLAUDE.md` requires re-running the build between
seeding a `build.py` mutation and testing it, and that sequence would have written a
MUTATED dictionary into the generation clone. Git cannot see it: the artifact is
untracked and outside the tree. `build.py::_version_hash`'s own docstring says it was
extracted so a test could ask what a rule edit does to the hash *without* running a build
"which would write `build/`" — and this test does exactly that.

Read-only paths may stay symlinks: `raw/`, `benchmark/fixtures/`, `deploy/targets.json`,
and the root `targets.json` / `dictionary.json` / `retrieval_queries.json`.

Also set `user.name` and `user.email` **in the clone** — COMPASS sets them locally, not
globally, so a fresh clone cannot commit at all until you do.

## Baseline, measured in the loop clone 2026-09-10

Read your own floor on iteration 1 and compare to these; do not inherit a number from
another clone. `compass-score`'s 994 is a different tree.

| gate | value here | limit | headroom |
|---|---|---|---|
| tests collected (4 key-dependent modules ignored) | **809** (791 passed, 10 failed, 8 skipped) | may only rise | — |
| `ruff check .` | **227** | `RUFF_CEILING` 232 | 5 |
| `mypy` | **59** | `MYPY_CEILING` 59 | **none — any new error fails** |
| `build.py` | **3dc8415eccfe** | `tests/test_dictionary.py::BUILD_HASH` | must not move |
| `benchmark.retrieval_eval` | runs | — | — |
| `benchmark.contamination_check` | **cannot run** — `benchmark.prevalence_key` | task 0d | — |

The 10 failures and the 4 ignored modules are all the same cause, and all clear when 0d
lands. `pytest tests/` unignored exits 2 on collection, so **0d is the first thing that
makes the primary gate runnable at all.**

## Order

Do exactly one item per iteration, in this order. Skip nothing silently: if an item is
blocked, say so, record why, and move to the next.

**Tier 0 — preconditions. Status as of 2026-09-10; do not re-do the DONE ones.**
- 0a  **NOT BLOCKING — note only.** `serve/` is in no lane (`AGENTS.md` §Parallel Lanes),
      so it may not be dispatched to parallel lanes. This loop is SERIAL — one item per
      iteration — so nothing can collide and the rule's purpose is not engaged. Do not
      stop for it. It must be settled before anyone dispatches lanes again; the collision
      it guards is C29a (`agent/prompt_contract.py`, Lane A) against C29/C31
      (`serve/api.py`, unassigned).
- 0b  **GRANTED by the operator 2026-09-10: the build hash may move to whatever value is
      necessary.** Not needed yet, and the premise was inverted — MEASURED the same day
      with `build.py::_version_hash`, baseline reproducing `3dc8415eccfe` exactly: adding
      a column INSIDE `build()` does **not** move the hash, because `build` is in
      `_NOT_HASHED` as a DECLARED GAP and its source never enters the payload. What does
      move it: adding a name to `_HASHED_SOURCES` (→ `622d09c5da95`), bumping
      `BUILD_RULES_VERSION` (→ `340acb97f4bd`), editing a hashed regex (→ `4e1dd2ac4310`).
      `AGENTS.md`'s "any column … moves `version_hash` on its own" is false as written.
      When you reach R3 or C26, state which of those you are doing and update ALL NINE
      live pins (six `EXPECTED_HASH` guards in `src/`, three test constants), leaving the
      two historical mentions in `agent/query_rewrite.py` alone. Stop and confirm the
      blast radius on `deploy/` first — `deploy/manifest.json::dictionary_version_hash`
      and the 0.942 parity gate both artifacts rest on.
- 0c  **DONE** — `5cb989e`. `_role_candidates`'s docstring corrected to what the code
      does, with `test_the_role_never_reaches_the_encoder` pinning it. `role` is NOT
      rendered; do not make it render.
- 0d  **DONE** — `27b6949`. The two withheld imports are deferred, `main`'s sections are
      lazy, and a section whose module is missing SKIPs loudly with a non-zero exit.
      `benchmark.contamination_check` now runs everywhere; `pytest tests/` collects 917
      where it could not collect at all before.

**Tier 1 — cheap, unblocked, each gates something unrepeatable**
- 1  C27 — must precede C6. C6 is one-shot and C27 is a defect in its scorer.
- 2  C31(a)(b) — must precede C29's end-to-end. A pinned request bypasses retrieval and
     the model entirely, so it would count as covered without a splitter running.
- 3  T4 — must precede C6, the C18 sweep, C21 and C29's measurement. It changes the system
     prompt of every Specifier call.
- 4  C19 — must precede C6.

**Tier 2 — decisions that reshape Tier 3**
- 5  C30, convention reading, **user-level** — stop and ask. Must precede C29's fixture,
     C17, the C18 sweep and C21.
- 6  C29a, with `benchmark/resolver_eval.py`'s re-baseline named in its ACCEPT.
- 7  Reconcile C16 with C29 — one resolver, one control arm.
- 8  C17, built as N models, not two.

**Tier 3 — C29, restaged (see below).** 9 = C29-A, 10 = C29-B, 11 = C29-C.

**Tier 4 — the C12 chain:** C6's designable-with-instrument check ∥ C12 → C13 → T7 →
C18 sweep → C28 (user-level) → C6 (last live one-shot) → C21.
**Separate serial chain:** R3 → R9 → R5, C26 last and gated. Both R3 and C26 move the
build hash; move it once.

## C29 is three items, not one

The construct arm is **not** C29's ceiling. Measured 2026-09-10, at k=20: shared 0.32,
**split by role 0.51**, split by construct 0.71. By shape, role vs construct: 1×1
0.825/0.825 (same operation), 1×2 **0.300**/0.633, 2×2 **0.000**/0.500. A role splitter
emits one query per role however many constructs that role carries, so at 2×2 a *perfect*
role split covers nothing the shared pool did not.

- **C29-A** — done 2026-09-10: the `split_role` arm in `src/pool_coverage.py`.
- **C29-B** — restate the shipping baseline. 60 of the 100 requests are shapes no record
  can express (C30). The figure governing the route as it exists is 1×1: **0.600 shared
  against 0.825 oracle, on 40 requests**. No document may quote 0.32 as the number `_pair`
  fails at without naming that.
- **C29-C** — a real splitter, blocked on C29-A and C30. Its acceptance must not compare a
  clean fixture's result against the biased fixture's baseline, and must not reuse the
  biased fixture — every request there is `<exposures> affect <outcomes>`, so splitting on
  the literal token ` affect ` scores the oracle and generalises to nothing. Report
  end-to-end coverage on the same requests in the same run, never a product of accuracy
  and coverage; report a **wrong-split harm** count beside it; land a test on `_pair` in
  the same commit.

## Commit discipline

One logical change per commit; the message records the failure it prevents. Small enough
that a revert loses one idea.

**Before the first command, once.** Snapshot `out/`, `fixtures/`, `run/`, `build/`,
`dictionary.json`, `targets.json` outside every clone with a sha256 manifest — they are
gitignored and git will not protect them. **Refuse to start on a dirty tree**; the
operator commits or stashes with `git stash push -a` (plain `stash` skips ignored files).
Probe `pytest`, `mypy`, `build/dictionary.json`, `benchmark/fixtures/` and abort on any
failure: a loop that cannot run a gate must not commit code that gate governs. Record
which of `AGENTS.md` §Verify current state's six commands actually ran — a commit whose
gates were unrunnable is **unmeasured**, not green.

**Never touch, without stopping to ask:** `_rank`, `canonical_form`, `record_hash`,
`ENV_MODEL_GRANTS`, the Hard Constraints text, `AGENTS.md`, `CLAUDE.md`, `.gitignore`,
`pyproject.toml`'s `exclude`/`files`, C30, C28, C21's `_rank` rewrite, C12's key form, or
FUSION Recommendation 1.

**Pre-commit, every time.**
1. Whole suite, unpiped, no `-k`, no `-x`; read `$?` directly; persist with `--junitxml`.
   A pipe returns `tail`'s exit code, and `-k` silently narrows a seeded-failure check.
2. Test count from the junit XML (passed+failed+skipped+errors), refused if it fell.
   Refuse separately if the **skip count rose** — a new skip is a test that stopped running.
3. Refuse any diff that moves `RUFF_CEILING`, `MYPY_CEILING`, a recall floor, `BUILD_HASH`,
   a fixture-row count or an AST term tuple, unless the operator amended it. Where a move
   is legitimate, parse old and new and enforce ceiling↓ / floor↑ mechanically.
4. Refuse `git add -f` outright, and refuse any staged path under `out/`, `run/`,
   `fixtures/`, `build/`, `raw/`, `*.csv`, `dictionary.json`, `targets.json`. You may write
   those files; staging them is a human act preceded by a wording scan.
5. If the diff touches `agent/`, `env/`, `generate/`, `benchmark/`, `build.py` or `serve/`
   and adds no test lines, refuse.
6. Seeded failure, in a **throwaway worktree**: apply the mutation, `rm -rf __pycache__`
   before and after, re-run `build.py` if `build.py` was mutated, run the **whole owning
   test file** with no selector, assert red, discard. Record the mutation and the red test
   ids in a commit trailer.
7. If the diff touches a prompt, a convention, an `agent/schema.py` docstring,
   `env/tools.py` or `agent/prompt_contract.py`: run `benchmark.contamination_check`,
   require exit **0 or 2** — 2 means every section that RAN was clean and an answer-key
   module is withheld from this clone, which is the normal state here and cannot be
   fixed by any diff; 1 means a section FAILED and is a stop. Print `surface_hash` and
   the exempt-character count, and **do not** treat a moved hash as failure.
8. Refuse a diff constructing `ClaudeCliBackend(` without an explicit `model=` — it
   defaults to sonnet and the in-pipeline Specifier is `claude-haiku-4-5`.

**Post-commit, every time.**
9. Re-run the suite from a **fresh worktree at the new sha**. This is the only check that
   catches a green depending on an untracked file — `fixtures/multi_construct_requests.json`
   and every `out/*.json` are untracked.
10. `rm -rf __pycache__` and re-run once. A green that vanishes was bytecode.
11. Re-run `build.py` and assert the printed hash matches — then grep **all 12
    occurrences across 10 files** and assert they agree. `AGENTS.md` says "the pin lives
    once, in `tests/test_dictionary.py::BUILD_HASH`"; that is false, and a partial update
    leaves the tree self-inconsistent while green.
12. Write a machine-readable commit trailer: test count, skip count, ruff count, mypy
    count, build hash, `surface_hash`, and which of the six commands ran. The trailer is
    what survives a revert, so the ratchet cannot be walked backwards by restoring a file.
13. Monotonicity over the **whole loop history**, not commit-to-commit: read every trailer
    from the loop's first commit to HEAD and assert ruff and mypy never rose, floors never
    fell, test count never fell.

**Reverting.** 🛑 Never `git reset --hard`, `git checkout -- .` or `git clean` — untracked
artifacts are not recoverable and are not in git. Revert means `git revert <sha>`,
producing a new commit that passes the entire pre-commit gate including 2, 3 and 13. A
revert that lowers the test count or raises a ceiling is refused like any other commit and
**the loop stops for a human**.

**Never push.** Publication is a human act.

## Stop the loop and wait for the operator when

- A stop condition trips: the test count fell, or the build hash moved off `3dc8415eccfe`.
- An item is user-level (Tier 0, C30, C28, C21's `_rank`, C12's key form).
- A gate cannot run. Report which, and do not commit code that gate governs.
- A revert would move a ratchet the wrong way.
- Three consecutive iterations produce no commit.
