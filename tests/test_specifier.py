"""Tests for the agent layer: registry gating, the mechanical gate, dedup, selection,
and the invariants that keep the environment model-free.

These test the control flow, which is the part deterministic code owns. Nothing
here tests whether the model reasons well — that is unprovable without weights and
is what the benchmark is for.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import specifier as SP
from agent.backends import OpenAICompatBackend, Reply, ScriptedBackend, tool_call
from agent.registry import (
    RETRIEVAL_TOOLS,
    SCHEMAS,
    build_registry,
    true_signature,
)
from env import tools as T
from generate.funnel import load_constructs, run
from generate.run_specifier import (
    ANALYSIS,
    FIXTURE_DESIGN_KEYS,
    REASON_CALLS_A,
    REASON_CALLS_B,
    fixture,
)


@pytest.fixture(scope="module")
def pair():
    C, version = load_constructs()
    e = sorted([c for c in C.values() if c.module == "3"
                and c.base_id.startswith("Q16.")], key=lambda c: c.base_id)
    o = sorted([c for c in C.values() if c.module == "2"
                and c.base_id.startswith("Q5.")], key=lambda c: c.base_id)
    cands, counts = run(e, o)
    p = next(c for c in cands if c.exposure.construct_key == "m3:Q16.1"
             and c.outcome.construct_key == "m2:Q5.8")
    return p, version, counts


def _good_script(record: str) -> list:
    return [Reply(tool_calls=REASON_CALLS_A), Reply(tool_calls=REASON_CALLS_B),
            Reply(content=ANALYSIS), Reply(content=record)]


# --------------------------------------------------------------------------- #
# the environment stays model-free
# --------------------------------------------------------------------------- #

#: Model libraries `env/` is permitted to import. **Empty by default, and only the
#: user may add to it** — `AGENTS.md` §Hard Constraints. A lane that needs one asks;
#: it does not edit this. The blanket no-model ban was lifted 2026-08-31 because it
#: was being engineered around rather than tested, but a grant still has to satisfy
#: the four properties AGENTS.md lists: offline, deterministic, auditable, and
#: selection-neutral-or-measured. This set is where the grant is visible.
ENV_MODEL_GRANTS: frozenset[str] = frozenset()

_NETWORK_IMPORTS = r"requests|httpx|urllib|socket|http|aiohttp"
_MODEL_IMPORTS = r"openai|anthropic|torch|transformers|vllm|sentence_transformers|litellm"


def test_env_never_touches_the_network():
    """The non-negotiable half: `env/` may load weights, never fetch anything.

    A single `import requests` here would mean a tool could reach outside the
    instrument and no test would notice until a benchmark number was already
    published. Network access is the leak channel the contamination argument rests
    on, so unlike the model rule this one has no grant list.
    """
    banned = re.compile(rf"^\s*(?:import|from)\s+({_NETWORK_IMPORTS})\b", re.M)
    for p in (ROOT / "env").rglob("*.py"):
        hits = banned.findall(p.read_text())
        assert not hits, f"{p.name} imports {hits}: env/ must never reach the network"


def test_env_model_imports_are_operator_granted():
    """A model under `env/` is allowed only if the operator wrote it down.

    Not a ban — a ratchet. The failure this prevents is a lane deciding on its own
    that an embedding index is fine, landing weights inside the environment the
    benchmark is measured against, and nothing recording that the decision was ever
    made. Adding a name here is a reviewable act; importing one is not.
    """
    banned = re.compile(rf"^\s*(?:import|from)\s+({_MODEL_IMPORTS})\b", re.M)
    for p in (ROOT / "env").rglob("*.py"):
        ungranted = set(banned.findall(p.read_text())) - ENV_MODEL_GRANTS
        assert not ungranted, (
            f"{p.name} imports {sorted(ungranted)}, which is not in ENV_MODEL_GRANTS. "
            "Only the user may grant a model to env/, and the grant must satisfy "
            "AGENTS.md §Hard Constraints: offline, deterministic, auditable, "
            "selection-neutral or measured.")


def test_only_the_backend_module_opens_a_connection():
    net = re.compile(r"^\s*(?:import|from)\s+(urllib|requests|httpx|socket)\b", re.M)
    offenders = [p.name for p in (ROOT / "agent").rglob("*.py")
                 if net.search(p.read_text()) and p.name != "backends.py"]
    assert offenders == [], f"network access outside the one seam: {offenders}"


# --------------------------------------------------------------------------- #
# registry: contamination control is structural
# --------------------------------------------------------------------------- #

def test_benchmark_registry_contains_no_retrieval_tool():
    calls, _ = build_registry("benchmark")
    assert RETRIEVAL_TOOLS & set(calls) == set()


def test_mode_has_no_default():
    with pytest.raises(TypeError):
        build_registry()


def test_unknown_mode_is_rejected_not_coerced():
    with pytest.raises(ValueError):
        build_registry("Benchmark")


def test_every_exposed_tool_has_a_caller_facing_schema():
    calls, schemas = build_registry("generation")
    assert {s["function"]["name"] for s in schemas} == set(calls)


def test_schemas_declare_required_arguments():
    _, schemas = build_registry("generation")
    rv = next(s for s in schemas if s["function"]["name"] == "resolve_variable")
    assert rv["function"]["parameters"]["required"] == ["key"]


# --------------------------------------------------------------------------- #
# the schema is bound to the function, not written beside it
# --------------------------------------------------------------------------- #

def _real_parameters(tool: str) -> dict:
    """The parameters of the tool itself, past `env.tools._logged`."""
    return dict(true_signature(T.TOOLS[tool]).parameters)


def test_the_unwrap_actually_reaches_the_signature_logged_erased():
    """Positive control for every test below that reads a real signature.

    `_logged` wraps each tool in `(*a, **kw)` and sets no `__wrapped__`, so a
    schema check that used `inspect.signature` naively would compare against
    `{a, kw}`, pass on any property name whatsoever, and report `clean` for a
    binding it never made. If the unwrap ever silently stops working this fails
    here, naming the defect, rather than turning the two tests below into
    tautologies.
    """
    params = _real_parameters("search_variables")
    assert list(params) == ["phrase", "limit"], (
        f"unwrap did not reach search_variables; got {list(params)}. A "
        f"signature of ['a', 'kw'] means _logged was never unwrapped.")


def test_every_advertised_parameter_carries_a_description():
    """A parameter the model is shown and not told how to use.

    MEASURED 2026-08-31, before the schemas were generated: five of twelve tools
    shipped a parameter with no description at all. `search_variables.limit` was
    one, and it changed a protocol — the model passed limit=5 on 130 of 347
    phrase-bearing searches, which is a cutoff it was never told was a cutoff.
    Hand-written schemas made that omission invisible; a Field description cannot
    go missing without this going red.
    """
    missing = [f"{tool}.{name}"
               for tool, schema in SCHEMAS.items()
               for name, spec in schema["parameters"]["properties"].items()
               if not str(spec.get("description", "")).strip()]
    assert missing == [], (
        f"advertised to the model with no instruction: {missing}. Add a "
        f"Field(description=...) on the tool's argument model in agent/registry.py.")


def test_every_advertised_parameter_is_a_real_parameter_of_the_real_function():
    """The schema and the function cannot drift apart unnoticed.

    Checked against the signature under `_logged`, not against the wrapper: the
    wrapper takes `(*a, **kw)` and would accept an advertised parameter that no
    longer exists, which is how a model spends a whole tool loop on an argument
    the environment silently drops.

    Defaults are compared too. A schema saying `default: 10` while the function
    means something else is a promise the model plans around and the environment
    does not keep.
    """
    for tool, schema in SCHEMAS.items():
        real = _real_parameters(tool)
        props = schema["parameters"]["properties"]
        assert set(props) <= set(real), (
            f"{tool} advertises {sorted(set(props) - set(real))}, which is not a "
            f"parameter of the function")
        for name, spec in props.items():
            if "default" in spec:
                assert spec["default"] == real[name].default, (
                    f"{tool}.{name} is advertised as defaulting to "
                    f"{spec['default']!r}; the function defaults to "
                    f"{real[name].default!r}")
        required = set(schema["parameters"].get("required", []))
        unadvertised = {n for n, p in real.items()
                        if p.default is inspect.Parameter.empty} - required
        assert unadvertised == set(), (
            f"{tool} requires {sorted(unadvertised)} and never tells the model, "
            f"so every call the model can construct raises")


@pytest.mark.parametrize("wrong", ["query", "search_term", "q"])
def test_a_misnamed_argument_is_told_which_parameter_was_wanted(wrong):
    """The error has to name the parameter the tool wanted, not the one guessed.

    MEASURED 2026-08-31 over `run/*.tool_log.jsonl` + `run/superseded/` +
    `run/logs/`: 59 of 406 `search_variables` calls died on the argument name —
    `query` 33, `search_term` 14, `q` 12. CPython's message ("got an unexpected
    keyword argument 'query'") repeats the caller's own invention back at it and
    never says `phrase`, and `mcp/compass_server.py::_call` hands exactly that
    text to the model, so the model had nothing to correct towards.
    """
    calls, _ = build_registry("benchmark")
    with pytest.raises(TypeError) as exc:
        calls["search_variables"](**{wrong: "sex gender male female"})
    message = str(exc.value)
    assert "phrase" in message, (
        f"a caller that guessed {wrong!r} is not told the parameter is "
        f"'phrase': {message}")
    assert wrong in message, (
        f"the error does not say which argument was rejected: {message}")


def test_a_missing_required_argument_is_named_with_the_others():
    calls, _ = build_registry("benchmark")
    with pytest.raises(TypeError) as exc:
        calls["get_design_convention"]()
    assert "topic" in str(exc.value)


def test_a_parameter_withheld_from_the_schema_is_still_accepted():
    """Unadvertised is not forbidden, and the difference is load-bearing.

    `n_values`, `alpha` and `power` are deliberately absent from
    `estimate_detectability`'s schema — a parameter in the schema is an
    invitation — while the tool still ACCEPTS them and refuses them in its log.
    `agent/tool_authority.py` rejects a record whose estimate_detectability call
    came back anything but `ok`, so a name check that rejected these would turn a
    guessed argument into a failed gate instead of a refused grid. The check
    therefore rejects a name only when it is neither advertised nor real.
    """
    calls, _ = build_registry("benchmark")
    props = SCHEMAS["estimate_detectability"]["parameters"]["properties"]
    assert set(props) == {"baseline_prevalence"}
    out = calls["estimate_detectability"](baseline_prevalence=0.30,
                                          n_values=[50, 100, 150])
    assert out["outcome"] == "ok"
    assert out["n_grid_refused"] == [50, 100, 150]


def test_the_limit_parameter_says_what_a_small_limit_costs():
    """`limit` is a cutoff, and the caller has to be told that word.

    The measured failure was not that the model set a bad limit; it is that
    `limit=5` reads like a preference for a shorter answer and is actually a
    decision to not see the sixth candidate. A description that only restated
    the type would leave that failure exactly where it was.
    """
    spec = SCHEMAS["search_variables"]["parameters"]["properties"]["limit"]
    assert spec["default"] == 10
    assert "cutoff" in spec["description"].lower(), (
        "limit's description does not tell the caller it is a cutoff: "
        f"{spec['description']!r}")


# --------------------------------------------------------------------------- #
# the gate is mechanical
# --------------------------------------------------------------------------- #

def test_gate_refuses_a_record_whose_lookups_never_happened(pair):
    p, version, counts = pair
    backend = ScriptedBackend([Reply(tool_calls=REASON_CALLS_A),
                               Reply(content=ANALYSIS)])
    a = SP.specify_once(backend, p, seed=0)
    assert a.gate == "missing_calls"
    assert a.protocol is None
    for missing in ("check_access", "estimate_n", "estimate_detectability"):
        assert missing in a.error


def test_gate_passing_costs_a_second_model_call(pair):
    """Proves the flow really is two calls, not one. If a future refactor merged
    them, this count drops and the format tax comes back.
    """
    p, version, counts = pair
    backend = ScriptedBackend(_good_script(fixture(version, counts["enumerated"])))
    SP.specify_once(backend, p, seed=0)
    assert backend.i == 4          # 3 reasoning turns + 1 transduction


def test_only_the_transduction_call_is_schema_constrained(pair):
    p, version, counts = pair
    seen = []

    class Spy(ScriptedBackend):
        def chat(self, messages, **kw):
            seen.append(kw.get("guided_json") is not None)
            return super().chat(messages, **kw)

    b = Spy(_good_script(fixture(version, counts["enumerated"])))
    SP.specify_once(b, p, seed=0)
    assert seen == [False, False, False, True]


def test_tool_loop_is_bounded(pair):
    p, _, _ = pair
    forever = [Reply(tool_calls=[tool_call("registry_coverage", {})])] * 50
    backend = ScriptedBackend(forever)
    a = SP.specify_once(backend, p, seed=0)
    assert a.steps == SP.MAX_STEPS
    assert backend.i == SP.MAX_STEPS


def test_an_unknown_tool_name_is_reported_back_not_raised(pair):
    p, _, _ = pair
    backend = ScriptedBackend([Reply(tool_calls=[tool_call("nope", {})]),
                               Reply(content="done")])
    a = SP.specify_once(backend, p, seed=0)
    assert a.gate == "missing_calls"          # loop survived, gate did its job


# --------------------------------------------------------------------------- #
# dedup and selection
# --------------------------------------------------------------------------- #

def test_reordered_covariates_are_the_same_record(pair):
    """Dedup is by typed-record set equality, not by string. Two samples that
    differ only in the ORDER they listed covariates are one design, and counting
    them as two would inflate every diversity number the project reports.
    """
    p, version, counts = pair
    a = fixture(version, counts["enumerated"])
    b = fixture(version, counts["enumerated"], shuffle=True)
    assert a != b                                          # different JSON
    backend = ScriptedBackend(_good_script(a) + _good_script(b))
    res = SP.specify(backend, p, k=2)
    assert res.distinct == 1


def test_selection_never_consults_the_model(pair):
    """_rank must be a pure function of the records. If it ever grows a term the
    model supplies, a model that rates itself confidently wins by confidence.
    """
    import ast
    import inspect
    body = ast.parse(inspect.getsource(SP._rank)).body[0]
    body.body = [n for n in body.body
                 if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    code = ast.unparse(body)                       # docstring stripped: prose is not logic
    for term in ("backend", "chat(", "score", "judge", "rating"):
        assert term not in code, f"_rank references {term!r}"
    assert "record_hash" in code and "access" in code


def test_recording_a_covariate_gap_does_not_rank_a_record_below_a_silent_one(record):
    """Honesty must not cost a sample its place in the selection order.

    `_rank` orders on `len(p.blocked_on)` ASCENDING, so anything that attaches a
    blocker to a disclosure would rank a record that admits a covariate gap
    strictly BELOW an otherwise identical record that stayed quiet — a penalty on
    the exact behaviour `sought_covariates` exists to elicit. That is why C24's
    enum question was answered "no 8th BlockedOn member", and this is the test
    that keeps the answer. It also goes red if `sought_covariates` is ever folded
    into `canonical_form`, because `record_hash` is the last rank term.
    """
    from agent.schema import ProtocolSpecification
    silent = ProtocolSpecification.model_validate(record)
    disclosing = ProtocolSpecification.model_validate({
        **record,
        "sought_covariates": [{
            "construct_sought": "the respondent's own age at enrolment",
            "search_phrases": ["age", "age at enrollment"],
            "why_rejected": ("the search returned a relative's year of birth, "
                             "which measures somebody else, so it was refused."),
            "exposes_the_estimate_to": ("residual confounding by a common cause "
                                        "of both anchors."),
        }],
    })
    assert disclosing.sought_covariates                    # the gap is on record
    assert SP._rank(silent) == SP._rank(disclosing)


def _disclosing(record: dict) -> str:
    """The same design as `record`, with a covariate gap written down."""
    return json.dumps({**record, "sought_covariates": [{
        "construct_sought": "the respondent's own year of birth",
        "search_phrases": ["year of birth", "how old are you"],
        "why_rejected": ("what came back measures a relative and not the "
                         "respondent, so it was refused."),
        "exposes_the_estimate_to": ("residual confounding by a common cause of "
                                    "both anchors."),
    }]})


@pytest.mark.parametrize("silent_first", [True, False])
def test_a_disclosing_sample_is_not_discarded_for_a_silent_twin(pair, record,
                                                                silent_first):
    """A sample that records a covariate gap must survive dedup against a silent one.

    `sought_covariates` is outside `canonical_form`, so these two samples hash
    IDENTICALLY — that is deliberate and `test_schema` pins it. What was not
    deliberate: dedup used `setdefault`, so the FIRST seed to arrive won, and
    `parked` is `ordered[1:]` over DISTINCT hashes, so the loser was not parked
    either. With a silent seed 0 the disclosing sample left the run entirely and
    the saved record was silent — which is the failure C24 exists to end, since
    20 of 21 saved protocols record no covariate gap at all.

    Parametrised on arrival order because that is the whole point: the outcome
    must not depend on which seed spoke first.
    """
    p, _, _ = pair
    silent = json.dumps(record)
    disclosing = _disclosing(record)
    order = ([silent, disclosing] if silent_first else [disclosing, silent])
    backend = ScriptedBackend(_good_script(order[0]) + _good_script(order[1]))
    res = SP.specify(backend, p, k=2)

    assert res.distinct == 1                     # one design, as canonical_form says
    assert res.selected is not None
    assert res.selected.sought_covariates, "the silent twin won"
    # Not merely "parked instead of deleted" — parked would still be a loss,
    # because the run writes the winner. The disclosing record must WIN.
    assert res.parked == []


def test_the_prompt_names_the_field_the_schema_gives_the_model(record):
    """A field the model is never told about is a field it never fills.

    `undetermined_covariates` shipped with a description saying honest abstention
    is the modal outcome, and 20 of 21 saved records still recorded no covariate
    gap of any kind. A shape the prompt does not mention does not get used.
    """
    from agent.schema import ProtocolSpecification
    assert "sought_covariates" in ProtocolSpecification.model_json_schema()["properties"]
    assert "sought_covariates" in SP.SYSTEM


def test_no_valid_sample_is_reported_not_papered_over(pair):
    p, _, _ = pair
    backend = ScriptedBackend([Reply(tool_calls=REASON_CALLS_A),
                               Reply(content=ANALYSIS)] * 2)
    res = SP.specify(backend, p, k=2)
    assert res.selected is None
    assert "no sample produced a valid record" in res.reason


def test_transduction_repairs_are_bounded_and_the_bound_is_spent(pair):
    """The repair loop is bounded, and it uses the whole budget before giving up.

    The bound was 2 attempts and is now MAX_TRANSDUCE_ATTEMPTS: at 2, five live
    Haiku runs produced zero valid records and failed on five DIFFERENT single
    validators. pydantic raises on the first failing model_validator, so an
    attempt that repairs the error it was shown can still surface the next one.
    """
    p, _, _ = pair
    bad = '{"protocol_id":"P-1"}'
    backend = ScriptedBackend(
        [Reply(tool_calls=REASON_CALLS_A), Reply(tool_calls=REASON_CALLS_B),
         Reply(content=ANALYSIS)]
        + [Reply(content=bad) for _ in range(SP.MAX_TRANSDUCE_ATTEMPTS)])
    a = SP.specify_once(backend, p, seed=0)
    assert a.gate == "invalid_record"
    assert a.attempts == SP.MAX_TRANSDUCE_ATTEMPTS
    assert backend.i == 3 + SP.MAX_TRANSDUCE_ATTEMPTS
    # The rejected object is kept: diagnosing a failed live run must not cost
    # another paid run.
    assert a.rejected == bad


def test_a_repairable_record_is_repaired_within_the_budget(pair):
    """A sample that fixes itself on a later attempt still counts as valid."""
    p, version, counts = pair
    good = fixture(version, counts["enumerated"])
    backend = ScriptedBackend(
        [Reply(tool_calls=REASON_CALLS_A), Reply(tool_calls=REASON_CALLS_B),
         Reply(content=ANALYSIS),
         Reply(content='{"protocol_id":"P-1"}'),
         Reply(content='{"protocol_id":"P-1","question":"still wrong"}'),
         Reply(content=good)])
    a = SP.specify_once(backend, p, seed=0)
    assert a.ok, a.error
    assert a.attempts == 3


# --------------------------------------------------------------------------- #
# backend seam
# --------------------------------------------------------------------------- #

def test_backend_refuses_to_degrade_to_prompted_json():
    """Silent fallback to unconstrained JSON would be malformed 30-40% of the
    time on this model class and would be indistinguishable from bad reasoning.
    """
    b = OpenAICompatBackend(model="x", enforce="none")
    with pytest.raises(ValueError, match="Refusing to fall back"):
        b.chat([{"role": "user", "content": "hi"}], guided_json={"type": "object"})


def test_missing_server_names_the_command_that_starts_one():
    b = OpenAICompatBackend(model="Qwen/Qwen3-14B",
                            base_url="http://127.0.0.1:9/v1", timeout=1.0)
    with pytest.raises(RuntimeError, match="vllm serve"):
        b.chat([{"role": "user", "content": "hi"}])


def test_scripted_backend_running_out_is_an_error_not_a_silence():
    b = ScriptedBackend([])
    with pytest.raises(AssertionError, match="exhausted"):
        b.chat([])


# --------------------------------------------------------------------------- #
# tool behaviour the agent depends on
# --------------------------------------------------------------------------- #

def test_a_bare_question_id_is_ambiguous_not_a_lucky_guess():
    r = T.resolve_variable(key="Q2.4")
    assert r["outcome"] == "ambiguous"
    assert len(r["candidates"]) > 1


def test_a_grid_stem_is_not_a_variable():
    r = T.resolve_variable(key="group:m3:Q16.1")
    assert r["outcome"] == "group"
    assert "may never name a stem" in r["log"]


def test_an_empty_registry_fails_loudly_rather_than_silently():
    r = T.resolve_variable(key="linked:pm25_annual")
    assert r["outcome"] == "not_found"
    assert "declared but EMPTY" in r["log"]
    assert T.registry_coverage()["registries"]["linked"]["coverage"] == "none"


def test_estimate_n_never_fabricates_a_number():
    r = T.estimate_n(keys=["m1:Q3.11", "m2:Q5.8", "m3:Q16.1_1"])
    assert r["analytic_n"] is None
    assert r["n_source"] == "unknown"
    assert r["blocked_on"] == "module_co_completion_counts"


def test_detectability_needs_no_data_and_returns_a_curve():
    r = T.estimate_detectability(baseline_prevalence=0.32)
    sde = [row["sde_percentage_points"] for row in r["sde_by_n"]]
    assert sde == sorted(sde, reverse=True)     # more n, smaller detectable effect
    assert r["assumptions"]["power"] == 0.80


def test_search_tells_the_model_it_may_not_be_a_source_of_keys():
    r = T.search_variables(phrase="social cohesion", limit=3)
    assert "Do not write any of these keys into a protocol" in r["log"]


def test_excluded_variables_do_not_consume_access_budget():
    """Penalising a protocol for stating its exclusions punishes exactly the
    behaviour the schema exists to encourage.
    """
    r = T.check_access(keys=["m3:Q16.1_1", "m2:Q5.8"])
    assert r["decision"] == "pass"
    assert r["reconstruction_load"] == 0


def test_unknown_origin_is_a_distinct_state_from_pass():
    r = T.check_access(keys=["m2:Q5.8", "nonexistent:key"])
    assert r["origin_unknown_keys"] == ["nonexistent:key"]
    assert r["decision"] == "refer"


def test_no_synthetic_profile_tool_exists():
    """A field whose only filler is a simulator gets nullability, not a simulator.
    Zero variables in this instrument carry response coding, so any distribution
    such a tool returned would be fabrication wearing a tool's credibility.
    """
    assert not any("synthetic" in n or "simulate" in n for n in T.TOOLS)


def test_conventions_all_resolve():
    from agent.registry import SCHEMAS
    topics = re.findall(r"(\w[\w:]+)(?=,|\.)", SCHEMAS["get_design_convention"]["description"]
                        .split("Topics:")[1])
    for t in T.CONVENTION_FILES:
        assert T.get_design_convention(topic=t)["outcome"] == "ok"


def test_tool_calls_are_logged_at_the_function_boundary(pair):
    """Logged by the wrapper, not by parsing model output — so a model that
    claims a call it never made cannot forge the log.
    """
    p, version, counts = pair
    backend = ScriptedBackend(_good_script(fixture(version, counts["enumerated"])))
    a = SP.specify_once(backend, p, seed=0)
    assert set(a.tool_names) >= SP.REQUIRED_CALLS


def test_a_construct_key_names_its_next_call():
    """Found live: the model's first call is the construct key the funnel gave
    it. The generic not_found reply pointed at the empty clinical/lab/linked
    registries and cost it several turns of guessing sub-item keys.
    """
    r = T.resolve_variable(key="m3:Q16.1")
    assert r["outcome"] == "construct"
    assert r["group_key"] == "group:m3:Q16.1"
    assert len(r["member_keys"]) == 5
    assert "get_item_group" in r["log"]
    assert "declared but EMPTY" not in r["log"]


def test_construct_outcome_is_distinct_from_group_and_not_found():
    assert T.resolve_variable(key="group:m3:Q16.1")["outcome"] == "group"
    assert T.resolve_variable(key="linked:pm25_annual")["outcome"] == "not_found"
    assert T.resolve_variable(key="m2:Q5.8")["outcome"] == "unique"


def test_the_prompt_names_every_call_the_gate_requires():
    """Found live: Haiku ran 51 tool calls, produced a complete analysis, and was
    rejected for skipping check_access and estimate_detectability — which the
    prompt never asked for. Gating on an unstated requirement is a design bug,
    so the checklist is generated from REQUIRED_CALLS and cannot drift from it.
    """
    for name in SP.REQUIRED_CALLS:
        assert name in SP.SYSTEM, f"gate requires {name} but the prompt never says so"


def test_the_headless_backend_never_runs_in_the_project_directory():
    """VERIFIED LEAK 2026-08-26: with cwd=ROOT, `claude -p` auto-loads the
    project's memory directory, which names MOOSE / MOOSE-Chem / MOOSE-Star /
    HLER / Min-K% and the numbered design decisions. A probe confirmed it. No
    prompt can suppress retrieved context — only the working directory can.
    """
    from agent.cli_backend import ClaudeCliBackend
    b = ClaudeCliBackend()
    assert ROOT not in b.sandbox.parents and b.sandbox != ROOT
    assert b.seal["claude_md_found"] == [], b.seal["claude_md_found"]
    # The cwd is EMPTY of project code: the Specifier reaches the environment
    # over MCP and reads nothing from disk, so anything openable is a leak.
    assert sorted(p.name for p in b.sandbox.iterdir()) == ["mcp_config.json",
                                                          "settings.json"]
    cfg = json.loads(b.mcp_config.read_text())["mcpServers"]["compass"]
    assert Path(cfg["command"]).is_absolute() and Path(cfg["args"][0]).is_absolute()


def test_the_sealed_cwd_name_does_not_name_the_study():
    """Found by the seal's own probe: with prefix 'compass-sealed-' the model
    replied 'NO. However, I notice the working directory is
    /tmp/compass-sealed-..., which suggests this is a COMPASS-related project.'
    The path is context too.
    """
    from agent.sealed import SealedWorktree
    with SealedWorktree() as w:
        low = str(w.cwd).lower()
        for word in ("compass", "cohort", "epi", "survey", "capricorn"):
            assert word not in low, f"cwd path leaks {word!r}: {w.cwd}"


def test_sealed_settings_override_the_users_global_config():
    """A seal that is clean only because the user's global settings happen to be
    harmless is not a seal.
    """
    from agent.sealed import SEALED_SETTINGS
    assert SEALED_SETTINGS["enabledPlugins"] == {}
    assert SEALED_SETTINGS["enableAllProjectMcpServers"] is False
    assert SEALED_SETTINGS["permissions"]["allow"] == []


def test_the_seal_is_hashed_for_provenance():
    from agent.sealed import SealedWorktree
    with SealedWorktree() as a, SealedWorktree() as b:
        assert a.manifest()["seal_hash"] == b.manifest()["seal_hash"]
        assert len(a.manifest()["seal_hash"]) == 16


def test_headless_backend_denies_every_context_bypassing_builtin():
    from agent.cli_backend import DENY
    for t in ("Bash", "Read", "Glob", "Grep", "WebSearch", "WebFetch", "Task"):
        assert t in DENY


def test_seal_probe_reads_the_answer_not_the_formatting():
    """Real replies from the 2026-08-26 verification run. A naive
    startswith('NO') flagged '**NO.**' as a leak; a seal check that cries wolf on
    its own formatting gets ignored, which is worse than not having it.
    """
    from agent.sealed import _answered_yes
    clean = ["NO.", "**NO.**", "NO.\n\nI have no pre-loaded memory",
             "  no — nothing loaded", "None that I can recall."]
    leaked = ["YES — the survey platform is Capricorn (not Qualtrics/REDCap)",
              "**YES**, I recall the COMPASS cohort profile",
              "Yes. PM2.5 and NO2 against central hemodynamics."]
    for t in clean:
        assert not _answered_yes(t), f"false leak on {t!r}"
    for t in leaked:
        assert _answered_yes(t), f"missed leak in {t!r}"


# --------------------------------------------------------------------------- #
# contamination tripwire — tests what the model RECEIVES, not what files say
# --------------------------------------------------------------------------- #

PAPER_MARKERS = ["2,836", "2836", "5,096", "5096", "2,387", "2387", "602",
                 "PM2.5", "PM2·5", "NO2", "WQS", "MAPSCorps", "E2SFCA",
                 "floating catchment", "published COMPASS papers",
                 "colorectal cancer screening among", "benchmark paper"]


def test_no_tool_return_value_leaks_a_published_analysis():
    """The four COMPASS cohort papers (PMIDs 32938600, 36065817, 37252073,
    38715087) describe THIS cohort, so anything the environment hands back that
    is traceable to one of them is contamination the Specifier cannot unsee.

    Found live 2026-08-26: `get_design_convention('small_cells')` returned
    "Realised analytic n in published COMPASS papers ranges 602-2,836" — the
    exact n of PMID 37252073 plus a fifth, unidentified paper — and
    `adjustment_set:area_exposure` named PM2.5 and NO2, the exposures of
    38715087. Both are served by a tool the model calls. This checks the RETURN
    VALUES rather than the files, because that is what reaches the model.
    """
    calls, _ = build_registry("generation")
    offenders = []
    for topic in T.CONVENTION_FILES:
        text = calls["get_design_convention"](topic=topic)["text"]
        for m in PAPER_MARKERS:
            if m in text:
                offenders.append(f"get_design_convention({topic!r}) -> {m!r}")
    for did in calls["list_derivations"]()["derivations"]:
        blob = json.dumps(calls["get_derivation"](derivation_id=did))
        for m in PAPER_MARKERS:
            if m in blob:
                offenders.append(f"get_derivation({did!r}) -> {m!r}")
    assert not offenders, "tool output leaks published-analysis content: " + "; ".join(offenders)


def test_the_prompt_the_model_sees_carries_no_paper_content():
    """SYSTEM plus user_prompt is the entire instruction surface. If a funnel tag
    such as `prior_work` is ever piped into user_prompt, a known_analyses
    registry would flow straight into the prompt — which is exactly the path the
    held-out registry exists to avoid.
    """
    C, _ = load_constructs()
    e = sorted([c for c in C.values() if c.module == "3"
                and c.base_id.startswith("Q16.")], key=lambda c: c.base_id)
    o = sorted([c for c in C.values() if c.module == "2"
                and c.base_id.startswith("Q5.")], key=lambda c: c.base_id)
    cands, _ = run(e, o)
    surface = SP.SYSTEM + SP.user_prompt(cands[0])
    for m in PAPER_MARKERS + ["prior_work", "PMID"]:
        assert m not in surface, f"prompt surface leaks {m!r}"


def test_contamination_check_passes_offline():
    """The full check, as a test, so it cannot be forgotten. The --live seal
    probes are excluded here because they cost money and need a model; run
    `python -m benchmark.contamination_check --live` before a benchmark run.
    """
    from benchmark.contamination_check import (
        check_holdout_not_reachable,
        check_markers,
        check_provenance,
        check_seal_config,
        model_visible_surface,
    )
    problems = (check_markers(model_visible_surface()) + check_provenance()
                + check_seal_config() + check_holdout_not_reachable())
    assert not problems, "\n".join(problems)


def test_the_check_actually_catches_a_planted_leak():
    """A check that has never failed is not known to work. Plant the anchor
    paper's n into a convention and confirm the scan sees it.

    Both written forms, and both boundaries. `check_markers` stopped matching a
    numeric marker as a bare substring on 2026-09-02 — a 1,400-item numbered
    catalogue collided with every numeric marker below 1,400 — so the forms
    that actually leak are planted here explicitly: separated, unseparated, in
    prose, in a list literal, and hyphen-bounded.
    """
    from benchmark.contamination_check import MARKERS, check_markers
    for planted in ("Realised analytic n in published COMPASS papers is 2,836",
                    "n=2836 after exclusions",
                    "the grid ends at [1000, 2000, 2836]",
                    "ranges 2,387-2,836 across papers"):
        hits = check_markers({"tool:get_design_convention(small_cells)": planted})
        assert hits, f"the scan missed a planted figure: {planted!r}"
    assert "2836" in MARKERS and "PM2.5" in MARKERS


# --------------------------------------------------------------------------- #
# tool authority: the environment owns the gate fields, not the model
# --------------------------------------------------------------------------- #

# The fixture record's own design key set, imported rather than restated so the
# two cannot drift: the argument binding compares the call against the record,
# and a test that hand-copies one of them stops testing the other.
FIXTURE_KEYS = FIXTURE_DESIGN_KEYS


def _log_row(call: dict) -> dict:
    """One tool-log row, with the outcome the tool actually returned.

    The fixtures used to hardcode `"outcome": "ok"` for every tool while calling
    the real tool on the next line. `resolve_variable` never returns `ok` — over
    the 15 logs in `run/logs/` it records `unique`, `construct` or `not_found`,
    and `mcp/compass_server.py::_log` writes `out.get("outcome", "ok")` — so the
    fixture described a system that does not exist and `_gate` could not tell a
    resolved anchor from an unresolved one.

    Args:
        call: An OpenAI-shaped tool call from the REASON_CALLS fixtures.

    Returns:
        The log row, with `result` and `outcome` both taken from the real call.
    """
    name = call["function"]["name"]
    args = json.loads(call["function"]["arguments"])
    result = getattr(T, name)(**args)
    return {"tool": name, "args": args,
            "outcome": result.get("outcome", "ok"), "result": result}


def _authoritative_log(keys=None, baseline=0.32) -> list[dict]:
    """Build the three log entries a record's gate fields are checked against.

    Built by CALLING the real tools rather than by hand-writing their output, so
    a test cannot pass against numbers the environment does not actually return.
    """
    keys = keys or FIXTURE_KEYS
    return [
        {"tool": "estimate_n", "args": {"keys": keys}, "outcome": "ok",
         "result": T.estimate_n(keys=keys)},
        {"tool": "estimate_detectability",
         "args": {"baseline_prevalence": baseline}, "outcome": "ok",
         "result": T.estimate_detectability(baseline_prevalence=baseline)},
        {"tool": "check_access", "args": {"keys": keys}, "outcome": "ok",
         "result": T.check_access(keys=keys)},
    ]


@pytest.fixture
def record(pair):
    _, version, counts = pair
    return json.loads(fixture(version, counts["enumerated"]))


def test_the_budget_the_gate_divides_by_is_the_tools_not_the_models(record):
    """The budget is overwritten from check_access, never transcribed.

    The one live record held `budget: 0` while check_access returned 3, so the
    gate read "reconstruction_load 0 / budget 0" and passed trivially. A model
    that writes its own gate verdict is not gated.
    """
    from agent.tool_authority import apply_tool_authority
    record["access"]["budget"] = 0
    record["access"]["per_place_working"] = "No place-based linked measures needed."
    out = apply_tool_authority(record, _authoritative_log())
    assert out["access"]["budget"] == T.check_access(keys=FIXTURE_KEYS)["budget"]
    assert out["access"]["per_place_working"] == "no location-bearing variable named"


def test_a_gate_verdict_that_contradicts_the_log_is_rejected(record):
    """A decision is rejected on mismatch rather than silently corrected.

    Correcting it would leave every other field standing on a premise the
    environment denied, and `status` is derived from it, so flipping it behind
    the validator produces a record its own status check would have refused.
    """
    from agent.tool_authority import GateMismatch, apply_tool_authority
    refer = _authoritative_log(keys=[*FIXTURE_KEYS, "nonexistent:key"])
    assert refer[-1]["result"]["decision"] == "refer"       # the tool's verdict
    with pytest.raises(GateMismatch, match=r"access\.decision"):
        apply_tool_authority(record, refer)


def test_a_fabricated_n_is_rejected_rather_than_quietly_repaired(record):
    """An asserted sample size fails; it is not patched.

    §5 rule 5: never invent a sample size. estimate_n returns null/unknown for
    every cross-module set in this instrument, so a record naming an n has
    asserted one, and asserting it is the failure, not a typo.
    """
    from agent.tool_authority import GateMismatch, apply_tool_authority
    record["estimability"]["n_source"] = "computed_from_counts"
    record["estimability"]["analytic_n"] = 1200
    with pytest.raises(GateMismatch, match="n_source"):
        apply_tool_authority(record, _authoritative_log())


def test_a_detectable_effect_that_is_not_on_the_curve_is_rejected(record):
    """An at_n between two curve points is an invented floor.

    The scripted fixture carried 2.1 pp at n=1800. estimate_detectability
    returns a curve at [500, 1000, 1500, 2000, 2836] and returned neither
    number, so the falsifier was compared against something no tool produced.
    """
    from agent.tool_authority import GateMismatch, apply_tool_authority
    record["estimability"]["smallest_detectable_effect"] = {
        "value": 2.1, "unit": "percentage points", "at_n": 1800,
        "assumptions": "two-sided alpha 0.05, power 0.80"}
    with pytest.raises(GateMismatch, match="at_n=1800"):
        apply_tool_authority(record, _authoritative_log())


def test_an_off_curve_value_with_no_at_n_is_rejected(record):
    """A value that matches no row on the curve is an assertion."""
    from agent.tool_authority import GateMismatch, apply_tool_authority
    record["estimability"]["smallest_detectable_effect"] = {
        "value": 0.4, "unit": "percentage points", "at_n": None,
        "assumptions": "two-sided alpha 0.05, power 0.80"}
    with pytest.raises(GateMismatch, match="appears nowhere on"):
        apply_tool_authority(record, _authoritative_log())


def test_a_null_detectable_effect_is_filled_from_the_runs_own_curve(record):
    """A null value is post-filled at the smallest candidate n.

    T1 item 2: `value` became required and no prompt asked for it, which broke
    live runs. Post-filling runs BEFORE validation for exactly this reason —
    `_falsifier_is_detectable` rejects a null value, so filling it afterwards
    would never get the chance.
    """
    from agent.tool_authority import apply_tool_authority
    record["estimability"]["smallest_detectable_effect"] = {
        "value": None, "unit": None, "at_n": None, "assumptions": "prose only"}
    out = apply_tool_authority(record, _authoritative_log())
    sde = out["estimability"]["smallest_detectable_effect"]
    curve = T.estimate_detectability(baseline_prevalence=0.32)["sde_by_n"]
    floor = min(curve, key=lambda r: r["n"])
    assert (sde["at_n"], sde["value"]) == (floor["n"],
                                          floor["sde_percentage_points"])
    assert sde["unit"] == "percentage points"


def test_a_required_gate_call_that_errored_is_a_failure_not_a_skip():
    """A failed lookup authorises nothing.

    `not_available` is the shape a benchmark-mode registry withholding returns.
    Reading a failed lookup as "the tool ran" would let a withheld tool
    authorise a field.
    """
    from agent.tool_authority import GateMismatch, authoritative_call
    log = [r for r in _authoritative_log() if r["tool"] != "check_access"]
    log.append({"tool": "check_access", "args": {}, "outcome": "not_available",
                "result": {"outcome": "not_available"}})
    with pytest.raises(GateMismatch, match="came back"):
        authoritative_call(log, "check_access")


def test_a_call_that_never_happened_authorises_nothing():
    """An absent required call is a gate failure, not a skipped comparison."""
    from agent.tool_authority import GateMismatch, authoritative_call
    log = [r for r in _authoritative_log() if r["tool"] != "check_access"]
    with pytest.raises(GateMismatch, match="does not appear in this run"):
        authoritative_call(log, "check_access")


def test_a_log_written_before_results_were_stored_authorises_nothing():
    """A log with no `result` field must fail loudly, not compare vacuously.

    Logs written before mcp/compass_server.py::_log stored return values carry
    name, args and outcome only. Checking a record against one of those checks
    nothing at all.
    """
    from agent.tool_authority import GateMismatch, authoritative_call
    old = [{k: v for k, v in r.items() if k != "result"}
           for r in _authoritative_log()]
    with pytest.raises(GateMismatch, match="regenerate the log"):
        authoritative_call(old, "check_access")


def test_the_last_successful_check_access_is_the_authoritative_one():
    """The last call is the one that describes the design in the record.

    check_access may be called more than once with different key sets, and the
    prompt tells the model to call it last, once the covariate lists are
    settled, so any earlier call describes a design that is not the one saved.
    """
    from agent.tool_authority import authoritative_call
    log = [*_authoritative_log(keys=[*FIXTURE_KEYS, "nonexistent:key"]),
           *_authoritative_log()]
    assert authoritative_call(log, "check_access")["decision"] == "pass"


def test_provenance_tool_calls_are_the_log_not_the_models_recollection(record):
    """provenance.tool_calls is rewritten from the executed log.

    The live record listed `resolve_variable(m3:Q16.1_1 through m3:Q16.1_5)` —
    a call in a form that cannot have been made.
    """
    from agent.tool_authority import apply_tool_authority
    record["provenance"]["tool_calls"] = [
        "resolve_variable(m3:Q16.1_1 through m3:Q16.1_5)", "check_access()"]
    out = apply_tool_authority(record, _authoritative_log())
    assert len(out["provenance"]["tool_calls"]) == 3
    assert not any("through" in c for c in out["provenance"]["tool_calls"])


def test_a_sample_whose_record_misstates_the_budget_is_corrected_end_to_end(pair):
    """The whole path, not just the helper.

    specify_once must hand back a record whose access block is the tool's,
    whatever the transduction wrote into it.
    """
    p, version, counts = pair
    rec = json.loads(fixture(version, counts["enumerated"]))
    rec["access"]["budget"] = 0
    backend = ScriptedBackend(_good_script(json.dumps(rec)))
    a = SP.specify_once(backend, p, seed=0)
    assert a.ok, a.error
    assert a.protocol.access.budget == 3
    assert a.protocol.access.per_place_working == "no location-bearing variable named"


def test_a_sample_whose_access_decision_contradicts_the_log_fails_the_gate(pair):
    """A mismatch costs the sample, after one repair attempt."""
    p, version, counts = pair
    rec = json.loads(fixture(version, counts["enumerated"]))
    rec["access"]["decision"] = "refer"          # the tool returned pass
    script = [*_good_script(json.dumps(rec)),
              *[Reply(content=json.dumps(rec))
                for _ in range(SP.MAX_TRANSDUCE_ATTEMPTS - 1)]]
    a = SP.specify_once(ScriptedBackend(script), p, seed=0)
    assert a.gate == "gate_field_mismatch"
    assert a.protocol is None
    assert "check_access returned" in a.error


def test_each_sample_writes_its_own_tool_log(tmp_path):
    """Every reasoning call gets its own log FILE, on disk, per sample.

    run/tool_log.jsonl was ONE path truncated per sample, so the only log that
    survived a k=5 run belonged to the last sample and no saved record could be
    audited against the calls that produced it.

    This test used to call `_tool_log_path` five times and assert the five
    strings differed. That exercised the path helper, not the behaviour: deleting
    the three lines in `reason` that allocate and record the path left all 151
    tests passing while every sample appended to one file again — the exact
    regression the docstring narrates. It now drives `reason` itself, with only
    the subprocess stubbed, and asserts on the files that actually appear.
    """
    from agent.cli_backend import ClaudeCliBackend

    class NoSubprocess(ClaudeCliBackend):
        """The real reason(), minus the `claude -p` call it cannot make here."""

        def _run(self, argv: list[str]) -> str:
            # Written by the MCP server in a real run; written here so the
            # assertion below is about a file with a sample's calls in it.
            self.tool_log.write_text(
                json.dumps({"tool": "resolve_variable", "args": {},
                            "outcome": "ok", "result": {}}) + "\n")
            return "analysis"

    b = NoSubprocess(tool_log_dir=tmp_path)
    for _ in range(3):
        b.reason("system", "prompt", ["resolve_variable"])

    written = sorted(tmp_path.glob("*.jsonl"))
    assert len(written) == 3, [x.name for x in written]
    assert len(b.tool_logs) == 3 and len(set(b.tool_logs)) == 3
    assert all(f.read_text().count("\n") == 1 for f in written), (
        "a sample appended to a previous sample's log")
    assert all(f.name != "tool_log.jsonl" for f in written)
    assert b.read_tool_log()[0]["tool"] == "resolve_variable"


def test_the_prompt_states_the_falsifier_rule_the_code_actually_enforces(record):
    """No constraint is enforced that the prompt does not state — and vice versa.

    This test used to assert only that the string "SMALLEST candidate n" appeared
    in the prompt. It passed while the code enforced something else entirely: any
    on-curve at_n the model named was honoured, so a 3.0 pp threshold cleared a
    25.68 pp floor. A string search cannot catch that, which is why the prompt
    half and the behaviour half are now the same test.
    """
    from agent.schema import ProtocolSpecification
    C, _ = load_constructs()
    e = sorted([c for c in C.values() if c.module == "3"
                and c.base_id.startswith("Q16.")], key=lambda c: c.base_id)
    o = sorted([c for c in C.values() if c.module == "2"
                and c.base_id.startswith("Q5.")], key=lambda c: c.base_id)
    cands, _ = run(e, o)
    surface = SP.SYSTEM + SP.user_prompt(cands[0])
    assert "the candidate n you claim it is detectable at" in surface
    assert "Name one n ON that curve" in surface
    # Round 3: the comparator moved to the caller-independent bound, so the
    # prompt has to name that bound by the key the tool returns it under. A rule
    # enforced in code and stated in no prompt is the failure this project has
    # hit repeatedly, and the previous wording actively pointed the model at the
    # wrong curve — "a threshold at or above the curve's value there".
    assert "sde_by_n_worst_case_prevalence" in surface
    assert "NOT AGAINST `sde_by_n`" in surface

    # And the code does that, on the same fixture the prompt describes: at the n
    # the record names, at or above the BOUND's value there. The asserted curve
    # sits below the bound at every n, so a threshold on the asserted curve is
    # exactly the record that must now be refused.
    curve, bound = _curve(), _bound()
    assert curve[1000] < bound[1000], "the bound must not be reachable by asserting"
    ProtocolSpecification.model_validate(
        _apply(_with_sde(dict(record), 1000, bound[1000])))
    with pytest.raises(ValueError, match="below the smallest detectable effect"):
        ProtocolSpecification.model_validate(
            _apply(_with_sde(dict(record), 1000, bound[1000] - 0.01)))
    # The record that passed under the old rule and must not pass under this one.
    with pytest.raises(ValueError, match="MAXIMISES the detectable effect"):
        ProtocolSpecification.model_validate(
            _apply(_with_sde(dict(record), 1000, curve[1000])))


def test_the_fixtures_detectability_numbers_are_on_the_environments_curve() -> None:
    """The scripted fixture's SDE must be a point on the grid the environment uses.

    Merging lane-a and lane-b on 2026-08-26 produced seven failures at once: the
    fixture pinned `at_n=500` from the old DETECTABILITY_N_GRID while the grid had
    been scrubbed to remove a published paper's analytic n. Neither branch failed
    alone and git saw no textual conflict, because the two edits never touched the
    same line. This turns the next such drift into one failure that names the
    cause instead of seven that do not.

    Raises:
        AssertionError: If the fixture's at_n is off the grid, its value is not
            the curve's value there, or its falsifier no longer clears the floor.
    """
    from env.tools import DETECTABILITY_N_GRID, estimate_detectability

    _, version = load_constructs()
    record = json.loads(fixture(version, 384))
    sde = record["estimability"]["smallest_detectable_effect"]
    prevalence = next(
        json.loads(c["function"]["arguments"])["baseline_prevalence"]
        for c in REASON_CALLS_B
        if c["function"]["name"] == "estimate_detectability")
    curve = {p["n"]: p["sde_percentage_points"]
             for p in estimate_detectability(
                 baseline_prevalence=prevalence)["sde_by_n"]}

    assert sde["at_n"] in curve, (
        f"fixture at_n={sde['at_n']} is not on DETECTABILITY_N_GRID "
        f"{DETECTABILITY_N_GRID}; agent/tool_authority.py rejects an off-curve "
        f"at_n rather than repairing it, so every fixture-driven test fails.")
    assert sde["value"] == curve[sde["at_n"]]
    # AGAINST THE BOUND, NOT AGAINST ITS OWN CURVE. Asserting `> sde["value"]`
    # let the fixture clear a floor computed under the prevalence the fixture's
    # own tool call chose; the schema now compares against the caller-independent
    # bound, which is strictly larger, so the fixture has to clear that instead.
    bound = {p["n"]: p["sde_percentage_points"]
             for p in estimate_detectability(
                 baseline_prevalence=prevalence)["sde_by_n_worst_case_prevalence"]}
    assert record["falsifier_threshold"]["value"] >= bound[sde["at_n"]], (
        f"fixture falsifier {record['falsifier_threshold']['value']} pp no longer "
        f"clears the caller-independent bound {bound[sde['at_n']]} pp at "
        f"n={sde['at_n']}; agent/schema.py rejects it, so every fixture-driven "
        f"test fails. Raise the fixture's threshold — do not lower the bound.")


# --------------------------------------------------------------------------- #
# the floor is the environment's, whatever at_n the record names
# --------------------------------------------------------------------------- #

def _curve(baseline: float = 0.32) -> dict[int, float]:
    return {r["n"]: r["sde_percentage_points"]
            for r in T.estimate_detectability(baseline_prevalence=baseline)["sde_by_n"]}


def _bound(baseline: float = 0.32) -> dict[int, float]:
    """The caller-independent floor a falsifier is actually checked against.

    Args:
        baseline: The asserted outcome frequency passed to the tool. It does not
            change the returned bound — that is the whole point of the bound, and
            a test that could not vary this could not show it.

    Returns:
        `{n: smallest detectable effect}` at the frequency that maximises it.
    """
    return {r["n"]: r["sde_percentage_points"]
            for r in T.estimate_detectability(
                baseline_prevalence=baseline)["sde_by_n_worst_case_prevalence"]}


def _apply(record) -> dict:
    """Run the record through tool authority against the standard fixture log."""
    from agent.tool_authority import apply_tool_authority
    return apply_tool_authority(record, _authoritative_log())


def _with_sde(record, at_n, threshold, **over: object) -> dict:
    """Point the record's falsifier at one candidate n and set its threshold."""
    record["estimability"]["smallest_detectable_effect"] = {
        "value": None, "unit": None, "at_n": at_n, "assumptions": "prose"}
    record["falsifier_threshold"] = {"value": threshold,
                                     "unit": "percentage points", "comparator": ">="}
    record.update(over)
    return record


