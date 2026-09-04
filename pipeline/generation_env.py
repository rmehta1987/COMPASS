"""Where and how an artefact was generated, measured by machine.

Every emitted hypothesis is stamped with the state of the clone that produced
it: whether the answer key was present in the tree, whether the `scoring-key`
ref was reachable from `.git`, the pushed sha, whether the tree was clean, and
the branch. The scoring harness refuses an artefact whose `key_present` or
`key_fetchable` is true, the same way the retriever refuses a hash mismatch.

`key_fetchable` is true when the ref exists locally or as a remote-tracking
ref, when the key's blob is reachable at `scoring-key:benchmark/
prevalence_key.py`, or when `remote.origin.fetch` is a wildcard refspec that a
later `git fetch` could pull the branch through. A `--single-branch` clone
pins the refspec to one branch, which is what makes `false` provable rather
than dependent on garbage collection having run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

KEY_PATH = Path("benchmark") / "prevalence_key.py"
KEY_BRANCH = "scoring-key"


class GenerationEnv(BaseModel):
    """The generation clone's state at stamping time.

    Attributes:
        key_present: `benchmark/prevalence_key.py` existed in the tree.
        key_fetchable: The `scoring-key` ref was present in `.git`, or a
            wildcard fetch refspec could pull it in.
        tree_sha: HEAD's full sha; must exist on the remote, so stamp after
            the push.
        tree_clean: `git status --porcelain` was empty.
        branch: The checked-out branch.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    key_present: bool
    key_fetchable: bool
    tree_sha: str = Field(min_length=7)
    tree_clean: bool
    branch: str = Field(min_length=1)

    @property
    def clean_for_scoring(self) -> bool:
        """True when a scorer may accept an artefact stamped with this.

        Returns:
            Neither the key nor its ref was reachable.
        """
        return not (self.key_present or self.key_fetchable)


def _git(repo: Path, *args: str) -> tuple[int, str]:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def key_fetchable(repo: Path) -> bool:
    """Measure whether the answer key's branch is reachable from this clone.

    Args:
        repo: The clone's root.

    Returns:
        See the module docstring.
    """
    rc, refs = _git(repo, "for-each-ref", "--format=%(refname)",
                    f"refs/heads/{KEY_BRANCH}", f"refs/remotes/*/{KEY_BRANCH}")
    if rc == 0 and refs:
        return True
    rc, _ = _git(repo, "cat-file", "-e", f"{KEY_BRANCH}:{KEY_PATH.as_posix()}")
    if rc == 0:
        return True
    rc, specs = _git(repo, "config", "--get-all", "remote.origin.fetch")
    return rc == 0 and any("*" in s for s in specs.splitlines())


def stamp(repo: Path, *, require_pushed: bool = False) -> GenerationEnv:
    """Measure the clone and build the stamp.

    Args:
        repo: The clone's root.
        require_pushed: Refuse to stamp a sha the remote does not have.

    Returns:
        The stamp.

    Raises:
        RuntimeError: When `repo` is not a git checkout, or `require_pushed`
            is set and HEAD is not contained in `origin/<branch>`.
    """
    rc, sha = _git(repo, "rev-parse", "HEAD")
    if rc != 0 or not sha:
        raise RuntimeError(f"{repo} is not a git checkout")
    _, branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _, status = _git(repo, "status", "--porcelain")
    if require_pushed:
        rc, _ = _git(repo, "merge-base", "--is-ancestor", sha, f"origin/{branch}")
        if rc != 0:
            raise RuntimeError(f"HEAD {sha[:12]} is not on origin/{branch}; push first")
    return GenerationEnv(key_present=(repo / KEY_PATH).exists(),
                         key_fetchable=key_fetchable(repo), tree_sha=sha,
                         tree_clean=(status == ""), branch=branch)
