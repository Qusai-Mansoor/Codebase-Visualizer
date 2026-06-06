# Phase 5: Definition Extraction (engine/definitions.py)

> Guide §6 ("Phase 4 — Definition Extraction").

## What it does
Walks every parsed AST and emits `GraphNode` objects — one per module, package, class, function,
method, property, and lambda. Phase 4 provides the real definition location; this phase extracts the
structural information (kind, async-ness, abstract/protocol/dataclass/mixin flags, bases, decorators).

## Input
`ParseResult` + `ResolverResult` (for resolving base classes) + a `ProjectGraph` to populate.

## Output
Populated `ProjectGraph.nodes` plus INHERITS edges into `ProjectGraph.edges`.

## Key algorithm — the AST visitor (guide §6.2)
Subclass `ast.NodeVisitor`; `generic_visit(node)` recurses into children.
```python
class DefinitionExtractor(ast.NodeVisitor):
    def __init__(self, module, graph):
        self.module, self.graph = module, graph
        self._class_stack: list[str] = []     # track nesting for FQNs

    def run(self):
        # emit MODULE node (id = module_name, all_exports = get_exported_names(...))
        self.visit(self.module.tree)

    def visit_ClassDef(self, node):
        fqn = self._fqn(node.name)
        decorators = self._extract_decorators(node.decorator_list)
        bases = self._extract_bases(node.bases)
        # GraphNode(kind=CLASS, is_abstract/_protocol/_dataclass/_mixin, bases, decorators, ...)
        self._class_stack.append(node.name)
        self.generic_visit(node)              # recurse into methods
        self._class_stack.pop()

    def visit_FunctionDef(self, node):
        kind = self._function_kind(node, decorators)  # FUNCTION/METHOD/CLASSMETHOD/STATICMETHOD/PROPERTY
        # GraphNode(kind=kind, is_async=isinstance(node, ast.AsyncFunctionDef), ...)
        self.generic_visit(node)
    visit_AsyncFunctionDef = visit_FunctionDef

    def _fqn(self, name):
        return '.'.join([self.module.module_name] + self._class_stack + [name])
```
`_function_kind`: outside a class → FUNCTION; inside → METHOD, unless decorators contain
`classmethod` / `staticmethod` / `property` (or `abstractproperty`).

## Flag detection (guide §6.3–6.4)
- **Abstract** — base is `ABC`/`ABCMeta`/`abc.ABC`/`abc.ABCMeta`, OR any method has `@abstractmethod`.
- **Protocol** — base is `Protocol`/`typing.Protocol`/`typing_extensions.Protocol`.
- **Dataclass** — any decorator contains `'dataclass'`.
- **Mixin** (heuristic) — name ends with `Mixin`/`mixin` (strongest signal), OR: no `__init__`,
  only method/`pass`/docstring children, and zero bases.

## Lambdas, callables, inheritance (guide §6.5–6.7)
- **Lambdas** assigned to module-level names → `NodeKind.LAMBDA` with synthetic FQN by location
  (`visit_Assign` checking `isinstance(node.value, ast.Lambda)`).
- **`__call__` classes** — a class defining `__call__` is callable like a function; tag it so Phase 6
  can route `obj()` to `ClassName.__call__`.
- **Inheritance edges** — after a class node, emit an `INHERITS` edge per base; resolve each base
  through Phase 4 bindings (`_extract_bases` → `binding.real_fqn`, else store raw text to match later).

## Edge cases
1. **Nested classes/functions** — `_class_stack` must produce correct FQNs for nested definitions.
2. **`@property` getters** — kind `PROPERTY`; later (Phase 6/§12.7) attribute access counts as a call.
3. **Mixin false positives** — the heuristic is deliberately conservative; name suffix dominates.
4. **dataclass-generated methods** (§12.6) — emit synthetic `__init__`/`__repr__`/`__eq__` nodes with
   `is_synthetic=True` (also for attrs/pydantic).
5. **Unresolvable bases** — keep raw text so a later pass can reconcile against resolved class FQNs.

## Library APIs
| API | Purpose |
|-----|---------|
| `ast.NodeVisitor` / `generic_visit` | Structured AST walk with `visit_*` methods. |
| `ast.get_docstring(node)` | Node docstrings. |
| `ast.unparse(expr)` | Render a base/decorator expression back to source text. |
| `node.lineno` / `node.end_lineno` | Span info for the node. |

## Common mistakes
1. Wrong FQNs from a mismanaged class/nesting stack (push before, pop after `generic_visit`).
2. Misclassifying method kind by ignoring decorators (classmethod/staticmethod/property).
3. Not resolving bases through Phase 4 bindings → inheritance edges point at raw names that never
   match real class nodes.

## Test fixtures
- `fixtures/abstract_mixin/` — verify `is_abstract` and `is_mixin`.
- `fixtures/async_surface/` — verify `is_async` on async defs.
- `fixtures/property_getter/` — verify `PROPERTY` kind and no false "unused" flag.
- `fixtures/decorator_chain/` — decorators captured on nodes for Phase 7.

## Implementation notes
Provide the visitor with access to the resolver so `_extract_bases` can map bases to real FQNs. Emit
the MODULE node first (with `all_exports`), then visit the tree.