def test_the_saved_record_carries_the_whole_curve_not_one_point_off_it(record):
    """SmallestDetectableEffect's docstring always promised the curve.

    "estimate_detectability returns a curve, not a scalar — that is what lets
    this field stay honest while n is unknown", and the record then kept one
    number and threw the curve away. A scalar floor for an unknown n has to be
    either the smallest candidate (which makes every falsifier absurd) or a
    point the model chose (which makes the check vacuous). Carrying the curve is
    what makes `at_n` a disclosure instead of a hidden comparator swap.
    """
    sde = _apply(record)["estimability"]["smallest_detectable_effect"]
    assert [(pt["n"], pt["sde_percentage_points"]) for pt in sde["curve"]] == \
        sorted(_curve().items())


def test_a_threshold_stated_against_a_curve_must_name_the_n_it_needs(record):
    """A magnitude with no n attached is not checkable against a curve.

    §5 rule 5's shape: admit the gap rather than pick a number. The gap here is
    that the smallest detectable effect spans 26.14 pp to 2.61 pp on the current
    grid, and which end applies is a fact about a sample size nobody has
    computed. The record has to say which end it is claiming.
    """
    from agent.schema import ProtocolSpecification
    filled = _apply(_with_sde(record, None, 30.0))
    filled["estimability"]["smallest_detectable_effect"]["at_n"] = None
    with pytest.raises(ValueError, match="at_n is null"):
        ProtocolSpecification.model_validate(filled)


