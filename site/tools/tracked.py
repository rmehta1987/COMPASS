"""Step 6 — every file the page loads is tracked by git.

``main`` ignores ``*.json``. An artefact that is ignored works from a local
checkout and serves empty from Pages, and ``git status`` shows nothing. For
every loaded artefact and every page, ``git ls-files --error-unmatch`` must
succeed, and ``git check-ignore`` must not match.
"""
from __future__ import annotations

import subprocess

from common import REPO, SITE, fail, loaded_artefacts, ok, pages


def git(*args: str) -> int:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True).returncode


def main() -> None:
    files = [str(p.relative_to(REPO)) for p in pages()] + \
            [str((SITE / a).relative_to(REPO)) for a in loaded_artefacts()]
    problems: list[str] = []
    for f in files:
        if git("check-ignore", "-q", f) == 0:
            problems.append(f"{f} matches a .gitignore rule")
        if git("ls-files", "--error-unmatch", f) != 0:
            problems.append(f"{f} is not tracked (git add it)")
    if problems:
        for s in problems:
            print("      " + s)
        fail(f"tracked: {len(problems)} problem(s)")
    ok(f"tracked: {len(files)} file(s) tracked and not ignored")


if __name__ == "__main__":
    main()
