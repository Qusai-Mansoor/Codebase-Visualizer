# Phase 12: Testing Strategy

> Guide §13. The brief specifically asks how you verified the graph is correct. "I eyeballed it" does
> not pass. This is the systematic approach.

## What it does
Defines how each phase is verified: hand-crafted fixture mini-packages with exact expected output,
ground-truth spot checks against a real project (FastAPI), and snapshot regression after each phase.

## Test fixtures — mini packages (guide §13.1)
Each fixture in `tests/fixtures/` tests one behavior. Run the analyzer on it and assert exact output.

| Fixture (this repo) | Guide name | What it tests |
|---------------------|-----------|----------------|
| `reexport_pkg/` | reexport_chain | `from .core import Thing` — edge points to `core.py`, NOT `__init__.py` |
| (add) `wildcard_all/` | wildcard_all | `__all__ = ['foo']` + wildcard — only `foo` resolves |
| `abstract_mixin/` | abstract_mixin | abstract base + mixin — verify `is_abstract`, `is_mixin` |
| `circular_import_a/` + `circular_import_b/` | circular_import | `a` imports `b`, `b` imports `a` — cycle detected |
| `decorator_chain/` | decorator_chain | stacked decorators — all DECORATES edges emitted |
| `async_surface/` | async_surface | async/sync calling each other — `is_async` tags + edge types |
| `type_checking_only/` | type_checking_only | import under `if TYPE_CHECKING` — `is_type_only=True`, no call edge |
| `property_getter/` | property_getter | `@property` — PROPERTY kind, no false "unused" flag |
| `namespace_pkg/` | namespace_pkg | package without `__init__.py` — discovery still works |
| `simple_pkg/` | (baseline) | dotted-name computation, basic nodes/edges |

## Ground-truth spot checks on FastAPI (guide §13.2)
Run against FastAPI's own source (public, well-structured, all the interesting patterns). Pick known
re-exports and verify the `file` field in the JSON matches the real source:
- `fastapi.APIRouter` → defined in `fastapi/routing.py` (NOT `fastapi/__init__.py`).
- `fastapi.Depends` → defined in `fastapi/params.py`.
- `fastapi.HTTPException` → actually re-exported from starlette → should be **external**.
Open the JSON, grep for each name, confirm `file` matches. This is the headline correctness check.

## Regression tests after each phase (guide §13.3)
After implementing a phase, run the fixture tests and freeze the output JSON. From then on, any change
that alters the frozen output is a regression. Use `pytest-snapshot` (already a dev dependency) or
store expected JSON files and diff.

## Test file map
| Test file | Covers |
|-----------|--------|
| `tests/test_models.py` | enums serialize to strings; dataclasses instantiate with/without optionals |
| `tests/test_discovery.py` | dotted names, skip dirs, namespace pkgs, src-layout |
| `tests/test_parser.py` | syntax-error handling, encoding fallback, empty files |
| `tests/test_resolver.py` | re-export following, `__all__`/wildcard, TYPE_CHECKING, cycles |
| `tests/test_definitions.py` | node kinds, abstract/protocol/mixin/async flags, inheritance edges |
| `tests/test_calls.py` | call edges, builtins skipped, TYPE_CHECKING calls excluded |
| `tests/test_graph.py` | cycle detection, unused (dunders/roots excluded), communities |
| `tests/test_integration.py` | full pipeline on a fixture → serialized JSON snapshot |

## Common mistakes
1. Asserting on loosely-shaped output instead of exact expected nodes/edges.
2. Not freezing snapshots, so regressions slip through silently.
3. Skipping the FastAPI ground-truth check — fixtures alone don't prove real-world correctness.

## Implementation notes
Write tests alongside each phase (TDD-friendly). Keep fixtures tiny and single-purpose. The
integration test is the end-to-end guard; the FastAPI spot check is the reality check. As each phase
lands, freeze its snapshot before moving on.
