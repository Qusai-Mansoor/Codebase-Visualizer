# Phase 2: Discovery (engine/discovery.py)

> Guide §3 ("Phase 1 — Discovery").

## What it does
Discovery answers one question: given a path on disk, what Python modules exist here, and what are
their fully-qualified (dotted) names? Every later phase depends on this map. Get it wrong and import
resolution will silently use the wrong files.

## Input
A `pathlib.Path` pointing at the project root.

## Output
`DiscoveryResult`:
```python
@dataclass
class DiscoveryResult:
    root: Path
    module_map: dict[str, Path]   # dotted_name -> absolute path to .py file
    package_map: dict[str, Path]  # dotted_name -> absolute path to package dir
    skipped: dict[Path, str]      # path -> reason string
```

## Key algorithm (from guide §3.4)
```python
SKIP_DIRS = {
  '.git', '.venv', 'venv', 'env', '.env',
  '__pycache__', 'node_modules', '.tox',
  'build', 'dist', '.eggs',  # plus '*.egg-info' handled by suffix check
  '.mypy_cache', '.pytest_cache', '.ruff_cache',
}
MAX_FILE_BYTES = 2_000_000  # skip files > 2 MB (generated files)

def discover(root: Path) -> DiscoveryResult:
    root = root.resolve()
    module_map, package_map, skipped = {}, {}, {}
    for py_file in root.rglob('*.py'):
        rel = py_file.relative_to(root)
        if any(part in SKIP_DIRS or part.endswith('.egg-info') for part in rel.parts):
            skipped[py_file] = 'in skip directory'; continue
        if py_file.stat().st_size > MAX_FILE_BYTES:
            skipped[py_file] = f'too large ({py_file.stat().st_size} bytes)'; continue
        parts = list(rel.parts)
        parts[-1] = parts[-1][:-3]            # strip .py
        dotted = '.'.join(parts)
        module_map[dotted] = py_file
        if parts[-1] == '__init__':
            pkg_dotted = '.'.join(parts[:-1]) if len(parts) > 1 else parts[0]
            package_map[pkg_dotted] = py_file.parent
            module_map[pkg_dotted] = py_file   # 'mypkg' -> mypkg/__init__.py
    return DiscoveryResult(root, module_map, package_map, skipped)
```

## Edge cases (guide §3.5)
1. **Namespace packages (no `__init__.py`)** — `rglob` still finds the `.py` files, but no package is
   registered. After building `module_map`, infer packages: for any `a.b.c`, ensure `a` and `a.b`
   exist in `package_map` even without an `__init__.py`.
2. **src-layout detection** — if a `src/` dir exists with `__init__.py` or top-level `.py`, use `src/`
   as the base for dotted names; this affects *every* dotted name.
3. **First-party vs third-party** — only analyze the project's own code. A module whose file is inside
   the project root is first-party; anything resolving to site-packages/stdlib is external (record as
   an external node, never recurse).
4. **Stub files (`.pyi`)** — collect separately; use a `.pyi` when an imported module has no `.py`.
5. **Large/generated files (>2 MB)** — skip gracefully into `skipped`, don't fail.

## Library APIs
| API | Purpose |
|-----|---------|
| `Path.rglob('*.py')` | Recursively yields all `.py` files. |
| `Path.relative_to(root)` | Absolute → project-relative path (to compute dotted names). |
| `path.parts` | Split path into components: `('mypackage', 'core.py')`. |
| `path.stem` | Filename without extension. |
| `path.stat().st_size` | File size, for the 2 MB skip rule. |

## Common mistakes
1. **Mutating `module_map` while iterating it.** Build it fresh, then read it in later phases.
2. Forgetting to register the package alias (`'mypkg' -> mypkg/__init__.py`) for `__init__.py` files,
   so `from mypkg import X` can't be resolved.
3. Not handling namespace packages, so deeply-nested modules have no package ancestors.

## Test fixtures
- `fixtures/namespace_pkg/` — package without `__init__.py`; discovery must still find its modules.
- `fixtures/simple_pkg/` — baseline dotted-name computation.

## Implementation notes
Include both the namespace-package inference and src-layout detection — they are easy to forget and
silently corrupt every downstream phase. Never mutate the map during construction.