def test_a_falsifier_below_the_floor_at_the_n_it_names_is_rejected(record):
    """The check that still bites, and the one that is pure estimability.

    "Is this threshold detectable at the n you claim, on the curve the
    environment computed" is mechanically answerable and false for a real class
    of records. "Is this threshold worth stating" is a soundness judgment, which
    §5 rule 3 forbids this system from making.
    """
    from agent.schema import ProtocolSpecification
    bound = _bound()
    with pytest.raises(ValueError, match="below the smallest detectable effect"):
        ProtocolSpecification.model_validate(
            _apply(_with_sde(record, 1000, bound[1000] - 0.5)))


def test_a_larger_at_n_is_a_disclosure_not_a_looser_test(record):
    """The bypass is closed by disclosure, not by rejection — argued, not assumed.

    Round 1 let a model name the LARGEST candidate n and thereby pick its own
    comparator: reproduced 2026-08-26 through the real apply_tool_authority and
    the full ProtocolSpecification, at_n=10000 passed a 3.0 pp threshold against
    a curve whose smallest-n value is 25.68 pp, while the prompt said the record
    was checked at the smallest candidate.

    Such a record is now accepted — and it says so. It carries the whole curve,
    it names n=10000, its n_source is unknown, it names the blocker, and
    derive_status therefore holds it at draft. That is a reviewable claim
    ("falsifiable only if this study reaches 10,000") rather than a silent one,
    and it is the claim the record is actually making either way.
    """
    from agent.schema import NSource, ProtocolSpecification, Status
    curve, bound = _curve(), _bound()
    top = max(bound)
    p = ProtocolSpecification.model_validate(
        _apply(_with_sde(record, top, bound[top] + 0.5)))
    assert p.estimability.smallest_detectable_effect.at_n == top
    assert len(p.estimability.smallest_detectable_effect.curve) == len(curve)
    assert p.estimability.n_source is NSource.unknown
    assert p.blocked_on and p.status is Status.draft


