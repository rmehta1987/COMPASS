# ATTEMPTS
(one entry per red check.sh: date · item · attempt n/3 · what was tried · which step went red · why)
- 2026-09-04 · item 12 · attempt 1/3 · pipeline/ledger.py append-only JSONL + summary + verify · RED at step 2 (pytest): verify() built Ledger(run_dir) whose run_id defaulted to the directory name while rows carried the run_id they were written with, so a run whose id differs from its directory name never verifies · approach for attempt 2: the ledger's run_id is read from its rows when they exist; the directory name is only the default for a new ledger; verify checks all rows agree
