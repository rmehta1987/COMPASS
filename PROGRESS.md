# PROGRESS
(one line per green commit: date · item · sha · what the check proved)
- 2026-09-04 · item 1 · check.sh v1 · steps 0-6 (key unreachable, build hash pin, pytest 743 passed with 4 file ignores + 4 node-id deselects, ruff/mypy vs ceilings read from tests, retrieval_eval, smoke ALL PASS) · seeded pytest failure turned step 2 red in 6 s · 1m32s
- 2026-09-04 · item 2 · pipeline/retrieval_record.py (RequestSnapshot, Hit, RetrievalRecord; pydantic, frozen, extra=forbid) · 11 tests: JSON round trip lossless for resolved and abstained, tuples/None survive, wording fields absent, abstention invariants refuse 5 inconsistent shapes · pipeline/ added to mypy files · 754 passed, ruff 228, mypy 59 · GREEN
