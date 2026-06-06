"""Tests for pyviz/engine/tracer.py — Phase 10 verification."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from pyviz.engine.tracer import RuntimeEdge, RuntimeTracer, trace_test_suite
from pyviz.models import (
    Confidence,
    DiscoveryResult,
    EdgeKind,
    GraphEdge,
    NodeKind,
    ProjectGraph,
)

FIXTURES = Path(__file__).parent / 'fixtures'


# ---------------------------------------------------------------------------
# Helper: build a minimal mock frame
# ---------------------------------------------------------------------------

def _frame(filename: str, qualname: str, back=None):
    code = types.SimpleNamespace(co_filename=filename, co_qualname=qualname)
    return types.SimpleNamespace(f_code=code, f_back=back)


def _tracer(tmp_path) -> RuntimeTracer:
    return RuntimeTracer(tmp_path)


# ---------------------------------------------------------------------------
# RuntimeEdge dataclass
# ---------------------------------------------------------------------------

def test_runtime_edge_fields():
    re = RuntimeEdge('a.py', 'mod_a.caller', 'b.py', 'mod_b.callee')
    assert re.caller_file == 'a.py'
    assert re.caller_qualname == 'mod_a.caller'
    assert re.callee_file == 'b.py'
    assert re.callee_qualname == 'mod_b.callee'


def test_runtime_edge_count_defaults_to_1():
    re = RuntimeEdge('a.py', 'q', 'b.py', 'r')
    assert re.count == 1


# ---------------------------------------------------------------------------
# _is_project_file
# ---------------------------------------------------------------------------

def test_is_project_file_true(tmp_path):
    t = RuntimeTracer(tmp_path)
    assert t._is_project_file(str(tmp_path / 'mod.py')) is True


def test_is_project_file_false(tmp_path):
    t = RuntimeTracer(tmp_path)
    assert t._is_project_file('/usr/lib/python3/os.py') is False


# ---------------------------------------------------------------------------
# _trace — return values
# ---------------------------------------------------------------------------

def test_non_call_event_returns_trace_func(tmp_path):
    t = _tracer(tmp_path)
    callee = _frame(str(tmp_path / 'a.py'), 'mod.func')
    result = t._trace(callee, 'return', None)
    assert result is t._trace


def test_callee_outside_project_returns_none(tmp_path):
    t = _tracer(tmp_path)
    callee = _frame('/usr/lib/python3/os.py', 'os.getcwd')
    result = t._trace(callee, 'call', None)
    assert result is None


def test_caller_none_returns_trace_func(tmp_path):
    t = _tracer(tmp_path)
    callee = _frame(str(tmp_path / 'a.py'), 'mod.func', back=None)
    result = t._trace(callee, 'call', None)
    assert result is t._trace


def test_caller_outside_project_returns_trace_func(tmp_path):
    t = _tracer(tmp_path)
    caller = _frame('/usr/lib/python3/os.py', 'os.walk')
    callee = _frame(str(tmp_path / 'a.py'), 'mod.func', back=caller)
    result = t._trace(callee, 'call', None)
    assert result is t._trace


def test_same_file_returns_trace_func_no_edge(tmp_path):
    t = _tracer(tmp_path)
    path = str(tmp_path / 'a.py')
    caller = _frame(path, 'mod.caller')
    callee = _frame(path, 'mod.callee', back=caller)
    result = t._trace(callee, 'call', None)
    assert result is t._trace
    assert len(t.edges) == 0


# ---------------------------------------------------------------------------
# _trace — edge recording
# ---------------------------------------------------------------------------

def test_cross_file_call_records_edge(tmp_path):
    t = _tracer(tmp_path)
    caller = _frame(str(tmp_path / 'a.py'), 'mod_a.caller')
    callee = _frame(str(tmp_path / 'b.py'), 'mod_b.callee', back=caller)
    t._trace(callee, 'call', None)
    assert len(t.edges) == 1


def test_recorded_edge_fields(tmp_path):
    t = _tracer(tmp_path)
    caller_path = str(tmp_path / 'a.py')
    callee_path = str(tmp_path / 'b.py')
    caller = _frame(caller_path, 'mod_a.caller')
    callee = _frame(callee_path, 'mod_b.callee', back=caller)
    t._trace(callee, 'call', None)
    re = next(iter(t.edges.values()))
    assert re.caller_file == caller_path
    assert re.caller_qualname == 'mod_a.caller'
    assert re.callee_file == callee_path
    assert re.callee_qualname == 'mod_b.callee'


def test_duplicate_call_increments_count(tmp_path):
    t = _tracer(tmp_path)
    caller = _frame(str(tmp_path / 'a.py'), 'mod_a.fn')
    callee = _frame(str(tmp_path / 'b.py'), 'mod_b.fn', back=caller)
    t._trace(callee, 'call', None)
    t._trace(callee, 'call', None)
    re = next(iter(t.edges.values()))
    assert re.count == 2


# ---------------------------------------------------------------------------
# start / stop
# ---------------------------------------------------------------------------

def test_start_installs_sys_trace(tmp_path):
    t = _tracer(tmp_path)
    prev = sys.gettrace()
    try:
        t.start()
        assert sys.gettrace() is t._trace
    finally:
        t.stop()
        sys.settrace(prev)


def test_stop_removes_sys_trace(tmp_path):
    t = _tracer(tmp_path)
    prev = sys.gettrace()
    try:
        t.start()
        t.stop()
        assert sys.gettrace() is None
    finally:
        sys.settrace(prev)


# ---------------------------------------------------------------------------
# merge_into_graph
# ---------------------------------------------------------------------------

def _minimal_discovery(tmp_path) -> DiscoveryResult:
    """Discovery with two modules: mod_a -> a.py, mod_b -> b.py."""
    a = tmp_path / 'a.py'
    b = tmp_path / 'b.py'
    a.write_text('', encoding='utf-8')
    b.write_text('', encoding='utf-8')
    return DiscoveryResult(
        root=tmp_path,
        module_map={'mod_a': a, 'mod_b': b},
        package_map={},
        skipped={},
    )


def test_merge_upgrades_static_edge_to_both(tmp_path):
    discovery = _minimal_discovery(tmp_path)
    pg = ProjectGraph()
    static_edge = GraphEdge(
        src='mod_a.caller', dst='mod_b.callee',
        kind=EdgeKind.CALLS, confidence=Confidence.STATIC,
    )
    pg.edges.append(static_edge)

    t = _tracer(tmp_path)
    t.edges[(str(tmp_path / 'a.py'), 'caller', str(tmp_path / 'b.py'), 'callee')] = \
        RuntimeEdge(str(tmp_path / 'a.py'), 'caller', str(tmp_path / 'b.py'), 'callee')
    t.merge_into_graph(pg, discovery)

    assert static_edge.confidence == Confidence.BOTH


def test_merge_appends_runtime_edge(tmp_path):
    discovery = _minimal_discovery(tmp_path)
    pg = ProjectGraph()

    t = _tracer(tmp_path)
    t.edges[(str(tmp_path / 'a.py'), 'caller', str(tmp_path / 'b.py'), 'callee')] = \
        RuntimeEdge(str(tmp_path / 'a.py'), 'caller', str(tmp_path / 'b.py'), 'callee')
    t.merge_into_graph(pg, discovery)

    assert len(pg.edges) == 1
    assert pg.edges[0].confidence == Confidence.RUNTIME
    assert pg.edges[0].kind == EdgeKind.CALLS
    assert pg.edges[0].src == 'mod_a.caller'
    assert pg.edges[0].dst == 'mod_b.callee'


def test_merge_skips_unmappable_caller(tmp_path):
    discovery = _minimal_discovery(tmp_path)
    pg = ProjectGraph()

    t = _tracer(tmp_path)
    t.edges[('/unknown/x.py', 'caller', str(tmp_path / 'b.py'), 'callee')] = \
        RuntimeEdge('/unknown/x.py', 'caller', str(tmp_path / 'b.py'), 'callee')
    t.merge_into_graph(pg, discovery)

    assert len(pg.edges) == 0


def test_merge_skips_unmappable_callee(tmp_path):
    discovery = _minimal_discovery(tmp_path)
    pg = ProjectGraph()

    t = _tracer(tmp_path)
    t.edges[(str(tmp_path / 'a.py'), 'caller', '/unknown/y.py', 'callee')] = \
        RuntimeEdge(str(tmp_path / 'a.py'), 'caller', '/unknown/y.py', 'callee')
    t.merge_into_graph(pg, discovery)

    assert len(pg.edges) == 0


def test_merge_empty_edges_is_noop(tmp_path):
    discovery = _minimal_discovery(tmp_path)
    pg = ProjectGraph()
    static_edge = GraphEdge(
        src='mod_a.fn', dst='mod_b.fn',
        kind=EdgeKind.CALLS, confidence=Confidence.STATIC,
    )
    pg.edges.append(static_edge)

    t = _tracer(tmp_path)
    t.merge_into_graph(pg, discovery)

    assert len(pg.edges) == 1
    assert static_edge.confidence == Confidence.STATIC  # unchanged


def test_merge_does_not_touch_other_edge_kinds(tmp_path):
    discovery = _minimal_discovery(tmp_path)
    pg = ProjectGraph()
    inherits_edge = GraphEdge(
        src='mod_a.Child', dst='mod_b.Parent',
        kind=EdgeKind.INHERITS, confidence=Confidence.STATIC,
    )
    pg.edges.append(inherits_edge)

    t = _tracer(tmp_path)
    # Simulate a runtime call with the same src/dst as the inherits edge
    t.edges[(str(tmp_path / 'a.py'), 'Child', str(tmp_path / 'b.py'), 'Parent')] = \
        RuntimeEdge(str(tmp_path / 'a.py'), 'Child', str(tmp_path / 'b.py'), 'Parent')
    t.merge_into_graph(pg, discovery)

    # The INHERITS edge must not have been touched; a new CALLS edge is appended
    assert inherits_edge.confidence == Confidence.STATIC
    assert any(e.kind == EdgeKind.CALLS for e in pg.edges)


# ---------------------------------------------------------------------------
# trace_test_suite — callable guard
# ---------------------------------------------------------------------------

def test_trace_test_suite_is_callable():
    assert callable(trace_test_suite)