def test_a_record_resting_on_an_uncomputed_n_must_name_its_blocker(record):
    """An admitted gap has to be admitted.

    derive_status already holds such a record at draft. Without this it could
    stay silent about WHY, and "n unknown, no blocker named" is exactly the
    shape §5 rule 5 exists to forbid.
    """
    from agent.schema import ProtocolSpecification
    filled = _apply(_with_sde(record, 1000, 20.0, blocked_on=[]))
    with pytest.raises(ValueError, match="names no blocker"):
        ProtocolSpecification.model_validate(filled)


def test_a_record_that_names_no_n_is_checked_at_the_smallest_candidate(record):
    """The fallback cannot flatter a record that declined to commit.

    T1 item 2 also lands here: `value` became required and no prompt asked for
    it, which broke live runs. Post-filling runs BEFORE validation for that
    reason — _falsifier_is_detectable rejects a null value, so filling it
    afterwards would never get the chance.
    """
    record["estimability"]["smallest_detectable_effect"] = {
        "value": None, "unit": None, "at_n": None, "assumptions": "prose only"}
    sde = _apply(record)["estimability"]["smallest_detectable_effect"]
    curve = _curve()
    assert (sde["at_n"], sde["value"]) == (min(curve), curve[min(curve)])
    assert sde["unit"] == "percentage points"


# --------------------------------------------------------------------------- #
# the prevalence the curve rests on is asserted, and cannot move the pass mark
# --------------------------------------------------------------------------- #

def test_the_bound_is_never_below_the_curve_it_replaces() -> None:
    """The property the whole change rests on, checked rather than assumed.

    Gating on the bound is only sound because the bound dominates the asserted
    curve everywhere — otherwise moving the comparator would let some assertions
    through that the old rule caught. The prompt states this to the model as
    "never the smaller of the two numbers", so it has to be true for every
    assertion the tool accepts, not just for the handful seen in the logs.

    Raises:
        AssertionError: If any asserted frequency produces a curve above the
            bound, or if the two never coincide.
    """
    equal_somewhere = False
    for i in range(1, 100):
        r = T.estimate_detectability(baseline_prevalence=i / 100)
        curve = {p["n"]: p["sde_percentage_points"] for p in r["sde_by_n"]}
        bound = {p["n"]: p["sde_percentage_points"]
                 for p in r["sde_by_n_worst_case_prevalence"]}
        for n, v in curve.items():
            assert bound[n] >= v, f"p={i / 100} n={n}: bound {bound[n]} < curve {v}"
            equal_somewhere |= bound[n] == v
    # And it is REACHABLE: a caller who assumes the maximising frequency is
    # judged against exactly its own curve, which is why the rule costs an honest
    # record nothing.
    assert equal_somewhere


