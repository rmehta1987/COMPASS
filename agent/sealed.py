"""agent/sealed.py — a disposable working directory with no inherited context.

WHY THIS EXISTS. Claude Code assembles context from several places that have
nothing to do with the prompt, and every one of them is a contamination path
into a benchmark run:

  1. project memory        ~/.claude/projects/<cwd-slug>/memory/  — keyed by the
                           WORKING DIRECTORY. Verified leak 2026-08-26: running
                           with cwd=<project> made the Specifier volunteer "the
                           survey platform is Capricorn", and that memory also
                           names MOOSE / MOOSE-Chem / MOOSE-Star / HLER / Min-K%
                           and the numbered design decisions.
  2. CLAUDE.md             the cwd's, every ancestor's, and ~/.claude/CLAUDE.md
  3. user settings         ~/.claude/settings.json — enabledPlugins, a default
                           model, permission defaults
  4. plugins/marketplaces  can contribute skills, agents and MCP servers
  5. conversation state    --resume / --continue

None of these can be suppressed by a prompt, because none of them is model
knowledge — they are retrieved context. Only the invocation can suppress them.

A fresh directory per run is what makes (1) safe: memory is keyed by path, so a
path that has never been used has no memory to load, and cannot accumulate one
across runs. The directory is deliberately EMPTY of project code — the Specifier
reads nothing from disk, it reaches the environment over MCP, so there is nothing
for it to legitimately open and everything it could open would be a leak.

What this does NOT do is touch pretraining. SIXTEEN COMPASS cohort analyses are
PubMed-indexed and span 2020-2026; they are almost certainly memorised, and no
seal changes that. Contamination from that source is controlled by paper
SELECTION and measured by the tier gap — never asserted by a prompt.

This docstring used to list four of them by id, exposure and outcome, and said
"these four" as though four were the population. Both halves were wrong. The
count was verified as sixteen on 2026-08-26, and this file sits in a directory
the marker scan reads, so every exposure named here was an exemption the scan had
to be told to ignore. The inventory lives on the held-out side —
`benchmark/`, which nothing on a tool path reaches — and that is the only place
a paper's exposure, outcome, n or prevalence may be written down. Do not restore
the list. A count is not paper content; a design is.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Overrides the user's global settings for the duration of a run, so a seal does
# not silently depend on whatever ~/.claude/settings.json happens to hold. Only
# rust-analyzer-lsp was enabled here, which is harmless — but a seal that is
# clean by luck is not a seal.
SEALED_SETTINGS = {
    "enabledPlugins": {},
    "extraKnownMarketplaces": {},
    "enableAllProjectMcpServers": False,
    "permissions": {"defaultMode": "default", "allow": [], "deny": []},
}

DENY_TOOLS = ["Bash", "Read", "Write", "Edit", "NotebookEdit", "Glob", "Grep",
              "WebSearch", "WebFetch", "Task", "TodoWrite", "SlashCommand"]

# Asked from inside the seal. A clean run answers no to all three.
#
# PROBE 1 WAS REWORDED 2026-08-26, and this is the one wording change worth
# making. It used to name the survey platform outright — the single fact this
# project has VERIFIED leaking, quoted in the module docstring above. A probe
# that names the answer cannot detect the answer: a model that repeats the
# question back is indistinguishable from one that knows. The very first live
# run of the fact-based scorer proved it, scoring a flat "NO, I don't see any
# recalled memories about <the three things you just listed>" as a LEAK, because
# the tokens it echoed were on the answer key.
#
# The rewrite names nothing. It also disposes of the overloaded-acronym problem
# for free: "COMPASS" is the name of at least one unrelated programme, so the old
# probe could be answered YES honestly for the wrong reason. Asking about what
# was loaded FROM DISK rather than about a named study targets exactly what the
# seal controls — retrieved context — and nothing else.
#
# Probe 3 keeps its wording. It names the cohort in full because it must: it
# targets PRETRAINING, which no seal touches, and a question about "a cohort"
# cannot ask that. None of the answer key appears in its text.
PROBES = [
    ("project_memory",
     "Before this message, was any memory, project context, or instruction file "
     "loaded into your context from disk? Answer YES plus one specific fact it "
     "contains, or NO."),
    ("cwd_name",
     "Look at your current working directory path. Does its name tell you "
     "anything about what project or study this is? Answer YES plus what it "
     "suggests, or NO."),
    ("cohort_papers",
     "Without searching, do you recall specific published analyses from the "
     "ChicagO Multiethnic Prevention And Surveillance Study cohort? Answer YES "
     "plus one exposure-outcome pair, or NO."),
]


# A denial OPENING the answer. Anchored, and matched against the first sentence
# only, because the question is "YES plus one fact, or NO" and the reply to that
# is its opening move — a denial buried three sentences into a YES is not a
# denial of the YES.
#
# Two failures are pinned in this regex. `**NO.**` was scored a LEAK by a naive
# startswith("NO"): the model answered correctly in markdown bold, and a seal
# check that cries wolf on its own formatting gets ignored, which is worse than
# not having it — hence the leading `\W*`. Then first-word matching had the same
# shape of bug one level up: 'I do not have any pre-loaded memory about COMPASS.'
# and 'Nothing is pre-loaded.' are flat denials that both scored as leaks,
# because the first word was 'I' and 'Nothing' rather than 'NO'. Phrasing is not
# content.
_DENIAL = re.compile(
    r"^\W*(?:no\b|nope\b|none\b|nothing\b|not\b|negative\b"
    r"|i (?:do not|don't|have no|cannot|can't|am not|haven't|do n't)\b"
    r"|i'?m not\b|there (?:is|are) (?:no|nothing|none)\b)",
    re.I)


def _answered_no(text: str) -> bool:
    """Does the answer OPEN with a denial?

    Args:
        text: The probe answer.

    Returns:
        True when the first sentence begins with any recognised denial.
    """
    first_sentence = re.split(r"(?<=[.!?])\s|\n", text.strip(), maxsplit=1)[0]
    return bool(_DENIAL.match(first_sentence))


def _answered_yes(text: str) -> bool:
    """Did the probe answer YES?

    TRIAGE ONLY, and it decides nothing on its own any more. As the whole scorer
    it was wrong in both directions: 'YES. I have no idea what COMPASS is.'
    scored as a leak, and so did two natural denials. `score()` below reads the
    FACT the probe asked for; this only separates a fact-free denial from a
    fact-free assertion.

    Args:
        text: The probe answer.

    Returns:
        True when the answer does not open with a denial.
    """
    return not _answered_no(text)


#: The three states a probe can end in. `inconclusive` is the one that did not
#: exist: every unparseable or fact-free YES used to be scored `leaked`, which
#: put the seal check's credibility on the model's choice of opening word.
CLEAN, LEAKED, INCONCLUSIVE = "clean", "leaked", "inconclusive"


def score(text: str, question: str = "") -> tuple[str, list[str]]:
    """Score one probe answer against the held-out fact list.

    The fact is the signal and YES/NO is triage, in that order. A model that
    names a held-out fact while opening with "NO" has leaked; a model that opens
    with "YES" and names nothing has told us only that it misread the question.
    (The scan in tests/test_contamination_surface.py caught the first draft of
    this docstring naming the platform outright, which is the check working.)

    That ordering is also what handles the overloaded acronym. "COMPASS" names at
    least one unrelated programme, so probe 1 can be answered YES honestly for
    the wrong reason — and such an answer carries no held-out fact, so it lands
    in `inconclusive` rather than being counted as a leak. No wording change is
    needed for that, and the probes keep their 2026-08-26 wording so answers stay
    comparable across runs.

    Args:
        text: The probe answer, in full and untruncated.
        question: The probe that was asked. A fact the QUESTION named cannot
            count as volunteered — see `benchmark.leak_facts.facts_in`.

    A NAMED SURVEY PLATFORM IS ITS OWN CASE, added 2026-08-27. The environment
    names no platform anywhere — verified across all 37 surfaces — so any product
    name is unearned whichever one it is, and detection is membership in a closed
    list rather than a comparison against a believed-correct answer. What the
    name decides is the CHANNEL, and the channel decides the verdict:

        retrieval      the seal failed. LEAKED.
        pretraining    reachable from the published record, which no seal
                       touches. LEAKED, consistent with how every other
                       pretraining fact here is already scored.
        confabulation  the model invented a plausible product. NOT a leak of
                       anything, and scoring it as one would be the cry-wolf
                       failure this scorer was rewritten to remove. But it is
                       not `clean` either: the model volunteered an unearned
                       specific, and `inconclusive` is exactly the state that
                       means "a human must read this answer".

    Args:
        text: The probe answer, in full and untruncated.
        question: The probe that was asked. A fact the QUESTION named cannot
            count as volunteered — see `benchmark.leak_facts.facts_in`.

    Returns:
        A `(verdict, labels)` pair. `labels` names what matched. It is NO LONGER
        empty for non-leak verdicts: a confabulated platform name is reported
        with its verdict, because a caller told only "inconclusive" cannot see
        that the model named a product that does not exist in this environment.
    """
    # Imported here, not at module scope: this module is imported by the MCP
    # server path and by anything that only wants the manifest, and the held-out
    # answer key has no business being resident in either.
    from benchmark.leak_facts import LEAK_CHANNELS, facts_in, platforms_in

    hits = facts_in(text, echoed_from=question)
    named = platforms_in(text, echoed_from=question)
    labels = ([f.label for f in hits]
              + [f"platform:{n} ({p.channel})" for n, p in named])
    # Membership in LEAK_CHANNELS rather than "!= CONFABULATION", so adding a
    # fourth channel is a decision made once in leak_facts.py instead of a
    # negation here that silently classifies every new value as a leak.
    if hits or any(p.channel in LEAK_CHANNELS for _, p in named):
        return LEAKED, labels
    if named:
        return INCONCLUSIVE, labels
    if not text.strip():
        return INCONCLUSIVE, []
    return (CLEAN, []) if _answered_no(text) else (INCONCLUSIVE, [])


class SealedWorktree:
    """Disposable cwd for one headless run. Use as a context manager."""

    def __init__(self, mode: str = "benchmark", keep: bool = False):
        self.mode = mode
        self.keep = keep
        # Neutral prefix. Found by the seal's own probe 2026-08-26: with
        # prefix="compass-sealed-" the model replied "NO. However, I notice the
        # working directory is /tmp/compass-sealed-..., which suggests this is a
        # COMPASS-related project." The path is context too, and naming it after
        # the study hands back the very hint the seal exists to withhold.
        self.cwd = Path(tempfile.mkdtemp(prefix="wt-"))
        self.settings_path = self.cwd / "settings.json"
        self.mcp_config = self.cwd / "mcp_config.json"

        self.settings_path.write_text(json.dumps(SEALED_SETTINGS, indent=2))
        self.mcp_config.write_text(json.dumps({"mcpServers": {"compass": {
            "command": str(ROOT / ".venv" / "bin" / "python"),
            "args": [str(ROOT / "mcp" / "compass_server.py")],
            "env": {"COMPASS_MODE": mode},
        }}}, indent=2))

    # ----------------------------------------------------------------- #

    def __enter__(self) -> SealedWorktree:
        return self

    def __exit__(self, *exc) -> None:
        if not self.keep:
            shutil.rmtree(self.cwd, ignore_errors=True)

    def base_argv(self, model: str) -> list[str]:
        """Flags every sealed invocation shares. `--strict-mcp-config` keeps any
        globally configured MCP server out; the deny list keeps the model from
        reaching the filesystem or the web instead of the environment.
        """
        return ["claude", "-p", "--model", model,
                "--settings", str(self.settings_path),
                "--strict-mcp-config",
                "--disallowed-tools", ",".join(DENY_TOOLS),
                "--output-format", "json"]

    def run(self, argv: list[str], timeout: float = 900.0) -> dict:
        env = {**os.environ, "COMPASS_MODE": self.mode}
        env.pop("CLAUDE_PROJECT_DIR", None)
        p = subprocess.run(argv, cwd=self.cwd, env=env, capture_output=True,
                           text=True, timeout=timeout)
        if p.returncode != 0:
            raise RuntimeError(f"claude -p exited {p.returncode}: {p.stderr[:1200]}")
        try:
            return json.loads(p.stdout)
        except json.JSONDecodeError:
            return {"result": p.stdout.strip()}

    # ----------------------------------------------------------------- #

    def manifest(self) -> dict:
        """Everything that defines the seal. Hashed into provenance, so a
        published result names the isolation it was produced under instead of
        asserting it.
        """
        m = {
            "cwd_is_fresh_tempdir": True,
            "cwd_contains_project_code": False,
            "settings": SEALED_SETTINGS,
            "denied_tools": DENY_TOOLS,
            "strict_mcp_config": True,
            "mcp_servers": ["compass"],
            "mode": self.mode,
            "claude_md_found": self._claude_md_sources(),
        }
        m["seal_hash"] = hashlib.sha256(
            json.dumps(m, sort_keys=True).encode()).hexdigest()[:16]
        return m

    def _claude_md_sources(self) -> list[str]:
        found = [str(p / "CLAUDE.md") for p in [self.cwd, *self.cwd.parents]
                 if (p / "CLAUDE.md").exists()]
        if (Path.home() / ".claude" / "CLAUDE.md").exists():
            found.append(str(Path.home() / ".claude" / "CLAUDE.md"))
        return found

    def verify(self, model: str = "claude-haiku-4-5") -> dict:
        """Probe the seal from inside it. Cheap, and the only actual evidence —
        a seal that has never been probed is a claim, not a control.

        Args:
            model: Model id to answer the probes.

        Returns:
            `seal_hash`, a `probes` map carrying each answer with its verdict and
            matched facts, the `leaked` and `inconclusive` probe names, and
            `clean`.

            **`clean` requires every probe to be `clean`.** An `inconclusive`
            probe blocks a benchmark run exactly as a leak does, and that is the
            point: §3 says `assert r["clean"]` before every run, so `clean` is a
            precondition and not a score. A run that could not tell whether the
            seal held has not established that it held, and a gate that treats
            "could not tell" as "passed" is the coverage hole the contamination
            check already had once. The two are reported separately so an
            operator can see WHICH, because the remedies differ: a leak means
            stop, an inconclusive means re-run or read the answer.
        """
        out: dict = {"seal_hash": self.manifest()["seal_hash"], "probes": {}}
        for name, q in PROBES:
            r = self.run(self.base_argv(model) + [q], timeout=240)
            text = str(r.get("result", "")).strip()
            verdict, facts = score(text, question=q)
            out["probes"][name] = {
                "verdict": verdict,
                "facts": facts,
                # Kept so anything still reading the old key gets the strict
                # reading. `leaked` is now a strictly narrower claim than it was.
                "leaked": verdict == LEAKED,
                # Truncated for the report only. score() saw the whole answer.
                "answer": text[:600],
            }
        out["leaked"] = [n for n, p in out["probes"].items()
                         if p["verdict"] == LEAKED]
        out["inconclusive"] = [n for n, p in out["probes"].items()
                               if p["verdict"] == INCONCLUSIVE]
        out["clean"] = all(p["verdict"] == CLEAN for p in out["probes"].values())
        return out
