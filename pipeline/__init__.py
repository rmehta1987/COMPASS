"""Pipeline wiring: request → retrieval record → hypothesis artefact.

Everything here is deterministic and model-free. The retriever bundle under
`deploy/` is frozen and validated; this package adapts to it, never changes it.
"""
