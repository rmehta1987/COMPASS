"""serve/ — a loopback test endpoint that lets the tool page drive real runs.

Not the pipeline and not a measurement surface. Everything here exists so a
browser can reach `deploy/retriever.py` and `agent/specifier.py` during
development; nothing here may be cited as a result. A record produced through
this package is `externally_posed` with `screened_from=0` and never enters a
benchmark denominator (`AGENTS.md` §Contamination Practice).

Two properties are load-bearing rather than tidy:

  * `env/` is untouched. The ban is on `env/` code CALLING out; this package
    calls out and therefore lives outside it.
  * The instrument is withheld. `deploy/retriever.py::_hit` returns `stem`,
    `option`, `key` and `members` verbatim, so every response is filtered by
    `serve/redact.py` before it leaves the process.
"""
