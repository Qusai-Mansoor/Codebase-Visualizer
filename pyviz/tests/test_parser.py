"""Tests for pyviz/engine/parser.py — Phase 3 verification."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pyviz.engine.discovery import discover
from pyviz.engine.parser import parse_all, _read_source
from pyviz.models import ParseResult, ParsedModule

FIXTURES = Path(__file__).parent / 'fixtures'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _discover_and_parse(root: Path) -> ParseResult:
    return parse_all(discover(root))


# pytest fixture that parses the whole fixtures dir once per session
import pytest as _pytest

@_pytest.fixture(scope='session')
def fixtures_parse_result():
    return _discover_and_parse(FIXTURES)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

def test_parse_all_returns_parse_result(tmp_path):
    (tmp_path / 'mod.py').write_text('x = 1\n', encoding='utf-8')
    result = _discover_and_parse(tmp_path)
    assert isinstance(result, ParseResult)


def test_parse_result_has_parsed_and_failed_dicts(tmp_path):
    (tmp_path / 'mod.py').write_text('x = 1\n', encoding='utf-8')
    result = _discover_and_parse(tmp_path)
    assert isinstance(result.parsed, dict)
    assert isinstance(result.failed, dict)


# ---------------------------------------------------------------------------
# Valid module — basic fields
# Discover from FIXTURES so dotted names include the package prefix.
# ---------------------------------------------------------------------------

def test_valid_module_in_parsed(fixtures_parse_result):
    assert 'parse_suite.valid_module' in fixtures_parse_result.parsed


def test_valid_module_not_in_failed(fixtures_parse_result):
    assert 'parse_suite.valid_module' not in fixtures_parse_result.failed


def test_parsed_module_is_parsed_module_instance(fixtures_parse_result):
    assert isinstance(fixtures_parse_result.parsed['parse_suite.valid_module'], ParsedModule)


def test_parsed_module_name_field(fixtures_parse_result):
    pm = fixtures_parse_result.parsed['parse_suite.valid_module']
    assert pm.module_name == 'parse_suite.valid_module'


def test_parsed_module_file_field_is_absolute_path(fixtures_parse_result):
    pm = fixtures_parse_result.parsed['parse_suite.valid_module']
    assert isinstance(pm.file, Path)
    assert pm.file.is_absolute()
    assert pm.file.name == 'valid_module.py'


def test_parsed_module_source_field_is_str(fixtures_parse_result):
    pm = fixtures_parse_result.parsed['parse_suite.valid_module']
    assert isinstance(pm.source, str)
    assert 'greet' in pm.source


def test_parsed_module_tree_is_ast_module(fixtures_parse_result):
    pm = fixtures_parse_result.parsed['parse_suite.valid_module']
    assert isinstance(pm.tree, ast.Module)


def test_parsed_module_encoding_is_utf8_for_ascii_file(fixtures_parse_result):
    pm = fixtures_parse_result.parsed['parse_suite.valid_module']
    assert pm.encoding == 'utf-8'


# ---------------------------------------------------------------------------
# Empty file — must be in parsed, not failed
# ---------------------------------------------------------------------------

def test_empty_file_is_parsed_not_failed(fixtures_parse_result):
    assert 'parse_suite.empty_module' in fixtures_parse_result.parsed
    assert 'parse_suite.empty_module' not in fixtures_parse_result.failed


def test_empty_file_tree_is_ast_module(fixtures_parse_result):
    pm = fixtures_parse_result.parsed['parse_suite.empty_module']
    assert isinstance(pm.tree, ast.Module)


def test_empty_file_tree_body_is_empty_list(fixtures_parse_result):
    pm = fixtures_parse_result.parsed['parse_suite.empty_module']
    assert pm.tree.body == []


def test_empty_file_source_is_empty_string(fixtures_parse_result):
    pm = fixtures_parse_result.parsed['parse_suite.empty_module']
    assert pm.source == ''


# ---------------------------------------------------------------------------
# SyntaxError — goes to failed, not parsed
# ---------------------------------------------------------------------------

def test_syntax_error_file_goes_to_failed(tmp_path):
    bad = tmp_path / 'bad.py'
    bad.write_text('def broken(\n    x = =\n)\n', encoding='utf-8')
    result = _discover_and_parse(tmp_path)
    assert 'bad' in result.failed
    assert 'bad' not in result.parsed


def test_syntax_error_message_contains_syntax_error(tmp_path):
    bad = tmp_path / 'bad.py'
    bad.write_text('def broken(\n    x = =\n)\n', encoding='utf-8')
    result = _discover_and_parse(tmp_path)
    assert 'SyntaxError' in result.failed['bad']


def test_syntax_error_message_contains_line_number(tmp_path):
    bad = tmp_path / 'bad.py'
    bad.write_text('def broken(\n    x = =\n)\n', encoding='utf-8')
    result = _discover_and_parse(tmp_path)
    msg = result.failed['bad']
    assert 'line' in msg.lower()


def test_one_bad_file_does_not_prevent_other_modules(tmp_path):
    (tmp_path / 'good.py').write_text('x = 1\n', encoding='utf-8')
    (tmp_path / 'bad.py').write_text('def broken( x = =\n', encoding='utf-8')
    result = _discover_and_parse(tmp_path)
    assert 'good' in result.parsed
    assert 'bad' in result.failed


# ---------------------------------------------------------------------------
# Encoding fallback — latin-1 files
# ---------------------------------------------------------------------------

def test_latin1_file_parsed_with_fallback_encoding(tmp_path):
    latin1 = tmp_path / 'latin1_mod.py'
    # \xe9 is 'é' in latin-1 but invalid in UTF-8
    latin1.write_bytes(b'# caf\xe9\nx = 1\n')
    result = _discover_and_parse(tmp_path)
    assert 'latin1_mod' in result.parsed


def test_latin1_file_encoding_field_is_latin1(tmp_path):
    latin1 = tmp_path / 'latin1_mod.py'
    latin1.write_bytes(b'# caf\xe9\nx = 1\n')
    result = _discover_and_parse(tmp_path)
    pm = result.parsed['latin1_mod']
    assert pm.encoding == 'latin-1'


# ---------------------------------------------------------------------------
# ast.fix_missing_locations — all statement nodes have line numbers
# ---------------------------------------------------------------------------

def test_fix_missing_locations_applied(tmp_path):
    mod = tmp_path / 'mymod.py'
    mod.write_text('def foo():\n    pass\n', encoding='utf-8')
    result = _discover_and_parse(tmp_path)
    pm = result.parsed['mymod']
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.stmt):
            assert hasattr(node, 'lineno'), f'{type(node).__name__} missing lineno'


# ---------------------------------------------------------------------------
# _read_source helper
# ---------------------------------------------------------------------------

def test_read_source_utf8(tmp_path):
    f = tmp_path / 'f.py'
    f.write_text('x = 1\n', encoding='utf-8')
    src, enc = _read_source(f)
    assert src == 'x = 1\n'
    assert enc == 'utf-8'


def test_read_source_latin1_fallback(tmp_path):
    f = tmp_path / 'f.py'
    f.write_bytes(b'# caf\xe9\nx = 1\n')
    src, enc = _read_source(f)
    assert enc == 'latin-1'
    assert 'x = 1' in src


# ---------------------------------------------------------------------------
# All modules in module_map are attempted
# ---------------------------------------------------------------------------

def test_all_modules_attempted(tmp_path):
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    (pkg / 'a.py').write_text('a = 1\n', encoding='utf-8')
    (pkg / 'b.py').write_text('b = 2\n', encoding='utf-8')
    result = _discover_and_parse(tmp_path)
    all_keys = set(result.parsed) | set(result.failed)
    assert {'pkg', 'pkg.a', 'pkg.b'} <= all_keys


# ---------------------------------------------------------------------------
# ParseResult independence — two separate calls don't share dicts
# ---------------------------------------------------------------------------

def test_two_parse_results_are_independent(tmp_path):
    (tmp_path / 'x.py').write_text('x = 1\n', encoding='utf-8')
    r1 = _discover_and_parse(tmp_path)
    r2 = _discover_and_parse(tmp_path)
    assert r1.parsed is not r2.parsed
    assert r1.failed is not r2.failed
