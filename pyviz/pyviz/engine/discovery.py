"""Phase 2 — File discovery.

Given a project root, walks all .py (and .pyi) files and builds:
  - module_map:  dotted_name -> absolute Path  (every .py module)
  - package_map: dotted_name -> absolute dir   (every package)
  - stub_map:    dotted_name -> absolute Path  (every .pyi stub)
  - skipped:     absolute Path -> reason       (files that were skipped)

Handles: skip-dirs, large-file limit, __init__.py package aliases,
         src-layout, namespace packages, .pyi stub collection.
"""
from __future__ import annotations

from pathlib import Path

from pyviz.models import DiscoveryResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SKIP_DIRS: frozenset[str] = frozenset({
    '.git', '.venv', 'venv', 'env', '.env',
    '__pycache__', 'node_modules', '.tox',
    'build', 'dist', '.eggs',
    '.mypy_cache', '.pytest_cache', '.ruff_cache',
})

MAX_FILE_BYTES = 2_000_000  # skip files > 2 MB (generated/vendored files)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def discover(root: Path) -> DiscoveryResult:
    """Walk *root* and return a DiscoveryResult with all first-party modules."""
    root = root.resolve()
    scan_base = _detect_src_layout(root)

    module_map: dict[str, Path] = {}
    package_map: dict[str, Path] = {}
    stub_map: dict[str, Path] = {}
    skipped: dict[Path, str] = {}

    _collect_py_files(scan_base, scan_base, module_map, package_map, skipped)
    _collect_pyi_files(scan_base, scan_base, stub_map, skipped)
    _infer_namespace_packages(module_map, package_map, scan_base)

    entry_points = _parse_entry_points(root)

    return DiscoveryResult(
        root=root,
        module_map=module_map,
        package_map=package_map,
        skipped=skipped,
        stub_map=stub_map,
        entry_points=entry_points,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _detect_src_layout(root: Path) -> Path:
    """Return root/src if it looks like a src-layout project, else root."""
    src = root / 'src'
    if not src.is_dir():
        return root
    # src-layout: src/ contains at least one .py file or __init__.py at top level
    for child in src.iterdir():
        if child.suffix == '.py' or (child.is_dir() and (child / '__init__.py').exists()):
            return src
    return root


def _should_skip_path(rel: Path) -> str | None:
    """Return a skip reason string if this relative path is under a skip dir, else None."""
    for part in rel.parts:
        if part in SKIP_DIRS or part.endswith('.egg-info'):
            return 'in skip directory'
    return None


def _collect_py_files(
    scan_base: Path,
    base: Path,
    module_map: dict[str, Path],
    package_map: dict[str, Path],
    skipped: dict[Path, str],
) -> None:
    for py_file in base.rglob('*.py'):
        rel = py_file.relative_to(scan_base)

        skip_reason = _should_skip_path(rel)
        if skip_reason:
            skipped[py_file] = skip_reason
            continue

        try:
            size = py_file.stat().st_size
        except OSError:
            skipped[py_file] = 'stat() failed'
            continue

        if size > MAX_FILE_BYTES:
            skipped[py_file] = f'too large ({size} bytes)'
            continue

        parts = list(rel.parts)
        parts[-1] = parts[-1][:-3]  # strip .py
        dotted = '.'.join(parts)
        module_map[dotted] = py_file

        if parts[-1] == '__init__':
            pkg_dotted = '.'.join(parts[:-1]) if len(parts) > 1 else parts[0]
            package_map[pkg_dotted] = py_file.parent
            module_map[pkg_dotted] = py_file  # 'mypkg' -> mypkg/__init__.py


def _collect_pyi_files(
    scan_base: Path,
    base: Path,
    stub_map: dict[str, Path],
    skipped: dict[Path, str],
) -> None:
    for pyi_file in base.rglob('*.pyi'):
        rel = pyi_file.relative_to(scan_base)

        if _should_skip_path(rel):
            continue  # skip silently — already captured in skipped via .py pass

        parts = list(rel.parts)
        parts[-1] = parts[-1][:-4]  # strip .pyi
        dotted = '.'.join(parts)
        stub_map[dotted] = pyi_file


def _parse_entry_points(root: Path) -> dict[str, str]:
    """Parse pyproject.toml for [project.scripts] and [tool.poetry.scripts] entries.

    Converts 'pkg.mod:fn' → 'pkg.mod.fn' (the callable FQN).
    Returns {} if pyproject.toml is absent, unreadable, or has no scripts section.
    """
    pyproject = root / 'pyproject.toml'
    if not pyproject.is_file():
        return {}
    try:
        try:
            import tomllib          # stdlib on Python 3.11+
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]
        with open(pyproject, 'rb') as f:
            data = tomllib.load(f)
    except Exception:
        return {}
    result: dict[str, str] = {}
    for section in (
        data.get('project', {}).get('scripts', {}),
        data.get('tool', {}).get('poetry', {}).get('scripts', {}),
    ):
        for name, ref in section.items():
            if isinstance(ref, str) and ':' in ref:
                mod, fn = ref.split(':', 1)
                result[name] = f'{mod}.{fn}'
    return result


def _infer_namespace_packages(
    module_map: dict[str, Path],
    package_map: dict[str, Path],
    scan_base: Path,
) -> None:
    """Add package_map entries for namespace packages (no __init__.py)."""
    # Collect all dotted names first to avoid mutating while iterating
    for dotted in list(module_map.keys()):
        parts = dotted.split('.')
        # Walk every prefix of length >= 1 (skip the module itself)
        for depth in range(1, len(parts)):
            prefix = '.'.join(parts[:depth])
            if prefix not in package_map:
                pkg_dir = scan_base.joinpath(*parts[:depth])
                if pkg_dir.is_dir():
                    package_map[prefix] = pkg_dir
