# Phase 4: Import Resolution (engine/resolver.py)

> Guide §5 ("Phase 3 — Import Resolution"). **The most important phase — and the largest.**

## What it does
Answers: when module A imports name X, what is X's *actual definition site*? The naive answer is "the
module you imported it from"; the correct answer is "the file and line where X was created with `def`
/ `class` / assignment". The difference is exactly the `__init__.py` re-export bug the brief tests for.

## Input
`DiscoveryResult` + `ParseResult`.

## Output
`ResolverResult` — a binding table. For every `(module, imported_name)` pair, a `ResolvedBinding`
(found the real definition) or an `UnresolvedBinding` (gave up).
```python
@dataclass
class ResolvedBinding:
    name: str               # original imported name
    real_module: str        # dotted module where it's actually defined
    real_file: Path
    real_line: int
    real_fqn: str           # 'mypkg.core.MyClass'
    is_type_only: bool = False  # came from inside TYPE_CHECKING
    is_wildcard: bool = False   # came from 'from x import *'

@dataclass
class UnresolvedBinding:
    name: str
    reason: str             # 'external' | 'dynamic' | 'cycle' | 'not_found'
    import_source: str

Binding = ResolvedBinding | UnresolvedBinding

@dataclass
class ResolverResult:
    bindings: dict[tuple[str, str], Binding]   # (importer_module, local_name) -> Binding
    warnings: list[AnalysisWarning]
```

## Key algorithms — two strategies (guide §5.4)
**Strategy A (jedi, primary):** fast, handles most cases.
```python
script = jedi.Script(source=module.source, path=str(module.file),
                     project=jedi.Project(path=str(project_root)))
defns = [d for d in script.infer(line=import_line, column=0) if d.module_path]
# If jedi resolves to an __init__ that re-exports, hand off to Strategy B.
if d.module_path and '__init__' in str(d.module_path):
    return _follow_init_reexport(module, name, d, project_root)
```
A `Definition` exposes `.module_path`, `.line`, `.name`, `.full_name`, `.type`.

**Strategy B (manual `__init__.py` re-export follower, fallback / correctness core):** when jedi
resolves to `__init__.py` or fails, walk the import chain by hand with a cycle guard.
```python
def follow_import_chain(module_name, symbol_name, parse_result, discovery, visited):
    key = (module_name, symbol_name)
    if key in visited:
        return UnresolvedBinding(symbol_name, 'cycle', module_name)
    visited.add(key)
    mod = parse_result.parsed.get(module_name)
    if mod is None:
        return UnresolvedBinding(symbol_name, 'external', module_name)
    for node in ast.iter_child_nodes(mod.tree):
        # def/class with matching name  -> ResolvedBinding (real_line = node.lineno)
        # module-level Assign to name   -> ResolvedBinding (alias)
        # ImportFrom re-export          -> recurse into resolve_module_name(...) source
        # wildcard 'from .x import *'   -> recurse, return if Resolved
    return UnresolvedBinding(symbol_name, 'not_found', module_name)
```
**Relative import helper:** `resolve_module_name(module, level, current_module, discovery)` —
`level 0` = absolute; `level 1` = same package; `level 2` = parent. Anchor = `current.split('.')[:-level]`.

## Edge cases
1. **`__init__.py` re-exports** — never stop at `__init__.py`; follow `from .core import Thing` to
   `core.py` and report `real_line` of the actual `def`/`class`. This is the headline correctness test.
2. **`__all__` and wildcards** (guide §5.5) — `get_exported_names`: read `__all__` if it's a literal
   list/tuple of strings; if dynamic, return `[]` and warn; with no `__all__`, export every top-level
   name not starting with `_`. For `from x import *`, only resolve names actually exported by `x`.
3. **TYPE_CHECKING imports** (guide §5.6) — detect `if TYPE_CHECKING:` / `if typing.TYPE_CHECKING:`
   blocks; mark bindings `is_type_only=True`. These must NOT produce call edges.
4. **Cycles** — the `visited` set breaks circular re-export chains; report `reason='cycle'`.
5. **External / not-found** — module not in `parse_result.parsed` → `external`; surface as a warning,
   never crash.

## Library APIs — jedi
| API | Purpose |
|-----|---------|
| `jedi.Project(path=root)` | One project for the whole run (shares cache). |
| `jedi.Script(source, path, project)` | A queryable view of one file. |
| `script.infer(line, column)` | Returns `Definition` objects for a name at a position. |
| `Definition.module_path / .line / .name / .full_name / .type` | The real definition site. |
| `ast.iter_child_nodes`, `ast.ImportFrom`, `ast.Assign` | Manual chain following. |

## Common mistakes
1. **Trusting jedi when it lands on `__init__.py`** — that's the re-export trap; always fall back to
   Strategy B there.
2. **Asking jedi "what does this file import?"** — jedi is for *name resolution* only; never use it as
   an import scanner, and never regex the source.
3. **Treating TYPE_CHECKING imports as runtime** — produces phantom dependencies / call edges.
4. **Forgetting to still emit an IMPORTS edge** even when resolution succeeds (the import happened
   regardless; dead-code detection needs it — see Phase 6).

## Test fixtures
- `fixtures/reexport_pkg/` — `from .core import Thing`; binding must point at `core.py`, not `__init__.py`.
- `fixtures/circular_import_a/` + `circular_import_b/` — mutual re-export; cycle guard must engage.
- `fixtures/type_checking_only/` — import under `if TYPE_CHECKING`; `is_type_only=True`, no call edge.
- (wildcard/`__all__`) — a fixture where `__all__ = ['foo']` so only `foo` resolves.

## Implementation notes
Use jedi as primary with the manual follower as fallback. Wrap every jedi call in `try/except`. Stop
recursing the moment a binding is identified as external (biggest perf win, guide §12.11). This phase
needs careful review — re-read guide §5 in full before implementing.
