"""Tests for pyviz/engine/resolver.py — Phase 4 verification."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pyviz.engine.discovery import discover
from pyviz.engine.parser import parse_all
from pyviz.engine.resolver import (
    resolve_all,
    _follow_chain,
    _resolve_relative,
    _get_exported_names,
    _get_type_checking_ranges,
)
from pyviz.models import ResolverResult, ResolvedBinding, UnresolvedBinding
import ast

FIXTURES = Path(__file__).parent / 'fixtures'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(root: Path):
    d = discover(root)
    p = parse_all(d)
    return resolve_all(d, p)


# Session-scoped parse of the whole fixtures directory (reused across tests).
@pytest.fixture(scope='session')
def fixtures_result():
    return _run(FIXTURES)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

def test_resolve_all_returns_resolver_result(tmp_path):
    (tmp_path / 'mod.py').write_text('x = 1\n', encoding='utf-8')
    result = _run(tmp_path)
    assert isinstance(result, ResolverResult)


def test_resolver_result_bindings_is_dict(tmp_path):
    (tmp_path / 'mod.py').write_text('import os\n', encoding='utf-8')
    result = _run(tmp_path)
    assert isinstance(result.bindings, dict)


def test_resolver_result_warnings_is_list(tmp_path):
    (tmp_path / 'mod.py').write_text('import os\n', encoding='utf-8')
    result = _run(tmp_path)
    assert isinstance(result.warnings, list)


def test_binding_keys_are_2_tuples(tmp_path):
    (tmp_path / 'mod.py').write_text('import os\n', encoding='utf-8')
    result = _run(tmp_path)
    for k in result.bindings:
        assert isinstance(k, tuple) and len(k) == 2


# ---------------------------------------------------------------------------
# __init__.py re-export chain — the headline correctness test
# ---------------------------------------------------------------------------

def test_reexport_thing_resolves_to_core_module(fixtures_result):
    # 'reexport_pkg' imports 'Thing' from .core via __init__.py
    key = ('reexport_pkg', 'Thing')
    assert key in fixtures_result.bindings
    binding = fixtures_result.bindings[key]
    assert isinstance(binding, ResolvedBinding)
    assert binding.real_module == 'reexport_pkg.core'


def test_reexport_thing_points_at_core_py_file(fixtures_result):
    binding = fixtures_result.bindings[('reexport_pkg', 'Thing')]
    assert isinstance(binding, ResolvedBinding)
    assert binding.real_file.name == 'core.py'


def test_reexport_thing_real_line_is_class_definition(fixtures_result):
    binding = fixtures_result.bindings[('reexport_pkg', 'Thing')]
    assert isinstance(binding, ResolvedBinding)
    # class Thing: pass is on line 1 of core.py
    assert binding.real_line == 1


def test_reexport_thing_not_pointing_at_init(fixtures_result):
    binding = fixtures_result.bindings[('reexport_pkg', 'Thing')]
    assert isinstance(binding, ResolvedBinding)
    assert '__init__' not in binding.real_file.name


def test_reexport_fqn_is_correct(fixtures_result):
    binding = fixtures_result.bindings[('reexport_pkg', 'Thing')]
    assert isinstance(binding, ResolvedBinding)
    assert binding.real_fqn == 'reexport_pkg.core.Thing'


# ---------------------------------------------------------------------------
# TYPE_CHECKING imports
# ---------------------------------------------------------------------------

def test_type_checking_import_is_type_only(tmp_path):
    # Use an internal import under TYPE_CHECKING so the binding is a ResolvedBinding
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text(
        'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from pkg.sub import MyClass\n',
        encoding='utf-8',
    )
    (pkg / 'sub.py').write_text('class MyClass:\n    pass\n', encoding='utf-8')
    result = _run(tmp_path)
    key = ('pkg', 'MyClass')
    assert key in result.bindings
    binding = result.bindings[key]
    assert isinstance(binding, ResolvedBinding)
    assert binding.is_type_only is True


def test_non_type_checking_import_not_type_only(tmp_path):
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('from pkg.sub import MyClass\n', encoding='utf-8')
    (pkg / 'sub.py').write_text('class MyClass:\n    pass\n', encoding='utf-8')
    result = _run(tmp_path)
    key = ('pkg', 'MyClass')
    assert key in result.bindings
    binding = result.bindings[key]
    assert isinstance(binding, ResolvedBinding)
    assert binding.is_type_only is False


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

def test_circular_imports_produce_cycle_binding(fixtures_result):
    # circular_import_a and circular_import_b each import from the other
    cycle_bindings = [
        b for b in fixtures_result.bindings.values()
        if isinstance(b, UnresolvedBinding) and b.reason == 'cycle'
    ]
    assert len(cycle_bindings) >= 1


# ---------------------------------------------------------------------------
# External imports
# ---------------------------------------------------------------------------

def test_external_import_produces_unresolved_external(tmp_path):
    (tmp_path / 'mod.py').write_text('import os\n', encoding='utf-8')
    result = _run(tmp_path)
    key = ('mod', 'os')
    assert key in result.bindings
    assert isinstance(result.bindings[key], UnresolvedBinding)
    assert result.bindings[key].reason == 'external'


def test_external_import_produces_warning(tmp_path):
    (tmp_path / 'mod.py').write_text('import os\n', encoding='utf-8')
    result = _run(tmp_path)
    assert len(result.warnings) >= 1


# ---------------------------------------------------------------------------
# Wildcard imports and __all__
# ---------------------------------------------------------------------------

def test_wildcard_with_all_resolves_listed_names(fixtures_result):
    # allexport_pkg/__init__.py is empty; tests use tmp_path for wildcard
    pass  # See tmp_path wildcard tests below


def test_wildcard_only_resolves_all_exports(tmp_path):
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('from pkg.utils import *\n', encoding='utf-8')
    (pkg / 'utils.py').write_text(
        "__all__ = ['foo']\n\ndef foo(): pass\n\ndef bar(): pass\n",
        encoding='utf-8',
    )
    result = _run(tmp_path)
    assert ('pkg', 'foo') in result.bindings
    assert ('pkg', 'bar') not in result.bindings


def test_wildcard_binding_has_is_wildcard_true(tmp_path):
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('from pkg.utils import *\n', encoding='utf-8')
    (pkg / 'utils.py').write_text(
        "__all__ = ['foo']\ndef foo(): pass\n",
        encoding='utf-8',
    )
    result = _run(tmp_path)
    binding = result.bindings.get(('pkg', 'foo'))
    assert isinstance(binding, ResolvedBinding)
    assert binding.is_wildcard is True


def test_no_all_wildcard_exports_public_names(tmp_path):
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('from pkg.utils import *\n', encoding='utf-8')
    (pkg / 'utils.py').write_text(
        'def pub(): pass\ndef _priv(): pass\n',
        encoding='utf-8',
    )
    result = _run(tmp_path)
    assert ('pkg', 'pub') in result.bindings
    assert ('pkg', '_priv') not in result.bindings


# ---------------------------------------------------------------------------
# _resolve_relative unit tests
# ---------------------------------------------------------------------------

def _make_import_from(level, module):
    node = ast.ImportFrom(module=module, names=[], level=level)
    return node


def test_resolve_relative_level0_returns_module():
    node = _make_import_from(0, 'foo.bar')
    assert _resolve_relative(node, 'mypkg.mod') == 'foo.bar'


def test_resolve_relative_level1_same_package():
    node = _make_import_from(1, 'core')
    assert _resolve_relative(node, 'mypkg.mod') == 'mypkg.core'


def test_resolve_relative_level1_no_module():
    node = _make_import_from(1, None)
    assert _resolve_relative(node, 'mypkg.mod') == 'mypkg'


def test_resolve_relative_level2_parent_package():
    node = _make_import_from(2, 'utils')
    assert _resolve_relative(node, 'mypkg.sub.mod') == 'mypkg.utils'


def test_resolve_relative_level1_from_init_package():
    # __init__.py: from .core import X — is_package=True
    node = _make_import_from(1, 'core')
    assert _resolve_relative(node, 'mypkg', is_package=True) == 'mypkg.core'


# ---------------------------------------------------------------------------
# _get_exported_names unit tests
# ---------------------------------------------------------------------------

def test_get_exported_names_with_all(tmp_path):
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    (pkg / 'utils.py').write_text(
        "__all__ = ['foo', 'bar']\ndef foo(): pass\ndef bar(): pass\ndef _priv(): pass\n",
        encoding='utf-8',
    )
    d = discover(tmp_path)
    p = parse_all(d)
    names = _get_exported_names('pkg.utils', p)
    assert set(names) == {'foo', 'bar'}


def test_get_exported_names_without_all(tmp_path):
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    (pkg / 'utils.py').write_text(
        'def pub(): pass\ndef _priv(): pass\nx = 1\n',
        encoding='utf-8',
    )
    d = discover(tmp_path)
    p = parse_all(d)
    names = _get_exported_names('pkg.utils', p)
    assert 'pub' in names
    assert 'x' in names
    assert '_priv' not in names


# ---------------------------------------------------------------------------
# Independence
# ---------------------------------------------------------------------------

def test_two_resolver_results_are_independent(tmp_path):
    (tmp_path / 'mod.py').write_text('import os\n', encoding='utf-8')
    r1 = _run(tmp_path)
    r2 = _run(tmp_path)
    assert r1.bindings is not r2.bindings
    assert r1.warnings is not r2.warnings
