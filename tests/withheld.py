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
DESIGN_KEY = "benchmark.design_key"


def _importable(module: str) -> bool:
    """Whether a module can be imported here. No validation, on purpose.

    The guards below are built at import time, so anything that can raise here
    costs every test in every file that imports this module -- 98 of them, as
    three collection errors naming this file rather than the defect. So the
    "is it really withheld?" check lives in `tests/test_withheld.py`, where its
    red state costs one test and names what drifted. `present` is the
    validating form, for callers that want the error.

    Args:
        module: Dotted module name.

    Returns:
        True when the module is importable.
    """
    return importlib.util.find_spec(module) is not None


def present(module: str) -> bool:
    """Whether a WITHHELD module can be imported in this clone.

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
    return _importable(module)


def _guard(module: str) -> pytest.MarkDecorator:
    """Build the skip mark for one withheld module.

    Args:
        module: Dotted module name.

    Returns:
        A `skipif` mark whose reason says what did not run, and that it is not
        a pass.
    """
    return pytest.mark.skipif(
        not _importable(module),
        reason=(f"{module} is withheld from this clone, so this did not run. "
                f"NOT a pass -- run it where the key lives."))


#: Needs the held-out prevalence/identification key.
needs_prevalence_key = _guard(PREVALENCE_KEY)

#: Needs the held-out leak-fact and platform-name key.
needs_leak_facts = _guard(LEAK_FACTS)

#: Needs the held-out design-arrow key (C36) -- one row per paper, both sides.
#: A test wanting this AND the prevalence key carries two decorations and counts
#: twice against `GUARD_CEILING`, which is the right cost: since C36 the design
#: key is the only reader for design, so a test needing both is usually reading
#: the prevalence key for something it no longer owns.
needs_design_key = _guard(DESIGN_KEY)

#: Every module a guard here may name. `tests/test_withheld.py` asserts this
#: against `WITHHELD_MODULES` in BOTH directions, so a guard cannot come to name
#: a module the contamination gate does not hold out -- an unconditional skip
#: wearing a condition -- and a withheld module cannot come to have no guard,
#: which is how a test that needs a key ends up permanently red here instead.
#: Listed rather than derived from `WITHHELD_MODULES` on purpose: deriving it
#: would make both of those tests true by construction and therefore vacuous.
GUARDED_MODULES = (PREVALENCE_KEY, LEAK_FACTS, DESIGN_KEY)
