"""Skip guards for the tests that need an answer-key module.

`benchmark/prevalence_key.py` and `benchmark/leak_facts.py` are held out of
every clone but the scoring one, and the clone where prompts, conventions and
`env/tools.py` are EDITED is never the scoring one. Until 2026-09-14 the 45
tests that need them therefore FAILED here, in the same red as a test the last
edit actually broke. A suite that is permanently red says nothing about the
change you just made, and the habit it trains -- read past the failures -- is
the habit that hides the forty-sixth.

So those tests skip here instead. A skip is not a pass and pytest counts it
separately, which is the whole point: `benchmark/contamination_check.py` makes
the same distinction in its exit status (`EXIT_INCOMPLETE`), for the same
reason, and `AGENTS.md` §Verification Discipline is the rule both implement --
"could not detect X" is never "X is absent".

Two properties this must keep:

- **Named, not broad.** The skippable modules come from
  `benchmark.contamination_check.WITHHELD_MODULES` rather than being retyped,
  so the set cannot drift apart from the gate's, and a genuine missing
  dependency still fails rather than being laundered into a skip.
- **Nothing is deleted.** Every guarded test stays collected, so the suite's
  test count does not fall, and the same test runs for real in the clone that
  holds the key.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmark.contamination_check import WITHHELD_MODULES  # noqa: E402

PREVALENCE_KEY = "benchmark.prevalence_key"
LEAK_FACTS = "benchmark.leak_facts"

# The guards may only name a module the gate agrees is withheld. Asserted at
# import so a rename in WITHHELD_MODULES cannot leave a guard that skips on a
# module nobody holds out -- which would be an unconditional skip wearing a
# condition.
assert {PREVALENCE_KEY, LEAK_FACTS} <= WITHHELD_MODULES, (
    f"a guard names a module WITHHELD_MODULES does not: "
    f"{{PREVALENCE_KEY, LEAK_FACTS}} - {WITHHELD_MODULES}")


def present(module: str) -> bool:
    """Whether a withheld module can be imported in this clone.

    Args:
        module: Dotted module name. Must be one `WITHHELD_MODULES` names, so
            this can never be used to excuse an ordinary broken import.

    Returns:
        True when the module is importable here.

    Raises:
        ValueError: If `module` is not a withheld module.
    """
    if module not in WITHHELD_MODULES:
        raise ValueError(
            f"{module!r} is not withheld. Only {sorted(WITHHELD_MODULES)} may "
            f"turn a failure into a skip; everything else is a real defect.")
    return importlib.util.find_spec(module) is not None


def _guard(module: str) -> pytest.MarkDecorator:
    """Build the skip mark for one withheld module.

    Args:
        module: Dotted module name.

    Returns:
        A `skipif` mark whose reason says what did not run, and that it is not
        a pass.
    """
    return pytest.mark.skipif(
        not present(module),
        reason=(f"{module} is withheld from this clone, so this did not run. "
                f"NOT a pass -- run it where the key lives."))


#: Needs the held-out prevalence/identification key.
needs_prevalence_key = _guard(PREVALENCE_KEY)

#: Needs the held-out leak-fact and platform-name key.
needs_leak_facts = _guard(LEAK_FACTS)

#: True when this clone holds both keys, so a whole-suite claim can say so.
WITHHELD_PRESENT = all(present(m) for m in (PREVALENCE_KEY, LEAK_FACTS))
