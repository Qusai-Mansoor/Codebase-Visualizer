# Phase 8: Graph Assembly & Analysis (engine/graph.py)

> Guide §9 ("Phase 7 — Graph Assembly & Analysis").

## What it does
Assembles all nodes/edges into a `networkx.DiGraph` and runs post-processing analyses: circular import
detection, dead-code (unused symbol) candidates, and community detection for clustering.

## Input
A fully-annotated `ProjectGraph` (after Phases 5–7, optionally merged with runtime edges from Phase 10).

## Output
- `nx.DiGraph` with node/edge attributes
- `cycles: list[list[str]]`
- `unused: list[str]`
- `communities: dict[str, int]` (node_id → community id)

## Build the networkx graph (guide §9.2)
```python
import networkx as nx
def build_nx_graph(pg: ProjectGraph) -> nx.DiGraph:
    G = nx.DiGraph()
    for nid, n in pg.nodes.items():
        G.add_node(nid, kind=n.kind.value, file=n.file, line=n.line,
                   is_async=n.is_async, is_abstract=n.is_abstract)
    for e in pg.edges:
        G.add_edge(e.src, e.dst, kind=e.kind.value,
                   confidence=e.confidence.value, line=e.line)
    return G
```

## Circular import detection (guide §9.3)
Build a subgraph of module/package nodes + `imports` edges, then `nx.simple_cycles`. Canonicalize each
cycle (`tuple(sorted(cycle))`) to dedupe.

## Dead-code / unused symbols (guide §9.4)
```python
def find_unused_symbols(G, pg):
    call_kinds = {'calls', 'inherits', 'decorates'}
    exported = {f'{nid}.{name}' for nid, n in pg.nodes.items() for name in n.all_exports}
    for nid, data in G.nodes(data=True):
        if data.get('kind') not in ('function','method','class','classmethod','staticmethod'):
            continue
        name = nid.rsplit('.', 1)[-1]
        if name.startswith('__') and name.endswith('__'):  continue   # dunders: implicit
        if nid in exported:                                  continue   # in __all__
        incoming = [d for _,_,d in G.in_edges(nid, data=True) if d.get('kind') in call_kinds]
        if not incoming:  yield nid
```
Also exclude **roots** (§12.3–12.5): pyproject `[project.scripts]` entry points, `__main__.py`, and
test functions/fixtures in `test_*.py` / `*_test.py`.

## Community detection (guide §9.5)
Convert to undirected, restrict to module/package nodes, run
`networkx.algorithms.community.louvain_communities(subG, seed=42)` → map each node to a community id.
Fall back to `{}` if Louvain is unavailable (networkx < 2.7).

## Edge cases
1. **Dunder methods are never unused** (§12.2) — `__repr__`/`__eq__`/`__hash__` are called by Python.
2. **Entry points / `__main__.py` / tests are roots** — never dead code regardless of in-degree.
3. **`__all__` exports** — excluded from unused detection.
4. **Duplicate cycles** — canonicalize to avoid reporting the same cycle multiple times.
5. **Louvain only on undirected, module-scoped subgraph** — cleaner clusters than full node set.

## Library APIs
| API | Purpose |
|-----|---------|
| `nx.DiGraph` / `add_node` / `add_edge` / `in_edges` | Build & query the graph. |
| `nx.simple_cycles(subG)` | Enumerate import cycles. |
| `networkx.algorithms.community.louvain_communities` | Cluster modules. |
| `G.to_undirected()` / `G.subgraph(nodes)` | Prep for community detection. |

## Common mistakes
1. Flagging dunders or roots as unused (false positives that discredit the whole report).
2. Running `simple_cycles` on the full graph (incl. call edges) instead of the imports-only subgraph.
3. Running Louvain on the directed graph (it expects undirected input).

## Test fixtures
- `fixtures/circular_import_a/` + `circular_import_b/` — cycle is detected exactly once.
- `fixtures/property_getter/` — property getter is not falsely "unused".
- Any fixture with a `test_*.py` — its functions are treated as roots.

## Implementation notes
Assemble the roots set (entry points from `pyproject.toml`, `__main__.py`, test files) before running
unused detection. This phase only runs after the graph is fully annotated (Phase 7 complete).
