"""Tests for pyviz/engine/graph.py — Phase 8 verification."""
from __future__ import annotations

from pathlib import Path

import networkx as nx
import pytest

from pyviz.engine.calls import extract_all as extract_calls
from pyviz.engine.decorators import extract_all as extract_decorators
from pyviz.engine.definitions import extract_all as extract_defs
from pyviz.engine.discovery import discover
from pyviz.engine.graph import GraphAssemblyResult, assemble, build_nx_graph
from pyviz.engine.parser import parse_all
from pyviz.engine.resolver import resolve_all
from pyviz.models import ProjectGraph

FIXTURES = Path(__file__).parent / 'fixtures'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_graph(root: Path) -> ProjectGraph:
    d = discover(root)
    p = parse_all(d)
    r = resolve_all(d, p)
    g = ProjectGraph()
    extract_defs(p, r, g, d)
    extract_calls(p, r, g, d)
    extract_decorators(p, r, g, d)
    return g


def _run(root: Path) -> GraphAssemblyResult:
    return assemble(_build_graph(root))


@pytest.fixture(scope='session')
def fixtures_result() -> GraphAssemblyResult:
    return _run(FIXTURES)


# ---------------------------------------------------------------------------
# Return type / structure
# ---------------------------------------------------------------------------

def test_assemble_returns_assembly_result(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    result = _run(tmp_path)
    assert isinstance(result, GraphAssemblyResult)


def test_graph_is_digraph(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    result = _run(tmp_path)
    assert isinstance(result.graph, nx.DiGraph)


def test_cycles_is_list(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    result = _run(tmp_path)
    assert isinstance(result.cycles, list)


def test_unused_is_list(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    result = _run(tmp_path)
    assert isinstance(result.unused, list)


def test_communities_is_dict(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    result = _run(tmp_path)
    assert isinstance(result.communities, dict)


# ---------------------------------------------------------------------------
# build_nx_graph — nodes
# ---------------------------------------------------------------------------

def test_graph_nodes_populated(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    pg = _build_graph(tmp_path)
    G = build_nx_graph(pg)
    assert 'mod' in G.nodes
    assert 'mod.foo' in G.nodes


def test_graph_node_has_kind_attr(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    pg = _build_graph(tmp_path)
    G = build_nx_graph(pg)
    assert G.nodes['mod.foo']['kind'] == 'function'


def test_graph_node_has_file_attr(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    pg = _build_graph(tmp_path)
    G = build_nx_graph(pg)
    assert G.nodes['mod.foo']['file'] is not None


# ---------------------------------------------------------------------------
# build_nx_graph — edges
# ---------------------------------------------------------------------------

def test_graph_edges_populated(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'def foo(): pass\ndef bar(): foo()\n', encoding='utf-8'
    )
    pg = _build_graph(tmp_path)
    G = build_nx_graph(pg)
    assert G.has_edge('mod.bar', 'mod.foo')


def test_graph_edge_has_kind_attr(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'def foo(): pass\ndef bar(): foo()\n', encoding='utf-8'
    )
    pg = _build_graph(tmp_path)
    G = build_nx_graph(pg)
    assert G['mod.bar']['mod.foo']['kind'] == 'calls'


def test_graph_edge_has_confidence_attr(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'def foo(): pass\ndef bar(): foo()\n', encoding='utf-8'
    )
    pg = _build_graph(tmp_path)
    G = build_nx_graph(pg)
    assert 'confidence' in G['mod.bar']['mod.foo']


# ---------------------------------------------------------------------------
# find_cycles
# ---------------------------------------------------------------------------

def test_cycle_detected(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'def ping(): pong()\ndef pong(): ping()\n', encoding='utf-8'
    )
    result = _run(tmp_path)
    assert len(result.cycles) > 0


def test_cycle_contains_both_functions(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'def ping(): pong()\ndef pong(): ping()\n', encoding='utf-8'
    )
    result = _run(tmp_path)
    all_nodes = {n for cycle in result.cycles for n in cycle}
    assert 'mod.ping' in all_nodes
    assert 'mod.pong' in all_nodes


def test_cycle_deduplicated(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'def ping(): pong()\ndef pong(): ping()\n', encoding='utf-8'
    )
    result = _run(tmp_path)
    canonical = {tuple(sorted(c)) for c in result.cycles}
    assert len(canonical) == len(result.cycles)


def test_no_cycle_linear_calls(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'def foo(): pass\ndef bar(): foo()\n', encoding='utf-8'
    )
    result = _run(tmp_path)
    assert result.cycles == []


# ---------------------------------------------------------------------------
# _find_unused_symbols
# ---------------------------------------------------------------------------

def test_unused_finds_uncalled_function(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'def called(): pass\ndef caller(): called()\ndef orphan(): pass\n',
        encoding='utf-8',
    )
    result = _run(tmp_path)
    assert 'mod.orphan' in result.unused


def test_unused_excludes_called_function(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'def called(): pass\ndef caller(): called()\n', encoding='utf-8'
    )
    result = _run(tmp_path)
    assert 'mod.called' not in result.unused


def test_unused_excludes_dunder(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'class Foo:\n    def __init__(self): pass\n', encoding='utf-8'
    )
    result = _run(tmp_path)
    assert 'mod.Foo.__init__' not in result.unused


def test_unused_excludes_exported(tmp_path):
    (tmp_path / 'mod.py').write_text(
        "__all__ = ['Foo']\nclass Foo: pass\n", encoding='utf-8'
    )
    result = _run(tmp_path)
    assert 'mod.Foo' not in result.unused


def test_unused_excludes_test_file_function(tmp_path):
    (tmp_path / 'test_something.py').write_text(
        'def test_foo(): pass\n', encoding='utf-8'
    )
    result = _run(tmp_path)
    assert 'test_something.test_foo' not in result.unused


# ---------------------------------------------------------------------------
# _detect_communities
# ---------------------------------------------------------------------------

def test_communities_int_values(fixtures_result):
    assert all(isinstance(v, int) for v in fixtures_result.communities.values())


def test_communities_covers_module_nodes(fixtures_result):
    module_nodes = [
        nid for nid, d in fixtures_result.graph.nodes(data=True)
        if d.get('kind') == 'module'
    ]
    assert len(module_nodes) > 0
    for nid in module_nodes:
        assert nid in fixtures_result.communities
