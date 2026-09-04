"""Which strata of the instrument the retrieval benchmark never measured.

The 224-row fixture covers eleven of the sixteen strata `src/char_strata.py`
assigns to targets. Four have zero gold rows: SES/employment, insurance/access,
cancer screening and demographics, 61 targets across 51 constructs, and they are
exactly the mediators a disparities hypothesis is built on. Retrieval quality
there is unknown, not poor, and a limitation that lives only in a document gets
discovered by whoever reads a proposal built on it. So the record carries it:
every `Hit` names its stratum and says whether the benchmark measured it.

The stratum rule is reused, not restated: `src/char_strata.py` holds the
priority-ordered keyword classifier over the target's cleaned stem, committed
there so the grouping is auditable. It is loaded by path because `src/` is the
retrieval experiments' tree and is outside this package's lint and type scope.
"""

from __future__ import annotations

import importlib.util
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CLASSIFIER = ROOT / "src" / "char_strata.py"
PREREG = ROOT / "out" / "qx_preregistration.json"


def load_domain_of() -> Any:
    """The committed stratum classifier, `domain_of(stem) -> str`.

    Returns:
        The function.
    """
    spec = importlib.util.spec_from_file_location("compass_char_strata", CLASSIFIER)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {CLASSIFIER}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.domain_of


def gold_keys(prereg: Path = PREREG) -> list[str]:
    """The gold keys of the pre-registered positives.

    Args:
        prereg: The tracked pre-registration file.

    Returns:
        One key per positive row, in file order.
    """
    return [str(r["gold_key"]) for r in json.loads(prereg.read_text())["positives"]]


@dataclass(frozen=True)
class Strata:
    """Stratum per target, and which strata the fixture measured.

    Attributes:
        stratum_of: Target id to stratum name.
        rows_per_stratum: Fixture rows whose gold target falls in each stratum.
        targets_per_stratum: Targets in each stratum.
        constructs_per_stratum: Distinct constructs in each stratum.
    """

    stratum_of: dict[int, str]
    rows_per_stratum: dict[str, int]
    targets_per_stratum: dict[str, int]
    constructs_per_stratum: dict[str, int]

    @classmethod
    def from_targets(cls, targets: list[dict[str, Any]],
                     keys: list[str]) -> Strata:
        """Classify every target and count fixture rows per stratum.

        Args:
            targets: The bundle's target rows (need `target_id`, `stem`,
                `construct_key`, `members`).
            keys: Gold keys of the fixture's positives. A key that no target
                folds is ignored: a fake or partial target set must still work.

        Returns:
            The strata.
        """
        domain_of = load_domain_of()
        stratum = {int(t["target_id"]): str(domain_of(t.get("stem", "")))
                   for t in targets}
        by_key = {m: int(t["target_id"]) for t in targets for m in t["members"]}
        rows = Counter(stratum[by_key[k]] for k in keys if k in by_key)
        n_targets = Counter(stratum.values())
        constructs: dict[str, set[str]] = defaultdict(set)
        for t in targets:
            constructs[stratum[int(t["target_id"])]].add(str(t["construct_key"]))
        return cls(stratum_of=stratum, rows_per_stratum=dict(rows),
                   targets_per_stratum=dict(n_targets),
                   constructs_per_stratum={s: len(c) for s, c in constructs.items()})

    @classmethod
    def from_retriever(cls, retriever: Any, prereg: Path = PREREG) -> Strata:
        """Build from a loaded bundle and the tracked pre-registration file.

        Args:
            retriever: Anything with a `targets` list.
            prereg: The pre-registration file.

        Returns:
            The strata.
        """
        return cls.from_targets(retriever.targets, gold_keys(prereg))

    def unmeasured(self) -> frozenset[str]:
        """Strata with zero fixture rows.

        Returns:
            Their names.
        """
        return frozenset(s for s in self.targets_per_stratum
                         if self.rows_per_stratum.get(s, 0) == 0)

    def of(self, target_id: int) -> tuple[str, bool]:
        """A target's stratum and whether the benchmark left it unmeasured.

        Args:
            target_id: The bundle's target id.

        Returns:
            `(stratum, unmeasured_stratum)`.
        """
        s = self.stratum_of[int(target_id)]
        return s, self.rows_per_stratum.get(s, 0) == 0
