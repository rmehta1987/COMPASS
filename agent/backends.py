"""agent/backends.py — the model seam. One swappable interface, three implementations.

The whole system touches a served model in exactly one place. That is deliberate:
the tool layer, the funnel and the schema are all model-free and testable without
weights, and swapping Gemma 4 for Qwen3 must be a config change, not a refactor.

TARGET: Gemma 4 or Qwen3 8-27B behind an OpenAI-compatible server (vLLM, or
llama.cpp with GBNF). Two facts about that size class shape everything here:

  1. A single call asked to reason AND emit constrained JSON loses 4-10 points
     against the same model doing them separately. Guided decoding alone costs
     ~1.6 points of reasoning while lifting parse validity from 55.7% to 92.2%.
     So: reason first, unconstrained; transduce second, constrained. Never one
     call. `chat()` therefore takes `guided_json` as an explicit argument and the
     Specifier passes it on exactly one of its two calls.
  2. Prompted-JSON without grammar enforcement was malformed 30-40% of the time
     on a 7B. `guided_json` is not an optimisation here, it is the parser.

Two backends know how to enforce a schema: vLLM's `guided_json` extra-body field
and the newer `response_format: json_schema`. Which one a server accepts depends
on its version, so `enforce` selects, and `RETRY_UNCONSTRAINED` is deliberately
absent — a server that cannot enforce should fail loudly rather than silently
degrade to the 30-40% mode.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Reply:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    raw: dict | None = None
    stop_reason: str | None = None


class Backend(Protocol):
    name: str
    def chat(self, messages: list[dict], *, tools: list[dict] | None = None,
             guided_json: dict | None = None, temperature: float = 0.0,
             seed: int | None = None, max_tokens: int = 2048) -> Reply: ...


# --------------------------------------------------------------------------- #
# served model
# --------------------------------------------------------------------------- #

class OpenAICompatBackend:
    """vLLM / llama.cpp / Ollama behind an OpenAI-compatible /v1 endpoint.

    Verified-absent at authoring time: no ANTHROPIC/OPENAI/VLLM key was set and
    ports 11434, 8000, 8080 and 1234 were all closed. So this class is written
    against the documented API and exercised end-to-end by ScriptedBackend; the
    first real run must confirm the two server-dependent choices below
    (`enforce`, and whether the server emits `tool_calls` or inline text).
    """

    def __init__(self, model: str, base_url: str | None = None,
                 api_key: str | None = None, enforce: str = "guided_json",
                 timeout: float = 240.0):
        self.name = model
        self.model = model
        self.base_url = (base_url or os.environ.get("COMPASS_LLM_URL")
                         or "http://localhost:8000/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("COMPASS_LLM_KEY") or "EMPTY"
        self.enforce = enforce
        self.timeout = timeout

    def chat(self, messages, *, tools=None, guided_json=None, temperature=0.0,
             seed=None, max_tokens=2048) -> Reply:
        body: dict[str, Any] = {
            "model": self.model, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens,
        }
        if seed is not None:
            body["seed"] = seed
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if guided_json is not None:
            if self.enforce == "guided_json":            # vLLM extra body
                body["guided_json"] = guided_json
                body["guided_decoding_backend"] = "xgrammar"
            elif self.enforce == "response_format":      # newer vLLM / llama.cpp
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "protocol", "strict": True,
                                    "schema": guided_json}}
            else:
                raise ValueError(
                    f"enforce={self.enforce!r} cannot constrain output. Refusing to "
                    "fall back to prompted JSON: on this model class that mode is "
                    "malformed 30-40% of the time, and a silent degradation here "
                    "would be indistinguishable from the model reasoning badly.")

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                out = json.loads(r.read())
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"no model server at {self.base_url} ({exc}). Start one, e.g.\n"
                f"  vllm serve {self.model} --port 8000 "
                f"--guided-decoding-backend xgrammar\n"
                f"or set COMPASS_LLM_URL.") from exc

        msg = out["choices"][0]["message"]
        return Reply(content=msg.get("content") or "",
                     tool_calls=msg.get("tool_calls") or [],
                     raw=out, stop_reason=out["choices"][0].get("finish_reason"))


# --------------------------------------------------------------------------- #
# deterministic stand-in
# --------------------------------------------------------------------------- #

class ScriptedBackend:
    """A backend that replays a fixed list of replies.

    This exists so the control flow — tool loop, gate, transduction, k-sample
    dedup, selection — is provable without weights, and so the tests stay
    deterministic when weights arrive. It is not a mock of the model's judgment;
    it is a fixture for everything around the judgment.
    """

    def __init__(self, script: list[Reply | Callable[[list[dict]], Reply]]):
        self.name = "scripted"
        self.script = list(script)
        self.i = 0
        self.seen: list[list[dict]] = []

    def chat(self, messages, *, tools=None, guided_json=None, temperature=0.0,
             seed=None, max_tokens=2048) -> Reply:
        self.seen.append(messages)
        if self.i >= len(self.script):
            raise AssertionError(
                f"ScriptedBackend exhausted after {self.i} calls; the agent asked "
                f"for another. Either the loop does not terminate or the script is "
                f"short.")
        step = self.script[self.i]
        self.i += 1
        return step(messages) if callable(step) else step


def tool_call(name: str, args: dict, cid: str | None = None) -> dict:
    return {"id": cid or f"call_{name}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def from_env() -> Backend:
    """Pick a backend from the environment. Explicit about what it found."""
    model = os.environ.get("COMPASS_LLM_MODEL")
    if not model:
        raise RuntimeError(
            "COMPASS_LLM_MODEL is unset. Set it to the served model id, e.g.\n"
            "  export COMPASS_LLM_MODEL=Qwen/Qwen3-14B\n"
            "  export COMPASS_LLM_URL=http://localhost:8000/v1\n"
            "For tests, construct ScriptedBackend directly instead.")
    return OpenAICompatBackend(model=model)
