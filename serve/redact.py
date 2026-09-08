"""Keep the withheld instrument out of anything the browser receives.

The retriever answers with instrument content by design: `_hit` carries `stem`,
`option`, the variable `key` and the roster `members`, and a `Cited` label in a
record carries `question_text` byte for byte. That is correct inside the
pipeline and wrong on a socket — `README.md` §What is withheld lists the
codebooks, `targets.json` and the fixtures as not cleared for release, direct
identifiers included, and `site/tools/no_instrument.py` exists to prove that
none of it reaches `site/`. An endpoint that answers queries one at a time
walks around that gate unless something stands in the way. This is that thing.

Two filters, because they fail differently:

  * STRUCTURAL (`pseudonymise_hit`) — an allowlist. A field is dropped unless
    it is named safe, so a new key in `_hit` is excluded by default rather than
    published by default.
  * TEXTUAL (`Scrubber`) — the pipeline's own five-word-run rule, applied to
    free prose where wording arrives inside a sentence the model wrote. Same
    rule as `tests/test_query_rewrite.py::test_the_prompt_carries_no_instrument_wording`
    and `site/tools/no_instrument.py`: collapse whitespace, lower-case, forbid
    any five consecutive words shared with a dictionary entry.

The textual filter REPLACES the offending field and says so in the response
rather than editing inside the sentence. A half-scrubbed sentence still reads
as a citation and hides how much leaked; a named replacement does not.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

#: Everything `deploy/retriever.py::_hit` may put on the wire. An allowlist,
#: not a denylist: `_hit` gaining a field must not publish it by default.
SAFE_HIT_FIELDS = frozenset({"cos", "margin_12", "fold_size", "n_siblings", "module"})

#: What `_hit` returns that is withheld instrument content. Named so the test
#: can assert on the intersection rather than on today's field list.
WITHHELD_HIT_FIELDS = frozenset({"key", "construct_key", "stem", "option", "members"})

#: Tier A forbids a bare variable key anywhere the browser can see it; the same
#: pattern `site/tools/no_instrument.py` scans for.
KEY_RE = re.compile(r"\bm\d+:Q\d+(?:[._~]\w+)*")

#: Words per forbidden run. The pipeline's number, not a new one.
RUN = 5

REDACTED = "[REDACTED: instrument wording]"


class DictionaryUnavailable(RuntimeError):
    """Raised when the scan cannot see the instrument it is meant to scan for.

    A scan without the dictionary certifies nothing. `site/tools/no_instrument.py`
    exits 2 rather than pass vacuously; this raises for the same reason.
    """


def _grams(text: str) -> set[tuple[str, ...]]:
    """Five-word runs of `text`, whitespace collapsed and lower-cased.

    Args:
        text: Any prose. Markup is not stripped here; the caller decides
            whether it also needs to scan a rendered form.

    Returns:
        Every `RUN`-length consecutive word tuple, as a set.
    """
    w = " ".join(text.lower().split()).split()
    return {tuple(w[i:i + RUN]) for i in range(len(w) - RUN + 1)}


def dictionary_path() -> Path | None:
    """Locate the built dictionary, preferring an explicit override.

    Returns:
        The first readable candidate, or None when the instrument is withheld
        from this tree (the public repository, where the scan cannot run).
    """
    root = Path(__file__).resolve().parent.parent
    env = os.environ.get("COMPASS_DICTIONARY")
    cands = [Path(env)] if env else []
    cands += [root / "dictionary.json", root / "build" / "dictionary.json"]
    return next((p for p in cands if p.is_file()), None)


class Pseudonymiser:
    """Stable, salted stand-ins for target ids.

    A target id is a row index into the withheld `targets.json`, so publishing
    it hands back a join key even though it carries no wording. Salting breaks
    the join for anyone without the map, and keeping the map on disk means a
    tester can still tell which target a run picked.

    Attributes:
        salt: The per-run secret. Read from `COMPASS_SERVE_SALT` when set so a
            testing session can reproduce yesterday's labels; otherwise random,
            so a forgotten endpoint does not emit stable public identifiers.
    """

    def __init__(self, salt: str | None = None) -> None:
        """Build a pseudonymiser.

        Args:
            salt: Explicit salt. Falls back to `COMPASS_SERVE_SALT`, then to a
                fresh random one.
        """
        self.salt = salt or os.environ.get("COMPASS_SERVE_SALT") or os.urandom(16).hex()
        self._map: dict[int, str] = {}

    def label(self, target_id: int) -> str:
        """The stand-in for one target.

        Args:
            target_id: The retriever's 1-based row index.

        Returns:
            A short opaque label, stable for the life of this salt.
        """
        if target_id not in self._map:
            h = hashlib.sha256(f"{self.salt}:{target_id}".encode()).hexdigest()
            self._map[target_id] = f"V{h[:6].upper()}"
        return self._map[target_id]

    def dump(self, path: Path) -> None:
        """Write the map so a tester can invert it; never served over HTTP.

        Args:
            path: Destination file. Parents are created.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"salt": self.salt, "labels": {str(k): v for k, v in self._map.items()}},
            indent=1), encoding="utf-8")


