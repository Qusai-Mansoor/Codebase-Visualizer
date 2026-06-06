"""Tests for pyviz/engine/calls.py — Phase 6 verification."""
from __future__ import annotations

from pathlib import Path

import pytest

from pyviz.engine.calls import extract_all as extract_calls
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
    return g


def _calls_from(graph: ProjectGraph, src: str) -> list[str]:
    return [
        e.dst for e in graph.edges
        if e.kind == EdgeKind.CALLS and e.src == src
    ]


def _calls_edges(graph: ProjectGraph) -> list[tuple[str, str]]:
    return [(e.src, e.dst) for e in graph.edges if e.kind == EdgeKind.CALLS]


@pytest.fixture(scope='session')
def fixtures_graph() -> ProjectGraph:
    return _run(FIXTURES)


@pytest.fixture(scope='session')
def call_graph() -> ProjectGraph:
    # Discover from FIXTURES (parent) so names are 'call_graph_pkg.foo' not 'foo'
    return _run(FIXTURES)


# ---------------------------------------------------------------------------
# Return type / structure
# ---------------------------------------------------------------------------

def test_extract_calls_returns_project_graph(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    g = _run(tmp_path)
    assert isinstance(g, ProjectGraph)


def test_no_calls_produces_no_call_edges(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo():\n    x = 1\n    return x\n', encoding='utf-8')
    g = _run(tmp_path)
    call_edges = [e for e in g.edges if e.kind == EdgeKind.CALLS]
    assert call_edges == []


# ---------------------------------------------------------------------------
# Basic local call edges
# ---------------------------------------------------------------------------

def test_local_call_produces_edge(call_graph):
    dsts = _calls_from(call_graph, 'call_graph_pkg.caller')
    assert 'call_graph_pkg.helper' in dsts


def test_call_edge_kind(call_graph):
    edges = [e for e in call_graph.edges if e.kind == EdgeKind.CALLS]
    assert len(edges) > 0
    assert all(e.kind == EdgeKind.CALLS for e in edges)


def test_call_edge_confidence_static(call_graph):
    edges = [
        e for e in call_graph.edges
        if e.kind == EdgeKind.CALLS and e.src == 'call_graph_pkg.caller'
    ]
    assert len(edges) > 0
    assert all(e.confidence == Confidence.STATIC for e in edges)


def test_call_edge_has_line_number(call_graph):
    edges = [
        e for e in call_graph.edges
        if e.kind == EdgeKind.CALLS and e.src == 'call_graph_pkg.caller'
    ]
    assert len(edges) > 0
    assert all(e.line is not None for e in edges)


def test_multiple_calls_from_same_caller(call_graph):
    dsts = _calls_from(call_graph, 'call_graph_pkg.multi_caller')
    assert 'call_graph_pkg.helper' in dsts
    assert 'call_graph_pkg.caller' in dsts


# ---------------------------------------------------------------------------
# Builtin calls suppressed
# ---------------------------------------------------------------------------

def test_builtin_print_no_edge(call_graph):
    dsts = _calls_from(call_graph, 'call_graph_pkg.builtin_user')
    assert not any('print' in d for d in dsts)


def test_builtin_len_no_edge(call_graph):
    dsts = _calls_from(call_graph, 'call_graph_pkg.builtin_user')
    assert not any('len' in d for d in dsts)


def test_builtin_no_dynamic_warning(call_graph):
    warnings = [w for w in call_graph.warnings if w.kind == 'dynamic_call'
                and 'builtin_user' in (w.message or '')]
    assert warnings == []


# ---------------------------------------------------------------------------
# self / cls calls — no edge, no warning
# ---------------------------------------------------------------------------

def test_self_method_call_no_edge(call_graph):
    # method_a calls self.method_b() — self is untyped, no CALLS edge
    dsts = _calls_from(call_graph, 'call_graph_pkg.MyClass.method_a')
    assert 'call_graph_pkg.MyClass.method_b' not in dsts


def test_self_call_no_dynamic_warning(call_graph):
    warnings = [w for w in call_graph.warnings if w.kind == 'dynamic_call'
                and 'method_a' in (w.message or '')]
    assert warnings == []


# ---------------------------------------------------------------------------
# Cross-module call via resolved binding
# ---------------------------------------------------------------------------

def test_cross_module_call_via_binding(call_graph):
    # app.main() calls utility() which was imported from .utils
    dsts = _calls_from(call_graph, 'call_graph_pkg.app.main')
    assert 'call_graph_pkg.utils.utility' in dsts


def test_cross_module_call_confidence_static(call_graph):
    edges = [
        e for e in call_graph.edges
        if e.kind == EdgeKind.CALLS and e.src == 'call_graph_pkg.app.main'
        and e.dst == 'call_graph_pkg.utils.utility'
    ]
    assert len(edges) == 1
    assert edges[0].confidence == Confidence.STATIC


# ---------------------------------------------------------------------------
# Dynamic calls produce warnings
# ---------------------------------------------------------------------------

def test_dynamic_call_warning_emitted(call_graph):
    # app.dynamic_example(obj) calls obj.unknown_method() — dynamic
    warnings = [w for w in call_graph.warnings if w.kind == 'dynamic_call']
    assert len(warnings) > 0


def test_dynamic_call_warning_has_message(call_graph):
    warnings = [w for w in call_graph.warnings if w.kind == 'dynamic_call']
    assert all(w.message for w in warnings)


def test_dynamic_call_no_edge_added(call_graph):
    # obj.unknown_method() produces a warning, not an edge
    dsts = _calls_from(call_graph, 'call_graph_pkg.app.dynamic_example')
    assert len(dsts) == 0


# ---------------------------------------------------------------------------
# TYPE_CHECKING block — no call edges
# ---------------------------------------------------------------------------

def test_type_checking_block_calls_suppressed(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'from typing import TYPE_CHECKING\n'
        'def foo(): pass\n'
        'def bar():\n'
        '    if TYPE_CHECKING:\n'
        '        foo()\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    dsts = _calls_from(g, 'mod.bar')
    assert 'mod.foo' not in dsts


def test_type_checking_no_warning(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'from typing import TYPE_CHECKING\n'
        'def bar():\n'
        '    if TYPE_CHECKING:\n'
        '        some_func()\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    warnings = [w for w in g.warnings if w.kind == 'dynamic_call']
    assert warnings == []


# ---------------------------------------------------------------------------
# Nested calls (args contain calls)
# ---------------------------------------------------------------------------

def test_nested_call_in_arg_produces_edge(call_graph):
    # nested_call does len(helper()) — helper() inside len() args
    dsts = _calls_from(call_graph, 'call_graph_pkg.MyClass.nested_call')
    assert 'call_graph_pkg.helper' in dsts


# ---------------------------------------------------------------------------
# Method uses module-level helper
# ---------------------------------------------------------------------------

def test_method_calls_module_function(call_graph):
    dsts = _calls_from(call_graph, 'call_graph_pkg.MyClass.uses_helper')
    assert 'call_graph_pkg.helper' in dsts


# ---------------------------------------------------------------------------
# Module-level calls not attributed to any function
# ---------------------------------------------------------------------------

def test_module_level_call_not_attributed(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'def foo(): pass\nfoo()  # module-level call\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    edges = _calls_edges(g)
    # No function node 'mod' — module-level calls have no caller scope
    assert not any(src == 'mod' for src, _ in edges)


# ---------------------------------------------------------------------------
# Call edges have correct file field
# ---------------------------------------------------------------------------

def test_call_edge_file_is_string(call_graph):
    edges = [e for e in call_graph.edges if e.kind == EdgeKind.CALLS]
    assert len(edges) > 0
    assert all(isinstance(e.file, str) for e in edges if e.file is not None)


# ---------------------------------------------------------------------------
# with statement — no crash, regular calls inside body still tracked
# ---------------------------------------------------------------------------

def test_with_statement_no_crash(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'def foo():\n    with open("f") as fh:\n        pass\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    assert isinstance(g, ProjectGraph)


def test_calls_inside_with_body_tracked(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'def helper(): pass\n'
        'def foo():\n'
        '    with open("f") as fh:\n'
        '        helper()\n',
        encoding='utf-8',
    )
    g = _run(tmp_path)
    dsts = _calls_from(g, 'mod.foo')
    assert 'mod.helper' in dsts


# ---------------------------------------------------------------------------
# Intra-module chained call: utils.second() → utility()
# ---------------------------------------------------------------------------

def test_intra_module_chained_call(call_graph):
    dsts = _calls_from(call_graph, 'call_graph_pkg.utils.second')
    assert 'call_graph_pkg.utils.utility' in dsts
