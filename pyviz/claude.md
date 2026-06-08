# Claude Code Session Tracking

This file tracks which phases are complete and provides context for future Claude Code sessions.

## Project Overview
- **Name:** Python Codebase Visualizer
- **Goal:** Analyze Python codebases and produce call/dependency graphs
- **Tech Stack:** Python (ast, jedi, networkx), FastAPI, Next.js + React Flow (frontend)
- **Status:** [IN PROGRESS]

> **Phase numbering note:** The `docs/` files are numbered `01–12` (Models first, then the analysis
> phases, then implicit requirements + testing). The Core Implementation Guide internally calls
> Discovery "Phase 1". When a doc says "Phase N", trust the doc's own input/output contract, not the
> number. `docs/INTEGRATION_PLAN.md` maps the two numbering schemes.

## Phase Completion Matrix

| Phase | Module | Status | Notes | Session |
|-------|--------|--------|-------|---------|
| 1 | models.py | ✅ Complete | All dataclasses + enums; 27 tests pass | 1 |
| 2 | discovery.py | ✅ Complete | SKIP_DIRS, src-layout, namespace pkgs, .pyi stubs; 25 tests pass | 2 |
| 3 | parser.py | ✅ Complete | UTF-8/latin-1 fallback, SyntaxError → failed, empty files OK; 25 tests pass | 3 |
| 4 | resolver.py | ✅ Complete | __init__ re-export chain, TYPE_CHECKING, cycles, wildcards/__all__, jedi fallback; 26 tests pass | 4 |
| 5 | definitions.py | ✅ Complete | DefinitionExtractor visitor; CLASS/FUNCTION/METHOD/PROPERTY/LAMBDA nodes; INHERITS edges; dataclass synthetics; is_abstract/protocol/mixin/dataclass flags; 34 tests pass | 5 |
| 6 | calls.py | ✅ Complete | CallEdgeExtractor visitor; CALLS edges; TYPE_CHECKING suppression; builtin skip; self/cls skip; cross-module binding resolution; dynamic_call warnings; 26 tests pass | 6 |
| 7 | decorators.py | ✅ Complete | DECORATES edges; role tagging (8 patterns); getattr dispatch warnings; local+import decorator resolution; __init__ canonical normalization; 23 tests pass | 7 |
| 8 | graph.py | ✅ Complete | build_nx_graph; find_cycles (nx.simple_cycles + dedup); _find_unused_symbols (dunders/exports/roots excluded); _detect_communities (Louvain); 22 tests pass | 8 |
| 9 | serializer.py | ✅ Complete | serialize(pg, nx_graph, communities, unused, cycles, root) → JSON str; dangling edge filter; enum .value; null community/role; ISO timestamp; 24 tests pass | 9 |
| 10 | tracer.py | ✅ Complete | RuntimeTracer(sys.settrace); cross-file call recording; merge_into_graph (STATIC→BOTH, new RUNTIME edges); trace_test_suite entry point; stable bound-method cache; 21 tests pass | 10 |
| 12 | test_integration.py | ✅ Complete | Full pipeline on fixtures; re-export/cycle/decorator/flag/wildcard assertions; snapshot regression; 17 tests pass | 12 |
| 13 | cli.py + viewer.html | ✅ Complete | Typer CLI (analyze/serve/version); reconciled pipeline; --trace/--quiet/--compact; bundled Cytoscape viewer (SRI-pinned); 11 tests pass | 13 |
| - | API | ⬜ PENDING | FastAPI service (Phase 14) | TBD |
| - | Frontend | ⬜ PENDING | Next.js + React Flow (Phases 15-16) | TBD |

**Legend:** ⬜ = Pending, 🟨 = In Progress, ✅ = Complete, ❌ = Blocked

## Global Requirements (All Phases Must Satisfy)

### Error Handling
- Every file I/O operation must be in a try/except
- Parse failures (SyntaxError, encoding issues) must be logged, not crash
- Unresolved imports must be warnings, not failures
- External packages must be handled gracefully (external nodes, no recursion)

