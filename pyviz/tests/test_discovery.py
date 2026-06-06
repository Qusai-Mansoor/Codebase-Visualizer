"""Tests for pyviz/engine/discovery.py — Phase 2 verification."""
from pathlib import Path

import pytest

from pyviz.engine.discovery import SKIP_DIRS, MAX_FILE_BYTES, discover
from pyviz.models import DiscoveryResult

FIXTURES = Path(__file__).parent / 'fixtures'


# ---------------------------------------------------------------------------
# Baseline — simple_pkg (has __init__.py + core.py)
# Discover from the FIXTURES parent so dotted names include the package name.
# ---------------------------------------------------------------------------

def test_discover_returns_discovery_result():
    result = discover(FIXTURES)
    assert isinstance(result, DiscoveryResult)


def test_simple_pkg_module_map_contains_package():
    result = discover(FIXTURES)
    assert 'simple_pkg' in result.module_map


def test_simple_pkg_module_map_contains_submodule():
    result = discover(FIXTURES)
    assert 'simple_pkg.core' in result.module_map


def test_simple_pkg_package_map_contains_package():
    result = discover(FIXTURES)
    assert 'simple_pkg' in result.package_map


def test_simple_pkg_no_skipped_files():
    # Discover just the simple_pkg subtree via tmp_path to avoid noise from siblings
    import shutil, tempfile
    with tempfile.TemporaryDirectory() as td:
        shutil.copytree(FIXTURES / 'simple_pkg', Path(td) / 'simple_pkg')
        result = discover(Path(td))
    assert result.skipped == {}


def test_simple_pkg_submodule_path_is_absolute():
    result = discover(FIXTURES)
    p = result.module_map['simple_pkg.core']
    assert p.is_absolute()
    assert p.name == 'core.py'


# ---------------------------------------------------------------------------
# Package alias — __init__.py registered under the package name
# ---------------------------------------------------------------------------

def test_init_py_registered_under_package_dotted_name():
    result = discover(FIXTURES)
    init_path = result.module_map['simple_pkg']
    assert init_path.name == '__init__.py'


def test_package_map_points_at_directory():
    result = discover(FIXTURES)
    pkg_dir = result.package_map['simple_pkg']
    assert pkg_dir.is_dir()


# ---------------------------------------------------------------------------
# Skip directories
# ---------------------------------------------------------------------------

def test_skip_venv_directory(tmp_path):
    (tmp_path / '.venv' / 'lib').mkdir(parents=True)
    victim = tmp_path / '.venv' / 'lib' / 'foo.py'
    victim.write_text('x = 1\n', encoding='utf-8')
    result = discover(tmp_path)
    assert victim in result.skipped
    assert 'skip' in result.skipped[victim]


def test_skip_build_directory(tmp_path):
    (tmp_path / 'build').mkdir()
    victim = tmp_path / 'build' / 'bar.py'
    victim.write_text('x = 1\n', encoding='utf-8')
    result = discover(tmp_path)
    assert victim in result.skipped


def test_skip_egg_info_directory(tmp_path):
    (tmp_path / 'mypkg.egg-info').mkdir()
    victim = tmp_path / 'mypkg.egg-info' / 'sources.py'
    victim.write_text('x = 1\n', encoding='utf-8')
    result = discover(tmp_path)
    assert victim in result.skipped


def test_skip_dirs_constant_is_populated():
    # Spot-check that the known skip dirs are present
    for d in ('.git', '.venv', 'venv', '__pycache__', 'node_modules', 'build'):
        assert d in SKIP_DIRS


def test_normal_file_not_skipped(tmp_path):
    pkg = tmp_path / 'mypkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    (pkg / 'mod.py').write_text('x = 1\n', encoding='utf-8')
    result = discover(tmp_path)
    assert result.skipped == {}
    assert 'mypkg.mod' in result.module_map


# ---------------------------------------------------------------------------
# Large file skip
# ---------------------------------------------------------------------------

def test_large_file_skipped(tmp_path):
    big = tmp_path / 'big.py'
    big.write_bytes(b'x = 1\n' * ((MAX_FILE_BYTES // 6) + 1))
    result = discover(tmp_path)
    assert big in result.skipped
    assert 'too large' in result.skipped[big]


def test_file_just_under_limit_not_skipped(tmp_path):
    ok = tmp_path / 'ok.py'
    ok.write_bytes(b'x = 1\n' * ((MAX_FILE_BYTES // 6) - 1))
    result = discover(tmp_path)
    assert ok not in result.skipped


# ---------------------------------------------------------------------------
# Namespace packages (no __init__.py)
# Discover from FIXTURES so dotted names include the namespace_pkg prefix.
# ---------------------------------------------------------------------------

def test_namespace_pkg_module_in_module_map():
    result = discover(FIXTURES)
    assert 'namespace_pkg.utils' in result.module_map


def test_namespace_pkg_inferred_in_package_map():
    result = discover(FIXTURES)
    assert 'namespace_pkg' in result.package_map


def test_namespace_pkg_no_init_in_module_map():
    result = discover(FIXTURES)
    # There is no __init__.py, so 'namespace_pkg' should NOT be in module_map
    # (it would be there only if an __init__.py existed)
    assert 'namespace_pkg' not in result.module_map


# ---------------------------------------------------------------------------
# src-layout detection
# ---------------------------------------------------------------------------

def test_src_layout_uses_src_as_base(tmp_path):
    src = tmp_path / 'src'
    pkg = src / 'mypkg'
    pkg.mkdir(parents=True)
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    (pkg / 'mod.py').write_text('x = 1\n', encoding='utf-8')
    result = discover(tmp_path)
    assert 'mypkg' in result.module_map
    assert 'mypkg.mod' in result.module_map


def test_src_layout_no_src_prefix_in_dotted_name(tmp_path):
    src = tmp_path / 'src'
    pkg = src / 'mypkg'
    pkg.mkdir(parents=True)
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    result = discover(tmp_path)
    assert 'src.mypkg' not in result.module_map


def test_non_src_layout_unchanged(tmp_path):
    pkg = tmp_path / 'mypkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    result = discover(tmp_path)
    assert 'mypkg' in result.module_map


# ---------------------------------------------------------------------------
# Stub file collection (.pyi)
# ---------------------------------------------------------------------------

def test_pyi_stub_collected_in_stub_map(tmp_path):
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    (pkg / 'mod.py').write_text('def foo(): pass\n', encoding='utf-8')
    (pkg / 'mod.pyi').write_text('def foo() -> None: ...\n', encoding='utf-8')
    result = discover(tmp_path)
    assert 'pkg.mod' in result.stub_map
    assert result.stub_map['pkg.mod'].suffix == '.pyi'


def test_pyi_without_py_also_collected(tmp_path):
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    (pkg / 'types.pyi').write_text('X: int\n', encoding='utf-8')
    result = discover(tmp_path)
    assert 'pkg.types' in result.stub_map


def test_no_stubs_gives_empty_stub_map(tmp_path):
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    result = discover(tmp_path)
    assert result.stub_map == {}


# ---------------------------------------------------------------------------
# DiscoveryResult.root is always the original root (not src/)
# ---------------------------------------------------------------------------

def test_root_is_original_root_not_src(tmp_path):
    src = tmp_path / 'src'
    pkg = src / 'mypkg'
    pkg.mkdir(parents=True)
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    result = discover(tmp_path)
    assert result.root == tmp_path.resolve()
