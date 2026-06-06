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
| 4 | resolver.py | ⬜ PENDING | Import resolution (jedi + manual) | TBD |
| 5 | definitions.py | ⬜ PENDING | Definition extraction from AST | TBD |
| 6 | calls.py | ⬜ PENDING | Call edge extraction | TBD |
| 7 | decorators.py | ⬜ PENDING | Decorator & dynamic dispatch | TBD |
| 8 | graph.py | ⬜ PENDING | Graph assembly & analysis | TBD |
| 9 | serializer.py | ⬜ PENDING | JSON serialization | TBD |
| 10 | tracer.py | ⬜ PENDING | Runtime tracing (stretch) | TBD |
| - | CLI | ⬜ PENDING | Typer CLI wrapper | TBD |
| - | API | ⬜ PENDING | FastAPI service | TBD |

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
- [ ] Entry points in pyproject.toml — treat as roots
- [ ] __main__.py — always a root
- [ ] Test files (tests/*.py) — functions are roots
- [ ] Dunder methods (__init__, __call__, etc.) — never mark as unused
- [ ] dataclass-generated methods — synthetic nodes
- [ ] Properties (@property) — attribute access calls getter
- [ ] importlib.import_module() — dynamic import warning
- [ ] Version-gated imports (if sys.version_info >= ...) — track both branches
- [ ] Large file handling (>2MB) — skip gracefully

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

**Session:** 3
**Assignee:** Claude Code (Sonnet 4.6)
**Task:** Implement Phase 3 — engine/parser.py

### What you did this session:
1. Implemented `engine/parser.py` — `parse_all(discovery)` iterating `module_map`, `_read_source` with UTF-8 → latin-1 fallback, `ast.parse(type_comments=True)` + `ast.fix_missing_locations`, SyntaxError and OSError both caught and logged to `failed`
2. Added `_looks_like_version_mismatch` heuristic to annotate SyntaxErrors on match/case/type keywords
3. Seeded `tests/fixtures/parse_suite/` — `__init__.py`, `valid_module.py`, `empty_module.py`
4. Wrote `tests/test_parser.py` with 25 tests; all pass
5. Full suite: 77 passed (27 models + 25 discovery + 25 parser)

### Key decisions:
- Fixture-based tests call `_discover_and_parse(FIXTURES)` (not `PARSE_SUITE`) so dotted names include `parse_suite.` prefix — same pattern as Phase 2 discovery tests
- Used a `session`-scoped pytest fixture for the FIXTURES parse result to avoid repeated filesystem I/O in the fixture-based tests
- latin-1 encoding tested via `tmp_path` (raw bytes with `\xe9`) — no need for a committed binary fixture
- Empty file (0 bytes) is a first-class fixture in `parse_suite/empty_module.py`

### Blockers / Questions:
- None

### Next Steps:
Phase 4 — `engine/resolver.py`. Context: `docs/04_IMPORT_RESOLUTION.md` + this file.

---

**Last Updated:** Session 3
**Last Verified:** Session 3 — `python -m pytest tests/test_models.py tests/test_discovery.py tests/test_parser.py` → 77 passed
