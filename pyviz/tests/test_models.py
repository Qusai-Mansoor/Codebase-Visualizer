"""Tests for pyviz/models.py — Phase 1 verification."""
import ast
import json
from pathlib import Path

import pytest

from pyviz.models import (
    AnalysisWarning,
    Binding,
    Confidence,
    DiscoveryResult,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
    ParsedModule,
    ParseResult,
    ProjectGraph,
    ResolvedBinding,
    ResolverResult,
    UnresolvedBinding,
)


# ---------------------------------------------------------------------------
# Enum serialisation
# ---------------------------------------------------------------------------

def test_node_kind_values_are_strings():
    for member in NodeKind:
        assert isinstance(member.value, str)

def test_edge_kind_values_are_strings():
    for member in EdgeKind:
        assert isinstance(member.value, str)

def test_confidence_values_are_strings():
    for member in Confidence:
        assert isinstance(member.value, str)

def test_enums_json_serialisable():
    # str-Enum members serialise directly without a custom encoder
    payload = {
        'kind': NodeKind.CLASS,
        'edge': EdgeKind.CALLS,
        'conf': Confidence.STATIC,
    }
    result = json.dumps(payload)
    data = json.loads(result)
    assert data['kind'] == 'class'
    assert data['edge'] == 'calls'
    assert data['conf'] == 'static'

def test_node_kind_coverage():
    expected = {
        'package', 'module', 'class', 'function', 'method',
        'classmethod', 'staticmethod', 'property', 'decorator', 'lambda', 'unknown',
    }
    assert {m.value for m in NodeKind} == expected

def test_edge_kind_coverage():
    assert {m.value for m in EdgeKind} == {'imports', 'calls', 'inherits', 'decorates', 'contains'}

def test_confidence_coverage():
    assert {m.value for m in Confidence} == {'static', 'runtime', 'both', 'dynamic', 'unresolved'}


# ---------------------------------------------------------------------------
# GraphNode
# ---------------------------------------------------------------------------

def _make_node(**kwargs):
    defaults = dict(
        id='pkg.mod.MyClass',
        kind=NodeKind.CLASS,
        name='MyClass',
        file='pkg/mod.py',
        line=10,
        end_line=50,
        docstring='A class.',
    )
    defaults.update(kwargs)
    return GraphNode(**defaults)

def test_graph_node_required_fields():
    node = _make_node()
    assert node.id == 'pkg.mod.MyClass'
    assert node.kind == NodeKind.CLASS
    assert node.name == 'MyClass'

def test_graph_node_optional_fields_default_false():
    node = _make_node()
    assert node.is_async is False
    assert node.is_abstract is False
    assert node.is_protocol is False
    assert node.is_dataclass is False
    assert node.is_mixin is False

def test_graph_node_list_fields_default_empty():
    node = _make_node()
    assert node.bases == []
    assert node.decorators == []
    assert node.all_exports == []
    assert node.warnings == []

def test_graph_node_list_fields_independent():
    # Two instances must not share list objects
    a = _make_node(id='a', name='A')
    b = _make_node(id='b', name='B')
    a.bases.append('Base')
    assert b.bases == []

def test_graph_node_optional_none_fields():
    node = _make_node(file=None, line=None, end_line=None, docstring=None)
    assert node.file is None
    assert node.line is None
    assert node.end_line is None
    assert node.docstring is None


# ---------------------------------------------------------------------------
# GraphEdge
# ---------------------------------------------------------------------------

def test_graph_edge_required_fields():
    edge = GraphEdge(src='a.foo', dst='b.bar', kind=EdgeKind.CALLS)
    assert edge.src == 'a.foo'
    assert edge.dst == 'b.bar'
    assert edge.kind == EdgeKind.CALLS

def test_graph_edge_defaults():
    edge = GraphEdge(src='a', dst='b', kind=EdgeKind.IMPORTS)
    assert edge.confidence == Confidence.STATIC
    assert edge.file is None
    assert edge.line is None
    assert edge.is_type_only is False

def test_graph_edge_type_only_flag():
    edge = GraphEdge(src='a', dst='b', kind=EdgeKind.IMPORTS, is_type_only=True)
    assert edge.is_type_only is True


