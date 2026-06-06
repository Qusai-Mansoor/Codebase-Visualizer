# Phase 11: Implicit & Inferred Requirements (cross-cutting)

> Guide §12. These were not stated in the brief but a real implementation must handle them. They are
> the filter interviewers probe. Every phase should be checked against this list.

## What it does
Not a module — a checklist of cross-cutting requirements that several phases must jointly satisfy.
Track these in `claude.md`'s edge-case checklist.

## The requirements (guide §12.1–12.11)

1. **Third-party vs first-party boundary (§12.1)** — calls resolving to stdlib/third-party emit an
   `is_external=True` placeholder node; never recurse into site-packages. Rule: file outside the
   project root ⇒ external. *Phases: 2, 4, 5.*

2. **`__dunder__` methods are not unused (§12.2)** — `__repr__`/`__eq__`/`__hash__` are called by
   Python internals. Never flag any `__x__` as unused. *Phase: 8.*

3. **Entry points are roots (§12.3)** — `[project.scripts] serve = 'myapp.cli:main'` ⇒ `myapp.cli.main`
   is invoked by the OS, has no in-codebase callers. Parse pyproject scripts/console_scripts into a
   `roots` set excluded from unused detection. *Phases: 8, CLI.*

4. **`__main__.py` is a root (§12.4)** — executed by `python -m pkg`. Always a root; don't mark its
   contents unused by in-degree alone. *Phase: 8.*

5. **Test files are separate roots (§12.5)** — everything under `tests/` (and `test_*.py` / `*_test.py`)
   is run by pytest, not called by the main codebase. Top-level test functions/fixtures are roots.
   *Phase: 8.*

6. **dataclass-generated methods (§12.6)** — `@dataclass` synthesizes `__init__`/`__repr__`/`__eq__`
   not present in source. Emit synthetic method nodes with `is_synthetic=True` (also attrs / pydantic
   validators). *Phase: 5.*

7. **Property calls are attribute accesses (§12.7)** — a `@property` getter runs on `obj.name`, not
   `obj.name()`. That's an `ast.Attribute`, not `ast.Call`. Optionally walk attributes; when the name
   resolves to a property, emit a `CALLS` edge with `Confidence.DYNAMIC`. *Phases: 5, 6.*

8. **`importlib.import_module` dynamic imports (§12.8)** — detect calls to `importlib.import_module`;
   record the literal string argument, or `'dynamic string, cannot resolve'` otherwise. *Phases: 4, 7.*

9. **Version-gated imports (§12.9)** — `if sys.version_info >= (3, 10):` — you can't know which branch
   runs. Record imports from both branches, tag `is_conditional=True`; don't give them the same
   confidence as unconditional imports. *Phase: 4.*

10. **Multiple assignments / reassignment (§12.10)** — for `handler = None; handler = MyClass()`, take
    the *last* assignment as canonical. For assignments inside conditionals, record all possible values
    and mark the binding ambiguous. *Phase: 4.*

11. **Large-repo performance (§12.11)** — a 500-file repo should finish in < 30 s:
    - Parse once, cache `ParsedModule` by `(path, mtime)`; never re-parse.
    - One shared `jedi.Project` for the whole run (reuses jedi's cache across `Script`s).
    - Parallelize parsing with `concurrent.futures.ProcessPoolExecutor` (ast.parse is CPU-bound).
    - Stop recursing at external packages (biggest win for third-party-heavy projects).
    *Phases: 3, 4.*

## Verification (guide §14.2)
Grep generated code for these strings — absence usually means the edge case was skipped:
`TYPE_CHECKING`, `__all__`, `cycle`, `external`, `__main__`, `is_synthetic`, `import_module`,
`version_info`. Confirm every file-read and every jedi call is wrapped in `try/except`, and that no
regex is run over Python source.

## Implementation notes
This file has no module of its own — it's the contract enforcement layer. When implementing any phase,
open this list and confirm which items that phase owns (annotated *Phases:* above) before declaring it
done. Mirror the checkboxes in `claude.md`.