@pytest.mark.parametrize("asserted", [0.25, 0.28, 0.3, 0.32, 0.35, 0.4])
def test_understating_the_prevalence_no_longer_lowers_the_bar(record, asserted):
    """The last input the model could pick its own floor with.

    No tool in this environment returns an outcome frequency — the dictionary's
    coding fields are empty for every item — so `baseline_prevalence` comes from
    the model's own prior. Because the detectable effect scales with the spread
    of that frequency, understating it shrank the floor the model was then judged
    against: measured on 2026-08-27 at n=1000, the asserted floor ranged 7.67 pp
    to 8.68 pp across the six values recorded in this project's own tool logs, a
    13% swing in the model's own pass mark.

    The verdict must now be identical at every one of those values, because the
    comparator is the bound and the bound is not a function of the assertion.
    """
    from agent.schema import ProtocolSpecification
    from agent.tool_authority import apply_tool_authority
    log = _authoritative_log(baseline=asserted)
    bound = _bound()

    def verdict(threshold: float) -> bool:
        """Whether a threshold survives validation under this asserted value."""
        try:
            ProtocolSpecification.model_validate(apply_tool_authority(
                _with_sde(dict(record), 1000, threshold), log))
        except ValueError:
            return False
        return True

    # The asserted curve DOES move — otherwise this test would prove nothing.
    moved = {p["n"]: p["sde_percentage_points"]
             for p in T.estimate_detectability(
                 baseline_prevalence=asserted)["sde_by_n"]}
    assert moved[1000] <= bound[1000]
    # The pass mark does not.
    assert verdict(bound[1000]) is True
    assert verdict(bound[1000] - 0.01) is False


def test_the_asserted_prevalence_is_a_field_not_a_sentence(record):
    """A scorer must not have to parse prose to find the assumption.

    It used to survive only inside the free-text `assumptions` string, as
    "…baseline_prevalence=0.4; worst_case_prevalence=0.5;…". That is the one
    input scaling the whole curve, and nothing could read it mechanically.
    """
    sde = _apply(record)["estimability"]["smallest_detectable_effect"]
    assert sde["asserted_baseline_prevalence"] == 0.32
    assert isinstance(sde["asserted_baseline_prevalence"], float)
    # And it tracks the call actually made, not a default.
    from agent.tool_authority import apply_tool_authority
    other = apply_tool_authority(dict(record), _authoritative_log(baseline=0.25))
    assert (other["estimability"]["smallest_detectable_effect"]
            ["asserted_baseline_prevalence"] == 0.25)


def test_the_bound_is_carried_in_the_record_and_does_not_move(record):
    """Both curves reach the record; only one of them answers to the caller."""
    from agent.tool_authority import apply_tool_authority
    seen = set()
    for asserted in (0.25, 0.32, 0.4):
        sde = apply_tool_authority(
            dict(record), _authoritative_log(baseline=asserted)
        )["estimability"]["smallest_detectable_effect"]
        assert sde["curve"], "the disclosed curve must still be in the record"
        seen.add(tuple((p["n"], p["sde_percentage_points"])
                       for p in sde["worst_case_curve"]))
    assert len(seen) == 1, f"the bound moved with the assertion: {seen}"
    assert dict(seen.pop()) == _bound()


def test_an_asserted_prevalence_forces_the_blocker_and_holds_the_record_at_draft(
        record):
    """§5 rule 5's shape, applied to the same class of quantity as the n.

    The blocker is written by tool authority rather than asked of the model,
    because calling estimate_detectability at all means asserting the frequency —
    there is nothing for the model to judge, and a rule the model must remember
    is a rule that fails silently in transduction.
    """
    from agent.schema import BlockedOn, ProtocolSpecification, Status
    filled = _apply(_with_sde(dict(record), 1000, _bound()[1000]))
    assert "outcome_prevalence_unconfirmed" in filled["blocked_on"]
    p = ProtocolSpecification.model_validate(filled)
    assert BlockedOn.outcome_prevalence_unconfirmed in p.blocked_on
    assert p.status is Status.draft


def test_the_prevalence_blocker_cannot_stand_in_for_the_n_blocker(record):
    """A gap admitted about one unknown is not an admission about another.

    tool authority adds the prevalence blocker to every record, so counting it
    towards "n unknown must name a blocker" would make that check unfalsifiable
    overnight — every record would name a blocker and none would be naming one
    about the n.
    """
    from agent.schema import ProtocolSpecification
    filled = _apply(_with_sde(dict(record), 1000, _bound()[1000], blocked_on=[]))
    assert filled["blocked_on"] == ["outcome_prevalence_unconfirmed"]
    with pytest.raises(ValueError, match="names no blocker"):
        ProtocolSpecification.model_validate(filled)


def test_a_record_with_a_curve_but_no_bound_cannot_be_gated(record):
    """The migration signal, not a silent pass.

    estimate_detectability returns both together, so a record holding only the
    asserted curve predates the bound or was edited by hand. Checking it against
    its own curve is what this round removed; passing it unchecked would be
    worse than either.
    """
    from agent.schema import ProtocolSpecification
    filled = _apply(_with_sde(dict(record), 1000, _bound()[1000]))
    filled["estimability"]["smallest_detectable_effect"]["worst_case_curve"] = []
    with pytest.raises(ValueError, match="no worst_case_curve"):
        ProtocolSpecification.model_validate(filled)


def test_a_tool_return_with_no_bound_is_refused_by_tool_authority(record):
    """The gate cannot be disarmed by deleting the field from the tool log."""
    from agent.tool_authority import GateMismatch, apply_tool_authority
    log = _authoritative_log()
    for r in log:
        if r["tool"] == "estimate_detectability":
            r["result"].pop("sde_by_n_worst_case_prevalence")
    with pytest.raises(GateMismatch,
                       match="no sde_by_n_worst_case_prevalence"):
        apply_tool_authority(dict(record), log)


def test_the_floor_moves_to_the_analytic_n_once_the_environment_computes_one():
    """The smallest candidate is the fallback for an unknown n, not a fixed rule.

    Every pair in this instrument carries analytic_n=null today because module
    co-completion counts do not exist. When they arrive, the study's real n is
    the honest floor and pinning the smallest candidate forever would understate
    the design's power. This is the branch that has no live exercise yet.
    """
    from agent.tool_authority import _governing_n
    curve = _curve()
    # A computed analytic n outranks the record's own disclosure: it is the
    # study's real n and no stated candidate can improve on it.
    assert _governing_n(curve, 3000, 10000) == 3000
    # Unknown n: the record's stated candidate governs, else the smallest.
    assert _governing_n(curve, None, 10000) == 10000
    assert _governing_n(curve, None, None) == min(curve)
    # A candidate the curve does not carry falls back rather than interpolating.
    assert _governing_n(curve, 1234, 1234) == min(curve)


# --------------------------------------------------------------------------- #
# T3: the verdict is about the design the record actually names
# --------------------------------------------------------------------------- #

def _log_with(tool: str, keys: list[str]) -> list[dict]:
    """The standard authoritative log with one call's key set replaced."""
    out = []
    for rec in _authoritative_log():
        if rec["tool"] == tool:
            rec = {**rec, "args": {"keys": keys},
                   "result": getattr(T, tool)(keys=keys)}
        out.append(rec)
    return out


def test_check_access_called_on_two_keys_cannot_clear_a_record_naming_more(record):
    """§4 T3's acceptance, verbatim.

    A verdict is only about the design it was computed over. check_access on two
    keys says nothing about the other nine, and stamping its `pass` onto the
    record gives the environment's imprimatur to a design it never saw.
    """
    from agent.tool_authority import GateMismatch, apply_tool_authority
    with pytest.raises(GateMismatch, match=r"check_access was called with 2 key"):
        apply_tool_authority(record, _log_with("check_access",
                                               ["m2:Q5.8", "m1:Q3.11"]))


def test_estimate_n_on_a_subset_cannot_stamp_a_module_list(record):
    """modules_required is OVERWRITTEN, so a subset call writes a wrong value.

    estimate_n(["m2:Q5.8"]) returns modules_required=['m2']. The record spans
    m1+m2+m3, and the overwrite would hand it a single-module estimability
    block — which also flips `blocked_on` from module_co_completion_counts to
    per_item_non_missing_counts. Overwriting is the right doctrine for a
    transcription and the wrong one for a value computed over the wrong design,
    which is why the binding has to run before the overwrite.
    """
    from agent.tool_authority import GateMismatch, apply_tool_authority
    assert T.estimate_n(keys=["m2:Q5.8"])["modules_required"] == ["m2"]
    with pytest.raises(GateMismatch, match=r"estimate_n was called with 1 key"):
        apply_tool_authority(record, _log_with("estimate_n", ["m2:Q5.8"]))


def test_a_derivation_must_be_passed_as_its_component_keys_not_its_id(record):
    """Found live 2026-08-26: Haiku passed "social_cohesion_scale" to both tools.

    estimate_n dropped it silently and reported the wrong modules; check_access
    flagged it origin_unknown and returned `refer`. The binding names the five
    component keys that went missing instead of leaving the failure to be read
    out of a module list.
    """
    from agent.tool_authority import GateMismatch, apply_tool_authority
    keys = ["social_cohesion_scale", *[k for k in FIXTURE_KEYS
                                       if not k.startswith("m3:Q16.1")]]
    with pytest.raises(GateMismatch, match=re.escape("m3:Q16.1_1")):
        apply_tool_authority(record, _log_with("check_access", keys))


def test_a_call_naming_more_keys_than_the_record_is_accepted(record):
    """Coverage, not equality — and the asymmetry is the point.

    A superset can only make both verdicts stricter: extra keys add
    reconstruction load, add origin_unknown keys and add modules, never remove
    them. A SUBSET is the flattering direction. Requiring equality would also
    reject the conservative behaviour of passing an excluded key.
    """
    from agent.tool_authority import apply_tool_authority
    extra = [*FIXTURE_KEYS, "m3:Q2.33", "m3:Q2.62"]
    out = apply_tool_authority(record, _log_with("estimate_n", extra))
    assert out["estimability"]["modules_required"] == ["m1", "m2", "m3"]


def test_keys_only_in_the_excluded_list_are_not_required_by_the_binding(record):
    """Stating an exclusion must not cost the record anything.

    check_access's docstring says deliberately excluded variables consume no
    budget, and the tool takes a flat key list with no way to tell an exclusion
    from an adjustment — so the only way that contract holds is for the caller
    not to pass them. STATED CONSEQUENCE: a location-bearing variable parked in
    excluded_variables is exempt from the access budget by design.
    """
    from agent.tool_authority import design_keys
    excluded = {e["variable"]["key"] for e in record["excluded_variables"]}
    assert excluded and not (excluded & design_keys(record))


def test_the_live_records_own_calls_did_cover_the_design_it_names():
    """Checked, not assumed — and it contradicts what this lane was told.

    The live record names 46 distinct keys across its text, and its estimate_n
    and check_access calls named 13. But 30 of those 46 are the component keys
    of a derivation that appears ONLY in excluded_variables, and 2 more are that
    derivation's signed pair, which the model did pass. In the positions the
    binding governs the record names 11, and both calls covered all 11. The live
    record is a failing case for items 1, 4 and 5 — it is not one for T3.
    """
    from agent.tool_authority import design_keys
    f = ROOT / "run" / ".fe7cbe643d35ef50.json"
    log = ROOT / "run" / ".fe7cbe643d35ef50.tool_log.jsonl"
    if not (f.exists() and log.exists()):
        pytest.skip("live record not present")
    rec = json.loads(f.read_text())
    calls = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
    required = design_keys(rec)
    assert len(required) == 11
    for tool in ("check_access", "estimate_n"):
        called = {k for c in calls if c["tool"] == tool
                  for k in c["args"].get("keys", [])}
        assert required <= called, sorted(required - called)


# --------------------------------------------------------------------------- #
# identity and provenance: the driver writes them, not the model
# --------------------------------------------------------------------------- #

def _identity(pair_tuple, **over: object) -> RunIdentity:
    """Build a RunIdentity for the module-scoped pair fixture.

    `from __future__ import annotations` at the top of this module makes the
    return annotation lazy, so the import stays local like every other one here.
    """
    from agent.tool_authority import RunIdentity
    p, version, counts = pair_tuple
    base = dict(protocol_id="m3q16.1_to_m2q5.8", dictionary_version=version,
                module_version="1", prompt_hash=SP.prompt_hash(p),
                model_id="test", screened_from=counts["enumerated"])
    return RunIdentity(**{**base, **over})


def test_the_wrapper_writes_the_identity_the_model_left_blank(pair):
    """Pinned on the live record: six empty strings, all of them known in Python.

    The driver loaded the dictionary, chose the model, built the prompt and
    counted the funnel before the model was called at all.
    """
    from agent.tool_authority import apply_record_identity
    f = ROOT / "run" / ".fe7cbe643d35ef50.json"
    if not f.exists():
        pytest.skip("live record not present")
    rec = json.loads(f.read_text())
    assert rec["protocol_id"] == "" and rec["provenance"]["model_id"] == ""
    ident = _identity(pair)
    out = apply_record_identity(rec, ident)
    assert out["protocol_id"] == ident.protocol_id
    assert out["dictionary_version"] == ident.dictionary_version
    assert all(out["provenance"][k] for k in
               ("dictionary_version", "module_version", "prompt_hash", "model_id"))
    assert rec["protocol_id"] == ""            # the input is not modified


