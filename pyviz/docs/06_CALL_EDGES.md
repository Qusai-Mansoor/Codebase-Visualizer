# Phase 6: Call-Edge Extraction (engine/calls.py)

> Guide §7 ("Phase 5 — Call-Edge Extraction").

## What it does
Walks the body of every function/method and emits a `GraphEdge(kind=CALLS)` for every function call.
This produces the call graph, and is where "imports" and "calls" diverge — a name can be imported
without being called. This phase fires only on actual `ast.Call` nodes.

## Input
`ParseResult` + `ResolverResult` + the `ProjectGraph` (already populated with definition nodes from
Phase 5, so locally-defined names can be matched).

## Output
`CALLS` edges appended to `ProjectGraph.edges`; `dynamic_call` entries in `ProjectGraph.warnings`.

## The `ast.Call` node (guide §7.2)
| AST shape | Source | Meaning |
|-----------|--------|---------|
| `Call(func=Name('foo'))` | `foo()` | call local/imported name |
| `Call(func=Attribute(Name('mod'),'bar'))` | `mod.bar()` | method/attr call |
| `Call(func=Attribute(Attribute(Name('a'),'b'),'c'))` | `a.b.c()` | chained attribute call |

## Key algorithm (guide §7.3)
```python
class CallEdgeExtractor(ast.NodeVisitor):
    def __init__(self, module, caller_fqn, resolver, graph):
        ...
        self._in_type_checking = False

    def visit_If(self, node):
        test = node.test
        if (isinstance(test, ast.Name) and test.id == 'TYPE_CHECKING') or \
           (isinstance(test, ast.Attribute) and test.attr == 'TYPE_CHECKING'):
            self._in_type_checking = True; self.generic_visit(node); self._in_type_checking = False
        else:
            self.generic_visit(node)

    def visit_Call(self, node):
        if not self._in_type_checking:
            self._emit_call(node)
        self.generic_visit(node)               # also process nested calls

    def _resolve_call_target(self, func_expr):
        if isinstance(func_expr, ast.Name):      return self._resolve_name(func_expr.id, func_expr)
        if isinstance(func_expr, ast.Attribute): return self._resolve_attr(func_expr)
        return None, Confidence.DYNAMIC          # lambda/subscript calls, etc.

    def _resolve_name(self, name, node):
        b = self.resolver.bindings.get((self.module.module_name, name))
        if isinstance(b, ResolvedBinding):       return b.real_fqn, Confidence.STATIC
        local = f'{self.module.module_name}.{name}'
        if local in self.graph.nodes:            return local, Confidence.STATIC
        if name in dir(builtins):                return None, Confidence.STATIC   # skip builtins
        return None, Confidence.DYNAMIC
```
`_emit_call` appends a `GraphEdge(src=caller_fqn, dst=target_fqn, kind=CALLS, confidence, line)`;
when the target is `None`, it records a `dynamic_call` `AnalysisWarning` instead.

## Edge cases
1. **TYPE_CHECKING blocks** — calls inside them must NOT produce edges (`_in_type_checking` flag).
2. **Builtins** — `print`, `len`, etc.: resolve to `None` with `Confidence.STATIC`; do not add edges.
3. **`with` statements / context managers** (§7.4) — implicitly call `__enter__`/`__exit__`; visit
   `ast.With` and emit an edge if the manager's type resolves.
4. **Comprehensions** (§7.5) — each has its own scope but `generic_visit` still descends; calls inside
   them count.
5. **Property access** (§12.7) — `obj.name` (an `ast.Attribute`, not a `Call`) invokes a `@property`
   getter; optionally walk attributes and emit a `CALLS` edge with `Confidence.DYNAMIC` when the name
   resolves to a property.

## Distinguishing imports from calls (guide §7.6)
At the end of this phase the graph has IMPORTS edges (from Phase 4) and CALLS edges. A symbol that is
imported but never called has an IMPORTS edge but no CALLS edge — the basis for dead-code detection
in Phase 8. **Ensure IMPORTS edges are emitted in Phase 4 even when resolution succeeds.**

## Library APIs
| API | Purpose |
|-----|---------|
| `ast.NodeVisitor` / `visit_Call` / `visit_If` / `visit_With` | Targeted call-graph walk. |
| `ast.unparse(call.func)` | Human-readable text for unresolved-call warnings. |
| `builtins` (`dir(builtins)`) | Identify and skip built-in calls. |

## Common mistakes
1. Emitting edges for TYPE_CHECKING-only calls (phantom dependencies).
2. Adding edges to builtins, polluting the graph.
3. Forgetting `generic_visit` after handling a call, so nested calls are missed.

## Test fixtures
- `fixtures/type_checking_only/` — no call edge from inside `if TYPE_CHECKING`.
- `fixtures/async_surface/` — async↔sync calls produce correct CALLS edges and `is_async` tags.
- `fixtures/property_getter/` — attribute access to a property surfaces as a (dynamic) call.

## Implementation notes
One `CallEdgeExtractor` per function/method, seeded with that function's `caller_fqn`. Resolve through
Phase 4 bindings first, then locally-defined nodes, then skip builtins, else mark dynamic.
