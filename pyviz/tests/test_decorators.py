"""Tests for pyviz/engine/decorators.py — Phase 7 verification."""
from __future__ import annotations

from pathlib import Path

import pytest

from pyviz.engine.calls import extract_all as extract_calls
from pyviz.engine.decorators import extract_all as extract_decorators
from pyviz.engine.definitions import extract_all as extract_defs
from pyviz.engine.discovery import discover
from pyviz.engine.parser import parse_all
from pyviz.engine.resolver import resolve_all
from pyviz.models import (
    Confidence,
    EdgeKind,
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
    g = extract_defs(p, r, g, d)
    g = extract_calls(p, r, g, d)
    g = extract_decorators(p, r, g, d)
    return g


def _decorates_edges(graph: ProjectGraph) -> list[tuple[str, str]]:
    return [(e.src, e.dst) for e in graph.edges if e.kind == EdgeKind.DECORATES]


@pytest.fixture(scope='session')
def fixtures_graph() -> ProjectGraph:
    return _run(FIXTURES)


# ---------------------------------------------------------------------------
# Return type / structure
# ---------------------------------------------------------------------------

def test_extract_all_returns_project_graph(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    g = _run(tmp_path)
    assert isinstance(g, ProjectGraph)


# ---------------------------------------------------------------------------
# DECORATES edges
# ---------------------------------------------------------------------------

def test_decorates_edge_emitted(fixtures_graph):
    # decorator_chain: @my_decorator on decorated_func
    # my_decorator is defined locally → binding exists → DECORATES edge
    edges = _decorates_edges(fixtures_graph)
    dsts = [dst for _, dst in edges]
    assert 'decorator_chain.decorated_func' in dsts


def test_decorates_edge_direction(fixtures_graph):
    edges = [
        e for e in fixtures_graph.edges
        if e.kind == EdgeKind.DECORATES and e.dst == 'decorator_chain.decorated_func'
    ]
    assert len(edges) == 1
    assert edges[0].src == 'decorator_chain.my_decorator'


def test_decorates_edge_kind(fixtures_graph):
    edges = [e for e in fixtures_graph.edges if e.kind == EdgeKind.DECORATES]
    assert len(edges) > 0
    assert all(e.kind == EdgeKind.DECORATES for e in edges)


def test_decorates_edge_confidence_static(fixtures_graph):
    edges = [
        e for e in fixtures_graph.edges
        if e.kind == EdgeKind.DECORATES and e.dst == 'decorator_chain.decorated_func'
    ]
    assert len(edges) == 1
    assert edges[0].confidence == Confidence.STATIC


def test_decorates_edge_has_file(fixtures_graph):
    edges = [e for e in fixtures_graph.edges if e.kind == EdgeKind.DECORATES]
    assert len(edges) > 0
    assert all(e.file is not None for e in edges)


def test_stacked_decorators_two_edges(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'def dec_a(f): return f\n'
        'def dec_b(f): return f\n'
        '@dec_a\n'
        '@dec_b\n'
        'def target(): pass\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    edges = [e for e in g.edges if e.kind == EdgeKind.DECORATES and e.dst == 'mod.target']
    assert len(edges) == 2
    srcs = {e.src for e in edges}
    assert 'mod.dec_a' in srcs
    assert 'mod.dec_b' in srcs


def test_unresolved_decorator_no_edge(tmp_path):
    # External decorator not in bindings → no DECORATES edge
    (tmp_path / 'mod.py').write_text(
        'from click import command\n'
        '@command()\n'
        'def cli(): pass\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    edges = [e for e in g.edges if e.kind == EdgeKind.DECORATES]
    assert edges == []


def test_decorator_with_args_stripped(fixtures_graph):
    # @pytest.fixture(scope='session') → base stripped to 'pytest.fixture' → role tagged
    node = fixtures_graph.nodes.get('framework_roles.session_fixture')
    assert node is not None
    assert node.role == 'test_fixture'


# ---------------------------------------------------------------------------
# Role tagging
# ---------------------------------------------------------------------------

def test_role_pytest_fixture(fixtures_graph):
    node = fixtures_graph.nodes.get('framework_roles.my_fixture')
    assert node is not None
    assert node.role == 'test_fixture'


def test_role_pytest_fixture_with_args(fixtures_graph):
    node = fixtures_graph.nodes.get('framework_roles.session_fixture')
    assert node is not None
    assert node.role == 'test_fixture'


def test_role_property(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'class Foo:\n    @property\n    def val(self): return 1\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    node = g.nodes.get('mod.Foo.val')
    assert node is not None
    assert node.role == 'property'


def test_role_abstractmethod(fixtures_graph):
    node = fixtures_graph.nodes.get('abstract_mixin.ConcreteABC.do_thing')
    assert node is not None
    assert node.role == 'abstract'


def test_role_dataclass(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'from dataclasses import dataclass\n@dataclass\nclass Point:\n    x: int\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    node = g.nodes.get('mod.Point')
    assert node is not None
    assert node.role == 'dataclass'


def test_role_http_endpoint_router(tmp_path):
    # Simulate @router.get('/x') — unresolved but role matched by text
    (tmp_path / 'mod.py').write_text(
        'def get(path):\n    def dec(f): return f\n    return dec\n'
        'class router:\n    @staticmethod\n    def get(path):\n        def dec(f): return f\n        return dec\n'
        'class router_inst: pass\n'
        'router_inst = router()\n'
        '@router.get("/")\n'
        'def endpoint(): pass\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    node = g.nodes.get('mod.endpoint')
    assert node is not None
    assert node.role == 'http_endpoint'


def test_role_cli_command(tmp_path):
    (tmp_path / 'mod.py').write_text(
        '@click.command()\ndef cli(): pass\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    node = g.nodes.get('mod.cli')
    assert node is not None
    assert node.role == 'cli_command'


def test_role_background_task(tmp_path):
    (tmp_path / 'mod.py').write_text(
        '@app.task\ndef work(): pass\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    node = g.nodes.get('mod.work')
    assert node is not None
    assert node.role == 'background_task'


def test_role_auth_guarded(tmp_path):
    (tmp_path / 'mod.py').write_text(
        '@login_required\ndef protected(): pass\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    node = g.nodes.get('mod.protected')
    assert node is not None
    assert node.role == 'auth_guarded'


def test_no_role_plain_function(tmp_path):
    (tmp_path / 'mod.py').write_text('def plain(): pass\n', encoding='utf-8')
    g = _run(tmp_path)
    node = g.nodes.get('mod.plain')
    assert node is not None
    assert node.role is None


# ---------------------------------------------------------------------------
# getattr dynamic dispatch
# ---------------------------------------------------------------------------

def test_getattr_dispatch_warning_emitted(fixtures_graph):
    warnings = [w for w in fixtures_graph.warnings if w.kind == 'dynamic_dispatch']
    assert len(warnings) > 0


def test_getattr_warning_kind(fixtures_graph):
    warnings = [w for w in fixtures_graph.warnings if w.kind == 'dynamic_dispatch']
    assert all(w.kind == 'dynamic_dispatch' for w in warnings)


def test_getattr_normal_call_no_warning(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'def normal():\n    return len([1, 2, 3])\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    warnings = [w for w in g.warnings if w.kind == 'dynamic_dispatch']
    assert warnings == []


def test_getattr_no_call_edge(fixtures_graph):
    # getattr dispatch must NOT produce a CALLS edge
    from pyviz.models import EdgeKind as EK
    calls = [
        e for e in fixtures_graph.edges
        if e.kind == EK.CALLS and e.src == 'getattr_dispatch.dispatcher'
    ]
    assert calls == []
