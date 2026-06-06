---
name: project-architecture
description: Core architecture, module roles, and data flow for Phases 1-4 of the Python Codebase Visualizer
metadata:
  type: project
---

Python Codebase Visualizer — Phases 1–4 architecture snapshot (Session 4, 2026-06-06).

**Why:** Recorded to accelerate future verification sessions without re-reading all files.
**How to apply:** Use as orientation before diving into any phase verification task.

## Module Roles
- `pyviz/models.py` — shared dataclasses/enums consumed by all phases. Defines NodeKind, EdgeKind, Confidence, GraphNode, GraphEdge, AnalysisWarning, ProjectGraph, DiscoveryResult, ParsedModule, ParseResult, ResolvedBinding, UnresolvedBinding, ResolverResult.
- `pyviz/engine/discovery.py` — Phase 2. `discover(root)` → DiscoveryResult. Builds module_map, package_map, stub_map, skipped. Helpers: _detect_src_layout, _should_skip_path, _collect_py_files, _collect_pyi_files, _infer_namespace_packages.
- `pyviz/engine/parser.py` — Phase 3. `parse_all(discovery)` → ParseResult. Helpers: _read_source (UTF-8 then latin-1), _looks_like_version_mismatch.
- `pyviz/engine/resolver.py` — Phase 4. `resolve_all(discovery, parse_result)` → ResolverResult. Strategy B (manual AST chain) primary for internal; Strategy A (jedi) for externals only. Key helpers: _resolve_module_imports, _process_import, _record_binding, _follow_chain, _handle_wildcard, _resolve_relative, _get_type_checking_ranges, _is_type_checking_test, _get_exported_names, _make_jedi_project, _try_jedi_binding.

## Known Issues (verified 2026-06-06)
1. **Double registration / duplicate processing:** module_map stores both 'mypkg.__init__' and 'mypkg' pointing to the same file. parse_all parses it twice; resolve_all processes its imports twice, creating duplicate binding keys. Spec-compliant but causes redundant work and duplicate bindings.
2. **Silent failure for parse-failed internal modules:** When an internal module is in module_map but failed to parse (SyntaxError), _follow_chain returns UnresolvedBinding(reason='external'). The warning-suppression condition `reason != 'external' or src_module not in module_map` evaluates False (external AND in map), so NO warning is emitted. The binding silently appears as 'external'.
3. **Wildcard re-export gap in _follow_chain:** `from .core import *` in __init__.py is not followed. A consumer doing `from mypkg import Thing` when mypkg/__init__.py does `from .core import *` returns UnresolvedBinding(not_found). Spec pseudocode says to recurse on wildcard re-exports.
4. **Dotted `import foo.bar` binds wrong local name:** Python binds 'foo', not 'foo.bar'. Implementation uses 'foo.bar' as the binding key.
5. **`_resolve_relative` anchor is never None:** `if anchor is None` is dead code.
6. **src-layout detection misses namespace packages:** If src/ contains only a namespace package (no __init__.py and no direct .py files), _detect_src_layout returns root instead of src/, causing wrong dotted names ('src.nspkg.mod' instead of 'nspkg.mod').
7. **`__all__ +=` augmented assignment not detected:** _get_exported_names only finds Assign nodes, not AugAssign.
8. **_collect_pyi_files skipped entries not added to skipped dict:** Comment says 'already captured via .py pass' but .py pass only captures .py files; .pyi files in skip dirs are silently dropped without a skipped entry.

## Test fixtures location
`pyviz/tests/fixtures/`: simple_pkg, namespace_pkg, parse_suite, reexport_pkg, circular_import_a, circular_import_b, type_checking_only, allexport_pkg.

## Test counts (Session 4)
107 tests total: 27 models + 25 discovery + 25 parser + 26 resolver (+ 4 new = 107).
