# skip logic and missingness
**Topic id:** `skip_logic_missingness` · authored 2026-08-26 · unconfirmed by study team
**Source:** `authored-unconfirmed` — written by the pipeline author, not supplied or reviewed by the study team.

Skip logic appears **nowhere** in a two-column codebook. The instrument plainly has it —
"how old were you when you were first told" is asked only of those who answered yes —
but no machine-readable record of it exists in `raw/`.

**Convention.** Any variable whose wording presupposes a prior affirmative answer is
defined only within a subgroup. Naming it as a covariate conditions on that subgroup and
induces selection bias. Such variables are excluded with role `descendant_of_outcome` or
`descendant_of_exposure` and a mechanism sentence naming the presupposition.

**Enforcement is by wording, not by structure.** `branch_dependency` is null for all
2,804 rows and a test asserts it stays null. That test failing is the notification that a
richer codebook arrived — it is not a bug.

**Default.** A prune criterion whose input does not exist does not prune. Suspected skip
logic is a reason to exclude a covariate with a stated role, never to silently drop a
candidate pair.
