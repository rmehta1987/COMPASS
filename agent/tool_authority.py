"""agent/tool_authority.py — the environment owns the gate fields, not the model.

A model that writes its own gate verdict is not gated. In the only real record
this pipeline has produced, three fields were the model's transcription of a
number a tool had already computed, and two of them were wrong in the direction
that helps the record pass:

    access.budget                 the record said 0; check_access returned 3, so
                                  the gate read "reconstruction_load 0 / budget
                                  0" and passed trivially
    access.per_place_working      the record said "No place-based linked measures
                                  required"; check_access returned "no
                                  location-bearing variable named"
    smallest_detectable_effect    value null, with the whole detectability curve
                                  pasted into the free-text assumptions field, so
                                  the falsifier check had nothing to compare
                                  against and a 13pp threshold sailed through

This module is the structural fix. It runs after transduction and BEFORE
validation, over the raw JSONL records the MCP server wrote (or, on the
in-process tool loop, the return values captured at the function boundary). It is
mechanical Python: no model call happens anywhere in this path, because control
flow does not move into the model.

It runs before validation on purpose. `_falsifier_is_detectable` rejects a record
whose smallest_detectable_effect.value is null, and no prompt asks for that value
— post-filling after validation would never get the chance to supply it, which is
the exact failure recorded as T1 item 2.

TWO DIFFERENT GUARANTEES, DELIBERATELY NOT THE SAME ONE
-------------------------------------------------------
OVERWRITTEN — the tool's working: reconstruction_load, budget,
location_bearing_keys, origin_unknown_keys, per_place_working, modules_required,
the whole smallest_detectable_effect block, and provenance.tool_calls. These are
transcriptions of something the environment computed, over which the model has no
discretion. A transcription slip is not a design error, and discarding a sample
over one spends a model call to fix a copy-paste. Overwriting also makes the
guarantee structural rather than merely detected: afterwards the field IS the
tool's return value, so no future loosening of a comparison can quietly reopen
the hole.

APPENDED TO, NOT OVERWRITTEN — blocked_on gains
`outcome_prevalence_unconfirmed` whenever the run called estimate_detectability,
and nothing else in the list is touched. It is its own shape because blocked_on
is the model's disclosure everywhere else and must stay so: the model's other
blockers are judgements about its own design, while this one is a mechanical
consequence of having called the tool at all — asserting an outcome frequency
this environment holds no data to confirm. Deriving it here rather than asking
for it means it cannot be forgotten in transduction; the schema enforces it too,
so a hand-built record cannot dodge it.

REJECTED ON MISMATCH — the verdicts: access.decision, estimability.n_source,
estimability.analytic_n. Overwriting a verdict would be worse than useless. A
model that wrote decision=pass over a tool that said refer chose its covariate
lists believing it had clearance, so silently correcting that one field leaves
every other field standing on a premise the environment denied. It would also
break the record from the inside: `status` is derived from access.decision and
n_source by derive_status() and validated against them, so flipping either behind
the validator's back yields a record whose own status validator would have
rejected it. And §5 rule 5 is explicit that a fabricated n must fail rather than
be quietly repaired.

REJECTED ON MISMATCH — the ARGUMENTS. A verdict is only about the design it was
computed over. Round 1 stamped the last successful call's return value into the
record without ever asking whether that call named the design the record
describes, and wrote the residual down as a comment instead of closing it. It is
closed here: the authoritative call's key set must COVER every variable key the
record names in a position that uses it. Coverage, not equality, because a
superset can only make both verdicts stricter — extra keys can add
reconstruction load, add origin_unknown keys, and add modules to
modules_required, never remove them — while a SUBSET is the flattering
direction and is exactly the hole. Calling estimate_n on one key of a
three-module design stamps modules_required=['m2'] on a record spanning m1+m2+m3
and gives a wrong value the environment's imprimatur.

WHAT THE BINDING DELIBERATELY DOES NOT REQUIRE: keys that appear only in
`excluded_variables`. check_access's own docstring states that deliberately
excluded variables consume no budget, and the tool takes a flat key list with no
way to tell an exclusion from an adjustment — so the only way that contract can
hold is for the caller not to pass them. Requiring them would reject a record
for stating its exclusions, which is the behaviour the three-list schema exists
to encourage. The consequence, stated rather than discovered later: a
location-bearing variable parked in `excluded_variables` is exempt from the
access budget by design.

THE FLOOR THE FALSIFIER IS CHECKED AGAINST is likewise the environment's, not the
model's. See _governing_n.

IDENTITY AND PROVENANCE are owned here too, from a different source of authority:
the driver rather than the tool log. See apply_record_identity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agent.schema import _dictionary_wording, _signed_derivations

#: The tools whose return values own a field in the record. Kept separate from
#: specifier.REQUIRED_CALLS because resolve_variable is required to be CALLED but
#: owns no gate field — its authority is already enforced by _wording_is_verbatim
#: against the dictionary, which is a stronger check than a log comparison.
AUTHORITATIVE_TOOLS: tuple[str, ...] = (
    "check_access", "estimate_n", "estimate_detectability")

_MISSING = object()


class GateMismatch(ValueError):
    """A record's gate fields contradict the tool log of the run that produced it.

    Subclasses ValueError so the transduction repair loop, which already catches
    ValidationError and ValueError, hands the model the mismatch text and lets it
    try once more rather than discarding the sample outright.
    """


def _last_ok(log_records: list[dict[str, Any]], tool: str) -> dict[str, Any]:
    """Return the whole log ENTRY that owns `tool`'s fields in the record.

    Split out from authoritative_call so "which call counts" has exactly one
    definition: the argument binding has to interrogate the same call whose
    return value is stamped into the record, or the two checks are about
    different calls and the binding proves nothing.

    Args:
        log_records: Raw log entries for ONE sample, each a dict with `tool`,
            `args`, `outcome` and `result` keys, in call order.
        tool: The tool whose authoritative call is wanted.

    Returns:
        That call's raw log entry, arguments included.

    Raises:
        GateMismatch: If the call never happened, if every attempt came back
            `error` / `not_available`, or if the log entry predates result
            capture and so carries no return value to be authoritative with.
    """
    # WHY THE LAST SUCCESSFUL CALL, precisely. check_access can be called more
    # than once with different key sets, so "which one counts" has to be pinned
    # rather than assumed. The obvious worry is retry-until-pass; it does not
    # apply, because check_access is a pure function of its keys and the only way
    # to turn a `refer` into a `pass` is to change the key set — which is
    # changing the design, not gaming the gate. The system prompt tells the model
    # to call it "last, once the covariate lists are settled", so any earlier
    # call was made against an incomplete key set and describes a design that is
    # not the one in the record; taking anything but the last would put a stale
    # verdict into the record.
    #
    # NOT CHECKED HERE, BUT CHECKED: that this call's key set is the one the
    # record actually names. That is _reject_uncovered, which apply_tool_authority
    # runs against THIS entry — the split exists so both checks are about the same
    # call. Keeping it out of this function means authoritative_call() stays
    # usable by readers like generate/live_specifier.audit(), which have a log and
    # a validated record and no need to re-derive the binding.
    seen = [r for r in log_records if r.get("tool") == tool]
    if not seen:
        raise GateMismatch(
            f"{tool} does not appear in this run's tool log, so no value it "
            f"returns can be authoritative. A record cannot assert a field the "
            f"environment was never asked to compute.")

    # A required call that came back `error` or `not_available` is a gate
    # FAILURE, never a silent skip: `not_available` is the exact shape a
    # benchmark-mode registry withholding returns, and reading it as "the tool
    # ran" would let a withheld tool authorise a field.
    ok = [r for r in seen if r.get("outcome") == "ok"]
    if not ok:
        outcomes = sorted({str(r.get("outcome")) for r in seen})
        raise GateMismatch(
            f"every {tool} call in this run's log came back {outcomes}. A failed "
            f"lookup does not authorise a gate field; the call has to succeed.")

    if not isinstance(ok[-1].get("result"), dict):
        raise GateMismatch(
            f"the {tool} entry in this run's log carries no `result`. Logs "
            f"written before mcp/compass_server.py stored return values cannot "
            f"authorise anything — regenerate the log and re-run the sample.")
    return ok[-1]


def authoritative_call(log_records: list[dict[str, Any]], tool: str) -> dict[str, Any]:
    """Return the result dict of the call that owns `tool`'s fields in the record.

    Args:
        log_records: Raw log entries for ONE sample, in call order.
        tool: The tool whose authoritative call is wanted.

    Returns:
        The `result` dict the environment returned for that call.

    Raises:
        GateMismatch: Propagated from _last_ok.
    """
    result: dict[str, Any] = _last_ok(log_records, tool)["result"]
    return result


def _reject_mismatch(field: str, wrote: object, tool: str, returned: object,
                     hint: str = "") -> None:
    """Raise if a verdict field disagrees with the tool that owns it.

    Args:
        field: Dotted path of the field, for the error message.
        wrote: The value the transduction emitted, or `_MISSING`.
        tool: The tool whose return value is authoritative.
        returned: The value that tool actually returned.
        hint: Which key of the tool's result to read, when the result has more
            than one field that could plausibly be copied.

    Raises:
        GateMismatch: If the two disagree.
    """
    # A field the transduction omitted entirely is left alone: pydantic will
    # reject it with a better message than this function can, and reporting a
    # mismatch against a value that was never written would send the repair
    # attempt after the wrong error.
    if wrote is _MISSING or wrote == returned:
        return
    raise GateMismatch(
        f"{field} says {wrote!r} but {tool} returned {returned!r} in this run's "
        f"own tool log. {hint}This field is the environment's verdict, not "
        f"yours: copy it from the tool output or change the design until the "
        f"tool returns what you want to claim.")


def _governing_n(rows: dict[int, float], analytic_n: object,
                 stated: object = None) -> int:
    """The n whose curve value the falsifier is checked against.

    Args:
        rows: The returned curve as {n: smallest detectable effect, pp}.
        analytic_n: The value `estimate_n` returned for this design, which is
            null for every cross-module set in this instrument until module
            co-completion counts arrive.
        stated: The candidate n the record itself commits to, if any.

    Returns:
        The analytic n where the environment computed one; otherwise the n the
        record states; otherwise the smallest candidate.
    """
    # PRECEDENCE, AND WHY. A computed analytic n outranks everything: it is the
    # study's real n and no disclosure can improve on it.
    if isinstance(analytic_n, int) and not isinstance(analytic_n, bool) \
            and analytic_n in rows:
        return analytic_n
    # Otherwise the record's own stated n governs — but only as a DISCLOSURE, not
    # as a free comparator. Round 1 let any on-curve at_n through silently, so a
    # model that named the largest candidate picked its own floor and a 3.0 pp
    # threshold cleared a curve whose smallest-n value is 25.68 pp. What makes
    # that safe now is not this line but the three around it: the whole curve is
    # written into the record beside at_n, ProtocolSpecification refuses a
    # threshold that names no n at all, and a record resting on an uncomputed n
    # must carry its blocker and cannot leave draft.
    #
    # The alternative — pinning the smallest candidate always — was tried and
    # rejected. It makes ONE element of an authored evaluation grid set the
    # minimum effect every protocol in the system may claim: on the current grid
    # that is 26.14 pp at baseline prevalence 0.32, which is why the scripted
    # fixture had to assert a 27 pp falsifier to pass. A rule satisfied by making
    # the claim absurd fails as surely as one satisfied vacuously, and it decides
    # whether a falsifier is WORTH stating — a soundness judgment this system is
    # forbidden to make (§5 rule 3: estimability, never soundness).
    if isinstance(stated, int) and not isinstance(stated, bool) and stated in rows:
        return stated
    # Nothing stated: the smallest candidate, which is the only default that
    # cannot flatter a record that declined to commit.
    return min(rows)


def _asserted_prevalence(det: dict[str, Any]) -> float | None:
    """The outcome frequency the curve was computed under, from the tool's return.

    Args:
        det: The authoritative `estimate_detectability` result.

    Returns:
        The asserted reference-arm outcome frequency, or None when the tool
        recorded no assumption set to read it from.

    Read from the tool's own `assumptions`, never from the call arguments: the
    arguments say what was asked for and the assumption set says what the
    formula actually used, and only the second is the environment's word.
    """
    v = det.get("assumptions", {}).get("baseline_prevalence")
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _sde_from_curve(sde: dict[str, Any], det: dict[str, Any],
                    analytic_n: object = None) -> dict[str, Any]:
    """Resolve smallest_detectable_effect against the curve the tool returned.

    Args:
        sde: The `smallest_detectable_effect` object as transduced.
        det: The authoritative `estimate_detectability` result.
        analytic_n: The authoritative `estimate_n` analytic_n, or None.

    Returns:
        A new smallest_detectable_effect dict whose value, unit and at_n are the
        governing point of the returned curve, carrying both the disclosed curve
        and the caller-independent bound the falsifier is checked against.

    Raises:
        GateMismatch: If either curve is absent, or the record names an at_n or a
            value that is not on the disclosed curve.
    """
    rows: dict[int, float] = {int(r["n"]): float(r["sde_percentage_points"])
                              for r in det.get("sde_by_n", [])
                              if isinstance(r, dict) and "n" in r}
    if not rows:
        raise GateMismatch(
            "estimate_detectability returned no sde_by_n curve, so "
            "smallest_detectable_effect cannot be established.")
    # The bound is fetched here rather than recomputed, for the same reason every
    # other gate field is: recomputing it would put a second implementation of
    # the environment's formula in the agent package, and the two would drift.
    worst: dict[int, float] = {
        int(r["n"]): float(r["sde_percentage_points"])
        for r in det.get("sde_by_n_worst_case_prevalence", [])
        if isinstance(r, dict) and "n" in r}
    if not worst:
        raise GateMismatch(
            "estimate_detectability returned no sde_by_n_worst_case_prevalence "
            "bound. The falsifier is checked against that bound and not against "
            "the curve, because the curve's outcome frequency is the caller's "
            "own assertion; with no bound there is nothing to check against.")

    at_n = sde.get("at_n")
    value = sde.get("value")
    # An off-curve at_n or value is still REJECTED rather than repaired, and the
    # rejection is not made redundant by the overwrite below. at_n=1800 against a
    # curve that holds neither 1800 nor its value says the prose analysis reasoned
    # about a floor no tool produced; rewriting it silently would hide that the
    # whole falsifier argument rests on an interpolated number.
    if at_n is not None and int(at_n) not in rows:
        raise GateMismatch(
            f"smallest_detectable_effect.at_n={at_n} is not a point on the "
            f"curve estimate_detectability returned ({sorted(rows)}). "
            f"Interpolating between curve points is inventing a number the "
            f"environment did not compute.")
    if at_n is None and value is not None and not any(
            round(float(value), 2) == v for v in rows.values()):
        raise GateMismatch(
            f"smallest_detectable_effect.value={value} appears nowhere on "
            f"the curve estimate_detectability returned "
            f"({sorted(rows.items())}). A detectable effect that is not a "
            f"tool output is an assertion.")

    at_n = _governing_n(rows, analytic_n, at_n)

    # THE WHOLE CURVE, not one point off it. SmallestDetectableEffect's own
    # docstring has always said estimate_detectability "returns a curve, not a
    # scalar — that is what lets this field stay honest while n is unknown", and
    # the record then threw the curve away and kept one number. Writing it here
    # is what lets `value` be a disclosed commitment rather than a hidden choice:
    # a reader sees at a glance what the design buys at every other candidate n.
    return {"curve": [{"n": n, "sde_percentage_points": v}
                      for n, v in sorted(rows.items())],
            # THE COMPARATOR, carried beside the disclosure. Until this was
            # written the record held only the caller-asserted curve, so
            # agent/schema.py had nothing to check a threshold against except a
            # floor whose height the caller had set.
            "worst_case_curve": [{"n": n, "sde_percentage_points": v}
                                 for n, v in sorted(worst.items())],
            # STRUCTURED, NOT A SUBSTRING. This used to survive only inside the
            # `assumptions` sentence below, where no scorer could read it without
            # parsing prose — and it is the one input that scales the entire
            # curve.
            "asserted_baseline_prevalence": _asserted_prevalence(det),
            "value": rows[at_n], "unit": "percentage points", "at_n": at_n,
            # The tool's own assumption set, verbatim, replaces the model's
            # prose. In the live record that prose held the entire curve while
            # `value` was null, which is how the falsifier check came to have
            # nothing to compare against.
            "assumptions": "; ".join(f"{k}={v}" for k, v in
                                     det.get("assumptions", {}).items())}


#: The covariate lists whose keys the record actually USES. `excluded_variables`
#: is absent on purpose — see the module docstring.
_USED_LISTS: tuple[str, ...] = ("adjusted_covariates", "undetermined_covariates")


def _ref_keys(ref: object) -> list[str]:
    """Variable keys reachable from one Ref, whatever kind of Ref it is.

    Args:
        ref: An exposure, outcome or covariate reference, as raw JSON.

    Returns:
        The variable keys it names. A derivation contributes its component keys
        rather than its id, because that is what the tools take: passing the id
        into estimate_n dropped it silently and reported the wrong modules, and
        passing it into check_access returned `refer` on an unknown origin.
        An area measure contributes none — it names no instrument variable.
    """
    if not isinstance(ref, dict):
        return []
    if ref.get("kind") == "derivation":
        return [k for k in ref.get("component_keys", []) if isinstance(k, str)]
    key = ref.get("key")
    return [key] if isinstance(key, str) else []


def design_keys(record: dict[str, Any]) -> set[str]:
    """The variable keys a record names in a position that uses them.

    Args:
        record: The transduced JSON object, as parsed.

    Returns:
        Keys from the exposure, the outcome, the adjusted covariates and the
        undetermined covariates. Undetermined ones count because the schema
        ships each as a paired sensitivity specification — a model that is run
        with the variable in it needs the same clearance and the same modules.
    """
    keys = set(_ref_keys(record.get("exposure"))) | set(_ref_keys(record.get("outcome")))
    for name in _USED_LISTS:
        for entry in record.get(name) or []:
            if isinstance(entry, dict):
                keys |= set(_ref_keys(entry.get("variable")))
    return keys


def _reject_uncovered(tool: str, call: dict[str, Any],
                      required: set[str]) -> None:
    """Raise if the authoritative call did not name the design the record does.

    Args:
        tool: The tool whose authoritative call is being bound.
        call: That call's raw log entry.
        required: The keys the record names in a used position.

    Raises:
        GateMismatch: If any required key is absent from the call's arguments.
    """
    called = {k for k in (call.get("args") or {}).get("keys", [])
              if isinstance(k, str)}
    missing = sorted(required - called)
    if not missing:
        return
    # NAME THE REAL PROBLEM WHEN THERE IS A WORSE ONE. A key that resolves
    # nowhere is not "a key you forgot to pass" — it does not exist, and it fails
    # registry membership too. Found live 2026-08-27: Haiku wrote `m1:age`, which
    # matches the key pattern, and spent all four transductions being told it had
    # not passed that key to check_access rather than that no such variable is in
    # the instrument. A repair aimed at the wrong error cannot land.
    known = _dictionary_wording()
    unknown = [k for k in missing if known and k not in known]
    if unknown:
        raise GateMismatch(
            f"{unknown} appear in this record but resolve nowhere in the "
            f"instrument, which is why {tool} was never called with them. "
            f"resolve_variable did not return these keys. Do not substitute a "
            f"similar-sounding item: delete each one's entry, or replace it "
            f"with a key resolve_variable actually returned.")
    # THE REMEDY HAS TO BE ONE THIS READER CAN PERFORM. This text reaches the
    # transduction call, which has no tools at all, so "call the tool again" is
    # an instruction the only reader of the message cannot follow — the same
    # class of defect as a constraint stated in no prompt. Found on the live run
    # of 2026-08-26: Haiku added a covariate after its last estimate_n, and the
    # first draft of this message sent the repair attempt after an impossible fix.
    raise GateMismatch(
        f"{tool} was called with {len(called)} key(s) but this record names "
        f"{len(required)} in positions that use them, and {len(missing)} were "
        f"never passed: {missing}. The value {tool} returned describes a "
        f"different design from the one written down. You cannot call tools now. "
        f"Fix it in the record: drop each of those keys from the adjusted and "
        f"undetermined lists, or move it to excluded_variables with its "
        f"mechanism — a variable the environment was never asked about has no "
        f"clearance and no module accounting, so it cannot sit in a list the "
        f"design uses.")


def _restate_derivation_units(record: dict[str, Any]) -> None:
    """Copy each DerivationRef's unit from the signed file it names, in place.

    Args:
        record: The transduced JSON object. Modified.

    OVERWRITTEN, not rejected, and the reason is a measured property of the
    transduction call rather than a preference. `_transduce` renders the research
    log as `name(args) -> outcome`: the tool RETURN VALUES are not in that
    prompt. So the model at transduction time cannot see the string
    get_derivation returned, and a rule that demands it be copied verbatim demands
    something the only reader of the rule cannot do — the same defect as a
    constraint stated in no prompt. Found live 2026-08-27: Haiku wrote
    `unit: "scale"` for a signed "mean Likert score, 5 items" and lost the sample
    across both attempts even though the rejection quoted the exact string.

    The unit is also a pure transcription: once the model has chosen a
    derivation_id — which IS its decision, and is checked — the signed file fixes
    the unit and the model has no discretion left. `component_keys` is NOT
    treated this way and is still rejected on mismatch: the keys are the
    substance of which items enter the scale, the analysis prose lists them, and
    a 30-versus-2 disagreement means the reasoning was about a different variable
    set, not that a label was reworded.
    """
    signed = _signed_derivations()
    if not signed:
        return
    for ref in _iter_derivation_refs(record):
        did = ref.get("derivation_id")
        got = signed.get(did) if isinstance(did, str) else None
        if isinstance(got, dict) and got.get("unit"):
            ref["unit"] = got["unit"]


def _iter_derivation_refs(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Every DerivationRef in a record, wherever a Ref may appear.

    Args:
        record: The transduced JSON object.

    Returns:
        The reference dicts themselves, so a caller can edit them in place.
    """
    out: list[dict[str, Any]] = []
    refs: list[Any] = [record.get("exposure"), record.get("outcome")]
    for name in (*_USED_LISTS, "excluded_variables"):
        refs += [e.get("variable") for e in (record.get(name) or [])
                 if isinstance(e, dict)]
    for r in refs:
        if isinstance(r, dict) and r.get("kind") == "derivation":
            out.append(r)
    return out


