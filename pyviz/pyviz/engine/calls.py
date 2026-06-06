"""Phase 6 — Call-edge extraction.

Walks every function/method body and emits GraphEdge(kind=CALLS) for every
ast.Call node. TYPE_CHECKING calls are skipped. Unresolved dynamic calls
are recorded as AnalysisWarning(kind='dynamic_call').
"""
from __future__ import annotations

import ast
import builtins
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

_BUILTIN_NAMES: frozenset[str] = frozenset(dir(builtins))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_all(
    parse_result: ParseResult,
    resolver_result: ResolverResult,
    graph: ProjectGraph,
    discovery: DiscoveryResult,
) -> ProjectGraph:
    """Append CALLS edges to *graph* for every function/method call found."""
    for parsed_mod in parse_result.parsed.values():
        rel_file = _rel_file(parsed_mod, discovery)
        walker = _ModuleCallWalker(
            module=parsed_mod,
            resolver=resolver_result,
            graph=graph,
            rel_file=rel_file,
        )
        walker.visit(parsed_mod.tree)
    return graph


# ---------------------------------------------------------------------------
# Module-level scope walker — finds callables, spawns per-function extractor
# ---------------------------------------------------------------------------

class _ModuleCallWalker(ast.NodeVisitor):
    def __init__(
        self,
        module: ParsedModule,
        resolver: ResolverResult,
        graph: ProjectGraph,
        rel_file: str,
    ) -> None:
        self.module = module
        self.resolver = resolver
        self.graph = graph
        self.rel_file = rel_file
        self._class_stack: list[str] = []

    def _fqn(self, name: str) -> str:
        return '.'.join([self.module.module_name] + self._class_stack + [name])

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        fqn = self._fqn(node.name)
        if fqn in self.graph.nodes:
            extractor = CallEdgeExtractor(
                module=self.module,
                caller_fqn=fqn,
                resolver=self.resolver,
                graph=self.graph,
                rel_file=self.rel_file,
            )
            for stmt in node.body:
                extractor.visit(stmt)
        # Continue walking to find nested function/class defs
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


# ---------------------------------------------------------------------------
# Per-function call-edge extractor
# ---------------------------------------------------------------------------

