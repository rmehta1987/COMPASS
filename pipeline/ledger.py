"""The run ledger: one row per hypothesis generated, whether or not it shipped.

A match rate needs a denominator, and "40% on 20 hypotheses" and "40% on
2,000" are different results. The ledger is where the denominator lives:
every pair the run took past the gate gets a row, including the ones the
Specifier refused, the samples that produced no valid record, and the ones a
later validator discards. `total_generated_this_run` is never stored as a
number of its own; it is the row count, and `verify()` fails if a summary
claims otherwise.

Append-only, JSON lines, one file per run. Rows carry the strata of both
anchors so a baseline scored under D1 = narrow can be compared with a later
run on the same strata rather than on a different scope. The run id lives in
the rows: a ledger opened on an existing file takes its id from them, and the
directory name only seeds a new one.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

OUTCOMES = ("emitted", "refused", "no_valid_record", "gate_blocked", "discarded")
LEDGER_NAME = "ledger.jsonl"
SUMMARY_NAME = "summary.json"


class LedgerRow(BaseModel):
    """One generated hypothesis, or one attempt that produced none.

    Attributes:
        run_id: The run this row belongs to.
        seq: 0-based position in the ledger; contiguous by construction.
        pair_id: The pair's id.
        exposure_key: The exposure anchor's dictionary construct key.
        outcome_key: The outcome anchor's dictionary construct key.
        exposure_stratum: From the exposure record's hit.
        outcome_stratum: From the outcome record's hit.
        estimability: The gate's verdict the pair carried.
        outcome: One of `OUTCOMES`.
        protocol_id: The record's id when one was selected.
        record_hash: Its hash.
        artefact: Path of the written artefact, relative to the run directory.
        note: Free text: the refusal reason, the validator that discarded it.
        at: UTC timestamp, ISO 8601.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    seq: int = Field(ge=0)
    pair_id: str = Field(min_length=1)
    exposure_key: str = Field(min_length=1)
    outcome_key: str = Field(min_length=1)
    exposure_stratum: str = Field(min_length=1)
    outcome_stratum: str = Field(min_length=1)
    estimability: str = Field(min_length=1)
    outcome: str = Field(pattern="^(" + "|".join(OUTCOMES) + ")$")
    protocol_id: str | None = None
    record_hash: str | None = None
    artefact: str | None = None
    note: str = ""
    at: str = Field(min_length=1)


