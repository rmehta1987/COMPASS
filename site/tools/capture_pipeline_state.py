"""Items 7 and 10 — capture the funnel gate's real output and the GenerationEnv stamp.

Read-only against the generation clone (``COMPASS_GEN``, default
``/home/mehta5/compass-gen``): imports its ``pipeline`` package, runs the
same functions its CLI runs, and writes the raw result to ``run/site/`` here.
Nothing is written into the generation clone. Run with that clone's venv so
its dependencies resolve::

    /home/mehta5/compass-gen/.venv/bin/python site/tools/capture_pipeline_state.py
"""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GEN = Path(os.environ.get("COMPASS_GEN", "/home/mehta5/compass-gen")).resolve()


def main() -> int:
    sys.path.insert(0, str(GEN))
    os.chdir(GEN)  # the pipeline resolves build/ relative to its root
    from pipeline.auto_intake import worked_frame
    from pipeline.gate import MISSING_EXPORTS, gate
    from pipeline.generation_env import stamp

    live, extra = worked_frame()
    res = gate(live, allow_unestimable=False)
    env = stamp(GEN)
    head = subprocess.run(["git", "-C", str(GEN), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    def plain(o):  # noqa: ANN001, ANN202
        if dataclasses.is_dataclass(o):
            return {f.name: plain(getattr(o, f.name)) for f in dataclasses.fields(o)}
        if isinstance(o, (list, tuple)):
            return [plain(x) for x in o]
        if isinstance(o, dict):
            return {str(k): plain(v) for k, v in o.items()}
        if hasattr(o, "model_dump"):
            return o.model_dump()
        return o if isinstance(o, (str, int, float, bool)) or o is None else repr(o)

    raw = {
        "captured": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generation_clone_head": head,
        "worked_frame_extra": plain(extra),
        "live_type": type(live).__name__, "n_live": len(live),
        "live_sample": plain(live[:2]) if isinstance(live, (list, tuple)) else plain(live),
        "gate_result_fields": [f.name for f in dataclasses.fields(res)] if dataclasses.is_dataclass(res) else list(vars(res)),
        "gate": plain(res),
        "missing_exports_expected": list(MISSING_EXPORTS),
        "generation_env": env.model_dump(),
        "clean_for_scoring": env.clean_for_scoring,
    }
    out = REPO / "run" / "site" / "pipeline_state.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(raw, indent=1, default=str) + "\n")
    print(f"wrote {out.relative_to(REPO)}  live {len(live)}  passed {len(res.passed)}  blocked {len(res.blocked)}  missing {res.missing_exports}  env {env.model_dump()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