class CallEdgeExtractor(ast.NodeVisitor):
    def __init__(
        self,
        module: ParsedModule,
        caller_fqn: str,
        resolver: ResolverResult,
        graph: ProjectGraph,
        rel_file: str,
    ) -> None:
        self.module = module
        self.caller_fqn = caller_fqn
        self.resolver = resolver
        self.graph = graph
        self.rel_file = rel_file
        self._in_type_checking = False

    # Stop at nested scope boundaries — the module walker handles them
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        pass

    def visit_If(self, node: ast.If) -> None:
        test = node.test
        is_tc = (
            (isinstance(test, ast.Name) and test.id == 'TYPE_CHECKING') or
            (isinstance(test, ast.Attribute) and test.attr == 'TYPE_CHECKING')
        )
        if is_tc:
            prev = self._in_type_checking
            self._in_type_checking = True
            self.generic_visit(node)
            self._in_type_checking = prev
        else:
            self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if not self._in_type_checking:
            self._emit_call(node)
        self.generic_visit(node)  # descend to catch nested calls in args

    def visit_With(self, node: ast.With) -> None:
        if not self._in_type_checking:
            for item in node.items:
                self._emit_enter_edge(item.context_expr)
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Emission helpers
    # ------------------------------------------------------------------

    def _emit_call(self, node: ast.Call) -> None:
        line = getattr(node, 'lineno', None)
        # §12.8 — importlib.import_module is a special dynamic-import pattern
        if self._is_importlib_call(node):
            self._emit_dynamic_import_warning(node, line)
            return  # do not also emit a dynamic_call warning
        target, confidence = self._resolve_call_target(node.func)
        if target is not None:
            self.graph.edges.append(GraphEdge(
                src=self.caller_fqn,
                dst=target,
                kind=EdgeKind.CALLS,
                confidence=confidence,
                file=self.rel_file,
                line=line,
            ))
        elif confidence == Confidence.DYNAMIC:
            self.graph.warnings.append(AnalysisWarning(
                kind='dynamic_call',
                message=f'{self.caller_fqn}: unresolved call to {ast.unparse(node.func)!r}',
                file=self.rel_file,
                line=line,
            ))

    def _is_importlib_call(self, node: ast.Call) -> bool:
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == 'import_module'
            and isinstance(func.value, ast.Name)
            and func.value.id == 'importlib'
        ):
            return True
        if isinstance(func, ast.Name) and func.id == 'import_module':
            b = self.resolver.bindings.get((self.module.module_name, 'import_module'))
            if isinstance(b, ResolvedBinding) and 'importlib' in b.real_fqn:
                return True
        return False

    def _emit_dynamic_import_warning(self, node: ast.Call, line) -> None:
        if (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            mod_ref = node.args[0].value
        else:
            mod_ref = 'dynamic string, cannot resolve'
        self.graph.warnings.append(AnalysisWarning(
            kind='dynamic_import',
            message=f'{self.caller_fqn}: importlib.import_module({mod_ref!r})',
            file=self.rel_file,
            line=line,
        ))

    def _emit_enter_edge(self, ctx_expr: ast.expr) -> None:
        """Emit a CALLS edge to __enter__ when the context manager type resolves."""
        target, confidence = self._resolve_call_target(ctx_expr)
        if target is None:
            return
        enter_fqn = f'{target}.__enter__'
        if enter_fqn in self.graph.nodes:
            self.graph.edges.append(GraphEdge(
                src=self.caller_fqn,
                dst=enter_fqn,
                kind=EdgeKind.CALLS,
                confidence=confidence,
                file=self.rel_file,
                line=getattr(ctx_expr, 'lineno', None),
            ))

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    def _resolve_call_target(
        self, func_expr: ast.expr
    ) -> tuple[Optional[str], Confidence]:
        if isinstance(func_expr, ast.Name):
            return self._resolve_name(func_expr.id)
        if isinstance(func_expr, ast.Attribute):
            return self._resolve_attr(func_expr)
        return None, Confidence.DYNAMIC  # lambda calls, subscript calls, etc.

    def _resolve_name(self, name: str) -> tuple[Optional[str], Confidence]:
        # 1. Phase 4 import bindings
        b = self.resolver.bindings.get((self.module.module_name, name))
        if isinstance(b, ResolvedBinding):
            return b.real_fqn, Confidence.STATIC
        # 2. Locally-defined node
        local = f'{self.module.module_name}.{name}'
        if local in self.graph.nodes:
            return local, Confidence.STATIC
        # 3. Built-in — skip silently
        if name in _BUILTIN_NAMES:
            return None, Confidence.STATIC
        # 4. Unresolvable
        return None, Confidence.DYNAMIC

    def _resolve_attr(
        self, node: ast.Attribute
    ) -> tuple[Optional[str], Confidence]:
        val = node.value
        # self.x() / cls.x() — skip, needs type inference
        if isinstance(val, ast.Name) and val.id in ('self', 'cls'):
            return None, Confidence.STATIC
        # super().x() — skip
        if (
            isinstance(val, ast.Call)
            and isinstance(val.func, ast.Name)
            and val.func.id == 'super'
        ):
            return None, Confidence.STATIC
        # Other chained calls: obj.method().attr() — dynamic
        if isinstance(val, ast.Call):
            return None, Confidence.DYNAMIC
        if isinstance(val, ast.Name):
            base = val.id
            # Check import bindings for the base name
            b = self.resolver.bindings.get((self.module.module_name, base))
            if isinstance(b, ResolvedBinding):
                candidate = f'{b.real_fqn}.{node.attr}'
                if candidate in self.graph.nodes:
                    return candidate, Confidence.STATIC
                # Known external method — skip silently
                return None, Confidence.STATIC
            # Check locally-defined base (class or module node)
            local_base = f'{self.module.module_name}.{base}'
            if local_base in self.graph.nodes:
                candidate = f'{local_base}.{node.attr}'
                if candidate in self.graph.nodes:
                    return candidate, Confidence.STATIC
                return None, Confidence.STATIC
        # Chained attribute like a.b.c() — dynamic
        return None, Confidence.DYNAMIC


# ---------------------------------------------------------------------------
# Internal utility
# ---------------------------------------------------------------------------

def _rel_file(parsed_mod: ParsedModule, discovery: DiscoveryResult) -> str:
    try:
        return str(parsed_mod.file.relative_to(discovery.root))
    except ValueError:
        return str(parsed_mod.file)