def _render_calls(log_records: list[dict[str, Any]]) -> list[str]:
    """Render the executed log as the provenance.tool_calls list.

    Args:
        log_records: Raw log entries for one sample, in call order.

    Returns:
        One string per executed call, name, arguments and outcome.
    """
    return [f"{r.get('tool')}({json.dumps(r.get('args', {}), sort_keys=True)[:160]})"
            f" -> {r.get('outcome')}" for r in log_records]


def apply_tool_authority(record: dict[str, Any],
                         log_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Post-fill tool-owned fields and reject verdicts that contradict the log.

    Operates on the transduced JSON object rather than a validated record,
    because `_falsifier_is_detectable` rejects a null
    smallest_detectable_effect.value and the value has to be supplied before
    validation runs, not after.

    Args:
        record: The transduced JSON object, as parsed.
        log_records: Raw log entries for THIS sample, each carrying the tool
            name, arguments, outcome and the environment's return value.

    Returns:
        A new dict with the tool-owned fields replaced by the environment's own
        values. The input is not modified.

    Raises:
        GateMismatch: If a required call is absent or failed, if its log entry
            carries no result, if the call did not name every key the record
            uses, or if a verdict field the model wrote disagrees with the tool
            that owns it.
    """
    if not isinstance(record, dict):
        return record                       # not an object; pydantic says why

    out: dict[str, Any] = json.loads(json.dumps(record))     # deep copy, JSON-safe

    # Computed once, before any field is touched: the binding has to be checked
    # against what the model wrote, not against a record this function has
    # already been rewriting.
    required = design_keys(out)

    acc = authoritative_call(log_records, "check_access")
    _reject_uncovered("check_access", _last_ok(log_records, "check_access"), required)
    block = out.get("access")
    if isinstance(block, dict):
        # Found live 2026-08-26: Haiku wrote decision='ok', which is the tool's
        # `outcome` envelope, not its verdict. Naming the right key in the
        # rejection is what makes the one repair attempt usable.
        _reject_mismatch("access.decision", block.get("decision", _MISSING),
                         "check_access", acc.get("decision"),
                         hint="Read the tool's `decision` key; `outcome` only "
                              "says the call itself succeeded. ")
        block.update(
            reconstruction_load=acc.get("reconstruction_load"),
            budget=acc.get("budget"),
            location_bearing_keys=list(acc.get("location_bearing_keys", [])),
            origin_unknown_keys=list(acc.get("origin_unknown_keys", [])),
            per_place_working=acc.get("per_place_working"))

    est_n = authoritative_call(log_records, "estimate_n")
    _reject_uncovered("estimate_n", _last_ok(log_records, "estimate_n"), required)
    det = authoritative_call(log_records, "estimate_detectability")
    est = out.get("estimability")
    if isinstance(est, dict):
        _reject_mismatch("estimability.n_source", est.get("n_source", _MISSING),
                         "estimate_n", est_n.get("n_source"))
        _reject_mismatch("estimability.analytic_n", est.get("analytic_n", _MISSING),
                         "estimate_n", est_n.get("analytic_n"))
        est["modules_required"] = list(est_n.get("modules_required", []))
        sde = est.get("smallest_detectable_effect")
        filled = _sde_from_curve(
            sde if isinstance(sde, dict) else {}, det, est_n.get("analytic_n"))
        est["smallest_detectable_effect"] = filled
        # THE BLOCKER IS WRITTEN, NOT ASKED FOR. Calling estimate_detectability
        # at all means asserting an outcome frequency this environment cannot
        # confirm, so the admission follows mechanically from the tool log and
        # there is nothing for the model to judge. Leaving it to the model would
        # mean one more rule that fails silently in transduction and costs a
        # repair attempt; the schema still enforces it, so a hand-built record
        # cannot dodge it either.
        if filled.get("asserted_baseline_prevalence") is not None:
            blocked = out.get("blocked_on")
            blocked = list(blocked) if isinstance(blocked, list) else []
            if "outcome_prevalence_unconfirmed" not in blocked:
                blocked.append("outcome_prevalence_unconfirmed")
            out["blocked_on"] = blocked

    _restate_derivation_units(out)

    prov = out.get("provenance")
    if isinstance(prov, dict):
        # The live record listed "resolve_variable(m3:Q16.1_1 through
        # m3:Q16.1_5)" — a call in a form that cannot have been made. A model's
        # recollection of its own research log is not the log.
        prov["tool_calls"] = _render_calls(log_records)
    return out


# --------------------------------------------------------------------------- #
# identity and provenance: the driver owns these, not the tool log and not the
# model
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class RunIdentity:
    """What the driver knows before the model is called at all.

    Every field here was an empty string in the one live record the pipeline had
    produced: protocol_id, dictionary_version and all four populated provenance
    fields. The record saved as a dotfile because its filename is built from
    protocol_id, and `dictionary_version`'s own Field description said it "pins
    this record to a build hash" while nothing pinned it. None of it is the
    model's to write — the driver loaded the dictionary, chose the model, built
    the prompt and counted the funnel, so the driver states them.

    Attributes:
        protocol_id: Filename-safe id for this pair, derived from the pair id.
        dictionary_version: `build/dictionary.json`'s version_hash.
        module_version: The dictionary build's rules_version — which collapse and
            key rules produced the namespace this record's keys are drawn from.
        prompt_hash: Hash of the exact prompt text this run sent.
        model_id: The backend's own name, including the model.
        screened_from: The funnel's enumerated count. The denominator.
        selection_mode: How the pair reached the model. `enumerated_screen`
            whenever a funnel produced it.
        seed: The sample seed, where the backend has one.
    """

    protocol_id: str
    dictionary_version: str
    module_version: str
    prompt_hash: str
    model_id: str
    screened_from: int
    selection_mode: str = "enumerated_screen"
    seed: int | None = None


def protocol_id_for(pair_id: str) -> str:
    """Build a deterministic, filename-safe protocol id from a pair id.

    Args:
        pair_id: The funnel candidate's `pair_id`, e.g. `m3:Q16.1 -> m2:Q5.8`.

    Returns:
        A slug such as `m3q16.1_to_m2q5.8`.
    """
    # Derived, never asked for. The live record's protocol_id was the empty
    # string, so it saved as `run/.<hash>.json` — a dotfile, invisible to `ls`
    # and to every glob in this repo.
    return (pair_id.replace(":", "").replace(" -> ", "_to_")
            .replace(" ", "_").lower())


def apply_record_identity(record: dict[str, Any],
                          identity: RunIdentity) -> dict[str, Any]:
    """Write the fields the driver owns over whatever the model emitted.

    OVERWRITTEN, not rejected on mismatch, for the same reason the tool's working
    is: the model has no discretion over any of them, so a disagreement is a
    transcription slip and discarding the sample would spend a model call to fix
    a copy-paste.

    `selection_mode` and `screened_from` are here because SelectionRationale's
    docstring has claimed since it was written that both "are written by the
    wrapper from the funnel counter, never by the model — which has every
    incentive to keep the denominator small," and no wrapper wrote them. The live
    record's model wrote `selection_mode: externally_posed` for a pair the
    enumerated funnel had handed it, and `_denominator_required_when_enumerated`
    therefore never fired, so the record legally carried `screened_from: null`.

    Args:
        record: The transduced JSON object, as parsed.
        identity: What the driver knows about this run.

    Returns:
        A new dict with the driver-owned fields written. The input is not
        modified.
    """
    if not isinstance(record, dict):
        return record                       # not an object; pydantic says why

    out: dict[str, Any] = json.loads(json.dumps(record))     # deep copy, JSON-safe
    out["protocol_id"] = identity.protocol_id
    out["dictionary_version"] = identity.dictionary_version

    prov = out.get("provenance")
    if not isinstance(prov, dict):
        prov = out["provenance"] = {}
    prov.update(dictionary_version=identity.dictionary_version,
                module_version=identity.module_version,
                prompt_hash=identity.prompt_hash,
                model_id=identity.model_id)
    if identity.seed is not None:
        prov["seed"] = identity.seed

    sel = out.get("selection_rationale")
    if isinstance(sel, dict):
        # Left alone when the transduction omitted the block entirely: pydantic
        # names the missing field better than a half-built one would, and a
        # rationale invented here would be prose no one wrote.
        sel["selection_mode"] = identity.selection_mode
        sel["screened_from"] = identity.screened_from
    return out