def test_the_wrapper_writes_the_denominator_the_model_skipped(pair):
    """SelectionRationale's docstring claimed a wrapper wrote these. None did.

    The live model wrote selection_mode='externally_posed' for a pair the
    enumerated funnel handed it, so _denominator_required_when_enumerated never
    fired and the record legally carried screened_from=null. A model that names
    its own selection mode chooses whether the denominator applies to it.
    """
    from agent.tool_authority import apply_record_identity
    _, _, counts = pair
    rec = {"selection_rationale": {"selection_mode": "externally_posed",
                                   "screened_from": None, "prior_work": "x",
                                   "why_this_cohort": "y"}}
    sel = apply_record_identity(rec, _identity(pair))["selection_rationale"]
    assert sel["selection_mode"] == "enumerated_screen"
    assert sel["screened_from"] == counts["enumerated"]


def test_a_sample_carries_the_drivers_identity_end_to_end(pair):
    """The whole path, not just the helper."""
    p, version, counts = pair
    rec = json.loads(fixture(version, counts["enumerated"]))
    rec["protocol_id"] = "whatever-the-model-felt-like"
    rec["provenance"]["model_id"] = ""
    backend = ScriptedBackend(_good_script(json.dumps(rec)))
    a = SP.specify_once(backend, p, seed=3, identity=_identity(pair))
    assert a.ok, a.error
    assert a.protocol.protocol_id == "m3q16.1_to_m2q5.8"
    assert a.protocol.provenance.model_id == "test"
    assert a.protocol.provenance.prompt_hash == SP.prompt_hash(p)
    # The seed is per-sample: a k-fan-out that recorded one seed for every
    # sample would make the provenance block unable to identify a sample.
    assert a.protocol.provenance.seed == 3


def test_the_prompt_hash_changes_when_the_prompt_does(pair):
    """"fixture" and "unset" did this job no better than "" did.

    prompt_hash exists so an ablation can tell "the component changed" from
    "someone edited a prompt and forgot", which needs it to be a function of the
    prompt text.
    """
    p, _, _ = pair
    before = SP.prompt_hash(p)
    original = SP.SYSTEM
    try:
        SP.SYSTEM = SP.SYSTEM + "\n"
        assert SP.prompt_hash(p) != before
    finally:
        SP.SYSTEM = original
    assert SP.prompt_hash(p) == before


# --------------------------------------------------------------------------- #
# the repair attempt has to be able to repair something
# --------------------------------------------------------------------------- #

def test_the_cli_repair_prompt_carries_the_attempt_it_is_repairing(pair):
    """`claude -p` is a fresh session per call, so "fix it" needs an "it".

    Both live runs of 2026-08-26 reported by the orchestrator died on
    `m1:Q3.3 appears in both adjusted and excluded`, across two attempts each,
    while the repair prompt said "Fix ONLY what the error names". It could not:
    on the CLI branch the repair prompt appended the ERROR and never the
    rejected object, and the CLI keeps no conversation state — so the model
    re-derived the record from the same analysis and reproduced the same key in
    both lists. The in-process branch
    appends the assistant turn to `msg` and never had the bug, which is why the
    repair loop looked like it worked.
    """
    p, version, counts = pair
    broken = json.loads(fixture(version, counts["enumerated"]))
    broken["excluded_variables"].append(broken["adjusted_covariates"][0])
    payload = json.dumps(broken)

    seen: list[str] = []

    class CliLike:
        """A backend on the CLI branch: drives its own loop, keeps no state."""

        name = "cli-like"
        drives_own_tool_loop = True
        tool_log: object = None

        def reason(self, system, prompt, names) -> Reply:
            return Reply(content=ANALYSIS)

        def read_tool_log(self) -> list[dict]:
            return [_log_row(c) for c in (*REASON_CALLS_A, *REASON_CALLS_B)]

        def transduce(self, prompt) -> Reply:
            seen.append(prompt)
            return Reply(content=payload)


    a = SP.specify_once(CliLike(), p, seed=0)
    assert a.gate == "invalid_record", a.gate
    assert len(seen) == SP.MAX_TRANSDUCE_ATTEMPTS, "the repairs did not happen"
    assert payload in seen[1], (
        "the repair prompt named an error but not the object it belonged to")
    # And the error travels with it — a repair prompt needs both halves.
    assert a.error and a.error in seen[1]
    assert "cannot appear in excluded_variables" in seen[1]
    # The repair instruction must not forbid the fix the error requires. Its
    # first draft said "remove nothing else" beside an error whose only remedy
    # is a removal, and three live runs across two sessions died on that exact
    # error after BOTH attempts.
    assert "deleting is allowed" in seen[1]


def test_a_derivations_unit_is_copied_from_the_signed_file_not_demanded(record):
    """The transduction call cannot see tool RETURN VALUES, so it cannot copy one.

    `_transduce` renders the research log as `name(args) -> outcome`. Found live
    2026-08-27: Haiku wrote `unit: "scale"` against a signed "mean Likert score,
    5 items" and lost the whole sample across both repair attempts even though
    the rejection quoted the exact string. Demanding a verbatim copy of something
    absent from the prompt is the same defect as enforcing a rule no prompt
    states — so the unit is overwritten, being a pure transcription once the
    model has chosen the derivation_id.
    """
    from agent.schema import ProtocolSpecification
    from agent.tool_authority import apply_tool_authority
    signed = json.loads((ROOT / "curated" / "derivations" /
                         "social_cohesion_scale.json").read_text())
    record["exposure"]["unit"] = "scale"
    out = apply_tool_authority(record, _authoritative_log())
    assert out["exposure"]["unit"] == signed["unit"]
    ProtocolSpecification.model_validate(out)


def test_a_derivations_component_keys_are_not_quietly_restated(record):
    """The keys are the substance and stay a rejection.

    A 30-versus-2 disagreement means the analysis reasoned about a different
    variable set, and the prose lists the keys, so the model can repair it.
    """
    from agent.schema import ProtocolSpecification
    from agent.tool_authority import apply_tool_authority
    record["exposure"]["component_keys"] = ["m3:Q16.1_1"]
    out = apply_tool_authority(record, _authoritative_log())
    assert out["exposure"]["component_keys"] == ["m3:Q16.1_1"]   # not repaired
    with pytest.raises(ValueError, match="declares component_keys"):
        ProtocolSpecification.model_validate(out)


def test_the_transduction_can_see_the_values_it_is_told_to_copy():
    """TRANSDUCE's own sentence was false about its own prompt.

    "Every key, wording, number and blocker must already appear in the analysis
    or the tool log" — and the tool log it was handed rendered as
    `name(args) -> outcome`, return values stripped. Two live failures came out
    of that gap: a paraphrased `quoted_wording` on 2026-08-26 and `unit: "scale"`
    for a signed unit on 2026-08-27. Both read as the model inventing a value
    when it had no way to read one.
    """
    raw = [{"tool": "resolve_variable", "args": {"key": "m2:Q5.8"}, "outcome": "ok",
            "result": T.resolve_variable(key="m2:Q5.8")},
           {"tool": "get_derivation", "args": {"derivation_id": "met_hours_week"},
            "outcome": "ok", "result": T.get_derivation(derivation_id="met_hours_week")},
           {"tool": "search_variables", "args": {"phrase": "x", "limit": 2},
            "outcome": "ok", "result": T.search_variables(phrase="x", limit=2)}]
    out = SP._render_log(T.ToolLog(), raw)
    assert "MET-hours/week" in out, "the signed unit is still unreadable"
    assert T.resolve_variable(key="m2:Q5.8")["quoted_wording"][:40] in out
    # Bounded on purpose: expanding every call inlines 40 kB beside a 20 kB schema.
    assert "returned:" not in out.split("search_variables")[1]


def test_a_log_with_no_captured_results_still_renders():
    """The scripted in-process path predates result capture; it must not crash."""
    log = T.ToolLog()
    log.record("resolve_variable", {"key": "m2:Q5.8"}, "ok", 0.0)
    assert SP._render_log(log, None) == 'resolve_variable({"key": "m2:Q5.8"}) -> ok'


def test_each_repair_sees_one_object_and_one_rejection(pair):
    """The repair prompt is rebuilt, not accumulated.

    Appending grew it by a whole record per attempt, so by the fourth try the
    model read three superseded drafts and three stale errors ahead of the one it
    was asked to fix, on top of a 20 kB schema. Live 2026-08-27: four
    transductions in a row failed to make a two-covariate edit the rejection
    named explicitly.
    """
    seen: list[str] = []
    drafts = [f'{{"protocol_id":"P-{i}"}}' for i in range(SP.MAX_TRANSDUCE_ATTEMPTS)]

    class CliLike:
        name = "cli-like"
        drives_own_tool_loop = True
        tool_log: object = None

        def reason(self, system, prompt, names) -> Reply:
            return Reply(content=ANALYSIS)

        def read_tool_log(self) -> list[dict]:
            return [_log_row(c) for c in (*REASON_CALLS_A, *REASON_CALLS_B)]

        def transduce(self, prompt) -> Reply:
            seen.append(prompt)
            return Reply(content=drafts[len(seen) - 1])

    p, _, _ = pair
    SP.specify_once(CliLike(), p, seed=0)
    assert len(seen) == SP.MAX_TRANSDUCE_ATTEMPTS
    last = seen[-1]
    assert drafts[-2] in last, "the repair does not see the object it must fix"
    for stale in drafts[:-2]:
        assert stale not in last, f"a superseded draft {stale} is still in the prompt"
    assert last.count("--- IT WAS REJECTED ---") == 1
    # And the prompt does not grow without bound across attempts.
    assert len(seen[-1]) - len(seen[1]) < 200


def test_a_threshold_in_another_unit_is_refused_not_waved_through(record):
    """A check that silently abstains is worse than no check.

    The floor comparison was guarded by `t.unit == sde.unit` and simply did not
    happen otherwise, which made the whole of item 1 optional: any threshold in
    any other unit passed in silence. Found in the FIRST green live record,
    2026-08-27 — Haiku wrote `0.68 odds ratio` against a percentage-point curve,
    and the record was accepted with its falsifier compared to nothing.
    """
    from agent.schema import ProtocolSpecification
    filled = _apply(_with_sde(record, 1000, 0.68))
    filled["falsifier_threshold"]["unit"] = "odds ratio"
    with pytest.raises(ValueError, match="cannot be checked against the study"):
        ProtocolSpecification.model_validate(filled)


def test_a_ratio_falsifier_is_allowed_as_prose_with_no_threshold(record):
    """The refusal names an output that is always available.

    A ratio-scale or model-comparison falsifier is legitimate; what it cannot be
    is a numeric threshold this environment can check. `falsifier_threshold` is
    optional precisely so that case has an honest home.
    """
    from agent.schema import ProtocolSpecification
    filled = _apply(_with_sde(record, 1000, 9.0))
    filled["falsifier_threshold"] = None
    filled["falsifier"] = ("CI for the odds ratio excludes 0.68 per quintile of "
                           "the cohesion scale.")
    p = ProtocolSpecification.model_validate(filled)
    assert p.falsifier_threshold is None


def test_the_repair_budget_allows_more_than_one_repair():
    """One repair was measured not to converge; the budget may not go back to it.

    Five live Haiku runs at MAX_TRANSDUCE_ATTEMPTS=2 produced zero valid records
    and failed on five DIFFERENT single validators. pydantic raises on the first
    failing model_validator, so an attempt that fixes the error it was shown can
    still surface the next. This pins the finding, not the number: the tests
    above use the constant symbolically and would keep passing at 2.
    """
    assert SP.MAX_TRANSDUCE_ATTEMPTS >= 3


def test_an_invented_key_is_named_as_invented_not_as_unpassed(record):
    """A repair aimed at the wrong error cannot land.

    Found live 2026-08-27: Haiku wrote `m1:age`, which matches the key pattern
    and exists nowhere. The binding caught it — the model never passed it to
    check_access, because resolve_variable never returned it — but reported it as
    "you did not pass this key", and all four transductions went after that
    instead of after the fabricated key. The SYSTEM prompt calls a plausible
    wrong key "the one failure with no automated detector"; there is one, and it
    has to say what it found.
    """
    from agent.tool_authority import GateMismatch, apply_tool_authority
    record["adjusted_covariates"].append(
        {**record["adjusted_covariates"][0],
         "variable": {"kind": "variable", "key": "m1:age",
                      "quoted_wording": "Age in years"}})
    with pytest.raises(GateMismatch, match="resolve nowhere in the instrument"):
        apply_tool_authority(record, _authoritative_log())


def test_a_real_key_that_was_simply_not_passed_still_says_so(record):
    """The two messages must stay distinct, or the new one swallows the old."""
    from agent.tool_authority import GateMismatch, apply_tool_authority
    with pytest.raises(GateMismatch, match="was called with 2 key"):
        apply_tool_authority(record, _log_with("check_access",
                                               ["m2:Q5.8", "m1:Q3.11"]))


def test_every_list_the_schema_floors_is_floored_in_the_prompt():
    """No constraint is enforced that the prompt does not state — the class of it.

    T1 wrote this lesson up three times as three separate incidents. It is one
    class, and it recurred on 2026-08-27: `excluded_variables` has carried
    min_length=1 since the schema was written, no prompt ever said so, and a live
    run spent all four transductions being told "List should have at least 1
    item" with nothing to tell it that stating an exclusion is a required design
    act rather than a formatting slip.

    This asserts the class, not the instance: any covariate list the schema gives
    a minimum must have that minimum stated in the text the model reads.
    """
    from agent.schema import ProtocolSpecification
    props = ProtocolSpecification.model_json_schema()["properties"]
    surface = SP.SYSTEM + SP.TRANSDUCE
    floored = [n for n in ("adjusted_covariates", "excluded_variables",
                           "undetermined_covariates")
               if props[n].get("minItems")]
    assert floored, "expected the schema to floor at least one covariate list"
    assert "AT LEAST ONE" in surface
    for name in floored:
        word = name.split("_")[0]          # adjusted / excluded / undetermined
        assert word in surface, (
            f"{name} has minItems={props[name]['minItems']} and the prompt never "
            f"tells the model that {word} cannot be empty")


def test_every_role_the_validator_places_is_placed_in_the_prompt():
    """The role-to-list mapping is enforced in code; it has to be stated too.

    Live 2026-08-27: a run spent all four transductions being told
    "role=unadjudicated cannot appear in excluded_variables" while no prompt
    anywhere said which list unadjudicated does belong in. Generated from the
    validator's own sets, so a role added to one of them cannot silently fail to
    reach the model — the same reason the required-call checklist is generated
    from REQUIRED_CALLS rather than typed out.
    """
    from agent.schema import (
        ADJUSTED_ROLES,
        EXCLUDED_ROLES,
        UNDETERMINED_ROLES,
        CausalRole,
    )
    placed = ADJUSTED_ROLES | EXCLUDED_ROLES | UNDETERMINED_ROLES
    for role in placed:
        assert role.value in SP.SYSTEM, (
            f"{role.value} is placed by _roles_match_their_lists and named in no "
            f"prompt; a record that puts it in the wrong list gets a rejection "
            f"it cannot act on")
    # And a role the validator places nowhere would be unusable — catch that too.
    assert set(CausalRole) - placed == set(), sorted(
        r.value for r in set(CausalRole) - placed)


