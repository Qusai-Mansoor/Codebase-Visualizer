"""Phase 13 — CLI tests.

Exercises the Typer CLI via CliRunner against local fixtures (no network).
The --url clone path is covered by manual smoke testing, not here.
"""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from pyviz.cli import _render_viewer, app

runner = CliRunner()

FIXTURES = Path(__file__).parent / 'fixtures'
SIMPLE_PKG = FIXTURES / 'simple_pkg'


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------

def test_version_exits_zero():
    result = runner.invoke(app, ['version'])
    assert result.exit_code == 0


def test_version_prints_version_string():
    from pyviz import __version__
    result = runner.invoke(app, ['version'])
    assert __version__ in result.stdout


# ---------------------------------------------------------------------------
# analyze — happy path
# ---------------------------------------------------------------------------

def test_analyze_writes_valid_json(tmp_path):
    out = tmp_path / 'graph.json'
    result = runner.invoke(app, ['analyze', str(SIMPLE_PKG), '-o', str(out)])
    assert result.exit_code == 0, result.stdout
    assert out.exists()
    data = json.loads(out.read_text(encoding='utf-8'))
    assert 'nodes' in data and 'edges' in data and 'meta' in data


def test_analyze_contains_expected_node(tmp_path):
    out = tmp_path / 'graph.json'
    runner.invoke(app, ['analyze', str(SIMPLE_PKG), '-o', str(out)])
    data = json.loads(out.read_text(encoding='utf-8'))
    ids = {n['id'] for n in data['nodes']}
    # Analyzing the package dir directly roots there, so the FQN is 'core.add'
    assert 'core.add' in ids


def test_analyze_quiet_prints_output_path(tmp_path):
    out = tmp_path / 'graph.json'
    result = runner.invoke(app, ['analyze', str(SIMPLE_PKG), '-o', str(out), '--quiet'])
    assert result.exit_code == 0
    assert out.exists()
    # Quiet mode prints just the path, not the summary table
    assert 'Analysis Summary' not in result.stdout


def test_analyze_compact_is_single_line(tmp_path):
    out = tmp_path / 'graph.json'
    result = runner.invoke(app, ['analyze', str(SIMPLE_PKG), '-o', str(out), '--compact'])
    assert result.exit_code == 0
    text = out.read_text(encoding='utf-8')
    assert '\n' not in text.strip()      # compact = no newlines inside the JSON
    assert json.loads(text)              # still valid JSON


# ---------------------------------------------------------------------------
# analyze — validation / error paths
# ---------------------------------------------------------------------------

def test_analyze_no_path_no_url_errors():
    result = runner.invoke(app, ['analyze'])
    assert result.exit_code == 1


def test_analyze_both_path_and_url_errors():
    result = runner.invoke(app, ['analyze', str(SIMPLE_PKG), '--url', 'https://example.com/x.git'])
    assert result.exit_code == 1


def test_analyze_nonexistent_dir_errors(tmp_path):
    missing = tmp_path / 'does_not_exist'
    result = runner.invoke(app, ['analyze', str(missing)])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# serve — validation + viewer rendering
# ---------------------------------------------------------------------------

def test_serve_missing_file_errors(tmp_path):
    result = runner.invoke(app, ['serve', str(tmp_path / 'nope.json')])
    assert result.exit_code == 1


def test_render_viewer_injects_graph_data(tmp_path):
    # Produce a real graph first
    out = tmp_path / 'graph.json'
    runner.invoke(app, ['analyze', str(SIMPLE_PKG), '-o', str(out)])
    rendered = _render_viewer(out)
    assert '__GRAPH_DATA__' not in rendered      # placeholder replaced
    assert 'core.add' in rendered                # graph content injected
    assert 'cytoscape' in rendered               # viewer scaffolding present


def test_render_viewer_escapes_script_breakout(tmp_path):
    """A malicious analyzed repo must not break out of the <script> tag (stored XSS)."""
    payload = {
        'nodes': [{
            'id': 'x', 'name': 'x', 'kind': 'function',
            'file': None, 'line': None, 'end_line': None,
            'docstring': '</script><script>alert(1)</script>',
            'is_async': False, 'is_abstract': False, 'is_protocol': False,
            'is_dataclass': False, 'is_mixin': False,
            'bases': [], 'decorators': [], 'warnings': [],
            'community': None, 'role': None,
        }],
        'edges': [], 'meta': {},
    }
    gf = tmp_path / 'mal.json'
    gf.write_text(json.dumps(payload), encoding='utf-8')
    rendered = _render_viewer(gf)
    # The literal closing-tag sequence must be neutralized to '<\/'
    assert '</script><script>alert(1)</script>' not in rendered
    assert '<\\/script>' in rendered
