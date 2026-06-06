"""Tests for pyviz/engine/definitions.py — Phase 5 verification."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from pyviz.engine.definitions import extract_all
from pyviz.engine.discovery import discover
from pyviz.engine.parser import parse_all
from pyviz.engine.resolver import resolve_all
from pyviz.models import (
    EdgeKind,
    GraphNode,
    NodeKind,
    ProjectGraph,
)

FIXTURES = Path(__file__).parent / 'fixtures'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(root: Path) -> ProjectGraph:
    d = discover(root)
    p = parse_all(d)
    r = resolve_all(d, p)
    g = ProjectGraph()
    return extract_all(p, r, g, d)


@pytest.fixture(scope='session')
def fixtures_graph():
    return _run(FIXTURES)


# ---------------------------------------------------------------------------
# Return type / structure
# ---------------------------------------------------------------------------

def test_extract_all_returns_project_graph(tmp_path):
    (tmp_path / 'mod.py').write_text('x = 1\n', encoding='utf-8')
    g = _run(tmp_path)
    assert isinstance(g, ProjectGraph)


def test_nodes_dict_populated(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    g = _run(tmp_path)
    assert len(g.nodes) > 0


def test_module_node_exists_for_each_module(tmp_path):
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    (pkg / 'sub.py').write_text('x = 1\n', encoding='utf-8')
    g = _run(tmp_path)
    assert 'pkg' in g.nodes
    assert 'pkg.sub' in g.nodes


def test_module_node_kind_is_module(tmp_path):
    (tmp_path / 'mod.py').write_text('', encoding='utf-8')
    g = _run(tmp_path)
    assert g.nodes['mod'].kind == NodeKind.MODULE


# ---------------------------------------------------------------------------
# MODULE node fields
# ---------------------------------------------------------------------------

def test_module_node_id_equals_dotted_name(tmp_path):
    (tmp_path / 'mymod.py').write_text('', encoding='utf-8')
    g = _run(tmp_path)
    assert 'mymod' in g.nodes
    assert g.nodes['mymod'].id == 'mymod'


def test_module_node_name_is_last_component(tmp_path):
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    (pkg / 'sub.py').write_text('', encoding='utf-8')
    g = _run(tmp_path)
    assert g.nodes['pkg.sub'].name == 'sub'


def test_module_node_all_exports_populated_when_all_present(tmp_path):
    (tmp_path / 'mod.py').write_text(
        "__all__ = ['foo', 'bar']\ndef foo(): pass\ndef bar(): pass\n",
        encoding='utf-8',
    )
    g = _run(tmp_path)
    assert set(g.nodes['mod'].all_exports) == {'foo', 'bar'}


def test_module_node_all_exports_empty_without_all(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    g = _run(tmp_path)
    assert g.nodes['mod'].all_exports == []


# ---------------------------------------------------------------------------
# CLASS node
# ---------------------------------------------------------------------------

def test_class_node_kind(tmp_path):
    (tmp_path / 'mod.py').write_text('class Foo:\n    pass\n', encoding='utf-8')
    g = _run(tmp_path)
    assert g.nodes['mod.Foo'].kind == NodeKind.CLASS


def test_class_node_fqn(tmp_path):
    (tmp_path / 'mod.py').write_text('class Foo:\n    pass\n', encoding='utf-8')
    g = _run(tmp_path)
    assert 'mod.Foo' in g.nodes


def test_class_bases_populated(tmp_path):
    (tmp_path / 'mod.py').write_text('class Child(Base):\n    pass\n', encoding='utf-8')
    g = _run(tmp_path)
    assert 'Base' in g.nodes['mod.Child'].bases


# ---------------------------------------------------------------------------
# FUNCTION / METHOD kinds
# ---------------------------------------------------------------------------

def test_top_level_function_kind(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    g = _run(tmp_path)
    assert g.nodes['mod.foo'].kind == NodeKind.FUNCTION


def test_instance_method_kind(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'class C:\n    def meth(self): pass\n', encoding='utf-8'
    )
    g = _run(tmp_path)
    assert g.nodes['mod.C.meth'].kind == NodeKind.METHOD


def test_classmethod_kind(fixtures_graph):
    node = fixtures_graph.nodes.get('decorator_chain.DecoratedClass.class_method')
    assert node is not None
    assert node.kind == NodeKind.CLASSMETHOD


def test_staticmethod_kind(fixtures_graph):
    node = fixtures_graph.nodes.get('decorator_chain.DecoratedClass.static_method')
    assert node is not None
    assert node.kind == NodeKind.STATICMETHOD


def test_property_kind(fixtures_graph):
    node = fixtures_graph.nodes.get('property_getter.Config.value')
    assert node is not None
    assert node.kind == NodeKind.PROPERTY


# ---------------------------------------------------------------------------
# is_async
# ---------------------------------------------------------------------------

def test_async_function_is_async_true(fixtures_graph):
    node = fixtures_graph.nodes.get('async_surface.fetch')
    assert node is not None
    assert node.is_async is True


def test_async_method_is_async_true(fixtures_graph):
    node = fixtures_graph.nodes.get('async_surface.AsyncWorker.run')
    assert node is not None
    assert node.is_async is True


def test_sync_function_is_async_false(fixtures_graph):
    node = fixtures_graph.nodes.get('async_surface.AsyncWorker.sync_method')
    assert node is not None
    assert node.is_async is False


# ---------------------------------------------------------------------------
# is_abstract / is_mixin
# ---------------------------------------------------------------------------

def test_abstract_class_is_abstract_true(fixtures_graph):
    node = fixtures_graph.nodes.get('abstract_mixin.ConcreteABC')
    assert node is not None
    assert node.is_abstract is True


def test_mixin_class_is_mixin_true(fixtures_graph):
    node = fixtures_graph.nodes.get('abstract_mixin.ServiceMixin')
    assert node is not None
    assert node.is_mixin is True


def test_non_mixin_class_is_mixin_false(tmp_path):
    (tmp_path / 'mod.py').write_text('class Normal:\n    def __init__(self): pass\n', encoding='utf-8')
    g = _run(tmp_path)
    assert g.nodes['mod.Normal'].is_mixin is False


# ---------------------------------------------------------------------------
# is_dataclass + synthetic nodes
# ---------------------------------------------------------------------------

def test_dataclass_flag(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'from dataclasses import dataclass\n@dataclass\nclass Point:\n    x: int\n    y: int\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    assert g.nodes['mod.Point'].is_dataclass is True


def test_dataclass_synthetic_init_node(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'from dataclasses import dataclass\n@dataclass\nclass Point:\n    x: int\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    assert 'mod.Point.__init__' in g.nodes
    assert g.nodes['mod.Point.__init__'].is_synthetic is True


def test_dataclass_synthetic_repr_and_eq(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'from dataclasses import dataclass\n@dataclass\nclass Pt:\n    x: int\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    assert 'mod.Pt.__repr__' in g.nodes
    assert 'mod.Pt.__eq__' in g.nodes


# ---------------------------------------------------------------------------
# Decorators captured
# ---------------------------------------------------------------------------

def test_decorator_captured_on_function(fixtures_graph):
    node = fixtures_graph.nodes.get('decorator_chain.decorated_func')
    assert node is not None
    assert 'my_decorator' in node.decorators


def test_staticmethod_decorator_in_decorators(fixtures_graph):
    node = fixtures_graph.nodes.get('decorator_chain.DecoratedClass.static_method')
    assert node is not None
    assert 'staticmethod' in node.decorators


# ---------------------------------------------------------------------------
# INHERITS edges
# ---------------------------------------------------------------------------

def test_inherits_edge_emitted(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'class Base:\n    pass\nclass Child(Base):\n    pass\n', encoding='utf-8'
    )
    g = _run(tmp_path)
    inherits = [e for e in g.edges if e.kind == EdgeKind.INHERITS]
    assert any(e.src == 'mod.Child' for e in inherits)


def test_inherits_edge_dst_is_base_name(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'class Base:\n    pass\nclass Child(Base):\n    pass\n', encoding='utf-8'
    )
    g = _run(tmp_path)
    inherits = [e for e in g.edges if e.kind == EdgeKind.INHERITS and e.src == 'mod.Child']
    assert len(inherits) == 1
    assert inherits[0].dst == 'Base'


# ---------------------------------------------------------------------------
# LAMBDA node
# ---------------------------------------------------------------------------

def test_lambda_node_emitted(tmp_path):
    (tmp_path / 'mod.py').write_text('identity = lambda x: x\n', encoding='utf-8')
    g = _run(tmp_path)
    assert 'mod.identity' in g.nodes
    assert g.nodes['mod.identity'].kind == NodeKind.LAMBDA


# ---------------------------------------------------------------------------
# FQN correctness for nested definitions
# ---------------------------------------------------------------------------

def test_method_fqn_includes_class(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'class Foo:\n    def bar(self): pass\n', encoding='utf-8'
    )
    g = _run(tmp_path)
    assert 'mod.Foo.bar' in g.nodes


# ---------------------------------------------------------------------------
# is_protocol
# ---------------------------------------------------------------------------

def test_protocol_class_flag(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'from typing import Protocol\nclass MyProto(Protocol):\n    def method(self): ...\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    assert g.nodes['mod.MyProto'].is_protocol is True


# ---------------------------------------------------------------------------
# line / file fields
# ---------------------------------------------------------------------------

def test_function_line_number(tmp_path):
    (tmp_path / 'mod.py').write_text('x = 1\ndef foo(): pass\n', encoding='utf-8')
    g = _run(tmp_path)
    assert g.nodes['mod.foo'].line == 2


def test_file_is_relative_string(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    g = _run(tmp_path)
    file_val = g.nodes['mod.foo'].file
    assert isinstance(file_val, str)
    assert not file_val.startswith('C:') or '/' in file_val or '\\' in file_val
    assert 'mod.py' in file_val