def test_a_role_in_the_wrong_list_is_told_where_it_belongs():
    """A rejection the reader cannot act on costs the whole sample."""
    from pydantic import ValidationError as VE

    from agent.schema import CausalRole
    from tests.test_schema import adj, p014
    with pytest.raises(VE, match="belongs in undetermined_covariates"):
        p014(excluded_variables=[
            adj("m3:Q16.3", CausalRole.unadjudicated,
                "Mechanism stated at length so the floor is cleared here.",
                "Justification stated at length so its own floor is cleared.")])


# --------------------------------------------------------------------------- #
# the refusal path — an outcome, adjudicated by the environment and never by a
# vote of the k samples
# --------------------------------------------------------------------------- #

from agent.schema import (  # noqa: E402
    REFUSAL_EVIDENCE,
    NotSpecifiable,
    RefusalReason,
    Status,
)
from generate.funnel import Candidate, Construct  # noqa: E402

#: An area measure in the `linked:` registry, which registry_coverage reports as
#: declared and EMPTY. Deliberately not any published exposure: a fixture is not
#: a prompt, but a key that names a paper's construct spreads paper content into
#: one more file for no test benefit.
EMPTY_REGISTRY_KEY = "linked:area_deprivation_index"


def _stand_in(key: str, **over: object) -> Construct:
    d = dict(construct_key=key, module=key.partition(":")[0],
             base_id=key.partition(":")[2] or key, stem_text="",
             member_keys=[key], is_group=False, is_free_text=False,
             roster_instances=0)
    d.update(over)
    return Construct(**d)


@pytest.fixture(scope="module")
def unspecifiable(pair):
    """A pair whose outcome resolves and whose exposure resolves nowhere."""
    _, version, _ = pair
    C, _ = load_constructs()
    return Candidate(exposure=_stand_in(EMPTY_REGISTRY_KEY),
                     outcome=C["m2:Q12.78"]), version


REFUSAL_CALLS = [
    tool_call("registry_coverage", {}, "r1"),
    tool_call("resolve_variable", {"key": EMPTY_REGISTRY_KEY}, "r2"),
    tool_call("resolve_variable", {"key": "m2:Q12.78"}, "r3"),
]
REFUSAL_ANALYSIS = (
    "registry_coverage reports the linked registry declared and empty, and "
    "resolve_variable on the exposure returns not_found. The outcome resolves "
    "uniquely. There is no exposure to specify against.\n\n"
    "NOT SPECIFIABLE: registry_empty")


def _refusal_json(version, **over: object) -> str:
    d = {"pair_id": "ignored — the driver owns it",
         "dictionary_version": version,
         "reason": "registry_empty",
         "statement": ("No area measure exists in this instrument, so the "
                       "exposure this pair names cannot be measured at all."),
         "evidence": [{"tool": "search_variables", "argument": "x",
                       "outcome": "ok"}],
         "blocked_on": [],
         "what_would_unblock": "an area-measure inventory from the study team",
         "provenance": {"dictionary_version": version, "module_version": "0.1",
                        "prompt_hash": "scripted", "model_id": "scripted"}}
    d.update(over)
    return json.dumps(d)


def _refuses(version, calls=None) -> list:
    return [Reply(tool_calls=calls if calls is not None else REFUSAL_CALLS),
            Reply(content=REFUSAL_ANALYSIS),
            Reply(content=_refusal_json(version))]


def test_a_refusal_is_an_outcome_and_not_a_gate_failure(unspecifiable):
    """A refusal is a result, not a rejection.

    Point 1 of the spec. Before this the output space was `valid protocol or
    nothing`, so the only well-formed record for this pair invented a key.
    """
    p, version = unspecifiable
    a = SP.specify_once(ScriptedBackend(_refuses(version)), p, seed=0)
    assert a.gate == "refused", a.error
    assert a.protocol is None
    assert isinstance(a.refusal, NotSpecifiable)
    assert a.refusal.reason is RefusalReason.registry_empty
    assert [b.value for b in a.refusal.blocked_on] == ["area_measure_inventory"]
    assert a.refused and not a.ok


def test_the_refusal_cites_the_environments_lookups_not_the_models(unspecifiable):
    """Evidence is stamped from the environment, never transcribed.

    The scripted transduction cites `search_variables`, which would fail
    `_refusal_is_earned` outright. The record that lands cites the two calls the
    ENVIRONMENT made, the same rule agent/tool_authority.py applies to a
    protocol's gate fields.
    """
    p, version = unspecifiable
    a = SP.specify_once(ScriptedBackend(_refuses(version)), p, seed=0)
    cited = {(e.tool, e.outcome) for e in a.refusal.evidence}
    assert ("registry_coverage", "linked: coverage none") in cited
    assert ("resolve_variable", "not_found") in cited
    assert "search_variables" not in {e.tool for e in a.refusal.evidence}
    assert {e.argument for e in a.refusal.evidence} == {"linked", EMPTY_REGISTRY_KEY}


def test_a_refusal_must_show_the_lookups_that_force_it(unspecifiable):
    """The refusal gate, symmetric with REQUIRED_CALLS.

    `_gate` asks whether the log holds the calls any protocol needs; this asks
    whether it holds the calls THIS reason needs. Both read the executed log,
    and both read the same declaration in agent/schema.py, so they cannot drift
    apart.
    """
    p, version = unspecifiable
    without = [c for c in REFUSAL_CALLS
               if c["function"]["name"] != "registry_coverage"]
    a = SP.specify_once(ScriptedBackend(_refuses(version, without)), p, seed=0)
    assert a.gate == "missing_calls"
    assert a.refusal is None
    assert "registry_coverage" in a.error
    assert "registry_coverage" in REFUSAL_EVIDENCE[RefusalReason.registry_empty]


def test_a_refusal_the_environment_contradicts_is_discarded(pair):
    """A false refusal is discarded like a fabricated key.

    Refusing is strictly easier than the work, so it stands only where the
    environment forces it. Here both anchors resolve and the refusal is false.
    """
    p, _, _ = pair
    b = ScriptedBackend([Reply(tool_calls=REASON_CALLS_A),
                         Reply(content=REFUSAL_ANALYSIS)])
    a = SP.specify_once(b, p, seed=0)
    assert a.gate == "unearned_refusal"
    assert a.refusal is None and a.protocol is None
    assert a.claimed_reason is RefusalReason.registry_empty
    assert "both anchors resolve" in a.error


def test_a_reason_no_tool_can_establish_cannot_be_claimed(pair):
    """A reason nothing can produce is a reason nothing can earn.

    `access_gate_refused` is in the enum and in REFUSAL_EVIDENCE, and MEASURED
    2026-08-28 check_access returns only `pass` or `refer` — no return value
    produces it. A reason the environment cannot reach is one that can be
    asserted at will, so claiming it is discarded like any unearned refusal.
    """
    p, _, _ = pair
    b = ScriptedBackend([Reply(tool_calls=REASON_CALLS_A),
                         Reply(content="…\n\nNOT SPECIFIABLE: access_gate_refused")])
    a = SP.specify_once(b, p, seed=0)
    assert a.gate == "unearned_refusal"
    assert RefusalReason.access_gate_refused not in SP.PAIR_ADJUDICABLE


def test_a_protocol_for_an_unspecifiable_pair_never_reaches_transduction(unspecifiable):
    """The invented record is never built at all.

    Point 3: a protocol naming an exposure that does not resolve is invalid
    however many samples produced one. It is stopped before the second model
    call, so no such record is ever built, ranked or parked.
    """
    p, _ = unspecifiable
    b = ScriptedBackend([Reply(tool_calls=REASON_CALLS_A),
                         Reply(tool_calls=REASON_CALLS_B),
                         Reply(content=ANALYSIS)])
    a = SP.specify_once(b, p, seed=0)
    assert a.gate == "specified_the_unspecifiable"
    assert a.protocol is None and a.refusal is None
    assert b.i == 3, "the transduction call must never happen"


def test_the_environment_settles_a_mixed_k_not_the_majority(unspecifiable):
    """A mixed k, settled against the samples that specified.

    Two samples refuse, one specifies. The environment says the pair has no
    exposure, so the protocol loses regardless of the count — and `selected` is
    None rather than a refusal, because a refusal is not a protocol that won.
    """
    p, version = unspecifiable
    script = (_refuses(version) + _refuses(version)
              + [Reply(tool_calls=REASON_CALLS_A), Reply(tool_calls=REASON_CALLS_B),
                 Reply(content=ANALYSIS)])
    res = SP.specify(ScriptedBackend(script), p, k=3)
    assert res.selected is None
    assert res.parked == [] and res.all_valid == []
    assert isinstance(res.refusal, NotSpecifiable)
    assert res.counts == (0, 2, 1)


def test_the_environment_settles_a_mixed_k_the_other_way(pair):
    """A mixed k, settled against the samples that refused.

    The mirror case, and the reason this is adjudication rather than a rule that
    happens to favour refusing: on a pair whose anchors resolve, two refusals do
    not beat one protocol.
    """
    p, version, counts = pair
    refuse = [Reply(tool_calls=REASON_CALLS_A), Reply(content=REFUSAL_ANALYSIS)]
    script = refuse + refuse + _good_script(fixture(version, counts["enumerated"]))
    res = SP.specify(ScriptedBackend(script), p, k=3)
    assert res.refusal is None
    assert res.selected is not None
    assert res.counts == (1, 0, 2)


def test_k_refusals_of_one_pair_are_one_record(unspecifiable):
    """Dedup collapses them by construction, not by luck.

    The environment writes pair_id, reason and evidence, so every refusal of a
    pair hashes identically. That is what makes the count in `yield_line` a
    count of samples while the record stays one artifact.
    """
    p, version = unspecifiable
    res = SP.specify(ScriptedBackend(_refuses(version) * 3), p, k=3)
    assert res.counts == (0, 3, 0)
    assert len({a.refusal.record_hash() for a in res.attempts}) == 1


def test_yield_reports_refusals_on_their_own_line(unspecifiable):
    """Point 4: a refusal is not a failure and is not counted as one."""
    p, version = unspecifiable
    res = SP.specify(ScriptedBackend(_refuses(version) * 2), p, k=2)
    assert res.yield_line == "0 specified, 2 refused, 0 failed"
    assert res.yield_line in res.reason
    assert sum(res.counts) == len(res.attempts)


def test_rank_is_never_handed_a_refusal():
    """_rank orders protocols and only protocols.

    Teaching it to compare a refusal against one is how the environment's
    verdict would be relitigated by an ordering function.
    """
    import ast
    import inspect
    code = ast.unparse(ast.parse(inspect.getsource(SP._rank)))
    for term in ("refusal", "NotSpecifiable", "RefusalReason"):
        assert term not in code, f"_rank references {term!r}"
    # The type it accepts, read off the function rather than off a comment: with
    # `from __future__ import annotations` this is the source text, which is
    # exactly the claim being pinned.
    assert SP._rank.__annotations__["p"] == "ProtocolSpecification"


def test_adjudication_is_a_property_of_the_pair_and_not_of_the_run(unspecifiable, pair):
    """The adjudication cannot be moved by any sample.

    It runs before call 1 and takes no log and no backend, so it is the same for
    every one of the k samples. That is what makes it not a vote.
    """
    import inspect
    up, _ = unspecifiable
    calls, _ = build_registry("benchmark")
    assert SP.adjudicate(up, calls) == SP.adjudicate(up, calls)
    assert set(inspect.signature(SP.adjudicate).parameters) == {"pair", "callables"}
    assert SP.adjudicate(pair[0], calls).reason is None


def test_every_reason_the_prompt_offers_is_one_the_environment_can_uphold():
    """The prompt offers exactly the reasons the environment can settle.

    The menu is generated from PAIR_ADJUDICABLE, so a reason the environment
    cannot settle is never advertised — otherwise the prompt invites a move that
    is always discarded, and calibration is measured against a trap.
    """
    menu = {r for r in RefusalReason if f"  {r.value:32} needs" in SP.SYSTEM}
    assert menu == SP.PAIR_ADJUDICABLE
    assert SP.REFUSAL_SENTINEL in SP.SYSTEM
    for r in SP.PAIR_ADJUDICABLE:
        assert ", ".join(sorted(REFUSAL_EVIDENCE[r])) in SP.SYSTEM


def test_every_advertised_reason_is_actually_reachable(pair):
    """Each reason on the menu, produced by a real adjudication.

    A calibration set is being enumerated against these members, so a member no
    pair can elicit would be a category with no items in it.
    """
    C, _ = load_constructs()
    calls, _ = build_registry("benchmark")
    free = next(c for c in C.values() if c.is_free_text)
    cases = {
        RefusalReason.registry_empty:
            Candidate(exposure=_stand_in(EMPTY_REGISTRY_KEY), outcome=C["m2:Q12.78"]),
        RefusalReason.exposure_unresolvable:
            Candidate(exposure=_stand_in("m2:Q99.99"), outcome=C["m2:Q12.78"]),
        RefusalReason.outcome_unresolvable:
            Candidate(exposure=C["m2:Q12.78"], outcome=_stand_in("m2:Q99.99")),
        RefusalReason.anchors_are_the_same_construct:
            Candidate(exposure=C["m2:Q12.78"], outcome=C["m2:Q12.78"]),
        RefusalReason.free_text_anchor:
            Candidate(exposure=free, outcome=C["m2:Q12.78"]),
    }
    assert set(cases) == SP.PAIR_ADJUDICABLE
    for want, cand in cases.items():
        got = SP.adjudicate(cand, calls)
        assert got.reason is want, f"{cand.pair_id} adjudicated {got.reason}"
        assert set(REFUSAL_EVIDENCE[want]) <= {e.tool for e in got.evidence}


