"""Tests for Phase 11 — cross-cutting implicit requirements.

Covers:
  §12.3  pyproject.toml entry-point scripts → roots
  §12.8  importlib.import_module() → dynamic_import warning
  §12.9  if sys.version_info >= ... → is_conditional binding
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pyviz.engine.calls import extract_all as extract_calls
from pyviz.engine.definitions import extract_all as extract_defs
from pyviz.engine.discovery import discover
from pyviz.engine.graph import assemble
from pyviz.engine.parser import parse_all
from pyviz.engine.resolver import resolve_all
from pyviz.models import ProjectGraph, ResolvedBinding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(root: Path):
    d = discover(root)
    p = parse_all(d)
    r = resolve_all(d, p)
    g = ProjectGraph()
    extract_defs(p, r, g, d)
    extract_calls(p, r, g, d)
    return d, p, r, g


def _assemble(root: Path):
    d, p, r, g = _run(root)
    return d, assemble(g, d)


# ===========================================================================
# §12.3 — Entry points from pyproject.toml
# ===========================================================================

def test_pyproject_scripts_parsed(tmp_path):
    (tmp_path / 'myapp').mkdir()
    (tmp_path / 'myapp' / '__init__.py').write_text('', encoding='utf-8')
    (tmp_path / 'myapp' / 'cli.py').write_text('def main(): pass\n', encoding='utf-8')
    (tmp_path / 'pyproject.toml').write_text(
        '[project.scripts]\nmyapp = "myapp.cli:main"\n', encoding='utf-8'
    )
    d = discover(tmp_path)
    assert 'myapp' in d.entry_points


def test_entry_point_colon_converted(tmp_path):
    (tmp_path / 'myapp').mkdir()
    (tmp_path / 'myapp' / '__init__.py').write_text('', encoding='utf-8')
    (tmp_path / 'myapp' / 'cli.py').write_text('def main(): pass\n', encoding='utf-8')
    (tmp_path / 'pyproject.toml').write_text(
        '[project.scripts]\nmyapp = "myapp.cli:main"\n', encoding='utf-8'
    )
    d = discover(tmp_path)
    assert d.entry_points['myapp'] == 'myapp.cli.main'


def test_missing_pyproject_gives_empty(tmp_path):
    (tmp_path / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    d = discover(tmp_path)
    assert d.entry_points == {}


def test_entry_point_not_in_unused(tmp_path):
    (tmp_path / 'myapp').mkdir()
    (tmp_path / 'myapp' / '__init__.py').write_text('', encoding='utf-8')
    (tmp_path / 'myapp' / 'cli.py').write_text('def main(): pass\n', encoding='utf-8')
    (tmp_path / 'pyproject.toml').write_text(
        '[project.scripts]\nmyapp = "myapp.cli:main"\n', encoding='utf-8'
    )
    _, ar = _assemble(tmp_path)
    assert 'myapp.cli.main' not in ar.unused


def test_poetry_scripts_parsed(tmp_path):
    (tmp_path / 'srv').mkdir()
    (tmp_path / 'srv' / '__init__.py').write_text('', encoding='utf-8')
    (tmp_path / 'srv' / 'run.py').write_text('def serve(): pass\n', encoding='utf-8')
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.poetry.scripts]\nsrv = "srv.run:serve"\n', encoding='utf-8'
    )
    d = discover(tmp_path)
    assert d.entry_points.get('srv') == 'srv.run.serve'


# ===========================================================================
# §12.8 — importlib.import_module detection
# ===========================================================================

def test_importlib_dot_import_module_warning(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'import importlib\ndef loader(): importlib.import_module("foo")\n',
        encoding='utf-8',
    )
    _, _, _, g = _run(tmp_path)
    kinds = [w.kind for w in g.warnings]
    assert 'dynamic_import' in kinds


def test_importlib_warning_kind(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'import importlib\ndef loader(): importlib.import_module("mymod")\n',
        encoding='utf-8',
    )
    _, _, _, g = _run(tmp_path)
    w = next(w for w in g.warnings if w.kind == 'dynamic_import')
    assert w.kind == 'dynamic_import'


def test_importlib_literal_in_message(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'import importlib\ndef loader(): importlib.import_module("target_mod")\n',
        encoding='utf-8',
    )
    _, _, _, g = _run(tmp_path)
    w = next(w for w in g.warnings if w.kind == 'dynamic_import')
    assert 'target_mod' in w.message


def test_importlib_dynamic_arg_message(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'import importlib\ndef loader(name): importlib.import_module(name)\n',
        encoding='utf-8',
    )
    _, _, _, g = _run(tmp_path)
    w = next(w for w in g.warnings if w.kind == 'dynamic_import')
    assert 'dynamic string' in w.message


def test_importlib_no_calls_edge(tmp_path):
    (tmp_path / 'mod.py').write_text(
        'import importlib\ndef loader(): importlib.import_module("foo")\n',
        encoding='utf-8',
    )
    _, _, _, g = _run(tmp_path)
    calls_edges = [e for e in g.edges if e.kind.value == 'calls']
    # No CALLS edge to importlib; the warning replaces it
    assert not any('importlib' in e.dst for e in calls_edges)


# ===========================================================================
# §12.9 — Version-gated imports (sys.version_info)
# ===========================================================================

def test_version_gated_binding_is_conditional(tmp_path):
    (tmp_path / 'pkg').mkdir()
    (tmp_path / 'pkg' / '__init__.py').write_text('', encoding='utf-8')
    (tmp_path / 'pkg' / 'compat.py').write_text('def helper(): pass\n', encoding='utf-8')
    (tmp_path / 'pkg' / 'main.py').write_text(
        'import sys\n'
        'if sys.version_info >= (3, 11):\n'
        '    from pkg.compat import helper\n',
        encoding='utf-8',
    )
    d, _, r, _ = _run(tmp_path)
    b = r.bindings.get(('pkg.main', 'helper'))
    assert isinstance(b, ResolvedBinding)
    assert b.is_conditional is True


def test_normal_import_not_conditional(tmp_path):
    (tmp_path / 'pkg').mkdir()
    (tmp_path / 'pkg' / '__init__.py').write_text('', encoding='utf-8')
    (tmp_path / 'pkg' / 'compat.py').write_text('def helper(): pass\n', encoding='utf-8')
    (tmp_path / 'pkg' / 'main.py').write_text(
        'from pkg.compat import helper\n', encoding='utf-8'
    )
    d, _, r, _ = _run(tmp_path)
    b = r.bindings.get(('pkg.main', 'helper'))
    assert isinstance(b, ResolvedBinding)
    assert b.is_conditional is False


def test_both_branches_resolved(tmp_path):
    (tmp_path / 'pkg').mkdir()
    (tmp_path / 'pkg' / '__init__.py').write_text('', encoding='utf-8')
    (tmp_path / 'pkg' / 'new.py').write_text('def fn(): pass\n', encoding='utf-8')
    (tmp_path / 'pkg' / 'old.py').write_text('def fn(): pass\n', encoding='utf-8')
    (tmp_path / 'pkg' / 'main.py').write_text(
        'import sys\n'
        'if sys.version_info >= (3, 11):\n'
        '    from pkg.new import fn\n'
        'else:\n'
        '    from pkg.old import fn\n',
        encoding='utf-8',
    )
    d, _, r, _ = _run(tmp_path)
    # Both branches declare 'fn'; last import wins for the binding key
    b = r.bindings.get(('pkg.main', 'fn'))
    assert isinstance(b, ResolvedBinding)
    assert b.is_conditional is True


def test_version_gated_does_not_affect_is_type_only(tmp_path):
    (tmp_path / 'pkg').mkdir()
    (tmp_path / 'pkg' / '__init__.py').write_text('', encoding='utf-8')
    (tmp_path / 'pkg' / 'compat.py').write_text('def helper(): pass\n', encoding='utf-8')
    (tmp_path / 'pkg' / 'main.py').write_text(
        'import sys\n'
        'if sys.version_info >= (3, 11):\n'
        '    from pkg.compat import helper\n',
        encoding='utf-8',
    )
    d, _, r, _ = _run(tmp_path)
    b = r.bindings.get(('pkg.main', 'helper'))
    assert isinstance(b, ResolvedBinding)
    assert b.is_type_only is False   # version-gated ≠ type-only
