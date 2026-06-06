# Phase 9: Serialization (engine/serializer.py)

> Guide §10 ("Phase 8 — Serialization").

## What it does
Serializes the assembled graph + analysis results into the JSON contract consumed by the frontend.
If this schema changes, the frontend breaks — document and freeze it.

## Input
`ProjectGraph` + `nx.DiGraph` + `communities` + `unused` + `cycles` + `root`.

## Output
A JSON string (`json.dumps(..., indent=2)`) with `nodes`, `edges`, and `meta`.

## JSON schema (guide §10.1, TypeScript reference)
```ts
type Node = {
  id: string; kind: string; name: string;
  file: string | null; line: number | null; end_line: number | null;
  docstring: string | null;
  is_async: boolean; is_abstract: boolean; is_protocol: boolean;
  is_dataclass: boolean; is_mixin: boolean;
  bases: string[]; decorators: string[]; warnings: string[];
  community: number | null;     // from Phase 8 community detection
  role: string | null;          // 'http_endpoint', 'test_fixture', ... from Phase 7
}
type Edge = {
  src: string; dst: string;
  kind: string;        // 'calls' | 'imports' | 'inherits' | 'decorates'
  confidence: string;  // 'static' | 'runtime' | 'both' | 'dynamic'
  file: string | null; line: number | null; is_type_only: boolean;
}
type GraphOutput = {
  nodes: Node[]; edges: Edge[];
  meta: {
    root: string; python_version: string; generated_at: string;  // ISO 8601
    circular_imports: string[][];   // each inner array is one cycle
    unused_symbols: string[];
    warnings: { kind: string; message: string; file: string|null; line: number|null }[];
  };
}
```

## Key algorithm (guide §10.2)
```python
def serialize(pg, nx_graph, communities, unused, cycles, root) -> str:
    nodes_out = [{
        'id': n.id, 'kind': n.kind.value, 'name': n.name,
        'file': n.file, 'line': n.line, 'end_line': n.end_line,
        'docstring': n.docstring,
        'is_async': n.is_async, 'is_abstract': n.is_abstract,
        'is_protocol': n.is_protocol, 'is_dataclass': n.is_dataclass,
        'is_mixin': n.is_mixin, 'bases': n.bases, 'decorators': n.decorators,
        'warnings': n.warnings, 'community': communities.get(nid),
    } for nid, n in pg.nodes.items()]

    edges_out = [{
        'src': e.src, 'dst': e.dst, 'kind': e.kind.value,
        'confidence': e.confidence.value, 'file': e.file, 'line': e.line,
        'is_type_only': e.is_type_only,
    } for e in pg.edges if e.src in pg.nodes and e.dst in pg.nodes]   # filter dangling

    output = {'nodes': nodes_out, 'edges': edges_out, 'meta': {
        'root': str(root), 'python_version': sys.version,
        'generated_at': datetime.datetime.utcnow().isoformat(),
        'circular_imports': cycles, 'unused_symbols': unused,
        'warnings': [{'kind': w.kind, 'message': w.message, 'file': w.file, 'line': w.line}
                     for w in pg.warnings],
    }}
    return json.dumps(output, indent=2)
```

## Edge cases
1. **Dangling edges** — filter so both `src` and `dst` exist in `pg.nodes` before emitting. Edges to
   un-analyzed external packages would otherwise break a frontend that assumes every endpoint has a node.
2. **Enum → string** — always emit `.value`, never the Enum object.
3. **Null fields** — external/synthetic nodes may have `null` file/line; the schema allows it.
4. **`community` / `role`** — attached here from Phase 8/7 results; default `null` when absent.
5. **ISO 8601 timestamps** — `generated_at` must be ISO format for the frontend.

## Library APIs
| API | Purpose |
|-----|---------|
| `json.dumps(output, indent=2)` | Produce the JSON string. |
| `datetime.datetime.utcnow().isoformat()` | ISO 8601 `generated_at`. |
| `sys.version` | `python_version` in meta. |

## Common mistakes
1. Not filtering dangling edges → frontend crashes on missing endpoints.
2. Serializing Enum objects instead of `.value` strings.
3. Drifting from the schema (renamed/missing fields) without updating the frontend contract.

## Test fixtures
All fixtures: freeze the serialized JSON as a snapshot and diff on every change (see Phase 12).

## Implementation notes
This file *is* the analyzer↔frontend contract. Keep it in lockstep with the TypeScript types. Use
`pytest-snapshot` (or stored expected JSON) to detect accidental schema drift.
