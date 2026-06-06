"""Phase 7 — Decorator & dynamic dispatch.

Three responsibilities:
  1. Emit DECORATES edges (decorator FQN → decorated node FQN) for all
     decorators whose binding resolves to a first-party definition.
  2. Tag GraphNode.role for known framework patterns (pattern matching on
     raw decorator text — no resolution required).
  3. Detect getattr(obj, name)() dynamic dispatch and record
     AnalysisWarning(kind='dynamic_dispatch').
"""
from __future__ import annotations

import ast
from typing import Optional

from pyviz.models import (
    AnalysisWarning,
    Confidence,
    DiscoveryResult,
    EdgeKind,
    GraphEdge,
    ParseResult,
    ParsedModule,
    ProjectGraph,
    ResolvedBinding,
    ResolverResult,
)

# ---------------------------------------------------------------------------
# Role pattern table — (suffixes_to_match, role_string)
# Matched by stripping call-args from decorator text then checking suffix.
# ---------------------------------------------------------------------------

_ROLE_PATTERNS: list[tuple[list[str], str]] = [
    (
        [
            'app.get', 'app.post', 'app.put', 'app.delete', 'app.patch',
            'router.get', 'router.post', 'router.put', 'router.delete', 'router.patch',
            'app.route', 'bp.route',
        ],
        'http_endpoint',
    ),
    (['login_required'], 'auth_guarded'),
    (['pytest.fixture', 'fixture'], 'test_fixture'),
    (['app.task', 'celery.task', 'shared_task'], 'background_task'),
    (['property'], 'property'),
    (['abstractmethod', 'abc.abstractmethod'], 'abstract'),
    (['dataclass'], 'dataclass'),
    (['click.command', 'typer.command'], 'cli_command'),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_all(
    parse_result: ParseResult,
    resolver_result: ResolverResult,
    graph: ProjectGraph,
    discovery: DiscoveryResult,
) -> ProjectGraph:
    """Annotate *graph* with DECORATES edges, role tags, and dispatch warnings."""
    for parsed_mod in parse_result.parsed.values():
        rf = _rel_file(parsed_mod, discovery)
        _extract_decorator_edges(parsed_mod, graph, resolver_result, rf)
        _detect_getattr_dispatch(parsed_mod, graph, rf)
    return graph


# ---------------------------------------------------------------------------
# DECORATES edges + role tagging
# ---------------------------------------------------------------------------

def _extract_decorator_edges(
    module: ParsedModule,
    graph: ProjectGraph,
    resolver: ResolverResult,
    rel_file: str,
) -> None:
    # Canonical module name: strip '.__init__' so both package and __init__ runs
    # look up the same local FQN and produce deduplicatable edges.
    canonical = module.module_name.removesuffix('.__init__')

    for node_fqn, gnode in graph.nodes.items():
        if gnode.file != rel_file:
            continue
        role = _classify_role(gnode.decorators)
        if role:
            gnode.role = role
        for dec_text in gnode.decorators:
            base_name = dec_text.split('(')[0].strip()
            dec_fqn: Optional[str] = None
            # 1. Try resolved import binding (use original module name for binding lookup)
            binding = resolver.bindings.get((module.module_name, base_name))
            if not isinstance(binding, ResolvedBinding):
                binding = resolver.bindings.get((canonical, base_name))
            if isinstance(binding, ResolvedBinding):
                dec_fqn = binding.real_fqn
            else:
                # 2. Try locally-defined decorator (same module, no dots)
                if '.' not in base_name:
                    local = f'{canonical}.{base_name}'
                    if local in graph.nodes:
                        dec_fqn = local
            if dec_fqn is not None:
                # Deduplicate (both pkg and pkg.__init__ runs produce same edge)
                if not any(
                    e.kind == EdgeKind.DECORATES and e.src == dec_fqn and e.dst == node_fqn
                    for e in graph.edges
                ):
                    graph.edges.append(GraphEdge(
                        src=dec_fqn,
                        dst=node_fqn,
                        kind=EdgeKind.DECORATES,
                        confidence=Confidence.STATIC,
                        file=rel_file,
                    ))


def _classify_role(decorators: list[str]) -> Optional[str]:
    for dec in decorators:
        base = dec.split('(')[0].strip()
        for patterns, role in _ROLE_PATTERNS:
            for pat in patterns:
                if base == pat or base.endswith(f'.{pat}') or base == pat.split('.')[-1]:
                    return role
    return None


# ---------------------------------------------------------------------------
# getattr dynamic dispatch detection
# ---------------------------------------------------------------------------

def _detect_getattr_dispatch(
    module: ParsedModule,
    graph: ProjectGraph,
    rel_file: str,
) -> None:
    detector = _GetAttrDetector(module.module_name, graph, rel_file)
    detector.visit(module.tree)


class _GetAttrDetector(ast.NodeVisitor):
    def __init__(self, module_name: str, graph: ProjectGraph, rel_file: str) -> None:
        self.module_name = module_name
        self.graph = graph
        self.rel_file = rel_file

    def visit_Call(self, node: ast.Call) -> None:
        # Pattern: getattr(obj, name)() — the outer Call's func is itself a Call to getattr
        if (
            isinstance(node.func, ast.Call)
            and isinstance(node.func.func, ast.Name)
            and node.func.func.id == 'getattr'
        ):
            self.graph.warnings.append(AnalysisWarning(
                kind='dynamic_dispatch',
                message=f'{self.module_name}: getattr-based dispatch detected',
                file=self.rel_file,
                line=getattr(node, 'lineno', None),
            ))
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Internal utility
# ---------------------------------------------------------------------------

def _rel_file(parsed_mod: ParsedModule, discovery: DiscoveryResult) -> str:
    try:
        return str(parsed_mod.file.relative_to(discovery.root))
    except ValueError:
        return str(parsed_mod.file)
