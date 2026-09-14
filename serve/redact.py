"""Keep the withheld instrument out of anything the browser receives.

The retriever answers with instrument content by design: `_hit` carries `stem`,
`option`, the variable `key` and the roster `members`, and a `Cited` label in a
record carries `question_text` byte for byte. That is correct inside the
pipeline and wrong on a socket — `README.md` §What is withheld lists the
codebooks, `targets.json` and the fixtures as not cleared for release, direct
identifiers included, and `site/tools/no_instrument.py` exists to prove that
none of it reaches `site/`. An endpoint that answers queries one at a time
walks around that gate unless something stands in the way. This is that thing.

Three filters, because they fail differently and no one of them is enough:

  * STRUCTURAL, BY FIELD SET (`pseudonymise_hit`) — an allowlist over what the
    retriever returns. A field is dropped unless it is named safe, so a key
    `_hit` gains next year is excluded by default rather than published by
    default.
  * STRUCTURAL, BY FIELD NAME (`WORDING_FIELDS`) — a `Cited.wording` IS
    `question_text` byte for byte, and the textual rule below cannot see wording
    shorter than five words. Naming those fields closes that without lowering
    the run length, which the pipeline rejected as too noisy.
  * TEXTUAL (`Scrubber.hits`) — the pipeline's own five-word-run rule for prose
    where wording arrives inside a sentence the model wrote, plus the
    instrument's own key set matched literally.

Whichever fires, the WHOLE string is replaced and the path is named in
`redactions`. Editing inside a sentence leaves something that still reads as a
citation and hides how much leaked; a named replacement does not.

Four things this is known NOT to do, stated because a filter believed to be
total is worse than one whose edges are written down. The last three are why
`serve/api.py` binds loopback and why that is a property of the design rather
than a default someone may flip:

  * The five-word rule cannot see instrument text shorter than five words.
    THREE dictionary rows are (MEASURED 2026-09-08, 2,804 entries), two of them
    "List of Countries". `WORDING_FIELDS` is what covers them.
  * IT DOES NOT STOP CORRELATION, AND THE SALT DOES NOT EITHER. An earlier
    version of this paragraph claimed the salt bounds it; that was wrong. The
    allowlisted scalars are properties of the target row, not of the salt:
    `module`, `fold_size` and `n_siblings` are invariant across restarts, and
    `cos` is deterministic for a given (query, target). Record that tuple, take
    a new salt, re-issue the query, and the two labels join to one target.
  * `cos` IS A WORDING ORACLE. It is on the allowlist by design and returned at
    full precision even when the retriever abstains, so cosine against a
    candidate phrase is a per-word gradient: hill-climb it and you reconstruct
    wording no field ever printed. Rounding it would break the panel it exists
    for. Nothing here closes this; the bind address does.
  * It filters what this process SENDS. It says nothing about what the directory
    handed to `--site-dir` contains -- see `api.py::_refuse_unsafe_site_dir`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

#: Everything `deploy/retriever.py::_hit` may put on the wire. An allowlist,
#: not a denylist: `_hit` gaining a field must not publish it by default.
SAFE_HIT_FIELDS = frozenset({"cos", "margin_12", "fold_size", "n_siblings", "module"})

#: What `_hit` returns that is withheld instrument content. Named so the test
#: can assert on the intersection rather than on today's field list.
WITHHELD_HIT_FIELDS = frozenset({"key", "construct_key", "stem", "option", "members"})

#: Tier A forbids a bare variable key anywhere the browser can see it.
#:
#: Derived from the built dictionary's own `key_rule` and shape table, NOT from
#: `site/tools/no_instrument.py`, whose `m\d+:Q\d+(?:[._~]\w+)*` this started as
#: a copy of. MEASURED 2026-09-08 against `dictionary.json` (2,804 entries):
#: that pattern full-matches 1,080 keys and MISSES 1,724 -- every roster-prefixed
#: shape (`m1:1_Q6.2`, 970 + 550 rows) and every matrix shape whose qid it cannot
#: reach (`m1:Q2.9#1_1`). The shapes are `N_QN.N`, `QN.N`, `N_QN.N#N_N`,
#: `QN.N#N_N`, `QN.N_N`, `QN`, `QN_N`, `QN.N_N_TEXT`, `QN.N#N_N_N`, plus the
#: `~{occurrence}` suffix the key rule adds where a qid repeats in its module.
#: This pattern full-matches all 2,804 keys and all 1,080 construct keys.
#:
#: CASE-INSENSITIVE, and the literal sweep below case-folds both sides. Without
#: it, `M1:1_Q6.2` at the start of a sentence and `m1:1_q6.2` from a model that
#: lower-cased its own prose are missed by the regex AND by the literal set that
#: exists to back the regex up. `agent/schema.py::UnresolvedCovariate.why_rejected`
#: is free prose that asks the model to "name the keys you looked at and turned
#: down", so a case-shifted key there is reachable, not hypothetical.
KEY_RE = re.compile(
    r"\bm\d+:(?:\d+_)?Q\d+(?:\.\d+)?(?:#\d+(?:_\d+)*)?(?:_\d+)*(?:_TEXT)?(?:~\d+)?",
    re.IGNORECASE)

#: Record fields whose value is instrument text by construction. `Cited.wording`
#: is `question_text` byte for byte (`env/labels.py`), and the five-word-run rule
#: cannot see wording shorter than five words -- three dictionary rows are
#: (MEASURED 2026-09-08). Naming the field closes that on the structural side
#: instead of lowering the run length, which the pipeline rejected as too noisy.
#:
#: `stem`, `option` and `members` are the retriever's names for the same content
#: (`deploy/retriever.py::_hit`). `pseudonymise_hit`'s allowlist keeps them off
#: the retrieve path; this keeps them off EVERY OTHER path, which is what the
#: Scrubber is for. The textual rule does not cover them, MEASURED 2026-09-09
#: over the 1,353 rows of `deploy/targets.json`:
#:   - `members` -- 2,761 strings, ZERO five-word runs. Roster member names are
#:     shorter than the rule can see, so no corpus addition could ever help;
#:     structural is the only kind of cover available.
#:   - `stem` -- 12 rows carry 14 five-word runs the corpus does NOT hold. The
#:     target stem is a normalised, slightly shortened form of `stem_text`
#:     (96.5% similar on the first case), and the shortening joins words that
#:     the original kept apart, manufacturing runs no dictionary field contains.
#:   - `option` -- 440 runs, all of them already in the corpus today. It is
#:     named here anyway: that is a fact about the current build, not a
#:     guarantee, and it is the same field on the same code path as the other two.
WORDING_FIELDS = frozenset({"wording", "question_text", "stem_text",
                            "searchable_text", "quoted_wording", "subitem_text",
                            "stem", "option", "members"})

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
        # `ThreadingHTTPServer` runs a thread per request and `dump` iterates
        # `_map`, so without this a shutdown during an in-flight retrieval hit
        # `RuntimeError: dictionary changed size during iteration`, wrote no map,
        # and left every pseudonym that run permanently uninvertible.
        self._lock = threading.Lock()

    def label(self, target_id: int) -> str:
        """The stand-in for one target.

        Args:
            target_id: The retriever's 1-based row index.

        Returns:
            A short opaque label, stable for the life of this salt.
        """
        with self._lock:
            if target_id not in self._map:
                h = hashlib.sha256(f"{self.salt}:{target_id}".encode()).hexdigest()
                # 48 bits, not 24. Over the corpus's 1,353 targets a 24-bit
                # label collides with probability 1353^2/(2*2^24) ~= 5.5% per
                # salt, and a collision silently renders two different variables
                # as one label AND makes the dumped map ambiguous to invert.
                self._map[target_id] = f"V{h[:12].upper()}"
            return self._map[target_id]

    def dump(self, path: Path) -> None:
        """Write the map so a tester can invert it; never served over HTTP.

        Args:
            path: Destination file. Parents are created.
        """
        with self._lock:
            snapshot = {str(k): v for k, v in self._map.items()}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"salt": self.salt, "labels": snapshot}, indent=1),
                        encoding="utf-8")


def pseudonymise_hit(hit: dict[str, Any], pseud: Pseudonymiser,
                     *, show_instrument: bool = False) -> dict[str, Any]:
    """Reduce a retriever hit to what may leave the process.

    Allowlist, deliberately. `_hit` is owned by the deploy bundle and may gain a
    field; the failure mode of a denylist here is publishing the instrument, and
    the failure mode of an allowlist is an absent number in a demo panel.

    `show_instrument` turns the allowlist off. It exists because the redaction is
    aimed at OTHER PEOPLE, and an operator testing on loopback against a
    dictionary already on their own disk is not other people: with only a
    pseudonym they cannot tell whether the retriever found the RIGHT variable,
    which is the one question a retrieval demo is for. `serve/api.py` will not
    set it on a non-loopback bind, so the default protects the deployment and
    the flag serves the person who already has the file.

    Args:
        hit: A dict as returned by `deploy/retriever.py::CompassRetriever.search`.
        pseud: The map supplying this target's stand-in.
        show_instrument: Return the withheld fields alongside the pseudonym.
            Loopback only; `api.py::main` is what enforces that.

    Returns:
        A new dict carrying the pseudonym and the safe scalar fields, plus the
        instrument fields when `show_instrument` is set.
    """
    out: dict[str, Any] = {"target": pseud.label(int(hit["target_id"]))}
    for k in sorted(SAFE_HIT_FIELDS):
        if k in hit:
            out[k] = hit[k]
    if show_instrument:
        for k in sorted(WITHHELD_HIT_FIELDS):
            if k in hit:
                out[k] = hit[k]
        out["target_id"] = hit["target_id"]
        out["INSTRUMENT_SHOWN"] = "withheld content, loopback only, do not paste"
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
        keys: set[str] = set()
        for e in json.loads(p.read_text(encoding="utf-8"))["entries"]:
            for f in ("searchable_text", "question_text", "stem_text"):
                v = e.get(f)
                if isinstance(v, str):
                    corpus |= _grams(v)
            for f in ("key", "construct_key", "group_key"):
                v = e.get(f)
                if isinstance(v, str) and v:
                    keys.add(v)
        self.corpus = corpus
        # The instrument's OWN keys, matched literally. A regex encodes a belief
        # about the key grammar and the previous one was wrong about 61% of it;
        # this set is exhaustive by construction and cannot drift when a new
        # shape is built. The regex stays as the backstop for a key-shaped
        # string the dictionary does not contain.
        self.keys = keys

    def hits(self, text: str) -> list[str]:
        """Instrument runs and bare keys present in `text`.

        Args:
            text: Prose to check.

        Returns:
            Sorted descriptions of what was found; empty when the text is clean.
        """
        found = [f"key {k}" for k in sorted(set(KEY_RE.findall(text)))]
        # The literal sweep is 3,005 substring tests, so it is skipped for text
        # that cannot contain a key at all: every key has the form `m<n>:...`.
        # Case-folded on both sides for the same reason `KEY_RE` is IGNORECASE.
        if ":" in text:
            low = text.casefold()
            found += [f"key {k}" for k in sorted(self.keys) if k.casefold() in low]
        found += [" ".join(g) for g in sorted(_grams(text) & self.corpus)]
        return sorted(set(found))

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
            for i, (k, v) in enumerate(obj.items()):
                here = f"{_path}.{k}" if _path else str(k)
                if k in WORDING_FIELDS and v:
                    # Structural, not textual: this field IS instrument text by
                    # construction, and the five-word rule cannot see wording
                    # shorter than five words.
                    #
                    # ANY non-empty value, not only a `str`. `members` is a LIST
                    # of roster names, and the `isinstance(v, str)` this replaced
                    # let it past the structural rule entirely -- whereupon the
                    # walk cleared each name individually, because a name is far
                    # shorter than five words. A list of wording is still
                    # wording. Empty values are left alone: there is nothing to
                    # withhold, and replacing them would report a redaction that
                    # removed nothing.
                    out[k] = REDACTED
                    marks.append(here)
                    continue
                # A dict KEY can carry a variable key -- a record mapping
                # `{"m1:1_Q6.2": {...}}` would otherwise ship the key untouched,
                # because the walk only ever looked at values.
                if isinstance(k, str) and self.hits(k):
                    # The MARK MUST NOT NAME THE KEY. `here` interpolates the
                    # dict key, and `Handler._send` ships marks to the client
                    # under `redactions` -- so reporting `here` would delete the
                    # key from the body and reprint it verbatim in the report.
                    # The position is what a reader needs; the value is the
                    # thing being withheld.
                    safe_here = f"{_path}[key #{i}]" if _path else f"[key #{i}]"
                    sub, m = self.scrub(v, safe_here)
                    # Suffixed so two redacted keys in one dict cannot collide
                    # and silently drop a value.
                    out[f"{REDACTED}#{i}"] = sub
                    marks += [f"{safe_here} <key>", *m]
                    continue
                sub, m = self.scrub(v, here)
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