def pseudonymise_hit(hit: dict[str, Any], pseud: Pseudonymiser) -> dict[str, Any]:
    """Reduce a retriever hit to what may leave the process.

    Allowlist, deliberately. `_hit` is owned by the deploy bundle and may gain a
    field; the failure mode of a denylist here is publishing the instrument, and
    the failure mode of an allowlist is an absent number in a demo panel.

    Args:
        hit: A dict as returned by `deploy/retriever.py::CompassRetriever.search`.
        pseud: The map supplying this target's stand-in.

    Returns:
        A new dict carrying the pseudonym and the safe scalar fields only.
    """
    out: dict[str, Any] = {"target": pseud.label(int(hit["target_id"]))}
    for k in sorted(SAFE_HIT_FIELDS):
        if k in hit:
            out[k] = hit[k]
    return out


class Scrubber:
    """Refuse to emit prose that shares a five-word run with the instrument.

    Attributes:
        corpus: Every five-word run in the dictionary's three text fields.
        source: The dictionary file the corpus came from, for the health route.
    """

    def __init__(self, path: Path | None = None) -> None:
        """Load the instrument and index its five-word runs.

        Args:
            path: The dictionary. Defaults to `dictionary_path()`.

        Raises:
            DictionaryUnavailable: When no dictionary is readable. Serving
                without one would mean answering with an unchecked surface.
        """
        # `is_file` is checked for an EXPLICIT path too, not only for the
        # discovered one. A caller naming a path that does not exist is in the
        # same position as a caller naming none -- scanning nothing -- and the
        # first version raised FileNotFoundError there, which reads as a bug in
        # the caller rather than as a refusal to certify.
        p = path or dictionary_path()
        if p is None or not p.is_file():
            raise DictionaryUnavailable(
                f"no readable dictionary at {p or '<unset>'}; set "
                "COMPASS_DICTIONARY. A scan that cannot see the instrument "
                "certifies nothing, so the endpoint refuses to serve rather "
                "than serve unchecked.")
        self.source = p
        corpus: set[tuple[str, ...]] = set()
        for e in json.loads(p.read_text(encoding="utf-8"))["entries"]:
            for f in ("searchable_text", "question_text", "stem_text"):
                v = e.get(f)
                if isinstance(v, str):
                    corpus |= _grams(v)
        self.corpus = corpus

    def hits(self, text: str) -> list[str]:
        """Instrument runs and bare keys present in `text`.

        Args:
            text: Prose to check.

        Returns:
            Sorted descriptions of what was found; empty when the text is clean.
        """
        found = [f"key {k}" for k in sorted(set(KEY_RE.findall(text)))]
        found += [" ".join(g) for g in sorted(_grams(text) & self.corpus)]
        return found

    def scrub(self, obj: Any, _path: str = "") -> tuple[Any, list[str]]:
        """Walk a JSON-shaped object, replacing any string that carries wording.

        The whole string goes, not the matched run. Editing inside a sentence
        leaves something that still reads as a citation and hides how much was
        removed; a named replacement is visible in the response itself.

        Args:
            obj: Any JSON-serialisable structure.
            _path: Dotted location, used to report what was replaced.

        Returns:
            The filtered structure, and the list of paths that were replaced.
        """
        if isinstance(obj, str):
            if self.hits(obj):
                return REDACTED, [_path or "<root>"]
            return obj, []
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            marks: list[str] = []
            for k, v in obj.items():
                sub, m = self.scrub(v, f"{_path}.{k}" if _path else str(k))
                out[k] = sub
                marks += m
            return out, marks
        if isinstance(obj, list):
            vals: list[Any] = []
            marks = []
            for i, v in enumerate(obj):
                sub, m = self.scrub(v, f"{_path}[{i}]")
                vals.append(sub)
                marks += m
            return vals, marks
        return obj, []