# ---------------------------------------------------------------------------
# AnalysisWarning
# ---------------------------------------------------------------------------

def test_analysis_warning_with_location():
    w = AnalysisWarning(kind='syntax_error', message='bad syntax', file='foo.py', line=42)
    assert w.kind == 'syntax_error'
    assert w.line == 42

def test_analysis_warning_null_location():
    w = AnalysisWarning(kind='dynamic_call', message='unknown', file=None, line=None)
    assert w.file is None
    assert w.line is None


# ---------------------------------------------------------------------------
# ProjectGraph
# ---------------------------------------------------------------------------

def test_project_graph_defaults():
    pg = ProjectGraph()
    assert pg.nodes == {}
    assert pg.edges == []
    assert pg.warnings == []
    assert pg.root == ''
    assert pg.python_version == ''
    assert pg.generated_at == ''

def test_project_graph_containers_independent():
    a = ProjectGraph()
    b = ProjectGraph()
    a.edges.append(GraphEdge(src='x', dst='y', kind=EdgeKind.CALLS))
    assert b.edges == []


# ---------------------------------------------------------------------------
# DiscoveryResult
# ---------------------------------------------------------------------------

def test_discovery_result_instantiation(tmp_path):
    dr = DiscoveryResult(
        root=tmp_path,
        module_map={'pkg.mod': tmp_path / 'mod.py'},
        package_map={'pkg': tmp_path},
        skipped={},
    )
    assert dr.root == tmp_path
    assert 'pkg.mod' in dr.module_map


# ---------------------------------------------------------------------------
# ParsedModule / ParseResult
# ---------------------------------------------------------------------------

def test_parsed_module_instantiation(tmp_path):
    source = 'x = 1\n'
    tree = ast.parse(source)
    pm = ParsedModule(
        module_name='pkg.mod',
        file=tmp_path / 'mod.py',
        source=source,
        tree=tree,
        encoding='utf-8',
    )
    assert pm.module_name == 'pkg.mod'
    assert isinstance(pm.tree, ast.Module)

def test_parse_result_instantiation(tmp_path):
    source = 'x = 1\n'
    tree = ast.parse(source)
    pm = ParsedModule('pkg.mod', tmp_path / 'mod.py', source, tree, 'utf-8')
    pr = ParseResult(parsed={'pkg.mod': pm}, failed={})
    assert 'pkg.mod' in pr.parsed
    assert pr.failed == {}


# ---------------------------------------------------------------------------
# ResolvedBinding / UnresolvedBinding / Binding / ResolverResult
# ---------------------------------------------------------------------------

def test_resolved_binding(tmp_path):
    rb = ResolvedBinding(
        name='MyClass',
        real_module='pkg.core',
        real_file=tmp_path / 'core.py',
        real_line=10,
        real_fqn='pkg.core.MyClass',
    )
    assert rb.is_type_only is False
    assert rb.is_wildcard is False
    assert rb.real_fqn == 'pkg.core.MyClass'

def test_unresolved_binding():
    ub = UnresolvedBinding(name='Foo', reason='external', import_source='pkg.mod')
    assert ub.reason == 'external'

def test_binding_isinstance(tmp_path):
    rb = ResolvedBinding('X', 'a', tmp_path / 'a.py', 1, 'a.X')
    ub = UnresolvedBinding('Y', 'not_found', 'b')
    assert isinstance(rb, ResolvedBinding)
    assert isinstance(ub, UnresolvedBinding)

def test_resolver_result_defaults():
    rr = ResolverResult()
    assert rr.bindings == {}
    assert rr.warnings == []

def test_resolver_result_with_bindings(tmp_path):
    rb = ResolvedBinding('Thing', 'pkg.core', tmp_path / 'core.py', 5, 'pkg.core.Thing')
    rr = ResolverResult(bindings={('pkg.api', 'Thing'): rb})
    binding = rr.bindings[('pkg.api', 'Thing')]
    assert isinstance(binding, ResolvedBinding)
    assert binding.real_fqn == 'pkg.core.Thing'
