"""generate/live_specifier.py — the Specifier against a real model, no API key.

    ./.venv/bin/python generate/live_specifier.py [k]

Uses headless `claude -p` for reasoning and reaches the COMPASS environment over
MCP, so tool calls execute in our process and are logged by our server. The
deterministic layer is unchanged: the funnel produces the pair, the registry
builds the toolset, the gate inspects the executed call log, the schema validates
the record, and _rank selects.

READ THE RESULT FOR WHAT IT IS. This tests whether a competent model can drive
the tool surface and produce a valid record. It does NOT test the 8-27B target:
there is no grammar enforcement through the CLI, and the format tax that motivates
the two-call design does not bite a frontier model.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import argparse  # noqa: E402

from agent.cli_backend import ClaudeCliBackend  # noqa: E402
from agent.schema import NotSpecifiable, ProtocolSpecification  # noqa: E402
from agent.tool_authority import (  # noqa: E402
    RunIdentity,
    authoritative_call,
    protocol_id_for,
)
from env import tools as T  # noqa: E402


def run_identity(pair: object, version: str, screened_from: int,
                 model_id: str,
                 selection_mode: str = "enumerated_screen",
                 models: dict[str, str] | None = None,
                 anchors_proposed_by: str | None = None) -> RunIdentity:
    """Assemble what the driver knows before the model is called.

    Every one of these was the empty string in the record of 2026-08-26, which
    saved as `run/.<hash>.json` — a dotfile — because the filename is built from
    protocol_id. None of them is a fact about the design, so none is the model's
    to supply.

    Args:
        pair: The funnel candidate handed to the model.
        version: `build/dictionary.json`'s version_hash.
        screened_from: The funnel's enumerated count — the denominator.
        model_id: The backend's name, model included.
        selection_mode: How the pair reached the model. `externally_posed` for a
            pair named on the command line, because a stated pair was screened
            from nothing and a denominator copied off an unrelated funnel run
            would be a fabricated one.
        models: C17. Every model besides the Specifier that shaped the pair, by
            stage -- `{"resolver": ...}` when a model proposed the anchors.
        anchors_proposed_by: Who proposed the anchors. When omitted it follows
            from `selection_mode`: the funnel enumerates, and any other mode is
            a pair a person stated.

    Returns:
        The identity written over every sample of this run.
    """
    from agent.specifier import prompt_hash

    meta = json.loads((ROOT / "build" / "dictionary.json").read_text())
    return RunIdentity(
        protocol_id=protocol_id_for(getattr(pair, "pair_id", "unknown")),
        dictionary_version=version,
        # The collapse and key rules that produced the namespace these keys are
        # drawn from. Two records built under different rules are not comparable
        # even at the same version_hash.
        module_version=str(meta.get("rules_version", "")) or "unknown",
        prompt_hash=prompt_hash(pair),
        model_id=model_id,
        screened_from=screened_from,
        selection_mode=selection_mode,
        models=tuple(sorted((models or {}).items())),
        anchors_proposed_by=anchors_proposed_by or (
            "enumeration" if selection_mode == "enumerated_screen" else "person"))


#: Anything shaped like a variable key, wherever it appears in a record. The
#: same shape agent/schema.py's KEY_PATTERN accepts, which is the shape a model
#: invents when the schema requires an exposure it cannot find.
KEY_RX = re.compile(r"\b(?:m[123]|clinical|lab|linked|ehr):[A-Za-z0-9_.]+")

#: resolve_variable outcomes that mean the key names something real. Same set as
#: agent/specifier.py's, and for the same reason: `ambiguous` is a failure.
RESOLVED = {"unique", "group", "construct"}


def audit(p: ProtocolSpecification, log_records: list[dict]) -> None:
    """Print the record's gate fields beside the tool results that own them.

    The acceptance criterion for tool-authoritative gate fields is that a live
    record's `access` and `smallest_detectable_effect` equal the corresponding
    `result` entries in THAT RUN'S OWN log. Printing them side by side is how a
    reader checks it without rerunning anything — the previous failure mode was
    auditing a record against a log written two hours later by a different
    sample.

    Args:
        p: The selected ProtocolSpecification.
        log_records: The raw JSONL entries this sample wrote.
    """
    acc = authoritative_call(log_records, "check_access")
    det = authoritative_call(log_records, "estimate_detectability")
    sde = p.estimability.smallest_detectable_effect
    curve = {int(r["n"]): float(r["sde_percentage_points"])
             for r in det.get("sde_by_n", [])}
    # The comparator, read from the same log entry. Auditing only `sde.value`
    # showed the number the record discloses and not the number it was judged
    # against — which for this round is the whole point.
    bound = {int(r["n"]): float(r["sde_percentage_points"])
             for r in det.get("sde_by_n_worst_case_prevalence", [])}
    rows = [(f"access.{k}", getattr(p.access, k), acc.get(k)) for k in
            ("decision", "reconstruction_load", "budget", "location_bearing_keys",
             "origin_unknown_keys", "per_place_working")]
    rows.append(("sde.value", sde.value, curve.get(sde.at_n or -1)))
    rows.append(("sde.at_n", sde.at_n, sde.at_n if sde.at_n in curve else None))
    rows.append(("sde.asserted_prevalence", sde.asserted_baseline_prevalence,
                 det.get("assumptions", {}).get("baseline_prevalence")))
    rows.append(("sde.worst_case_curve", [(pt.n, pt.sde_percentage_points)
                                          for pt in sde.worst_case_curve],
                 sorted(bound.items())))
    print("\n  GATE FIELDS vs THIS RUN'S OWN LOG")
    for name, got, want in rows:
        got = got.value if hasattr(got, "value") else got
        flag = "MATCH  " if got == want else "DIFFERS"
        print(f"    {flag}  {name:<22} record={got!r}")
        print(f"    {'':7}  {'':<22} log   ={want!r}")
    # THE COMPARISON THE SCHEMA ACTUALLY MADE, spelled out. A reader should not
    # have to recompute it to see whether the falsifier cleared the bound or
    # merely cleared the curve the model's own assumption produced.
    if p.falsifier_threshold and sde.at_n in bound:
        t = p.falsifier_threshold
        print(f"\n  FALSIFIER vs THE CALLER-INDEPENDENT BOUND at n={sde.at_n}")
        print(f"    threshold          {t.value} {t.unit}")
        print(f"    bound  (comparator){bound[sde.at_n]:>7} pp   "
              f"<- worst-case prevalence, no caller can move it")
        print(f"    curve  (disclosure){curve.get(sde.at_n):>7} pp   "
              f"<- at asserted prevalence "
              f"{sde.asserted_baseline_prevalence}, NOT the comparator")
        print(f"    verdict            "
              f"{'CLEARS' if abs(t.value) >= abs(bound[sde.at_n]) else 'BELOW'} "
              f"the bound")


def refusal_audit(r: NotSpecifiable, stated: set[str],
                  log_records: list[dict]) -> None:
    """Print a refusal beside the calls that forced it.

    The same acceptance test the protocol path gets from `audit`: a reader
    checks the record against THIS sample's own log rather than against whatever
    log happened to be lying around. Two things must hold. Every cited lookup
    appears in the log with the outcome the record claims for it. And every key
    the record names is one the PAIR named or the instrument contains — echoing
    the stated exposure back is what a refusal is for, while a key that is
    neither is the fabrication this path exists to remove.

    Args:
        r: The refusal the environment upheld.
        stated: Every key the pair itself named, so a key the record echoes back
            is not counted as one it invented.
        log_records: The raw JSONL entries this sample wrote.
    """
    print("\n  REFUSAL vs THIS RUN'S OWN LOG")
    for label, value in (("reason", r.reason.value),
                         ("blocked_on", [b.value for b in r.blocked_on]),
                         ("would unblock", r.what_would_unblock),
                         ("statement", r.statement)):
        print(f"    {label:<18}{value}")
    for e in r.evidence:
        ran = [x for x in log_records if x.get("tool") == e.tool]
        args = [json.dumps(x.get("args", {})) for x in ran]
        flag = "IN LOG " if ran else "ABSENT "
        print(f"    {flag}  {e.tool}({e.argument!r}) -> {e.outcome}")
        print(f"    {'':7}  the run called it {len(ran)}x: {args[:4]}")
    # Counted off the SERIALISED record, not off a field list, so a field added
    # later cannot hide a key from the count. A key is invented when the record
    # names it, the pair did not state it, and the instrument does not contain
    # it — which is the failure this whole path exists to remove, and the number
    # the acceptance test reads.
    named = sorted(set(KEY_RX.findall(r.model_dump_json())))
    invented = [k for k in named if k not in stated
                and T.resolve_variable(key=k).get("outcome") not in RESOLVED]
    print(f"    keys named        {named}")
    print(f"    of those, stated  {[k for k in named if k in stated]}")
    print(f"    INVENTED KEYS     {len(invented)}  {invented}")


def ref(r: object) -> str:
    """Render any Ref as a short label.

    A Ref is a tagged union — covariates can be derivations or area measures too,
    not only survey variables. Assuming `.key` crashed a paid run after the
    record was already valid but before it was saved.

    Args:
        r: A VariableRef, DerivationRef or AreaMeasureRef.

    Returns:
        The key, or a `derivation:`/`area:` label.
    """
    key = getattr(r, "key", None)
    if isinstance(key, str):
        return key
    did = getattr(r, "derivation_id", None)
    if isinstance(did, str):
        return f"derivation:{did}"
    return f"area:{getattr(r, 'measure_id', r)}"
from agent.specifier import (  # noqa: E402
    Attempt,
    Result,
    specify,
    untraced_derivation_values,
)
from generate.funnel import (  # noqa: E402
    DEFAULT_FRAME,
    FRAMES,
    Candidate,
    Construct,
    live_at,
    load_constructs,
    run,
)


def winning_attempt(res: Result) -> Attempt | None:
    """The attempt that produced the selected record, found by identity.

    Not by `record_hash`. `sought_covariates` sits outside `canonical_form`, so a
    silent sample and its disclosing twin hash identically, and a hash match
    returned whichever arrived first. When the disclosing twin won, the saved
    record got the silent twin's tool log, audit and repairs. `specify` selects
    an attempt's own protocol object, so identity names exactly one attempt.

    Args:
        res: What `specify` returned.

    Returns:
        The attempt whose protocol was selected, or None if none was.
    """
    if res.selected is None:
        return None
    return next((a for a in res.attempts if a.protocol is res.selected), None)


def save_repairs(out: Path, attempt: Attempt, log_records: list[dict]) -> Path:
    """Persist a record's repair history beside it, with what traces nowhere.

    C19. A repair error can quote a signed file, so a record that passed on a
    later attempt can carry a value no tool in its log returned. The record's
    own tool log is already copied beside it; without the repairs next to it,
    such a value has no visible source, and `Attempt` does not outlive the run.

    Args:
        out: The record's path; the history is written beside it.
        attempt: The sample that produced the record.
        log_records: The record's own tool log, parsed.

    Returns:
        The path written.
    """
    record = attempt.protocol if attempt.protocol is not None else attempt.refusal
    untraced = (untraced_derivation_values(record, log_records, attempt.repairs)
                if record is not None else [])
    saved = out.with_suffix(".repairs.json")
    saved.write_text(json.dumps({"repairs": attempt.repairs, "untraced": untraced},
                                indent=2))
    return saved


def stand_in(key: str) -> Construct:
    """Represent a construct key the instrument does not contain.

    A pair whose anchor resolves nowhere has to be REPRESENTABLE or the refusal
    path can never be exercised end to end — which is the same shape as the hole
    it exists to close, one level up: the record could not represent an
    unspecifiable pair, and the driver could not construct one.

    Nothing is invented here beyond the key the caller stated. No wording, no
    members, no module — an empty stem is what a key with no codebook row has,
    and filling it with a plausible sentence would hand the model the very
    description the environment cannot give it.

    Args:
        key: The construct key, e.g. one in a declared-but-empty registry.

    Returns:
        A Construct carrying the key and nothing else.
    """
    prefix, _, rest = key.partition(":")
    return Construct(construct_key=key, module=prefix, base_id=rest or key,
                     stem_text="", member_keys=[key], is_group=False,
                     is_free_text=False, roster_instances=0)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Read the run's arguments.

    Args:
        argv: The command line, without the program name.

    Returns:
        The parsed arguments. `k` and `model` stay positional so the command in
        the handoff keeps working unchanged.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("k", nargs="?", type=int, default=1)
    ap.add_argument("model", nargs="?", default="claude-haiku-4-5")
    ap.add_argument("--exposure", help="run a STATED pair: exposure construct key")
    ap.add_argument("--outcome", help="run a STATED pair: outcome construct key")
    ap.add_argument("--frame", default=DEFAULT_FRAME, choices=sorted(FRAMES),
                    help="the named frame to walk (generate/funnel.py::FRAMES)")
    ap.add_argument("--index", type=int, default=0,
                    help="which live pair of the frame, in enumeration order")
    a = ap.parse_args(argv)
    if bool(a.exposure) != bool(a.outcome):
        ap.error("--exposure and --outcome are given together or not at all")
    return a


def main() -> None:
    """Run the Specifier against a live model and save the winning record."""
    args = parse_args(sys.argv[1:])
    k, model = args.k, args.model

    C, version = load_constructs()
    frame = FRAMES[args.frame]
    exposures, outcomes = frame.sides(C)
    cands, counts = run(exposures, outcomes)
    if args.exposure:
        # STATED, not enumerated, and the identity says so. A pair named on the
        # command line was screened from nothing, so it carries no funnel
        # denominator; copying the 6x64 frame's would be a fabricated one.
        pair = Candidate(exposure=C.get(args.exposure) or stand_in(args.exposure),
                         outcome=C.get(args.outcome) or stand_in(args.outcome))
        screened_from, mode = 0, "externally_posed"
    else:
        # T7: the frame is walked in enumeration order and `--index` says
        # where. The pair used to be named here by hand, which is a second,
        # value-based selection on top of the funnel's that no denominator
        # recorded.
        pair = live_at(cands, args.index)
        screened_from, mode = counts["enumerated"], "enumerated_screen"

    backend = ClaudeCliBackend(model=model, mode="benchmark")
    bar = "=" * 76
    print(bar)
    print(f"LIVE SPECIFIER   {backend.name}   k={k}   mode=benchmark")
    print(bar)
    print(f"  pair        {pair.pair_id}")
    print(f"  frame       {frame.name}  {frame.digest(C, version)}  "
          f"live index {'-' if args.exposure else args.index}")
    print(f"  dictionary  {version}   screened_from {screened_from} ({mode})")
    print("  running (each sample = 1 reasoning call w/ MCP tools + 1 transduction)\n")

    identity = run_identity(pair, version, screened_from, backend.name, mode)
    print(f"  identity    protocol_id={identity.protocol_id} "
          f"prompt_hash={identity.prompt_hash} model_id={identity.model_id}")
    res = specify(backend, pair, k=k, mode="benchmark", parked_dir=ROOT / "parked",
                  identity=identity)

    p_id = identity.protocol_id
    print(f"{bar}\nPER-SAMPLE\n{bar}")
    for a in res.attempts:
        print(f"  seed {a.seed}  gate={a.gate:<28} tool calls={a.steps}  "
              f"transductions={a.attempts}")
        print(f"     the sample declared: "
              f"{a.claimed_reason.value if a.claimed_reason else 'no refusal'}")
        print(f"     distinct tools: {sorted(set(a.tool_names))}")
        print(f"     tool log:       {a.tool_log_path}")
        if a.error:
            # The WHOLE rejection, not its first line. A pydantic ValidationError
            # opens with "1 validation error for ProtocolSpecification" and puts
            # the field and the reason on the lines after, so printing one line
            # printed the only line with no information in it — and a live run
            # that costs a model call is exactly where the reason has to survive.
            print("     error:")
            for line in a.error.splitlines():
                print(f"       {line[:150]}")
        if a.rejected:
            # Saved, not just printed. A live run costs a model call; diagnosing
            # why it failed must not cost a second one.
            d = ROOT / "run" / "logs"
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"rejected.seed{a.seed}.{p_id}.json"
            f.write_text(a.rejected)
            print(f"     rejected object: {f}")

    print(f"\n{bar}\nRESULT\n{bar}")
    print(f"  yield         {res.yield_line}")
    print(f"  {res.reason}")

    if res.refusal is not None:
        r = res.refusal
        out = ROOT / "run" / f"{p_id}.refusal.{r.record_hash()}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(r.model_dump_json(indent=2))
        print(f"\n  written       {out.relative_to(ROOT)}   (saved before printing)")
        # The refusing sample's OWN log, copied beside the record, for the same
        # reason the protocol path does it: a record auditable only against
        # whichever log was last written is not auditable.
        won = next((a for a in res.attempts
                    if a.refusal is not None and a.tool_log_path
                    and a.refusal.record_hash() == r.record_hash()), None)
        src = won.tool_log_path if won else None
        recs: list[dict] = []
        if src and Path(src).exists():
            saved = out.with_suffix(".tool_log.jsonl")
            shutil.copyfile(src, saved)
            print(f"  tool log      {saved.relative_to(ROOT)}   (this record's own log)")
            recs = [json.loads(x) for x in saved.read_text().splitlines() if x.strip()]
        if won is not None:
            rp = save_repairs(out, won, recs)
            print(f"  repairs       {rp.relative_to(ROOT)}   "
                  f"({len(won.repairs)} rejected before this record)")
        stated = {pair.exposure.construct_key, pair.outcome.construct_key,
                  *pair.exposure.member_keys, *pair.outcome.member_keys}
        refusal_audit(r, stated, recs)
        return

    p = res.selected
    if p is None:
        print("\n  No valid record. The analysis from the last sample:\n")
        print("   " + (res.attempts[-1].analysis or "")[:1500].replace("\n", "\n   "))
        return

    out = ROOT / "run" / f"{p.protocol_id}.{p.record_hash()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(p.model_dump_json(indent=2))
    print(f"\n  written       {out.relative_to(ROOT)}   (saved before printing)")

    # The winning sample's log, copied next to the record under a name that ties
    # the two together. Without this the record is auditable only against
    # whatever happened to be in run/tool_log.jsonl last, which is how an earlier
    # session came to report 28 tool calls for a record that made none of them.
    win = winning_attempt(res)
    src = win.tool_log_path if win else None
    log_recs: list[dict] = []
    if src and Path(src).exists():
        saved = out.with_suffix(".tool_log.jsonl")
        shutil.copyfile(src, saved)
        print(f"  tool log      {saved.relative_to(ROOT)}   (this record's own log)")
        log_recs = [json.loads(x) for x in saved.read_text().splitlines() if x.strip()]
        audit(p, log_recs)
    if win is not None:
        rp = save_repairs(out, win, log_recs)
        print(f"  repairs       {rp.relative_to(ROOT)}   "
              f"({len(win.repairs)} rejected before this record)")
    print(f"  {p.protocol_id}  {p.record_hash()}  status={p.status.value}")
    ex = ref(p.exposure)
    print(f"  question      {p.question[:70]}")
    print(f"  exposure      {ex}")
    print(f"  outcome       {ref(p.outcome)}")
    print(f"  direction     {p.expected_direction.direction.value}")
    print(f"  adjusted      {[ref(e.variable) for e in p.adjusted_covariates]}")
    print(f"  excluded      {[ref(e.variable) for e in p.excluded_variables]}")
    print(f"  undetermined  {[ref(e.variable) for e in p.undetermined_covariates]}")
    print(f"  n             {p.estimability.analytic_n} "
          f"({p.estimability.n_source.value})  blocked_on "
          f"{[b.value for b in p.blocked_on]}")
    ft = p.falsifier_threshold
    print(f"  falsifier     "
          f"{f'{ft.value} {ft.unit}' if ft else 'prose only, no threshold'}")
    print(f"  access        {p.access.decision.value} "
          f"{p.access.reconstruction_load}/{p.access.budget}")
    if backend.last_cost:
        print(f"\n  cost this run ~${backend.last_cost:.4f} (last call only)")




if __name__ == "__main__":
    main()
