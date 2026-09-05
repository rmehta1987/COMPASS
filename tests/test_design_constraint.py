"""The design constraint reaches the model before the roles do (brief 2, item 1).

The baseline run b3-20260904 lost 11 of 39 records to validator:temporality,
18 mediator and 2 descendant critiques under a cross-sectional design. The
validator is right and unchanged; the prompt now states the constraint before
the role table, so the model decides the design first.
"""

from __future__ import annotations

from agent.schema import CausalRole
from agent.specifier import SYSTEM


def test_the_constraint_precedes_the_role_table_and_names_the_rejected_roles():
    i = SYSTEM.index("Decide the design BEFORE you assign any role")
    j = SYSTEM.index("Each list accepts only certain roles")
    k = SYSTEM.index("adjusted", j)              # the rendered role table
    assert i < j < k
    para = SYSTEM[i:j]
    for role in (CausalRole.mediator, CausalRole.descendant_of_exposure,
                 CausalRole.confounder_or_mediator):
        assert role.value in para, role
    assert "cross-sectional" in para and "`unadjudicated`" in para
    assert "repeated measure" in para


def test_the_constraint_carries_no_study_content():
    i = SYSTEM.index("Decide the design BEFORE")
    j = SYSTEM.index("Each list accepts only certain roles")
    para = SYSTEM[i:j].lower()
    for banned in ("hypertension", "diabetes", "cancer", "pmid", "prevalence", "%"):
        assert banned not in para, banned
