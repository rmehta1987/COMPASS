# TIER STATE
build: 3dc8415eccfe
schema: inventory/schema.py@292571ccc682   (pinned by the scorer, never imported)
tier_rule: confident_anchor
last green: ed49ff3   (VERIFIED 2026-09-06, ./check.sh unpiped, exit 0, "GREEN";
                       ruff 226 <= 232, mypy 59 <= 59, R@1 0.643, canaries 7/7,
                       smoke_test ALL PASS, step 11 0 problems)

BLOCKED: the modality_mismatch half of item 8 — needs pipeline items 16-19.
         Everything else is buildable.

inputs:  BOTH PRESENT as of 6779b78. posed_pairs.json (95 rows, exactly
         {case_id, exposure, outcome}, c001..c095) and handoff/for_harness.json,
         taken from the orphan branch handoff-public (dcd80da), which shares no
         history with scoring-key. case_map.json is NOT here and never may be.
         Re-checked after the fetch: `git show scoring-key:...` finds nothing,
         no benchmark/prevalence_key.py in the tree, so check.sh step 0 holds
         and the artefacts generated here are not void.

seal:    the loop must never fetch scoring-key. handoff-public is fetched by
         explicit refspec only (`git fetch origin handoff-public`); the clone's
         configured refspec stays +refs/heads/ralph-loop:refs/remotes/origin/ralph-loop.

note: design agreement is not a component (design=false, 7 of 16 untrustworthy).
note: the real run is an operator step in compass-score; tier assignment needs
      the inventory and case_map.json, so it is BUILT and TESTED here against
      the fakes only. Never assert against the real tier_counts here.
note: an empty tier is UNMEASURED, never 0% (14a). Tier A is one paper with one
      posed pair; at the observed temporality discard it can vanish entirely.
note: the earlier TIER_STATE's blockers 1 and 2 are resolved/dissolved — the
      reasoning is in TIER_ATTEMPTS.md so it is not re-litigated.

## items  (phase 1 = build and prove on the fakes; phase 2 = generate)
- [x] 1  add tiered_score.py to check.sh          4a6986d
- [x] 2  fake inventory, 5 synthetic papers       cdcdfad
- [x] 3  posed-pair driver                        0808eef
- [x] 4  load for_harness.json, assert three hashes  0ccc446
- [x] 5  tier assignment code                     39ded44
- [x] 6  anchor-resolution component  955ee3e
- [x] 7  refusal component  40f15df
- [x] 8  modality analogue resolution (half — see 8a)  588cee5
- [x] 9  covariate recall, raw  2def6e7
- [x] 10 covariate recall, margin over modal  d56aaed
- [x] 11 direction agreement, weighted per paper  e558660
- [x] 12 tier A and B renderer — case studies  d64132d
- [x] 13 tier C and D renderer — rates  f4e4d20
- [x] 14 report assembly, targets before numbers  db959a2
- [x] 15 run the driver over all 95 cases       11c03f4, stamped 9e862b4,
         tagged posed-3dc8415eccfe-tiered-20260906. 9 emitted, 1 refused,
         85 unresolved_anchor. Pushed.
- [x] 16 commit and report attrition  ad0faa8 (code) + 11c03f4 (the run's
         own attrition.json: both sides 38, exposure only 37, outcome only
         10, emitted 9, refused 1; 18 abstaining SIDES near the threshold)

## PHASE 3 IS THE OPERATOR'S, in compass-score
The loop cannot run it: tier assignment needs the inventory and
inventory/case_map.json, and neither may ever be in compass-gen.

    git fetch && git checkout <ralph-loop at ed49ff3 or later>
    python -m benchmark.contamination_check --live        # before scoring
    python -m benchmark.tiered_score \
        --run artefacts/tiered-20260906 \
        --inventory inventory/ \
        --case-map inventory/case_map.json \
        --min-cos 0.729476

The scorer reads inventory rows as data and pins schema_version; it never
imports inventory/schema.py, and it never reads case_map.json unless handed it
with --case-map. If the tier predicate meets a paper reachable on both sides
only through an analogue it raises UnclassifiablePaper rather than binning it
(see below).

stamping note: `pipeline.generation_env.stamp(require_pushed=True)` records
tree_clean, and baseline_score refuses a stamp taken on a dirty tree. The
untracked run directories under artefacts/ (b4, b5, the tiered dry run) must
be moved out of the tree before stamping and restored after.

## Open question for the operator (not a blocker; nothing waits on it)
- The tier predicate does not place a paper whose BOTH sides are reachable
  only through a modality analogue: not A, not B, and not C or D since both
  sides are reachable. `tier_of` raises `UnclassifiablePaper` on that shape
  rather than binning it. If the real inventory holds one, phase 3 will stop
  there and the rule needs a fifth clause from the operator. The handoff's
  tier_counts sum to 16 with no residue, so it may well not occur.

## PARKED
(item · three attempts · why)
(none)