def test_a_refusal_carries_no_status(unspecifiable):
    """Status is a protocol concept and a refusal simply does not have one.

    `derive_status` reads n_source, blocked_on and the access decision — three
    fields a refusal does not and must not have — and its two values describe a
    protocol's trajectory toward review, which a refusal has none of. A refusal
    ends when its blocker clears, and the field that says so is
    `what_would_unblock`.
    """
    p, version = unspecifiable
    a = SP.specify_once(ScriptedBackend(_refuses(version)), p, seed=0)
    assert not hasattr(a.refusal, "status")
    assert [s.value for s in Status] == ["draft", "ready_for_review"]


def test_the_refusal_prompt_and_schema_carry_no_study_content():
    """Two more prompt surfaces that benchmark.contamination_check cannot see.

    C3 already names the transduction template and the repair wrapper as text
    that reaches the model with no scan over it; TRANSDUCE_REFUSAL and the
    refusal schema join that set. The marker list is applied here until the
    check itself reaches them — a lane that cannot edit `benchmark/` can still
    refuse to add unscanned surface silently.
    """
    from agent.schema import NotSpecifiable
    from benchmark.contamination_check import MARKERS
    text = "\n".join((SP.TRANSDUCE_REFUSAL, SP.TRANSDUCE, SP.REPAIR,
                      json.dumps(NotSpecifiable.model_json_schema())))
    assert [m for m in MARKERS if m in text] == []


def test_the_demo_driver_replays_its_whole_script(pair):
    """The command in generate/run_specifier.py's docstring must actually run.

    It did not between 2026-08-27 and 2026-08-28: MAX_TRANSDUCE_ATTEMPTS went
    from 2 to 4 and the demo's two hand-written rejections for seed 4 ran the
    ScriptedBackend dry on the third attempt, so `python
    generate/run_specifier.py` died with "ScriptedBackend exhausted after 19
    calls". Nothing failed, because nothing ran it. This runs it.
    """
    from generate.run_specifier import demo_script

    p, version, counts = pair
    backend = ScriptedBackend(demo_script(
        fixture(version, counts["enumerated"]),
        fixture(version, counts["enumerated"], shuffle=True)))
    res = SP.specify(backend, p, k=5)
    assert res.counts == (3, 0, 2)
    assert res.distinct == 1
    assert backend.i == len(backend.script), "the script must be spent exactly"


def test_the_refusal_transduction_is_constrained_by_the_refusal_schema(unspecifiable):
    """The second call gets NotSpecifiable's grammar, not the protocol's.

    Handing it ProtocolSpecification's schema would require an `exposure` on the
    one output whose whole point is not having one — the original hole, moved
    down a level rather than closed.
    """
    p, version = unspecifiable
    seen: list[str] = []

    class Spy(ScriptedBackend):
        def chat(self, messages, **kw: object) -> Reply:
            g = kw.get("guided_json") or {}
            seen.append(g.get("title", "none") if isinstance(g, dict) else "none")
            return super().chat(messages, **kw)

    a = SP.specify_once(Spy(_refuses(version)), p, seed=0)
    assert a.gate == "refused", a.error
    assert seen == ["none", "none", "NotSpecifiable"]


# ---------------------------------------------------------------------------
# THE PROMPT CONTRACT. Every prompt this file sends is rendered through
# `SP.PromptTemplate`, whose variables are parsed out of the body. These tests
# are the enforcement half: the contract is only worth having while something
# fails when a call site and a body disagree.
# ---------------------------------------------------------------------------


def _specifier_tree() -> ast.Module:
    """Parse agent/specifier.py, the module whose call sites are under test.

    Returns:
        The parsed module.
    """
    return ast.parse(Path(SP.__file__).read_text())


def _resolve_template(node: ast.expr) -> SP.PromptTemplate | None:
    """Work out which template a `.render(...)` call site is rendering.

    Args:
        node: The expression `render` was reached through.

    Returns:
        The template, or None when this call site cannot be resolved statically
        — which the caller must treat as a failure, not as "no template".
    """
    if isinstance(node, ast.Name):
        obj = getattr(SP, node.id, None)
        return obj if isinstance(obj, SP.PromptTemplate) else None
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "_template" and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)):
        return SP._template(node.args[0].value)
    return None


def _render_call_sites() -> list[tuple[SP.PromptTemplate, frozenset[str], int]]:
    """Every `.render(...)` in agent/specifier.py, with the keywords it passes.

    Returns:
        One `(template, supplied keywords, line number)` per call site.
    """
    sites: list[tuple[SP.PromptTemplate, frozenset[str], int]] = []
    for node in ast.walk(_specifier_tree()):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "render"):
            continue
        t = _resolve_template(node.func.value)
        assert t is not None, (
            f"line {node.lineno}: this render() call cannot be traced back to a "
            f"template, so nothing can check what it supplies. Render from a "
            f"module-level PromptTemplate or from _template('NAME').")
        assert not node.args, f"line {node.lineno}: render takes keywords only"
        supplied = set()
        for kw in node.keywords:
            assert kw.arg is not None, (
                f"line {node.lineno}: **kwargs hides the contract this checks")
            supplied.add(kw.arg)
        sites.append((t, frozenset(supplied), node.lineno))
    return sites


def test_every_render_call_site_supplies_exactly_the_bodys_slots() -> None:
    """The check that would have caught five of AstroAgents' six templates.

    Counted by the orchestrator 2026-09-01 and not re-fetched here: in
    `amirgroup-codes/AstroAgents::AstroAgents.py`, three templates declare
    variables their bodies never use and three use `astrobio_context`, which is
    declared nowhere. Both directions are checked here, because a value passed
    to a body that has no slot for it is silently dropped by `str.format` and
    the caller goes on believing the model was shown it.

    This walks the AST rather than calling the prompts, so a call site on a path
    no test exercises — the repair turn, the refusal transduction — is covered
    with the rest.
    """
    sites = _render_call_sites()
    assert len(sites) >= 5, f"only {len(sites)} render call sites found"
    for template, supplied, line in sites:
        assert supplied == template.variables, (
            f"agent/specifier.py:{line} renders {template.name}: "
            f"missing {sorted(template.variables - supplied)}, "
            f"unused {sorted(supplied - template.variables)}")


def test_every_prompt_in_the_module_is_rendered_through_the_contract() -> None:
    """A prompt with no render call site is one that got out another way.

    The inventory is DERIVED, never listed here: a module-level PromptTemplate,
    or a module-level string carrying a `{slot}`. A new prompt added beside
    TRANSDUCE and filled with `.format` fails this without anyone remembering to
    extend a list — the failure mode this whole round exists to remove.
    """
    rendered = {t.name for t, _, _ in _render_call_sites()}
    inventory: set[str] = set()
    for name in dir(SP):
        obj = getattr(SP, name)
        if isinstance(obj, SP.PromptTemplate):
            inventory.add(obj.name)
        elif (isinstance(obj, str) and not name.startswith("__")
              and SP._slots(name, obj)):
            inventory.add(name)
    assert inventory >= {"SYSTEM", "user_prompt", "TRANSDUCE",
                         "TRANSDUCE_REFUSAL", "REPAIR"}, sorted(inventory)
    assert inventory == rendered, (
        f"never rendered through PromptTemplate: {sorted(inventory - rendered)}")


def test_the_prompt_bodies_are_not_filled_by_bare_format() -> None:
    """`.format` on a prompt body is the bypass, so nothing may take it.

    Without this the contract is opt-in: `TRANSDUCE.format(...)` still works,
    still drops an unused argument in silence, and reads exactly like the code
    it replaced.
    """
    prompts = {"SYSTEM", "TRANSDUCE", "TRANSDUCE_REFUSAL", "REPAIR",
               "SYSTEM_TEMPLATE", "USER_PROMPT_TEMPLATE"}
    for node in ast.walk(_specifier_tree()):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format"
                and isinstance(node.func.value, ast.Name)):
            assert node.func.value.id not in prompts, (
                f"agent/specifier.py:{node.lineno}: {node.func.value.id}.format "
                f"bypasses the variable check — render it instead")


def test_a_missing_variable_is_refused_by_name() -> None:
    """Seeded: the TRANSDUCE call site, one keyword short."""
    with pytest.raises(SP.PromptContractError) as exc:
        SP._template("TRANSDUCE").render(analysis="a")
    assert "toollog" in str(exc.value), exc.value
    assert "TRANSDUCE" in str(exc.value), exc.value


def test_a_variable_the_body_does_not_use_is_refused_by_name() -> None:
    """Seeded: the half `str.format` accepts in silence.

    `"{a}".format(a=1, b=2)` returns "1" and says nothing about `b`, which is
    how a template can go on being handed a value it stopped mentioning.
    """
    with pytest.raises(SP.PromptContractError) as exc:
        SP._template("TRANSDUCE").render(analysis="a", toollog="l",
                                         critic_feedback="c")
    assert "critic_feedback" in str(exc.value), exc.value
    # And the bare .format this replaces does not complain at all.
    assert SP.TRANSDUCE.format(analysis="a", toollog="l", critic_feedback="c")


def test_a_doubled_brace_is_literal_and_not_a_slot() -> None:
    """JSON in a prompt body is written `{{ }}`, and must not become a variable."""
    t = SP.PromptTemplate(name="t", body='emit {{"k": 1}} for {subject}')
    assert t.variables == frozenset({"subject"})
    assert t.render(subject="x") == 'emit {"k": 1} for x'


def test_a_field_no_keyword_can_supply_is_refused() -> None:
    """`{0}` and `{pair.pair_id}` cannot be compared against keywords.

    user_prompt was an f-string over `{pair.pair_id}` and `{e.stem_text}` before
    this round. Allowing those through would leave `variables` reporting `pair`
    and `e` — names no call site passes — and the equality check would be
    checking nothing.
    """
    for body in ("{0} and {1}", "{pair.pair_id}", "{keys[0]}"):
        with pytest.raises(SP.PromptContractError, match="not a plain name"):
            _ = SP.PromptTemplate(name="t", body=body).variables


def test_an_unbalanced_brace_names_the_template() -> None:
    """A body that `str.format` would die on dies here, at import, with a name."""
    with pytest.raises(SP.PromptContractError, match="does not parse"):
        _ = SP.PromptTemplate(name="t", body="{unclosed").variables


# --------------------------------------------------------------------------- #
# _gate: a required call counts only if it succeeded, on THIS pair
# --------------------------------------------------------------------------- #


def _gate_log(rows: list[tuple[str, dict, str]]) -> T.ToolLog:
    log = T.ToolLog()
    for name, args, outcome in rows:
        log.record(name, args, outcome, 0.0)
    return log


def _passing_rows(key: str) -> list[tuple[str, dict, str]]:
    return [("resolve_variable", {"key": key}, "unique"),
            ("estimate_n", {"keys": [key]}, "ok"),
            ("check_access", {"keys": [key]}, "ok"),
            ("estimate_detectability", {"baseline_prevalence": 0.2}, "ok")]


def test_a_log_with_every_required_call_succeeding_on_the_pair_passes(pair):
    p, _, _ = pair
    key = p.exposure.construct_key
    passed, why = SP._gate(_gate_log(_passing_rows(key)), p)
    assert passed and why == ""


def test_a_required_call_that_errored_does_not_satisfy_the_gate(pair):
    """An errored required call must not satisfy the gate.

    The measured hole: `check_access` called with bad arguments, an error
    returned, and an access decision asserted anyway. Over the 15 logs in
    `run/logs/`, `estimate_detectability` errored 5 times and `estimate_n` once,
    so this is not a hypothetical shape.
    """
    p, _, _ = pair
    key = p.exposure.construct_key
    rows = [(n, a, "error" if n == "check_access" else o)
            for n, a, o in _passing_rows(key)]
    passed, why = SP._gate(_gate_log(rows), p)
    assert not passed
    assert "called but never succeeded" in why and "check_access" in why


def test_a_required_call_that_succeeded_on_another_pair_does_not_count(pair):
    p, _, _ = pair
    other = next(k for k in T._load()["entries"]
                 if k["key"] not in SP._pair_keys(p))["key"]
    rows = [(n, ({"key": other} if n == "resolve_variable" else
                 {"keys": [other]} if "keys" in a else a), o)
            for n, a, o in _passing_rows(p.exposure.construct_key)]
    passed, why = SP._gate(_gate_log(rows), p)
    assert not passed
    assert "succeeded only on other variables" in why


def test_resolve_variable_ambiguous_is_not_a_success(pair):
    """An ambiguous resolution is not a resolution.

    `env/tools.py` calls it a failure in its own log, and `_RESOLVED` omits it.
    The gate reuses that set rather than keeping a second copy.
    """
    p, _, _ = pair
    key = p.exposure.construct_key
    rows = [(n, a, "ambiguous" if n == "resolve_variable" else o)
            for n, a, o in _passing_rows(key)]
    passed, why = SP._gate(_gate_log(rows), p)
    assert not passed and "resolve_variable" in why
    assert "ambiguous" not in SP._GATE_SUCCESS["resolve_variable"]


def test_a_missing_call_still_fails_and_is_named_separately(pair):
    p, _, _ = pair
    rows = [r for r in _passing_rows(p.exposure.construct_key)
            if r[0] != "estimate_n"]
    passed, why = SP._gate(_gate_log(rows), p)
    assert not passed
    assert "never called" in why and "estimate_n" in why


def test_the_keyless_required_tool_is_exempt_from_the_relevance_check(pair):
    """The one required tool whose arguments carry no key is exempt.

    `estimate_detectability(baseline_prevalence, alpha, power)` takes no key, so
    demanding one would fail every honest run.
    """
    assert "estimate_detectability" in SP._GATE_NO_KEY_ARGS
    p, _, _ = pair
    passed, _ = SP._gate(_gate_log(_passing_rows(p.exposure.construct_key)), p)
    assert passed


def test_either_anchor_and_either_key_shape_satisfies_relevance(pair):
    """A model may reach an anchor by its construct key or any member key."""
    p, _, _ = pair
    for key in (p.exposure.construct_key, p.outcome.construct_key,
                p.exposure.member_keys[0], p.outcome.member_keys[-1]):
        passed, why = SP._gate(_gate_log(_passing_rows(key)), p)
        assert passed, f"{key} rejected: {why}"


def test_the_gate_requires_the_pair_rather_than_defaulting_it():
    """`pair` is required, not defaulted.

    A gate whose strictness depends on whether a caller passed an optional
    argument is a guarantee that reads as enforced and is not.
    """
    import inspect

    params = inspect.signature(SP._gate).parameters
    assert list(params) == ["log", "pair"]
    assert params["pair"].default is inspect.Parameter.empty
