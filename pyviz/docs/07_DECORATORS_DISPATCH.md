# Phase 7: Decorator & Dynamic Dispatch (engine/decorators.py)

> Guide §8 ("Phase 6 — Decorator & Dynamic Dispatch").

## What it does
Decorators are applied at definition time — they are calls that run once when the module loads. This
phase: (1) emits `DECORATES` edges between each decorator and its target, (2) recognizes known
framework patterns and tags nodes with a semantic `role`, and (3) best-effort detects dynamic dispatch
(`getattr`) patterns.

## Input
`ParseResult` + `ResolverResult` + the `ProjectGraph` (nodes already carry raw `decorators` text from
Phase 5).

## Output
`DECORATES` edges appended to `ProjectGraph.edges`; `role` tags on nodes; `dynamic_dispatch` warnings.

## Key algorithm — DECORATES edges (guide §8.2)
```python
def extract_decorator_edges(module, graph, resolver):
    for node_fqn, gnode in graph.nodes.items():
        if gnode.file != str(module.file):
            continue
        for dec_text in gnode.decorators:
            binding = resolver.bindings.get(
                (module.module_name, dec_text.split('(')[0])  # strip call args
            )
            if isinstance(binding, ResolvedBinding):
                graph.edges.append(GraphEdge(
                    src=binding.real_fqn, dst=node_fqn,
                    kind=EdgeKind.DECORATES, confidence=Confidence.STATIC,
                    file=str(module.file),
                ))
```
Edge direction is **decorator → decorated target**.

## Framework pattern recognition (guide §8.3)
Tag nodes with a `role` the UI can display:
| Decorator pattern | Framework | Role |
|-------------------|-----------|------|
| `@app.get()`, `@router.post()` | FastAPI | `http_endpoint` |
| `@app.route()`, `@bp.route()` | Flask | `http_endpoint` |
| `@login_required` | Django/Flask | `auth_guarded` |
| `@pytest.fixture` | pytest | `test_fixture` |
| `@app.task`, `@celery.task` | Celery | `background_task` |
| `@property` | stdlib | `property` |
| `@abstractmethod` | abc | `abstract` |
| `@dataclass` | dataclasses | `dataclass` |
| `@click.command()`, `@typer.command()` | Click/Typer | `cli_command` |

## Dynamic dispatch — getattr (guide §8.4)
`getattr(obj, name)()` cannot be statically resolved, but the pattern is detectable. In the AST it is
`Call(func=Call(func=Name('getattr'), ...))`. Walk calls; when the inner func is `getattr`, append a
`dynamic_dispatch` `AnalysisWarning` (target unknown) rather than a (wrong) edge.

## Edge cases
1. **Decorators with arguments** — strip `(` to get the base name before resolving the binding.
2. **Stacked decorators** — emit one DECORATES edge per decorator in the list.
3. **Unresolved decorators** — if the binding is unresolved (e.g. external), skip the edge but still
   apply role tagging from the raw text pattern.
4. **`getattr` dispatch** — surface as a warning so the UI can flag an analysis blind spot.
5. **Property/abstractmethod** — already affect node kind in Phase 5; here they additionally set `role`.

## Library APIs
| API | Purpose |
|-----|---------|
| `ast.NodeVisitor` / `visit_Call` | Detect `getattr(...)()` dispatch. |
| `ast.unparse` / string matching | Match decorator text against framework patterns. |
| Phase 4 `resolver.bindings` | Resolve a decorator name to its definition FQN. |

## Common mistakes
1. Reversing edge direction (must be decorator → target).
2. Failing to strip call args, so `@app.get('/x')` never matches a binding.
3. Treating `getattr` dispatch as a resolvable call (produces a wrong edge instead of a warning).

## Test fixtures
- `fixtures/decorator_chain/` — stacked decorators; verify every DECORATES edge is emitted.
- (framework roles) — a fixture with `@pytest.fixture` / FastAPI-style decorators to verify `role` tags.

## Implementation notes
Run after Phase 5 (nodes must already carry `decorators`) and before Phase 8 (graph must be fully
annotated). Role tagging is pattern-based on the raw decorator text and does not require resolution.
