"""Phase 8 — Graph assembly & analysis.

Assembles the fully-annotated ProjectGraph into a networkx.DiGraph and runs:
  1. Cycle detection via nx.simple_cycles
  2. Dead-code (unused symbol) candidate detection
  3. Community detection (Louvain) on the module/package subgraph
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import networkx as nx

from pyviz.models import ProjectGraph

# ---------------------------------------------------------------------------
# Output type (networkx stays out of models.py)
# ---------------------------------------------------------------------------

@dataclass
class GraphAssemblyResult:
    graph: Any                              # networkx.DiGraph
    cycles: list[list[str]] = field(default_factory=list)
    unused: list[str] = field(default_factory=list)
    communities: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assemble(pg: ProjectGraph) -> GraphAssemblyResult:
    """Build the networkx graph and run all post-processing analyses."""
    G = build_nx_graph(pg)
    cycles = find_cycles(G)
    unused = list(_find_unused_symbols(G, pg))
    communities = _detect_communities(G)
    return GraphAssemblyResult(graph=G, cycles=cycles, unused=unused, communities=communities)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_nx_graph(pg: ProjectGraph) -> nx.DiGraph:
    """Convert ProjectGraph nodes/edges to a networkx DiGraph."""
    G: nx.DiGraph = nx.DiGraph()
    for nid, n in pg.nodes.items():
        G.add_node(
            nid,
            kind=n.kind.value,
            file=n.file,
            line=n.line,
            is_async=n.is_async,
            is_abstract=n.is_abstract,
        )
    for e in pg.edges:
        G.add_edge(
            e.src,
            e.dst,
            kind=e.kind.value,
            confidence=e.confidence.value,
            line=e.line,
        )
    return G


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

def find_cycles(G: nx.DiGraph) -> list[list[str]]:
    """Return deduplicated cycles found in the full graph."""
    seen: set[tuple[str, ...]] = set()
    result: list[list[str]] = []
    for cycle in nx.simple_cycles(G):
        key = tuple(sorted(cycle))
        if key not in seen:
            seen.add(key)
            result.append(list(cycle))
    return result


# ---------------------------------------------------------------------------
# Unused symbol detection
# ---------------------------------------------------------------------------

_CALL_KINDS: frozenset[str] = frozenset({'calls', 'inherits', 'decorates'})
_CALLABLE_KINDS: frozenset[str] = frozenset(
    {'function', 'method', 'class', 'classmethod', 'staticmethod'}
)


def _find_unused_symbols(G: nx.DiGraph, pg: ProjectGraph) -> Iterator[str]:
    """Yield FQNs of callable nodes that have no incoming call/inherit/decorate edges."""
    exported: set[str] = set()
    for nid, n in pg.nodes.items():
        for name in n.all_exports:
            exported.add(f'{nid}.{name}')

    roots = _build_roots_set(pg)

    for nid, data in G.nodes(data=True):
        if data.get('kind') not in _CALLABLE_KINDS:
            continue
        name = nid.rsplit('.', 1)[-1]
        if name.startswith('__') and name.endswith('__'):
            continue  # dunders are always implicitly called
        if nid in exported:
            continue
        if nid in roots:
            continue
        incoming = [
            d for _, _, d in G.in_edges(nid, data=True)
            if d.get('kind') in _CALL_KINDS
        ]
        if not incoming:
            yield nid


def _build_roots_set(pg: ProjectGraph) -> set[str]:
    """Return node FQNs that are unconditionally alive (tests, __main__, entry points)."""
    roots: set[str] = set()
    for nid, node in pg.nodes.items():
        if node.file is None:
            continue
        fname = Path(node.file).name
        if fname.startswith('test_') or fname.endswith('_test.py') or fname == '__main__.py':
            roots.add(nid)
    return roots


# ---------------------------------------------------------------------------
# Community detection
# ---------------------------------------------------------------------------

def _detect_communities(G: nx.DiGraph) -> dict[str, int]:
    """Cluster module/package nodes using Louvain community detection."""
    module_kinds = {'module', 'package'}
    module_nodes = [nid for nid, d in G.nodes(data=True) if d.get('kind') in module_kinds]
    if not module_nodes:
        return {}
    subG = G.subgraph(module_nodes).to_undirected()
    try:
        from networkx.algorithms.community import louvain_communities
        communities_list = louvain_communities(subG, seed=42)
        return {node: i for i, comm in enumerate(communities_list) for node in comm}
    except Exception:
        return {}