### Edge Cases (Section 12 of Core Implementation Guide)
All phases must handle:
- [ ] TYPE_CHECKING imports (no call edges, marked is_type_only=True)
- [ ] __all__ and wildcard imports (resolve each exported name)
- [ ] __init__.py re-exports (follow the chain to the real definition)
- [ ] Circular imports (detect with visited set, break cycles)
- [ ] Namespace packages (no __init__.py)
- [ ] Stub files (.pyi) — collect separately
- [x] Entry points in pyproject.toml — treat as roots (Session 11: discovery._parse_entry_points + graph._build_roots_set)
- [x] __main__.py — always a root (Phase 8)
- [x] Test files (tests/*.py) — functions are roots (Phase 8)
- [x] Dunder methods (__init__, __call__, etc.) — never mark as unused (Phase 8)
- [x] dataclass-generated methods — synthetic nodes (Phase 5)
- [ ] Properties (@property) — attribute access calls getter (optional per spec §12.7)
- [x] importlib.import_module() — dynamic import warning (Session 11: calls._is_importlib_call)
- [x] Version-gated imports (if sys.version_info >= ...) — track both branches, is_conditional=True (Session 11: resolver._get_version_gated_ranges)
- [x] Large file handling (>2MB) — skip gracefully (Phase 2)

### Library Usage Rules
- **jedi** — used ONLY for import resolution. Never ask jedi "what does this file import?"
- **ast** — used ONLY for parsing and traversing. Never use regex on Python source.
- **networkx** — used ONLY in Phase 8 (graph assembly). Build the graph incrementally in phases 1-7.
- **Typer** — CLI argument parsing (Phase CLI)
- **FastAPI** — REST endpoint for the analyzer service (Phase API)

### No LLM in Parser
- LLMs are NOT allowed to determine code structure
- LLMs CAN write plain-English descriptions, cluster semantics, name patterns
- Static analysis must ALWAYS be deterministic

## Critical Notes for All Sessions

### Before You Code
1. **Read the relevant docs/** file for your phase (created in setup)
2. **Understand the input/output contracts** — exact dataclass types
3. **Know which edge cases apply** — Section 12 of Core Implementation Guide
4. **Review the test fixtures** — they define correctness

### While You Code
1. **Import only from models.py** — every phase depends on the same data structures
2. **Handle errors gracefully** — log warnings, don't crash
3. **Write tests first** — implement tests alongside code
4. **Use the library APIs exactly as shown** — don't improvise with jedi or networkx

### After You Code
1. **Update this file:** Change status to ✅, add session number
2. **Run the tests:** Verify all tests pass before moving to the next phase
3. **Review edge cases:** Grep for the edge case strings (TYPE_CHECKING, __all__, cycle, external)
4. **Update claude.md with blockers** if anything needs the previous phase first

## Current Session Notes

**Session:** 13
**Assignee:** Claude Code (Opus 4.8)
**Task:** Implement Phase 13 — CLI + bundled viewer (Part 2 §1 of CLI_and_Web_Interface_Guide.docx)

### What you did this session:
1. `pyviz/cli.py` — Typer CLI: `analyze` (path/--url/--output/--trace/--quiet/--compact), `serve`, `version`
2. `pyviz/viewer.html` — single-file Cytoscape.js + dagre viewer; `__GRAPH_DATA__` placeholder injected at serve time; SRI hashes pinned on all 3 CDN scripts
3. `pyproject.toml` — added `[tool.hatch.build.targets.wheel]` + force-include for `viewer.html`
4. `tests/test_cli.py` — 12 CliRunner tests (no network), incl. an XSS-breakout regression test
5. Security fix: `_render_viewer` escapes `</` → `<\/` and U+2028/U+2029 before injecting the
   (untrusted) graph JSON into the viewer `<script>` — prevents stored XSS from a malicious analyzed repo
6. Full suite: 296 passed

### ⚠️ CRITICAL — Part 2 guide API mismatch (applies to Phase 14 API too):
The guide's sample code targets an IDEALIZED engine API. Real signatures:
- `definitions.extract_all(parsed, resolved, g, disc)` — needs `discovery` (guide omits it)
- `calls.extract_all(parsed, resolved, g, disc)` — needs `discovery`
- `decorators.extract_all(parsed, resolved, g, disc)` — guide calls it `process_all` (WRONG)
- `ar = graph_mod.assemble(g, disc)` → returns `GraphAssemblyResult(graph, cycles, unused, communities)`; does NOT mutate in place
- `serializer.serialize(pg, ar.graph, ar.communities, ar.unused, ar.cycles, root)` — 6 args (guide shows 2)
- `tracer.trace_test_suite(root, disc, g)` — ✅ matches guide

### Key decisions:
- `--compact` re-dumps via `json.dumps(json.loads(serialize(...)), separators=(',',':'))` — engine untouched (serialize always indents)
- `--trace` re-runs `assemble` after the tracer so runtime edges are included
- CLI tests assert `core.add` (not `simple_pkg.core.add`): analyzing a package dir directly roots there
- Bundled viewer factored `_render_viewer()` out so injection is unit-testable without binding a socket

### Blockers / Questions:
- None

### Next Steps (one phase at a time, per user):
Phase 14 — API: `pyviz/api.py` (FastAPI job-queue service) + `tests/test_api.py`. Reuse the reconciled pipeline from `cli.py`. Context: guide §2.
Phases 15-16 — Frontend (`web/`, Next.js + React Flow, full guide spec). Phase 17 — docs + ground-truth test.

---

**Last Updated:** Session 13
**Last Verified:** Session 13 — `python -m pytest tests/` → 296 passed
