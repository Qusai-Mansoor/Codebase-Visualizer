# Integration Plan: How Phases Connect

## Doc numbering vs. guide numbering

The `docs/` files are numbered `01–12`. The Core Implementation Guide numbers the *analysis* phases
starting at Discovery = "Phase 1". Mapping:

| Doc file | Guide section | Module |
|----------|---------------|--------|
| 01_MODELS | §2 | `models.py` |
| 02_DISCOVERY | §3 (Phase 1) | `engine/discovery.py` |
| 03_PARSING | §4 (Phase 2) | `engine/parser.py` |
| 04_IMPORT_RESOLUTION | §5 (Phase 3) | `engine/resolver.py` |
| 05_DEFINITIONS | §6 (Phase 4) | `engine/definitions.py` |
| 06_CALL_EDGES | §7 (Phase 5) | `engine/calls.py` |
| 07_DECORATORS_DISPATCH | §8 (Phase 6) | `engine/decorators.py` |
| 08_GRAPH_ASSEMBLY | §9 (Phase 7) | `engine/graph.py` |
| 09_SERIALIZATION | §10 (Phase 8) | `engine/serializer.py` |
| 10_RUNTIME_TRACING | §11 (Phase 9) | `engine/tracer.py` |
| 11_IMPLICIT_REQUIREMENTS | §12 | (cross-cutting) |
| 12_TESTING_STRATEGY | §13 | `tests/` |

## Data Flow

```
Discovery (02)
    │  DiscoveryResult: module_map, package_map, skipped
    ▼
Parser (03)
    │  ParseResult: parsed {name -> ParsedModule}, failed {name -> error}
    ▼
Import Resolution (04)
    │  ResolverResult: bindings {(module, name) -> Resolved|Unresolved}, warnings
    ▼
Definition Extraction (05)  +  Call Edge Extraction (06)
    │  ProjectGraph: nodes {id -> GraphNode} + edges [GraphEdge]
    ▼
Decorators & Dynamic Dispatch (07)
    │  annotated ProjectGraph (DECORATES edges, role tags, dispatch warnings)
    ▼
Graph Assembly & Analysis (08)   +   Runtime Tracing (10, optional)
    │  networkx.DiGraph + cycles + unused symbols + communities
    ▼
Serialization (09)
    │  JSON output (nodes / edges / meta) for the browser
    ▼
   done
```

## Key dependencies
- **04 must precede 05/06** — call edges and inheritance edges need resolved import bindings.
- **05 must precede 06** — call resolution checks `graph.nodes` for locally-defined names.
- **07 must precede 08** — the graph must be fully annotated before analysis.
- **10 (tracer) is optional** — it runs independently against the test suite and merges at the end,
  upgrading matching static edges to `Confidence.BOTH` and adding runtime-only edges as
  `Confidence.RUNTIME`.

## Communication between phases
Every phase receives the outputs of previous phases and reads its dataclasses from `models.py`.
No phase re-implements discovery, parsing, or import resolution. The single shared data model
(`models.py`) is the contract; changing a field there ripples through every phase and the frontend.

## CLI entry point flow
```
cli.analyze(repo_path) →
  discovery.discover(root)              # 02
  parser.parse_all(discovery)           # 03
  resolver.resolve_all(discovery, parse)# 04
  definitions.extract_all(...)          # 05
  calls.extract_all(...)                # 06
  decorators.extract_all(...)           # 07
  graph.assemble(project_graph)         # 08  -> nx graph, cycles, unused, communities
  (optional) tracer.trace_test_suite()  # 10
  serializer.serialize(...)             # 09
  return JSON
```