class RunSummary(BaseModel):
    """What a run produced, derived from its rows and nothing else.

    Attributes:
        run_id: The run.
        total_generated_this_run: The row count, including every discard.
        by_outcome: Rows per outcome.
        strata: Every stratum an anchor fell in, sorted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    total_generated_this_run: int = Field(ge=0)
    by_outcome: dict[str, int]
    strata: tuple[str, ...]


def read_rows(path: Path) -> list[LedgerRow]:
    """Every row in a ledger file, in order.

    Args:
        path: The `ledger.jsonl` file.

    Returns:
        The rows; empty when the file does not exist yet.
    """
    if not path.exists():
        return []
    return [LedgerRow.model_validate_json(line)
            for line in path.read_text().splitlines() if line.strip()]


class Ledger:
    """An append-only ledger for one run.

    Args:
        run_dir: The run's directory; the ledger is `run_dir/ledger.jsonl`.
        run_id: The id for a NEW ledger; defaults to the directory name. An
            existing ledger's id is read from its rows, and a different
            `run_id` is refused rather than silently mixed in.

    Raises:
        ValueError: When `run_id` disagrees with an existing ledger's rows.
    """

    def __init__(self, run_dir: Path, run_id: str | None = None) -> None:
        """Bind to a run directory; nothing is written until `append`."""
        self.run_dir = Path(run_dir)
        self.path = self.run_dir / LEDGER_NAME
        existing = read_rows(self.path)
        if existing:
            found = existing[0].run_id
            if run_id is not None and run_id != found:
                raise ValueError(f"ledger at {self.path} belongs to run {found!r}, "
                                 f"not {run_id!r}")
            self.run_id = found
        else:
            self.run_id = run_id or self.run_dir.name

    def rows(self) -> list[LedgerRow]:
        """Every row on disk, in order.

        Returns:
            The rows; empty when the file does not exist yet.
        """
        return read_rows(self.path)

    def append(self, *, pair_id: str, exposure_key: str, outcome_key: str,
               exposure_stratum: str, outcome_stratum: str, estimability: str,
               outcome: str, protocol_id: str | None = None,
               record_hash: str | None = None, artefact: str | None = None,
               note: str = "") -> LedgerRow:
        """Write one row at the end of the file.

        Args:
            pair_id: The pair's id.
            exposure_key: Exposure construct key.
            outcome_key: Outcome construct key.
            exposure_stratum: Exposure stratum.
            outcome_stratum: Outcome stratum.
            estimability: The gate's verdict.
            outcome: One of `OUTCOMES`.
            protocol_id: When a record was selected.
            record_hash: Likewise.
            artefact: Relative path of the artefact written, if any.
            note: Why, when the outcome is not `emitted`.

        Returns:
            The row written. `seq` is the current row count, so the file's
            length is the only counter.
        """
        row = LedgerRow(run_id=self.run_id, seq=len(self.rows()), pair_id=pair_id,
                        exposure_key=exposure_key, outcome_key=outcome_key,
                        exposure_stratum=exposure_stratum,
                        outcome_stratum=outcome_stratum, estimability=estimability,
                        outcome=outcome, protocol_id=protocol_id,
                        record_hash=record_hash, artefact=artefact, note=note,
                        at=datetime.now(UTC).isoformat(timespec="seconds"))
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(row.model_dump_json() + "\n")
        return row

    def summary(self) -> RunSummary:
        """Derive the summary from the rows.

        Returns:
            The summary; `total_generated_this_run` is `len(rows())`.
        """
        rows = self.rows()
        strata = sorted({r.exposure_stratum for r in rows}
                        | {r.outcome_stratum for r in rows})
        return RunSummary(run_id=self.run_id, total_generated_this_run=len(rows),
                          by_outcome=dict(Counter(r.outcome for r in rows)),
                          strata=tuple(strata))

    def write_summary(self) -> Path:
        """Write `summary.json` beside the ledger.

        Returns:
            The path written.
        """
        out = self.run_dir / SUMMARY_NAME
        out.write_text(self.summary().model_dump_json(indent=2) + "\n")
        return out


def verify(run_dir: Path) -> RunSummary:
    """Check a run directory's summary against its ledger.

    Args:
        run_dir: The run's directory.

    Returns:
        The summary derived from the rows.

    Raises:
        ValueError: When the rows are not contiguous or do not share one run
            id, the summary file is missing, or it disagrees with the rows.
    """
    ledger = Ledger(run_dir)
    rows = ledger.rows()
    for i, r in enumerate(rows):
        if r.seq != i:
            raise ValueError(f"row {i} carries seq {r.seq}: the ledger was edited")
        if r.run_id != ledger.run_id:
            raise ValueError(f"row {i} belongs to run {r.run_id!r}, not "
                             f"{ledger.run_id!r}")
    derived = ledger.summary()
    stored_path = Path(run_dir) / SUMMARY_NAME
    if not stored_path.exists():
        raise ValueError(f"{stored_path} is missing; write_summary() was not run")
    stored = RunSummary.model_validate_json(stored_path.read_text())
    if stored != derived:
        raise ValueError(
            f"summary disagrees with the ledger: stored total "
            f"{stored.total_generated_this_run}, rows {derived.total_generated_this_run}"
            f"; stored by_outcome {stored.by_outcome}, rows {derived.by_outcome}")
    return derived


def main(argv: list[str] | None = None) -> int:
    """`verify RUN_DIR`: exit 0 when the summary matches the ledger.

    Args:
        argv: Arguments; `sys.argv[1:]` when None.

    Returns:
        Process exit code.
    """
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", type=Path)
    a = ap.parse_args(argv)
    try:
        s = verify(a.run_dir)
    except ValueError as e:
        print(f"ledger: {e}")
        return 1
    print(f"ledger {a.run_dir}: total_generated_this_run {s.total_generated_this_run} "
          f"{json.dumps(s.by_outcome, sort_keys=True)} strata {list(s.strata)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
