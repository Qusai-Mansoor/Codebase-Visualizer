"""Tests for pyviz/engine/serializer.py — Phase 9 verification."""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from pyviz.engine.calls import extract_all as extract_calls
from pyviz.engine.decorators import extract_all as extract_decorators
from pyviz.engine.definitions import extract_all as extract_defs
from pyviz.engine.discovery import discover
from pyviz.engine.graph import GraphAssemblyResult, assemble
from pyviz.engine.parser import parse_all
from pyviz.engine.resolver import resolve_all
from pyviz.engine.serializer import serialize
from pyviz.models import Confidence, EdgeKind, GraphEdge, ProjectGraph

FIXTURES = Path(__file__).parent / 'fixtures'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_run(root: Path) -> tuple[ProjectGraph, GraphAssemblyResult]:
    d = discover(root)
    p = parse_all(d)
    r = resolve_all(d, p)
    g = ProjectGraph()
    extract_defs(p, r, g, d)
    extract_calls(p, r, g, d)
    extract_decorators(p, r, g, d)
    result = assemble(g)
    return g, result


def _serialize_raw(root: Path) -> str:
    pg, ar = _full_run(root)
    return serialize(pg, ar.graph, ar.communities, ar.unused, ar.cycles, root)


def _serialize(root: Path) -> dict:
    return json.loads(_serialize_raw(root))


# ---------------------------------------------------------------------------
# Return value
# ---------------------------------------------------------------------------

def test_returns_string(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    pg, ar = _full_run(tmp_path)
    result = serialize(pg, ar.graph, ar.communities, ar.unused, ar.cycles, tmp_path)
    assert isinstance(result, str)


def test_valid_json(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    raw = _serialize_raw(tmp_path)
    # must not raise
    json.loads(raw)


# ---------------------------------------------------------------------------
# Top-level schema
# ---------------------------------------------------------------------------

def test_has_nodes_key(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    out = _serialize(tmp_path)
    assert 'nodes' in out


def test_has_edges_key(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    out = _serialize(tmp_path)
    assert 'edges' in out


def test_has_meta_key(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    out = _serialize(tmp_path)
    assert 'meta' in out


# ---------------------------------------------------------------------------
# nodes array
# ---------------------------------------------------------------------------

def test_nodes_is_list(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    out = _serialize(tmp_path)
    assert isinstance(out['nodes'], list)


def test_node_has_required_fields(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    out = _serialize(tmp_path)
    fn_node = next(n for n in out['nodes'] if n['id'] == 'mod.foo')
    for field in ('id', 'kind', 'name', 'file', 'line', 'end_line',
                  'docstring', 'is_async', 'is_abstract', 'is_protocol',
                  'is_dataclass', 'is_mixin', 'bases', 'decorators',
                  'warnings', 'community', 'role'):
        assert field in fn_node, f"missing field: {field}"


def test_node_kind_is_string(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    out = _serialize(tmp_path)
    for node in out['nodes']:
        assert isinstance(node['kind'], str), f"kind is not str: {node['kind']!r}"


def test_node_community_null_when_absent(tmp_path):
    # Single module — Louvain on isolated node returns community, but
    # an unclustered node (community not in dict) must serialize as null.
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    pg, ar = _full_run(tmp_path)
    # Forcibly clear communities so foo has no entry
    raw = serialize(pg, ar.graph, {}, ar.unused, ar.cycles, tmp_path)
    out = json.loads(raw)
    fn_node = next(n for n in out['nodes'] if n['id'] == 'mod.foo')
    assert fn_node['community'] is None


def test_node_role_null_when_absent(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    out = _serialize(tmp_path)
    fn_node = next(n for n in out['nodes'] if n['id'] == 'mod.foo')
    assert fn_node['role'] is None


def test_node_role_set_when_present():
    out = _serialize(FIXTURES / 'framework_roles')
    role_nodes = [n for n in out['nodes'] if n['role'] == 'test_fixture']
    assert len(role_nodes) > 0


# ---------------------------------------------------------------------------
# edges array
# ---------------------------------------------------------------------------

def test_edges_is_list(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\ndef bar(): foo()\n', encoding='utf-8')
    out = _serialize(tmp_path)
    assert isinstance(out['edges'], list)


def test_edge_has_required_fields(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\ndef bar(): foo()\n', encoding='utf-8')
    out = _serialize(tmp_path)
    assert len(out['edges']) > 0
    edge = out['edges'][0]
    for field in ('src', 'dst', 'kind', 'confidence', 'file', 'line', 'is_type_only'):
        assert field in edge, f"missing edge field: {field}"


def test_edge_kind_is_string(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\ndef bar(): foo()\n', encoding='utf-8')
    out = _serialize(tmp_path)
    for edge in out['edges']:
        assert isinstance(edge['kind'], str)


def test_dangling_edge_filtered(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    pg, ar = _full_run(tmp_path)
    # Inject a dangling edge: dst does not exist in pg.nodes
    pg.edges.append(GraphEdge(
        src='mod.foo',
        dst='nonexistent.ghost',
        kind=EdgeKind.CALLS,
        confidence=Confidence.STATIC,
    ))
    raw = serialize(pg, ar.graph, ar.communities, ar.unused, ar.cycles, tmp_path)
    out = json.loads(raw)
    dangling = [e for e in out['edges'] if e['dst'] == 'nonexistent.ghost']
    assert dangling == []


def test_edge_is_type_only_present(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\ndef bar(): foo()\n', encoding='utf-8')
    out = _serialize(tmp_path)
    for edge in out['edges']:
        assert 'is_type_only' in edge
        assert isinstance(edge['is_type_only'], bool)


# ---------------------------------------------------------------------------
# meta
# ---------------------------------------------------------------------------

def test_meta_root_is_string(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    out = _serialize(tmp_path)
    assert isinstance(out['meta']['root'], str)


def test_meta_generated_at_is_iso(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    out = _serialize(tmp_path)
    # Must not raise
    datetime.datetime.fromisoformat(out['meta']['generated_at'])


def test_meta_python_version_present(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    out = _serialize(tmp_path)
    assert 'python_version' in out['meta']
    assert isinstance(out['meta']['python_version'], str)


def test_meta_circular_imports_is_list(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    out = _serialize(tmp_path)
    assert isinstance(out['meta']['circular_imports'], list)


def test_meta_unused_symbols_is_list(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    out = _serialize(tmp_path)
    assert isinstance(out['meta']['unused_symbols'], list)


def test_meta_warnings_is_list(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    out = _serialize(tmp_path)
    assert isinstance(out['meta']['warnings'], list)


def test_meta_cycles_populated():
    out = _serialize(FIXTURES / 'mutual_calls')
    # mutual_calls has ping↔pong cycle; should appear in circular_imports
    all_cycle_nodes = {n for cycle in out['meta']['circular_imports'] for n in cycle}
    assert len(out['meta']['circular_imports']) > 0
    assert any('ping' in n for n in all_cycle_nodes)


def test_meta_unused_populated(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'def orphan(): pass\ndef caller(): pass\n', encoding='utf-8'
    )
    out = _serialize(tmp_path)
    assert len(out['meta']['unused_symbols']) > 0
