"""pyviz CLI — Typer + Rich wrapper around the analysis engine.

Commands:
  pyviz analyze <path>            Analyze a local directory, write graph.json
  pyviz analyze --url <github>    Clone and analyze a GitHub repo
  pyviz analyze <path> --trace    Static analysis + runtime tracing on the test suite
  pyviz serve <graph.json>        Open a local bundled HTML viewer
  pyviz version                   Print the installed version

This is a thin wrapper: it reconciles the engine's real phase signatures and
serializes the result to the JSON contract consumed by the viewer/frontend.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from pyviz.engine import (
    calls,
    decorators,
    definitions,
    discovery,
    parser,
    resolver,
    serializer,
)
from pyviz.engine import graph as graph_mod
from pyviz.models import ProjectGraph

app = typer.Typer(
    name='pyviz',
    help='Python Codebase Visualizer — analyze and explore Python projects as graphs.',
    add_completion=False,
    rich_markup_mode='rich',
)
console = Console()


# ─── commands ──────────────────────────────────────────────────────

@app.command()
def analyze(
    path: Optional[Path] = typer.Argument(
        None, help='Local path to a Python project'
    ),
    url: Optional[str] = typer.Option(
        None, '--url', '-u', help='GitHub URL to clone and analyze'
    ),
    output: Path = typer.Option(
        Path('graph.json'), '--output', '-o', help='Output JSON file'
    ),
    trace: bool = typer.Option(
        False, '--trace', help='Also run runtime tracing on the test suite'
    ),
    quiet: bool = typer.Option(
        False, '--quiet', '-q', help='Suppress progress output'
    ),
    compact: bool = typer.Option(
        False, '--compact', help='Write compact (non-indented) JSON'
    ),
):
    """Analyze a Python codebase and produce a graph JSON."""
    if not path and not url:
        console.print('[red]Error:[/red] provide either a path or --url')
        raise typer.Exit(1)
    if path and url:
        console.print('[red]Error:[/red] provide path OR --url, not both')
        raise typer.Exit(1)

    cleanup_dir: Optional[Path] = None
    if url:
        target = _clone_repo(url)
        cleanup_dir = target
    else:
        target = path.resolve()
        if not target.is_dir():
            console.print(f'[red]Error:[/red] {target} is not a directory')
            raise typer.Exit(1)

    try:
        g, ar, root = _run_pipeline(target, trace=trace, quiet=quiet)
        raw = serializer.serialize(g, ar.graph, ar.communities, ar.unused, ar.cycles, root)
        if compact:
            raw = json.dumps(json.loads(raw), separators=(',', ':'))
        output.write_text(raw, encoding='utf-8')
        if not quiet:
            _print_summary(g, output)
        else:
            console.print(str(output))
    except KeyboardInterrupt:
        console.print('\n[yellow]Cancelled[/yellow]')
        raise typer.Exit(130)
    finally:
        if cleanup_dir and cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)


@app.command()
def serve(
    graph_file: Path = typer.Argument(..., help='Path to a graph.json'),
    port: int = typer.Option(8765, '--port', '-p'),
):
    """Open a local browser viewer for a previously generated graph."""
    if not graph_file.exists():
        console.print(f'[red]Error:[/red] {graph_file} does not exist')
        raise typer.Exit(1)
    _serve_local_viewer(graph_file, port)


@app.command()
def version():
    """Print version info."""
    from pyviz import __version__
    console.print(f'[bold cyan]pyviz[/bold cyan] version [green]{__version__}[/green]')


# ─── internal helpers ──────────────────────────────────────────────

def _run_pipeline(root: Path, *, trace: bool, quiet: bool):
    """Run the full engine pipeline. Returns (ProjectGraph, GraphAssemblyResult, root)."""
    if quiet:
        return _run_pipeline_quiet(root, trace=trace)

    with Progress(
        SpinnerColumn(),
        TextColumn('[progress.description]{task.description}'),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        steps = 8 if trace else 7
        t = progress.add_task('Discovering files...', total=steps)

        disc = discovery.discover(root)
        progress.update(t, advance=1, description='Parsing modules...')

        parsed = parser.parse_all(disc)
        progress.update(t, advance=1, description='Resolving imports...')

        resolved = resolver.resolve_all(disc, parsed)
        progress.update(t, advance=1, description='Extracting definitions...')

        g = ProjectGraph()
        definitions.extract_all(parsed, resolved, g, disc)
        progress.update(t, advance=1, description='Extracting calls...')

        calls.extract_all(parsed, resolved, g, disc)
        progress.update(t, advance=1, description='Processing decorators...')

        decorators.extract_all(parsed, resolved, g, disc)
        progress.update(t, advance=1, description='Assembling graph...')

        ar = graph_mod.assemble(g, disc)
        progress.update(t, advance=1, description='Done')

        if trace:
            progress.update(t, description='Running tracer...')
            from pyviz.engine import tracer
            tracer.trace_test_suite(root, disc, g)
            ar = graph_mod.assemble(g, disc)  # re-assemble to pick up runtime edges
            progress.update(t, advance=1, description='Done')

    return g, ar, root


def _run_pipeline_quiet(root: Path, *, trace: bool):
    disc = discovery.discover(root)
    parsed = parser.parse_all(disc)
    resolved = resolver.resolve_all(disc, parsed)
    g = ProjectGraph()
    definitions.extract_all(parsed, resolved, g, disc)
    calls.extract_all(parsed, resolved, g, disc)
    decorators.extract_all(parsed, resolved, g, disc)
    ar = graph_mod.assemble(g, disc)
    if trace:
        from pyviz.engine import tracer
        tracer.trace_test_suite(root, disc, g)
        ar = graph_mod.assemble(g, disc)
    return g, ar, root


def _clone_repo(url: str) -> Path:
    try:
        import git  # gitpython
    except ImportError:
        console.print(
            '[red]Error:[/red] gitpython is not installed (and the git binary must be on PATH). '
            'Install with [bold]pip install gitpython[/bold].'
        )
        raise typer.Exit(1)

    temp = Path(tempfile.mkdtemp(prefix='pyviz_'))
    console.print(f'Cloning [cyan]{url}[/cyan] into {temp}...')
    try:
        git.Repo.clone_from(url, temp, depth=1)
        return temp
    except Exception as e:
        shutil.rmtree(temp, ignore_errors=True)
        console.print(f'[red]Clone failed:[/red] {e}')
        raise typer.Exit(1)


def _print_summary(g: ProjectGraph, output: Path):
    table = Table(title='Analysis Summary', border_style='cyan')
    table.add_column('Metric', style='bold')
    table.add_column('Count', justify='right', style='green')

    by_kind: dict[str, int] = {}
    for n in g.nodes.values():
        by_kind[n.kind.value] = by_kind.get(n.kind.value, 0) + 1

    for kind, count in sorted(by_kind.items()):
        table.add_row(kind, str(count))
    table.add_row('total nodes', str(len(g.nodes)), style='bold')
    table.add_row('total edges', str(len(g.edges)), style='bold')
    table.add_row('warnings', str(len(g.warnings)))

    console.print(table)
    console.print(Panel(
        f'Graph written to [cyan]{output}[/cyan]\n'
        f'Run [bold]pyviz serve {output}[/bold] to open the viewer.',
        title='Done', border_style='green',
    ))


def _render_viewer(graph_file: Path) -> str:
    """Read viewer.html and inject the graph JSON at the __GRAPH_DATA__ placeholder.

    The graph is analyzed from arbitrary (possibly untrusted) repos, so node
    names/docstrings/paths can contain the substring "</script>" or the JS line
    separators U+2028/U+2029. Escaping these prevents a malicious repo from breaking
    out of the <script> tag and executing JS in the viewer (stored XSS).
    """
    viewer_html = (Path(__file__).parent / 'viewer.html').read_text(encoding='utf-8')
    graph_json = graph_file.read_text(encoding='utf-8')
    safe_json = (
        graph_json
        .replace('</', '<\\/')
        .replace(' ', '\u2028')
        .replace(' ', '\u2029')
    )
    return viewer_html.replace('__GRAPH_DATA__', safe_json)


def _serve_local_viewer(graph_file: Path, port: int):
    """Bundled HTML viewer with the graph injected."""
    import http.server
    import socketserver
    import threading
    import webbrowser

    rendered = _render_viewer(graph_file)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/':
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(rendered.encode('utf-8'))
            else:
                self.send_error(404)

        def log_message(self, *args):  # silence
            pass

    with socketserver.TCPServer(('', port), Handler) as httpd:
        url = f'http://localhost:{port}'
        console.print(f'Viewer at [cyan]{url}[/cyan] — Ctrl+C to stop')
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            console.print('\n[yellow]Stopped[/yellow]')


if __name__ == '__main__':
    app()
