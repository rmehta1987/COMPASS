# Brief — scope every open backlog item

Run in `/home/mehta5/compass-gen`, branch `ralph-loop`. **Analysis only. Build nothing,
commit nothing but the scoping document, and change no behaviour.**

Deliverable: `BACKLOG_SCOPE.md`, one section per open item, each broken into the fixed
sub-bullet schema in §2. The point is that a later agent can pick any item up and know
what it touches before opening a file.

## 0. Read the primaries, not the backlog

`TASKS.md` is an index, not evidence (`AGENTS.md` §Source of Truth). **Every claim it
makes about the code must be re-derived from the code before you repeat it**, and where it
is stale, say so in the item's scope. Cite `path::symbol`, never line numbers.

A verification pass on 2026-09-08 confirmed these still hold, so you need not redo them —
but do not extend the same trust to claims not on this list:

* C12: `benchmark/scorability.py::EXPOSURE_KEYS` is `{}` (read from source; the module
  cannot be imported here, see below).
* C17: `agent/schema.py::Provenance.model_id` is a single `str`.
* C27: `agent/sealed.py::SealedWorktree.run` does not reference `is_error`.
* C28: `agent/specifier.py::_rank` still carries the covariate-count term.
* C29: `_rank` has no proposal term.
* `benchmark/contamination_check.py::main` still computes `surface_hash`.
* `RefusalReason.access_gate_refused` and `no_contrast_definable` both still present.
* R3: no `retrieval_text` in `build.py`.

🛑 **Numbering note.** Two different items both carried the id `C28` until 2026-09-08. The
older one (the `_rank` covariate-count defect) keeps `C28`; the newer (model-proposed
derivations) is now `C29`. Commit messages and briefs written before that date may say
`C28` when they mean `C29`. Do not renumber anything else.

## 1. What you cannot verify here

Several backlog items name modules that **cannot be imported in this clone**:
`benchmark/scorability.py`, `benchmark/input_leakage.py`, `benchmark/instrument_terms.py`,
`benchmark/tier_gate.py` and `benchmark/contamination_check.py` all reach
`benchmark/prevalence_key.py`, which lives on the orphan branch `scoring-key` and must
never be fetched into a generation clone. Read their source instead of importing, and mark
every such item **VERIFIABLE-IN: score** in its scope.

Do not fetch `scoring-key`. Do not create `benchmark/prevalence_key.py`.

## 2. The sub-bullet schema — identical for every item

For each open item, produce exactly these sub-bullets. Write "none" rather than omitting
one, so the sections stay comparable.

* **Claim check** — each factual claim `TASKS.md` makes about the code, and whether it
  re-derives. Name the symbol you read or the command you ran. Flag anything stale.
* **Blockers** — what it waits on, and whether each blocker still holds today. Distinguish
  blocked-on-a-task from blocked-on-a-person from blocked-on-a-decision.
* **Files and lanes** — every file the change would touch, each assigned to Lane A, B or C
  per `AGENTS.md` §Parallel Lanes, plus anything the item touches that is in NO lane
  (`check.sh`, `run/`, `build.py`, `raw/`, `parked/`, `references/`, `agent/__init__.py`).
  Say explicitly if the item is cross-lane.
* **Verifiable in** — `gen`, `score`, `both`, or `neither`, with the reason.
* **Acceptance** — quote the ACCEPT clause if `TASKS.md` states one, and say whether it is
  testable as written. If it is not, say what is missing. If there is none, draft one.
* **Seeded failure** — how you would break the behaviour to prove the test catches it,
  and where the seed goes. `AGENTS.md` §Testing Patterns; note a `-k` selector narrows a
  seeded check and must not be used.
* **Blast radius** — does it move `surface_hash`, the build hash `3dc8415eccfe`, a saved
  record hash (those are filenames), a ratchet, or a prompt surface? Name each.
* **User amendment?** — yes/no, with the constraint it touches. Changing `_rank`, a Hard
  Constraint or its AST test is a user amendment, never a lane's.
* **Size** — S/M/L with one sentence of justification. Not hours.
* **Ordering** — what must land before it, and what it unblocks.

## 3. The items

Cover every one of these. Group them as `TASKS.md` does; do not reorder.

**The C12 chain:** C12, C6, C13, C21.
**Retrieval, lexical, in order:** R3, R9, R5. Note the scope note — the shipped embedding
retriever in `deploy/` is NOT governed by these; its open questions are
`CHARACTERISATION.md` §7.
**Blocked on a person:** the two Qualtrics exports.
**Not blocked on C12:** C16 (+ its second acceptance), C29, C17, C19, C27, C18, T4, T7,
C28, C26 (+ its two unmet preconditions and its operator question).
**Deferred 2026-08-28:** C8, C9, C10 — scope these as DEFERRED, one paragraph each, and
read `references/PRIOR_ART_CONTAMINATION.md` before writing anything about them.

**Known-open defects with no task yet:** the final section of `TASKS.md`. For these,
produce a shorter form — claim check, blast radius, and a one-line "would this earn an
item?" using the file's own bar: *"A finding earns an item only if it can change a number
the project publishes or blocks a downstream stage."* Two of them are decisions already
made (`surface_hash` should be deleted outright; `lane-b-referent` stays unmerged) — mark
those as decided, not open.

## 4. Two things to look for that the backlog does not connect

* **C28 and C29 are the same defect in two terms of one function.** C28 is the
  covariate-count term paying a record to adjust a wrong key over disclosing a gap; C29 is
  the blocked-on term letting an ungrounded proposal outrank a grounded record. Both are
  `_rank` rewarding the wrong thing, both are user amendments, and amending one without
  the other risks the second undoing the first. Scope them as a pair and say so.
* **Several items claim a guarantee that no test enforces.** `DESIGN.md` §7 lists three
  unbound or vacuous guarantees. When an item's ACCEPT clause restates a guarantee, check
  whether a test exists; an unenforced guarantee is this codebase's recurring defect
  (`AGENTS.md` §Testing Patterns).

## 5. Limits

* Analysis only. No code changes, no new tests, no edits to `TASKS.md` itself.
* Do not run `./check.sh` more than once, and do not run anything live or billed. No
  `--live`, no model calls, no `pipeline.run`, no `pipeline.pose_terms`.
* Do not read `codebook.csv`. Do not open `benchmark/cohort_papers.py` rows to check a
  citation — `AGENTS.md` §Contamination Practice: an agent reading paper content is itself
  a channel.
* Do not touch `deploy/`, the manifest or `smoke_test.py`.
* `BACKLOG_SCOPE.md` is a tracked markdown file at the repo root, so it is subject to
  `tests/test_publication_surface.py` and `AGENTS.md` §Publication Boundary: no instrument
  key token, no term paired with an inventory status. Run that test file before you finish
  — and note it scans `git ls-files`, so **stage your file first or it is not scanned**.
* You are not the operator. Scope the work; do not decide which items get done.

## 6. Done when

* `BACKLOG_SCOPE.md` covers every item in §3 with the full §2 schema, none omitted.
* Every `TASKS.md` claim you repeated has been re-derived, and every stale one is flagged.
* Items unverifiable in this clone are marked VERIFIABLE-IN: score with the reason.
* C28 and C29 are scoped as a pair.
* `tests/test_publication_surface.py` passes with your file staged.
* `./check.sh` still green and nothing else in the tree changed.
