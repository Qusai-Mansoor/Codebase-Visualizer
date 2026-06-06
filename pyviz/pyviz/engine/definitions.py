"""Phase 5 — Definition extraction.

Walks every parsed AST and emits GraphNode objects into a ProjectGraph:
  one MODULE node per module/package, plus CLASS / FUNCTION / METHOD /
  CLASSMETHOD / STATICMETHOD / PROPERTY / LAMBDA nodes.

Also emits INHERITS edges for base-class relationships.
"""
from __future__ import annotations

import ast
from typing import Optional

from pyviz.models import (
    DiscoveryResult,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
    ParseResult,
    ParsedModule,
    ProjectGraph,
    ResolvedBinding,
    ResolverResult,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_all(
    parse_result: ParseResult,
    resolver_result: ResolverResult,
    graph: ProjectGraph,
    discovery: DiscoveryResult,
) -> ProjectGraph:
    """Populate *graph* with nodes and INHERITS edges from all parsed modules."""
    for module_name, parsed_mod in parse_result.parsed.items():
        extractor = DefinitionExtractor(
            module=parsed_mod,
            graph=graph,
            resolver_result=resolver_result,
            discovery=discovery,
        )
        extractor.run()
    return graph


# ---------------------------------------------------------------------------
# AST visitor
# ---------------------------------------------------------------------------

class DefinitionExtractor(ast.NodeVisitor):
    def __init__(
        self,
        module: ParsedModule,
        graph: ProjectGraph,
        resolver_result: ResolverResult,
        discovery: DiscoveryResult,
    ) -> None:
        self.module = module
        self.graph = graph
        self.resolver_result = resolver_result
        self.discovery = discovery
        self._class_stack: list[str] = []

    def run(self) -> None:
        mod_id = self.module.module_name
        self.graph.nodes[mod_id] = GraphNode(
            id=mod_id,
            kind=NodeKind.MODULE,
            name=mod_id.split('.')[-1],
            file=self._rel_file(),
            line=1,
            end_line=None,
            docstring=ast.get_docstring(self.module.tree),
            all_exports=_get_module_exports(self.module),
        )
        self.visit(self.module.tree)

    # ------------------------------------------------------------------
    # Visitor methods
    # ------------------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        fqn = self._fqn(node.name)
        decorators = _extract_decorators(node.decorator_list)
        bases = self._extract_bases(node.bases)

        is_abstract = _is_abstract_class(node, bases)
        is_protocol = _is_protocol_class(bases)
        is_dc = _is_dataclass(decorators)
        is_mixin = _is_mixin(node.name, node, bases)

        self.graph.nodes[fqn] = GraphNode(
            id=fqn,
            kind=NodeKind.CLASS,
            name=node.name,
            file=self._rel_file(),
            line=node.lineno,
            end_line=getattr(node, 'end_lineno', None),
            docstring=ast.get_docstring(node),
            is_abstract=is_abstract,
            is_protocol=is_protocol,
            is_dataclass=is_dc,
            is_mixin=is_mixin,
            bases=bases,
            decorators=decorators,
        )

        for base in bases:
            self.graph.edges.append(GraphEdge(
                src=fqn,
                dst=base,
                kind=EdgeKind.INHERITS,
                file=self._rel_file(),
                line=node.lineno,
            ))

        if is_dc:
            self._emit_dataclass_synthetics(fqn, node)

        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        decorators = _extract_decorators(node.decorator_list)
        in_class = bool(self._class_stack)
        kind = _function_kind(decorators, in_class)
        is_async = isinstance(node, ast.AsyncFunctionDef)
        fqn = self._fqn(node.name)

        self.graph.nodes[fqn] = GraphNode(
            id=fqn,
            kind=kind,
            name=node.name,
            file=self._rel_file(),
            line=node.lineno,
            end_line=getattr(node, 'end_lineno', None),
            docstring=ast.get_docstring(node),
            is_async=is_async,
            decorators=decorators,
        )
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        if not self._class_stack and isinstance(node.value, ast.Lambda):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    fqn = self._fqn(target.id)
                    self.graph.nodes[fqn] = GraphNode(
                        id=fqn,
                        kind=NodeKind.LAMBDA,
                        name=target.id,
                        file=self._rel_file(),
                        line=node.lineno,
                        end_line=getattr(node, 'end_lineno', None),
                        docstring=None,
                    )
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fqn(self, name: str) -> str:
        return '.'.join([self.module.module_name] + self._class_stack + [name])

    def _rel_file(self) -> str:
        try:
            return str(self.module.file.relative_to(self.discovery.root))
        except ValueError:
            return str(self.module.file)

    def _extract_bases(self, bases: list[ast.expr]) -> list[str]:
        result: list[str] = []
        for base in bases:
            raw = ast.unparse(base)
            first = raw.split('.')[0]
            key = (self.module.module_name, first)
            binding = self.resolver_result.bindings.get(key)
            if isinstance(binding, ResolvedBinding):
                result.append(binding.real_fqn)
            else:
                result.append(raw)
        return result

    def _emit_dataclass_synthetics(self, class_fqn: str, ast_node: ast.ClassDef) -> None:
        for mname in ('__init__', '__repr__', '__eq__'):
            fqn = f'{class_fqn}.{mname}'
            if fqn not in self.graph.nodes:
                self.graph.nodes[fqn] = GraphNode(
                    id=fqn,
                    kind=NodeKind.METHOD,
                    name=mname,
                    file=self._rel_file(),
                    line=ast_node.lineno,
                    end_line=None,
                    docstring=None,
                    is_synthetic=True,
                )


# ---------------------------------------------------------------------------
# Module-level pure helpers
# ---------------------------------------------------------------------------

def _extract_decorators(decorator_list: list[ast.expr]) -> list[str]:
    return [ast.unparse(d) for d in decorator_list]


def _function_kind(decorators: list[str], in_class: bool) -> NodeKind:
    if not in_class:
        return NodeKind.FUNCTION
    for d in decorators:
        if d == 'classmethod':
            return NodeKind.CLASSMETHOD
        if d == 'staticmethod':
            return NodeKind.STATICMETHOD
        if (
            d == 'property'
            or 'abstractproperty' in d
            or d.endswith('.getter')
            or d.endswith('.setter')
            or d.endswith('.deleter')
        ):
            return NodeKind.PROPERTY
    return NodeKind.METHOD


def _is_abstract_class(node: ast.ClassDef, bases: list[str]) -> bool:
    abstract_bases = {'ABC', 'ABCMeta', 'abc.ABC', 'abc.ABCMeta'}
    if any(b in abstract_bases for b in bases):
        return True
    for child in ast.walk(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in child.decorator_list:
                unparsed = ast.unparse(d)
                if unparsed in ('abstractmethod', 'abc.abstractmethod'):
                    return True
    return False


def _is_protocol_class(bases: list[str]) -> bool:
    protocol_names = {'Protocol', 'typing.Protocol', 'typing_extensions.Protocol'}
    return any(b in protocol_names for b in bases)


def _is_dataclass(decorators: list[str]) -> bool:
    return any('dataclass' in d for d in decorators)


def _is_mixin(name: str, node: ast.ClassDef, bases: list[str]) -> bool:
    if name.endswith('Mixin') or name.endswith('mixin'):
        return True
    if not bases:
        has_init = any(
            isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef)) and c.name == '__init__'
            for c in ast.iter_child_nodes(node)
        )
        if not has_init:
            has_non_method = any(
                isinstance(c, (ast.Assign, ast.AnnAssign, ast.ClassDef))
                for c in ast.iter_child_nodes(node)
            )
            if not has_non_method:
                return True
    return False


def _get_module_exports(module: ParsedModule) -> list[str]:
    for node in ast.iter_child_nodes(module.tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == '__all__':
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        return [
                            elt.value
                            for elt in node.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        ]
    return []
