"""Phase 12 — Integration tests.

Runs the full pipeline (discover → parse → resolve → definitions → calls →
decorators → assemble → serialize) on the fixtures tree and validates output.

§13.1  mini-package fixture assertions (re-export, cycles, decorators, flags, wildcard)
§13.2  FastAPI ground-truth spot check — skipped: requires discovering from the
       site-packages root to get fully-qualified dotted names (fastapi.routing, etc.),
       which is impractical in a unit test context. Leaving as documented intent.
§13.3  snapshot regression for simple_pkg
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pyviz.engine.calls import extract_all as extract_calls
from pyviz.engine.decorators import extract_all as extract_decorators
from pyviz.engine.definitions import extract_all as extract_defs
from pyviz.engine.discovery import discover
from pyviz.engine.graph import assemble
from pyviz.engine.parser import parse_all
from pyviz.engine.resolver import resolve_all
from pyviz.engine.serializer import serialize
from pyviz.models import ProjectGraph, ResolvedBinding

FIXTURES = Path(__file__).parent / 'fixtures'
SIMPLE_PKG = FIXTURES / 'simple_pkg'
MUTUAL_CALLS_PKG = FIXTURES / 'mutual_calls'


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

def _run(root: Path):
    d = discover(root)
    p = parse_all(d)
    r = resolve_all(d, p)
    g = ProjectGraph()
    extract_defs(p, r, g, d)
    extract_calls(p, r, g, d)
    extract_decorators(p, r, g, d)
    return d, p, r, g


def _assemble(root: Path):
    d, p, r, g = _run(root)
    return d, p, r, g, assemble(g, d)


def _serialize(root: Path) -> dict:
    d, p, r, g, ar = _assemble(root)
    raw = serialize(g, ar.graph, ar.communities, ar.unused, ar.cycles, root)
    return json.loads(raw)


def _normalize_simple(data: dict) -> dict:
    """Normalize simple_pkg-only subset for stable snapshot comparison.

    Keeps only simple_pkg nodes/edges; normalizes all non-deterministic and
    cross-fixture meta fields so the snapshot is portable and stable.
    """
    data = copy.deepcopy(data)
    # Normalize all non-deterministic meta fields
    data['meta']['generated_at'] = 'NORMALIZED'
    data['meta']['python_version'] = 'NORMALIZED'
    data['meta']['root'] = 'NORMALIZED'
    data['meta']['circular_imports'] = []  # from full fixtures run, not simple_pkg
    data['meta']['unused_symbols'] = []    # same
    data['meta']['warnings'] = []          # same
    # Keep only simple_pkg nodes/edges for a small, stable snapshot
    data['nodes'] = [n for n in data['nodes'] if n['id'].startswith('simple_pkg')]
    data['edges'] = [
        e for e in data['edges']
        if e['src'].startswith('simple_pkg') and e['dst'].startswith('simple_pkg')
    ]
    data['nodes'].sort(key=lambda n: n['id'])
    data['edges'].sort(key=lambda e: (e['src'], e['dst'], e['kind']))
    for n in data['nodes']:
        if n.get('file'):
            n['file'] = Path(n['file']).name
        n['community'] = None  # Louvain IDs are non-deterministic across runs
    for e in data['edges']:
        if e.get('file'):
            e['file'] = Path(e['file']).name if e['file'] else None
    return data


# ---------------------------------------------------------------------------
# Session-scoped shared results (run full FIXTURES pipeline once per session)
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def fixtures_json():
    return _serialize(FIXTURES)


@pytest.fixture(scope='session')
def fixtures_nodes(fixtures_json):
    return {n['id']: n for n in fixtures_json['nodes']}


@pytest.fixture(scope='session')
def fixtures_edges(fixtures_json):
    return fixtures_json['edges']


@pytest.fixture(scope='session')
def fixtures_bindings():
    d, p, r, g = _run(FIXTURES)
    return r.bindings


# ===========================================================================
# §13.1 — Full pipeline + JSON schema validation
# ===========================================================================

def test_full_pipeline_returns_valid_json(fixtures_json):
    assert isinstance(fixtures_json, dict)
    assert 'nodes' in fixtures_json
    assert 'edges' in fixtures_json
    assert 'meta' in fixtures_json


def test_simple_pkg_has_add_node(fixtures_nodes):
    assert 'simple_pkg.core.add' in fixtures_nodes


def test_serialized_schema_nodes(fixtures_json):
    required = {
        'id', 'kind', 'name', 'file', 'line', 'is_async', 'is_abstract',
        'is_protocol', 'is_dataclass', 'is_mixin', 'bases', 'decorators',
        'warnings', 'community', 'role',
    }
    for node in fixtures_json['nodes']:
        missing = required - node.keys()
        assert not missing, f"node {node['id']!r} missing keys: {missing}"


def test_serialized_schema_edges(fixtures_json):
    required = {'src', 'dst', 'kind', 'confidence', 'is_type_only'}
    for edge in fixtures_json['edges']:
        missing = required - edge.keys()
        assert not missing, f"edge missing keys: {missing}"


# ---------------------------------------------------------------------------
# Re-export chain (§13.1 — reexport_chain fixture)
# ---------------------------------------------------------------------------

def test_reexport_resolves_to_source_file(fixtures_nodes):
    node = fixtures_nodes.get('reexport_pkg.core.Thing')
    assert node is not None, "reexport_pkg.core.Thing node not found"
    assert node['file'] is not None
    assert node['file'].endswith('core.py')


def test_reexport_not_in_init(fixtures_nodes):
    thing_nodes = [n for key, n in fixtures_nodes.items() if n.get('name') == 'Thing']
    for n in thing_nodes:
        assert not (n.get('file') or '').endswith('__init__.py'), \
            "Thing definition node should not point to __init__.py"


# ---------------------------------------------------------------------------
# Cycle detection (§13.1 — mutual_calls fixture)
# ---------------------------------------------------------------------------

def test_cycles_detected():
    d, p, r, g, ar = _assemble(MUTUAL_CALLS_PKG)
    assert len(ar.cycles) > 0, "mutual_calls.ping/pong cycle not detected"


def test_cycles_in_serialized_meta():
    data = _serialize(MUTUAL_CALLS_PKG)
    assert len(data['meta']['circular_imports']) > 0


# ---------------------------------------------------------------------------
# Decorator chain (§13.1 — decorator_chain fixture)
# ---------------------------------------------------------------------------

def test_decorator_chain_edge_present(fixtures_edges):
    decorates_edges = [
        e for e in fixtures_edges
        if e['kind'] == 'decorates'
        and e['src'] == 'decorator_chain.my_decorator'
        and e['dst'] == 'decorator_chain.decorated_func'
    ]
    assert decorates_edges, "DECORATES edge my_decorator → decorated_func not found"


def test_staticmethod_kind(fixtures_nodes):
    node = fixtures_nodes.get('decorator_chain.DecoratedClass.static_method')
    assert node is not None, "static_method node not found"
    assert node['kind'] == 'staticmethod'


def test_classmethod_kind(fixtures_nodes):
    node = fixtures_nodes.get('decorator_chain.DecoratedClass.class_method')
    assert node is not None, "class_method node not found"
    assert node['kind'] == 'classmethod'


# ---------------------------------------------------------------------------
# Abstract / mixin flags (§13.1 — abstract_mixin fixture)
# ---------------------------------------------------------------------------

def test_abstract_flag_set(fixtures_nodes):
    node = fixtures_nodes.get('abstract_mixin.ConcreteABC')
    assert node is not None, "ConcreteABC node not found"
    assert node['is_abstract'] is True


def test_mixin_flag_set(fixtures_nodes):
    node = fixtures_nodes.get('abstract_mixin.ServiceMixin')
    assert node is not None, "ServiceMixin node not found"
    assert node['is_mixin'] is True


# ---------------------------------------------------------------------------
# Wildcard import with __all__ (§13.1 — wildcard_all fixture)
# ---------------------------------------------------------------------------

def test_wildcard_all_foo_resolved(fixtures_bindings):
    b = fixtures_bindings.get(('wildcard_all.consumer', 'foo'))
    assert isinstance(b, ResolvedBinding), "'foo' should be bound via wildcard"


def test_wildcard_all_bar_resolved(fixtures_bindings):
    b = fixtures_bindings.get(('wildcard_all.consumer', 'bar'))
    assert isinstance(b, ResolvedBinding), "'bar' should be bound via wildcard"


def test_wildcard_all_private_not_bound(fixtures_bindings):
    b = fixtures_bindings.get(('wildcard_all.consumer', '_private'))
    assert not isinstance(b, ResolvedBinding), \
        "'_private' must not be bound (excluded from __all__)"


# ===========================================================================
# §13.3 — Snapshot regression for simple_pkg nodes/edges
# ===========================================================================

def test_simple_pkg_snapshot(snapshot, fixtures_json):
    data = _normalize_simple(fixtures_json)
    snapshot.snapshot_dir = Path(__file__).parent / '__snapshots__'
    snapshot.assert_match(json.dumps(data, indent=2, sort_keys=True), 'simple_pkg_snapshot.json')
