"""Phase 4 — Import resolution.

For every (module, imported_name) pair, resolves the *actual* definition site:
the file and line of the `def`/`class`/assignment, not just the re-export module.

Two strategies:
  Strategy B (primary for internal modules): manual AST chain-follower.
  Strategy A (jedi, optional): used only for modules NOT in module_map; falls back
      to UnresolvedBinding(external) if jedi is unavailable or fails.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

from pyviz.models import (
    AnalysisWarning,
    Binding,
    DiscoveryResult,
    ParseResult,
    ParsedModule,
    ResolvedBinding,
    ResolverResult,
    UnresolvedBinding,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_all(discovery: DiscoveryResult, parse_result: ParseResult) -> ResolverResult:
    """Resolve every import in every parsed module."""
    bindings: dict[tuple[str, str], Binding] = {}
    warnings: list[AnalysisWarning] = []

    jedi_project = _make_jedi_project(discovery.root)

    for module_name, parsed_mod in parse_result.parsed.items():
        _resolve_module_imports(
            module_name, parsed_mod,
            discovery, parse_result,
            jedi_project, bindings, warnings,
        )

    return ResolverResult(bindings=bindings, warnings=warnings)


# ---------------------------------------------------------------------------
# Per-module import resolution
# ---------------------------------------------------------------------------

def _resolve_module_imports(
    module_name: str,
    parsed_mod: ParsedModule,
    discovery: DiscoveryResult,
    parse_result: ParseResult,
    jedi_project,
    bindings: dict,
    warnings: list,
) -> None:
    tc_ranges = _get_type_checking_ranges(parsed_mod.tree)
    vg_ranges = _get_version_gated_ranges(parsed_mod.tree)

    for node in ast.walk(parsed_mod.tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        lineno = getattr(node, 'lineno', 0)
        is_type_only = any(start <= lineno <= end for start, end in tc_ranges)
        is_conditional = any(start <= lineno <= end for start, end in vg_ranges)
        _process_import(
            node, module_name, is_type_only, is_conditional,
            parsed_mod, discovery, parse_result,
            jedi_project, bindings, warnings,
        )


def _process_import(
    node: ast.stmt,
    module_name: str,
    is_type_only: bool,
    is_conditional: bool,
    parsed_mod: ParsedModule,
    discovery: DiscoveryResult,
    parse_result: ParseResult,
    jedi_project,
    bindings: dict,
    warnings: list,
) -> None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            local_name = alias.asname if alias.asname else alias.name
            src_module = alias.name
            key = (module_name, local_name)
            binding = _record_binding(
                src_module, alias.name, is_type_only, is_conditional, False,
                parse_result, discovery, jedi_project,
                parsed_mod, node, warnings, module_name,
            )
            bindings[key] = binding

    elif isinstance(node, ast.ImportFrom):
        is_pkg = module_name in discovery.package_map
        src_module = _resolve_relative(node, module_name, is_package=is_pkg)
        if src_module is None:
            return

        for alias in node.names:
            if alias.name == '*':
                _handle_wildcard(
                    src_module, module_name, is_type_only,
                    parse_result, discovery, jedi_project,
                    parsed_mod, node, bindings, warnings,
                )
                continue

            local_name = alias.asname if alias.asname else alias.name
            key = (module_name, local_name)
            binding = _record_binding(
                src_module, alias.name, is_type_only, is_conditional, False,
                parse_result, discovery, jedi_project,
                parsed_mod, node, warnings, module_name,
            )
            bindings[key] = binding


def _record_binding(
    src_module: str,
    import_name: str,
    is_type_only: bool,
    is_conditional: bool,
    is_wildcard: bool,
    parse_result: ParseResult,
    discovery: DiscoveryResult,
    jedi_project,
    parsed_mod: ParsedModule,
    import_node: ast.stmt,
    warnings: list,
    importer_module: str,
) -> Binding:
    if src_module in discovery.module_map:
        result = _follow_chain(src_module, import_name, parse_result, discovery, frozenset())
    else:
        result = _try_jedi_binding(
            src_module, import_name, is_type_only,
            parsed_mod, import_node, jedi_project,
        )
        if result is None:
            result = UnresolvedBinding(import_name, 'external', importer_module)

    if isinstance(result, UnresolvedBinding):
        reason = result.reason
        if reason != 'external' or src_module not in discovery.module_map:
            warnings.append(AnalysisWarning(
                kind='unresolved_import',
                message=f'{importer_module}: cannot resolve {src_module}.{import_name} ({reason})',
                file=str(parsed_mod.file),
                line=getattr(import_node, 'lineno', None),
            ))
    elif isinstance(result, ResolvedBinding):
        result.is_type_only = is_type_only
        result.is_conditional = is_conditional
        result.is_wildcard = is_wildcard

    return result


# ---------------------------------------------------------------------------
# Strategy B — manual AST chain follower
# ---------------------------------------------------------------------------

def _follow_chain(
    module_name: str,
    symbol_name: str,
    parse_result: ParseResult,
    discovery: DiscoveryResult,
    visited: frozenset,
) -> Binding:
    key = (module_name, symbol_name)
    if key in visited:
        return UnresolvedBinding(symbol_name, 'cycle', module_name)
    visited = visited | {key}

    mod = parse_result.parsed.get(module_name)
    if mod is None:
        return UnresolvedBinding(symbol_name, 'external', module_name)

    for node in ast.iter_child_nodes(mod.tree):
        # def / async def / class
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == symbol_name:
                return ResolvedBinding(
                    name=symbol_name,
                    real_module=module_name,
                    real_file=mod.file,
                    real_line=node.lineno,
                    real_fqn=f'{module_name}.{symbol_name}',
                )

        # assignment: FOO = ...
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == symbol_name:
                    return ResolvedBinding(
                        name=symbol_name,
                        real_module=module_name,
                        real_file=mod.file,
                        real_line=node.lineno,
                        real_fqn=f'{module_name}.{symbol_name}',
                    )

        # annotated assignment: FOO: int = ...
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == symbol_name:
                return ResolvedBinding(
                    name=symbol_name,
                    real_module=module_name,
                    real_file=mod.file,
                    real_line=node.lineno,
                    real_fqn=f'{module_name}.{symbol_name}',
                )

        # re-export: from .core import Thing
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                local = alias.asname if alias.asname else alias.name
                if local == symbol_name and alias.name != '*':
                    is_pkg = module_name in discovery.package_map
                    src2 = _resolve_relative(node, module_name, is_package=is_pkg)
                    if src2 is None:
                        continue
                    return _follow_chain(src2, alias.name, parse_result, discovery, visited)

    return UnresolvedBinding(symbol_name, 'not_found', module_name)


# ---------------------------------------------------------------------------
# Wildcard import handler
# ---------------------------------------------------------------------------

def _handle_wildcard(
    src_module: str,
    importer_module: str,
    is_type_only: bool,
    parse_result: ParseResult,
    discovery: DiscoveryResult,
    jedi_project,
    parsed_mod: ParsedModule,
    import_node: ast.stmt,
    bindings: dict,
    warnings: list,
) -> None:
    exported = _get_exported_names(src_module, parse_result)
    if not exported:
        warnings.append(AnalysisWarning(
            kind='unresolved_import',
            message=f'{importer_module}: wildcard from {src_module} — could not determine exports',
            file=str(parsed_mod.file),
            line=getattr(import_node, 'lineno', None),
        ))
        return

    for name in exported:
        key = (importer_module, name)
        binding = _follow_chain(src_module, name, parse_result, discovery, frozenset())
        if isinstance(binding, ResolvedBinding):
            binding.is_type_only = is_type_only
            binding.is_wildcard = True
        bindings[key] = binding


# ---------------------------------------------------------------------------
# Relative import resolution
# ---------------------------------------------------------------------------

def _resolve_relative(
    import_node: ast.ImportFrom,
    current_module: str,
    is_package: bool = False,
) -> Optional[str]:
    level = import_node.level
    module = import_node.module  # may be None for 'from . import foo'

    if level == 0:
        return module  # absolute import

    parts = current_module.split('.')
    # For __init__.py modules (is_package=True), the current module IS the package;
    # for regular modules, strip one component to get the package.
    anchor = parts[:] if is_package else parts[:-1]

    # level > 1: go up additional package levels
    if level > 1:
        up = level - 1
        anchor = anchor[:-up] if up < len(anchor) else []

    if anchor is None or (level > len(parts) and not is_package):
        return None

    if module:
        return '.'.join(anchor + [module])
    return '.'.join(anchor) if anchor else None


# ---------------------------------------------------------------------------
# TYPE_CHECKING block detection
# ---------------------------------------------------------------------------

def _get_type_checking_ranges(tree: ast.Module) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking_test(node.test):
            start = node.lineno
            end = max(
                (getattr(n, 'end_lineno', getattr(n, 'lineno', start)) for n in ast.walk(node)),
                default=start,
            )
            ranges.append((start, end))
    return ranges


def _is_type_checking_test(test: ast.expr) -> bool:
    if isinstance(test, ast.Name) and test.id == 'TYPE_CHECKING':
        return True
    if isinstance(test, ast.Attribute) and test.attr == 'TYPE_CHECKING':
        return True
    return False


def _get_version_gated_ranges(tree: ast.Module) -> list[tuple[int, int]]:
    """Return (start_line, end_line) pairs for if sys.version_info ... blocks (both branches)."""
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if isinstance(test, ast.Compare) and isinstance(test.left, ast.Attribute):
            attr = test.left
            if (
                attr.attr == 'version_info'
                and isinstance(attr.value, ast.Name)
                and attr.value.id == 'sys'
            ):
                start = node.lineno
                end = max(
                    (getattr(n, 'end_lineno', getattr(n, 'lineno', start)) for n in ast.walk(node)),
                    default=start,
                )
                ranges.append((start, end))
    return ranges


# ---------------------------------------------------------------------------
# __all__ / exported name helpers
# ---------------------------------------------------------------------------

def _get_exported_names(module_name: str, parse_result: ParseResult) -> list[str]:
    mod = parse_result.parsed.get(module_name)
    if mod is None:
        return []

    for node in ast.iter_child_nodes(mod.tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == '__all__':
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        names = []
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                names.append(elt.value)
                        return names
                    return []  # dynamic __all__

    # No __all__ — export all public top-level names
    names: list[str] = []
    for node in ast.iter_child_nodes(mod.tree):
        name: Optional[str] = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    break
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                name = node.target.id
        if name and not name.startswith('_'):
            names.append(name)
    return names


# ---------------------------------------------------------------------------
# Strategy A — jedi (optional)
# ---------------------------------------------------------------------------

def _make_jedi_project(root: Path):
    try:
        import jedi
        return jedi.Project(path=str(root))
    except Exception:
        return None


def _try_jedi_binding(
    src_module: str,
    import_name: str,
    is_type_only: bool,
    parsed_mod: ParsedModule,
    import_node: ast.stmt,
    jedi_project,
) -> Optional[ResolvedBinding]:
    if jedi_project is None:
        return None
    try:
        import jedi
        script = jedi.Script(
            source=parsed_mod.source,
            path=str(parsed_mod.file),
            project=jedi_project,
        )
        lineno = getattr(import_node, 'lineno', 1)
        lines = parsed_mod.source.splitlines()
        if lineno > len(lines):
            return None
        line_text = lines[lineno - 1]
        import_kw = 'import '
        idx = line_text.find(import_kw)
        if idx == -1:
            return None
        col = line_text.find(import_name, idx + len(import_kw))
        if col == -1:
            return None

        defns = script.goto(line=lineno, column=col)
        for d in defns:
            mp = d.module_path
            if mp and str(mp).endswith('.py') and '__init__' not in str(mp):
                fqn = d.full_name or f'{src_module}.{import_name}'
                return ResolvedBinding(
                    name=import_name,
                    real_module=src_module,
                    real_file=Path(str(mp)),
                    real_line=d.line or 1,
                    real_fqn=fqn,
                    is_type_only=is_type_only,
                )
    except Exception:
        pass
    return None
